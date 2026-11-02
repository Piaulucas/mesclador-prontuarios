"""Testes do contador com empresas e tarefas fictícias."""

from datetime import datetime

from flask import Flask

from mesclador import horas


def test_totais_repartem_meia_noite_semana_e_mes():
    sessoes = [
        {"tipo": "Auditoria", "inicio": "2026-08-31T23:30:00", "fim": "2026-09-01T00:30:00"},
        {"tipo": "Produtividade", "inicio": "2026-09-01T10:00:00", "fim": "2026-09-01T11:00:00"},
    ]
    totais = horas.calcular_totais(sessoes, datetime(2026, 9, 1, 12))
    for periodo in ("dia", "mes"):
        assert totais[periodo] == {"geral": 5400,
                                   "por_tipo": {"Auditoria": 1800, "Produtividade": 3600}}
    assert totais["semana"] == {"geral": 7200,
                                 "por_tipo": {"Auditoria": 3600, "Produtividade": 3600}}
    totais = horas.calcular_totais(sessoes, datetime(2026, 8, 31, 23, 45))
    assert totais["dia"]["geral"] == 900
    assert totais["semana"]["geral"] == 900
    assert totais["mes"]["geral"] == 900


def test_sessao_aberta_conta_ate_relogio_injetado(config):
    instante = [datetime(2026, 10, 31, 23, 50)]
    app = Flask(__name__)
    app.register_blueprint(horas.criar_blueprint(config, relogio=lambda: instante[0]))
    cliente = app.test_client()
    assert cliente.post("/horas/iniciar", json={"tipo": 1, "tarefa": "Conferir lote"}).status_code == 201
    instante[0] = datetime(2026, 11, 1, 0, 10)
    dados = cliente.get("/horas/dados").get_json()
    assert dados["ativa"]["tarefa"] == "Conferir lote"
    assert dados["totais"]["dia"]["geral"] == 600
    assert dados["totais"]["semana"]["geral"] == 1200
    assert dados["totais"]["mes"]["geral"] == 600


def test_uma_sessao_por_vez_parada_e_exclusao(config):
    instante = [datetime(2026, 10, 5, 9)]
    bp = horas.criar_blueprint(config, relogio=lambda: instante[0])
    app = Flask(__name__)
    app.register_blueprint(bp)
    cliente = app.test_client()
    primeira = cliente.post("/horas/iniciar", json={"tipo": 1, "empresa": "EMPRESA A"}).get_json()["id"]
    instante[0] = datetime(2026, 10, 5, 10)
    segunda = cliente.post("/horas/iniciar", json={"tipo": 2, "tarefa": "Organizar agenda"}).get_json()["id"]
    dados = cliente.get("/horas/dados").get_json()
    assert dados["ativa"]["id"] == segunda
    assert next(s for s in dados["sessoes"] if s["id"] == primeira)["fim"] == "2026-10-05T10:00:00"
    assert cliente.post(f"/horas/sessao/{segunda}/excluir", json={}).status_code == 404
    instante[0] = datetime(2026, 10, 5, 11)
    assert cliente.post("/horas/parar", json={}).status_code == 200
    assert cliente.post("/horas/parar", json={}).status_code == 400
    assert cliente.post(f"/horas/sessao/{primeira}/excluir", json={}).status_code == 200
    assert cliente.get("/horas/dados").get_json()["totais"]["dia"]["geral"] == 3600


def test_tipos_e_validacoes(cliente):
    assert cliente.get("/horas/dados").get_json()["tipos"][0]["nome"] == "Auditoria"
    assert cliente.post("/horas/tipo", json={"nome": "Reuniões"}).status_code == 201
    for nome in ("reuniões", " Auditoria "):
        assert cliente.post("/horas/tipo", json={"nome": nome}).status_code == 400
    for dados in ({"nome": "  "}, {"nome": 7}, {"nome": "Novo", "extra": 1}, []):
        assert cliente.post("/horas/tipo", json=dados).status_code == 400
    for dados in ({}, {"tipo": 0}, {"tipo": True}, {"tipo": 999},
                  {"tipo": 1, "empresa": "INVENTADA"}, {"tipo": 1, "tarefa": 5},
                  {"tipo": 1, "extra": 1}):
        assert cliente.post("/horas/iniciar", json=dados).status_code == 400
    assert cliente.get("/horas/dados").get_json()["ativa"] is None
    assert cliente.post("/horas/parar", json={"extra": 1}).status_code == 400
    assert cliente.post("/horas/sessao/1/excluir", json=[]).status_code == 400


def test_inicio_invalido_preserva_sessao_aberta(cliente):
    resposta = cliente.post("/horas/iniciar", json={"tipo": 1, "tarefa": "Conferir lote"})
    assert resposta.status_code == 201
    id_ = resposta.get_json()["id"]
    assert cliente.post("/horas/iniciar", json={"tipo": 999}).status_code == 400
    assert cliente.get("/horas/dados").get_json()["ativa"]["id"] == id_


def test_clique_na_empresa_conta_auditoria_sem_reiniciar(config):
    instante = [datetime(2026, 10, 5, 9)]
    app = Flask(__name__)
    app.register_blueprint(horas.criar_blueprint(config, relogio=lambda: instante[0]))
    cliente = app.test_client()
    assert cliente.post("/horas/iniciar", json={"tipo": 2, "tarefa": "Organizar agenda"}).status_code == 201
    instante[0] = datetime(2026, 10, 5, 10)
    resposta = cliente.post("/horas/auditoria", json={"empresa": "EMPRESA A"})
    assert resposta.get_json() == {"ok": True, "iniciada": True}
    ativa = cliente.get("/horas/dados").get_json()["ativa"]
    assert (ativa["tipo"], ativa["empresa"], ativa["inicio"]) == ("Auditoria", "EMPRESA A", "2026-10-05T10:00:00")
    # mesma empresa de novo: continua a mesma sessão
    instante[0] = datetime(2026, 10, 5, 10, 30)
    assert cliente.post("/horas/auditoria", json={"empresa": "EMPRESA A"}).get_json()["iniciada"] is False
    assert cliente.get("/horas/dados").get_json()["ativa"]["id"] == ativa["id"]
    # outra empresa: encerra a anterior e começa a nova
    instante[0] = datetime(2026, 10, 5, 11)
    assert cliente.post("/horas/auditoria", json={"empresa": "EMPRESA B"}).get_json()["iniciada"] is True
    dados = cliente.get("/horas/dados").get_json()
    assert dados["ativa"]["empresa"] == "EMPRESA B"
    assert next(s for s in dados["sessoes"] if s["id"] == ativa["id"])["fim"] == "2026-10-05T11:00:00"
    for corpo in ({"empresa": "EMPRESA INEXISTENTE"}, {"empresa": 1}, {}, {"empresa": "EMPRESA A", "x": 1}):
        assert cliente.post("/horas/auditoria", json=corpo).status_code == 400
    assert cliente.get("/horas/dados").get_json()["ativa"]["empresa"] == "EMPRESA B"
