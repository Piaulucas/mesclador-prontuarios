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


# ---------- reinício quando a instância aberta está desatualizada ----------
# Tudo com mocks: nenhum servidor real sobe e nenhum processo é encerrado.

import io
import urllib.error
from types import SimpleNamespace

import pytest

from mesclador import __main__ as principal


class RespostaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def resposta(texto):
    return RespostaFalsa(texto.encode())


def erro_http(codigo):
    return urllib.error.HTTPError("http://127.0.0.1/versao", codigo, "erro", {}, None)


def test_instancia_com_mesma_versao_nao_esta_desatualizada(monkeypatch):
    monkeypatch.setattr(principal.urllib.request, "urlopen", lambda *a, **k: resposta("abc"))
    assert principal.instancia_desatualizada(5050, "abc") is False


def test_instancia_com_versao_diferente_esta_desatualizada(monkeypatch):
    monkeypatch.setattr(principal.urllib.request, "urlopen", lambda *a, **k: resposta("velha"))
    assert principal.instancia_desatualizada(5050, "nova") is True


def test_instancia_sem_rota_versao_404_esta_desatualizada(monkeypatch):
    def urlopen(*a, **k):
        raise erro_http(404)
    monkeypatch.setattr(principal.urllib.request, "urlopen", urlopen)
    assert principal.instancia_desatualizada(5050, "nova") is True


@pytest.mark.parametrize("erro", [TimeoutError(), erro_http(500)])
def test_erro_inesperado_ao_consultar_versao_nao_encerra_a_instancia(monkeypatch, erro):
    def urlopen(*a, **k):
        raise erro
    monkeypatch.setattr(principal.urllib.request, "urlopen", urlopen)
    assert principal.instancia_desatualizada(5050, "nova") is False


def test_pedir_encerramento_usa_post_na_rota_encerrar(monkeypatch):
    pedidos = []
    monkeypatch.setattr(principal.urllib.request, "urlopen",
                        lambda req, **k: pedidos.append(req) or resposta("{}"))
    principal.pedir_encerramento(5050)
    assert pedidos[0].full_url == "http://127.0.0.1:5050/encerrar"
    assert pedidos[0].get_method() == "POST"


def test_esperar_porta_livre_volta_quando_a_porta_libera(monkeypatch):
    estados = iter([True, True, False])
    monkeypatch.setattr(principal, "porta_ocupada", lambda p: next(estados))
    monkeypatch.setattr(principal.time, "sleep", lambda s: None)
    assert principal.esperar_porta_livre(5050, limite=5) is True


def test_esperar_porta_livre_desiste_no_limite(monkeypatch):
    monkeypatch.setattr(principal, "porta_ocupada", lambda p: True)
    monkeypatch.setattr(principal.time, "sleep", lambda s: None)
    relogio = iter(range(0, 100))
    monkeypatch.setattr(principal.time, "monotonic", lambda: next(relogio))
    assert principal.esperar_porta_livre(5050, limite=3) is False


@pytest.fixture
def partida(monkeypatch):
    """Isola main(): registra o que foi chamado em vez de mexer em rede, navegador ou processos."""
    chamadas = []
    estado = SimpleNamespace(rodando=False, desatualizada=False, ocupada=False, liberou=True)
    config = SimpleNamespace(porta=5050)

    class AppFalso:
        config = {"PASTA_TEMP": "/nao/existe"}

        def run(self, **kw):
            chamadas.append(("run", kw["port"]))

    monkeypatch.setattr(principal.cfg, "carregar", lambda *a: config)
    monkeypatch.setattr(principal.versao, "calcular_versao", lambda: "nova")
    monkeypatch.setattr(principal, "ja_esta_rodando", lambda p: estado.rodando)
    monkeypatch.setattr(principal, "instancia_desatualizada", lambda p, v: estado.desatualizada)
    monkeypatch.setattr(principal, "porta_ocupada", lambda p: estado.ocupada)
    monkeypatch.setattr(principal, "pedir_encerramento", lambda p: chamadas.append(("encerrar", p)))
    monkeypatch.setattr(principal, "esperar_porta_livre", lambda p: estado.liberou)
    monkeypatch.setattr(principal, "mostrar", lambda url: chamadas.append(("mostrar", url)))
    monkeypatch.setattr(principal, "create_app",
                        lambda c, versao=None: chamadas.append(("create_app", versao)) or AppFalso())
    monkeypatch.setattr(principal.threading, "Timer",
                        lambda *a, **k: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(principal.sys, "argv", ["mesclador"])
    return SimpleNamespace(estado=estado, chamadas=chamadas)


def nomes(partida):
    return [c[0] for c in partida.chamadas]


def test_porta_livre_sobe_normalmente(partida):
    principal.main()
    assert nomes(partida) == ["create_app", "run"]
    assert ("create_app", "nova") in partida.chamadas


def test_instancia_com_hash_igual_so_mostra_a_janela(partida):
    partida.estado.rodando = True
    partida.estado.desatualizada = False
    principal.main()
    assert partida.chamadas == [("mostrar", "http://127.0.0.1:5050")]


def test_instancia_com_hash_diferente_encerra_e_sobe_a_nova(partida, capsys):
    partida.estado.rodando = True
    partida.estado.desatualizada = True
    principal.main()
    assert nomes(partida) == ["encerrar", "create_app", "run"]
    assert "desatualizado" in capsys.readouterr().out   # fica no log (~/Library/Logs/mesclador.log)


def test_porta_ocupada_por_outro_servico_nao_chama_encerrar(partida):
    partida.estado.rodando = False
    partida.estado.ocupada = True
    with pytest.raises(SystemExit) as e:
        principal.main()
    assert "outro programa" in str(e.value)
    assert partida.chamadas == []


def test_timeout_ao_liberar_a_porta_nao_sobe_e_avisa(partida):
    partida.estado.rodando = True
    partida.estado.desatualizada = True
    partida.estado.liberou = False
    with pytest.raises(SystemExit) as e:
        principal.main()
    assert "Encerrar o app" in str(e.value)
    assert nomes(partida) == ["encerrar", "mostrar"]   # mostra a janela antiga; não cria app novo
