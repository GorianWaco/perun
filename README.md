# Perun

Opcje uruchamiania i Proton dla gier Steam na Linuksie
(to samo pole co PPM na grę → Właściwości → Opcje uruchamiania,
plus wybór warstwy zgodności i doinstalowanie GE-Proton / CachyOS).

## Instalacja — jedna komenda

```bash
curl -fsSL https://raw.githubusercontent.com/GorianWaco/perun/main/install.sh | bash
```

Skrypt doinstaluje GTK4, libadwaita, python-vdf i wrzuci Peruna do `~/.local`.

Flatpak (z GitHub Releases):

```bash
curl -fsSL https://raw.githubusercontent.com/GorianWaco/perun/main/install.sh | bash -s -- --flatpak
```

Z katalogu źródłowego:

```bash
./install.sh
./install.sh --flatpak
./build-flatpak.sh          # buduje dist/Perun-*.flatpak
```

Potem z menu albo:

```bash
perun
# Flatpak:
flatpak run pl.gorian.Perun
```

## GUI

- lista zainstalowanych gier **i skrótów spoza Steam** (Battle.net, GOG Galaxy…)
- **Proton:** wybór wersji (GE-Proton, CachyOS, Experimental, Hotfix…)
- **Doinstaluj Proton:** GE-Proton i Proton-CachyOS z GitHuba (jak ProtonUp-Qt)
- **Nakładki przy starcie:** GameMode i MangoHud (pozycja, limit FPS, temperatury, VRAM, OpenGL…)
- **Obraz i okno:** intro, pełny ekran, okno, 3440×1440
- **Proton (zmienne):** DLSS/Reflex, WineD3D, esync, VKD3D
- przycisk **Uruchom**

## Konsola

```bash
perun list
perun get battlenet
perun set Icarus "gamemoderun mangohud %command%"
perun tools
perun install
perun install GE-Proton
perun install cachyos
perun uninstall GE-Proton11-5-x86_64
perun proton Battle.net GE-Proton11-6-x86_64
```

Skróty spoza Steam zapisują opcje w `shortcuts.vdf`, Proton w `config.vdf`.

## Proton z GitHuba

W GUI: ikona pobierania w belce albo **Doinstaluj inną wersję**.
Paczki lądują w `~/.local/share/Steam/compatibilitytools.d/` (SHA512 + tar).
Po instalacji / usunięciu uruchom Steam ponownie.

## Kopie zapasowe

`~/.local/share/perun/backups/` — ostatnie 10 kopii przed zapisem.
