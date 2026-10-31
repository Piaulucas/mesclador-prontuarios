"""Faturas e tarefas fictícias, com banco isolado e datas fixas."""

import sqlite3
from datetime import date

from mesclador import pendencias


def test_pagina_pendencias_tem_aba_grupos_e_formularios(cliente):
    resposta = cliente.get("/pendencias/")
    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert "<title>Pendências · Área de trabalho</title>" in html
    assert 'href="/pendencias/" class="ativa" aria-current="page"' in html
    assert html.index("Vencidas") < html.index("Vencendo") < html.index("No prazo")
    assert html.index("No prazo") < html.index("Aguardando terceiros")
    assert html.index("Aguardando terceiros") < html.index("NF a solicitar") < html.index("Tarefas")
    for texto in ("Registrar fatura", "Chegou o ofício de glosa", "Respondi a glosa",
                  "NF solicitada", "NF emitida", "Nova tarefa", "Concluir tarefa"):
        assert texto in html
    assert 'id="pendenciasAviso"' in html
    assert 'id="formNfEmitida"' in html and 'fetch("/pendencias/nfs-solicitadas")' in html
    assert "pendenciasAberta:" in html and "textContent" in html
    assert "https://" not in html


def test_inicio_mostra_contagens_e_link_para_pendencias(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'id="inicioPendencias"' in html
    assert 'fetch("/pendencias/dados")' in html
    assert 'cartao.href = "/pendencias/"' in html
    assert 'class="inicio-reservas"' not in html


def test_fluxo_das_rotas_usadas_pela_tela(cliente):
    fatura = cliente.post("/pendencias/fatura", json={
        "empresa": "EMPRESA A", "competencia": "2026-10", "referencia": "Fictícia"})
    assert fatura.status_code == 200
    numero = fatura.get_json()["id"]
    for campos in ({"oficio_data": "2026-10-10"}, {"resposta_data": "2026-10-20"},
                   {"nf": "solicitada", "nf_data": "2026-10-21"}):
        assert cliente.post(f"/pendencias/fatura/{numero}", json=campos).status_code == 200
    assert cliente.get("/pendencias/nfs-solicitadas").get_json() == [{
        "id": numero, "empresa": "EMPRESA A", "competencia": "2026-10", "referencia": "Fictícia"}]
    assert cliente.post(f"/pendencias/fatura/{numero}", json={
        "nf": "emitida", "nf_data": "2026-10-22"}).status_code == 200
    assert cliente.get("/pendencias/nfs-solicitadas").get_json() == []
    tarefa = cliente.post("/pendencias/tarefa", json={
        "empresa": "EMPRESA A", "texto": "Conferir fatura fictícia", "prazo": None})
    assert tarefa.status_code == 200
    assert cliente.post(f"/pendencias/tarefa/{tarefa.get_json()['id']}",
                        json={"concluida": True}).status_code == 200
    dados = cliente.get("/pendencias/dados").get_json()
    assert all(not itens for itens in dados["empresas"][0]["grupos"].values())


def test_banco_criado_na_primeira_abertura_e_unicidade(config, cliente):
    assert not config.trabalho_arquivo.exists()
    dados = {"empresa": "EMPRESA A", "competencia": "2026-09", "referencia": "F-1"}
    resposta = cliente.post("/pendencias/fatura", json=dados)
    assert resposta.status_code == 200
    assert resposta.get_json()["id"] == 1
    assert config.trabalho_arquivo.exists()
    with sqlite3.connect(config.trabalho_arquivo) as banco:
        assert banco.execute("PRAGMA user_version").fetchone()[0] == 1
        assert banco.execute("SELECT nf, referencia FROM fatura").fetchone() == ("nao_solicitada", "F-1")
    assert cliente.post("/pendencias/fatura", json=dados).status_code == 400
    assert cliente.post("/pendencias/fatura", json={**dados, "referencia": "F-2"}).status_code == 200
    assert cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA B", "competencia": "2026-09"}).status_code == 200
    assert cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA B", "competencia": "2026-09"}).status_code == 400


def test_prazo_glosa_e_espera_com_hoje_fixo():
    hoje = date(2026, 10, 31)
    fatura = {"competencia": "2026-09", "oficio_data": "2026-09-01", "resposta_data": None,
              "nf": "nao_solicitada"}
    assert pendencias.avaliar_glosa(fatura, hoje) == {
        "situacao": "vencendo", "limite": "2026-10-31", "dias_restantes": 0}
    assert pendencias.avaliar_glosa(fatura, date(2026, 11, 1))["situacao"] == "vencida"
    assert pendencias.avaliar_glosa(fatura, date(2026, 10, 21))["situacao"] == "vencendo"
    assert pendencias.avaliar_glosa(fatura, date(2026, 10, 20))["situacao"] == "no_prazo"
    assert pendencias.avaliar_glosa(fatura, hoje, prazo_dias=45)["limite"] == "2026-10-16"
    assert pendencias.avaliar_glosa(fatura, date(2026, 10, 25), alerta_dias=5)["situacao"] == "no_prazo"
    assert pendencias.avaliar_nf(fatura) == {"situacao": "nf_a_solicitar"}
    fatura["oficio_data"] = None
    assert pendencias.avaliar_glosa(fatura, hoje) == {"situacao": "aguardando_oficio", "dias_de_espera": 30}
    assert pendencias.avaliar_glosa(fatura, date(2026, 9, 1))["dias_de_espera"] == 0
    fatura["resposta_data"] = "2026-10-20"
    assert pendencias.avaliar_glosa(fatura, hoje) is None


def test_tarefa_com_sem_prazo_e_concluida():
    tarefa = {"prazo": None, "concluida_em": None}
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31)) == {"situacao": "sem_prazo"}
    tarefa["prazo"] = "2026-10-30"
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31))["situacao"] == "vencida"
    tarefa["prazo"] = "2026-11-02"
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31))["situacao"] == "vencendo"
    tarefa["concluida_em"] = "2026-10-31"
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31)) is None


