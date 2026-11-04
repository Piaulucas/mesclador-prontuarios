"""Painel de tarefas (flutuante e janela por cima) com tarefas e sessões fictícias."""

from datetime import date, datetime

from flask import Flask

from mesclador import horas, pendencias


def _app(config, instante):
    app = Flask(__name__)
    relogio = lambda: instante[0]  # noqa: E731
    app.register_blueprint(pendencias.criar_blueprint(config, relogio=relogio))
    app.register_blueprint(horas.criar_blueprint(config, relogio=relogio))
    return app.test_client()


def test_painel_substitui_o_botao_antigo_em_todas_as_telas(cliente):
    for rota in ("/", "/painel/", "/mesclar", "/converter", "/pendencias/", "/horas/"):
        html = cliente.get(rota).get_data(as_text=True)
        assert 'id="tarefasPainel"' in html and 'id="tarefasPilula"' in html
        assert 'id="tarefasPorCima"' in html and 'id="tarefasContador"' in html
        assert 'src="/static/tarefas.js"' in html
        assert "postit" not in html
    assert cliente.get("/static/postit.js").status_code == 404
    codigo = cliente.get("/static/tarefas.js").get_data(as_text=True)
    for trecho in ('fetch("/pendencias/tarefas")', '"/horas/iniciar", {tarefa_id: id}', '"/horas/parar"',
                   "{concluida: true}", 'new BroadcastChannel("tarefas")', "documentPictureInPicture.requestWindow",
                   'window.open("/tarefas/janela", "tarefas"', '"pagehide"', "setPointerCapture",
                   '"tarefasMinimizado"', '"tarefasPosicao"', '"Sem empresa"', 'new Event("horasAlteradas")'):
        assert trecho in codigo, trecho
    assert 'if (temPip) abrirPip();' in codigo
    assert 'else abrirJanelaComum();' in codigo
    assert 'botaoManter.addEventListener("click", abrirPip)' in codigo
    assert "https://" not in codigo


def test_janela_de_tarefas_nao_tem_barra_nem_painel_duplicado(cliente):
    resposta = cliente.get("/tarefas/janela")
    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert '<body class="tarefas-janela">' in html
    assert 'class="topo"' not in html and 'id="encerrar"' not in html
    assert html.count('id="tarefasPainel"') == 1
    assert 'id="tarefasManter"' in html and 'id="tarefasMarcador"' in html
    assert "<title>Tarefas · Área de trabalho</title>" in html
    # o script comum não quebra sem a barra superior
    assert 'if (indicador) indicador.hidden = !horasInicio;' in html and 'if ($("encerrar"))' in html


def test_tempo_por_tarefa_e_dados_do_painel(config):
    instante = [datetime(2026, 11, 2, 9)]
    cliente = _app(config, instante)
    a = cliente.post("/pendencias/tarefa", json={"empresa": "EMPRESA A", "texto": "Conferir lote fictício"}).get_json()["id"]
    b = cliente.post("/pendencias/tarefa", json={"texto": "Organizar a semana"}).get_json()["id"]
    # ▶: a sessão herda texto e empresa da tarefa; o tipo vem da sessão em andamento
    assert cliente.post("/horas/iniciar", json={"tipo": 2}).status_code == 201
    instante[0] = datetime(2026, 11, 2, 9, 30)
    assert cliente.post("/horas/iniciar", json={"tarefa_id": a}).status_code == 201
    ativa = cliente.get("/horas/dados").get_json()["ativa"]
    assert (ativa["tipo"], ativa["tarefa"], ativa["empresa"], ativa["tarefa_id"]) == (
        "Produtividade", "Conferir lote fictício", "EMPRESA A", a)
    instante[0] = datetime(2026, 11, 2, 10)
    assert cliente.post("/horas/iniciar", json={"tarefa_id": b}).status_code == 201
    instante[0] = datetime(2026, 11, 2, 10, 5)
    dados = cliente.get("/pendencias/tarefas").get_json()
    assert {t["id"]: t["segundos"] for t in dados["tarefas"]} == {a: 1800, b: 300}
    assert dados["ativa"]["tarefa_id"] == b and dados["ativa"]["empresa"] is None
    assert dados["empresas"] == ["EMPRESA A", "EMPRESA B"]
    for corpo in ({"tarefa_id": 999}, {"tarefa_id": "1"}, {"tarefa_id": True}, {}):
        assert cliente.post("/horas/iniciar", json=corpo).status_code == 400
    assert cliente.get("/horas/dados").get_json()["ativa"]["tarefa_id"] == b


def test_concluir_tarefa_contada_volta_para_a_atividade_anterior(config):
    hoje = date.today()
    instante = [datetime(hoje.year, hoje.month, hoje.day, 9)]
    cliente = _app(config, instante)
    tarefa = cliente.post("/pendencias/tarefa", json={"empresa": "EMPRESA A", "texto": "Pedir FDR fictícia"}).get_json()["id"]
    assert cliente.post("/horas/auditoria", json={"empresa": "EMPRESA B"}).status_code == 200
    instante[0] = datetime(hoje.year, hoje.month, hoje.day, 9, 20)
    cliente.post("/horas/iniciar", json={"tarefa_id": tarefa})
    instante[0] = datetime(hoje.year, hoje.month, hoje.day, 9, 35)
    resposta = cliente.post(f"/pendencias/tarefa/{tarefa}", json={"concluida": True}).get_json()
    assert resposta["contador"] == "voltou"
    ativa = cliente.get("/horas/dados").get_json()["ativa"]
    assert (ativa["tipo"], ativa["empresa"], ativa["tarefa_id"], ativa["inicio"]) == (
        "Auditoria", "EMPRESA B", None, hoje.isoformat() + "T09:35:00")
    dados = cliente.get("/pendencias/tarefas").get_json()
    assert dados["tarefas"] == [] and dados["concluidas_hoje"][0]["segundos"] == 900
    # sem atividade anterior: o contador para
    outra = cliente.post("/pendencias/tarefa", json={"texto": "Tarefa geral"}).get_json()["id"]
    cliente.post("/horas/parar", json={})
    instante[0] = datetime(hoje.year, hoje.month, hoje.day, 10)
    cliente.post("/horas/iniciar", json={"tarefa_id": outra})
    assert cliente.post(f"/pendencias/tarefa/{outra}", json={"concluida": True}).get_json()["contador"] == "parado"
    assert cliente.get("/horas/dados").get_json()["ativa"] is None
    # concluir uma tarefa que não está sendo contada não mexe no contador
    terceira = cliente.post("/pendencias/tarefa", json={"texto": "Outra"}).get_json()["id"]
    assert cliente.post(f"/pendencias/tarefa/{terceira}", json={"concluida": True}).get_json()["contador"] is None
    assert cliente.post("/horas/iniciar", json={"tarefa_id": terceira}).status_code == 400   # já concluída


def test_painel_lista_prazos_de_recurso_vencidos_e_vencendo(config):
    instante = [datetime(2026, 11, 2, 9)]
    cliente = _app(config, instante)
    for competencia, oficio in (("2026-07", "2026-08-20"), ("2026-08", "2026-09-05"), ("2026-09", "2026-10-20")):
        numero = cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA A", "competencia": competencia,
                                                          "enviada_em": oficio}).get_json()["id"]
        cliente.post(f"/pendencias/fatura/{numero}/glosa", json={"oficio_data": oficio, "valor_glosado": 1000})
    prazos = cliente.get("/pendencias/tarefas").get_json()["prazos"]
    assert [(p["competencia"], p["faixa"]) for p in prazos] == [("2026-07", "vencida"), ("2026-08", "vencendo")]
