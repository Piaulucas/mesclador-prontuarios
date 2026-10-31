"""Ponto de entrada:  python3 -m mesclador  [caminho/do/config.toml]"""

import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from . import config as cfg
from . import navegador, versao
from .web import IDENTIDADE, create_app

ESPERA_PORTA_LIVRE = 10   # segundos esperando a instância antiga encerrar
AVISO_VERSAO_ANTIGA = ("Uma versão antiga da Área de trabalho ainda está aberta. "
                       "Clique em 'Encerrar o app' na tela e abra de novo.")


def ja_esta_rodando(porta):
    """True se o Mesclador já está aberto nesta porta (ex.: clicou no ícone duas vezes)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/ping", timeout=1) as r:
            return r.read().decode() == IDENTIDADE
    except Exception:
        return False


def instancia_desatualizada(porta, versao_atual):
    """True se a instância aberta roda outro código (ou é antiga demais para ter /versao).
    Se não der para saber (erro de rede, resposta estranha), diz False: melhor não encerrar à toa."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/versao", timeout=1) as r:
            return r.read().decode() != versao_atual
    except urllib.error.HTTPError as e:
        return e.code == 404
    except Exception:
        return False


def pedir_encerramento(porta):
    """Pede à instância aberta que se encerre (a mesma rota do botão Encerrar o app)."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/encerrar", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=2).close()
    except Exception:
        pass   # se não encerrar, esperar_porta_livre acusa


def esperar_porta_livre(porta, limite=None):
    """Espera a porta ficar livre. False se passar do limite (padrão: ESPERA_PORTA_LIVRE)."""
    fim = time.monotonic() + (ESPERA_PORTA_LIVRE if limite is None else limite)
    while porta_ocupada(porta):
        if time.monotonic() >= fim:
            return False
        time.sleep(0.2)
    return True


def mostrar(url):
    """Mostra o app: reaproveita a aba aberta; se não houver, abre uma nova."""
    if not navegador.focar_aba(url):
        webbrowser.open(url)


def porta_ocupada(porta):
    """True se outro programa (que não é o Mesclador) está usando a porta."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main():
    config = cfg.carregar(sys.argv[1] if len(sys.argv) > 1 else None)
    url = f"http://127.0.0.1:{config.porta}"

    versao_atual = versao.calcular_versao()

    # Segunda abertura: em vez de dar erro de porta em uso, só mostra a janela que já existe
    # (a menos que ela rode um código diferente do da pasta: aí encerra a antiga e sobe a nova)
    if ja_esta_rodando(config.porta):
        if not instancia_desatualizada(config.porta, versao_atual):
            print(f"A Área de trabalho já está aberta em {url}")
            mostrar(url)
            return
        print(f"A Área de trabalho em {url} está com código desatualizado (diferente do da pasta); reiniciando.")
        pedir_encerramento(config.porta)
        if not esperar_porta_livre(config.porta):
            mostrar(url)   # deixa a janela antiga à vista, com o botão Encerrar o app
            navegador.avisar(AVISO_VERSAO_ANTIGA)   # o app roda sem Terminal: o log ninguém vê
            raise SystemExit(f"A Área de trabalho aberta em {url} está desatualizada e não encerrou sozinha. "
                             "Clique em 'Encerrar o app' na janela dele e abra de novo.")
    elif porta_ocupada(config.porta):
        raise SystemExit(f"A porta {config.porta} está sendo usada por outro programa. "
                         "Troque 'porta' no config.toml.")

    app = create_app(config, versao=versao_atual)
    threading.Timer(1.0, lambda: mostrar(url)).start()
    print(f"Área de trabalho aberta em {url}  (feche pelo botão Encerrar ou Ctrl+C)")
    try:
        # 127.0.0.1 = acessível só deste computador
        app.run(host="127.0.0.1", port=config.porta, debug=False)
    finally:
        shutil.rmtree(app.config["PASTA_TEMP"], ignore_errors=True)


if __name__ == "__main__":
    main()
