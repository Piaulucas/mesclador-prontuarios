from pathlib import Path

import pytest

from pypdf import PdfReader

from tests.conftest import jpeg, pdf


def enviar(cliente, *arquivos):
    return cliente.post("/enviar", data={"arquivos": list(arquivos)},
                        content_type="multipart/form-data").get_json()


PASTA = {}   # preenchido pelo fixture autouse abaixo


@pytest.fixture(autouse=True)
def _pasta(pasta_principal):
    PASTA["p"] = str(pasta_principal)


def corpo(ids, **extra):
    base = {"itens": [{"id": i, "giro": 0} for i in ids], "empresa": "EMPRESA A", "pasta": PASTA["p"],
            "mes": "2026-10", "tipo": "ADULTO-PED", "numero": "045", "nome": "José da Silva"}
    base.update(extra)
    return base


def test_enviar_recusa_formato_nao_suportado(cliente):
    resp = enviar(cliente, (jpeg(), "f1.jpg"), (pdf(), "f2.pdf"), (jpeg(), "nota.docx"))
    assert [r.get("paginas") for r in resp[:2]] == [1, 2]
    assert "formato não suportado" in resp[2]["erro"]


def test_salva_na_subpasta_existente_com_numero_exato(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (pdf(2), "a.pdf"), (jpeg(), "b.jpg"))]
    r = cliente.post("/salvar", json=corpo(ids))
    assert r.status_code == 200
    esperado = pasta_principal / "Adulto e Pediátrico" / "45 - JOSE DA SILVA.pdf"
    assert Path(r.get_json()["caminho"]) == esperado
    assert len(PdfReader(esperado).pages) == 3


def test_cria_subpasta_quando_nao_existe(cliente, pasta_principal):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    r = cliente.post("/salvar", json=corpo([id1], tipo="NEONATAL", numero="4", nome="RN de Fulana"))
    assert Path(r.get_json()["caminho"]) == pasta_principal / "NEONATAL" / "04 - RN DE FULANA.pdf"


def test_pasta_inexistente_da_erro(cliente, tmp_path):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    assert cliente.post("/salvar", json=corpo([id1], pasta=str(tmp_path / "nao-existe"))).status_code == 400


def test_nao_sobrescreve_sem_confirmar(cliente):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    cliente.post("/salvar", json=corpo([id1]))
    id2 = enviar(cliente, (jpeg(), "b.jpg"))[0]["id"]
    assert cliente.post("/salvar", json=corpo([id2])).status_code == 409
    assert cliente.post("/salvar", json=corpo([id2], sobrescrever=True)).status_code == 200


def test_salvar_sem_nome_da_erro(cliente):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    assert cliente.post("/salvar", json=corpo([id1], nome="")).status_code == 400


def test_planilhas_e_busca(cliente):
    lista = cliente.get("/planilhas?empresa=EMPRESA A&mes=2026-10").get_json()
    assert lista[0]["caminho"] == "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx"
    achados = cliente.get("/buscar", query_string={"empresa": "EMPRESA A",
                                                   "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", "numero": "3",
                                                   "tipo": "NEONATAL"}).get_json()
    assert [a["nome"] for a in achados] == ["RN DE FULANA"]


def test_empresa_sem_planilha(cliente):
    assert cliente.get("/planilhas?empresa=EMPRESA B&mes=2026-10").get_json() == []


def test_abrir_so_aceita_pdfs_salvos_na_sessao(cliente):
    assert cliente.get("/abrir?caminho=/etc/passwd").status_code == 404
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    caminho = cliente.post("/salvar", json=corpo([id1])).get_json()["caminho"]
    assert cliente.get("/abrir", query_string={"caminho": caminho}).status_code == 200


