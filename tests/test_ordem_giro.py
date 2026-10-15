"""A ordem e o giro definidos na tela de mesclar precisam chegar ao PDF salvo.
Páginas distinguíveis pelo conteúdo (texto ou cor), nunca só pela contagem. Dados fictícios."""

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader

from mesclador import pdfs
from tests.conftest import jpeg_colorido, pdf_com_textos


def enviar(cliente, *arquivos):
    return cliente.post("/enviar", data={"arquivos": list(arquivos)},
                        content_type="multipart/form-data").get_json()


def _textos(caminho):
    return [p.extract_text().strip() for p in PdfReader(caminho).pages]


def _pixel(caminho, indice, x_rel, y_rel):
    """Cor (RGB) da página `indice` na posição relativa (0..1) da imagem renderizada."""
    doc = pdfium.PdfDocument(str(caminho))
    try:
        img = doc[indice].render(scale=1).to_pil().convert("RGB")
    finally:
        doc.close()
    return img.getpixel((int(x_rel * (img.width - 1)), int(y_rel * (img.height - 1))))


def _salvar(cliente, pasta, itens):
    r = cliente.post("/salvar", json={"itens": itens, "empresa": "EMPRESA A", "pasta": str(pasta), "mes": "2026-10",
                                      "tipo": "ADULTO-PED", "numero": "045", "nome": "José da Silva"})
    assert r.status_code == 200, r.get_json()
    return Path(r.get_json()["caminho"])


# ---------- ordem ----------

def test_ordem_da_tela_vale_sobre_a_ordem_dos_nomes(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (pdf_com_textos(["UM"]), "1.pdf"),
                                   (pdf_com_textos(["DOIS"]), "2.pdf"),
                                   (pdf_com_textos(["TRES"]), "3.pdf"))]
    novo = [ids[2], ids[0], ids[1]]   # a tela mostra 3, 1, 2
    saida = _salvar(cliente, pasta_principal, [{"id": i, "giro": 0} for i in novo])
    assert _textos(saida) == ["TRES", "UM", "DOIS"]


def test_ordem_mista_pagina_2_antes_da_1_com_imagem_no_meio(cliente, pasta_principal):
    resp = enviar(cliente, (pdf_com_textos(["A1", "A2", "A3"]), "a.pdf"), (jpeg_colorido((255, 0, 0)), "b.jpg"))
    p1, p2, _p3, foto = (r["id"] for r in resp)
    saida = _salvar(cliente, pasta_principal, [{"id": i, "giro": 0} for i in (p2, foto, p1)])
    paginas = PdfReader(saida).pages
    assert len(paginas) == 3
    assert paginas[0].extract_text().strip() == "A2"
    assert paginas[2].extract_text().strip() == "A1"
    assert paginas[1].extract_text().strip() == ""                # a do meio é a foto
    r, g, b = _pixel(saida, 1, 0.5, 0.5)
    assert r > 200 and g < 60 and b < 60                           # vermelha: é o JPEG
    assert "A3" not in _textos(saida)                              # a página 3 ficou de fora, como na tela


def test_sem_ordem_na_chamada_antiga_nada_quebra(cliente, pasta_principal):
    """Chamada antiga: itens sem 'giro' continuam sendo aceitos, na ordem recebida."""
    ids = [r["id"] for r in enviar(cliente, (pdf_com_textos(["UM"]), "1.pdf"), (pdf_com_textos(["DOIS"]), "2.pdf"))]
    saida = _salvar(cliente, pasta_principal, [{"id": ids[1]}, {"id": ids[0]}])
    assert _textos(saida) == ["DOIS", "UM"]


# ---------- giro ----------

def test_pdf_sem_ajuste_girado_vai_com_rotacao_e_continua_texto(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (pdf_com_textos(["UM"]), "1.pdf"), (pdf_com_textos(["DOIS"]), "2.pdf"))]
    saida = _salvar(cliente, pasta_principal, [{"id": ids[0], "giro": 90}, {"id": ids[1], "giro": 0}])
    paginas = PdfReader(saida).pages
    assert paginas[0].rotation == 90
    assert paginas[1].rotation == 0
    assert _textos(saida) == ["UM", "DOIS"]   # texto extraível: não virou imagem


def test_jpeg_sem_ajuste_girado_180_fica_de_cabeca_para_baixo(cliente, pasta_principal):
    foto = jpeg_colorido((255, 255, 255), marca=((255, 0, 0), 200))   # quadrado vermelho no canto superior esquerdo
    id_ = enviar(cliente, (foto, "a.jpg"))[0]["id"]
    saida = _salvar(cliente, pasta_principal, [{"id": id_, "giro": 180}])
    r, g, b = _pixel(saida, 0, 0.05, 0.05)
    assert r > 200 and g > 200 and b > 200            # o canto superior esquerdo agora é branco
    r, g, b = _pixel(saida, 0, 0.95, 0.95)
    assert r > 200 and g < 80 and b < 80              # o quadrado foi para o canto inferior direito


def test_jpeg_sem_ajuste_girado_90_vira_paisagem(cliente, pasta_principal):
    id_ = enviar(cliente, (jpeg_colorido((255, 255, 255), 600, 800), "a.jpg"))[0]["id"]
    pagina = PdfReader(_salvar(cliente, pasta_principal, [{"id": id_, "giro": 90}])).pages[0]
    assert float(pagina.mediabox.width) > float(pagina.mediabox.height)


