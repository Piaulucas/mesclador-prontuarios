"""Controle das abas do navegador no macOS (Chrome e Safari), via AppleScript.

Usado para: (1) ao clicar no ícone com o app já aberto, mostrar a aba existente
em vez de abrir outra; (2) ao encerrar o app, fechar a aba dele.
Na primeira vez o macOS pede permissão para controlar o navegador.
Fora do macOS, ou sem permissão, as funções só devolvem False.
"""

import platform
import subprocess

# Percorre as abas abertas do Chrome e do Safari (só se já estiverem abertos)
# e executa a ação na primeira aba cujo endereço começa com o do app.
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
