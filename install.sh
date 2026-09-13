#!/usr/bin/env bash
# Instalator Perun — native albo Flatpak.
#
# Znajomi (jedna komenda):
#   curl -fsSL https://raw.githubusercontent.com/GorianWaco/perun/main/install.sh | bash
#
# Z katalogu projektu:
#   ./install.sh              # native, z zależnościami
#   ./install.sh --flatpak    # Flatpak z GitHub Releases albo lokalnego .flatpak
#   ./install.sh --uninstall

set -euo pipefail

REPO="GorianWaco/perun"
APP_NAME="Perun"
APP_ID="perun"
FLATPAK_ID="pl.gorian.Perun"
OLD_ID="steam-launch"
VERSION="1.5.0"
FLATHUB_REPO="https://dl.flathub.org/repo/flathub.flatpakrepo"

MODE="native"
PREFIX=""
DRY_RUN=0
NO_DEPS=0
LOCAL_BUNDLE=""
UNINSTALL=0

usage() {
  cat <<EOF
Użycie: $0 [opcje]

  (domyślnie)        instalacja native (~/.local) z zależnościami
  --flatpak          Flatpak z GitHub Releases (albo --local PLIK)
  --local PLIK       zainstaluj istniejący plik .flatpak
  --system           native do /usr/local (root)
  --prefix DIR       native do własnego prefiksu
  --no-deps          nie instaluj pakietów systemowych
  --uninstall        odinstaluj native i Flatpak
  --dry-run          pokaż, co zostałoby zrobione
  -h, --help         ta pomoc

Znajomi:
  curl -fsSL https://raw.githubusercontent.com/GorianWaco/perun/main/install.sh | bash
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --flatpak) MODE="flatpak"; shift ;;
    --local) LOCAL_BUNDLE="${2:?}"; MODE="flatpak"; shift 2 ;;
    --system) MODE="native"; PREFIX="/usr/local"; shift ;;
    --prefix) PREFIX="${2:?}"; MODE="native"; shift 2 ;;
    --no-deps) NO_DEPS=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Nieznana opcja: $1" >&2; usage >&2; exit 1 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
info() { printf '==> %s\n' "$*"; }
die()  { printf 'Błąd: %s\n' "$*" >&2; exit 1; }

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY: $*"
  else
    "$@"
  fi
}

sudo_cmd() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "Potrzebuję root/sudo, żeby doinstalować pakiety. Uruchom z sudo albo: $0 --no-deps"
  fi
}

