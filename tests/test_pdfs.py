from pypdf import PdfReader

from mesclador import pdfs
from tests.conftest import jpeg, pdf


def salvar(tmp_path, nome, conteudo):
    caminho = tmp_path / nome
    caminho.write_bytes(conteudo.getvalue())
    return caminho


def test_tipo_do_arquivo():
    assert pdfs.tipo_do_arquivo("a.PDF") == "pdf"
    assert pdfs.tipo_do_arquivo("foto.jpeg") == "img"
    assert pdfs.tipo_do_arquivo("nota.docx") is None


def test_limpar_nome_arquivo():
    assert pdfs.limpar_nome_arquivo('A/B:C*"D') == "ABCD"


def test_miniatura_conta_paginas(tmp_path):
    origem = salvar(tmp_path, "a.pdf", pdf(3))
    assert pdfs.gerar_miniatura(origem, "pdf", tmp_path / "m.jpg") == 3
    assert (tmp_path / "m.jpg").exists()


def test_mesclar_respeita_a_ordem_e_o_giro(tmp_path):
    p = salvar(tmp_path, "a.pdf", pdf(2))
    img = salvar(tmp_path, "b.jpg", jpeg(600, 800))   # retrato
    writer = pdfs.mesclar([(img, "img", 90), (p, "pdf", 180)])
    saida = tmp_path / "saida.pdf"
    writer.write(saida)
    paginas = PdfReader(saida).pages

    assert len(paginas) == 3
    largura, altura = float(paginas[0].mediabox.width), float(paginas[0].mediabox.height)
    assert largura > altura                     # a imagem girada virou paisagem
    assert paginas[1].rotation == 180 and paginas[2].rotation == 180
