#!/usr/bin/env bash
# Buduje Perun-VERSION.flatpak
set -euo pipefail
cd "$(dirname "$0")"

VERSION=$(python3 -c "import pathlib,re; t=pathlib.Path('perun.py').read_text(); print(re.search(r'VERSION\\s*=\\s*\"([^\"]+)\"', t).group(1))")
BUNDLE="dist/Perun-${VERSION}.flatpak"
REPO_DIR="flatpak/repo"
MANIFEST="flatpak/pl.gorian.Perun.yml"
APP_ID="pl.gorian.Perun"

mkdir -p dist flatpak/build flatpak/repo

BUILDER=()
if command -v flatpak-builder >/dev/null 2>&1; then
  BUILDER=(flatpak-builder)
elif flatpak info --user org.flatpak.Builder >/dev/null 2>&1 || flatpak info org.flatpak.Builder >/dev/null 2>&1; then
  BUILDER=(
    flatpak run
    --filesystem=home
    --share=network
    --env=FLATPAK_USER_DIR="${HOME}/.local/share/flatpak"
    --command=flatpak-builder
    org.flatpak.Builder
  )
else
  echo "Nie znaleziono flatpak-builder."
  echo "  sudo pacman -S flatpak-builder"
  echo "  albo: flatpak install --user flathub org.flatpak.Builder"
  exit 1
fi

echo "=== Perun ${VERSION} Flatpak ==="
echo "Using: ${BUILDER[*]}"

flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo || true
flatpak install --user -y flathub org.gnome.Platform//50 org.gnome.Sdk//50 || true

echo "==> build"
"${BUILDER[@]}" --force-clean --ccache --user \
  --install-deps-from=flathub \
  --repo="$REPO_DIR" \
  flatpak/build "$MANIFEST"

echo "==> bundle → $BUNDLE"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  "$REPO_DIR" "$BUNDLE" "$APP_ID"

ln -sfn "$(basename "$BUNDLE")" dist/Perun.flatpak

echo
echo "OK. $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
echo "Instalacja:"
echo "  ./install.sh --flatpak"
echo "  albo: flatpak install --user $BUNDLE && flatpak run $APP_ID"