source_dir() {
  local self="${BASH_SOURCE[0]:-}"
  if [[ -n "$self" && -f "$self" ]]; then
    local dir
    dir="$(cd "$(dirname "$self")" && pwd)"
    if [[ -f "$dir/perun.py" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
  fi
  return 1
}

install_system_deps() {
  [[ "$NO_DEPS" -eq 1 ]] && return 0
  info "Zależności systemowe (GTK4, libadwaita, python-vdf)"
  if command -v pacman >/dev/null 2>&1; then
    sudo_cmd pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita python-vdf
  elif command -v dnf >/dev/null 2>&1; then
    sudo_cmd dnf install -y python3 python3-gobject gtk4 libadwaita python3-pip
    python3 -m pip install --user vdf >/dev/null
  elif command -v apt-get >/dev/null 2>&1; then
    sudo_cmd apt-get update -y
    sudo_cmd apt-get install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 python3-pip
    python3 -m pip install --user vdf >/dev/null || sudo_cmd apt-get install -y python3-vdf || true
  elif command -v zypper >/dev/null 2>&1; then
    sudo_cmd zypper --non-interactive install python3 python3-gobject gtk4 libadwaita python3-pip
    python3 -m pip install --user vdf >/dev/null
  else
    say "! Nie znam tej dystrybucji. Doinstaluj: python3, PyGObject, GTK4, libadwaita, python-vdf"
  fi
  python3 -c "import gi, vdf" 2>/dev/null || python3 -m pip install --user vdf
  python3 -c "import gi, vdf" || die "Brak python-vdf / PyGObject po instalacji."
}

fetch_sources() {
  if src="$(source_dir)"; then
    printf '%s\n' "$src"
    return 0
  fi
  command -v git >/dev/null 2>&1 || {
    if command -v pacman >/dev/null 2>&1; then sudo_cmd pacman -S --needed --noconfirm git
    elif command -v apt-get >/dev/null 2>&1; then sudo_cmd apt-get install -y git
    elif command -v dnf >/dev/null 2>&1; then sudo_cmd dnf install -y git
    else die "Zainstaluj git."; fi
  }
  local dest="${TMPDIR:-/tmp}/perun-src-$$"
  info "Pobieram źródła z GitHuba…"
  git clone --depth 1 "https://github.com/${REPO}.git" "$dest"
  printf '%s\n' "$dest"
}

uninstall_all() {
  info "Odinstalowuję ${APP_NAME}"
  if command -v flatpak >/dev/null 2>&1; then
    flatpak uninstall --user -y "$FLATPAK_ID" >/dev/null 2>&1 || true
  fi
  local prefix="${PREFIX:-${HOME}/.local}"
  rm -f "${prefix}/bin/${APP_ID}" "${prefix}/bin/${OLD_ID}"
  rm -f "${prefix}/share/applications/${APP_ID}.desktop"
  rm -f "${prefix}/share/applications/${OLD_ID}.desktop"
  rm -f "${prefix}/share/applications/${FLATPAK_ID}.desktop"
  rm -f "${prefix}/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
  rm -f "${prefix}/share/icons/hicolor/scalable/apps/${OLD_ID}.svg"
  rm -f "${prefix}/share/icons/hicolor/scalable/apps/${FLATPAK_ID}.svg"
  rm -f "${prefix}/share/${APP_ID}/perun.py" "${prefix}/share/${APP_ID}/README.md"
  rmdir "${prefix}/share/${APP_ID}" 2>/dev/null || true
  say "Usunięto ${APP_NAME}. Kopie zapasowe zostawiam w ~/.local/share/perun/backups"
}

ensure_flatpak() {
  if command -v flatpak >/dev/null 2>&1; then
    return
  fi
  info "Instaluję Flatpak…"
  if command -v pacman >/dev/null 2>&1; then
    sudo_cmd pacman -S --needed --noconfirm flatpak
  elif command -v dnf >/dev/null 2>&1; then
    sudo_cmd dnf install -y flatpak
  elif command -v apt-get >/dev/null 2>&1; then
    sudo_cmd apt-get update -y
    sudo_cmd apt-get install -y flatpak
  else
    die "Zainstaluj pakiet flatpak i odpal skrypt jeszcze raz."
  fi
}

ensure_flathub() {
  if flatpak remotes 2>/dev/null | awk '{print $1}' | grep -qx flathub; then
    return
  fi
  info "Dodaję Flathub…"
  flatpak remote-add --if-not-exists --user flathub "$FLATHUB_REPO"
}

latest_flatpak_url() {
  command -v curl >/dev/null 2>&1 || die "Brak curl."
  local json url
  json=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest") || \
    die "Nie udało się odczytać GitHub Releases."
  url=$(printf '%s' "$json" | grep -oE "https://github.com/${REPO}/releases/download/[^\"[:space:]]+\\.flatpak" | head -n1)
  [[ -n "$url" ]] || die "W najnowszym release nie ma pliku .flatpak — użyj ./install.sh (native)."
  printf '%s\n' "$url"
}

install_flatpak() {
  ensure_flatpak
  ensure_flathub
  local bundle="$LOCAL_BUNDLE"
  if [[ -z "$bundle" ]]; then
    local src
    src="$(source_dir || true)"
    if [[ -n "$src" ]]; then
      local local_dist
      local_dist="$(ls -1t "$src"/dist/Perun-*.flatpak 2>/dev/null | head -n1 || true)"
      if [[ -n "$local_dist" ]]; then
        bundle="$local_dist"
      fi
    fi
  fi
  if [[ -z "$bundle" ]]; then
    local tmp
    tmp="$(mktemp -d)"
    info "Pobieram Flatpak z GitHub Releases…"
    local url dest
    url="$(latest_flatpak_url)"
    dest="$tmp/$(basename "$url")"
    curl -fL --progress-bar -o "$dest" "$url"
    bundle="$dest"
  fi
  [[ -f "$bundle" ]] || die "Nie ma pliku: $bundle"
  if flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1; then
    flatpak uninstall --user -y "$FLATPAK_ID" >/dev/null 2>&1 || true
  fi
  info "Instaluję Flatpak (pierwszy raz dociągnie GNOME ~400 MB)…"
  flatpak install --user -y "$bundle"
  say
  say "✓ Zainstalowano ${APP_NAME} (Flatpak)"
  say "  Uruchom:  flatpak run ${FLATPAK_ID}"
  say "  albo z menu: ${APP_NAME}"
}

install_native() {
  local src prefix
  src="$(fetch_sources)"
  if [[ -n "$PREFIX" ]]; then
    prefix="$PREFIX"
  else
    prefix="${HOME}/.local"
  fi
  if [[ "$prefix" == "/usr/local" && "$(id -u)" -ne 0 ]]; then
    die "Instalacja systemowa wymaga root. Uruchom: sudo $0 --system"
  fi
  install_system_deps

  local bin_dir share_dir app_dir desktop_dir icon_dir
  bin_dir="${prefix}/bin"
  share_dir="${prefix}/share"
  app_dir="${share_dir}/${APP_ID}"
  desktop_dir="${share_dir}/applications"
  icon_dir="${share_dir}/icons/hicolor/scalable/apps"
  local data_dir="${HOME}/.local/share/${APP_ID}"
  local old_data="${HOME}/.local/share/${OLD_ID}"

  info "Kopiuję pliki do ${prefix}"
  run mkdir -p "$app_dir" "$bin_dir" "$desktop_dir" "$icon_dir"
  run install -m755 "${src}/perun.py" "${app_dir}/perun.py"
  run install -m644 "${src}/perun.desktop" "${desktop_dir}/perun.desktop"
  run install -m644 "${src}/icons/perun.svg" "${icon_dir}/perun.svg"
  if [[ -f "${src}/README.md" ]]; then
    run install -m644 "${src}/README.md" "${app_dir}/README.md"
  fi

  local wrapper="${bin_dir}/perun"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY: write ${wrapper}"
  else
    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
exec python3 "${app_dir}/perun.py" "\$@"
EOF
    chmod 755 "$wrapper"
  fi

  if [[ -d "${old_data}/backups" ]]; then
    info "Przenoszę kopie zapasowe"
    mkdir -p "${data_dir}/backups"
    find "${old_data}/backups" -maxdepth 1 -type f -exec mv -n {} "${data_dir}/backups/" \; || true
  fi
  rm -f "${bin_dir}/${OLD_ID}"
  rm -f "${desktop_dir}/${OLD_ID}.desktop"
  rm -f "${icon_dir}/${OLD_ID}.svg"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$desktop_dir" 2>/dev/null || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${share_dir}/icons/hicolor" 2>/dev/null || true
  fi

  say
  say "✓ Zainstalowano ${APP_NAME} ${VERSION}"
  say "  Uruchom:  perun"
  say "  CLI:      perun list"
  say "            perun install GE-Proton"
  say "  Menu:     ${APP_NAME}"
}

echo "=========================================="
echo "  ${APP_NAME} ${VERSION}"
echo "=========================================="

if [[ "$UNINSTALL" -eq 1 ]]; then
  uninstall_all
  exit 0
fi

if [[ "$MODE" == "flatpak" ]]; then
  install_flatpak
else
  install_native
fi