def test_previa(cliente):
    r = cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "NEONATAL",
                                             "numero": "003", "nome": "rn de fulana"}).get_json()
    assert r["caminho"] == "PRONTUARIOS OUTUBRO/NEONATAL/03 - RN DE FULANA.pdf"
    assert "será criada" in r["aviso"]
    r = cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "ADULTO-PED",
                                             "numero": "12", "nome": "x"}).get_json()
    assert r["caminho"] == "PRONTUARIOS OUTUBRO/Adulto e Pediátrico/12 - X.pdf" and r["aviso"] == ""


def test_seletor_fora_do_mac_avisa(cliente, monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    r = cliente.post("/escolher-pasta", json={})
    assert r.status_code == 400 and "macOS" in r.get_json()["erro"]


def test_pagina_inicial(cliente):
    assert cliente.get("/").status_code == 200


def test_lista_so_planilhas_do_mes(cliente):
    lista = cliente.get("/planilhas?empresa=EMPRESA A&mes=2026-10").get_json()
    assert [p["caminho"] for p in lista] == ["2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx"]
    assert cliente.get("/planilhas?empresa=EMPRESA A&mes=2026-11").get_json() == []


def test_mes_anterior_ao_inicio_e_bloqueado(config, tmp_path):
    from mesclador.web import create_app
    config.mes_inicial = "2026-10"
    c = create_app(config, pasta_temp=tmp_path / "t2").test_client()
    assert c.get("/planilhas?empresa=EMPRESA A&mes=2026-09").get_json() == []
    id1 = enviar(c, (jpeg(), "a.jpg"))[0]["id"]
    r = c.post("/salvar", json=corpo([id1], mes="2026-09"))
    assert r.status_code == 400
    assert c.post("/salvar", json=corpo([id1], mes="2026-10")).status_code == 200


def test_numero_com_dois_digitos(cliente):
    casos = {"4": "04", "004": "04", "10": "10", "045": "45", "123": "123"}
    for entrada, esperado in casos.items():
        r = cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "ADULTO-PED",
                                                 "numero": entrada, "nome": "x"}).get_json()
        assert r["caminho"].endswith(f"/{esperado} - X.pdf"), (entrada, r)


def zip_do_drive():
    """Imita o .zip do Google Drive: pasta com o nome do paciente, folhas fora de ordem
    alfabética simples e lixo do macOS."""
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("FULANO DE TAL/folha10.jpg", jpeg().getvalue())
        z.writestr("FULANO DE TAL/folha2.jpg", jpeg().getvalue())
        z.writestr("FULANO DE TAL/folha1.pdf", pdf(2).getvalue())
        z.writestr("FULANO DE TAL/.DS_Store", b"x")
        z.writestr("FULANO DE TAL/leia-me.txt", b"x")
        z.writestr("__MACOSX/FULANO DE TAL/._folha2.jpg", b"x")
    b.seek(0)
    return b


def test_enviar_zip_extrai_em_ordem_natural_e_ignora_lixo(cliente):
    resp = enviar(cliente, (zip_do_drive(), "FULANO DE TAL-20261014.zip"))
    assert [r["nome"] for r in resp] == ["folha1.pdf", "folha2.jpg", "folha10.jpg"]
    assert [r["paginas"] for r in resp] == [2, 1, 1]


def test_zip_mesclado_e_salvo(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (zip_do_drive(), "p.zip"))]
    r = cliente.post("/salvar", json=corpo(ids, numero="7"))
    assert len(PdfReader(r.get_json()["caminho"]).pages) == 4


def test_zip_sem_arquivos_validos_avisa(cliente):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("nota.txt", b"x")
    b.seek(0)
    [r] = enviar(cliente, (b, "vazio.zip"))
    assert "nenhum PDF ou imagem" in r["erro"]


def test_zip_corrompido_avisa(cliente):
    import io
    [r] = enviar(cliente, (io.BytesIO(b"isto nao e um zip"), "ruim.zip"))
    assert "zip inválido" in r["erro"]


def test_arquivo_vindo_de_pasta_usa_so_o_nome(cliente):
    [r] = enviar(cliente, (jpeg(), "FULANO/folha1.jpg"))
    assert r["nome"] == "folha1.jpg"
