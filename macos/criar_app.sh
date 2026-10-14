#!/bin/bash
# Cria o ícone ~/Applications/Mesclador.app, que abre o Mesclador com dois cliques.
# Rode uma vez (e de novo se mudar a pasta do projeto de lugar):
#     bash macos/criar_app.sh
set -euo pipefail

PROJETO="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO="$HOME/Applications/Mesclador.app"
ICONE="$PROJETO/macos/icone.png"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

chmod +x "$PROJETO/macos/abrir.sh"

# 1) O app é um AppleScript mínimo que chama o abrir.sh
cat > "$TMP/app.applescript" <<APPLESCRIPT
do shell script quoted form of "$PROJETO/macos/abrir.sh"
APPLESCRIPT
mkdir -p "$HOME/Applications"
rm -rf "$DESTINO"
osacompile -o "$DESTINO" "$TMP/app.applescript"

# 2) Ícone: gera todos os tamanhos que o macOS pede a partir do PNG de 1024px
ICONSET="$TMP/icone.iconset"
mkdir "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$ICONE" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$ICONE" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$DESTINO/Contents/Resources/applet.icns"

# Nas versões recentes do macOS o app do AppleScript traz o ícone padrão dentro do
# Assets.car, que tem prioridade sobre o applet.icns. Remove e aponta para o nosso.
PLIST="$DESTINO/Contents/Info.plist"
rm -f "$DESTINO/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet" "$PLIST"

# Alterar o app invalida a assinatura; reassina localmente para o macOS não bloquear
codesign --force --deep --sign - "$DESTINO" >/dev/null 2>&1 || true
touch "$DESTINO"   # faz o Finder atualizar o ícone

echo "Pronto: $DESTINO"
echo "Arraste-o para o Dock para abrir com um clique."
echo "Se mover a pasta do projeto, rode este script de novo."