def test_api_agrupa_abertas_e_atualiza_registros(config, cliente):
    primeira = cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA A", "competencia": "2026-08"}).get_json()["id"]
    segunda = cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA A", "competencia": "2026-09"}).get_json()["id"]
    assert cliente.post(f"/pendencias/fatura/{segunda}", json={
        "oficio_data": "2026-09-01", "nf": "solicitada", "nf_data": "2026-09-10", "nota": "Cobrar retorno"}).status_code == 200
    tarefa = cliente.post("/pendencias/tarefa", json={
        "empresa": "EMPRESA B", "texto": "Conferir documentos", "prazo": "2026-11-02"}).get_json()["id"]
    dados = pendencias.listar(config, date(2026, 10, 31))
    a, b = dados["empresas"]
    assert dados["hoje"] == "2026-10-31"
    assert [f["id"] for f in a["grupos"]["nf_a_solicitar"]] == [primeira]
    assert a["grupos"]["aguardando_terceiros"][0]["id"] == primeira
    assert a["grupos"]["vencendo"][0]["id"] == segunda
    assert b["grupos"]["tarefas"][0]["situacao"] == "vencendo"
    assert dados["totais"]["nf_a_solicitar"] == 1
    assert cliente.get("/pendencias/dados").status_code == 200
    assert cliente.post(f"/pendencias/fatura/{segunda}", json={"resposta_data": "2026-10-31"}).status_code == 200
    assert cliente.post(f"/pendencias/tarefa/{tarefa}", json={"concluida_em": "2026-10-31"}).status_code == 200
    dados = pendencias.listar(config, date(2026, 10, 31))
    assert not dados["empresas"][0]["grupos"]["vencendo"]
    assert not dados["empresas"][1]["grupos"]["tarefas"]
    assert cliente.post(f"/pendencias/tarefa/{tarefa}", json={
        "concluida": False, "texto": "Rever documentos", "prazo": None}).status_code == 200
    assert pendencias.listar(config, date(2026, 10, 31))["empresas"][1]["grupos"]["tarefas"][0]["situacao"] == "sem_prazo"


def test_api_valida_campos_sem_gravar(config, cliente):
    base = {"empresa": "EMPRESA A", "competencia": "2026-09"}
    invalidas = [
        {**base, "empresa": "DESCONHECIDA"}, {**base, "empresa": ["EMPRESA A"]},
        {**base, "competencia": "2026-13"}, {**base, "competencia": "0000-01"},
        {**base, "referencia": 1}, {**base, "paciente": "Pessoa Fictícia"},
    ]
    for entrada in invalidas:
        resposta = cliente.post("/pendencias/fatura", json=entrada)
        assert resposta.status_code == 400 and resposta.get_json()["erro"]
    assert cliente.post("/pendencias/fatura", json=base).status_code == 200
    for entrada in ({"oficio_data": "2026-02-30"}, {"resposta_data": "01/10/2026"},
                    {"nf": "invalida"}, {"nf_data": []}, {"nota": 10}, {"empresa": "EMPRESA B"}):
        assert cliente.post("/pendencias/fatura/1", json=entrada).status_code == 400
    assert cliente.post("/pendencias/fatura/999", json={"nota": "Teste"}).status_code == 404
    for entrada in ({"empresa": "EMPRESA A", "texto": ""},
                    {"empresa": "EMPRESA A", "texto": "Conferir", "prazo": "2026-13-01"},
                    {"empresa": "DESCONHECIDA", "texto": "Conferir"}):
        assert cliente.post("/pendencias/tarefa", json=entrada).status_code == 400
    tarefa = cliente.post("/pendencias/tarefa", json={"empresa": "EMPRESA A", "texto": "Conferir"}).get_json()["id"]
    for entrada in ({"concluida": "sim"}, {"concluida_em": "2026-02-30"},
                    {"prazo": "2026-02-30"}, {"texto": " "}, {"concluida": True, "concluida_em": None}):
        assert cliente.post(f"/pendencias/tarefa/{tarefa}", json=entrada).status_code == 400
    assert cliente.post("/pendencias/tarefa/999", json={"texto": "Conferir"}).status_code == 404
    with sqlite3.connect(config.trabalho_arquivo) as banco:
        assert banco.execute("SELECT count(*) FROM fatura").fetchone()[0] == 1
        assert banco.execute("SELECT count(*) FROM tarefa").fetchone()[0] == 1


def test_prazos_configurados_no_agrupamento(config, cliente):
    config.prazo_glosa_dias = 45
    config.alerta_dias = 5
    cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA A", "competencia": "2026-09"})
    cliente.post("/pendencias/fatura/1", json={"oficio_data": "2026-09-15"})
    dados = pendencias.listar(config, date(2026, 10, 25))
    assert dados["empresas"][0]["grupos"]["vencendo"][0]["limite"] == "2026-10-30"


def test_nf_a_solicitar_mostra_competencia_mais_antiga_primeiro(config, cliente):
    for competencia in ("2026-10", "2026-08", "2026-09"):
        assert cliente.post("/pendencias/fatura", json={
            "empresa": "EMPRESA A", "competencia": competencia}).status_code == 200
    itens = pendencias.listar(config, date(2026, 10, 31))["empresas"][0]["grupos"]["nf_a_solicitar"]
    assert [item["competencia"] for item in itens] == ["2026-08", "2026-09", "2026-10"]
