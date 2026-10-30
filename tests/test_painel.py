"""Rotas do painel com planilhas e pastas inteiramente fictícias."""

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

from mesclador.web import create_app

from .conftest import criar_planilha


def test_tela_e_link_do_painel(cliente):
    resposta = cliente.get("/painel/")
    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert 'id="painelMes"' in html
    assert 'type="month"' in html
    assert 'id="painelEmpresa"' in html
    assert 'href="/painel/"' in cliente.get("/").get_data(as_text=True)
    assert "textContent" in html


def test_dados_do_mes_cruzam_planilha_e_pdfs_sem_linha(config, pasta_planilhas, tmp_path):
    caminho = pasta_planilhas / "2026" / "10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx"
    livro = load_workbook(caminho)
    aba = livro["Remoção ADULTO-PED"]
    aba["E16"].fill = PatternFill(fill_type="solid", fgColor="FFFFFF00")
    aba["E17"].fill = PatternFill(fill_type="solid", fgColor="FFFF0000")
    aba["T17"].comment = Comment("Autor: Enviar BDV fictício", "Autor Fictício")
    livro.save(caminho)
    livro.close()
    pasta = tmp_path / "prontuarios" / "2026" / "10_OUTUBRO"
    adulto = pasta / "ADULTO-PED"
    adulto.mkdir(parents=True)
    (adulto / "46 - ANA SOUZA.pdf").write_bytes(b"PDF ficticio")
    (adulto / "99 - PESSOA FICTICIA.pdf").write_bytes(b"PDF ficticio")
    config.auditoria_prontuarios = {"EMPRESA A": str(tmp_path / "prontuarios" / "{ano}" / "{mm}_{MES}")}
    cliente = create_app(config, pasta_temp=tmp_path / "temporarios").test_client()

    resposta = cliente.get("/painel/dados?mes=2026-10")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["mes"] == "2026-10" and "hoje" in dados
    assert dados["totais"]["lancadas"] == 4
    assert dados["totais"]["por_auditar"] == 1
    assert dados["totais"]["com_equipe"] == 1
    assert dados["totais"]["sem_devolucao"] == 1
    empresa = dados["empresas"][0]
    assert empresa["planilha"] == "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx"
    assert empresa["contagem"]["percentual_concluido"] == 50
    assert empresa["pendencias"][0]["comentario"] == "Enviar BDV fictício"
    assert empresa["pendencias"][0]["devolucao"] == "devolução não registrada"
    assert "dias" not in empresa["pendencias"][0]
    assert empresa["pdfs_sem_linha"][0]["arquivo"] == "99 - PESSOA FICTICIA.pdf"
    assert any(i["motivo"] == "sem_cor_sem_pdf" for i in empresa["inconsistencias"])
    assert "Pasta de prontuários" in dados["empresas"][1]["aviso"]


def test_mes_invalido_e_anterior_ao_inicio(config, tmp_path):
    config.mes_inicial = "2026-10"
    cliente = create_app(config, pasta_temp=tmp_path / "temporarios").test_client()
    for mes in ("", "0000-01", "2026-13", "2026-9", "2026-09", "texto", "2026-10-extra"):
        assert cliente.get("/painel/dados", query_string={"mes": mes}).status_code == 400
    assert cliente.get("/painel/dados?mes=2026-10").status_code == 200
    assert 'min="2026-10"' in cliente.get("/painel/").get_data(as_text=True)


def test_planilha_com_defeito_em_uma_empresa_nao_derruba_outra(config, tmp_path):
    defeito = tmp_path / "defeito"
    defeito.mkdir()
    (defeito / "2026-10.xlsx").write_text("arquivo fictício ilegível", encoding="utf-8")
    boa = tmp_path / "boa"
    criar_planilha(boa / "2026-10.xlsx", [(1, "Ana Exemplo")], [])
    config.empresas = {"EMPRESA FICTÍCIA A": defeito, "EMPRESA FICTÍCIA B": boa}
    cliente = create_app(config, pasta_temp=tmp_path / "temporarios").test_client()
    resposta = cliente.get("/painel/dados?mes=2026-10")
    assert resposta.status_code == 200
    primeira, segunda = resposta.get_json()["empresas"]
    assert "Não foi possível ler a planilha" in primeira["aviso"]
    assert primeira["contagem"]["lancadas"] == 0
    assert segunda["contagem"]["lancadas"] == 1
    assert resposta.get_json()["totais"]["lancadas"] == 1