def test_folha_girada_e_ajustada_tem_giro_e_ajuste(cliente, pasta_principal):
    id_ = enviar(cliente, (jpeg_colorido((100, 100, 100), 300, 400), "a.jpg"))[0]["id"]
    saida = _salvar(cliente, pasta_principal, [{"id": id_, "giro": 90, "brilho": 60, "contraste": 0, "realce": False}])
    pagina = PdfReader(saida).pages[0]
    assert float(pagina.mediabox.width) > float(pagina.mediabox.height)   # girou
    r, _, _ = _pixel(saida, 0, 0.5, 0.5)
    assert r > 100 + 20                                                    # clareou


def test_pdf_ajustado_e_girado_tem_giro_e_ajuste(cliente, pasta_principal):
    id_ = enviar(cliente, (pdf_com_textos(["UM"]), "1.pdf"))[0]["id"]
    saida = _salvar(cliente, pasta_principal, [{"id": id_, "giro": 90, "brilho": 30, "contraste": 0, "realce": False}])
    pagina = PdfReader(saida).pages[0]
    assert float(pagina.mediabox.width) > float(pagina.mediabox.height)   # virou imagem já girada


@pytest.mark.parametrize("giro, esperado", [(270, 270), (-90, 270), (450, 90), (360, 0), (-180, 180)])
def test_giro_e_normalizado_no_pdf(tmp_path, giro, esperado):
    origem = tmp_path / "a.pdf"
    origem.write_bytes(pdf_com_textos(["UM"]).getvalue())
    saida = tmp_path / "saida.pdf"
    pdfs.mesclar([(origem, "pdf", giro, None)]).write(saida)
    assert PdfReader(saida).pages[0].rotation == esperado


@pytest.mark.parametrize("giro", [270, -90])
def test_giro_270_e_menos_90_de_jpeg_viram_paisagem(tmp_path, giro):
    origem = tmp_path / "a.jpg"
    origem.write_bytes(jpeg_colorido((255, 255, 255), 600, 800, marca=((255, 0, 0), 200)).getvalue())
    saida = tmp_path / "saida.pdf"
    pdfs.mesclar([(origem, "img", giro, None)]).write(saida)
    pagina = PdfReader(saida).pages[0]
    assert float(pagina.mediabox.width) > float(pagina.mediabox.height)
    # 270° horário = 90° anti-horário: o quadrado do canto superior esquerdo vai para o inferior esquerdo
    r, g, b = _pixel(saida, 0, 0.03, 0.97)
    assert r > 200 and g < 80 and b < 80


# ---------- .zip (formato Drive) e pasta: reordenar + girar folha de PDF sem ajuste ----------

def _zip_drive_com_conteudo():
    """Imita o .zip do Drive: pasta do paciente, pag1/pag2/pag10 e lixo do macOS (com iscas de conteúdo
    que não podem aparecer no PDF final)."""
    import io
    import zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("FULANO DE TAL/pag10.pdf", pdf_com_textos(["P10"]).getvalue())
        z.writestr("FULANO DE TAL/pag2.jpg", jpeg_colorido((255, 0, 0)).getvalue())
        z.writestr("FULANO DE TAL/pag1.pdf", pdf_com_textos(["P1A", "P1B"]).getvalue())
        z.writestr("FULANO DE TAL/.DS_Store", b"x")
        z.writestr("__MACOSX/FULANO DE TAL/._pag1.pdf", b"x")
        z.writestr("__MACOSX/FULANO DE TAL/pag3.pdf", pdf_com_textos(["ISCA"]).getvalue())
    b.seek(0)
    return b


def test_zip_do_drive_reordenado_e_girado_sai_certo_no_pdf(cliente, pasta_principal):
    resp = enviar(cliente, (_zip_drive_com_conteudo(), "FULANO DE TAL-20261014T190644Z-001.zip"))
    assert [r["nome"] for r in resp] == ["pag1.pdf · p1", "pag1.pdf · p2", "pag2.jpg", "pag10.pdf"]   # ordem natural inicial
    p1a, p1b, foto, p10 = (r["id"] for r in resp)

    # na tela: pag10, pag1·p2 (girada 90°), foto, pag1·p1; pag10 girada 270° (= -90°)
    saida = _salvar(cliente, pasta_principal, [{"id": p10, "giro": 270}, {"id": p1b, "giro": 90},
                                               {"id": foto, "giro": 0}, {"id": p1a, "giro": 0}])
    paginas = PdfReader(saida).pages
    assert len(paginas) == 4
    assert [p.extract_text().strip() for p in paginas] == ["P10", "P1B", "", "P1A"]   # iscas do __MACOSX ficaram de fora
    assert [p.rotation for p in paginas] == [270, 90, 0, 0]
    r, g, b = _pixel(saida, 2, 0.5, 0.5)
    assert r > 200 and g < 60 and b < 60                                              # a terceira é o JPEG vermelho


def test_pasta_reordenada_e_girada_sai_certo_no_pdf(cliente, pasta_principal):
    # o navegador manda cada arquivo da pasta como "PASTA/arquivo" e já em ordem natural (pag1, pag2, pag10)
    resp = enviar(cliente, (pdf_com_textos(["P1"]), "FULANO DE TAL/pag1.pdf"),
                  (pdf_com_textos(["P2"]), "FULANO DE TAL/pag2.pdf"),
                  (pdf_com_textos(["P10"]), "FULANO DE TAL/pag10.pdf"))
    assert [r["nome"] for r in resp] == ["pag1.pdf", "pag2.pdf", "pag10.pdf"]
    p1, p2, p10 = (r["id"] for r in resp)

    saida = _salvar(cliente, pasta_principal, [{"id": p10, "giro": 0}, {"id": p1, "giro": 0}, {"id": p2, "giro": 90}])
    paginas = PdfReader(saida).pages
    assert [p.extract_text().strip() for p in paginas] == ["P10", "P1", "P2"]
    assert [p.rotation for p in paginas] == [0, 0, 90]
