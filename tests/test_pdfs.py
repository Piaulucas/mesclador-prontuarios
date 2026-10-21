from pypdf import PdfReader
import pytest

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


@pytest.mark.parametrize("nome, documento", [
    ("Formulario.jpg", "formulario"), ("FORMULÁRIO.pdf", "formulario"),
    ("Formulaio.jpg", "formulario"), ("formulario_2.jpg", "formulario"),
    ("BDV.jpg", "bdv"), ("bdv 1.jpg", "bdv"), ("BDV-assinado.pdf", "bdv"),
    ("Boletim de Viagem.pdf", "bdv"), ("boletim_de_viagem.jpg", "bdv"),
    ("Boletim.jpg", "bdv"), ("FDR.jpg", "fdr"), ("fdr2.jpg", "fdr"),
    ("Ficha de Remocao.pdf", "fdr"), ("ficha_de_remoção.jpg", "fdr"),
    ("Ficha.jpg", "fdr"), ("BDV.pdf · p2", "bdv"),
    ("scan_1.jpg", None), ("abdvx.jpg", None), ("fdrx.jpg", None),
    ("viagem.jpg", None), ("remocao.jpg", None), ("Ficha Formulario.jpg", None),
])
def test_documento_do_arquivo(nome, documento):
    assert pdfs.documento_do_arquivo(nome) == documento


def test_ordenar_lote_mantem_continuacoes_e_sobra():
    nomes = ["scan_9.jpg", "FDR.jpg", "BDV 1.jpg", "scan_2.jpg", "BDV 2.jpg",
             "BDV 10.jpg", "Formulario.jpg"]
    itens = [{"nome": nome} for nome in nomes]
    assert [item["nome"] for item in pdfs.ordenar_lote(itens)] == [
        "Formulario.jpg", "BDV 1.jpg", "scan_2.jpg", "BDV 2.jpg", "BDV 10.jpg",
        "FDR.jpg", "scan_9.jpg"]


def test_ordenar_lote_mantem_paginas_do_pdf_juntas():
    nomes = ["FDR.jpg", "BDV.pdf · p1", "BDV.pdf · p2", "scan_2.jpg", "Formulario.jpg"]
    assert [item["nome"] for item in pdfs.ordenar_lote([{"nome": nome} for nome in nomes])] == [
        "Formulario.jpg", "BDV.pdf · p1", "BDV.pdf · p2", "scan_2.jpg", "FDR.jpg"]


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
