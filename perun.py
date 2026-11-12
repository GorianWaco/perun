#!/usr/bin/env python3
"""Perun — opcje uruchamiania i Proton dla gier Steam (w tym spoza Steam)."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import os
import platform
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import vdf
except ImportError:
    vdf = None  # type: ignore


APP_ID = "pl.gorian.Perun"
APP_NAME = "Perun"
VERSION = "1.9.0"

# Język interfejsu. Nazwy języków zostają w oryginale.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("pl", "Polski"),
    ("en", "English"),
    ("de", "Deutsch"),
)
_LANGS = tuple(code for code, _name in LANGUAGES)
_LANG = "pl"


def _pack(rows: dict[str, tuple[str, ...]]) -> dict[str, dict[str, str]]:
    tables = {code: {} for code in _LANGS}
    for key, values in rows.items():
        if len(values) != len(_LANGS):
            raise ValueError(f"{key}: {len(values)}")
        for code, value in zip(_LANGS, values, strict=True):
            tables[code][key] = value
    return tables


def language_codes() -> tuple[str, ...]:
    return _LANGS


def get_language() -> str:
    return _LANG


def set_language(code: str) -> str:
    global _LANG
    _LANG = code if code in _LANGS else "pl"
    return _LANG


def t(key: str, **kwargs: object) -> str:
    table = _TEXT.get(_LANG) or _TEXT["pl"]
    text = table.get(key) or _TEXT["pl"].get(key) or key
    if not kwargs:
        return text
    return text.format(**kwargs)


_TEXT = _pack(
    {
        "language": ("Język", "Language", "Sprache"),
        "language_desc": (
            "Nazwy języków zostają w oryginale, żeby dało się je rozpoznać.",
            "Language names stay in their own language so you can recognize them.",
            "Die Sprachnamen bleiben in der eigenen Sprache, damit man sie erkennt.",
        ),
        "language_row": ("Język interfejsu", "Interface language", "Sprache der Oberfläche"),
        "language_row_sub": (
            "Polski, angielski i niemiecki. Zmiana działa od razu.",
            "Polish, English, and German. The change applies at once.",
            "Polnisch, Englisch und Deutsch. Die Änderung gilt sofort.",
        ),
        "subtitle_main": (
            "opcje uruchamiania Steam",
            "Steam launch options",
            "Steam-Startoptionen",
        ),
        "tip_refresh": ("Odśwież listę gier", "Refresh the game list", "Spielliste aktualisieren"),
        "tip_proton": (
            "Zainstaluj albo usuń wersje Protona",
            "Install or remove Proton versions",
            "Proton-Versionen installieren oder entfernen",
        ),
        "tip_settings": (
            "Biblioteka Steam, język i plik ustawień gier",
            "Steam library, language, and the game-settings file",
            "Steam-Bibliothek, Sprache und die Spiel-Einstellungsdatei",
        ),
        "banner_steam": (
            "Steam jest uruchomiony. Przy zapisie zostanie chwilowo zamknięty, żeby nie nadpisał zmian.",
            "Steam is running. A save closes it for a moment so it does not overwrite the changes.",
            "Steam läuft. Beim Speichern wird es kurz geschlossen, damit es die Änderungen nicht überschreibt.",
        ),
        "search_placeholder": ("Szukaj gry…", "Search games…", "Spiel suchen…"),
        "all_games": ("Wszystkie gry z konta", "All games on the account", "Alle Spiele des Kontos"),
        "all_games_tip": (
            "Pokazuje też niezainstalowane gry, które Steam ma już w pamięci biblioteki tego konta.",
            "Also shows games that are not installed, if Steam has already cached them for this account.",
            "Zeigt auch nicht installierte Spiele, die Steam für dieses Konto schon im Bibliotheksspeicher hat.",
        ),
        "no_games": ("Brak gier", "No games", "Keine Spiele"),
        "empty_title": ("Wybierz grę", "Choose a game", "Spiel auswählen"),
        "empty_desc": (
            "Z listy po lewej wybierz grę, której chcesz zmienić opcje uruchamiania.",
            "Pick a game on the left to change its launch options.",
            "Wähle links ein Spiel, dessen Startoptionen du ändern willst.",
        ),
        "steam_missing_title": ("Nie znaleziono Steam", "Steam was not found", "Steam wurde nicht gefunden"),
        "steam_missing_desc": (
            "Zainstaluj Steam albo uruchom go raz, żeby powstał katalog ~/.local/share/Steam.",
            "Install Steam, or start it once so ~/.local/share/Steam is created.",
            "Installiere Steam oder starte es einmal, damit ~/.local/share/Steam entsteht.",
        ),
        "btn_play": ("Uruchom", "Play", "Starten"),
        "btn_clear": ("Wyczyść", "Clear", "Leeren"),
        "btn_copy": ("Kopiuj", "Copy", "Kopieren"),
        "btn_save": ("Zapisz", "Save", "Speichern"),
        "btn_export_game": ("Eksportuj grę", "Export game", "Spiel exportieren"),
        "btn_cancel": ("Anuluj", "Cancel", "Abbrechen"),
        "btn_delete": ("Usuń", "Delete", "Entfernen"),
        "btn_install": ("Zainstaluj", "Install", "Installieren"),
        "btn_import": ("Importuj", "Import", "Importieren"),
        "btn_ok": ("OK", "OK", "OK"),
        "grp_proton": ("Proton", "Proton", "Proton"),
        "grp_proton_desc": (
            "To samo co w Steam: Właściwości → Zgodność. Na liście jest Proton Stable i reszta narzędzi klienta. Dla Battle.net / Diablo 4 wybierz GE-Proton albo CachyOS.",
            "The same place as Steam: Properties → Compatibility. The list includes Proton Stable and the rest of the client tools. For Battle.net / Diablo 4 pick GE-Proton or CachyOS.",
            "Dieselbe Stelle wie in Steam: Eigenschaften → Kompatibilität. Die Liste enthält Proton Stable und die übrigen Client-Werkzeuge. Für Battle.net / Diablo 4 GE-Proton oder CachyOS wählen.",
        ),
        "row_proton": ("Wersja Protona", "Proton version", "Proton-Version"),
        "row_proton_sub": (
            "Warstwa zgodności Steam Play. Domyślna to ustawienie globalne z Steam Play.",
            "Steam Play compatibility layer. Default follows the global Steam Play setting.",
            "Steam-Play-Kompatibilitätsschicht. Standard folgt der globalen Steam-Play-Einstellung.",
        ),
        "proton_default": ("Domyślna (Steam Play)", "Default (Steam Play)", "Standard (Steam Play)"),
        "proton_default_named": (
            "Domyślna ({name})",
            "Default ({name})",
            "Standard ({name})",
        ),
        "compat_default": (
            "domyślny / Steam Play",
            "default / Steam Play",
            "Standard / Steam Play",
        ),
        "row_manage": ("Doinstaluj inną wersję", "Install another version", "Andere Version installieren"),
        "row_manage_sub": (
            "GE-Proton i Proton-CachyOS z GitHuba — tak jak w ProtonUp-Qt.",
            "GE-Proton and Proton-CachyOS from GitHub, the same idea as ProtonUp-Qt.",
            "GE-Proton und Proton-CachyOS von GitHub, wie in ProtonUp-Qt.",
        ),
        "grp_overlays": ("Nakładki przy starcie", "Launch wrappers", "Start-Hüllen"),
        "grp_overlays_desc": (
            "Owija komendę gry. Steam wstawia właściwy plik gry w miejsce %command%.",
            "Wraps the game command. Steam puts the real game file in place of %command%.",
            "Hüllt den Spielbefehl ein. Steam setzt die richtige Spieldatei an die Stelle von %command%.",
        ),
        "row_gamemode": ("GameMode — więcej klatek", "GameMode — more frames", "GameMode — mehr Bilder"),
        "row_gamemode_sub": (
            "Dla tej gry dopisuje gamemoderun. Ustawienia poniżej są wspólne dla wszystkich gier.",
            "Prepends gamemoderun for this game. The settings below are shared by every game.",
            "Setzt für dieses Spiel gamemoderun davor. Die Einstellungen darunter gelten für alle Spiele.",
        ),
        "gm_renice_member": (
            "Wyższy priorytet CPU na czas gry. 0 zostawia systemowy.",
            "Higher CPU priority while the game runs. 0 leaves the system value.",
            "Höhere CPU-Priorität, solange das Spiel läuft. 0 lässt den Systemwert.",
        ),
        "gm_renice_guest": (
            "Wyższy priorytet CPU. Żeby działał, konto musi być w grupie gamemode.",
            "Higher CPU priority. The account has to be in the gamemode group for this to work.",
            "Höhere CPU-Priorität. Das Konto muss in der Gruppe gamemode sein, damit das wirkt.",
        ),
        "gm_gov": ("Procesor podczas gry", "CPU while playing", "Prozessor während des Spiels"),
        "gm_gov_sub": (
            "GameMode przełącza governor tylko na czas gry.",
            "GameMode switches the governor only while the game runs.",
            "GameMode schaltet den Governor nur für die Spielzeit um.",
        ),
        "gm_gov_after": ("Procesor po wyjściu z gry", "CPU after the game", "Prozessor nach dem Spiel"),
        "gm_gov_after_sub": (
            "Puste znaczy: wróć do governora sprzed uruchomienia.",
            "Empty means: go back to the governor from before launch.",
            "Leer heißt: zurück zum Governor vor dem Start.",
        ),
        "gm_renice": ("Priorytet procesu", "Process priority", "Prozesspriorität"),
        "gm_ioprio": ("Priorytet dysku", "Disk priority", "Festplattenpriorität"),
        "gm_ioprio_sub": (
            "Kolejka odczytu dysku, gdy gra jest na pierwszym planie.",
            "Disk read queue while the game is in the foreground.",
            "Lese-Warteschlange der Platte, solange das Spiel im Vordergrund ist.",
        ),
        "sw_screen": ("Zablokuj wygaszacz", "Block the screensaver", "Bildschirmschoner sperren"),
        "sw_screen_sub": (
            "Na czas gry ekran nie gaśnie i komputer nie zasypia.",
            "While the game runs, the screen stays on and the computer does not sleep.",
            "Solange das Spiel läuft, bleibt der Bildschirm an und der Rechner schläft nicht.",
        ),
        "sw_nvidia": (
            "NVIDIA — maksymalna wydajność karty",
            "NVIDIA — maximum GPU performance",
            "NVIDIA — maximale Grafikleistung",
        ),
        "sw_nvidia_sub": (
            "Na czas gry włącza PowerMizer „Prefer Maximum Performance”. Nie podkręca zegarów.",
            "While the game runs, turns on PowerMizer “Prefer Maximum Performance”. It does not overclock.",
            "Schaltet für die Spielzeit PowerMizer „Prefer Maximum Performance“ ein. Übertaktet nicht.",
        ),
        "row_mango": ("MangoHud — nakładka FPS", "MangoHud — FPS overlay", "MangoHud — FPS-Einblendung"),
        "row_mango_sub": (
            "W grze: prawy Shift+F12 pokazuje/chowa HUD, lewy Shift+F1 przełącza limit FPS.",
            "In game: right Shift+F12 shows or hides the HUD, left Shift+F1 toggles the FPS limit.",
            "Im Spiel: Umschalt+F12 rechts zeigt oder versteckt das HUD, Umschalt+F1 links schaltet das FPS-Limit um.",
        ),
        "mango_pos": ("Pozycja na ekranie", "Position on screen", "Position auf dem Bildschirm"),
        "mango_pos_sub": (
            "Róg albo krawędź, w której stoi nakładka.",
            "Corner or edge where the overlay sits.",
            "Ecke oder Kante, an der die Einblendung steht.",
        ),
        "mango_fps": ("Limit FPS", "FPS limit", "FPS-Limit"),
        "mango_fps_sub": (
            "Na 180 Hz bez limitu 130 klatek rwie obraz. 120 trzyma równy czas klatki (także w DX12 / Diablo 4).",
            "At 180 Hz, an uncapped 130 frames tears the picture. 120 keeps an even frame time (also in DX12 / Diablo 4).",
            "Bei 180 Hz reißt ein unbegrenztes Bild bei 130 Bildern. 120 hält die Bildzeit gleichmäßig (auch in DX12 / Diablo 4).",
        ),
        "mango_font": ("Wielkość czcionki", "Font size", "Schriftgröße"),
        "mango_font_sub": (
            "Na ultrawide zwykle 24–28 px jest wygodne.",
            "On an ultrawide, 24–28 px is usually comfortable.",
            "Auf Ultrawide sind 24–28 px meist angenehm.",
        ),
        "sw_dlsym": ("OpenGL (--dlsym)", "OpenGL (--dlsym)", "OpenGL (--dlsym)"),
        "sw_dlsym_sub": (
            "Potrzebne w niektórych natywnych grach OpenGL. Dopisuje: mangohud --dlsym",
            "Needed by some native OpenGL games. Adds: mangohud --dlsym",
            "Nötig bei manchen nativen OpenGL-Spielen. Setzt dazu: mangohud --dlsym",
        ),
        "gov_performance": ("Wydajność", "Performance", "Leistung"),
        "gov_powersave": ("Oszczędzanie energii", "Power saving", "Energiesparen"),
        "gov_restore": ("Przywróć taki, jaki był", "Restore the previous one", "Den vorherigen wiederherstellen"),
        "gov_keep_perf": ("Zostaw wydajność", "Leave performance on", "Leistung anlassen"),
        "renice_none": ("Bez zmian", "Unchanged", "Unverändert"),
        "renice_higher": ("Wyższy", "Higher", "Höher"),
        "renice_high": ("Wysoki", "High", "Hoch"),
        "renice_very": ("Bardzo wysoki", "Very high", "Sehr hoch"),
        "io_highest": ("Najwyższy", "Highest", "Höchste"),
        "io_normal": ("Normalny", "Normal", "Normal"),
        "io_off": ("Nie zmieniaj", "Do not change", "Nicht ändern"),
        "pos_default": ("Domyślna (lewy górny)", "Default (top left)", "Standard (oben links)"),
        "pos_tl": ("Lewy górny róg", "Top left", "Oben links"),
        "pos_tc": ("Góra, środek", "Top center", "Oben mittig"),
        "pos_tr": ("Prawy górny róg", "Top right", "Oben rechts"),
        "pos_bl": ("Lewy dolny róg", "Bottom left", "Unten links"),
        "pos_bc": ("Dół, środek", "Bottom center", "Unten mittig"),
        "pos_br": ("Prawy dolny róg", "Bottom right", "Unten rechts"),
        "fps_off": ("Nie ograniczaj", "No limit", "Nicht begrenzen"),
        "fps_60": ("60 FPS", "60 FPS", "60 FPS"),
        "fps_90": ("90 FPS (połowa z 180 Hz)", "90 FPS (half of 180 Hz)", "90 FPS (Hälfte von 180 Hz)"),
        "fps_120": (
            "120 FPS — płynniej na 180 Hz",
            "120 FPS — smoother at 180 Hz",
            "120 FPS — flüssiger bei 180 Hz",
        ),
        "fps_144": ("144 FPS", "144 FPS", "144 FPS"),
        "fps_165": ("165 FPS", "165 FPS", "165 FPS"),
        "fps_175": ("175 FPS (VRR, 180 Hz − 5)", "175 FPS (VRR, 180 Hz − 5)", "175 FPS (VRR, 180 Hz − 5)"),
        "fps_180": ("180 FPS", "180 FPS", "180 FPS"),
        "fps_240": ("240 FPS", "240 FPS", "240 FPS"),
        "font_default": ("Domyślna", "Default", "Standard"),
        "font_16": ("16 px — mała", "16 px — small", "16 px — klein"),
        "font_20": ("20 px", "20 px", "20 px"),
        "font_24": ("24 px", "24 px", "24 px"),
        "font_28": ("28 px", "28 px", "28 px"),
        "font_32": ("32 px — duża", "32 px — large", "32 px — groß"),
        "flag_gpu_temp": ("Temperatura GPU", "GPU temperature", "GPU-Temperatur"),
        "flag_gpu_temp_sub": ("Temperatura karty graficznej", "Graphics card temperature", "Temperatur der Grafikkarte"),
        "flag_gpu_power": ("Moc GPU", "GPU power", "GPU-Leistung"),
        "flag_gpu_power_sub": ("Pobór mocy karty w watach", "Card power draw in watts", "Leistungsaufnahme der Karte in Watt"),
        "flag_gpu_clock": ("Taktowanie GPU", "GPU clock", "GPU-Takt"),
        "flag_gpu_clock_sub": ("Zegar rdzenia karty", "Graphics core clock", "Takt des Grafikkerns"),
        "flag_cpu_temp": ("Temperatura CPU", "CPU temperature", "CPU-Temperatur"),
        "flag_cpu_temp_sub": ("Temperatura procesora", "Processor temperature", "Prozessortemperatur"),
        "flag_vram": ("VRAM", "VRAM", "VRAM"),
        "flag_vram_sub": ("Zajętość pamięci karty", "Video memory in use", "Belegter Grafikspeicher"),
        "flag_ram": ("RAM", "RAM", "RAM"),
        "flag_ram_sub": ("Zajętość pamięci systemowej", "System memory in use", "Belegter Arbeitsspeicher"),
        "flag_wine": ("Proton / Wine", "Proton / Wine", "Proton / Wine"),
        "flag_wine_sub": ("Wersja Protona albo Wine", "Proton or Wine version", "Proton- oder Wine-Version"),
        "flag_resolution": ("Rozdzielczość", "Resolution", "Auflösung"),
        "flag_resolution_sub": ("Aktualna rozdzielczość gry", "Current game resolution", "Aktuelle Spielauflösung"),
        "flag_compact": ("Zwarty HUD", "Compact HUD", "Kompaktes HUD"),
        "flag_compact_sub": ("Mniejsza nakładka, mniej odstępów", "Smaller overlay, tighter spacing", "Kleinere Einblendung, weniger Abstand"),
        "flag_horizontal": ("Poziomy układ", "Horizontal layout", "Waagerechte Anordnung"),
        "flag_horizontal_sub": ("Wszystko w jednej linii", "Everything on one line", "Alles in einer Zeile"),
        "flag_hidden": ("Ukryj na starcie", "Hidden at start", "Beim Start versteckt"),
        "flag_hidden_sub": (
            "Schowany, aż naciśniesz prawy Shift+F12",
            "Hidden until you press right Shift+F12",
            "Versteckt, bis du Umschalt+F12 rechts drückst",
        ),
        "preset_image": ("Obraz i okno", "Picture and window", "Bild und Fenster"),
        "preset_image_desc": (
            "Argumenty dopisywane na końcu — trafiają wprost do gry.",
            "Arguments added at the end. They go straight to the game.",
            "Argumente am Ende. Sie gehen direkt an das Spiel.",
        ),
        "preset_novid": ("Pomiń intro", "Skip the intro", "Intro überspringen"),
        "preset_novid_tip": (
            "Wyłącza filmik startowy studia. W komendzie: -novid",
            "Turns off the studio intro video. In the command: -novid",
            "Schaltet das Studio-Intro aus. Im Befehl: -novid",
        ),
        "preset_full": ("Pełny ekran", "Fullscreen", "Vollbild"),
        "preset_full_tip": (
            "Start na całym monitorze. W komendzie: -fullscreen",
            "Starts on the whole monitor. In the command: -fullscreen",
            "Start auf dem ganzen Monitor. Im Befehl: -fullscreen",
        ),
        "preset_window": ("W oknie", "Windowed", "Im Fenster"),
        "preset_window_tip": (
            "Start w oknie zamiast na pełnym ekranie. W komendzie: -windowed",
            "Starts in a window instead of fullscreen. In the command: -windowed",
            "Start im Fenster statt im Vollbild. Im Befehl: -windowed",
        ),
        "preset_uw": ("Ultrawide 3440×1440", "Ultrawide 3440×1440", "Ultrawide 3440×1440"),
        "preset_uw_tip": (
            "Wymusza rozdzielczość Twojego monitora. W komendzie: -w 3440 -h 1440",
            "Forces your monitor’s resolution. In the command: -w 3440 -h 1440",
            "Erzwingt die Auflösung deines Monitors. Im Befehl: -w 3440 -h 1440",
        ),
        "preset_proton": ("Proton (gry z Windowsa)", "Proton (Windows games)", "Proton (Windows-Spiele)"),
        "preset_proton_desc": (
            "Zmienne przed %command%. Działają, gdy gra idzie przez Proton.",
            "Variables before %command%. They work when the game runs through Proton.",
            "Variablen vor %command%. Sie wirken, wenn das Spiel über Proton läuft.",
        ),
        "preset_nvapi": ("DLSS / Reflex (NVIDIA)", "DLSS / Reflex (NVIDIA)", "DLSS / Reflex (NVIDIA)"),
        "preset_nvapi_tip": (
            "Włącza NVAPI w Protonie: DLSS, Reflex, Frame Generation.",
            "Turns on NVAPI in Proton: DLSS, Reflex, Frame Generation.",
            "Schaltet NVAPI in Proton ein: DLSS, Reflex, Frame Generation.",
        ),
        "preset_dxvk": ("Licznik FPS (DXVK)", "FPS counter (DXVK)", "FPS-Zähler (DXVK)"),
        "preset_dxvk_tip": (
            "Tylko gry DX11. Diablo 4 jest na DX12 — tu nic nie da, użyj MangoHud.",
            "DX11 games only. Diablo 4 is DX12, so this does nothing there. Use MangoHud.",
            "Nur DX11-Spiele. Diablo 4 ist DX12, dort bringt das nichts. Nimm MangoHud.",
        ),
        "preset_wined3d": ("OpenGL zamiast Vulkan", "OpenGL instead of Vulkan", "OpenGL statt Vulkan"),
        "preset_wined3d_tip": (
            "Gdy Vulkan wywala grę. Zwykle wolniejsze, ale bywa stabilniejsze.",
            "When Vulkan crashes the game. Usually slower, sometimes more stable.",
            "Wenn Vulkan das Spiel abstürzen lässt. Meist langsamer, manchmal stabiler.",
        ),
        "preset_noesync": ("Wyłącz esync", "Turn off esync", "Esync ausschalten"),
        "preset_noesync_tip": (
            "Gdy gra wisi na starcie. W Diablo 4 zwykle pogarsza przycinki — lepiej bez tego.",
            "When the game hangs at startup. In Diablo 4 it usually makes stutter worse, so leave it off.",
            "Wenn das Spiel beim Start hängt. In Diablo 4 verschlimmert es Ruckler meist, also besser aus.",
        ),
        "preset_vkd3d": ("NVIDIA DX12 mniej przycinek", "NVIDIA DX12, less stutter", "NVIDIA DX12, weniger Ruckler"),
        "preset_vkd3d_tip": (
            "Omija host-visible VRAM w vkd3d. Czasem ścina mikro-stutter w Diablo 4 / DX12.",
            "Skips host-visible VRAM in vkd3d. Sometimes cuts micro-stutter in Diablo 4 / DX12.",
            "Umgeht host-visible VRAM in vkd3d. Schneidet manchmal Mikroruckler in Diablo 4 / DX12.",
        ),
        "preset_add_tip": (
            "Dopisz do komendy: {value}",
            "Add to the command: {value}",
            "Zum Befehl hinzufügen: {value}",
        ),
        "grp_command": ("Pełna komenda", "Full command", "Voller Befehl"),
        "grp_command_desc": (
            "To samo pole co w Steam: PPM na grę → Właściwości → Opcje uruchamiania. Przyciski powyżej ją składają, tu możesz poprawić ręcznie.",
            "The same field as in Steam: right-click the game → Properties → Launch options. The buttons above build it, and you can edit it here.",
            "Dasselbe Feld wie in Steam: Rechtsklick auf das Spiel → Eigenschaften → Startoptionen. Die Knöpfe oben bauen es, hier kannst du von Hand nachbessern.",
        ),
        "row_options": ("Opcje", "Options", "Optionen"),
        "tip_options": (
            "np. MANGOHUD_CONFIG=gpu_temp,position=top-right gamemoderun mangohud %command%",
            "e.g. MANGOHUD_CONFIG=gpu_temp,position=top-right gamemoderun mangohud %command%",
            "z. B. MANGOHUD_CONFIG=gpu_temp,position=top-right gamemoderun mangohud %command%",
        ),
        "toast_gamemode": (
            "Zapisano GameMode. Zadziała przy następnym uruchomieniu gry.",
            "GameMode saved. It applies the next time a game starts.",
            "GameMode gespeichert. Wirkt beim nächsten Spielstart.",
        ),
        "status_dirty": ("Zmiany niezapisane.", "Unsaved changes.", "Ungespeicherte Änderungen."),
        "status_steam_on": (
            "Zapis zamknie Steam na chwilę, zapisze opcje i Protona, potem uruchomi Steam ponownie.",
            "Save closes Steam for a moment, writes the options and Proton, then starts Steam again.",
            "Speichern schließt Steam kurz, schreibt Optionen und Proton und startet Steam wieder.",
        ),
        "status_steam_off": (
            "Steam jest wyłączony — zapis trafi od razu do plików konfiguracji.",
            "Steam is closed — the save goes straight into the config files.",
            "Steam ist aus — das Speichern geht direkt in die Konfigurationsdateien.",
        ),
        "toast_copied": (
            "Skopiowano opcje uruchamiania",
            "Launch options copied",
            "Startoptionen kopiert",
        ),
        "toast_launch": ("Uruchamiam {name}", "Starting {name}", "Starte {name}"),
        "status_saving": ("Zapisuję…", "Saving…", "Speichere…"),
        "toast_save_fail": ("Nie udało się zapisać", "Could not save", "Speichern ist fehlgeschlagen"),
        "dlg_not_saved": ("Nie zapisano", "Not saved", "Nicht gespeichert"),
        "toast_saved": ("Zapisano opcje: {name}", "Saved options: {name}", "Optionen gespeichert: {name}"),
        "status_saved_restart": (
            "Zapisane. Steam uruchamia się ponownie.",
            "Saved. Steam is starting again.",
            "Gespeichert. Steam startet neu.",
        ),
        "status_saved": ("Zapisane.", "Saved.", "Gespeichert."),
        "list_no_options": ("brak opcji", "no options", "keine Optionen"),
        "list_shortcut": ("spoza Steam", "non-Steam", "außerhalb von Steam"),
        "list_uninstalled": ("niezainstalowana", "not installed", "nicht installiert"),
        "list_kind_prefix": ("{kind} · {sub}", "{kind} · {sub}", "{kind} · {sub}"),
        "meta_never": ("nigdy", "never", "nie"),
        "meta_line": (
            "{origin}  ·  AppID {appid}  ·  Proton: {proton}  ·  ostatnio {last}",
            "{origin}  ·  AppID {appid}  ·  Proton: {proton}  ·  last played {last}",
            "{origin}  ·  AppID {appid}  ·  Proton: {proton}  ·  zuletzt {last}",
        ),
        "origin_shortcut": ("spoza Steam", "non-Steam", "außerhalb von Steam"),
        "origin_steam": ("Steam", "Steam", "Steam"),
        "origin_uninstalled_suffix": (
            ", niezainstalowana",
            ", not installed",
            ", nicht installiert",
        ),
        "win_proton": ("Wersje Protona", "Proton versions", "Proton-Versionen"),
        "win_proton_sub": (
            "GE-Proton i Proton-CachyOS → compatibilitytools.d",
            "GE-Proton and Proton-CachyOS → compatibilitytools.d",
            "GE-Proton und Proton-CachyOS → compatibilitytools.d",
        ),
        "grp_installed": ("Zainstalowane własne wersje", "Installed custom versions", "Installierte eigene Versionen"),
        "grp_installed_desc": (
            "Oficjalny Proton Steam (Experimental, Hotfix) zostaw w kliencie Steam.",
            "Leave official Steam Proton (Experimental, Hotfix) in the Steam client.",
            "Offizielles Steam-Proton (Experimental, Hotfix) bleibt im Steam-Client.",
        ),
        "grp_github": ("Doinstaluj z GitHuba", "Install from GitHub", "Von GitHub installieren"),
        "grp_github_desc": (
            "Po instalacji uruchom Steam ponownie, żeby nowa wersja weszła na listę zgodności.",
            "After installing, start Steam again so the new version appears in the compatibility list.",
            "Starte Steam nach der Installation neu, damit die neue Version in der Kompatibilitätsliste steht.",
        ),
        "row_flavor": ("Rodzaj", "Kind", "Art"),
        "row_release": ("Wydanie", "Release", "Ausgabe"),
        "pm_fetching": ("Pobieram listę z GitHuba…", "Fetching the list from GitHub…", "Hole die Liste von GitHub…"),
        "pm_choose": ("Wybierz wydanie i zainstaluj.", "Pick a release and install it.", "Wähle eine Ausgabe und installiere sie."),
        "pm_none": ("Nie ma jeszcze własnych wersji", "No custom versions yet", "Noch keine eigenen Versionen"),
        "pm_none_sub": (
            "Zainstaluj GE-Proton albo Proton-CachyOS poniżej.",
            "Install GE-Proton or Proton-CachyOS below.",
            "Installiere unten GE-Proton oder Proton-CachyOS.",
        ),
        "pm_default_play": ("domyślny Steam Play", "default Steam Play", "Standard-Steam-Play"),
        "pm_unassigned": ("nieprzypisany do gry", "not assigned to a game", "keinem Spiel zugeordnet"),
        "tip_remove": ("Usuń {name}", "Remove {name}", "{name} entfernen"),
        "pm_fetch_fail": (
            "nie udało się pobrać listy",
            "could not fetch the list",
            "Liste konnte nicht geladen werden",
        ),
        "pm_no_releases": ("brak wydań", "no releases", "keine Ausgaben"),
        "pm_github_empty": (
            "GitHub nie zwrócił wydań.",
            "GitHub returned no releases.",
            "GitHub hat keine Ausgaben geliefert.",
        ),
        "pm_installed_mark": (" · zainstalowany", " · installed", " · installiert"),
        "pm_pick_release": (
            "Wybierz wydanie do pobrania.",
            "Choose a release to download.",
            "Wähle eine Ausgabe zum Herunterladen.",
        ),
        "pm_cancelling": ("Anuluję…", "Cancelling…", "Breche ab…"),
        "pm_already": ("Już zainstalowane: {name}", "Already installed: {name}", "Schon installiert: {name}"),
        "pm_downloading": (
            "Pobieram {name} ({size})…",
            "Downloading {name} ({size})…",
            "Lade {name} herunter ({size})…",
        ),
        "phase_download": ("Pobieram…", "Downloading…", "Lade herunter…"),
        "phase_extract": ("Rozpakowuję…", "Unpacking…", "Entpacke…"),
        "toast_proton_fail": (
            "Nie udało się zainstalować Protona",
            "Could not install Proton",
            "Proton konnte nicht installiert werden",
        ),
        "pm_installed_done": (
            "Zainstalowano {name}. Uruchom Steam ponownie, żeby wszedł na listę zgodności.",
            "Installed {name}. Start Steam again so it appears in the compatibility list.",
            "{name} installiert. Starte Steam neu, damit es in der Kompatibilitätsliste steht.",
        ),
        "toast_installed": ("Zainstalowano {name}", "Installed {name}", "{name} installiert"),
        "pm_delete_body": (
            "Katalog {path} zostanie usunięty.",
            "The folder {path} will be removed.",
            "Der Ordner {path} wird entfernt.",
        ),
        "pm_delete_default": (
            " To obecnie globalny Proton Steam Play.",
            " This is the current global Steam Play Proton.",
            " Das ist derzeit das globale Steam-Play-Proton.",
        ),
        "pm_delete_users": (" Używają go: {names}", " Used by: {names}", " Verwendet von: {names}"),
        "pm_delete_heading": ("Usunąć {name}?", "Remove {name}?", "{name} entfernen?"),
        "toast_removed": ("Usunięto {name}", "Removed {name}", "{name} entfernt"),
        "flavor_ge": (
            "GloriousEggroll — gdy nie wiesz, co wybrać.",
            "GloriousEggroll — when you are not sure what to pick.",
            "GloriousEggroll — wenn du nicht weißt, was du wählen sollst.",
        ),
        "flavor_cachy": (
            "Build CachyOS. Wariant x86_64_v3, gdy CPU ma AVX2.",
            "CachyOS build. The x86_64_v3 variant when the CPU has AVX2.",
            "CachyOS-Build. Die Variante x86_64_v3, wenn die CPU AVX2 hat.",
        ),
        "win_settings": ("Biblioteka i ustawienia", "Library and settings", "Bibliothek und Einstellungen"),
        "win_settings_sub": (
            "Język, klient Steam i plik, który można przenieść na inny komputer",
            "Language, the Steam client, and a file you can move to another computer",
            "Sprache, der Steam-Client und eine Datei für einen anderen Rechner",
        ),
        "grp_library": ("Biblioteka Steam", "Steam library", "Steam-Bibliothek"),
        "grp_library_desc": (
            "Przełączniki i status znajomych zapisują się razem. Steam jest wtedy na chwilę zamykany. Jeśli Steam Cloud przywróci starszy widok, zapisz jeszcze raz.",
            "The switches and the friends status save together. Steam closes for a moment. If Steam Cloud restores an older view, save again.",
            "Schalter und Freundesstatus werden zusammen gespeichert. Steam schließt sich kurz. Wenn die Steam Cloud eine ältere Ansicht zurückholt, noch einmal speichern.",
        ),
        "sw_library": (
            "Uruchamiaj Steam w bibliotece",
            "Start Steam in the Library",
            "Steam in der Bibliothek starten",
        ),
        "sw_library_sub": (
            "Po starcie klient otwiera Bibliotekę.",
            "After startup the client opens the Library.",
            "Nach dem Start öffnet der Client die Bibliothek.",
        ),
        "sw_installed": (
            "Pokazuj tylko gry zainstalowane lokalnie",
            "Show only games installed locally",
            "Nur lokal installierte Spiele zeigen",
        ),
        "sw_installed_sub": (
            "Filtr biblioteki: Zainstalowane lokalnie. Perun nadal może pokazać resztę konta.",
            "Library filter: Installed locally. Perun can still show the rest of the account.",
            "Bibliotheksfilter: Lokal installiert. Perun kann den Rest des Kontos weiter zeigen.",
        ),
        "grp_friends": ("Status znajomych", "Friends status", "Freundesstatus"),
        "grp_friends_desc": (
            "Perun wpisuje ten status tuż przed każdym swoim uruchomieniem Steam. Niewidoczny zostawia konto zalogowane, a znajomi widzą offline.",
            "Perun writes this status just before every Steam start it performs. Invisible keeps the account logged in, while friends see you as offline.",
            "Perun schreibt diesen Status direkt vor jedem Steam-Start, den es selbst auslöst. Unsichtbar lässt das Konto angemeldet, Freunde sehen offline.",
        ),
        "row_persona": ("Status przy starcie", "Status at startup", "Status beim Start"),
        "row_persona_sub": (
            "Online, niewidoczny, offline i pozostałe stany listy znajomych.",
            "Online, invisible, offline, and the other friends-list states.",
            "Online, unsichtbar, offline und die übrigen Zustände der Freundesliste.",
        ),
        "steam_will_restart": (
            "Zapis zamknie Steam na chwilę i uruchomi go ponownie.",
            "Save closes Steam for a moment and starts it again.",
            "Speichern schließt Steam kurz und startet es neu.",
        ),
        "steam_is_off": (
            "Steam jest wyłączony — zapis trafi od razu do plików klienta.",
            "Steam is closed — the save goes straight into the client files.",
            "Steam ist aus — das Speichern geht direkt in die Client-Dateien.",
        ),
        "btn_save_steam": ("Zapisz ustawienia Steam", "Save Steam settings", "Steam-Einstellungen speichern"),
        "grp_share": ("Ustawienia gier", "Game settings", "Spieleinstellungen"),
        "grp_share_desc": (
            "Eksport wszystkich gier bierze tylko te z własnymi opcjami albo wybranym Protonem. Eksport jednej gry zapisuje wyłącznie wybraną pozycję, także z domyślnymi ustawieniami. Import dopasowuje gry Steam po AppID, a skróty spoza Steam po nazwie, i nie zmienia gier, których w pliku nie ma.",
            "Export all includes only games with their own launch options or a chosen Proton. Export one game writes just the selected title, including defaults. Import matches Steam games by AppID and shortcuts by name, and leaves games that are not in the file alone.",
            "Alle exportieren nimmt nur Spiele mit eigenen Startoptionen oder gewähltem Proton. Ein Spiel exportieren schreibt nur den gewählten Eintrag, auch mit Standardeinstellungen. Import trifft Steam-Spiele über die AppID und Verknüpfungen über den Namen und lässt Spiele, die nicht in der Datei stehen, in Ruhe.",
        ),
        "row_export_all": ("Eksportuj wszystkie…", "Export all…", "Alle exportieren…"),
        "row_export_all_sub": (
            "Plik JSON ze wszystkimi grami, które mają własne ustawienia",
            "A JSON file of every game that has its own settings",
            "Eine JSON-Datei aller Spiele mit eigenen Einstellungen",
        ),
        "row_export_one": ("Eksportuj wybraną grę…", "Export the selected game…", "Ausgewähltes Spiel exportieren…"),
        "row_export_one_sub": ("Tylko {name}", "Only {name}", "Nur {name}"),
        "row_export_one_none": (
            "Najpierw wybierz grę na liście",
            "Choose a game in the list first",
            "Wähle zuerst ein Spiel in der Liste",
        ),
        "row_import": ("Importuj…", "Import…", "Importieren…"),
        "row_import_sub": ("Wczytaj plik JSON", "Open a JSON file", "JSON-Datei öffnen"),
        "status_saving_steam": (
            "Zapisuję ustawienia Steam…",
            "Saving Steam settings…",
            "Speichere Steam-Einstellungen…",
        ),
        "toast_steam_fail": (
            "Nie udało się zapisać ustawień Steam",
            "Could not save Steam settings",
            "Steam-Einstellungen konnten nicht gespeichert werden",
        ),
        "toast_steam_ok": ("Zapisano ustawienia Steam", "Steam settings saved", "Steam-Einstellungen gespeichert"),
        "filter_json": ("Ustawienia Peruna (JSON)", "Perun settings (JSON)", "Perun-Einstellungen (JSON)"),
        "dlg_export": ("Eksportuj ustawienia gier", "Export game settings", "Spieleinstellungen exportieren"),
        "dlg_export_one": (
            "Eksportuj ustawienia: {name}",
            "Export settings: {name}",
            "Einstellungen exportieren: {name}",
        ),
        "export_name_all": ("perun-gry.json", "perun-games.json", "perun-spiele.json"),
        "toast_bad_save": (
            "Nie można zapisać w tym miejscu",
            "Cannot save in that place",
            "Dort kann nicht gespeichert werden",
        ),
        "toast_export_fail": ("Nie udało się wyeksportować", "Could not export", "Export ist fehlgeschlagen"),
        "dlg_export_fail": ("Nie wyeksportowano", "Not exported", "Nicht exportiert"),
        "exported_one": ("Zapisano ustawienia 1 gry", "Saved settings for 1 game", "Einstellungen für 1 Spiel gespeichert"),
        "exported_many": (
            "Zapisano ustawienia {count} gier",
            "Saved settings for {count} games",
            "Einstellungen für {count} Spiele gespeichert",
        ),
        "exported_named": (
            "Zapisano ustawienia gry {name}",
            "Saved settings for {name}",
            "Einstellungen für {name} gespeichert",
        ),
        "exported_path": (
            "Zapisano ustawienia {count} gier do {path}",
            "Saved settings for {count} games to {path}",
            "Einstellungen für {count} Spiele nach {path} gespeichert",
        ),
        "exported_named_path": (
            "Zapisano ustawienia gry {name} do {path}",
            "Saved settings for {name} to {path}",
            "Einstellungen für {name} nach {path} gespeichert",
        ),
        "dlg_import": ("Importuj ustawienia gier", "Import game settings", "Spieleinstellungen importieren"),
        "toast_bad_open": (
            "Nie można odczytać tego pliku",
            "Cannot read that file",
            "Diese Datei kann nicht gelesen werden",
        ),
        "import_body_running": (
            "Opcje uruchamiania i Proton zostaną zapisane dla gier z pliku. Pozostałe gry zostaną bez zmian. Steam zostanie na chwilę zamknięty.",
            "Launch options and Proton will be written for the games in the file. Other games stay as they are. Steam will close for a moment.",
            "Startoptionen und Proton werden für die Spiele in der Datei geschrieben. Andere Spiele bleiben. Steam wird kurz geschlossen.",
        ),
        "import_body_idle": (
            "Opcje uruchamiania i Proton zostaną zapisane dla gier z pliku. Pozostałe gry zostaną bez zmian.",
            "Launch options and Proton will be written for the games in the file. Other games stay as they are.",
            "Startoptionen und Proton werden für die Spiele in der Datei geschrieben. Andere Spiele bleiben.",
        ),
        "dlg_import_ask": (
            "Zaimportować ustawienia gier?",
            "Import game settings?",
            "Spieleinstellungen importieren?",
        ),
        "status_importing": (
            "Importuję ustawienia gier…",
            "Importing game settings…",
            "Importiere Spieleinstellungen…",
        ),
        "toast_import_fail": ("Nie udało się zaimportować", "Could not import", "Import ist fehlgeschlagen"),
        "dlg_import_fail": ("Nie zaimportowano", "Not imported", "Nicht importiert"),
        "imported_one": (
            "Zaimportowano ustawienia 1 gry",
            "Imported settings for 1 game",
            "Einstellungen für 1 Spiel importiert",
        ),
        "imported_many": (
            "Zaimportowano ustawienia {count} gier",
            "Imported settings for {count} games",
            "Einstellungen für {count} Spiele importiert",
        ),
        "skipped_suffix": (" Pominięto: {names}.", " Skipped: {names}.", " Übersprungen: {names}."),
        "persona_online": ("Online", "Online", "Online"),
        "persona_invisible": ("Niewidoczny", "Invisible", "Unsichtbar"),
        "persona_away": ("Zaraz wracam", "Away", "Abwesend"),
        "persona_offline": ("Offline", "Offline", "Offline"),
        "persona_busy": ("Zajęty", "Busy", "Beschäftigt"),
        "persona_play": ("Chcę grać", "Looking to Play", "Möchte spielen"),
        "persona_trade": ("Chcę handlować", "Looking to Trade", "Möchte handeln"),
        "persona_missing": ("brak", "not set", "nicht gesetzt"),
        "persona_other": ("inny ({state})", "other ({state})", "anderer ({state})"),
        "kind_shortcut": ("spoza Steam", "non-Steam", "außerhalb von Steam"),
        "kind_uninstalled": ("niezainstalowana", "not installed", "nicht installiert"),
        "kind_steam": ("Steam", "Steam", "Steam"),
        "kind_steam_uninstalled": (
            "Steam, niezainstalowana",
            "Steam, not installed",
            "Steam, nicht installiert",
        ),
        "cli_no_games": ("Brak gier.", "No games.", "Keine Spiele."),
        "cli_proton_mark": ("domyślny", "default", "Standard"),
        "cli_several": (
            "Kilka pasujących gier, podaj dokładniejszą nazwę albo AppID:",
            "Several games match. Give a more exact name or an AppID:",
            "Mehrere Spiele passen. Gib einen genaueren Namen oder eine AppID an:",
        ),
        "cli_not_found_game": ("Nie znaleziono gry: {query}", "Game not found: {query}", "Spiel nicht gefunden: {query}"),
        "cli_no_steam": ("Nie znaleziono Steam.", "Steam was not found.", "Steam wurde nicht gefunden."),
        "cli_no_options": ("(brak opcji)", "(no options)", "(keine Optionen)"),
        "cli_cleared": ("(wyczyszczone)", "(cleared)", "(geleert)"),
        "cli_saved": ("Zapisano {name}: {options}", "Saved {name}: {options}", "Gespeichert {name}: {options}"),
        "cli_error": ("Błąd: {error}", "Error: {error}", "Fehler: {error}"),
        "cli_default_tool": ("domyślny", "default", "Standard"),
        "cli_no_global": (
            "(brak globalnego Steam Play)",
            "(no global Steam Play)",
            "(kein globales Steam Play)",
        ),
        "cli_no_proton_installed": (
            "Nie znaleziono zainstalowanych wersji Protona.",
            "No installed Proton versions were found.",
            "Keine installierten Proton-Versionen gefunden.",
        ),
        "cli_kind_official": ("Steam", "Steam", "Steam"),
        "cli_kind_custom": ("własny", "custom", "eigen"),
        "cli_proton_missing": (
            "Nie znaleziono Protona: {name}",
            "Proton not found: {name}",
            "Proton nicht gefunden: {name}",
        ),
        "cli_proton_several": (
            "Kilka pasujących wersji, podaj dokładniejszą nazwę:",
            "Several versions match. Give a more exact name:",
            "Mehrere Versionen passen. Gib einen genaueren Namen an:",
        ),
        "cli_saved_proton": (
            "Zapisano Proton dla {name}: {label}",
            "Saved Proton for {name}: {label}",
            "Proton für {name} gespeichert: {label}",
        ),
        "cli_no_releases_short": ("  (brak wydań)", "  (no releases)", "  (keine Ausgaben)"),
        "cli_installed_mark": ("  [zainstalowany]", "  [installed]", "  [installiert]"),
        "cli_install_hint_1": (
            "Zainstaluj:  perun install GE-Proton",
            "Install:  perun install GE-Proton",
            "Installieren:  perun install GE-Proton",
        ),
        "cli_install_hint_2": (
            "             perun install cachyos",
            "             perun install cachyos",
            "             perun install cachyos",
        ),
        "cli_install_hint_3": (
            "             perun install GE-Proton11-6",
            "             perun install GE-Proton11-6",
            "             perun install GE-Proton11-6",
        ),
        "cli_downloading": (
            "Pobieram {name} ({size})…",
            "Downloading {name} ({size})…",
            "Lade {name} herunter ({size})…",
        ),
        "cli_installed_path": (
            "Zainstalowano {name}",
            "Installed {name}",
            "{name} installiert",
        ),
        "cli_restart_steam_list": (
            "Uruchom Steam ponownie, żeby wersja pojawiła się w kliencie Steam.",
            "Start Steam again so the version shows up in the Steam client.",
            "Starte Steam neu, damit die Version im Steam-Client erscheint.",
        ),
        "cli_cannot_remove": (
            "Nie znaleziono własnego Protona do usunięcia: {name}",
            "No custom Proton to remove was found: {name}",
            "Kein eigenes Proton zum Entfernen gefunden: {name}",
        ),
        "cli_several_short": (
            "Kilka pasujących, podaj dokładniejszą nazwę:",
            "Several match. Give a more exact name:",
            "Mehrere passen. Gib einen genaueren Namen an:",
        ),
        "cli_warning_global": ("to globalny Steam Play", "it is the global Steam Play", "das ist das globale Steam Play"),
        "cli_warning_used": ("używa: {names}", "used by: {names}", "verwendet von: {names}"),
        "cli_warning": ("Uwaga: {text}.", "Note: {text}.", "Hinweis: {text}."),
        "cli_removed": ("Usunięto {name}", "Removed {name}", "{name} entfernt"),
        "cli_restart_compat": (
            "Uruchom Steam ponownie, żeby zniknął z listy zgodności.",
            "Start Steam again so it disappears from the compatibility list.",
            "Starte Steam neu, damit es aus der Kompatibilitätsliste verschwindet.",
        ),
        "cli_imported": (
            "Zaimportowano ustawienia {count} gier.",
            "Imported settings for {count} games.",
            "Einstellungen für {count} Spiele importiert.",
        ),
        "cli_skipped": ("Pominięto: {names}", "Skipped: {names}", "Übersprungen: {names}"),
        "cli_library_on": (
            "Biblioteka przy starcie: {value}",
            "Library at startup: {value}",
            "Bibliothek beim Start: {value}",
        ),
        "cli_installed_only": (
            "Tylko zainstalowane lokalnie: {value}",
            "Only installed locally: {value}",
            "Nur lokal installiert: {value}",
        ),
        "cli_yes": ("tak", "yes", "ja"),
        "cli_no": ("nie", "no", "nein"),
        "cli_status_now": ("Status przy starcie: {label}", "Status at startup: {label}", "Status beim Start: {label}"),
        "cli_status_next": (
            "Perun ustawi przy następnym starcie: {label}",
            "Perun will set this on the next start: {label}",
            "Perun setzt das beim nächsten Start: {label}",
        ),
        "cli_saved_steam": (
            "Zapisano ustawienia Steam.",
            "Steam settings saved.",
            "Steam-Einstellungen gespeichert.",
        ),
        "cli_persona_fail": (
            "Perun: nie udało się ustawić statusu Steam: {error}",
            "Perun: could not set the Steam status: {error}",
            "Perun: Steam-Status konnte nicht gesetzt werden: {error}",
        ),
        "cli_desc": (
            "Perun — opcje uruchamiania i Proton dla gier Steam.",
            "Perun — launch options and Proton for Steam games.",
            "Perun — Startoptionen und Proton für Steam-Spiele.",
        ),
        "help_list": ("Pokaż gry i ich opcje", "Show games and their options", "Spiele und ihre Optionen zeigen"),
        "help_all": (
            "Pokaż też niezainstalowane gry z konta Steam",
            "Also show games from the Steam account that are not installed",
            "Auch nicht installierte Spiele des Steam-Kontos zeigen",
        ),
        "help_get": ("Pokaż opcje jednej gry", "Show one game’s options", "Optionen eines Spiels zeigen"),
        "help_game": ("Nazwa albo AppID", "Name or AppID", "Name oder AppID"),
        "help_set": (
            "Ustaw opcje (zamyka Steam na czas zapisu)",
            "Set options (closes Steam while saving)",
            "Optionen setzen (schließt Steam fürs Speichern)",
        ),
        "help_options": ("Treść opcji; puste = wyczyść", "Option text; empty = clear", "Optionstext; leer = leeren"),
        "help_keep_steam": (
            "Nie zamykaj Steam (zmiana może zostać nadpisana)",
            "Do not close Steam (the change may be overwritten)",
            "Steam nicht schließen (die Änderung kann überschrieben werden)",
        ),
        "help_clear": ("Wyczyść opcje gry", "Clear a game’s options", "Spieloptionen leeren"),
        "help_tools": (
            "Pokaż zainstalowane wersje Protona",
            "Show installed Proton versions",
            "Installierte Proton-Versionen zeigen",
        ),
        "help_proton": (
            "Pokaż albo ustaw wersję Protona dla gry",
            "Show or set a game’s Proton version",
            "Proton-Version eines Spiels zeigen oder setzen",
        ),
        "help_proton_tool": (
            "Nazwa Protona; 'default' = globalny Steam Play",
            "Proton name; 'default' = global Steam Play",
            "Proton-Name; 'default' = globales Steam Play",
        ),
        "help_install": (
            "Doinstaluj GE-Proton albo Proton-CachyOS (bez nazwy = lista wydań)",
            "Install GE-Proton or Proton-CachyOS (no name = list releases)",
            "GE-Proton oder Proton-CachyOS installieren (ohne Name = Ausgabenliste)",
        ),
        "help_install_version": (
            "np. GE-Proton, cachyos, GE-Proton11-6",
            "e.g. GE-Proton, cachyos, GE-Proton11-6",
            "z. B. GE-Proton, cachyos, GE-Proton11-6",
        ),
        "help_uninstall": ("Usuń własną wersję Protona", "Remove a custom Proton version", "Eigene Proton-Version entfernen"),
        "help_uninstall_version": (
            "Nazwa katalogu, np. GE-Proton11-5-x86_64",
            "Folder name, e.g. GE-Proton11-5-x86_64",
            "Ordnername, z. B. GE-Proton11-5-x86_64",
        ),
        "help_export": (
            "Zapisz ustawienia gier do pliku JSON",
            "Save game settings to a JSON file",
            "Spieleinstellungen in eine JSON-Datei schreiben",
        ),
        "help_export_path": ("np. perun-gry.json", "e.g. perun-games.json", "z. B. perun-spiele.json"),
        "help_export_game": (
            "Tylko ta gra (nazwa albo AppID). Bez tej opcji: wszystkie gry z własnymi ustawieniami.",
            "Only this game (name or AppID). Without it: every game with its own settings.",
            "Nur dieses Spiel (Name oder AppID). Ohne die Option: alle Spiele mit eigenen Einstellungen.",
        ),
        "help_import": (
            "Wczytaj ustawienia gier z pliku JSON",
            "Load game settings from a JSON file",
            "Spieleinstellungen aus einer JSON-Datei laden",
        ),
        "help_import_path": (
            "plik zapisany przez perun export",
            "a file written by perun export",
            "eine von perun export geschriebene Datei",
        ),
        "help_steam": (
            "Pokaż albo ustaw bibliotekę i status Steam",
            "Show or set the Steam library and status",
            "Steam-Bibliothek und Status zeigen oder setzen",
        ),
        "help_library": (
            "on = uruchamiaj Steam w bibliotece",
            "on = start Steam in the Library",
            "on = Steam in der Bibliothek starten",
        ),
        "help_installed_flag": (
            "on = w bibliotece tylko gry zainstalowane lokalnie",
            "on = library shows only games installed locally",
            "on = die Bibliothek zeigt nur lokal installierte Spiele",
        ),
        "help_status": (
            "Status znajomych wpisywany przed startem Steam",
            "Friends status written before Steam starts",
            "Freundesstatus, der vor dem Steam-Start geschrieben wird",
        ),
        "err_unknown_status": (
            "Nieznany status Steam: {name}",
            "Unknown Steam status: {name}",
            "Unbekannter Steam-Status: {name}",
        ),
        "err_no_vdf": (
            "Brak pakietu python-vdf. Zainstaluj: pacman -S python-vdf",
            "The python-vdf package is missing. Install it: pacman -S python-vdf",
            "Das Paket python-vdf fehlt. Installieren: pacman -S python-vdf",
        ),
        "err_no_vdf_short": ("Brak pakietu python-vdf.", "The python-vdf package is missing.", "Das Paket python-vdf fehlt."),
        "err_library_state": (
            "Nie udało się odczytać stanu biblioteki Steam.",
            "Could not read the Steam library state.",
            "Der Zustand der Steam-Bibliothek konnte nicht gelesen werden.",
        ),
        "err_no_steam": (
            "Nie znaleziono instalacji Steam.",
            "The Steam installation was not found.",
            "Die Steam-Installation wurde nicht gefunden.",
        ),
        "err_bad_sha_file": ("Niepoprawny plik SHA512.", "The SHA512 file is invalid.", "Die SHA512-Datei ist ungültig."),
        "err_github_http": ("GitHub HTTP {code}: {url}", "GitHub HTTP {code}: {url}", "GitHub HTTP {code}: {url}"),
        "err_github_connect": (
            "Nie udało się połączyć z GitHubem: {reason}",
            "Could not connect to GitHub: {reason}",
            "Keine Verbindung zu GitHub: {reason}",
        ),
        "err_github_list": (
            "GitHub nie zwrócił listy wydań.",
            "GitHub did not return a release list.",
            "GitHub hat keine Ausgabenliste geliefert.",
        ),
        "err_unknown_flavor": (
            "Nieznany rodzaj Protona: {name}",
            "Unknown Proton kind: {name}",
            "Unbekannte Proton-Art: {name}",
        ),
        "err_proton_query": (
            "Podaj nazwę Protona, np. GE-Proton albo cachyos.",
            "Give a Proton name, for example GE-Proton or cachyos.",
            "Gib einen Proton-Namen an, zum Beispiel GE-Proton oder cachyos.",
        ),
        "err_no_releases": ("Brak wydań: {name}", "No releases: {name}", "Keine Ausgaben: {name}"),
        "err_proton_missing": (
            "Nie znaleziono Protona: {name}",
            "Proton not found: {name}",
            "Proton nicht gefunden: {name}",
        ),
        "err_proton_ambiguous": (
            "Kilka pasujących wydań, podaj dokładniejszą nazwę: {names}",
            "Several releases match. Give a more exact name: {names}",
            "Mehrere Ausgaben passen. Gib einen genaueren Namen an: {names}",
        ),
        "err_download_cancelled": ("Anulowano pobieranie.", "Download cancelled.", "Download abgebrochen."),
        "err_empty_archive": ("Puste archiwum Protona.", "The Proton archive is empty.", "Das Proton-Archiv ist leer."),
        "err_bad_archive_path": (
            "Podejrzana ścieżka w archiwum: {name}",
            "Suspicious path in the archive: {name}",
            "Verdächtiger Pfad im Archiv: {name}",
        ),
        "err_bad_archive_root": (
            "Archiwum Protona ma dziwny katalog główny.",
            "The Proton archive has a strange root folder.",
            "Das Proton-Archiv hat einen merkwürdigen Stammordner.",
        ),
        "err_no_download": (
            "Brak pliku do pobrania dla {name}.",
            "There is no file to download for {name}.",
            "Für {name} gibt es keine Datei zum Herunterladen.",
        ),
        "err_sha_mismatch": (
            "Suma SHA512 się nie zgadza dla {name} — przerwano.",
            "The SHA512 sum does not match for {name} — stopped.",
            "Die SHA512-Summe für {name} stimmt nicht — abgebrochen.",
        ),
        "err_extract_dir": (
            "Rozpakowanie nie utworzyło katalogu Protona.",
            "Unpacking did not create a Proton folder.",
            "Das Entpacken hat keinen Proton-Ordner erzeugt.",
        ),
        "err_already_installed": (
            "Już zainstalowane: {name}",
            "Already installed: {name}",
            "Schon installiert: {name}",
        ),
        "err_cannot_remove": (
            "Tego Protona nie można usunąć z Peruna: {name}. Oficjalne wersje Steam zostaw w kliencie Steam.",
            "Perun cannot remove this Proton: {name}. Leave official Steam versions in the Steam client.",
            "Perun kann dieses Proton nicht entfernen: {name}. Offizielle Steam-Versionen bleiben im Steam-Client.",
        ),
        "err_no_shortcuts": ("Nie znaleziono shortcuts.vdf.", "shortcuts.vdf was not found.", "shortcuts.vdf wurde nicht gefunden."),
        "err_no_shortcut_index": (
            "Nie znaleziono skrótu o indeksie {index}.",
            "No shortcut with index {index} was found.",
            "Keine Verknüpfung mit Index {index} gefunden.",
        ),
        "err_shortcut_no_index": (
            "Skrót nie ma indeksu w shortcuts.vdf.",
            "The shortcut has no index in shortcuts.vdf.",
            "Die Verknüpfung hat keinen Index in shortcuts.vdf.",
        ),
        "err_no_localconfig": (
            "Nie znaleziono localconfig.vdf.",
            "localconfig.vdf was not found.",
            "localconfig.vdf wurde nicht gefunden.",
        ),
        "err_no_config": ("Nie znaleziono config.vdf.", "config.vdf was not found.", "config.vdf wurde nicht gefunden."),
        "err_no_config_file": (
            "Nie znaleziono pliku konfiguracji Steam.",
            "The Steam config file was not found.",
            "Die Steam-Konfigurationsdatei wurde nicht gefunden.",
        ),
        "err_steam_running": (
            "Steam jest uruchomiony i nadpisze pliki konfiguracji przy wyjściu. Zamknij Steam albo użyj zapisu z automatycznym zamknięciem.",
            "Steam is running and will overwrite the config files when it exits. Close Steam, or save with the automatic close.",
            "Steam läuft und überschreibt die Konfigurationsdateien beim Beenden. Schließe Steam oder speichere mit automatischem Schließen.",
        ),
        "err_no_account": ("Nie znaleziono konta Steam.", "The Steam account was not found.", "Das Steam-Konto wurde nicht gefunden."),
        "err_read_persona": (
            "Nie udało się odczytać statusu Steam.",
            "Could not read the Steam status.",
            "Der Steam-Status konnte nicht gelesen werden.",
        ),
        "err_steam_timeout": (
            "Steam nie zamknął się w oczekiwanym czasie.",
            "Steam did not close in time.",
            "Steam hat sich nicht rechtzeitig geschlossen.",
        ),
        "err_bad_export": (
            "Nie można odczytać pliku ustawień: {error}",
            "Cannot read the settings file: {error}",
            "Die Einstellungsdatei kann nicht gelesen werden: {error}",
        ),
        "err_not_perun_file": (
            "To nie jest plik ustawień Peruna.",
            "This is not a Perun settings file.",
            "Das ist keine Perun-Einstellungsdatei.",
        ),
        "err_bad_version": (
            "Nieobsługiwana wersja pliku ustawień Peruna.",
            "This Perun settings file version is not supported.",
            "Diese Version der Perun-Einstellungsdatei wird nicht unterstützt.",
        ),
        "err_no_game_list": (
            "Plik ustawień nie zawiera listy gier.",
            "The settings file does not contain a game list.",
            "Die Einstellungsdatei enthält keine Spielliste.",
        ),
        "skip_broken": ("uszkodzony wpis", "broken entry", "beschädigter Eintrag"),
        "skip_ambiguous": ("niejednoznaczny", "ambiguous", "mehrdeutig"),
        "skip_missing": ("brak", "missing", "fehlt"),
        "skip_shortcut": ("skrót ({reason}): {label}", "shortcut ({reason}): {label}", "Verknüpfung ({reason}): {label}"),
        "skip_game": ("gra: {name}", "game: {name}", "Spiel: {name}"),
        "err_appinfo_string": ("ucięty napis w appinfo.vdf", "truncated string in appinfo.vdf", "abgeschnittener Text in appinfo.vdf"),
        "err_appinfo_key": ("ucięty klucz w appinfo.vdf", "truncated key in appinfo.vdf", "abgeschnittener Schlüssel in appinfo.vdf"),
        "err_appinfo_int": ("ucięta liczba w appinfo.vdf", "truncated number in appinfo.vdf", "abgeschnittene Zahl in appinfo.vdf"),
        "err_appinfo_float": ("ucięty float w appinfo.vdf", "truncated float in appinfo.vdf", "abgeschnittener Float in appinfo.vdf"),
        "err_appinfo_u64": ("ucięty uint64 w appinfo.vdf", "truncated uint64 in appinfo.vdf", "abgeschnittenes uint64 in appinfo.vdf"),
        "err_appinfo_type": (
            "nieznany typ appinfo {kind}",
            "unknown appinfo type {kind}",
            "unbekannter appinfo-Typ {kind}",
        ),
        "err_github_rate": (
            "GitHub ograniczył zapytania (limit API). Spróbuj za chwilę.",
            "GitHub limited the requests (API limit). Try again in a moment.",
            "GitHub hat die Anfragen begrenzt (API-Limit). Versuch es gleich noch einmal.",
        ),
        "cli_and_more": (" (i inne)", " (and others)", " (und weitere)"),
        "skip_shortcut_word": ("skrót", "shortcut", "Verknüpfung"),
    }
)


UNCHANGED = object()

BACKUP_DIR = Path.home() / ".local/share/perun/backups"
BACKUP_KEEP = 10
PERUN_DIR = BACKUP_DIR.parent
VIEW_PATH = PERUN_DIR / "view.json"

EXPORT_FORMAT = "perun-games"
EXPORT_VERSION = 1
STEAM_LIBRARY_DIALOG = "#app_games"
STEAM_STORE_DIALOG = "#app_store"
# EPersonaState. 4 (snooze) ustawia sam klient i nie ma go na liście.
PERSONA_STATES: tuple[tuple[int, str, str], ...] = (
    (1, "online", "persona_online"),
    (7, "invisible", "persona_invisible"),
    (3, "away", "persona_away"),
    (0, "offline", "persona_offline"),
    (2, "busy", "persona_busy"),
    (6, "play", "persona_play"),
    (5, "trade", "persona_trade"),
)
PERSONA_VIEW_KEY = "persona_state"
# Grupa 0 to rodzaj aplikacji, grupa 1 to stan gry. Opcja 1 = zainstalowane lokalnie.
PLAY_STATE_GROUP = 1
INSTALLED_OPTION = 1
FILTER_GROUP_COUNT = 9
LIBRARY_FILTER_KEYS = (
    "collectionFilter",
    "collectionFilterGamepad",
    "collectionFilterVR",
)
APPINFO_MAGIC = 0x07564429
# Manifest Steam Play trzyma nazwy narzędzi i aliasy w rodzaju proton-stable.
STEAM_PLAY_MANIFEST_APPID = 891390
_APPINFO_CACHE: tuple[tuple[str, int, int], dict[str, tuple[str, str]]] | None = None
_COMPAT_CACHE: tuple[tuple[str, int, int], list[CompatTool]] | None = None
_COMPAT_LABELS: dict[str, str] = {}

TOOL_NAME_PREFIXES = (
    "Steam Linux Runtime",
    "Proton ",
    "Proton-",
)
TOOL_NAME_EXACT = {
    "Proton",
    "Proton Experimental",
    "Proton Hotfix",
    "Proton BattlEye Runtime",
    "Proton EasyAntiCheat Runtime",
    "Steamworks Common Redistributables",
}
TOOL_APPIDS = {
    "228980",
    "1070560",
    "1391110",
    "1628350",
    "4183110",
    "1493710",
    "2180100",
    "1161040",
    "1826330",
    "1391110",
}

# (klucz tytułu, klucz opisu, [(klucz etykiety, komenda, klucz opisu)])
PRESET_GROUPS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "preset_image",
        "preset_image_desc",
        [
            ("preset_novid", "-novid", "preset_novid_tip"),
            ("preset_full", "-fullscreen", "preset_full_tip"),
            ("preset_window", "-windowed", "preset_window_tip"),
            ("preset_uw", "-w 3440 -h 1440", "preset_uw_tip"),
        ],
    ),
    (
        "preset_proton",
        "preset_proton_desc",
        [
            ("preset_nvapi", "PROTON_ENABLE_NVAPI=1", "preset_nvapi_tip"),
            ("preset_dxvk", "DXVK_HUD=fps", "preset_dxvk_tip"),
            ("preset_wined3d", "PROTON_USE_WINED3D=1", "preset_wined3d_tip"),
            ("preset_noesync", "PROTON_NO_ESYNC=1", "preset_noesync_tip"),
            ("preset_vkd3d", "VKD3D_CONFIG=no_upload_hvv", "preset_vkd3d_tip"),
        ],
    ),
]

# MangoHud: bazowy zestaw (jak w domyślnym conf) dopisywany tylko gdy user
# ustawi cokolwiek własnego — sam przełącznik HUD-a nie dodaje MANGOHUD_CONFIG.
MANGO_BASELINE = (
    "fps",
    "gpu_stats",
    "cpu_stats",
    "frametime",
    "frame_timing",
    "throttling_status",
)
MANGO_FLAG_OPTIONS: list[tuple[str, str, str]] = [
    ("gpu_temp", "flag_gpu_temp", "flag_gpu_temp_sub"),
    ("gpu_power", "flag_gpu_power", "flag_gpu_power_sub"),
    ("gpu_core_clock", "flag_gpu_clock", "flag_gpu_clock_sub"),
    ("cpu_temp", "flag_cpu_temp", "flag_cpu_temp_sub"),
    ("vram", "flag_vram", "flag_vram_sub"),
    ("ram", "flag_ram", "flag_ram_sub"),
    ("wine", "flag_wine", "flag_wine_sub"),
    ("resolution", "flag_resolution", "flag_resolution_sub"),
    ("hud_compact", "flag_compact", "flag_compact_sub"),
    ("horizontal", "flag_horizontal", "flag_horizontal_sub"),
    ("no_display", "flag_hidden", "flag_hidden_sub"),
]
MANGO_POSITIONS: list[tuple[str, str]] = [
    ("", "pos_default"),
    ("top-left", "pos_tl"),
    ("top-center", "pos_tc"),
    ("top-right", "pos_tr"),
    ("bottom-left", "pos_bl"),
    ("bottom-center", "pos_bc"),
    ("bottom-right", "pos_br"),
]
MANGO_FPS_LIMITS: list[tuple[str, str]] = [
    ("", "fps_off"),
    ("60", "fps_60"),
    ("90", "fps_90"),
    ("120", "fps_120"),
    ("144", "fps_144"),
    ("165", "fps_165"),
    ("175", "fps_175"),
    ("180", "fps_180"),
    ("240", "fps_240"),
]
MANGO_FONT_SIZES: list[tuple[str, str]] = [
    ("", "font_default"),
    ("16", "font_16"),
    ("20", "font_20"),
    ("24", "font_24"),
    ("28", "font_28"),
    ("32", "font_32"),
]
MANGO_FLAG_KEYS = {key for key, _, _ in MANGO_FLAG_OPTIONS}
MANGO_VALUE_KEYS = {"position", "fps_limit", "font_size"}
MANGO_KNOWN_KEYS = set(MANGO_BASELINE) | MANGO_FLAG_KEYS | MANGO_VALUE_KEYS

# GameMode czyta ~/.config/gamemode.ini. To ustawienia demona, wspólne dla gier.
GAMEMODE_GOVERNORS: list[tuple[str, str]] = [
    ("performance", "gov_performance"),
    ("powersave", "gov_powersave"),
]
GAMEMODE_GOV_AFTER: list[tuple[str, str]] = [
    ("", "gov_restore"),
    ("powersave", "gov_powersave"),
    ("performance", "gov_keep_perf"),
]
GAMEMODE_RENICE: list[tuple[str, str]] = [
    ("0", "renice_none"),
    ("5", "renice_higher"),
    ("10", "renice_high"),
    ("15", "renice_very"),
]
GAMEMODE_IOPRIO: list[tuple[str, str]] = [
    ("0", "io_highest"),
    ("4", "io_normal"),
    ("off", "io_off"),
]


# --- GameMode (wspólny plik demona) -----------------------------------------

@dataclass
class GameModeConfig:
    desiredgov: str = "performance"
    defaultgov: str = ""
    renice: int = 0
    ioprio: str = "0"
    inhibit_screensaver: bool = True
    nv_max_performance: bool = False


def gamemode_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "gamemode.ini"


def _ini_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    return parser


def _ini_get(parser: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    if not parser.has_section(section) or not parser.has_option(section, key):
        return default
    return parser.get(section, key).strip()


def load_gamemode_config(path: Path | None = None) -> GameModeConfig:
    path = path or gamemode_config_path()
    cfg = GameModeConfig()
    if not path.is_file():
        return cfg
    parser = _ini_parser()
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error:
        return cfg
    gov = _ini_get(parser, "general", "desiredgov", "performance").lower()
    cfg.desiredgov = gov if gov in {"performance", "powersave"} else "performance"
    after = _ini_get(parser, "general", "defaultgov", "").lower()
    cfg.defaultgov = after if after in {"", "performance", "powersave"} else ""
    try:
        cfg.renice = int(_ini_get(parser, "general", "renice", "0") or "0")
    except ValueError:
        cfg.renice = 0
    cfg.renice = min(20, max(0, cfg.renice))
    ioprio = _ini_get(parser, "general", "ioprio", "0").lower()
    cfg.ioprio = ioprio if ioprio in {"0", "1", "2", "3", "4", "5", "6", "7", "off", "reset"} else "0"
    inhibit = _ini_get(parser, "general", "inhibit_screensaver", "1").lower()
    cfg.inhibit_screensaver = inhibit not in {"0", "false", "no", "off"}
    cfg.nv_max_performance = _ini_get(parser, "gpu", "nv_powermizer_mode", "") == "1"
    return cfg


def save_gamemode_config(cfg: GameModeConfig, path: Path | None = None) -> None:
    path = path or gamemode_config_path()
    parser = _ini_parser()
    if path.is_file():
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error:
            parser = _ini_parser()
    if not parser.has_section("general"):
        parser.add_section("general")
    gov = cfg.desiredgov if cfg.desiredgov in {"performance", "powersave"} else "performance"
    parser.set("general", "desiredgov", gov)
    if cfg.defaultgov in {"performance", "powersave"}:
        parser.set("general", "defaultgov", cfg.defaultgov)
    elif parser.has_option("general", "defaultgov"):
        parser.remove_option("general", "defaultgov")
    parser.set("general", "renice", str(min(20, max(0, int(cfg.renice)))))
    ioprio = cfg.ioprio if cfg.ioprio in {"0", "1", "2", "3", "4", "5", "6", "7", "off", "reset"} else "0"
    parser.set("general", "ioprio", ioprio)
    parser.set("general", "inhibit_screensaver", "1" if cfg.inhibit_screensaver else "0")
    if cfg.nv_max_performance:
        if not parser.has_section("gpu"):
            parser.add_section("gpu")
        parser.set("gpu", "apply_gpu_optimisations", "accept-responsibility")
        parser.set("gpu", "nv_powermizer_mode", "1")
    elif parser.has_section("gpu") and _ini_get(parser, "gpu", "nv_powermizer_mode") == "1":
        parser.remove_option("gpu", "nv_powermizer_mode")
        leftover = [key for key in parser.options("gpu") if key != "apply_gpu_optimisations"]
        if not leftover:
            parser.remove_section("gpu")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _render_ini(parser)
    tmp = path.with_suffix(".ini.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _render_ini(parser: configparser.ConfigParser) -> str:
    lines: list[str] = []
    for section in parser.sections():
        lines.append(f"[{section}]")
        for key, value in parser.items(section):
            lines.append(f"{key}={value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def user_in_gamemode_group() -> bool:
    try:
        import grp

        gid = grp.getgrnam("gamemode").gr_gid
    except KeyError:
        return False
    return gid in os.getgroups()


# --- ścieżki Steam ----------------------------------------------------------

def steam_root() -> Path | None:
    for candidate in (
        Path.home() / ".local/share/Steam",
        Path.home() / ".steam/steam",
        Path.home() / ".steam/root",
    ):
        if (candidate / "steamapps").is_dir() or (candidate / "config").is_dir():
            return candidate.resolve()
    return None


def library_folders(root: Path) -> list[Path]:
    folders: list[Path] = []
    for manifest in (
        root / "steamapps" / "libraryfolders.vdf",
        root / "config" / "libraryfolders.vdf",
    ):
        if not manifest.is_file() or vdf is None:
            continue
        try:
            data = vdf.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        libs = data.get("libraryfolders", data)
        if not isinstance(libs, dict):
            continue
        for entry in libs.values():
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if path:
                p = Path(str(path))
                if p.is_dir() and p not in folders:
                    folders.append(p)
    steamapps = root / "steamapps"
    if steamapps.is_dir() and root not in folders:
        folders.insert(0, root)
    if not folders:
        folders.append(root)
    return folders


def login_account_id(root: Path) -> str | None:
    login = root / "config" / "loginusers.vdf"
    if not login.is_file() or vdf is None:
        return None
    try:
        data = vdf.loads(login.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    users = data.get("users", {})
    if not isinstance(users, dict) or not users:
        return None
    chosen_id = None
    chosen_ts = -1
    for steamid64, info in users.items():
        if not isinstance(info, dict):
            continue
        if str(info.get("AutoLogin", "0")) == "1" or str(info.get("MostRecent", "0")) == "1":
            chosen_id = steamid64
            break
        try:
            ts = int(info.get("Timestamp", 0))
        except (TypeError, ValueError):
            ts = 0
        if ts >= chosen_ts:
            chosen_ts = ts
            chosen_id = steamid64
    if not chosen_id:
        return None
    try:
        return str(int(chosen_id) - 76561197960265728)
    except ValueError:
        return None


def userdata_dirs(root: Path) -> list[Path]:
    base = root / "userdata"
    if not base.is_dir():
        return []
    return [p for p in base.iterdir() if p.is_dir() and p.name.isdigit()]


def localconfig_path(root: Path) -> Path | None:
    account = login_account_id(root)
    if account:
        path = root / "userdata" / account / "config" / "localconfig.vdf"
        if path.is_file():
            return path
    newest: Path | None = None
    newest_mtime = -1.0
    for userdir in userdata_dirs(root):
        path = userdir / "config" / "localconfig.vdf"
        if not path.is_file():
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest = path
            newest_mtime = mtime
    return newest


def config_vdf_path(root: Path) -> Path:
    return root / "config" / "config.vdf"


def sharedconfig_path(root: Path) -> Path | None:
    account = login_account_id(root)
    if not account:
        return None
    return root / "userdata" / account / "7" / "remote" / "sharedconfig.vdf"


def _load_view() -> dict:
    try:
        data = json.loads(VIEW_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_view_updates(updates: dict) -> None:
    data = _load_view()
    data.update(updates)
    PERUN_DIR.mkdir(parents=True, exist_ok=True)
    VIEW_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_show_all_games() -> bool:
    return bool(_load_view().get("all_accounts"))


def save_show_all_games(enabled: bool) -> None:
    _save_view_updates({"all_accounts": bool(enabled)})


def load_language() -> str:
    raw = _load_view().get("language")
    return set_language(str(raw) if raw is not None else "pl")


def save_language(code: str) -> str:
    chosen = set_language(code)
    _save_view_updates({"language": chosen})
    return chosen


def persona_value(name: str) -> int:
    for value, key, _label in PERSONA_STATES:
        if key == name:
            return value
    raise ValueError(t("err_unknown_status", name=name))


def persona_label(state: int | None) -> str:
    for value, _key, label_key in PERSONA_STATES:
        if value == state:
            return t(label_key)
    if state is None:
        return t("persona_missing")
    return t("persona_other", state=state)


def load_persona_preference() -> int | None:
    raw = _load_view().get(PERSONA_VIEW_KEY)
    try:
        state = int(raw)
    except (TypeError, ValueError):
        return None
    if state not in {value for value, _key, _label in PERSONA_STATES}:
        return None
    return state


def save_persona_preference(state: int) -> None:
    if state not in {value for value, _key, _label in PERSONA_STATES}:
        raise ValueError(t("err_unknown_status", name=state))
    _save_view_updates({PERSONA_VIEW_KEY: int(state)})


# --- VDF helpers ------------------------------------------------------------

def _vdf_get(node: dict, *keys: str):
    cur = node
    for key in keys:
        if not isinstance(cur, dict):
            return None
        match = None
        for ck in cur:
            if str(ck).lower() == key.lower():
                match = ck
                break
        if match is None:
            return None
        cur = cur[match]
    return cur


def _vdf_ensure(node: dict, *keys: str) -> dict:
    cur = node
    for key in keys:
        found = None
        for ck in cur:
            if str(ck).lower() == key.lower() and isinstance(cur[ck], dict):
                found = ck
                break
        if found is None:
            cur[key] = {}
            found = key
        cur = cur[found]
    return cur


def load_vdf(path: Path) -> dict:
    if vdf is None:
        raise RuntimeError(t("err_no_vdf"))
    return vdf.loads(path.read_text(encoding="utf-8", errors="replace"))


def _dump_vdf(data: dict) -> str:
    if vdf is None:
        raise RuntimeError(t("err_no_vdf"))
    buf = io.StringIO()
    vdf.dump(data, buf, pretty=True)
    return buf.getvalue()


def _read_cstring(data: bytes, offset: int) -> tuple[str, int]:
    end = data.find(b"\x00", offset)
    if end < 0:
        raise ValueError(t("err_appinfo_string"))
    return data[offset:end].decode("utf-8", "replace"), end + 1


def _parse_appinfo_map(
    data: bytes, offset: int, end: int, strings: list[str]
) -> tuple[dict, int]:
    node: dict = {}
    while offset < end:
        kind = data[offset]
        offset += 1
        if kind == 0x08:
            return node, offset
        if offset + 4 > end:
            raise ValueError(t("err_appinfo_key"))
        key_index = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        key = strings[key_index] if 0 <= key_index < len(strings) else str(key_index)
        if kind == 0x00:
            child, offset = _parse_appinfo_map(data, offset, end, strings)
            node[key] = child
        elif kind == 0x01:
            value, offset = _read_cstring(data, offset)
            node[key] = value
        elif kind == 0x02:
            if offset + 4 > len(data):
                raise ValueError(t("err_appinfo_int"))
            node[key] = struct.unpack_from("<i", data, offset)[0]
            offset += 4
        elif kind == 0x03:
            if offset + 4 > len(data):
                raise ValueError(t("err_appinfo_float"))
            node[key] = struct.unpack_from("<f", data, offset)[0]
            offset += 4
        elif kind == 0x07:
            if offset + 8 > len(data):
                raise ValueError(t("err_appinfo_u64"))
            node[key] = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
        else:
            raise ValueError(t("err_appinfo_type", kind=f"{kind:#x}"))
    return node, offset


def _common_name_type(node: object) -> tuple[str, str]:
    if not isinstance(node, dict):
        return "", ""
    common = node.get("common")
    if isinstance(common, dict):
        name = common.get("name")
        kind = common.get("type")
        return (
            name if isinstance(name, str) else "",
            kind if isinstance(kind, str) else "",
        )
    for value in node.values():
        found = _common_name_type(value)
        if found != ("", ""):
            return found
    return "", ""


def parse_appinfo_bytes(data: bytes) -> dict[str, tuple[str, str]]:
    """AppID → (nazwa, typ) z appinfo.vdf w układzie v41."""
    if len(data) < 16:
        return {}
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != APPINFO_MAGIC:
        return {}
    table_at = struct.unpack_from("<q", data, 8)[0]
    if table_at <= 16 or table_at >= len(data):
        return {}
    count = struct.unpack_from("<I", data, table_at)[0]
    offset = table_at + 4
    strings: list[str] = []
    for _ in range(count):
        text, offset = _read_cstring(data, offset)
        strings.append(text)
    out: dict[str, tuple[str, str]] = {}
    cursor = 16
    while cursor + 8 <= table_at and cursor + 8 <= len(data):
        appid = struct.unpack_from("<I", data, cursor)[0]
        size = struct.unpack_from("<I", data, cursor + 4)[0]
        if appid == 0 or size < 60:
            break
        blob_at = cursor + 68
        blob_end = blob_at + (size - 60)
        if blob_end > len(data):
            break
        try:
            tree, _ = _parse_appinfo_map(data, blob_at, blob_end, strings)
            out[str(appid)] = _common_name_type(tree)
        except (ValueError, IndexError, UnicodeError):
            pass
        cursor += 8 + size
    return out


def appinfo_index(root: Path) -> dict[str, tuple[str, str]]:
    global _APPINFO_CACHE
    path = root / "appcache" / "appinfo.vdf"
    if not path.is_file():
        return {}
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _APPINFO_CACHE is not None and _APPINFO_CACHE[0] == key:
        return _APPINFO_CACHE[1]
    try:
        parsed = parse_appinfo_bytes(path.read_bytes())
    except (OSError, ValueError):
        return {}
    _APPINFO_CACHE = (key, parsed)
    return parsed


def _blank_library_filter() -> dict:
    groups = []
    for index in range(FILTER_GROUP_COUNT):
        if index == 0:
            groups.append({"rgOptions": [1, 2], "bAcceptUnion": True})
        else:
            groups.append({"rgOptions": [], "bAcceptUnion": False})
    return {
        "nFormatVersion": 2,
        "strSearchText": "",
        "filterGroups": groups,
        "setSuggestions": {},
    }


def _coerce_library_filter(filt: dict) -> None:
    raw_groups = filt.get("filterGroups")
    groups: list[dict] = []
    if isinstance(raw_groups, list):
        for item in raw_groups:
            if not isinstance(item, dict):
                groups.append({"rgOptions": [], "bAcceptUnion": False})
                continue
            options: list[int] = []
            for opt in item.get("rgOptions") or []:
                try:
                    options.append(int(opt))
                except (TypeError, ValueError):
                    continue
            groups.append(
                {"rgOptions": options, "bAcceptUnion": bool(item.get("bAcceptUnion"))}
            )
    while len(groups) < FILTER_GROUP_COUNT:
        if len(groups) == 0:
            groups.append({"rgOptions": [1, 2], "bAcceptUnion": True})
        else:
            groups.append({"rgOptions": [], "bAcceptUnion": False})
    filt["filterGroups"] = groups
    filt.setdefault("nFormatVersion", 2)
    filt.setdefault("strSearchText", "")
    if not isinstance(filt.get("setSuggestions"), dict):
        filt["setSuggestions"] = {}


def filter_shows_installed_only(state: dict | None) -> bool:
    if not isinstance(state, dict):
        return False
    filt = state.get("collectionFilter")
    if not isinstance(filt, dict):
        return False
    groups = filt.get("filterGroups")
    if not isinstance(groups, list) or len(groups) <= PLAY_STATE_GROUP:
        return False
    group = groups[PLAY_STATE_GROUP]
    if not isinstance(group, dict):
        return False
    options: list[int] = []
    for opt in group.get("rgOptions") or []:
        try:
            options.append(int(opt))
        except (TypeError, ValueError):
            return False
    return options == [INSTALLED_OPTION]


def set_installed_only_filter(state: dict | None, enabled: bool) -> dict:
    if isinstance(state, dict):
        state = json.loads(json.dumps(state))
    else:
        state = {"nVersion": 1}
    if not isinstance(state, dict):
        state = {"nVersion": 1}
    state.setdefault("nVersion", 1)
    for key in LIBRARY_FILTER_KEYS:
        filt = state.get(key)
        if not isinstance(filt, dict):
            if not enabled:
                continue
            filt = _blank_library_filter()
            state[key] = filt
        _coerce_library_filter(filt)
        group = filt["filterGroups"][PLAY_STATE_GROUP]
        if enabled:
            group["rgOptions"] = [INSTALLED_OPTION]
            group["bAcceptUnion"] = False
        else:
            group["rgOptions"] = [
                opt for opt in group["rgOptions"] if opt != INSTALLED_OPTION
            ]
    return state


def mutate_steam_default_dialog(data: dict, library: bool) -> None:
    steam = _vdf_ensure(data, "UserRoamingConfigStore", "Software", "Valve", "Steam")
    current = None
    for key in steam:
        if str(key).lower() == "steamdefaultdialog":
            current = str(steam[key] or "")
            break
    if library:
        _vdf_set_ci(steam, "SteamDefaultDialog", STEAM_LIBRARY_DIALOG)
    elif current == STEAM_LIBRARY_DIALOG:
        _vdf_set_ci(steam, "SteamDefaultDialog", STEAM_STORE_DIALOG)


def _ui_state_from_localconfig(data: dict) -> tuple[dict, str, dict | None]:
    store = _vdf_ensure(data, "UserLocalConfigStore")
    web = None
    for key in store:
        if str(key).lower() == "webstorage" and isinstance(store[key], dict):
            web = store[key]
            break
    if web is None:
        web = {}
        store["WebStorage"] = web
    state_key = "UIStoreLocalSteamUIState"
    raw = None
    for key in web:
        if str(key).lower() == "uistorelocalsteamuistate":
            state_key = str(key)
            raw = web[key]
            break
    state = None
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(t("err_library_state")) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(t("err_library_state"))
        state = parsed
    return web, state_key, state


# --- gry --------------------------------------------------------------------

@dataclass
class Game:
    appid: str
    name: str
    installdir: Path | None
    launch_options: str = ""
    last_played: int = 0
    compat_tool: str = ""
    icon: Path | None = None
    is_shortcut: bool = False
    shortcut_index: str | None = None
    launch_id: str = ""
    installed: bool = True


@dataclass
class CompatTool:
    name: str
    display: str
    official: bool = False
    install_path: Path | None = None
    # (grupa, …). Puste dla narzędzi z compatibilitytools.d — te sortuje osobno lista.
    rank: tuple = ()


@dataclass
class ProtonRelease:
    flavor_id: str
    flavor_name: str
    tag: str
    name: str
    download_url: str
    checksum_url: str | None
    size: int
    date: str
    installed: bool = False


def _is_tool(appid: str, name: str) -> bool:
    if appid in TOOL_APPIDS:
        return True
    if name in TOOL_NAME_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in TOOL_NAME_PREFIXES)


def _unsigned_appid(value: object) -> str:
    try:
        return str(int(value) & 0xFFFFFFFF)
    except (TypeError, ValueError):
        return str(value)


def shortcut_launch_id(unsigned_appid: str) -> str:
    return str((int(unsigned_appid) << 32) | 0x02000000)


def _search_text(game: Game) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", game.name.lower())
    return " ".join(
        part
        for part in (game.name.lower(), compact, game.appid, game.launch_id)
        if part
    )


def _find_icon(root: Path, appid: str, account: str | None = None) -> Path | None:
    home = Path.home()
    candidates = [
        home / f".local/share/icons/hicolor/128x128/apps/steam_icon_{appid}.png",
        home / f".local/share/icons/hicolor/256x256/apps/steam_icon_{appid}.png",
        home / f".local/share/icons/hicolor/48x48/apps/steam_icon_{appid}.png",
        root / "appcache" / "librarycache" / appid / "logo.png",
        root / "appcache" / "librarycache" / appid / "library_600x900.jpg",
    ]
    if account:
        grid = root / "userdata" / account / "config" / "grid"
        candidates.extend(
            [
                grid / f"{appid}_icon.jpg",
                grid / f"{appid}_icon.png",
                grid / f"{appid}.png",
                grid / f"{appid}.jpg",
                grid / f"{appid}p.jpg",
                grid / f"{appid}p.png",
            ]
        )
    cache = root / "appcache" / "librarycache" / appid
    if cache.is_dir():
        hashed = sorted(
            [p for p in cache.glob("*.jpg") if p.name.startswith("library_") is False],
            key=lambda p: p.stat().st_size,
        )
        candidates.extend(hashed[:1])
    for path in candidates:
        if path.is_file():
            return path
    return None


def _compat_map(root: Path) -> dict[str, str]:
    path = config_vdf_path(root)
    if not path.is_file():
        return {}
    try:
        data = load_vdf(path)
    except Exception:
        return {}
    mapping = _vdf_get(
        data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping"
    )
    if not isinstance(mapping, dict):
        return {}
    out: dict[str, str] = {}
    for appid, info in mapping.items():
        if appid == "0":
            continue
        if isinstance(info, dict) and info.get("name"):
            out[str(appid)] = str(info["name"])
    return out


def _apps_launch_map(root: Path) -> dict[str, dict]:
    path = localconfig_path(root)
    if not path or not path.is_file():
        return {}
    try:
        data = load_vdf(path)
    except Exception:
        return {}
    apps = _vdf_get(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
    if not isinstance(apps, dict):
        return {}
    return {str(k): v for k, v in apps.items() if isinstance(v, dict)}


def shortcuts_path(root: Path) -> Path | None:
    account = login_account_id(root)
    if account:
        path = root / "userdata" / account / "config" / "shortcuts.vdf"
        if path.is_file():
            return path
    newest: Path | None = None
    newest_mtime = -1.0
    for userdir in userdata_dirs(root):
        path = userdir / "config" / "shortcuts.vdf"
        if not path.is_file():
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest = path
            newest_mtime = mtime
    return newest


def default_compat_tool(root: Path | None = None) -> str:
    root = root or steam_root()
    if root is None:
        return ""
    path = config_vdf_path(root)
    if not path.is_file():
        return ""
    try:
        data = load_vdf(path)
    except Exception:
        return ""
    mapping = _vdf_get(
        data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping"
    )
    if not isinstance(mapping, dict):
        return ""
    zero = mapping.get("0")
    if isinstance(zero, dict):
        return str(zero.get("name") or "")
    return ""


def _arm_compat_tool(name: str) -> bool:
    low = name.lower()
    return low.endswith("-arm64") or low.endswith("_arm64")


def _flag_set(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false"}
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _from_windows(entry: dict) -> bool:
    raw = str(entry.get("from_oslist") or "")
    return "windows" in {part.strip().lower() for part in raw.split(",") if part.strip()}


def _proton_rank(name: str, display: str, *, alias_index: int | None, legacy: bool) -> tuple:
    if alias_index is not None:
        return (0, alias_index, 0, 0)
    low = name.lower()
    if "experimental" in low:
        return (1, 0, 0, 0)
    if "hotfix" in low:
        return (1, 1, 0, 0)
    match = re.search(r"(\d+)\.(\d+)(?:-(\d+))?", display) or re.search(
        r"(\d+)[._-](\d+)(?:[._-](\d+))?", name
    )
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3) or 0)
        return (3 if legacy else 2, -major, -minor, -patch)
    return (4, 0, 0, display.lower())


def _extended_compat(tree: object) -> dict | None:
    if not isinstance(tree, dict):
        return None
    nodes = [tree]
    appinfo = tree.get("appinfo")
    if isinstance(appinfo, dict):
        nodes.append(appinfo)
    for node in nodes:
        extended = node.get("extended")
        if isinstance(extended, dict) and isinstance(extended.get("compat_tools"), dict):
            return extended
    return None


def _iter_appinfo_trees(data: bytes):
    if len(data) < 16:
        return
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != APPINFO_MAGIC:
        return
    table_at = struct.unpack_from("<q", data, 8)[0]
    if table_at <= 16 or table_at >= len(data):
        return
    count = struct.unpack_from("<I", data, table_at)[0]
    offset = table_at + 4
    strings: list[str] = []
    for _ in range(count):
        text, offset = _read_cstring(data, offset)
        strings.append(text)
    cursor = 16
    while cursor + 8 <= table_at and cursor + 8 <= len(data):
        appid = struct.unpack_from("<I", data, cursor)[0]
        size = struct.unpack_from("<I", data, cursor + 4)[0]
        if appid == 0 or size < 60:
            break
        blob_at = cursor + 68
        blob_end = blob_at + (size - 60)
        if blob_end > len(data):
            break
        try:
            tree, _ = _parse_appinfo_map(data, blob_at, blob_end, strings)
        except (ValueError, IndexError, UnicodeError):
            tree = None
        if tree is not None:
            yield appid, tree
        cursor += 8 + size


def compat_tools_from_appinfo(data: bytes) -> list[CompatTool]:
    """Narzędzia Proton z appinfo.vdf, łącznie z aliasami w rodzaju Proton Stable.

    Klient Steam z października 2026 trzyma je w manifeście Steam Play (AppID 891390)
    oraz w osobnych listach, na przykład ARM64. `selectable_aliases` to pozycje,
    które da się wybrać w menu zgodności, niezależnie od numeru wydania.
    """
    global _COMPAT_LABELS
    catalogs: list[tuple[int, dict]] = []
    for appid, tree in _iter_appinfo_trees(data):
        extended = _extended_compat(tree)
        if extended is not None:
            catalogs.append((appid, extended))
    catalogs.sort(key=lambda item: (item[0] != STEAM_PLAY_MANIFEST_APPID, item[0]))

    arm_host = platform.machine().lower() in {"aarch64", "arm64"}
    by_name: dict[str, CompatTool] = {}
    labels: dict[str, str] = {}
    seen_aliases: set[str] = set()
    alias_index = 0

    for _appid, extended in catalogs:
        compat = extended.get("compat_tools")
        if not isinstance(compat, dict):
            continue
        for raw_name, entry in compat.items():
            name = str(raw_name).strip()
            if not name or not isinstance(entry, dict):
                continue
            if _arm_compat_tool(name) and not arm_host:
                continue
            if _flag_set(entry.get("unlisted")) or not _from_windows(entry):
                continue
            display = str(entry.get("display_name") or name).strip() or name
            legacy = _flag_set(entry.get("legacy"))
            tool = CompatTool(
                name=name,
                display=display,
                official=True,
                rank=_proton_rank(name, display, alias_index=None, legacy=legacy),
            )
            by_name.setdefault(name, tool)
            labels.setdefault(name, display)
            for alias in str(entry.get("aliases") or "").split(","):
                alias = alias.strip()
                if alias and alias != name:
                    labels.setdefault(alias, display)

        selectable = extended.get("selectable_aliases")
        if not isinstance(selectable, dict):
            continue
        for raw_alias, info in selectable.items():
            alias = str(raw_alias).strip()
            if not alias or alias in seen_aliases:
                continue
            if _arm_compat_tool(alias) and not arm_host:
                continue
            display = alias
            if isinstance(info, dict) and info.get("display_name"):
                display = str(info["display_name"]).strip() or alias
            seen_aliases.add(alias)
            labels[alias] = display
            by_name.setdefault(
                alias,
                CompatTool(
                    name=alias,
                    display=display,
                    official=True,
                    rank=_proton_rank(alias, display, alias_index=alias_index, legacy=False),
                ),
            )
            alias_index += 1

    _COMPAT_LABELS = labels
    return sorted(by_name.values(), key=lambda tool: tool.rank or (5, 0, 0, 0))


def steam_official_protons(root: Path) -> list[CompatTool]:
    global _COMPAT_CACHE
    path = root / "appcache" / "appinfo.vdf"
    if not path.is_file():
        return []
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _COMPAT_CACHE is not None and _COMPAT_CACHE[0] == key:
        return _COMPAT_CACHE[1]
    try:
        tools = compat_tools_from_appinfo(path.read_bytes())
    except (OSError, ValueError):
        return []
    _COMPAT_CACHE = (key, tools)
    return tools


def official_proton_internal(name: str) -> str | None:
    n = name.strip()
    exact = {
        "Proton Experimental": "proton_experimental",
        "Proton Hotfix": "proton_hotfix",
        "Proton Next": "proton_next",
    }
    if n in exact:
        return exact[n]
    match = re.match(r"^Proton (\d+)\.(\d+)", n)
    if not match:
        return None
    major, minor = match.group(1), match.group(2)
    special = {
        ("6", "3"): "proton_63",
        ("5", "13"): "proton_513",
        ("4", "11"): "proton_411",
        ("4", "2"): "proton_42",
        ("3", "16"): "proton_316",
        ("3", "7"): "proton_37",
    }
    if (major, minor) in special:
        return special[(major, minor)]
    if minor == "0":
        return f"proton_{major}"
    return f"proton_{major}{minor}"


def _parse_compat_tool_vdf(path: Path) -> list[CompatTool]:
    try:
        data = load_vdf(path)
    except Exception:
        return []
    tools = _vdf_get(data, "compatibilitytools", "compat_tools")
    if not isinstance(tools, dict):
        return []
    out: list[CompatTool] = []
    for internal, info in tools.items():
        name = str(internal).strip()
        if not name:
            continue
        display = name
        if isinstance(info, dict) and info.get("display_name"):
            display = str(info["display_name"]).strip() or name
        out.append(CompatTool(name=name, display=display, official=False))
    return out


def list_compat_tools(root: Path | None = None) -> list[CompatTool]:
    root = root or steam_root()
    if root is None:
        return []
    by_name: dict[str, CompatTool] = {}

    seen_bases: set[Path] = set()
    for base in (
        root / "compatibilitytools.d",
        Path.home() / ".steam" / "root" / "compatibilitytools.d",
        Path("/usr/share/steam/compatibilitytools.d"),
    ):
        if not base.is_dir():
            continue
        try:
            resolved = base.resolve()
        except OSError:
            resolved = base
        if resolved in seen_bases:
            continue
        seen_bases.add(resolved)
        candidates = [resolved / "compatibilitytool.vdf"]
        candidates.extend(resolved.glob("*/compatibilitytool.vdf"))
        for manifest in candidates:
            if not manifest.is_file():
                continue
            for tool in _parse_compat_tool_vdf(manifest):
                tool.install_path = manifest.parent
                by_name.setdefault(tool.name, tool)

    for tool in steam_official_protons(root):
        by_name.setdefault(tool.name, tool)

    for library in library_folders(root):
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            continue
        for manifest in steamapps.glob("appmanifest_*.acf"):
            try:
                data = load_vdf(manifest)
            except Exception:
                continue
            state = data.get("AppState", data)
            if not isinstance(state, dict):
                continue
            name = str(state.get("name", "")).strip()
            internal = official_proton_internal(name)
            if not internal:
                continue
            by_name.setdefault(
                internal,
                CompatTool(
                    name=internal,
                    display=name,
                    official=True,
                    rank=_proton_rank(internal, name, alias_index=None, legacy=False),
                ),
            )

    custom = sorted(
        (t for t in by_name.values() if not t.official),
        key=lambda t: t.display.lower(),
        reverse=True,
    )
    official = sorted(
        (t for t in by_name.values() if t.official),
        key=lambda t: t.rank or (5, 0, 0, t.display.lower()),
    )
    return custom + official


def compat_display(internal: str, tools: list[CompatTool] | None = None) -> str:
    if not internal:
        return t("compat_default")
    for tool in tools or []:
        if tool.name == internal:
            return tool.display
    label = _COMPAT_LABELS.get(internal)
    if label:
        return label
    return internal.replace("_", " ")


# --- instalacja Protona (jak ProtonUp-Qt) -----------------------------------

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "User-Agent": f"Perun/{VERSION} (Steam Proton installer)",
    "Accept": "application/vnd.github+json",
}

PROTON_FLAVORS: list[dict[str, str]] = [
    {
        "id": "ge",
        "name": "GE-Proton",
        "blurb": "flavor_ge",
        "api": f"{GITHUB_API}/repos/GloriousEggroll/proton-ge-custom/releases",
    },
    {
        "id": "cachyos",
        "name": "Proton-CachyOS",
        "blurb": "flavor_cachy",
        "api": f"{GITHUB_API}/repos/CachyOS/proton-cachyos/releases",
    },
]


def compatibilitytools_dir(root: Path | None = None) -> Path:
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError(t("err_no_steam"))
    path = root / "compatibilitytools.d"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cpu_flags() -> set[str]:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    for line in text.splitlines():
        if line.startswith("flags") or line.startswith("Features"):
            return set(line.split(":", 1)[-1].split())
    return set()


def preferred_proton_arches() -> list[str]:
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return ["aarch64", "arm64"]
    arches = ["x86_64"]
    flags = _cpu_flags()
    if "avx2" in flags:
        arches.insert(0, "x86_64_v3")
    return arches


def _is_archive_name(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".tar.gz") or lower.endswith(".tar.xz")


def _strip_archive_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in (".tar.gz", ".tar.xz"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


def archive_arch(name: str) -> str | None:
    lower = name.lower()
    if "x86_64_v4" in lower:
        return "x86_64_v4"
    if "x86_64_v3" in lower:
        return "x86_64_v3"
    if "aarch64" in lower:
        return "aarch64"
    if "arm64" in lower:
        return "arm64"
    if "x86_64" in lower:
        return "x86_64"
    return None


def pick_archive_asset(assets: list[dict], preferred: list[str] | None = None) -> dict | None:
    preferred = preferred or preferred_proton_arches()
    archives = [a for a in assets if _is_archive_name(str(a.get("name", "")))]
    for arch in preferred:
        for asset in archives:
            if archive_arch(str(asset["name"])) == arch:
                return asset
    if any(arch.startswith("x86_64") for arch in preferred):
        for asset in archives:
            if archive_arch(str(asset["name"])) is None:
                return asset
    return None


def pick_checksum_asset(assets: list[dict], archive_name: str) -> dict | None:
    stem = _strip_archive_suffix(archive_name)
    wanted = {f"{stem}.sha512sum", f"{archive_name}.sha512sum"}
    for asset in assets:
        if str(asset.get("name", "")) in wanted:
            return asset
    return None


def parse_sha512(text: str) -> str:
    token = (text or "").strip().split()[0] if text else ""
    if len(token) != 128 or any(c not in "0123456789abcdefABCDEF" for c in token):
        raise RuntimeError(t("err_bad_sha_file"))
    return token.lower()


def _http_open(url: str, timeout: float = 30, github_api: bool = False):
    headers = {"User-Agent": GITHUB_HEADERS["User-Agent"]}
    if github_api:
        headers["Accept"] = GITHUB_HEADERS["Accept"]
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def _http_json(url: str) -> object:
    try:
        with _http_open(url, timeout=30, github_api=True) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            raise RuntimeError(t("err_github_rate")) from exc
        raise RuntimeError(t("err_github_http", code=exc.code, url=url)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(t("err_github_connect", reason=exc.reason)) from exc


def _http_text(url: str) -> str:
    with _http_open(url, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _github_error_message(payload: object) -> str | None:
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])
    return None


def fetch_proton_releases(flavor_id: str, count: int = 20) -> list[ProtonRelease]:
    flavor = next((item for item in PROTON_FLAVORS if item["id"] == flavor_id), None)
    if flavor is None:
        raise ValueError(t("err_unknown_flavor", name=flavor_id))
    url = f"{flavor['api']}?per_page={int(count)}"
    payload = _http_json(url)
    if not isinstance(payload, list):
        msg = _github_error_message(payload) or t("err_github_list")
        raise RuntimeError(msg)
    preferred = preferred_proton_arches()
    installed = {tool.name for tool in list_compat_tools()}
    releases: list[ProtonRelease] = []
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        assets = entry.get("assets") or []
        if not isinstance(assets, list):
            continue
        asset = pick_archive_asset(
            [a for a in assets if isinstance(a, dict)], preferred
        )
        if asset is None:
            continue
        archive_name = str(asset.get("name") or "")
        checksum = pick_checksum_asset(
            [a for a in assets if isinstance(a, dict)], archive_name
        )
        folder = _strip_archive_suffix(archive_name)
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        date = str(entry.get("published_at") or "")[:10]
        releases.append(
            ProtonRelease(
                flavor_id=flavor["id"],
                flavor_name=flavor["name"],
                tag=str(entry.get("tag_name") or folder),
                name=folder,
                download_url=str(asset.get("browser_download_url") or ""),
                checksum_url=(
                    str(checksum.get("browser_download_url") or "") if checksum else None
                ),
                size=size,
                date=date,
                installed=folder in installed,
            )
        )
    return releases


def resolve_proton_release(query: str) -> ProtonRelease:
    raw = (query or "").strip()
    if not raw:
        raise ValueError(t("err_proton_query"))
    q = raw.lower()
    aliases = {
        "ge": "ge",
        "ge-proton": "ge",
        "proton-ge": "ge",
        "protonge": "ge",
        "gloriouseggroll": "ge",
        "cachyos": "cachyos",
        "proton-cachyos": "cachyos",
        "cachy": "cachyos",
    }
    if q in aliases:
        releases = fetch_proton_releases(aliases[q])
        if not releases:
            raise FileNotFoundError(t("err_no_releases", name=raw))
        for item in releases:
            if not item.installed:
                return item
        return releases[0]
    hits: list[ProtonRelease] = []
    for flavor in PROTON_FLAVORS:
        for item in fetch_proton_releases(flavor["id"]):
            blob = f"{item.name} {item.tag} {item.flavor_name}".lower()
            if q == item.name.lower() or q == item.tag.lower() or q in blob:
                hits.append(item)
    exact = [item for item in hits if item.name.lower() == q or item.tag.lower() == q]
    if len(exact) == 1:
        return exact[0]
    unique = {item.name: item for item in hits}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if not hits:
        raise FileNotFoundError(t("err_proton_missing", name=raw))
    names = ", ".join(item.name for item in unique.values())
    raise ValueError(t("err_proton_ambiguous", names=names))


def _sha512_file(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def download_url(
    url: str,
    dest: Path,
    progress=None,
    cancel=None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with _http_open(url, timeout=60) as resp:
            total = 0
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            got = 0
            with tmp.open("wb") as handle:
                while True:
                    if cancel is not None and cancel[0]:
                        raise InterruptedError(t("err_download_cancelled"))
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    got += len(chunk)
                    if progress is not None and total:
                        progress(min(got / total, 1.0))
        tmp.replace(dest)
        if progress is not None:
            progress(1.0)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _safe_extract_tar(archive: Path, dest: Path) -> str:
    dest = dest.resolve()
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        if not names:
            raise RuntimeError(t("err_empty_archive"))
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if target != dest and dest not in target.parents:
                raise RuntimeError(t("err_bad_archive_path", name=member.name))
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)
    top = names[0].split("/")[0]
    if not top or top in {".", ".."}:
        raise RuntimeError(t("err_bad_archive_root"))
    return top


def install_proton_release(
    release: ProtonRelease,
    progress=None,
    cancel=None,
    root: Path | None = None,
) -> Path:
    if not release.download_url:
        raise RuntimeError(t("err_no_download", name=release.name))
    dest_dir = compatibilitytools_dir(root)
    target = dest_dir / release.name
    if target.exists():
        raise FileExistsError(t("err_already_installed", name=release.name))
    cache = Path.home() / ".cache" / "perun"
    cache.mkdir(parents=True, exist_ok=True)
    filename = Path(urllib.parse.urlparse(release.download_url).path).name
    archive = cache / filename

    def report(fraction: float, phase: str = "download") -> None:
        if progress is None:
            return
        if phase == "download":
            progress(fraction * 0.92, "download")
        elif phase == "extract":
            progress(0.92 + fraction * 0.08, "extract")
        else:
            progress(fraction, phase)

    try:
        report(0.0)
        download_url(
            release.download_url,
            archive,
            progress=lambda frac: report(frac, "download"),
            cancel=cancel,
        )
        if release.checksum_url:
            expected = parse_sha512(_http_text(release.checksum_url))
            actual = _sha512_file(archive)
            if actual != expected:
                raise RuntimeError(t("err_sha_mismatch", name=release.name))
        if cancel is not None and cancel[0]:
            raise InterruptedError(t("err_download_cancelled"))
        report(0.0, "extract")
        top = _safe_extract_tar(archive, dest_dir)
        extracted = dest_dir / top
        if not extracted.is_dir():
            raise RuntimeError(t("err_extract_dir"))
        report(1.0, "extract")
        return extracted
    finally:
        try:
            archive.unlink(missing_ok=True)
        except OSError:
            pass


def tool_is_removable(tool: CompatTool, root: Path | None = None) -> bool:
    if tool.official or tool.install_path is None:
        return False
    try:
        base = compatibilitytools_dir(root).resolve()
        path = tool.install_path.resolve()
    except (OSError, FileNotFoundError):
        return False
    return path != base and base in path.parents and path.is_dir()


def uninstall_compat_tool(tool: CompatTool, root: Path | None = None) -> None:
    if not tool_is_removable(tool, root):
        raise ValueError(t("err_cannot_remove", name=tool.display))
    assert tool.install_path is not None
    shutil.rmtree(tool.install_path)


def games_using_tool(name: str, games: list[Game] | None = None) -> list[Game]:
    games = games if games is not None else list_games(include_uninstalled=True)
    return [game for game in games if game.compat_tool == name]


def format_bytes(size: int) -> str:
    if size <= 0:
        return "?"
    mib = size / (1024 * 1024)
    if mib >= 100:
        return f"{mib:.0f} MB"
    return f"{mib:.1f} MB"


def _list_shortcuts(root: Path, compat: dict[str, str], account: str | None) -> list[Game]:
    path = shortcuts_path(root)
    if path is None or not path.is_file() or vdf is None:
        return []
    try:
        data = vdf.binary_loads(path.read_bytes())
    except Exception:
        return []
    shortcuts = data.get("shortcuts", data)
    if not isinstance(shortcuts, dict):
        return []
    games: list[Game] = []
    for index, entry in shortcuts.items():
        if not isinstance(entry, dict):
            continue
        try:
            hidden = int(entry.get("IsHidden", 0) or 0)
        except (TypeError, ValueError):
            hidden = 0
        if hidden:
            continue
        name = str(entry.get("AppName") or entry.get("appname") or "").strip()
        if not name:
            continue
        appid = _unsigned_appid(entry.get("appid", 0))
        try:
            last = int(entry.get("LastPlayTime", 0) or 0)
        except (TypeError, ValueError):
            last = 0
        exe = str(entry.get("Exe") or entry.get("exe") or "").strip().strip('"')
        install = Path(exe).parent if exe else None
        if install and not install.is_dir():
            install = None
        icon = None
        icon_field = str(entry.get("icon") or "").strip()
        if icon_field:
            icon_path = Path(icon_field)
            if icon_path.is_file():
                icon = icon_path
        if icon is None:
            icon = _find_icon(root, appid, account)
        games.append(
            Game(
                appid=appid,
                name=name,
                installdir=install,
                launch_options=str(entry.get("LaunchOptions", "") or ""),
                last_played=last,
                compat_tool=compat.get(appid, ""),
                icon=icon,
                is_shortcut=True,
                shortcut_index=str(index),
                launch_id=shortcut_launch_id(appid),
                installed=install is not None,
            )
        )
    return games


def _account_games(
    root: Path,
    apps_cfg: dict[str, dict],
    compat: dict[str, str],
    account: str | None,
    seen: set[str],
    include_tools: bool,
) -> list[Game]:
    names = appinfo_index(root)
    appids: set[str] = set()
    cache = root / "appcache" / "librarycache"
    if cache.is_dir():
        for child in cache.iterdir():
            if child.is_dir() and child.name.isdigit():
                appids.add(child.name)
    appids.update(appid for appid in apps_cfg if str(appid).isdigit())
    appids.update(appid for appid in compat if str(appid).isdigit())
    games: list[Game] = []
    for appid in appids:
        if not appid or appid in seen:
            continue
        info = names.get(appid)
        cfg = apps_cfg.get(appid, {})
        options = str(cfg.get("LaunchOptions", "") or "")
        tool = compat.get(appid, "")
        if info is None:
            name, kind = "", ""
        else:
            name, kind = info
        playable = kind.casefold() in {"game", "application"}
        configured = bool(options.strip() or tool)
        if not playable and not configured:
            continue
        if not name:
            if not configured:
                continue
            name = appid
        if not include_tools and _is_tool(appid, name):
            continue
        try:
            last = int(cfg.get("LastPlayed", 0) or 0)
        except (TypeError, ValueError):
            last = 0
        games.append(
            Game(
                appid=appid,
                name=name,
                installdir=None,
                launch_options=options,
                last_played=last,
                compat_tool=tool,
                icon=_find_icon(root, appid, account),
                launch_id=appid,
                installed=False,
            )
        )
    return games


def list_games(
    root: Path | None = None,
    include_tools: bool = False,
    include_uninstalled: bool = False,
) -> list[Game]:
    root = root or steam_root()
    if root is None:
        return []
    apps_cfg = _apps_launch_map(root)
    compat = _compat_map(root)
    account = login_account_id(root)
    games: list[Game] = []
    seen: set[str] = set()
    for library in library_folders(root):
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            continue
        for manifest in steamapps.glob("appmanifest_*.acf"):
            try:
                data = load_vdf(manifest)
            except Exception:
                continue
            state = data.get("AppState", data)
            if not isinstance(state, dict):
                continue
            appid = str(state.get("appid", "")).strip()
            name = str(state.get("name", "")).strip() or appid
            if not appid or appid in seen:
                continue
            seen.add(appid)
            if not include_tools and _is_tool(appid, name):
                continue
            install = None
            installdir = state.get("installdir")
            if installdir:
                candidate = steamapps / "common" / str(installdir)
                if candidate.exists():
                    install = candidate
            cfg = apps_cfg.get(appid, {})
            try:
                last = int(cfg.get("LastPlayed", 0) or 0)
            except (TypeError, ValueError):
                last = 0
            games.append(
                Game(
                    appid=appid,
                    name=name,
                    installdir=install,
                    launch_options=str(cfg.get("LaunchOptions", "") or ""),
                    last_played=last,
                    compat_tool=compat.get(appid, ""),
                    icon=_find_icon(root, appid, account),
                    launch_id=appid,
                    installed=True,
                )
            )
    for shortcut in _list_shortcuts(root, compat, account):
        if shortcut.appid in seen:
            continue
        seen.add(shortcut.appid)
        games.append(shortcut)
    if include_uninstalled:
        for game in _account_games(root, apps_cfg, compat, account, seen, include_tools):
            seen.add(game.appid)
            games.append(game)
    games.sort(key=lambda g: (-int(g.installed), -g.last_played, g.name.lower()))
    return games


def resolve_game(query: str, games: list[Game] | None = None) -> list[Game]:
    games = games if games is not None else list_games(include_uninstalled=True)
    q = query.strip().lower()
    if not q:
        return []
    raw = query.strip()
    exact_id = [g for g in games if g.appid == raw or g.launch_id == raw]
    if exact_id:
        return exact_id
    exact_name = [g for g in games if g.name.lower() == q]
    if exact_name:
        return exact_name
    compact_q = re.sub(r"[^a-z0-9]+", "", q)
    hits = []
    for game in games:
        blob = _search_text(game)
        if q in blob or (compact_q and compact_q in blob):
            hits.append(game)
    return hits


# --- parser opcji -----------------------------------------------------------

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_mangohud_config(value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, _, val = part.partition("=")
            key = key.strip()
            if key:
                out[key] = val.strip()
        else:
            out[part] = "1"
    return out


def format_mangohud_config(cfg: dict[str, str]) -> str:
    if not cfg:
        return ""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        if key in seen or key not in cfg:
            return
        seen.add(key)
        val = cfg[key]
        if val in {"1", "true", "True"}:
            ordered.append(key)
        elif val != "":
            ordered.append(f"{key}={val}")

    for key in MANGO_BASELINE:
        add(key)
    for key, _, _ in MANGO_FLAG_OPTIONS:
        add(key)
    for key, val in cfg.items():
        if key not in seen and val in {"1", "true", "True"}:
            add(key)
    for key in ("position", "fps_limit", "font_size"):
        add(key)
    for key in cfg:
        add(key)
    return ",".join(ordered)


def mango_config_from_ui(
    flags: dict[str, bool],
    position: str,
    fps_limit: str,
    font_size: str,
    previous: dict[str, str],
) -> dict[str, str]:
    extras_on = [key for key, on in flags.items() if on]
    valued = {
        key: val
        for key, val in (
            ("position", position),
            ("fps_limit", fps_limit),
            ("font_size", font_size),
        )
        if val
    }
    unknown = {
        key: val
        for key, val in previous.items()
        if key not in MANGO_KNOWN_KEYS
    }
    if not extras_on and not valued and not unknown:
        return {}
    out: dict[str, str] = {}
    for key in MANGO_BASELINE:
        out[key] = previous.get(key, "1")
    for key, on in flags.items():
        if on:
            out[key] = "1"
    out.update(unknown)
    out.update(valued)
    return out


@dataclass
class ParsedLaunch:
    env: list[tuple[str, str]] = field(default_factory=list)
    gamemode: bool = False
    mangohud: bool = False
    mangohud_dlsym: bool = False
    mangohud_config: dict[str, str] = field(default_factory=dict)
    extra_before: list[str] = field(default_factory=list)
    args: str = ""

    def to_string(self) -> str:
        parts: list[str] = []
        for key, value in self.env:
            if key in {"MANGOHUD", "MANGOHUD_CONFIG", "MANGOHUD_DLSYM"}:
                continue
            parts.append(f"{key}={value}")
        if self.mangohud:
            cfg = format_mangohud_config(self.mangohud_config)
            if cfg:
                parts.append(f"MANGOHUD_CONFIG={cfg}")
        if self.gamemode:
            parts.append("gamemoderun")
        extra = [tok for tok in self.extra_before if tok != "--dlsym"]
        parts.extend(extra)
        if self.mangohud:
            parts.append("mangohud")
            if self.mangohud_dlsym:
                parts.append("--dlsym")
        needs_command = bool(parts)
        if needs_command:
            parts.append("%command%")
        if self.args.strip():
            parts.append(self.args.strip())
        return " ".join(parts).strip()


def parse_launch(text: str) -> ParsedLaunch:
    text = (text or "").strip()
    if not text:
        return ParsedLaunch()
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = text.split()

    env: list[tuple[str, str]] = []
    gamemode = False
    mangohud = False
    mangohud_dlsym = False
    mangohud_config: dict[str, str] = {}
    extra_before: list[str] = []
    args_tokens: list[str] = []
    seen_command = "%command%" in tokens
    after_command = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "%command%":
            after_command = True
            i += 1
            continue
        if after_command:
            args_tokens.append(token)
            i += 1
            continue
        if _ENV_RE.match(token):
            key, _, value = token.partition("=")
            if key == "MANGOHUD" and value in {"1", "true", "True"}:
                mangohud = True
            elif key == "MANGOHUD_DLSYM" and value in {"1", "true", "True"}:
                mangohud_dlsym = True
                mangohud = True
            elif key == "MANGOHUD_CONFIG":
                mangohud_config = parse_mangohud_config(value)
                mangohud = True
            else:
                env.append((key, value))
            i += 1
            continue
        if token == "gamemoderun":
            gamemode = True
            i += 1
            continue
        if token == "mangohud":
            mangohud = True
            if i + 1 < len(tokens) and tokens[i + 1] == "--dlsym":
                mangohud_dlsym = True
                i += 1
            i += 1
            continue
        if token == "--dlsym":
            mangohud_dlsym = True
            mangohud = True
            i += 1
            continue
        if seen_command:
            extra_before.append(token)
        else:
            args_tokens.append(token)
        i += 1

    if not seen_command:
        if gamemode or mangohud or env or extra_before:
            pass
        else:
            extra_before = []
    return ParsedLaunch(
        env=env,
        gamemode=gamemode,
        mangohud=mangohud,
        mangohud_dlsym=mangohud_dlsym,
        mangohud_config=mangohud_config,
        extra_before=extra_before,
        args=_join_args(args_tokens),
    )


def _join_args(tokens: list[str]) -> str:
    if not tokens:
        return ""
    out: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[A-Za-z0-9_./:=+%:,-]+", token):
            out.append(token)
        else:
            out.append(shlex.quote(token))
    return " ".join(out)


def toggle_token(command: str, token: str, enabled: bool) -> str:
    parsed = parse_launch(command)
    if token == "gamemoderun":
        parsed.gamemode = enabled
    elif token == "mangohud":
        parsed.mangohud = enabled
        parsed.env = [
            (k, v)
            for k, v in parsed.env
            if k not in {"MANGOHUD", "MANGOHUD_DLSYM"}
        ]
        if not enabled:
            parsed.mangohud_config = {}
            parsed.mangohud_dlsym = False
    else:
        existing = command.strip()
        if enabled:
            if token not in existing.split():
                parsed = parse_launch((existing + " " + token).strip())
        else:
            # usuń dokładny preset z env albo z args
            if "=" in token and not token.startswith("-"):
                key, _, value = token.partition("=")
                parsed.env = [(k, v) for k, v in parsed.env if not (k == key and v == value)]
            else:
                try:
                    args = shlex.split(parsed.args, posix=True)
                except ValueError:
                    args = parsed.args.split()
                preset_tokens = token.split()
                args = _remove_subseq(args, preset_tokens)
                parsed.args = _join_args(args)
    return parsed.to_string()


def _remove_subseq(hay: list[str], needle: list[str]) -> list[str]:
    if not needle:
        return hay
    i = 0
    out: list[str] = []
    skipped = False
    while i < len(hay):
        if not skipped and hay[i : i + len(needle)] == needle:
            i += len(needle)
            skipped = True
            continue
        out.append(hay[i])
        i += 1
    return out


def insert_preset(command: str, preset: str) -> str:
    command = (command or "").strip()
    parsed = parse_launch(command)
    if _ENV_RE.match(preset.split()[0]) and " " not in preset.strip():
        key, _, value = preset.partition("=")
        parsed.env = [(k, v) for k, v in parsed.env if k != key]
        parsed.env.append((key, value))
        return parsed.to_string()
    if preset in {"gamemoderun", "mangohud"}:
        return toggle_token(command, preset, True)
    current_args = parsed.args
    if preset in current_args:
        return parsed.to_string()
    parsed.args = (current_args + " " + preset).strip()
    return parsed.to_string()


# --- zapis ------------------------------------------------------------------

def _host_cmd(argv: list[str]) -> list[str]:
    if os.environ.get("FLATPAK_ID"):
        return ["flatpak-spawn", "--host", *argv]
    return argv


def steam_argv(*args: str) -> list[str]:
    return _host_cmd(["steam", *args])


def is_steam_running() -> bool:
    pid_file = Path.home() / ".steam" / "steam.pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return True
        except (ValueError, OSError, ProcessLookupError):
            pass
    try:
        result = subprocess.run(
            _host_cmd(["pgrep", "-f", r"/[Ss]team/.*/steam$"]),
            capture_output=True,
            text=True,
            check=False,
        )
        pids = [p for p in result.stdout.split() if p.isdigit()]
        return bool(pids)
    except FileNotFoundError:
        return False


def shutdown_steam(timeout: float = 25.0) -> None:
    subprocess.run(steam_argv("-shutdown"), capture_output=True, check=False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_steam_running():
            time.sleep(0.5)
            return
        time.sleep(0.2)
    raise TimeoutError(t("err_steam_timeout"))


def start_steam() -> None:
    try:
        _apply_saved_persona_state()
    except Exception as exc:
        print(t("cli_persona_fail", error=exc), file=sys.stderr)
    subprocess.Popen(
        steam_argv(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _backup_file(path: Path, prefix: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{prefix}-{stamp}{path.suffix}"
    shutil.copy2(path, dest)
    backups = sorted(BACKUP_DIR.glob(f"{prefix}-*{path.suffix}"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, path.stat().st_mode)
    tmp.replace(path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, path.stat().st_mode)
    tmp.replace(path)


def _mutate_localconfig_launches(data: dict, updates: list[tuple[str, str]]) -> None:
    apps = _vdf_ensure(
        data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps"
    )
    for appid, options in updates:
        app = apps.get(appid)
        if not isinstance(app, dict):
            app = {}
            apps[appid] = app
        text = (options or "").strip()
        if text:
            app["LaunchOptions"] = text
        else:
            app.pop("LaunchOptions", None)


def _mutate_shortcut_launches(data: dict, updates: list[tuple[str, str]]) -> None:
    shortcuts = data.get("shortcuts")
    if not isinstance(shortcuts, dict):
        raise FileNotFoundError(t("err_no_shortcuts"))
    for index, options in updates:
        entry = shortcuts.get(index)
        if not isinstance(entry, dict):
            raise FileNotFoundError(t("err_no_shortcut_index", index=index))
        entry["LaunchOptions"] = (options or "").strip()


def _mutate_compat_tools(data: dict, updates: list[tuple[str, str]]) -> None:
    mapping = _vdf_ensure(
        data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping"
    )
    for appid, tool_name in updates:
        tool_name = (tool_name or "").strip()
        if not tool_name:
            _vdf_pop_ci(mapping, appid)
            continue
        entry = None
        entry_key = appid
        for key in mapping:
            if str(key) == appid:
                entry = mapping[key]
                entry_key = key
                break
        if not isinstance(entry, dict):
            entry = {}
            mapping[entry_key] = entry
        _vdf_set_ci(entry, "name", tool_name)
        if not any(str(key).lower() == "config" for key in entry):
            entry["config"] = ""
        if not any(str(key).lower() == "priority" for key in entry):
            entry["priority"] = "250"


def _write_localconfig_launches(root: Path, updates: list[tuple[str, str]]) -> Path:
    if not updates:
        path = localconfig_path(root)
        if path is None:
            raise FileNotFoundError(t("err_no_localconfig"))
        return path
    path = localconfig_path(root)
    if path is None or not path.is_file():
        raise FileNotFoundError(t("err_no_localconfig"))
    _backup_file(path, "localconfig")
    data = load_vdf(path)
    _mutate_localconfig_launches(data, updates)
    _atomic_write_text(path, _dump_vdf(data))
    return path


def _write_localconfig_launch_options(root: Path, appid: str, options: str) -> Path:
    return _write_localconfig_launches(root, [(appid, options)])


def _write_shortcut_launches(root: Path, updates: list[tuple[str, str]]) -> Path:
    if not updates:
        path = shortcuts_path(root)
        if path is None:
            raise FileNotFoundError(t("err_no_shortcuts"))
        return path
    path = shortcuts_path(root)
    if path is None or not path.is_file():
        raise FileNotFoundError(t("err_no_shortcuts"))
    if vdf is None:
        raise RuntimeError(t("err_no_vdf_short"))
    _backup_file(path, "shortcuts")
    data = vdf.binary_loads(path.read_bytes())
    _mutate_shortcut_launches(data, updates)
    _atomic_write_bytes(path, vdf.binary_dumps(data))
    return path


def _write_shortcut_launch_options(root: Path, index: str, options: str) -> Path:
    return _write_shortcut_launches(root, [(index, options)])


def _vdf_set_ci(node: dict, key: str, value) -> None:
    for ck in node:
        if str(ck).lower() == key.lower():
            node[ck] = value
            return
    node[key] = value


def _vdf_pop_ci(node: dict, key: str) -> None:
    for ck in list(node):
        if str(ck).lower() == key.lower():
            node.pop(ck, None)


def _write_compat_tools(root: Path, updates: list[tuple[str, str]]) -> Path:
    path = config_vdf_path(root)
    if not updates:
        return path
    if not path.is_file():
        raise FileNotFoundError(t("err_no_config"))
    _backup_file(path, "config")
    data = load_vdf(path)
    _mutate_compat_tools(data, updates)
    _atomic_write_text(path, _dump_vdf(data))
    return path


def _write_compat_tool(root: Path, appid: str, tool_name: str) -> Path:
    return _write_compat_tools(root, [(appid, tool_name)])


def save_game(
    game: Game,
    *,
    launch_options: object = UNCHANGED,
    compat_tool: object = UNCHANGED,
    root: Path | None = None,
    close_steam: bool = False,
    restart_steam: bool = False,
) -> None:
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError(t("err_no_steam"))
    was_running = is_steam_running()
    if was_running and close_steam:
        shutdown_steam()
    elif was_running and not close_steam:
        raise RuntimeError(t("err_steam_running"))

    if launch_options is not UNCHANGED:
        options = str(launch_options or "").strip()
        if game.is_shortcut:
            if not game.shortcut_index:
                raise FileNotFoundError(t("err_shortcut_no_index"))
            _write_shortcut_launch_options(root, game.shortcut_index, options)
        else:
            _write_localconfig_launch_options(root, game.appid, options)

    if compat_tool is not UNCHANGED:
        tool_name = str(compat_tool or "").strip()
        current = (game.compat_tool or "").strip()
        if tool_name != current:
            _write_compat_tool(root, game.appid, tool_name)

    if was_running and close_steam and restart_steam:
        start_steam()


def set_launch_options(
    appid: str,
    options: str,
    root: Path | None = None,
    close_steam: bool = False,
    restart_steam: bool = False,
) -> Path:
    matches = resolve_game(appid)
    if len(matches) != 1:
        game = Game(appid=appid, name=appid, installdir=None, launch_id=appid)
    else:
        game = matches[0]
    save_game(
        game,
        launch_options=options,
        root=root,
        close_steam=close_steam,
        restart_steam=restart_steam,
    )
    path = shortcuts_path(root or steam_root() or Path()) if game.is_shortcut else localconfig_path(root or steam_root() or Path())
    if path is None:
        raise FileNotFoundError(t("err_no_config_file"))
    return path


# --- biblioteka Steam i przenoszenie ustawień -------------------------------

@dataclass
class SteamLibrarySettings:
    start_in_library: bool
    installed_only: bool


@dataclass
class ImportPlan:
    steam: list[tuple[str, str, str]] = field(default_factory=list)
    shortcuts: list[tuple[Game, str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _steam_closed_for_write(*, close_steam: bool) -> bool:
    """Zamyka Steam, gdy trzeba. Zwraca, czy był uruchomiony."""
    was_running = is_steam_running()
    if was_running and close_steam:
        shutdown_steam()
    elif was_running and not close_steam:
        raise RuntimeError(t("err_steam_running"))
    return was_running


def _web_storage(data: dict) -> dict:
    store = _vdf_ensure(data, "UserLocalConfigStore")
    for key in store:
        if str(key).lower() == "webstorage" and isinstance(store[key], dict):
            return store[key]
    store["WebStorage"] = {}
    return store["WebStorage"]


def _friend_prefs(web: dict, account: str) -> tuple[str, dict]:
    wanted = f"friendstorelocalprefs_{account}".lower()
    key = f"FriendStoreLocalPrefs_{account}"
    raw = None
    for existing in web:
        if str(existing).lower() == wanted:
            key = str(existing)
            raw = web[existing]
            break
    if raw is None:
        return key, {}
    if not isinstance(raw, str) or not raw.strip():
        return key, {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(t("err_read_persona")) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(t("err_read_persona"))
    return key, parsed


def persona_state_from_localconfig(data: dict, account: str) -> int | None:
    web = _vdf_get(data, "UserLocalConfigStore", "WebStorage")
    if not isinstance(web, dict):
        return None
    _key, prefs = _friend_prefs(web, account)
    if "ePersonaState" not in prefs:
        return None
    try:
        return int(prefs["ePersonaState"])
    except (TypeError, ValueError):
        return None


def mutate_persona_state(data: dict, account: str, state: int) -> None:
    if state not in {value for value, _key, _label in PERSONA_STATES}:
        raise ValueError(t("err_unknown_status", name=state))
    web = _web_storage(data)
    key, prefs = _friend_prefs(web, account)
    prefs["ePersonaState"] = int(state)
    web[key] = json.dumps(prefs, ensure_ascii=False, separators=(",", ":"))


def read_persona_state(root: Path | None = None) -> int | None:
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError(t("err_no_steam"))
    path = localconfig_path(root)
    if path is None or not path.is_file():
        return None
    account = login_account_id(root) or path.parent.parent.name
    return persona_state_from_localconfig(load_vdf(path), account)


def _write_persona_state(root: Path, state: int) -> None:
    path = localconfig_path(root)
    if path is None or not path.is_file():
        raise FileNotFoundError(t("err_no_localconfig"))
    account = login_account_id(root) or path.parent.parent.name
    _backup_file(path, "localconfig")
    data = load_vdf(path)
    mutate_persona_state(data, account, state)
    _atomic_write_text(path, _dump_vdf(data))


def _apply_saved_persona_state() -> None:
    """Wpisuje zapisany status, gdy Steam jest wyłączony i wartość się różni."""
    state = load_persona_preference()
    if state is None or is_steam_running():
        return
    root = steam_root()
    if root is None:
        return
    if read_persona_state(root) == state:
        return
    _write_persona_state(root, state)


def read_steam_library_settings(root: Path | None = None) -> SteamLibrarySettings:
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError(t("err_no_steam"))
    library = False
    path = sharedconfig_path(root)
    if path is not None and path.is_file():
        dialog = _vdf_get(
            load_vdf(path),
            "UserRoamingConfigStore",
            "Software",
            "Valve",
            "Steam",
            "SteamDefaultDialog",
        )
        library = str(dialog or "") == STEAM_LIBRARY_DIALOG
    installed = False
    local = localconfig_path(root)
    if local is not None and local.is_file():
        _web, _key, state = _ui_state_from_localconfig(load_vdf(local))
        installed = filter_shows_installed_only(state)
    return SteamLibrarySettings(library, installed)


def _write_library_start(root: Path, library: bool) -> None:
    path = sharedconfig_path(root)
    if path is None:
        raise FileNotFoundError(t("err_no_account"))
    if path.is_file():
        _backup_file(path, "sharedconfig")
        data = load_vdf(path)
    else:
        if not library:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
    mutate_steam_default_dialog(data, library)
    text = _dump_vdf(data)
    if path.is_file():
        _atomic_write_text(path, text)
    else:
        path.write_text(text, encoding="utf-8")


def _write_installed_only(root: Path, enabled: bool) -> None:
    path = localconfig_path(root)
    if path is None or not path.is_file():
        raise FileNotFoundError(t("err_no_localconfig"))
    _backup_file(path, "localconfig")
    data = load_vdf(path)
    web, state_key, state = _ui_state_from_localconfig(data)
    updated = set_installed_only_filter(state, enabled)
    web[state_key] = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
    _atomic_write_text(path, _dump_vdf(data))


def apply_steam_library_settings(
    settings: SteamLibrarySettings,
    *,
    root: Path | None = None,
    close_steam: bool = False,
    restart_steam: bool = False,
    persona: int | None = None,
) -> None:
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError(t("err_no_steam"))
    current = read_steam_library_settings(root)
    dialog_changes = current.start_in_library != settings.start_in_library
    filter_changes = current.installed_only != settings.installed_only
    persona_changes = False
    if persona is not None:
        if persona not in {value for value, _key, _label in PERSONA_STATES}:
            raise ValueError(t("err_unknown_status", name=persona))
        persona_changes = read_persona_state(root) != persona
    if not dialog_changes and not filter_changes and not persona_changes:
        if persona is not None:
            save_persona_preference(persona)
        return
    was_running = _steam_closed_for_write(close_steam=close_steam)
    try:
        if dialog_changes:
            _write_library_start(root, settings.start_in_library)
        if filter_changes:
            _write_installed_only(root, settings.installed_only)
        if persona_changes:
            _write_persona_state(root, persona)  # type: ignore[arg-type]
        if persona is not None:
            save_persona_preference(persona)
    finally:
        if was_running and close_steam and restart_steam:
            start_steam()


def _game_is_customized(game: Game) -> bool:
    return bool((game.launch_options or "").strip() or (game.compat_tool or "").strip())


def export_filename(game: Game | None = None) -> str:
    if game is None:
        return t("export_name_all")
    raw = re.sub(r"[^\w.-]+", "-", game.name, flags=re.UNICODE).strip("-._")
    slug = raw[:60] or str(game.appid)
    return f"perun-{slug}.json"


def export_games_payload(games: list[Game], *, only_custom: bool = True) -> dict:
    rows = []
    for game in games:
        if only_custom and not _game_is_customized(game):
            continue
        rows.append(
            {
                "appid": game.appid,
                "name": game.name,
                "launch_options": game.launch_options or "",
                "compat_tool": game.compat_tool or "",
                "shortcut": bool(game.is_shortcut),
            }
        )
    rows.sort(key=lambda row: (bool(row["shortcut"]), row["name"].casefold(), row["appid"]))
    return {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "games": rows}


def export_games(path: Path, root: Path | None = None, *, only: Game | None = None) -> int:
    if only is not None:
        payload = export_games_payload([only], only_custom=False)
    else:
        payload = export_games_payload(list_games(root, include_uninstalled=True))
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(payload["games"])


def load_games_file(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(t("err_bad_export", error=exc)) from exc
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise ValueError(t("err_not_perun_file"))
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != EXPORT_VERSION:
        raise ValueError(t("err_bad_version"))
    games = data.get("games")
    if not isinstance(games, list):
        raise ValueError(t("err_no_game_list"))
    return games


def plan_import(rows: list, games: list[Game]) -> ImportPlan:
    shortcuts: dict[str, list[Game]] = {}
    for game in games:
        if game.is_shortcut:
            shortcuts.setdefault(game.name.casefold(), []).append(game)
    plan = ImportPlan()
    for row in rows:
        if not isinstance(row, dict):
            plan.skipped.append(t("skip_broken"))
            continue
        appid = str(row.get("appid", "")).strip()
        name = str(row.get("name", "")).strip()
        options = str(row.get("launch_options", "") or "")
        tool = str(row.get("compat_tool", "") or "")
        if bool(row.get("shortcut")):
            hits = shortcuts.get(name.casefold(), [])
            label = name or appid or t("skip_shortcut_word")
            if len(hits) != 1 or not hits[0].shortcut_index:
                reason = t("skip_ambiguous") if len(hits) > 1 else t("skip_missing")
                plan.skipped.append(t("skip_shortcut", reason=reason, label=label))
                continue
            plan.shortcuts.append((hits[0], options, tool))
            continue
        if not appid.isdigit():
            plan.skipped.append(t("skip_game", name=name or appid or "?"))
            continue
        plan.steam.append((appid, options, tool))
    return plan


def import_games(
    path: Path,
    *,
    root: Path | None = None,
    close_steam: bool = False,
    restart_steam: bool = False,
) -> tuple[int, list[str]]:
    rows = load_games_file(path)
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError(t("err_no_steam"))
    plan = plan_import(rows, list_games(root, include_uninstalled=True))
    count = len(plan.steam) + len(plan.shortcuts)
    if count == 0:
        return 0, plan.skipped
    was_running = _steam_closed_for_write(close_steam=close_steam)
    try:
        if plan.steam:
            _write_localconfig_launches(
                root, [(appid, options) for appid, options, _tool in plan.steam]
            )
        if plan.shortcuts:
            _write_shortcut_launches(
                root,
                [
                    (game.shortcut_index or "", options)
                    for game, options, _tool in plan.shortcuts
                ],
            )
        compat = [(appid, tool) for appid, _options, tool in plan.steam]
        compat.extend((game.appid, tool) for game, _options, tool in plan.shortcuts)
        if compat:
            _write_compat_tools(root, compat)
    finally:
        if was_running and close_steam and restart_steam:
            start_steam()
    return count, plan.skipped


# --- CLI --------------------------------------------------------------------

def _print_games(games: list[Game]) -> None:
    if not games:
        print(t("cli_no_games"))
        return
    width = max(len(g.name) for g in games)
    for game in games:
        opts = game.launch_options or "—"
        if game.is_shortcut:
            kind = t("kind_shortcut")
        elif not game.installed:
            kind = t("kind_uninstalled")
        else:
            kind = t("kind_steam")
        proton = game.compat_tool or t("cli_proton_mark")
        print(f"{game.appid:>10}  {game.name:<{width}}  [{kind}]  {proton}  {opts}")


def _pick_one(query: str) -> Game:
    matches = resolve_game(query)
    if not matches:
        raise SystemExit(t("cli_not_found_game", query=query))
    if len(matches) > 1:
        print(t("cli_several"))
        _print_games(matches)
        raise SystemExit(2)
    return matches[0]


def cmd_list(args: argparse.Namespace) -> int:
    if steam_root() is None:
        print(t("cli_no_steam"), file=sys.stderr)
        return 1
    _print_games(list_games(include_uninstalled=bool(getattr(args, "all", False))))
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    game = _pick_one(args.game)
    if game.is_shortcut:
        kind = t("kind_shortcut")
    elif not game.installed:
        kind = t("kind_steam_uninstalled")
    else:
        kind = t("kind_steam")
    print(f"{game.name} ({game.appid}, {kind})")
    print(f"Proton: {game.compat_tool or t('compat_default')}")
    print(game.launch_options or t("cli_no_options"))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    game = _pick_one(args.game)
    options = args.options if args.options is not None else ""
    try:
        save_game(
            game,
            launch_options=options,
            close_steam=not args.keep_steam,
            restart_steam=not args.keep_steam,
        )
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    print(t("cli_saved", name=game.name, options=options or t("cli_cleared")))
    return 0


def cmd_tools(_: argparse.Namespace) -> int:
    tools = list_compat_tools()
    default = default_compat_tool()
    print(f"{t('cli_default_tool')}  {default or t('cli_no_global')}")
    if not tools:
        print(t("cli_no_proton_installed"))
        return 0
    width = max(len(tool.name) for tool in tools)
    for tool in tools:
        kind = t("cli_kind_official") if tool.official else t("cli_kind_custom")
        extra = f"  ({tool.display})" if tool.display != tool.name else ""
        print(f"{tool.name:<{width}}  [{kind}]{extra}")
    return 0


def cmd_proton(args: argparse.Namespace) -> int:
    game = _pick_one(args.game)
    if args.tool is None:
        print(f"{game.name} ({game.appid})")
        print(game.compat_tool or t("compat_default"))
        return 0
    raw = args.tool.strip()
    if raw.lower() in {"default", "domyślny", "domyslny", "-"}:
        tool_name = ""
        label = t("compat_default")
    else:
        tools = list_compat_tools()
        matches = [
            tool
            for tool in tools
            if tool.name.lower() == raw.lower() or tool.display.lower() == raw.lower()
        ]
        if not matches:
            matches = [
                tool
                for tool in tools
                if raw.lower() in tool.name.lower() or raw.lower() in tool.display.lower()
            ]
        if len(matches) != 1:
            if not matches:
                print(t("cli_proton_missing", name=raw), file=sys.stderr)
            else:
                print(t("cli_proton_several"), file=sys.stderr)
                for tool in matches:
                    print(f"  {tool.name}  ({tool.display})", file=sys.stderr)
            return 1
        tool_name = matches[0].name
        label = matches[0].display
    try:
        save_game(
            game,
            compat_tool=tool_name,
            close_steam=not args.keep_steam,
            restart_steam=not args.keep_steam,
        )
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    print(t("cli_saved_proton", name=game.name, label=label))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    query = (args.version or "").strip()
    if not query:
        try:
            for flavor in PROTON_FLAVORS:
                print(f"# {flavor['name']} — {t(flavor['blurb'])}")
                releases = fetch_proton_releases(flavor["id"])
                if not releases:
                    print(t("cli_no_releases_short"))
                    continue
                for item in releases:
                    mark = t("cli_installed_mark") if item.installed else ""
                    print(
                        f"  {item.name:<42}  {item.date}  {format_bytes(item.size)}{mark}"
                    )
        except Exception as exc:
            print(t("cli_error", error=exc), file=sys.stderr)
            return 1
        print()
        print(t("cli_install_hint_1"))
        print(t("cli_install_hint_2"))
        print(t("cli_install_hint_3"))
        return 0
    try:
        release = resolve_proton_release(query)
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    if release.installed:
        print(t("pm_already", name=release.name))
        return 0
    print(t("cli_downloading", name=release.name, size=format_bytes(release.size)))
    last = [-5]

    def progress(fraction: float, phase: str) -> None:
        pct = int(fraction * 100)
        if phase == "extract":
            if last[0] < 100:
                print("\n" + t("phase_extract"))
                last[0] = 100
            return
        if pct >= last[0] + 5 or pct >= 99:
            last[0] = pct
            print(f"\r  {pct}%", end="", flush=True)

    try:
        path = install_proton_release(release, progress=progress)
    except FileExistsError as exc:
        print(f"\n{exc}")
        return 0
    except InterruptedError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("\n" + t("cli_error", error=exc), file=sys.stderr)
        return 1
    print("\n" + t("cli_installed_path", name=path.name))
    print(t("cli_restart_steam_list"))
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    query = args.version.strip()
    tools = [tool for tool in list_compat_tools() if tool_is_removable(tool)]
    matches = [
        tool
        for tool in tools
        if tool.name.lower() == query.lower() or tool.display.lower() == query.lower()
    ]
    if not matches:
        matches = [
            tool
            for tool in tools
            if query.lower() in tool.name.lower() or query.lower() in tool.display.lower()
        ]
    if len(matches) != 1:
        if not matches:
            print(t("cli_cannot_remove", name=query), file=sys.stderr)
        else:
            print(t("cli_several_short"), file=sys.stderr)
            for tool in matches:
                print(f"  {tool.name}", file=sys.stderr)
        return 1
    tool = matches[0]
    users = games_using_tool(tool.name)
    default = default_compat_tool()
    if users or default == tool.name:
        names = ", ".join(game.name for game in users[:6])
        extra = t("cli_and_more") if len(users) > 6 else ""
        bits = []
        if default == tool.name:
            bits.append(t("cli_warning_global"))
        if names:
            bits.append(t("cli_warning_used", names=f"{names}{extra}"))
        print(t("cli_warning", text="; ".join(bits)), file=sys.stderr)
    try:
        uninstall_compat_tool(tool)
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    print(t("cli_removed", name=tool.name))
    print(t("cli_restart_compat"))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    if steam_root() is None:
        print(t("cli_no_steam"), file=sys.stderr)
        return 1
    game = None
    if getattr(args, "game", None):
        game = _pick_one(args.game)
    try:
        count = export_games(Path(args.path), only=game)
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    if game is not None:
        print(t("exported_named_path", name=game.name, path=args.path))
    else:
        print(t("exported_path", count=count, path=args.path))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    try:
        count, skipped = import_games(
            Path(args.path),
            close_steam=not args.keep_steam,
            restart_steam=not args.keep_steam,
        )
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    print(t("cli_imported", count=count))
    if skipped:
        print(t("cli_skipped", names=", ".join(skipped)))
    return 0


def cmd_steam(args: argparse.Namespace) -> int:
    if steam_root() is None:
        print(t("cli_no_steam"), file=sys.stderr)
        return 1
    try:
        current = read_steam_library_settings()
        persona_now = read_persona_state()
        if args.library is None and args.installed is None and args.status is None:
            print(
                t(
                    "cli_library_on",
                    value=t("cli_yes") if current.start_in_library else t("cli_no"),
                )
            )
            print(
                t(
                    "cli_installed_only",
                    value=t("cli_yes") if current.installed_only else t("cli_no"),
                )
            )
            print(t("cli_status_now", label=persona_label(persona_now)))
            preferred = load_persona_preference()
            if preferred is not None and preferred != persona_now:
                print(t("cli_status_next", label=persona_label(preferred)))
            return 0
        settings = SteamLibrarySettings(
            current.start_in_library if args.library is None else args.library == "on",
            current.installed_only if args.installed is None else args.installed == "on",
        )
        apply_steam_library_settings(
            settings,
            close_steam=not args.keep_steam,
            restart_steam=not args.keep_steam,
            persona=None if args.status is None else persona_value(args.status),
        )
    except Exception as exc:
        print(t("cli_error", error=exc), file=sys.stderr)
        return 1
    print(t("cli_saved_steam"))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    set_language("pl")
    samples = [
        "",
        "-novid -high",
        "gamemoderun %command%",
        "gamemoderun mangohud %command%",
        "PROTON_ENABLE_NVAPI=1 gamemoderun mangohud %command% -novid",
        "MANGOHUD=1 %command%",
        "gamemoderun gamescope -f -W 3440 -H 1440 -- %command%",
    ]
    failed = 0
    for sample in samples:
        parsed = parse_launch(sample)
        rebuilt = parsed.to_string()
        again = parse_launch(rebuilt).to_string()
        if again != rebuilt:
            print("FAIL rebuild", sample, "->", rebuilt, "->", again)
            failed += 1
        gm = toggle_token(sample, "gamemoderun", True)
        if "gamemoderun" not in gm:
            print("FAIL gamemode on", sample, gm)
            failed += 1
    on = toggle_token("", "gamemoderun", True)
    if on != "gamemoderun %command%":
        print("FAIL empty gamemode", on)
        failed += 1
    both = toggle_token(on, "mangohud", True)
    if both != "gamemoderun mangohud %command%":
        print("FAIL mangohud", both)
        failed += 1
    off = toggle_token(both, "gamemoderun", False)
    if off != "mangohud %command%":
        print("FAIL gamemode off", off)
        failed += 1
    with_nv = insert_preset(both, "PROTON_ENABLE_NVAPI=1")
    if "PROTON_ENABLE_NVAPI=1" not in with_nv:
        print("FAIL preset env", with_nv)
        failed += 1
    with_arg = insert_preset(with_nv, "-novid")
    if not with_arg.endswith("-novid"):
        print("FAIL preset arg", with_arg)
        failed += 1
    mango = parse_launch(
        "MANGOHUD_CONFIG=gpu_temp,position=top-right,fps_limit=144 mangohud %command%"
    )
    if not mango.mangohud or mango.mangohud_config.get("position") != "top-right":
        print("FAIL parse mango config", mango)
        failed += 1
    if mango.mangohud_config.get("fps_limit") != "144":
        print("FAIL fps_limit", mango.mangohud_config)
        failed += 1
    rebuilt_m = mango.to_string()
    if "MANGOHUD_CONFIG=" not in rebuilt_m or "position=top-right" not in rebuilt_m:
        print("FAIL mango to_string", rebuilt_m)
        failed += 1
    if parse_launch(rebuilt_m).to_string() != rebuilt_m:
        print("FAIL mango roundtrip", rebuilt_m)
        failed += 1
    dlsym = parse_launch("mangohud --dlsym %command%")
    if not dlsym.mangohud_dlsym or dlsym.to_string() != "mangohud --dlsym %command%":
        print("FAIL dlsym", dlsym.to_string())
        failed += 1
    built = mango_config_from_ui(
        {"gpu_temp": True, "ram": False},
        "top-right",
        "144",
        "",
        {},
    )
    text = format_mangohud_config(built)
    if "gpu_temp" not in text or "fps_limit=144" not in text or "position=top-right" not in text:
        print("FAIL mango_config_from_ui", text)
        failed += 1
    if "ram" in text.split(","):
        print("FAIL ram leaked", text)
        failed += 1
    empty = mango_config_from_ui({k: False for k, _, _ in MANGO_FLAG_OPTIONS}, "", "", "", {})
    if empty:
        print("FAIL empty mango config", empty)
        failed += 1
    if official_proton_internal("Proton Experimental") != "proton_experimental":
        print("FAIL official experimental")
        failed += 1
    if official_proton_internal("Proton Hotfix") != "proton_hotfix":
        print("FAIL official hotfix")
        failed += 1
    if official_proton_internal("Proton 9.0-4") != "proton_9":
        print("FAIL official proton 9", official_proton_internal("Proton 9.0-4"))
        failed += 1
    if official_proton_internal("Proton 6.3-8") != "proton_63":
        print("FAIL official proton 63")
        failed += 1
    if official_proton_internal("Proton BattlEye Runtime") is not None:
        print("FAIL battleye treated as proton")
        failed += 1
    if _unsigned_appid(-997512396) != "3297454900":
        print("FAIL unsigned appid", _unsigned_appid(-997512396))
        failed += 1
    if shortcut_launch_id("3297454900") != "14162460955568504832":
        print("FAIL shortcut launch id", shortcut_launch_id("3297454900"))
        failed += 1
    dummy = Game(
        appid="3297454900",
        name="Battle.net-Setup.exe",
        installdir=None,
        is_shortcut=True,
        launch_id="14162460955568504832",
    )
    blob = _search_text(dummy)
    if "battlenet" not in blob:
        print("FAIL search blob", blob)
        failed += 1
    if archive_arch("GE-Proton11-6-x86_64.tar.gz") != "x86_64":
        print("FAIL archive arch ge")
        failed += 1
    if archive_arch("proton-cachyos-11.0-20260703-slr-x86_64_v3.tar.xz") != "x86_64_v3":
        print("FAIL archive arch cachy v3")
        failed += 1
    if archive_arch("GE-Proton11-6-aarch64.tar.gz") != "aarch64":
        print("FAIL archive arch arm")
        failed += 1
    ge_assets = [
        {"name": "GE-Proton11-6-aarch64.tar.gz"},
        {"name": "GE-Proton11-6-x86_64.tar.gz"},
        {"name": "GE-Proton11-6-x86_64.sha512sum"},
    ]
    picked = pick_archive_asset(ge_assets, ["x86_64"])
    if not picked or picked["name"] != "GE-Proton11-6-x86_64.tar.gz":
        print("FAIL pick x86", picked)
        failed += 1
    picked_arm = pick_archive_asset(ge_assets, ["aarch64", "arm64"])
    if not picked_arm or "aarch64" not in picked_arm["name"]:
        print("FAIL pick arm", picked_arm)
        failed += 1
    cachy_assets = [
        {"name": "proton-cachyos-11.0-20260703-slr-x86_64.tar.xz"},
        {"name": "proton-cachyos-11.0-20260703-slr-x86_64_v3.tar.xz"},
        {"name": "proton-cachyos-11.0-20260703-slr-arm64.tar.xz"},
    ]
    picked_v3 = pick_archive_asset(cachy_assets, ["x86_64_v3", "x86_64"])
    if not picked_v3 or "x86_64_v3" not in picked_v3["name"]:
        print("FAIL pick v3", picked_v3)
        failed += 1
    check = pick_checksum_asset(ge_assets, "GE-Proton11-6-x86_64.tar.gz")
    if not check or check["name"] != "GE-Proton11-6-x86_64.sha512sum":
        print("FAIL checksum asset", check)
        failed += 1
    digest = parse_sha512("a" * 128 + "  file.tar.gz\n")
    if digest != "a" * 128:
        print("FAIL parse sha512", digest)
        failed += 1
    try:
        parse_sha512("not-a-hash")
        print("FAIL sha512 accepted garbage")
        failed += 1
    except RuntimeError:
        pass
    if _strip_archive_suffix("GE-Proton11-6-x86_64.tar.gz") != "GE-Proton11-6-x86_64":
        print("FAIL strip suffix")
        failed += 1
    import tarfile as _tarfile
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "compatibilitytool.vdf").write_text("ok", encoding="utf-8")
        archive = tmp_path / "tool.tar.gz"
        with _tarfile.open(archive, "w:gz") as tar:
            tar.add(
                payload / "compatibilitytool.vdf",
                arcname="DummyProton/compatibilitytool.vdf",
            )
        dest = tmp_path / "out"
        dest.mkdir()
        top = _safe_extract_tar(archive, dest)
        if top != "DummyProton" or not (dest / "DummyProton" / "compatibilitytool.vdf").is_file():
            print("FAIL extract", top)
            failed += 1
        evil = tmp_path / "evil.tar.gz"
        with _tarfile.open(evil, "w:gz") as tar:
            info = _tarfile.TarInfo(name="../escape/x")
            info.size = 0
            tar.addfile(info)
        try:
            _safe_extract_tar(evil, dest)
            print("FAIL extract allowed escape")
            failed += 1
        except RuntimeError:
            pass
    with tempfile.TemporaryDirectory() as tmp:
        ini = Path(tmp) / "gamemode.ini"
        fresh = load_gamemode_config(ini)
        if fresh.desiredgov != "performance" or fresh.renice != 0 or fresh.nv_max_performance:
            print("FAIL gamemode defaults", fresh)
            failed += 1
        ini.write_text(
            "[filter]\nwhitelist=RiseOfTheTombRaider\n\n"
            "[gpu]\napply_gpu_optimisations=accept-responsibility\n"
            "nv_powermizer_mode=1\nnv_core_clock_mhz_offset=50\n\n"
            "[general]\ndesiredgov=powersave\ndefaultgov=performance\nrenice=10\n"
            "ioprio=off\ninhibit_screensaver=0\n",
            encoding="utf-8",
        )
        loaded = load_gamemode_config(ini)
        if (
            loaded.desiredgov != "powersave"
            or loaded.defaultgov != "performance"
            or loaded.renice != 10
            or loaded.ioprio != "off"
            or loaded.inhibit_screensaver
            or not loaded.nv_max_performance
        ):
            print("FAIL gamemode load", loaded)
            failed += 1
        loaded.nv_max_performance = False
        loaded.defaultgov = ""
        loaded.desiredgov = "performance"
        save_gamemode_config(loaded, ini)
        text = ini.read_text(encoding="utf-8")
        if "whitelist=RiseOfTheTombRaider" not in text:
            print("FAIL gamemode dropped filter", text)
            failed += 1
        if "defaultgov=" in text:
            print("FAIL gamemode kept empty defaultgov", text)
            failed += 1
        if "nv_powermizer_mode=" in text or "nv_core_clock_mhz_offset=50" not in text:
            print("FAIL gamemode gpu merge", text)
            failed += 1
        if "apply_gpu_optimisations=accept-responsibility" not in text:
            print("FAIL gamemode dropped user gpu consent", text)
            failed += 1
        loaded.nv_max_performance = True
        save_gamemode_config(loaded, ini)
        again = load_gamemode_config(ini)
        if not again.nv_max_performance or again.desiredgov != "performance":
            print("FAIL gamemode nvidia on", again, ini.read_text(encoding="utf-8"))
            failed += 1
        bare = Path(tmp) / "bare.ini"
        bare.write_text("[gpu]\nnv_powermizer_mode=1\napply_gpu_optimisations=accept-responsibility\n", encoding="utf-8")
        bare_cfg = load_gamemode_config(bare)
        bare_cfg.nv_max_performance = False
        save_gamemode_config(bare_cfg, bare)
        bare_text = bare.read_text(encoding="utf-8")
        if "[gpu]" in bare_text or "nv_powermizer_mode" in bare_text:
            print("FAIL gamemode gpu section lingered", bare_text)
            failed += 1
    original = {
        "nVersion": 1,
        "eGameListView": 1,
        "collectionFilter": {
            "nFormatVersion": 2,
            "strSearchText": "witcher",
            "filterGroups": [
                {"rgOptions": [1, 2], "bAcceptUnion": True},
                {"rgOptions": [], "bAcceptUnion": False},
                {"rgOptions": [4], "bAcceptUnion": False},
            ],
            "setSuggestions": {"kept": 1},
        },
    }
    enabled = set_installed_only_filter(original, True)
    desktop = enabled["collectionFilter"]
    if desktop["filterGroups"][0]["rgOptions"] != [1, 2] or not desktop["filterGroups"][0]["bAcceptUnion"]:
        print("FAIL filter dropped app type", desktop["filterGroups"][0])
        failed += 1
    if desktop["filterGroups"][1] != {"rgOptions": [1], "bAcceptUnion": False}:
        print("FAIL installed filter", desktop["filterGroups"][1])
        failed += 1
    if desktop["filterGroups"][2]["rgOptions"] != [4] or desktop["strSearchText"] != "witcher":
        print("FAIL filter lost other state", desktop)
        failed += 1
    if desktop["setSuggestions"].get("kept") != 1:
        print("FAIL suggestions", desktop.get("setSuggestions"))
        failed += 1
    if enabled.get("eGameListView") != 1:
        print("FAIL view flag", enabled.get("eGameListView"))
        failed += 1
    if original["collectionFilter"]["filterGroups"][1]["rgOptions"] != []:
        print("FAIL filter mutated the input")
        failed += 1
    for key in LIBRARY_FILTER_KEYS:
        group = enabled[key]["filterGroups"][1]
        if group["rgOptions"] != [1]:
            print("FAIL filter view", key, group)
            failed += 1
    if not filter_shows_installed_only(enabled):
        print("FAIL installed switch read")
        failed += 1
    disabled = set_installed_only_filter(enabled, False)
    if filter_shows_installed_only(disabled):
        print("FAIL installed switch still on")
        failed += 1
    if disabled["collectionFilter"]["filterGroups"][2]["rgOptions"] != [4]:
        print("FAIL disable dropped other group")
        failed += 1
    mixed = set_installed_only_filter(
        {"collectionFilter": {"filterGroups": [{"rgOptions": [1], "bAcceptUnion": True}, {"rgOptions": [1, 3], "bAcceptUnion": False}]}},
        False,
    )
    if mixed["collectionFilter"]["filterGroups"][1]["rgOptions"] != [3]:
        print("FAIL disable removed extra play state", mixed["collectionFilter"]["filterGroups"][1])
        failed += 1
    if "collectionFilterGamepad" in mixed:
        print("FAIL disable created a missing view")
        failed += 1
    dialog = {"UserRoamingConfigStore": {"Software": {"Valve": {"Steam": {"SteamDefaultDialog": "#app_games", "Keep": "1"}}}}}
    mutate_steam_default_dialog(dialog, False)
    steam_node = dialog["UserRoamingConfigStore"]["Software"]["Valve"]["Steam"]
    if steam_node["SteamDefaultDialog"] != "#app_store" or steam_node["Keep"] != "1":
        print("FAIL dialog off", steam_node)
        failed += 1
    news = {"UserRoamingConfigStore": {"Software": {"Valve": {"Steam": {"SteamDefaultDialog": "#app_news"}}}}}
    mutate_steam_default_dialog(news, False)
    if news["UserRoamingConfigStore"]["Software"]["Valve"]["Steam"]["SteamDefaultDialog"] != "#app_news":
        print("FAIL dialog left a custom page")
        failed += 1
    mutate_steam_default_dialog(news, True)
    if news["UserRoamingConfigStore"]["Software"]["Valve"]["Steam"]["SteamDefaultDialog"] != "#app_games":
        print("FAIL dialog library")
        failed += 1
    persona_data = {
        "UserLocalConfigStore": {
            "WebStorage": {
                "FriendStoreLocalPrefs_5": '{"ePersonaState":1,"strNonFriendsAllowedToMsg":""}',
                "UIStoreLocalSteamUIState": "{}",
            }
        }
    }
    if persona_state_from_localconfig(persona_data, "5") != 1:
        print("FAIL persona read", persona_state_from_localconfig(persona_data, "5"))
        failed += 1
    mutate_persona_state(persona_data, "5", 7)
    web = persona_data["UserLocalConfigStore"]["WebStorage"]
    prefs = json.loads(web["FriendStoreLocalPrefs_5"])
    if prefs.get("ePersonaState") != 7 or prefs.get("strNonFriendsAllowedToMsg") != "":
        print("FAIL persona mutate", prefs)
        failed += 1
    if web.get("UIStoreLocalSteamUIState") != "{}":
        print("FAIL persona touched library state", web)
        failed += 1
    if persona_label(7) != "Niewidoczny" or persona_value("invisible") != 7:
        print("FAIL persona names")
        failed += 1
    try:
        mutate_persona_state(persona_data, "5", 4)
        print("FAIL persona accepted snooze")
        failed += 1
    except ValueError:
        pass
    empty_persona: dict = {}
    mutate_persona_state(empty_persona, "9", 0)
    created = json.loads(
        empty_persona["UserLocalConfigStore"]["WebStorage"]["FriendStoreLocalPrefs_9"]
    )
    if created.get("ePersonaState") != 0:
        print("FAIL persona create", created)
        failed += 1
    custom_games = [
        Game(appid="1", name="A", installdir=None, launch_options=" -novid ", compat_tool="proton_experimental"),
        Game(appid="2", name="B", installdir=None),
        Game(appid="3", name="C", installdir=None, is_shortcut=True),
    ]
    payload = export_games_payload(custom_games)
    if payload["format"] != "perun-games" or [row["appid"] for row in payload["games"]] != ["1"]:
        print("FAIL export payload", payload)
        failed += 1
    if payload["games"][0]["launch_options"] != " -novid ":
        print("FAIL export trimmed options")
        failed += 1
    one = export_games_payload([custom_games[1]], only_custom=False)
    if [row["appid"] for row in one["games"]] != ["2"] or one["games"][0]["name"] != "B":
        print("FAIL export one game", one)
        failed += 1
    if export_games_payload([custom_games[1]])["games"]:
        print("FAIL export all included a stock game")
        failed += 1
    local_games = [
        Game(appid="1", name="Real", installdir=None, launch_options="old"),
        Game(appid="99", name="Battle.net", installdir=None, is_shortcut=True, shortcut_index="0"),
        Game(appid="100", name="Dup", installdir=None, is_shortcut=True, shortcut_index="1"),
        Game(appid="101", name="Dup", installdir=None, is_shortcut=True, shortcut_index="2"),
    ]
    rows = [
        {"appid": "9", "name": "Other", "launch_options": "a", "compat_tool": "", "shortcut": False},
        {"appid": "1", "name": "Wrong Name", "launch_options": "", "compat_tool": "ge", "shortcut": False},
        {"appid": "50", "name": "Battle.net", "launch_options": "b", "compat_tool": "ge", "shortcut": True},
        {"appid": "51", "name": "Dup", "launch_options": "c", "compat_tool": "", "shortcut": True},
        {"appid": "nope", "name": "Zła", "launch_options": "d", "compat_tool": "", "shortcut": False},
        "broken",
    ]
    imported = plan_import(rows, local_games)
    if imported.steam != [("9", "a", ""), ("1", "", "ge")]:
        print("FAIL import steam", imported.steam)
        failed += 1
    if len(imported.shortcuts) != 1 or imported.shortcuts[0][0].appid != "99" or imported.shortcuts[0][1] != "b":
        print("FAIL import shortcut", imported.shortcuts)
        failed += 1
    if not any(item.startswith("skrót (niejednoznaczny)") for item in imported.skipped):
        print("FAIL import ambiguous", imported.skipped)
        failed += 1
    if not any(item.startswith("gra:") for item in imported.skipped):
        print("FAIL import bad appid", imported.skipped)
        failed += 1
    launch_data = {"UserLocalConfigStore": {"Software": {"Valve": {"Steam": {"apps": {"5": {"LaunchOptions": "old", "Keep": "1"}}}}}}}
    _mutate_localconfig_launches(launch_data, [("5", ""), ("9", "gamemoderun %command%")])
    apps = launch_data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
    if "LaunchOptions" in apps["5"] or apps["5"].get("Keep") != "1":
        print("FAIL clear launch", apps["5"])
        failed += 1
    if apps["9"]["LaunchOptions"] != "gamemoderun %command%":
        print("FAIL set launch", apps["9"])
        failed += 1
    compat_data = {"InstallConfigStore": {"Software": {"Valve": {"Steam": {"CompatToolMapping": {"1": {"name": "old", "config": "", "priority": "250"}}}}}}}
    _mutate_compat_tools(compat_data, [("1", ""), ("9", "GE-Proton")])
    mapping = compat_data["InstallConfigStore"]["Software"]["Valve"]["Steam"]["CompatToolMapping"]
    if "1" in mapping or mapping["9"].get("name") != "GE-Proton" or mapping["9"].get("priority") != "250":
        print("FAIL compat mutate", mapping)
        failed += 1
    shortcut_data = {"shortcuts": {"0": {"LaunchOptions": "old", "AppName": "Battle.net"}}}
    _mutate_shortcut_launches(shortcut_data, [("0", "mangohud %command%")])
    if shortcut_data["shortcuts"]["0"]["LaunchOptions"] != "mangohud %command%":
        print("FAIL shortcut mutate", shortcut_data)
        failed += 1
    if shortcut_data["shortcuts"]["0"]["AppName"] != "Battle.net":
        print("FAIL shortcut dropped name")
        failed += 1
    strings = ["appinfo", "appid", "public_only", "common", "name", "type"]

    def _kv_str(key: int, text: str) -> bytes:
        return bytes([0x01]) + struct.pack("<I", key) + text.encode() + b"\x00"

    def _kv_int(key: int, value: int) -> bytes:
        return bytes([0x02]) + struct.pack("<I", key) + struct.pack("<i", value)

    def _kv_map(key: int, inner: bytes) -> bytes:
        return bytes([0x00]) + struct.pack("<I", key) + inner + bytes([0x08])

    blob = _kv_map(0, _kv_int(1, 42) + _kv_map(3, _kv_str(4, "Test Game") + _kv_str(5, "Game"))) + bytes([0x08])
    record = struct.pack("<II", 42, 60 + len(blob)) + (b"\x00" * 60) + blob
    table = struct.pack("<I", len(strings)) + b"".join(item.encode() + b"\x00" for item in strings)
    appinfo = struct.pack("<IIq", APPINFO_MAGIC, 1, 16 + len(record)) + record + table
    parsed_info = parse_appinfo_bytes(appinfo)
    if parsed_info.get("42") != ("Test Game", "Game"):
        print("FAIL appinfo parse", parsed_info)
        failed += 1
    if parse_appinfo_bytes(b"not appinfo"):
        print("FAIL appinfo accepted garbage")
        failed += 1
    tool_strings = [
        "appinfo",
        "extended",
        "selectable_aliases",
        "proton-stable",
        "display_name",
        "Proton Stable",
        "compat_tools",
        "proton_experimental",
        "Proton Experimental",
        "from_oslist",
        "windows",
        "to_oslist",
        "linux",
        "aliases",
        "proton-experimental",
        "proton_11",
        "Proton 11.0-2",
        "proton-stable,proton-11.0",
        "proton_9",
        "Proton 9.0-4",
        "proton_63",
        "Proton 6.3-8",
        "proton_hotfix",
        "Proton Hotfix",
        "legacy",
        "steamlinuxruntime",
        "Steam Linux Runtime 1.0",
        "unlisted",
        "native",
        "proton-experimental-arm64",
        "Proton Experimental (ARM64)",
    ]
    stable_alias = _kv_map(3, _kv_str(4, "Proton Stable"))
    selectable = _kv_map(2, stable_alias)
    experimental = _kv_map(
        7,
        _kv_str(4, "Proton Experimental")
        + _kv_str(9, "windows")
        + _kv_str(11, "linux")
        + _kv_str(13, "proton-experimental"),
    )
    proton_11 = _kv_map(
        15,
        _kv_str(4, "Proton 11.0-2")
        + _kv_str(9, "windows")
        + _kv_str(11, "linux")
        + _kv_str(13, "proton-stable,proton-11.0"),
    )
    proton_9 = _kv_map(18, _kv_str(4, "Proton 9.0-4") + _kv_str(9, "windows"))
    proton_63 = _kv_map(
        20, _kv_str(4, "Proton 6.3-8") + _kv_str(9, "windows") + _kv_int(24, 1)
    )
    hotfix = _kv_map(
        22, _kv_str(4, "Proton Hotfix") + _kv_str(9, "windows") + _kv_int(24, 1)
    )
    runtime = _kv_map(
        25,
        _kv_str(4, "Steam Linux Runtime 1.0")
        + _kv_str(9, "linux")
        + _kv_int(27, 1)
        + _kv_str(13, "native"),
    )
    arm64 = _kv_map(29, _kv_str(4, "Proton Experimental (ARM64)") + _kv_str(9, "windows"))
    tool_blob = (
        _kv_map(
            0,
            _kv_map(1, selectable + _kv_map(6, experimental + proton_11 + proton_9 + proton_63 + hotfix + runtime + arm64)),
        )
        + bytes([0x08])
    )
    tool_record = struct.pack("<II", STEAM_PLAY_MANIFEST_APPID, 60 + len(tool_blob)) + (b"\x00" * 60) + tool_blob
    tool_table = struct.pack("<I", len(tool_strings)) + b"".join(item.encode() + b"\x00" for item in tool_strings)
    tool_appinfo = struct.pack("<IIq", APPINFO_MAGIC, 1, 16 + len(tool_record)) + tool_record + tool_table
    catalog = compat_tools_from_appinfo(tool_appinfo)
    catalog_names = [tool.name for tool in catalog]
    if platform.machine().lower() in {"aarch64", "arm64"}:
        if "proton-experimental-arm64" not in catalog_names:
            print("FAIL arm catalog dropped arm64 proton", catalog_names)
            failed += 1
    elif "proton-experimental-arm64" in catalog_names:
        print("FAIL catalog kept arm64 proton", catalog_names)
        failed += 1
    expected_names = [
        "proton-stable",
        "proton_experimental",
        "proton_hotfix",
        "proton_11",
        "proton_9",
        "proton_63",
    ]
    if platform.machine().lower() not in {"aarch64", "arm64"} and catalog_names != expected_names:
        print("FAIL compat catalog order", catalog_names)
        failed += 1
    by_catalog = {tool.name: tool.display for tool in catalog}
    if by_catalog.get("proton-stable") != "Proton Stable" or by_catalog.get("proton_11") != "Proton 11.0-2":
        print("FAIL compat catalog labels", by_catalog)
        failed += 1
    if "steamlinuxruntime" in catalog_names:
        print("FAIL catalog listed a runtime")
        failed += 1
    if compat_display("proton-11.0", catalog) != "Proton 11.0-2":
        print("FAIL alias display", compat_display("proton-11.0", catalog))
        failed += 1
    if compat_display("proton-stable", catalog) != "Proton Stable":
        print("FAIL stable display", compat_display("proton-stable", catalog))
        failed += 1
    if compat_tools_from_appinfo(b"not appinfo"):
        print("FAIL compat catalog accepted garbage")
        failed += 1
    if vdf is None:
        print("FAIL python-vdf missing")
        failed += 1
    else:
        packed = json.dumps(enabled, ensure_ascii=False, separators=(",", ":"))
        wrapped = {"UserLocalConfigStore": {"WebStorage": {"UIStoreLocalSteamUIState": packed}}}
        loaded = vdf.loads(_dump_vdf(wrapped))
        raw_state = loaded["UserLocalConfigStore"]["WebStorage"]["UIStoreLocalSteamUIState"]
        if not filter_shows_installed_only(json.loads(raw_state)):
            print("FAIL vdf filter roundtrip", raw_state[:120])
            failed += 1
        loaded_apps = vdf.loads(_dump_vdf(launch_data))
        round_apps = loaded_apps["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
        if round_apps["9"]["LaunchOptions"] != "gamemoderun %command%":
            print("FAIL vdf launch roundtrip", round_apps)
            failed += 1
    set_language("en")
    if t("btn_save") != "Save" or persona_label(7) != "Invisible":
        print("FAIL english", t("btn_save"), persona_label(7))
        failed += 1
    if export_filename(None) != "perun-games.json" or export_filename(custom_games[1]) != "perun-B.json":
        print("FAIL export filename en", export_filename(None), export_filename(custom_games[1]))
        failed += 1
    set_language("de")
    if t("btn_save") != "Speichern" or persona_label(7) != "Unsichtbar":
        print("FAIL german", t("btn_save"), persona_label(7))
        failed += 1
    if export_filename(None) != "perun-spiele.json":
        print("FAIL export filename de", export_filename(None))
        failed += 1
    if set_language("xx") != "pl" or t("btn_save") != "Zapisz" or persona_label(7) != "Niewidoczny":
        print("FAIL language fallback", get_language(), t("btn_save"), persona_label(7))
        failed += 1
    polish_skip = plan_import(
        [{"appid": "51", "name": "Dup", "launch_options": "c", "shortcut": True}],
        local_games,
    )
    if not any(item.startswith("skrót (niejednoznaczny)") for item in polish_skip.skipped):
        print("FAIL polish skip after language restore", polish_skip.skipped)
        failed += 1
    print("OK" if failed == 0 else f"{failed} failed")
    return 0 if failed == 0 else 1


# --- GUI --------------------------------------------------------------------

def cmd_gui(_: argparse.Namespace) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from threading import Thread

    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

    class PerunWindow(Adw.ApplicationWindow):
        def __init__(self, app: Adw.Application) -> None:
            super().__init__(application=app, title=APP_NAME)
            self.set_default_size(980, 640)
            self.games: list[Game] = []
            self.selected: Game | None = None
            self._syncing = False
            self._search = ""
            self._steam_was_running = False
            self._proton_tools: list[CompatTool] = []
            self._default_proton = ""
            self._proton_win: Adw.Window | None = None
            self._pm_releases: list[ProtonRelease] = []
            self._pm_cancel = [False]
            self._pm_busy = False
            self._show_all = load_show_all_games()
            self._settings_win: Adw.Window | None = None
            self._settings_busy = False
            self._i18n: list[tuple] = []
            self._combo_rows: list = []
            self._preset_rows: list[tuple] = []
            self._lang_lock = False
            self._language: Adw.ComboRow | None = None
            self._export_one_row: Adw.ActionRow | None = None
            self._pm_note_key: str | None = None

            self.toast_overlay = Adw.ToastOverlay()
            self.set_content(self.toast_overlay)

            toolbar = Adw.ToolbarView()
            self.toast_overlay.set_child(toolbar)

            header = Adw.HeaderBar()
            title = Adw.WindowTitle(title=APP_NAME, subtitle=t("subtitle_main"))
            self._tr("subtitle", title, "subtitle_main")
            header.set_title_widget(title)
            refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            self._tr("tooltip", refresh_btn, "tip_refresh")
            refresh_btn.connect("clicked", lambda *_: self.reload())
            header.pack_start(refresh_btn)
            proton_mgr_btn = Gtk.Button.new_from_icon_name("folder-download-symbolic")
            self._tr("tooltip", proton_mgr_btn, "tip_proton")
            proton_mgr_btn.connect("clicked", lambda *_: self._open_proton_manager())
            header.pack_end(proton_mgr_btn)
            settings_btn = Gtk.Button.new_from_icon_name("preferences-system-symbolic")
            self._tr("tooltip", settings_btn, "tip_settings")
            settings_btn.connect("clicked", lambda *_: self._open_library_settings())
            header.pack_end(settings_btn)
            toolbar.add_top_bar(header)

            self.banner = Adw.Banner()
            self._tr("banner", self.banner, "banner_steam")
            toolbar.add_top_bar(self.banner)

            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            paned.set_resize_start_child(False)
            paned.set_resize_end_child(True)
            paned.set_shrink_start_child(False)
            paned.set_shrink_end_child(True)
            paned.set_wide_handle(True)
            paned.set_position(340)
            toolbar.set_content(paned)

            # lewa kolumna — stała szerokość, żeby tytuły gier nie łamały się litera po literze
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            left.set_size_request(300, -1)
            search = Gtk.SearchEntry()
            self._tr("placeholder", search, "search_placeholder")
            search.set_margin_start(10)
            search.set_margin_end(10)
            search.set_margin_top(8)
            search.set_margin_bottom(8)
            search.connect("search-changed", self._on_search)
            left.append(search)

            account_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            account_row.set_margin_start(12)
            account_row.set_margin_end(12)
            account_row.set_margin_bottom(6)
            account_label = Gtk.Label(xalign=0, hexpand=True)
            account_label.set_ellipsize(Pango.EllipsizeMode.END)
            self._tr("label", account_label, "all_games", "all_games_tip")
            self.all_switch = Gtk.Switch()
            self.all_switch.set_valign(Gtk.Align.CENTER)
            self.all_switch.set_tooltip_text(t("all_games_tip"))
            self._i18n.append(("main", "tooltip", self.all_switch, ("all_games_tip",)))
            self.all_switch.set_active(self._show_all)
            self.all_switch.connect("notify::active", self._on_show_all)
            account_row.append(account_label)
            account_row.append(self.all_switch)
            left.append(account_row)

            scroller = Gtk.ScrolledWindow()
            scroller.set_vexpand(True)
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.listbox = Gtk.ListBox()
            self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.listbox.add_css_class("navigation-sidebar")
            self.listbox.set_filter_func(self._filter_row)
            placeholder = Gtk.Label()
            self._tr("label", placeholder, "no_games")
            self.listbox.set_placeholder(placeholder)
            self.listbox.connect("row-selected", self._on_select)
            scroller.set_child(self.listbox)
            left.append(scroller)
            paned.set_start_child(left)

            # prawa kolumna
            right_scroll = Gtk.ScrolledWindow()
            right_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            clamp = Adw.Clamp(maximum_size=720, tightening_threshold=520)
            clamp.set_margin_top(12)
            clamp.set_margin_bottom(24)
            clamp.set_margin_start(16)
            clamp.set_margin_end(16)
            self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            clamp.set_child(self.detail)
            right_scroll.set_child(clamp)
            paned.set_end_child(right_scroll)

            self.empty = Adw.StatusPage(icon_name="input-gaming-symbolic")
            self._tr("status", self.empty, "empty_title", "empty_desc")
            self.editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            self._build_editor()
            self.detail.append(self.empty)

            save_action = Gio.SimpleAction.new("save", None)
            save_action.connect("activate", lambda *_: self._on_save())
            self.add_action(save_action)
            app.set_accels_for_action("win.save", ["<Control>s"])

            self.connect("close-request", self._on_close)
            GLib.timeout_add_seconds(2, self._poll_steam)
            self.reload()

        def _tr(self, kind: str, widget, *keys: str, scope: str = "main") -> None:
            self._i18n.append((scope, kind, widget, keys))
            self._paint(kind, widget, keys)

        def _paint(self, kind: str, widget, keys: tuple[str, ...]) -> None:
            if kind == "subtitle":
                widget.set_subtitle(t(keys[0]))
            elif kind == "tooltip":
                widget.set_tooltip_text(t(keys[0]))
            elif kind == "banner":
                widget.set_title(t(keys[0]))
            elif kind == "placeholder":
                widget.set_placeholder_text(t(keys[0]))
            elif kind == "label":
                widget.set_text(t(keys[0]))
                if len(keys) > 1 and keys[1]:
                    widget.set_tooltip_text(t(keys[1]))
            elif kind == "status":
                widget.set_title(t(keys[0]))
                widget.set_description(t(keys[1]) if len(keys) > 1 and keys[1] else "")
            elif kind == "group":
                widget.set_title(t(keys[0]))
                widget.set_description(t(keys[1]) if len(keys) > 1 and keys[1] else None)
            elif kind == "row":
                widget.set_title(t(keys[0]))
                if len(keys) > 1 and keys[1]:
                    widget.set_subtitle(t(keys[1]))
            elif kind == "button":
                widget.set_label(t(keys[0]))
            elif kind == "window":
                widget.set_title(t(keys[0]))
            elif kind == "heading":
                widget.set_title(t(keys[0]))
                if len(keys) > 1 and keys[1]:
                    widget.set_subtitle(t(keys[1]))

        def _drop_scope(self, scope: str) -> None:
            self._i18n = [item for item in self._i18n if item[0] != scope]
            self._combo_rows = [
                row for row in self._combo_rows if getattr(row, "_scope", "main") != scope
            ]

        def _reload_labeled_combo(self, row: Adw.ComboRow) -> None:
            pairs = getattr(row, "_pairs", None)
            if not pairs:
                return
            current = self._combo_get(row) if getattr(row, "_values", None) else None
            previous = self._syncing
            self._syncing = True
            row.set_model(Gtk.StringList.new([t(label_key) for _value, label_key in pairs]))
            row._values = [value for value, _label_key in pairs]
            if current is None:
                row.set_selected(0)
            else:
                self._combo_set(row, current)
            self._syncing = previous

        def _apply_texts(self) -> None:
            for _scope, kind, widget, keys in list(self._i18n):
                self._paint(kind, widget, keys)
            for row in list(self._combo_rows):
                self._reload_labeled_combo(row)
            for row, _label_key, _tip_key, value in self._preset_rows:
                row.set_tooltip_text(t("preset_add_tip", value=value))
            self._refresh_list_subtitles()
            self._refresh_game_meta()
            self._refresh_proton_labels()
            self._refresh_status_line()
            self._refresh_export_one_row()
            if steam_root() is None:
                self.empty.set_title(t("steam_missing_title"))
                self.empty.set_description(t("steam_missing_desc"))
            if self._settings_alive() and not self._settings_busy:
                self._refresh_steam_status()
            self._refresh_proton_manager_texts()

        def _on_language(self, *_args) -> None:
            if self._lang_lock or self._syncing or self._language is None:
                return
            index = int(self._language.get_selected())
            codes = language_codes()
            if index < 0 or index >= len(codes) or codes[index] == get_language():
                return
            try:
                save_language(codes[index])
            except OSError as exc:
                self.toast(str(exc))
                return
            self._apply_texts()

        def _build_editor(self) -> None:
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            self.game_icon = Gtk.Image()
            self.game_icon.set_pixel_size(64)
            head.append(self.game_icon)
            titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            titles.set_valign(Gtk.Align.CENTER)
            titles.set_hexpand(True)
            self.game_title = Gtk.Label(xalign=0)
            self.game_title.add_css_class("title-2")
            self.game_title.set_wrap(True)
            self.game_title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.game_meta = Gtk.Label(xalign=0, hexpand=True)
            self.game_meta.add_css_class("dim-label")
            self.game_meta.set_wrap(True)
            self.game_meta.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            titles.append(self.game_title)
            titles.append(self.game_meta)
            head.append(titles)
            play = Gtk.Button()
            self._tr("button", play, "btn_play")
            play.add_css_class("suggested-action")
            play.set_valign(Gtk.Align.CENTER)
            play.connect("clicked", self._on_play)
            head.append(play)
            self.editor.append(head)

            proton_group = Adw.PreferencesGroup()
            self._tr("group", proton_group, "grp_proton", "grp_proton_desc")
            self.proton_row = Adw.ComboRow()
            self._tr("row", self.proton_row, "row_proton", "row_proton_sub")
            self._prepare_version_combo(self.proton_row)
            self.proton_row.set_model(Gtk.StringList.new([t("proton_default")]))
            self.proton_row._values = [""]  # type: ignore[attr-defined]
            self.proton_row.connect("notify::selected", self._on_proton_changed)
            proton_group.add(self.proton_row)
            manage = Adw.ActionRow()
            self._tr("row", manage, "row_manage", "row_manage_sub")
            manage.set_activatable(True)
            manage.add_suffix(Gtk.Image.new_from_icon_name("folder-download-symbolic"))
            manage.connect("activated", lambda *_: self._open_proton_manager())
            proton_group.add(manage)
            self.editor.append(proton_group)

            toggles = Adw.PreferencesGroup()
            self._tr("group", toggles, "grp_overlays", "grp_overlays_desc")
            self.gm_row = Adw.ExpanderRow()
            self._tr("row", self.gm_row, "row_gamemode", "row_gamemode_sub")
            self.gm_row.set_show_enable_switch(True)
            self.gm_row.set_expanded(False)
            self.gm_row.connect("notify::enable-expansion", self._on_gamemode_master)
            renice_key = "gm_renice_member" if user_in_gamemode_group() else "gm_renice_guest"
            self.gm_gov = self._make_combo("gm_gov", "gm_gov_sub", GAMEMODE_GOVERNORS)
            self.gm_gov_after = self._make_combo(
                "gm_gov_after", "gm_gov_after_sub", GAMEMODE_GOV_AFTER
            )
            self.gm_renice = self._make_combo("gm_renice", renice_key, GAMEMODE_RENICE)
            self.gm_ioprio = self._make_combo("gm_ioprio", "gm_ioprio_sub", GAMEMODE_IOPRIO)
            self.sw_gm_screen = Adw.SwitchRow()
            self._tr("row", self.sw_gm_screen, "sw_screen", "sw_screen_sub")
            self.sw_gm_nvidia = Adw.SwitchRow()
            self._tr("row", self.sw_gm_nvidia, "sw_nvidia", "sw_nvidia_sub")
            for widget in (
                self.gm_gov,
                self.gm_gov_after,
                self.gm_renice,
                self.gm_ioprio,
            ):
                widget.connect("notify::selected", self._on_gamemode_setting)
                self.gm_row.add_row(widget)
            for widget in (self.sw_gm_screen, self.sw_gm_nvidia):
                widget.connect("notify::active", self._on_gamemode_setting)
                self.gm_row.add_row(widget)
            toggles.add(self.gm_row)
            self._syncing = True
            self._load_gamemode_ui()
            self._syncing = False

            self.mango_row = Adw.ExpanderRow()
            self._tr("row", self.mango_row, "row_mango", "row_mango_sub")
            self.mango_row.set_show_enable_switch(True)
            self.mango_row.set_expanded(False)
            self.mango_row.connect("notify::enable-expansion", self._on_mango_master)

            self.mango_position = self._make_combo("mango_pos", "mango_pos_sub", MANGO_POSITIONS)
            self.mango_fps_limit = self._make_combo("mango_fps", "mango_fps_sub", MANGO_FPS_LIMITS)
            self.mango_font = self._make_combo("mango_font", "mango_font_sub", MANGO_FONT_SIZES)
            self.sw_mango_dlsym = Adw.SwitchRow()
            self._tr("row", self.sw_mango_dlsym, "sw_dlsym", "sw_dlsym_sub")
            for combo in (self.mango_position, self.mango_fps_limit, self.mango_font):
                combo.connect("notify::selected", self._on_mango_changed)
                self.mango_row.add_row(combo)
            self.sw_mango_dlsym.connect("notify::active", self._on_mango_changed)
            self.mango_row.add_row(self.sw_mango_dlsym)

            self.mango_flags: dict[str, Adw.SwitchRow] = {}
            for key, title_key, tip_key in MANGO_FLAG_OPTIONS:
                row = Adw.SwitchRow()
                self._tr("row", row, title_key, tip_key)
                row.connect("notify::active", self._on_mango_changed)
                self.mango_flags[key] = row
                self.mango_row.add_row(row)

            toggles.add(self.mango_row)
            self.editor.append(toggles)

            add_icon = "list-add-symbolic"
            for group_title, group_desc, items in PRESET_GROUPS:
                group = Adw.PreferencesGroup()
                self._tr("group", group, group_title, group_desc)
                for label_key, value, tip_key in items:
                    row = Adw.ActionRow()
                    self._tr("row", row, label_key, tip_key)
                    row.set_activatable(True)
                    row.set_tooltip_text(t("preset_add_tip", value=value))
                    self._preset_rows.append((row, label_key, tip_key, value))
                    row.add_suffix(Gtk.Image.new_from_icon_name(add_icon))
                    row.connect("activated", self._on_preset, value)
                    group.add(row)
                self.editor.append(group)

            cmd_group = Adw.PreferencesGroup()
            self._tr("group", cmd_group, "grp_command", "grp_command_desc")
            self.command = Adw.EntryRow()
            self._tr("row", self.command, "row_options")
            self._tr("tooltip", self.command, "tip_options")
            self.command.connect("changed", self._on_command_changed)
            cmd_group.add(self.command)
            self.editor.append(cmd_group)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            clear_btn = Gtk.Button()
            self._tr("button", clear_btn, "btn_clear")
            clear_btn.connect("clicked", self._on_clear)
            buttons.append(clear_btn)
            copy_btn = Gtk.Button()
            self._tr("button", copy_btn, "btn_copy")
            copy_btn.connect("clicked", self._on_copy)
            buttons.append(copy_btn)
            export_btn = Gtk.Button()
            self._tr("button", export_btn, "btn_export_game")
            export_btn.connect("clicked", lambda *_: self._on_export_games(self.selected))
            buttons.append(export_btn)
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            buttons.append(spacer)
            self.save_btn = Gtk.Button()
            self._tr("button", self.save_btn, "btn_save")
            self.save_btn.add_css_class("suggested-action")
            self.save_btn.connect("clicked", self._on_save)
            buttons.append(self.save_btn)
            self.editor.append(buttons)

            self.status = Gtk.Label(xalign=0)
            self.status.add_css_class("dim-label")
            self.status.set_wrap(True)
            self.editor.append(self.status)

        def toast(self, text: str) -> None:
            self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=3))

        def reload(self) -> None:
            selected_id = self.selected.appid if self.selected else None
            try:
                self.games = list_games(include_uninstalled=self._show_all)
                self._proton_tools = list_compat_tools()
                self._default_proton = default_compat_tool()
            except Exception as exc:
                self.toast(str(exc))
                self.games = []
                self._proton_tools = []
                self._default_proton = ""
            self._fill_list(selected_id)
            self._poll_steam()
            root = steam_root()
            if root is None:
                self.empty.set_title(t("steam_missing_title"))
                self.empty.set_description(t("steam_missing_desc"))

        def _game_list_subtitle(self, game: Game) -> str:
            sub = game.launch_options or t("list_no_options")
            if game.is_shortcut:
                return t("list_kind_prefix", kind=t("list_shortcut"), sub=sub)
            if not game.installed:
                return t("list_kind_prefix", kind=t("list_uninstalled"), sub=sub)
            return sub

        def _refresh_list_subtitles(self) -> None:
            index = 0
            while True:
                row = self.listbox.get_row_at_index(index)
                if row is None:
                    break
                game = self._game_for_row(row)
                if game is not None and isinstance(row, Adw.ActionRow):
                    row.set_subtitle(self._game_list_subtitle(game))
                index += 1

        def _game_meta_text(self, game: Game) -> str:
            last = (
                datetime.fromtimestamp(game.last_played).strftime("%Y-%m-%d %H:%M")
                if game.last_played
                else t("meta_never")
            )
            proton = compat_display(game.compat_tool, self._proton_tools)
            if game.is_shortcut:
                origin = t("origin_shortcut")
            else:
                origin = t("origin_steam")
                if not game.installed:
                    origin += t("origin_uninstalled_suffix")
            return t(
                "meta_line",
                origin=origin,
                appid=game.appid,
                proton=proton,
                last=last,
            )

        def _refresh_game_meta(self) -> None:
            if self.selected is not None and hasattr(self, "game_meta"):
                self.game_meta.set_text(self._game_meta_text(self.selected))

        def _refresh_proton_labels(self) -> None:
            if not hasattr(self, "proton_row"):
                return
            current = self._combo_get(self.proton_row)
            previous = self._syncing
            self._syncing = True
            self._fill_proton_combo(current)
            self._syncing = previous

        def _refresh_status_line(self) -> None:
            if self.selected is None or not hasattr(self, "status"):
                return
            if not self.save_btn.get_sensitive():
                self.status.set_text(t("status_saving"))
                return
            self._mark_dirty()

        def _refresh_export_one_row(self) -> None:
            row = self._export_one_row
            if row is None:
                return
            game = self.selected
            if game is None:
                row.set_subtitle(t("row_export_one_none"))
                row.set_sensitive(False)
            else:
                row.set_subtitle(t("row_export_one_sub", name=game.name))
                row.set_sensitive(True)

        def _refresh_proton_manager_texts(self) -> None:
            if self._proton_win is None or not hasattr(self, "_pm_flavor"):
                return
            flavor_id = self._combo_get(self._pm_flavor)
            flavor = next((item for item in PROTON_FLAVORS if item["id"] == flavor_id), None)
            if flavor is not None:
                self._pm_flavor.set_subtitle(t(flavor["blurb"]))
            if self._pm_busy:
                return
            if self._pm_releases:
                self._pm_show_releases()
            elif self._pm_note_key:
                self._pm_status.set_text(t(self._pm_note_key))
                self._pm_version.set_subtitle(t(self._pm_note_key))
            self._pm_fill_installed()

        def _fill_list(self, selected_id: str | None) -> None:
            while (child := self.listbox.get_first_child()) is not None:
                self.listbox.remove(child)
            pick = None
            for game in self.games:
                row = Adw.ActionRow(title=game.name)
                row.set_subtitle(self._game_list_subtitle(game))
                row.set_title_lines(1)
                row.set_subtitle_lines(1)
                row.appid = game.appid  # type: ignore[attr-defined]
                if game.icon:
                    img = Gtk.Image.new_from_file(str(game.icon))
                    img.set_pixel_size(32)
                    row.add_prefix(img)
                else:
                    icon_name = (
                        "application-x-executable-symbolic"
                        if game.is_shortcut
                        else "input-gaming-symbolic"
                    )
                    img = Gtk.Image.new_from_icon_name(icon_name)
                    img.set_pixel_size(32)
                    row.add_prefix(img)
                self.listbox.append(row)
                if selected_id and game.appid == selected_id:
                    pick = row
            if pick is not None:
                self.listbox.select_row(pick)
            elif self.games:
                first = self.listbox.get_row_at_index(0)
                if first is not None:
                    self.listbox.select_row(first)

        def _filter_row(self, row: Gtk.ListBoxRow) -> bool:
            if not self._search:
                return True
            game = self._game_for_row(row)
            if game is None:
                return False
            q = self._search
            compact = re.sub(r"[^a-z0-9]+", "", q)
            blob = _search_text(game)
            return q in blob or bool(compact and compact in blob)

        def _game_for_row(self, row: Gtk.ListBoxRow | None) -> Game | None:
            if row is None:
                return None
            appid = getattr(row, "appid", None)
            for game in self.games:
                if game.appid == appid:
                    return game
            return None

        def _on_search(self, entry: Gtk.SearchEntry) -> None:
            self._search = entry.get_text().strip().lower()
            self.listbox.invalidate_filter()

        def _on_select(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
            game = self._game_for_row(row)
            self.selected = game
            self._show_game(game)

        def _show_pane(self, widget: Gtk.Widget) -> None:
            child = self.detail.get_first_child()
            if child is widget:
                return
            if child is not None:
                self.detail.remove(child)
            self.detail.append(widget)

        def _show_game(self, game: Game | None) -> None:
            if game is None:
                self._show_pane(self.empty)
                return
            self._show_pane(self.editor)
            self.game_title.set_text(game.name)
            self.game_meta.set_text(self._game_meta_text(game))
            if game.icon:
                self.game_icon.set_from_file(str(game.icon))
            else:
                self.game_icon.set_from_icon_name(
                    "application-x-executable-symbolic"
                    if game.is_shortcut
                    else "input-gaming-symbolic"
                )
            self._syncing = True
            self._fill_proton_combo(game.compat_tool)
            self.command.set_text(game.launch_options)
            self._apply_toggles(parse_launch(game.launch_options))
            self._syncing = False
            self._set_status_idle()

        def _fill_proton_combo(self, current: str) -> None:
            default_label = (
                t("proton_default_named", name=self._default_proton)
                if self._default_proton
                else t("proton_default")
            )
            pairs: list[tuple[str, str]] = [("", default_label)]
            seen = {""}
            for tool in self._proton_tools:
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                pairs.append((tool.name, tool.display))
            if current and current not in seen:
                pairs.append((current, compat_display(current, self._proton_tools)))
            labels = [label for _, label in pairs]
            values = [value for value, _ in pairs]
            self.proton_row.set_model(Gtk.StringList.new(labels))
            self.proton_row._values = values  # type: ignore[attr-defined]
            self._combo_set(self.proton_row, current or "")

        def _prepare_version_combo(self, row: Adw.ComboRow) -> None:
            """Pełne nazwy wersji w liście. Domyślna fabryka libadwaity ucina je po 20 znakach."""
            button_factory = Gtk.SignalListItemFactory()

            def setup_button(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
                label = Gtk.Label(xalign=1, hexpand=True)
                label.set_halign(Gtk.Align.END)
                label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                # Nazwa w wierszu ma mieć miejsce na cały identyfikator, nie na „proton-ca…”.
                label.set_width_chars(46)
                label.set_max_width_chars(72)
                item.set_child(label)

            def bind_button(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
                obj = item.get_item()
                text = obj.get_string() if isinstance(obj, Gtk.StringObject) else ""
                item.get_child().set_text(text)

            button_factory.connect("setup", setup_button)
            button_factory.connect("bind", bind_button)
            row.set_factory(button_factory)

            list_factory = Gtk.SignalListItemFactory()

            def setup_list(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                label = Gtk.Label(xalign=0, hexpand=True)
                label.set_halign(Gtk.Align.START)
                label.set_ellipsize(Pango.EllipsizeMode.NONE)
                icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
                box.append(label)
                box.append(icon)
                item.set_child(box)

            def bind_list(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
                box = item.get_child()
                label = box.get_first_child()
                icon = label.get_next_sibling()
                obj = item.get_item()
                text = obj.get_string() if isinstance(obj, Gtk.StringObject) else ""
                label.set_text(text)

                def sync(*_args: object) -> None:
                    icon.set_opacity(1.0 if row.get_selected_item() is obj else 0.0)

                sync()
                item._perun_sig = row.connect("notify::selected-item", sync)  # type: ignore[attr-defined]

            def unbind_list(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
                sig = getattr(item, "_perun_sig", None)
                if sig is not None:
                    row.disconnect(sig)
                    item._perun_sig = None  # type: ignore[attr-defined]

            list_factory.connect("setup", setup_list)
            list_factory.connect("bind", bind_list)
            list_factory.connect("unbind", unbind_list)
            row.set_list_factory(list_factory)

            def widen_popup() -> bool:
                scrolled = None
                seen_popover = False

                def walk(widget: Gtk.Widget) -> None:
                    nonlocal scrolled, seen_popover
                    if isinstance(widget, Gtk.Popover):
                        seen_popover = True
                    if (
                        seen_popover
                        and scrolled is None
                        and isinstance(widget, Gtk.ScrolledWindow)
                    ):
                        scrolled = widget
                    child = widget.get_first_child()
                    while child is not None:
                        walk(child)
                        child = child.get_next_sibling()

                walk(row)
                if scrolled is None:
                    return False
                scrolled.set_propagate_natural_width(True)
                scrolled.set_propagate_natural_height(True)
                # Cała nazwa (proton-cachyos-…-x86_64_v3) i więcej niż kilka wierszy.
                scrolled.set_max_content_width(840)
                scrolled.set_max_content_height(560)
                return False

            GLib.idle_add(widen_popup)

        def _make_combo(
            self,
            title_key: str,
            subtitle_key: str,
            pairs: list[tuple[str, str]],
            scope: str = "main",
        ) -> Adw.ComboRow:
            row = Adw.ComboRow()
            row._pairs = pairs  # type: ignore[attr-defined]
            row._scope = scope  # type: ignore[attr-defined]
            self._combo_rows.append(row)
            self._tr("row", row, title_key, subtitle_key, scope=scope)
            self._reload_labeled_combo(row)
            return row

        def _combo_get(self, row: Adw.ComboRow) -> str:
            values: list[str] = getattr(row, "_values", [])
            index = int(row.get_selected())
            if index < 0 or index >= len(values):
                return ""
            return values[index]

        def _combo_set(self, row: Adw.ComboRow, value: str) -> None:
            values: list[str] = getattr(row, "_values", [])
            model = row.get_model()
            if value and value not in values:
                values.append(value)
                if isinstance(model, Gtk.StringList):
                    model.append(value)
                row._values = values  # type: ignore[attr-defined]
            if value in values:
                row.set_selected(values.index(value))
            else:
                row.set_selected(0)

        def _apply_toggles(self, parsed: ParsedLaunch) -> None:
            self.gm_row.set_enable_expansion(parsed.gamemode)
            self.mango_row.set_enable_expansion(parsed.mangohud)
            self.mango_row.set_expanded(bool(parsed.mangohud and parsed.mangohud_config))
            cfg = parsed.mangohud_config
            for key, switch in self.mango_flags.items():
                on = key in cfg and cfg[key] not in {"0", "false", "False"}
                switch.set_active(on)
            self._combo_set(self.mango_position, cfg.get("position", ""))
            self._combo_set(self.mango_fps_limit, cfg.get("fps_limit", ""))
            self._combo_set(self.mango_font, cfg.get("font_size", ""))
            self.sw_mango_dlsym.set_active(parsed.mangohud_dlsym)

        def _collect_mango(self, previous: dict[str, str]) -> dict[str, str]:
            flags = {key: row.get_active() for key, row in self.mango_flags.items()}
            return mango_config_from_ui(
                flags,
                self._combo_get(self.mango_position),
                self._combo_get(self.mango_fps_limit),
                self._combo_get(self.mango_font),
                previous,
            )

        def _write_launch(self, parsed: ParsedLaunch) -> None:
            self._syncing = True
            self.command.set_text(parsed.to_string())
            self._syncing = False
            self._mark_dirty()

        def _on_proton_changed(self, *_args) -> None:
            if self._syncing or self.selected is None:
                return
            self._mark_dirty()

        def _load_gamemode_ui(self) -> None:
            try:
                cfg = load_gamemode_config()
            except Exception:
                cfg = GameModeConfig()
            self._combo_set(self.gm_gov, cfg.desiredgov)
            self._combo_set(self.gm_gov_after, cfg.defaultgov)
            self._combo_set(self.gm_renice, str(cfg.renice))
            self._combo_set(self.gm_ioprio, cfg.ioprio)
            self.sw_gm_screen.set_active(cfg.inhibit_screensaver)
            self.sw_gm_nvidia.set_active(cfg.nv_max_performance)

        def _on_gamemode_master(self, row: Adw.ExpanderRow, _pspec=None) -> None:
            if self._syncing or self.selected is None:
                return
            if row.get_enable_expansion():
                row.set_expanded(True)
            updated = toggle_token(
                self.command.get_text(), "gamemoderun", row.get_enable_expansion()
            )
            self._write_launch(parse_launch(updated))

        def _on_gamemode_setting(self, *_args) -> None:
            if self._syncing:
                return
            cfg = GameModeConfig(
                desiredgov=self._combo_get(self.gm_gov) or "performance",
                defaultgov=self._combo_get(self.gm_gov_after),
                renice=int(self._combo_get(self.gm_renice) or "0"),
                ioprio=self._combo_get(self.gm_ioprio) or "0",
                inhibit_screensaver=self.sw_gm_screen.get_active(),
                nv_max_performance=self.sw_gm_nvidia.get_active(),
            )
            try:
                save_gamemode_config(cfg)
            except Exception as exc:
                self.toast(str(exc))
                return
            self.toast(t("toast_gamemode"))

        def _on_mango_master(self, row: Adw.ExpanderRow, _pspec=None) -> None:
            if self._syncing or self.selected is None:
                return
            if row.get_enable_expansion():
                row.set_expanded(True)
            self._on_mango_changed()

        def _on_mango_changed(self, *_args) -> None:
            if self._syncing or self.selected is None:
                return
            parsed = parse_launch(self.command.get_text())
            parsed.mangohud = self.mango_row.get_enable_expansion()
            parsed.mangohud_dlsym = bool(
                parsed.mangohud and self.sw_mango_dlsym.get_active()
            )
            if parsed.mangohud:
                parsed.mangohud_config = self._collect_mango(parsed.mangohud_config)
            else:
                parsed.mangohud_config = {}
                parsed.mangohud_dlsym = False
            self._write_launch(parsed)

        def _on_preset(self, _btn: Gtk.Button, preset: str) -> None:
            if self.selected is None:
                return
            updated = insert_preset(self.command.get_text(), preset)
            self._syncing = True
            self.command.set_text(updated)
            self._apply_toggles(parse_launch(updated))
            self._syncing = False
            self._mark_dirty()

        def _on_command_changed(self, _entry: Gtk.Entry) -> None:
            if self._syncing:
                return
            self._syncing = True
            self._apply_toggles(parse_launch(self.command.get_text()))
            self._syncing = False
            self._mark_dirty()

        def _mark_dirty(self) -> None:
            if self.selected is None:
                return
            cmd_dirty = self.command.get_text().strip() != (
                self.selected.launch_options or ""
            ).strip()
            proton_dirty = self._combo_get(self.proton_row) != (self.selected.compat_tool or "")
            self.save_btn.set_sensitive(True)
            if cmd_dirty or proton_dirty:
                self.status.set_text(t("status_dirty"))
            else:
                self._set_status_idle()

        def _set_status_idle(self) -> None:
            if is_steam_running():
                self.status.set_text(t("status_steam_on"))
            else:
                self.status.set_text(t("status_steam_off"))

        def _on_clear(self, *_args) -> None:
            self._syncing = True
            self.command.set_text("")
            self._apply_toggles(ParsedLaunch())
            self._syncing = False
            self._mark_dirty()

        def _on_copy(self, *_args) -> None:
            display = Gdk.Display.get_default()
            if display is None:
                return
            display.get_clipboard().set(self.command.get_text())
            self.toast(t("toast_copied"))

        def _on_play(self, *_args) -> None:
            if self.selected is None:
                return
            launch_id = self.selected.launch_id or self.selected.appid
            subprocess.Popen(
                steam_argv(f"steam://rungameid/{launch_id}"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.toast(t("toast_launch", name=self.selected.name))

        def _on_save(self, *_args) -> None:
            if self.selected is None:
                return
            options = self.command.get_text().strip()
            proton = self._combo_get(self.proton_row)
            game = self.selected
            name = game.name
            self.save_btn.set_sensitive(False)
            self.status.set_text(t("status_saving"))
            close = is_steam_running()

            def work() -> None:
                err: str | None = None
                try:
                    save_game(
                        game,
                        launch_options=options,
                        compat_tool=proton,
                        close_steam=close,
                        restart_steam=close,
                    )
                except Exception as exc:
                    err = str(exc)

                def done() -> None:
                    self.save_btn.set_sensitive(True)
                    if err:
                        self.status.set_text(err)
                        self.toast(t("toast_save_fail"))
                        dialog = Adw.AlertDialog(heading=t("dlg_not_saved"), body=err)
                        dialog.add_response("ok", t("btn_ok"))
                        dialog.present(self)
                        return
                    self.toast(t("toast_saved", name=name))
                    self.reload()
                    if close:
                        self.status.set_text(t("status_saved_restart"))
                    else:
                        self.status.set_text(t("status_saved"))

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _open_proton_manager(self) -> None:
            if self._proton_win is not None:
                self._proton_win.present()
                return
            win = Adw.Window()
            self._tr("window", win, "win_proton", scope="proton")
            win.set_transient_for(self)
            win.set_modal(True)
            win.set_default_size(560, 620)
            win.connect("close-request", self._on_proton_manager_close)

            toolbar = Adw.ToolbarView()
            win.set_content(toolbar)
            header = Adw.HeaderBar()
            pm_title = Adw.WindowTitle()
            self._tr("heading", pm_title, "win_proton", "win_proton_sub", scope="proton")
            header.set_title_widget(pm_title)
            toolbar.add_top_bar(header)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480)
            clamp.set_margin_top(12)
            clamp.set_margin_bottom(24)
            clamp.set_margin_start(16)
            clamp.set_margin_end(16)
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            clamp.set_child(column)
            scroll.set_child(clamp)
            toolbar.set_content(scroll)

            self._pm_installed_group = Adw.PreferencesGroup()
            self._tr("group", self._pm_installed_group, "grp_installed", "grp_installed_desc", scope="proton")
            self._pm_installed_rows: list[Gtk.Widget] = []
            column.append(self._pm_installed_group)

            add_group = Adw.PreferencesGroup()
            self._tr("group", add_group, "grp_github", "grp_github_desc", scope="proton")
            self._pm_flavor = Adw.ComboRow()
            self._tr("row", self._pm_flavor, "row_flavor", scope="proton")
            self._pm_flavor.set_subtitle(t(PROTON_FLAVORS[0]["blurb"]))
            self._pm_flavor.set_model(
                Gtk.StringList.new([item["name"] for item in PROTON_FLAVORS])
            )
            self._pm_flavor._values = [item["id"] for item in PROTON_FLAVORS]  # type: ignore[attr-defined]
            self._pm_flavor.connect("notify::selected", self._pm_on_flavor)
            add_group.add(self._pm_flavor)

            self._pm_version = Adw.ComboRow()
            self._tr("row", self._pm_version, "row_release", scope="proton")
            self._pm_version.set_subtitle(t("pm_fetching"))
            self._prepare_version_combo(self._pm_version)
            self._pm_version.set_model(Gtk.StringList.new(["—"]))
            self._pm_version._values = [""]  # type: ignore[attr-defined]
            add_group.add(self._pm_version)
            column.append(add_group)

            self._pm_progress = Gtk.ProgressBar()
            self._pm_progress.set_show_text(True)
            self._pm_progress.set_visible(False)
            column.append(self._pm_progress)

            self._pm_status = Gtk.Label(xalign=0)
            self._pm_status.add_css_class("dim-label")
            self._pm_status.set_wrap(True)
            self._pm_note_key = "pm_choose"
            self._pm_status.set_text(t("pm_choose"))
            column.append(self._pm_status)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self._pm_cancel_btn = Gtk.Button()
            self._tr("button", self._pm_cancel_btn, "btn_cancel", scope="proton")
            self._pm_cancel_btn.set_sensitive(False)
            self._pm_cancel_btn.connect("clicked", self._pm_on_cancel)
            buttons.append(self._pm_cancel_btn)
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            buttons.append(spacer)
            self._pm_install_btn = Gtk.Button()
            self._tr("button", self._pm_install_btn, "btn_install", scope="proton")
            self._pm_install_btn.add_css_class("suggested-action")
            self._pm_install_btn.connect("clicked", self._pm_on_install)
            buttons.append(self._pm_install_btn)
            column.append(buttons)

            self._proton_win = win
            self._pm_fill_installed()
            self._pm_load_versions()
            win.present()

        def _on_proton_manager_close(self, *_args) -> bool:
            if self._pm_busy:
                self._pm_cancel[0] = True
            self._drop_scope("proton")
            self._proton_win = None
            return False

        def _pm_fill_installed(self) -> None:
            for row in self._pm_installed_rows:
                self._pm_installed_group.remove(row)
            self._pm_installed_rows = []
            tools = [tool for tool in list_compat_tools() if tool_is_removable(tool)]
            if not tools:
                row = Adw.ActionRow(title=t("pm_none"), subtitle=t("pm_none_sub"))
                self._pm_installed_group.add(row)
                self._pm_installed_rows.append(row)
                return
            default = default_compat_tool()
            for tool in tools:
                users = games_using_tool(tool.name)
                bits = []
                if tool.name == default:
                    bits.append(t("pm_default_play"))
                if users:
                    bits.append(
                        ", ".join(game.name for game in users[:3])
                        + ("…" if len(users) > 3 else "")
                    )
                row = Adw.ActionRow(title=tool.display)
                row.set_subtitle("; ".join(bits) if bits else t("pm_unassigned"))
                btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                btn.add_css_class("flat")
                btn.set_valign(Gtk.Align.CENTER)
                btn.set_tooltip_text(t("tip_remove", name=tool.name))
                btn.connect("clicked", self._pm_on_uninstall, tool.name)
                row.add_suffix(btn)
                self._pm_installed_group.add(row)
                self._pm_installed_rows.append(row)

        def _pm_on_flavor(self, *_args) -> None:
            if self._pm_busy:
                return
            flavor_id = self._combo_get(self._pm_flavor)
            flavor = next((item for item in PROTON_FLAVORS if item["id"] == flavor_id), None)
            if flavor:
                self._pm_flavor.set_subtitle(t(flavor["blurb"]))
            self._pm_load_versions()

        def _pm_load_versions(self) -> None:
            flavor_id = self._combo_get(self._pm_flavor) or PROTON_FLAVORS[0]["id"]
            self._pm_note_key = "pm_fetching"
            self._pm_version.set_subtitle(t("pm_fetching"))
            self._pm_install_btn.set_sensitive(False)

            def work() -> None:
                err: str | None = None
                releases: list[ProtonRelease] = []
                try:
                    releases = fetch_proton_releases(flavor_id)
                except Exception as exc:
                    err = str(exc)

                def done() -> None:
                    if self._proton_win is None:
                        return
                    if err:
                        self._pm_releases = []
                        self._pm_note_key = None
                        self._pm_version.set_model(Gtk.StringList.new([t("pm_fetch_fail")]))
                        self._pm_version._values = [""]  # type: ignore[attr-defined]
                        self._pm_version.set_subtitle(err)
                        self._pm_status.set_text(err)
                        self._pm_install_btn.set_sensitive(False)
                        return
                    self._pm_releases = releases
                    if not releases:
                        self._pm_note_key = "pm_github_empty"
                        self._pm_version.set_model(Gtk.StringList.new([t("pm_no_releases")]))
                        self._pm_version._values = [""]  # type: ignore[attr-defined]
                        self._pm_version.set_subtitle(t("pm_github_empty"))
                        self._pm_status.set_text(t("pm_github_empty"))
                        self._pm_install_btn.set_sensitive(False)
                        return
                    self._pm_show_releases()

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _pm_show_releases(self) -> None:
            labels = []
            values = []
            for item in self._pm_releases:
                mark = t("pm_installed_mark") if item.installed else ""
                labels.append(f"{item.name}  ·  {format_bytes(item.size)}{mark}")
                values.append(item.name)
            selected = self._combo_get(self._pm_version)
            self._pm_version.set_model(Gtk.StringList.new(labels))
            self._pm_version._values = values  # type: ignore[attr-defined]
            if selected in values:
                self._pm_version.set_selected(values.index(selected))
            else:
                self._pm_version.set_selected(0)
            self._pm_note_key = "pm_choose"
            self._pm_version.set_subtitle(t("pm_pick_release"))
            self._pm_install_btn.set_sensitive(True)
            self._pm_status.set_text(t("pm_choose"))

        def _pm_selected_release(self) -> ProtonRelease | None:
            name = self._combo_get(self._pm_version)
            for item in self._pm_releases:
                if item.name == name:
                    return item
            return None

        def _pm_on_cancel(self, *_args) -> None:
            self._pm_cancel[0] = True
            self._pm_status.set_text(t("pm_cancelling"))

        def _pm_set_busy(self, busy: bool) -> None:
            self._pm_busy = busy
            self._pm_install_btn.set_sensitive(not busy)
            self._pm_cancel_btn.set_sensitive(busy)
            self._pm_flavor.set_sensitive(not busy)
            self._pm_version.set_sensitive(not busy)
            self._pm_progress.set_visible(busy)

        def _pm_on_install(self, *_args) -> None:
            release = self._pm_selected_release()
            if release is None or self._pm_busy:
                return
            if release.installed:
                self._pm_status.set_text(t("pm_already", name=release.name))
                return
            self._pm_cancel[0] = False
            self._pm_set_busy(True)
            self._pm_progress.set_fraction(0)
            self._pm_progress.set_text("0%")
            self._pm_status.set_text(
                t("pm_downloading", name=release.name, size=format_bytes(release.size))
            )

            def progress(fraction: float, phase: str) -> None:
                def tick() -> None:
                    if self._proton_win is None:
                        return
                    self._pm_progress.set_fraction(max(0.0, min(fraction, 1.0)))
                    self._pm_progress.set_text(f"{int(fraction * 100)}%")
                    phase_text = t("phase_extract") if phase == "extract" else t("phase_download")
                    self._pm_status.set_text(f"{phase_text} {release.name}")

                GLib.idle_add(tick)

            def work() -> None:
                err: str | None = None
                path: Path | None = None
                try:
                    path = install_proton_release(
                        release, progress=progress, cancel=self._pm_cancel
                    )
                except InterruptedError as exc:
                    err = str(exc)
                except Exception as exc:
                    err = str(exc)

                def done() -> None:
                    if self._proton_win is None:
                        return
                    self._pm_set_busy(False)
                    if err:
                        self._pm_status.set_text(err)
                        self.toast(t("toast_proton_fail"))
                        return
                    name = path.name if path is not None else release.name
                    self._pm_note_key = None
                    self._pm_status.set_text(t("pm_installed_done", name=name))
                    self.toast(t("toast_installed", name=name))
                    self._pm_fill_installed()
                    self._pm_load_versions()
                    self.reload()

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _pm_on_uninstall(self, _btn: Gtk.Button, tool_name: str) -> None:
            if self._pm_busy:
                return
            tool = next(
                (item for item in list_compat_tools() if item.name == tool_name),
                None,
            )
            if tool is None or not tool_is_removable(tool):
                return
            users = games_using_tool(tool.name)
            default = default_compat_tool()
            body = t("pm_delete_body", path=tool.install_path)
            if tool.name == default:
                body += t("pm_delete_default")
            if users:
                names = ", ".join(game.name for game in users[:8])
                if len(users) > 8:
                    names += "…"
                body += t("pm_delete_users", names=names)
            dialog = Adw.AlertDialog(
                heading=t("pm_delete_heading", name=tool.display),
                body=body,
            )
            dialog.add_response("cancel", t("btn_cancel"))
            dialog.add_response("delete", t("btn_delete"))
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def on_response(_dlg, response: str) -> None:
                if response != "delete":
                    return
                try:
                    uninstall_compat_tool(tool)
                except Exception as exc:
                    self.toast(str(exc))
                    return
                self.toast(t("toast_removed", name=tool.name))
                self._pm_fill_installed()
                self._pm_load_versions()
                self.reload()

            dialog.connect("response", on_response)
            parent = self._proton_win or self
            dialog.present(parent)

        def _on_show_all(self, switch: Gtk.Switch, _pspec: object) -> None:
            self._show_all = bool(switch.get_active())
            try:
                save_show_all_games(self._show_all)
            except OSError as exc:
                self.toast(str(exc))
            self.reload()

        def _open_library_settings(self) -> None:
            if self._settings_win is not None:
                self._settings_win.present()
                return
            win = Adw.Window()
            self._tr("window", win, "win_settings", scope="settings")
            win.set_transient_for(self)
            win.set_modal(True)
            win.set_default_size(520, 720)
            win.connect("close-request", self._on_library_settings_close)

            toolbar = Adw.ToolbarView()
            win.set_content(toolbar)
            header = Adw.HeaderBar()
            heading = Adw.WindowTitle()
            self._tr("heading", heading, "win_settings", "win_settings_sub", scope="settings")
            header.set_title_widget(heading)
            toolbar.add_top_bar(header)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480)
            clamp.set_margin_top(12)
            clamp.set_margin_bottom(24)
            clamp.set_margin_start(16)
            clamp.set_margin_end(16)
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            clamp.set_child(column)
            scroll.set_child(clamp)
            toolbar.set_content(scroll)

            lang_group = Adw.PreferencesGroup()
            self._tr("group", lang_group, "language", "language_desc", scope="settings")
            self._language = Adw.ComboRow()
            self._tr("row", self._language, "language_row", "language_row_sub", scope="settings")
            self._language.set_model(Gtk.StringList.new([name for _code, name in LANGUAGES]))
            codes = language_codes()
            current = get_language()
            index = codes.index(current) if current in codes else 0
            self._lang_lock = True
            self._language.set_selected(index)
            self._lang_lock = False
            self._language.connect("notify::selected", self._on_language)
            lang_group.add(self._language)
            column.append(lang_group)

            library_group = Adw.PreferencesGroup()
            self._tr("group", library_group, "grp_library", "grp_library_desc", scope="settings")
            self._sw_library = Adw.SwitchRow()
            self._tr("row", self._sw_library, "sw_library", "sw_library_sub", scope="settings")
            self._sw_installed = Adw.SwitchRow()
            self._tr("row", self._sw_installed, "sw_installed", "sw_installed_sub", scope="settings")
            library_group.add(self._sw_library)
            library_group.add(self._sw_installed)
            column.append(library_group)

            status_group = Adw.PreferencesGroup()
            self._tr("group", status_group, "grp_friends", "grp_friends_desc", scope="settings")
            self._persona_row = self._make_combo(
                "row_persona",
                "row_persona_sub",
                [(str(value), label) for value, _key, label in PERSONA_STATES],
                scope="settings",
            )
            status_group.add(self._persona_row)
            column.append(status_group)

            self._steam_status = Gtk.Label(xalign=0)
            self._steam_status.add_css_class("dim-label")
            self._steam_status.set_wrap(True)
            column.append(self._steam_status)

            steam_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            steam_spacer = Gtk.Box()
            steam_spacer.set_hexpand(True)
            steam_buttons.append(steam_spacer)
            self._steam_save_btn = Gtk.Button()
            self._tr("button", self._steam_save_btn, "btn_save_steam", scope="settings")
            self._steam_save_btn.add_css_class("suggested-action")
            self._steam_save_btn.connect("clicked", self._on_save_steam_settings)
            steam_buttons.append(self._steam_save_btn)
            column.append(steam_buttons)

            share_group = Adw.PreferencesGroup()
            self._tr("group", share_group, "grp_share", "grp_share_desc", scope="settings")
            export_all = Adw.ActionRow()
            self._tr("row", export_all, "row_export_all", "row_export_all_sub", scope="settings")
            export_all.set_activatable(True)
            export_all.add_suffix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
            export_all.connect("activated", lambda *_: self._on_export_games(None))
            self._export_one_row = Adw.ActionRow()
            self._tr("row", self._export_one_row, "row_export_one", scope="settings")
            self._export_one_row.set_activatable(True)
            self._export_one_row.add_suffix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
            self._export_one_row.connect(
                "activated", lambda *_: self._on_export_games(self.selected)
            )
            import_row = Adw.ActionRow()
            self._tr("row", import_row, "row_import", "row_import_sub", scope="settings")
            import_row.set_activatable(True)
            import_row.add_suffix(Gtk.Image.new_from_icon_name("document-open-symbolic"))
            import_row.connect("activated", lambda *_: self._on_import_games())
            share_group.add(export_all)
            share_group.add(self._export_one_row)
            share_group.add(import_row)
            column.append(share_group)

            self._settings_win = win
            self._load_library_switches()
            self._refresh_export_one_row()
            win.present()

        def _on_library_settings_close(self, *_args) -> bool:
            self._drop_scope("settings")
            self._settings_win = None
            self._language = None
            self._export_one_row = None
            return False

        def _load_library_switches(self) -> None:
            try:
                settings = read_steam_library_settings()
            except Exception as exc:
                self.toast(str(exc))
                settings = SteamLibrarySettings(False, False)
            self._syncing = True
            self._sw_library.set_active(settings.start_in_library)
            self._sw_installed.set_active(settings.installed_only)
            preferred = load_persona_preference()
            current_persona = preferred
            if current_persona is None:
                try:
                    current_persona = read_persona_state()
                except (OSError, RuntimeError, FileNotFoundError):
                    current_persona = None
            self._combo_set(
                self._persona_row,
                str(current_persona if current_persona is not None else 1),
            )
            self._syncing = False
            self._refresh_steam_status()

        def _refresh_steam_status(self) -> None:
            if not self._settings_alive() or not hasattr(self, "_steam_status"):
                return
            if is_steam_running():
                self._steam_status.set_text(t("steam_will_restart"))
            else:
                self._steam_status.set_text(t("steam_is_off"))

        def _settings_alive(self) -> bool:
            return self._settings_win is not None

        def _on_save_steam_settings(self, *_args) -> None:
            if not self._settings_alive() or self._settings_busy:
                return
            settings = SteamLibrarySettings(
                self._sw_library.get_active(),
                self._sw_installed.get_active(),
            )
            raw_persona = self._combo_get(self._persona_row)
            persona = int(raw_persona) if raw_persona.isdigit() else None
            close = is_steam_running()
            self._settings_busy = True
            self._steam_save_btn.set_sensitive(False)
            self._steam_status.set_text(t("status_saving_steam"))

            def work() -> None:
                err: str | None = None
                try:
                    apply_steam_library_settings(
                        settings,
                        close_steam=close,
                        restart_steam=close,
                        persona=persona,
                    )
                except Exception as exc:
                    err = str(exc)

                def done() -> None:
                    self._settings_busy = False
                    if not self._settings_alive():
                        return
                    self._steam_save_btn.set_sensitive(True)
                    if err:
                        self._steam_status.set_text(err)
                        self.toast(t("toast_steam_fail"))
                        dialog = Adw.AlertDialog(heading=t("dlg_not_saved"), body=err)
                        dialog.add_response("ok", t("btn_ok"))
                        dialog.present(self._settings_win)
                        return
                    self.toast(t("toast_steam_ok"))
                    self._load_library_switches()
                    if close:
                        self._steam_status.set_text(t("status_saved_restart"))

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _json_file_dialog(self, title: str) -> Gtk.FileDialog:
            dialog = Gtk.FileDialog()
            dialog.set_title(title)
            dialog.set_modal(True)
            file_filter = Gtk.FileFilter()
            file_filter.set_name(t("filter_json"))
            file_filter.add_pattern("*.json")
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(file_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(file_filter)
            return dialog

        def _on_export_games(self, game: Game | None = None) -> None:
            if self._settings_busy or (game is not None and not isinstance(game, Game)):
                return
            parent = self._settings_win or self
            if isinstance(game, Game):
                dialog = self._json_file_dialog(t("dlg_export_one", name=game.name))
                dialog.set_initial_name(export_filename(game))
            else:
                if self._settings_win is None:
                    return
                dialog = self._json_file_dialog(t("dlg_export"))
                dialog.set_initial_name(export_filename(None))
            target = game

            def chosen(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
                self._on_export_chosen(dlg, result, target)

            dialog.save(parent, None, chosen)

        def _on_export_chosen(
            self,
            dialog: Gtk.FileDialog,
            result: Gio.AsyncResult,
            game: Game | None = None,
        ) -> None:
            try:
                chosen = dialog.save_finish(result)
            except GLib.Error:
                return
            path_text = chosen.get_path() if chosen is not None else None
            if not path_text:
                self.toast(t("toast_bad_save"))
                return
            path = Path(path_text)

            def work() -> None:
                err: str | None = None
                count = 0
                try:
                    count = export_games(path, only=game)
                except Exception as exc:
                    err = str(exc)

                def done() -> None:
                    if err:
                        self.toast(t("toast_export_fail"))
                        alert = Adw.AlertDialog(heading=t("dlg_export_fail"), body=err)
                        alert.add_response("ok", t("btn_ok"))
                        alert.present(self._settings_win or self)
                        return
                    if game is not None:
                        self.toast(t("exported_named", name=game.name))
                    elif count == 1:
                        self.toast(t("exported_one"))
                    else:
                        self.toast(t("exported_many", count=count))

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _on_import_games(self) -> None:
            if not self._settings_alive() or self._settings_busy:
                return
            dialog = self._json_file_dialog(t("dlg_import"))
            dialog.open(self._settings_win, None, self._on_import_chosen)

        def _on_import_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, *_args) -> None:
            try:
                chosen = dialog.open_finish(result)
            except GLib.Error:
                return
            path_text = chosen.get_path() if chosen is not None else None
            if not path_text:
                self.toast(t("toast_bad_open"))
                return
            path = Path(path_text)
            if is_steam_running():
                body = t("import_body_running")
            else:
                body = t("import_body_idle")
            confirm = Adw.AlertDialog(heading=t("dlg_import_ask"), body=body)
            confirm.add_response("cancel", t("btn_cancel"))
            confirm.add_response("import", t("btn_import"))
            confirm.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
            confirm.set_default_response("import")
            confirm.set_close_response("cancel")

            def on_response(_dlg: Adw.AlertDialog, response: str) -> None:
                if response != "import":
                    return
                self._run_import(path)

            confirm.connect("response", on_response)
            confirm.present(self._settings_win or self)

        def _run_import(self, path: Path) -> None:
            if self._settings_busy:
                return
            close = is_steam_running()
            self._settings_busy = True
            self._steam_save_btn.set_sensitive(False)
            self.status.set_text(t("status_importing"))

            def work() -> None:
                err: str | None = None
                count = 0
                skipped: list[str] = []
                try:
                    count, skipped = import_games(
                        path,
                        close_steam=close,
                        restart_steam=close,
                    )
                except Exception as exc:
                    err = str(exc)

                def done() -> None:
                    self._settings_busy = False
                    self.save_btn.set_sensitive(True)
                    if self._settings_alive():
                        self._steam_save_btn.set_sensitive(True)
                    if err:
                        self.status.set_text(err)
                        self.toast(t("toast_import_fail"))
                        alert = Adw.AlertDialog(heading=t("dlg_import_fail"), body=err)
                        alert.add_response("ok", t("btn_ok"))
                        alert.present(self._settings_win or self)
                        return
                    self.reload()
                    message = t("imported_one") if count == 1 else t("imported_many", count=count)
                    detail = message
                    if skipped:
                        detail += "." + t("skipped_suffix", names=", ".join(skipped))
                    self.toast(message)
                    self.status.set_text(detail)
                    if self._settings_alive():
                        self._refresh_steam_status()

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _poll_steam(self) -> bool:
            running = is_steam_running()
            self.banner.set_revealed(running)
            return True

        def _on_close(self, *_args) -> bool:
            return False

    class PerunApp(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.connect("activate", self._on_activate)

        def _on_activate(self, app: Adw.Application) -> None:
            win = app.get_active_window()
            if win is None:
                win = PerunWindow(app)
            win.present()

    if vdf is None:
        print(t("err_no_vdf"), file=sys.stderr)
        return 1
    Adw.init()
    app = PerunApp()
    return app.run(None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perun",
        description=t("cli_desc"),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help=t("help_list"))
    p_list.add_argument("--all", action="store_true", help=t("help_all"))
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help=t("help_get"))
    p_get.add_argument("game", help=t("help_game"))
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help=t("help_set"))
    p_set.add_argument("game", help=t("help_game"))
    p_set.add_argument("options", nargs="?", default="", help=t("help_options"))
    p_set.add_argument("--keep-steam", action="store_true", help=t("help_keep_steam"))
    p_set.set_defaults(func=cmd_set)

    p_clear = sub.add_parser("clear", help=t("help_clear"))
    p_clear.add_argument("game")
    p_clear.add_argument("--keep-steam", action="store_true")
    p_clear.set_defaults(func=cmd_set, options="")

    p_tools = sub.add_parser("tools", help=t("help_tools"))
    p_tools.set_defaults(func=cmd_tools)

    p_proton = sub.add_parser("proton", help=t("help_proton"))
    p_proton.add_argument("game", help=t("help_game"))
    p_proton.add_argument("tool", nargs="?", help=t("help_proton_tool"))
    p_proton.add_argument("--keep-steam", action="store_true")
    p_proton.set_defaults(func=cmd_proton)

    p_install = sub.add_parser("install", help=t("help_install"))
    p_install.add_argument("version", nargs="?", help=t("help_install_version"))
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help=t("help_uninstall"))
    p_uninstall.add_argument("version", help=t("help_uninstall_version"))
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_export = sub.add_parser("export", help=t("help_export"))
    p_export.add_argument("path", help=t("help_export_path"))
    p_export.add_argument("--game", help=t("help_export_game"))
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help=t("help_import"))
    p_import.add_argument("path", help=t("help_import_path"))
    p_import.add_argument("--keep-steam", action="store_true")
    p_import.set_defaults(func=cmd_import)

    p_steam = sub.add_parser("steam", help=t("help_steam"))
    p_steam.add_argument("--library", choices=("on", "off"), help=t("help_library"))
    p_steam.add_argument("--installed", choices=("on", "off"), help=t("help_installed_flag"))
    p_steam.add_argument(
        "--status",
        choices=tuple(key for _value, key, _label in PERSONA_STATES),
        help=t("help_status"),
    )
    p_steam.add_argument("--keep-steam", action="store_true")
    p_steam.set_defaults(func=cmd_steam)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "selftest":
        set_language("pl")
        return cmd_selftest(argparse.Namespace())
    load_language()
    if not argv or argv[0] not in {
        "list",
        "get",
        "set",
        "clear",
        "tools",
        "proton",
        "install",
        "uninstall",
        "export",
        "import",
        "steam",
        "-h",
        "--help",
        "--version",
    }:
        if argv and argv[0] == "gui":
            argv = argv[1:]
        ns = argparse.Namespace()
        return cmd_gui(ns)
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        return cmd_gui(args)
    return int(func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
