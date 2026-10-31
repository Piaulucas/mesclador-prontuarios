"""Controle das abas do navegador no macOS (Chrome e Safari), via AppleScript.

Usado para: (1) ao clicar no ícone com o app já aberto, mostrar a aba existente
em vez de abrir outra; (2) ao encerrar o app, fechar a aba dele; (3) mostrar um aviso
na tela quando o app não consegue abrir (o app roda sem Terminal, então o log não é visto).
Na primeira vez o macOS pede permissão para controlar o navegador.
Fora do macOS, ou sem permissão, as funções só devolvem False.
"""

import platform
import subprocess

# Percorre as abas abertas do Chrome e do Safari (só se já estiverem abertos)
# e executa a ação na primeira aba cujo endereço começa com o do app.
# O endereço-base encontra Início, Mesclar, Converter e Auditoria na mesma porta.
_SCRIPT = """
on run argv
  set alvo to item 1 of argv
  set acao to item 2 of argv
  if application "Google Chrome" is running then
    tell application "Google Chrome"
      repeat with w in windows
        set i to 0
        repeat with t in tabs of w
          set i to i + 1
          if URL of t starts with alvo then
            if acao is "fechar" then
              close t
            else
              set active tab index of w to i
              set index of w to 1
              activate
            end if
            return "ok"
          end if
        end repeat
      end repeat
    end tell
  end if
  if application "Safari" is running then
    tell application "Safari"
      repeat with w in windows
        repeat with t in tabs of w
          if URL of t starts with alvo then
            if acao is "fechar" then
              close t
            else
              set current tab of w to t
              set index of w to 1
              activate
            end if
            return "ok"
          end if
        end repeat
      end repeat
    end tell
  end if
  return "nao"
end run
"""


def _executar(url, acao):
    if platform.system() != "Darwin":
        return False
    try:
        r = subprocess.run(["osascript", "-e", _SCRIPT, url, acao],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "ok"
    except Exception:
        return False


def focar_aba(url):
    """Traz para a frente a aba do app. True se encontrou."""
    return _executar(url, "focar")


def fechar_aba(url):
    """Fecha a aba do app. True se encontrou."""
    return _executar(url, "fechar")


def avisar(mensagem):
    """Mostra um diálogo do macOS com a mensagem. True se foi mostrado; fora do macOS
    ou se o osascript falhar, devolve False (quem chama já registrou a mensagem no log)."""
    if platform.system() != "Darwin":
        return False
    try:
        # a mensagem vai como argumento (não dentro do script) para não precisar escapar aspas;
        # "giving up after" fecha o diálogo sozinho se ninguém clicar, para o app não ficar preso
        r = subprocess.run(
            ["osascript",
             "-e", "on run argv",
             "-e", 'display dialog (item 1 of argv) with title "Área de trabalho" buttons {"OK"} '
                   'default button "OK" with icon caution giving up after 120',
             "-e", "end run",
             mensagem],
            capture_output=True, text=True, timeout=130)
        return r.returncode == 0
    except Exception:
        return False
