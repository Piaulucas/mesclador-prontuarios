import os

from mesclador.versao import calcular_versao


def montar_codigo(raiz):
    (raiz / "templates").mkdir(parents=True)
    (raiz / "modulo.py").write_text("x = 1\n")
    (raiz / "templates" / "index.html").write_text("<p>Olá</p>")
    return raiz


def test_hash_muda_quando_um_py_muda(tmp_path):
    raiz = montar_codigo(tmp_path / "codigo")
    antes = calcular_versao(raiz)
    (raiz / "modulo.py").write_text("x = 2\n")
    assert calcular_versao(raiz) != antes


def test_hash_muda_quando_um_template_muda(tmp_path):
    raiz = montar_codigo(tmp_path / "codigo")
    antes = calcular_versao(raiz)
    (raiz / "templates" / "index.html").write_text("<p>Outro texto</p>")
    assert calcular_versao(raiz) != antes


def test_hash_nao_muda_so_por_tocar_o_arquivo(tmp_path):
    raiz = montar_codigo(tmp_path / "codigo")
    antes = calcular_versao(raiz)
    for arquivo in (raiz / "modulo.py", raiz / "templates" / "index.html"):
        os.utime(arquivo, (1_000_000_000, 1_000_000_000))   # só a data de modificação muda
    assert calcular_versao(raiz) == antes


def test_hash_ignora_cache_e_arquivos_ocultos(tmp_path):
    raiz = montar_codigo(tmp_path / "codigo")
    antes = calcular_versao(raiz)
    (raiz / "__pycache__").mkdir()
    (raiz / "__pycache__" / "modulo.cpython-312.pyc").write_bytes(b"\x00\x01")
    (raiz / "templates" / ".DS_Store").write_bytes(b"lixo do Finder")
    assert calcular_versao(raiz) == antes


def test_hash_muda_ao_novo_arquivo_ou_renomear(tmp_path):
    raiz = montar_codigo(tmp_path / "codigo")
    antes = calcular_versao(raiz)
    (raiz / "modulo.py").rename(raiz / "outro.py")
    assert calcular_versao(raiz) != antes


def test_hash_do_codigo_real_e_estavel():
    assert calcular_versao() == calcular_versao()
