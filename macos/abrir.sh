#!/bin/zsh -l
# Abre o Mesclador em segundo plano (sem Terminal). Usado pelo ícone Mesclador.app.
# O "-l" carrega o PATH do seu usuário, para achar o mesmo python3 do Terminal.
# Se o app já estiver aberto, o Python só traz o navegador para a frente.

cd "${0:A:h}/.." || exit 1
mkdir -p "$HOME/Library/Logs"
nohup python3 -m mesclador >> "$HOME/Library/Logs/mesclador.log" 2>&1 &
