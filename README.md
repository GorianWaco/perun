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
- przełącznik **Wszystkie gry z konta** — dopisuje niezainstalowane gry, które Steam ma już w pamięci biblioteki
- **Biblioteka Steam:** start w oknie Biblioteki i filtr „tylko zainstalowane lokalnie”
- **Status znajomych:** Online, niewidoczny, offline i pozostałe stany, wpisywane tuż przed startem Steam
- **Eksport / import** ustawień gier (opcje uruchamiania i Proton) do pliku JSON
- **Proton:** wybór wersji (GE-Proton, CachyOS, Proton Stable, Experimental, Hotfix i numerowane wydania Steam)
- **Doinstaluj Proton:** GE-Proton i Proton-CachyOS z GitHuba (jak ProtonUp-Qt)
- **Nakładki przy starcie:** GameMode i MangoHud (pozycja, limit FPS, temperatury, VRAM, OpenGL…)
- **Obraz i okno:** intro, pełny ekran, okno, 3440×1440
- **Proton (zmienne):** DLSS/Reflex, WineD3D, esync, VKD3D
- przycisk **Uruchom**

## Konsola

```bash
perun list
perun list --all
perun get battlenet
perun set Icarus "gamemoderun mangohud %command%"
perun steam
perun steam --library on --installed on
perun steam --status invisible
perun export perun-gry.json
perun import perun-gry.json
perun tools
perun install
perun install GE-Proton
perun install cachyos
perun uninstall GE-Proton11-5-x86_64
perun proton Battle.net GE-Proton11-6-x86_64
```

Skróty spoza Steam zapisują opcje w `shortcuts.vdf`, Proton w `config.vdf`.

`perun steam` czyta albo zapisuje ustawienia klienta: start w Bibliotece (`sharedconfig.vdf`, `SteamDefaultDialog`), filtr biblioteki „Zainstalowane lokalnie” i status znajomych (`ePersonaState` w `localconfig.vdf`). Zapis zamyka Steam na chwilę, tak jak zapis opcji gry. Wybrany status Perun wpisuje ponownie przy każdym swoim uruchomieniu Steam. `--status` przyjmuje: `online`, `invisible`, `away`, `offline`, `busy`, `play`, `trade`.

`perun export` zapisuje tylko gry z własnymi opcjami uruchamiania albo wybranym Protonem. W pliku są AppID, nazwa, opcje, Proton i znacznik skrótu. Nie ma haseł, biletów ani reszty konfiguracji Steam. `perun import` dopasowuje gry Steam po AppID (także gdy gra nie jest zainstalowana) i skróty po nazwie. Gry spoza pliku zostają bez zmian.

Lista „wszystkie gry z konta” bierze zainstalowane gry, skróty, gry z zapisanymi opcjami oraz pozycje typu gra albo program z `appcache/librarycache`. Nie odpytuje sklepu, więc świeżo kupiona gra pojawi się, gdy Steam raz ją pokaże w bibliotece.

## Proton z GitHuba

W GUI: ikona pobierania w belce albo **Doinstaluj inną wersję**.
Paczki lądują w `~/.local/share/Steam/compatibilitytools.d/` (SHA512 + tar).
Po instalacji / usunięciu uruchom Steam ponownie.

## Kopie zapasowe

`~/.local/share/perun/backups/` — ostatnie 10 kopii przed zapisem.
