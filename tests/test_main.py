import socket

from mesclador import navegador
from mesclador.__main__ import ja_esta_rodando, porta_ocupada


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_porta_livre_nao_esta_rodando():
    p = porta_livre()
    assert not ja_esta_rodando(p)
    assert not porta_ocupada(p)


def test_porta_de_outro_programa_nao_e_o_mesclador():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        p = s.getsockname()[1]
        assert porta_ocupada(p)
        assert not ja_esta_rodando(p)


def test_navegador_fora_do_mac_nao_faz_nada(monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert navegador.focar_aba("http://127.0.0.1:5050") is False
    assert navegador.fechar_aba("http://127.0.0.1:5050") is False
