import io
import zipfile

import pytest
from PIL import Image, ImageStat

from mesclador import imagens
from tests.conftest import jpeg, pdf


@pytest.fixture
def downloads(tmp_path, cliente):
    d = tmp_path / "Downloads"
    d.mkdir()
    cliente.application.config["PASTA_DOWNLOADS"] = d
    return d


def enviar(cliente, *arquivos):
    return cliente.post("/converter/enviar", data={"arquivos": list(arquivos)},
                        content_type="multipart/form-data").get_json()


def exportar(cliente, ids, **extra):
    corpo = {"nome": "MARIA SOUZA", "paginas": [{"id": i, "giro": 0} for i in ids]}
    corpo.update(extra)
    return cliente.post("/converter/exportar", json=corpo)


def test_tela_converter_abre(cliente):
    html = cliente.get("/converter").get_data(as_text=True)
    assert "<h1>Converter em JPG</h1>" in html and "Exportar JPG" in html
    assert "Exportar ${paginas.length} JPG" in html


def test_converter_pede_a_pasta_so_quando_ha_paginas(cliente):
    html = cliente.get("/converter").get_data(as_text=True)
    # o nome da pasta fica na barra de exportação, que começa escondida e aparece com as páginas
    assert '<div class="barra-fixa" id="barraExportar" role="region" aria-label="Exportar os JPG" hidden>' in html
    assert html.index('id="barraExportar"') < html.index('id="nome"') < html.index('id="exportar"')
    assert '$("barraExportar").hidden = !paginas.length;' in html
    assert "Pasta de saída" not in html
    assert f"const DPI = {imagens.DPI_EXPORTACAO};" in html


def test_converter_ajustes_ficam_no_cartao_da_pagina(cliente):
    html = cliente.get("/converter").get_data(as_text=True)
    assert 'if (escolhida) { c.appendChild($("ajustesPagina")); }' in html
    assert '$("reserva").appendChild($("ajustesPagina"));' in html
    for id_ in ("brilho", "contraste", "realce", "aplicarTodas", "restaurar"):
        assert f'id="{id_}"' in html


def test_pdf_vira_uma_pagina_por_folha(cliente):
    r = enviar(cliente, (pdf(3), "prontuario.pdf"))
    assert [p["nome"] for p in r["paginas"]] == ["prontuario.pdf · p1", "prontuario.pdf · p2", "prontuario.pdf · p3"]
    assert r["sugestao_nome"] == "prontuario"


def test_zip_sugere_nome_do_paciente(cliente):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("MARIA SOUZA/a.pdf", pdf(2).getvalue())
        z.writestr("MARIA SOUZA/b.jpg", jpeg().getvalue())
    b.seek(0)
    r = enviar(cliente, (b, "MARIA SOUZA-20261014T190644Z-001.zip"))
    assert len(r["paginas"]) == 3 and r["sugestao_nome"] == "MARIA SOUZA"


def test_exporta_jpgs_numerados_em_pasta_nova(cliente, downloads):
    ids = [p["id"] for p in enviar(cliente, (pdf(2), "a.pdf"), (jpeg(), "b.jpg"))["paginas"]]
    r = exportar(cliente, ids).get_json()
    pasta = downloads / "MARIA SOUZA"
    assert r["quantidade"] == 3 and r["pasta"] == str(pasta)
    assert sorted(p.name for p in pasta.iterdir()) == [f"MARIA SOUZA - 0{i}.jpg" for i in (1, 2, 3)]
    with Image.open(pasta / "MARIA SOUZA - 01.jpg") as img:
        assert img.format == "JPEG" and round(img.info["dpi"][0]) == imagens.DPI_EXPORTACAO


def test_exportar_de_novo_nao_sobrescreve(cliente, downloads):
    ids = [p["id"] for p in enviar(cliente, (jpeg(), "b.jpg"))["paginas"]]
    exportar(cliente, ids)
    r = exportar(cliente, ids).get_json()
    assert r["nome_pasta"] == "MARIA SOUZA (2)"


def test_exportar_sem_nome_ou_sem_paginas_da_erro(cliente, downloads):
    ids = [p["id"] for p in enviar(cliente, (jpeg(), "b.jpg"))["paginas"]]
    assert exportar(cliente, ids, nome="  ").status_code == 400
    assert exportar(cliente, []).status_code == 400


def test_giro_na_exportacao(cliente, downloads):
    ids = [p["id"] for p in enviar(cliente, (jpeg(600, 800), "b.jpg"))["paginas"]]
    exportar(cliente, ids, paginas=[{"id": ids[0], "giro": 90}])
    with Image.open(downloads / "MARIA SOUZA" / "MARIA SOUZA - 01.jpg") as img:
        assert img.width > img.height


def test_ajustes_por_pagina_na_exportacao(cliente, downloads):
    cinza = io.BytesIO()
    Image.new("RGB", (100, 100), (120, 120, 120)).save(cinza, "PNG")
    ids = [enviar(cliente, (io.BytesIO(cinza.getvalue()), f"c{n}.png"))["paginas"][0]["id"] for n in (1, 2)]
    exportar(cliente, ids, paginas=[{"id": ids[0], "giro": 0, "brilho": 60},
                                    {"id": ids[1], "giro": 0}])

    def media(n):
        with Image.open(downloads / "MARIA SOUZA" / f"MARIA SOUZA - {n:02d}.jpg") as img:
            return ImageStat.Stat(img.convert("L")).mean[0]

    assert media(1) > 120 + 10      # 1ª ficou mais clara que o original
    assert abs(media(2) - 120) < 2  # 2ª ficou igual ao original


def test_previa_responde_com_ajustes(cliente):
    [p] = enviar(cliente, (jpeg(), "b.jpg"))["paginas"]
    r = cliente.get(f"/converter/previa/{p['id']}?tam=200&brilho=40&contraste=-20&realce=1")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"


def test_mostrar_so_pastas_exportadas(cliente, downloads):
    assert cliente.post("/converter/mostrar", json={"pasta": "/etc"}).status_code == 404


def test_ajustes_mudam_a_imagem():
    cinza = Image.new("RGB", (50, 50), (120, 120, 120))
    assert imagens.ajustar(cinza, brilho=50).getpixel((0, 0))[0] > 120
    assert imagens.ajustar(cinza, brilho=-50).getpixel((0, 0))[0] < 120
    assert imagens.ajustar(cinza).getpixel((0, 0)) == (120, 120, 120)      # sem ajuste = igual
    colorida = Image.new("RGB", (50, 50), (200, 30, 30))
    r, g, b = imagens.ajustar(colorida, realce=True).getpixel((0, 0))
    assert r == g == b                                                       # realce = tons de cinza


def test_pasta_livre(tmp_path):
    (tmp_path / "X").mkdir()
    (tmp_path / "X (2)").mkdir()
    assert imagens.pasta_livre(tmp_path, "X").name == "X (3)"
