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
    resp = enviar(cliente, (jpeg(), "f1.jpg"), (pdf(1), "f2.pdf"), (jpeg(), "nota.docx"))
    assert [r.get("paginas") for r in resp[:2]] == [1, 1]
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
    assert [r["nome"] for r in resp] == ["folha1.pdf · p1", "folha1.pdf · p2", "folha2.jpg", "folha10.jpg"]
    assert [r["paginas"] for r in resp] == [1, 1, 1, 1]


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


def zip_com(nomes):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n in nomes:
            z.writestr(n, jpeg().getvalue())
    b.seek(0)
    return b


def test_zip_com_nome_do_paciente_informa_origem(cliente):
    resp = enviar(cliente, (zip_com(["MARIA SOUZA/a.jpg"]), "MARIA SOUZA-20261014T190644Z-001.zip"))
    assert resp[0]["origem"] == "MARIA SOUZA"


def test_drive_download_usa_pasta_interna(cliente):
    resp = enviar(cliente, (zip_com(["JOSE SILVA/a.jpg", "JOSE SILVA/b.jpg"]), "drive-download-20261014T1-001.zip"))
    assert resp[0]["origem"] == "JOSE SILVA"


def test_drive_download_sem_pasta_nao_confere(cliente):
    resp = enviar(cliente, (zip_com(["a.jpg", "b.jpg"]), "drive-download-20261014T190644Z-1-001.zip"))
    assert all("origem" not in r for r in resp)


def test_previa_informa_conferencia(cliente):
    def conf(origem, nome):
        return cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "ADULTO-PED", "numero": "4",
                                                    "nome": nome, "origem": origem}).get_json()["confere"]
    assert conf("MARIA SOUZA", "MARIA FICTICIA DE SOUZA") is True
    assert conf("MARIA SOUZA", "ANA PEREIRA") is False
    assert conf("drive-download-20261014T190644Z-1-001", "ANA PEREIRA") is None
    assert conf("", "ANA PEREIRA") is None


def test_ping_identifica_o_app(cliente):
    assert cliente.get("/ping").get_data(as_text=True) == "mesclador"


def test_encerrar_chama_a_rotina_de_saida(config, tmp_path):
    import time
    from mesclador.web import create_app
    app = create_app(config, pasta_temp=tmp_path / "t3")
    chamado = []
    app.config["AO_ENCERRAR"] = lambda url: chamado.append(url)   # não mata o processo do teste
    assert app.test_client().post("/encerrar").get_json() == {"ok": True}
    time.sleep(0.5)
    assert chamado == ["http://localhost"]   # endereço usado para achar e fechar a aba


# ---------- ajustes de legibilidade por item (tela de mesclar) ----------

def _cinza(valor=100, largura=300, altura=400):
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (largura, altura), (valor, valor, valor)).save(b, "JPEG")
    b.seek(0)
    return b


def _media_da_pagina(caminho, indice):
    import pypdfium2 as pdfium
    from PIL import ImageStat
    doc = pdfium.PdfDocument(str(caminho))
    try:
        img = doc[indice].render(scale=1).to_pil().convert("L")
    finally:
        doc.close()
    return ImageStat.Stat(img).mean[0]


def test_mesclar_com_ajuste_clareia_so_o_item_ajustado(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (_cinza(100), "a.jpg"), (pdf(1), "b.pdf"))]
    itens = [{"id": ids[0], "giro": 0, "brilho": 60, "contraste": 0, "realce": False},
             {"id": ids[1], "giro": 0, "brilho": 0, "contraste": 0, "realce": False}]
    r = cliente.post("/salvar", json=corpo(ids, itens=itens))
    assert r.status_code == 200
    saida = Path(r.get_json()["caminho"])
    assert _media_da_pagina(saida, 0) > 100 + 20          # imagem ficou mais clara que o original
    pagina_pdf = PdfReader(saida).pages[1]
    assert (float(pagina_pdf.mediabox.width), float(pagina_pdf.mediabox.height)) == (595, 842)   # PDF sem ajuste não virou imagem


def test_mesclar_pdf_com_realce_mantem_as_paginas(cliente):
    ids = [r["id"] for r in enviar(cliente, (pdf(2), "a.pdf"))]
    assert len(ids) == 2   # uma folha por página
    itens = [{"id": i, "giro": 0, "brilho": 0, "contraste": 0, "realce": True} for i in ids]
    r = cliente.post("/salvar", json=corpo(ids, itens=itens))
    assert r.status_code == 200
    assert len(PdfReader(r.get_json()["caminho"]).pages) == 2


def test_salvar_recusa_ajuste_invalido(cliente):
    ids = [r["id"] for r in enviar(cliente, (jpeg(), "a.jpg"))]
    itens = [{"id": ids[0], "giro": 0, "brilho": "muito"}]
    assert cliente.post("/salvar", json=corpo(ids, itens=itens)).status_code == 400


def test_miniatura_com_ajuste_responde_jpeg(cliente):
    id_ = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    r = cliente.get(f"/miniatura/{id_}?brilho=50&contraste=-20&realce=1")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    assert cliente.get(f"/miniatura/{id_}?brilho=abc").status_code == 400


def test_miniatura_ampliada_renderiza_a_primeira_pagina(cliente):
    from io import BytesIO
    from PIL import Image
    id_ = enviar(cliente, (pdf(2), "a.pdf"))[0]["id"]
    r = cliente.get(f"/miniatura/{id_}?tam=1400&brilho=10")
    assert r.mimetype == "image/jpeg"
    assert max(Image.open(BytesIO(r.data)).size) > 1000


# ---------- PDF de várias páginas vira um cartão por página ----------

def test_pdf_de_varias_paginas_vira_um_item_por_pagina(cliente):
    resp = enviar(cliente, (pdf(3), "x.pdf"))
    assert [r["nome"] for r in resp] == ["x.pdf · p1", "x.pdf · p2", "x.pdf · p3"]
    assert [r["paginas"] for r in resp] == [1, 1, 1]


def test_zip_com_pdf_de_duas_paginas_e_imagem_mantem_ordem_e_origem(cliente):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("MARIA SOUZA/a.pdf", pdf(2).getvalue())
        z.writestr("MARIA SOUZA/b.jpg", jpeg().getvalue())
    b.seek(0)
    resp = enviar(cliente, (b, "MARIA SOUZA-20261014T190644Z-001.zip"))
    assert [r["nome"] for r in resp] == ["a.pdf · p1", "a.pdf · p2", "b.jpg"]
    assert all(r["origem"] == "MARIA SOUZA" for r in resp)


def test_mesclar_paginas_separadas_na_ordem_nova_sem_virar_imagem(cliente):
    p1, p2, p3 = (r["id"] for r in enviar(cliente, (pdf(3), "x.pdf")))
    r = cliente.post("/salvar", json=corpo([p3, p1, p2], itens=[{"id": i, "giro": 0} for i in (p3, p1)]))
    assert r.status_code == 200
    paginas = PdfReader(r.get_json()["caminho"]).pages
    assert len(paginas) == 2
    assert all((float(p.mediabox.width), float(p.mediabox.height)) == (595, 842) for p in paginas)
