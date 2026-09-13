#!/usr/bin/env python3
"""Perun — opcje uruchamiania i Proton dla gier Steam (w tym spoza Steam)."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shlex
import shutil
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
VERSION = "1.5.0"

UNCHANGED = object()

BACKUP_DIR = Path.home() / ".local/share/perun/backups"
BACKUP_KEEP = 10

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

# (tytuł grupy, opis grupy, [(etykieta, komenda, co robi)])
PRESET_GROUPS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "Obraz i okno",
        "Argumenty dopisywane na końcu — trafiają wprost do gry.",
        [
            (
                "Pomiń intro",
                "-novid",
                "Wyłącza filmik startowy studia. W komendzie: -novid",
            ),
            (
                "Pełny ekran",
                "-fullscreen",
                "Start na całym monitorze. W komendzie: -fullscreen",
            ),
            (
                "W oknie",
                "-windowed",
                "Start w oknie zamiast na pełnym ekranie. W komendzie: -windowed",
            ),
            (
                "Ultrawide 3440×1440",
                "-w 3440 -h 1440",
                "Wymusza rozdzielczość Twojego monitora. W komendzie: -w 3440 -h 1440",
            ),
        ],
    ),
    (
        "Proton (gry z Windowsa)",
        "Zmienne przed %command%. Działają, gdy gra idzie przez Proton.",
        [
            (
                "DLSS / Reflex (NVIDIA)",
                "PROTON_ENABLE_NVAPI=1",
                "Włącza NVAPI w Protonie: DLSS, Reflex, Frame Generation.",
            ),
            (
                "Licznik FPS (DXVK)",
                "DXVK_HUD=fps",
                "Tylko gry DX11. Diablo 4 jest na DX12 — tu nic nie da, użyj MangoHud.",
            ),
            (
                "OpenGL zamiast Vulkan",
                "PROTON_USE_WINED3D=1",
                "Gdy Vulkan wywala grę. Zwykle wolniejsze, ale bywa stabilniejsze.",
            ),
            (
                "Wyłącz esync",
                "PROTON_NO_ESYNC=1",
                "Gdy gra wisi na starcie. W Diablo 4 zwykle pogarsza przycinki — lepiej bez tego.",
            ),
            (
                "NVIDIA DX12 mniej przycinek",
                "VKD3D_CONFIG=no_upload_hvv",
                "Omija host-visible VRAM w vkd3d. Czasem ścina mikro-stutter w Diablo 4 / DX12.",
            ),
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
    ("gpu_temp", "Temperatura GPU", "Temperatura karty graficznej"),
    ("gpu_power", "Moc GPU", "Pobór mocy karty w watach"),
    ("gpu_core_clock", "Taktowanie GPU", "Zegar rdzenia karty"),
    ("cpu_temp", "Temperatura CPU", "Temperatura procesora"),
    ("vram", "VRAM", "Zajętość pamięci karty"),
    ("ram", "RAM", "Zajętość pamięci systemowej"),
    ("wine", "Proton / Wine", "Wersja Protona albo Wine"),
    ("resolution", "Rozdzielczość", "Aktualna rozdzielczość gry"),
    ("hud_compact", "Zwarty HUD", "Mniejsza nakładka, mniej odstępów"),
    ("horizontal", "Poziomy układ", "Wszystko w jednej linii"),
    ("no_display", "Ukryj na starcie", "Schowany, aż naciśniesz prawy Shift+F12"),
]
MANGO_POSITIONS: list[tuple[str, str]] = [
    ("", "Domyślna (lewy górny)"),
    ("top-left", "Lewy górny róg"),
    ("top-center", "Góra, środek"),
    ("top-right", "Prawy górny róg"),
    ("bottom-left", "Lewy dolny róg"),
    ("bottom-center", "Dół, środek"),
    ("bottom-right", "Prawy dolny róg"),
]
MANGO_FPS_LIMITS: list[tuple[str, str]] = [
    ("", "Nie ograniczaj"),
    ("60", "60 FPS"),
    ("90", "90 FPS (połowa z 180 Hz)"),
    ("120", "120 FPS — płynniej na 180 Hz"),
    ("144", "144 FPS"),
    ("165", "165 FPS"),
    ("175", "175 FPS (VRR, 180 Hz − 5)"),
    ("180", "180 FPS"),
    ("240", "240 FPS"),
]
MANGO_FONT_SIZES: list[tuple[str, str]] = [
    ("", "Domyślna"),
    ("16", "16 px — mała"),
    ("20", "20 px"),
    ("24", "24 px"),
    ("28", "28 px"),
    ("32", "32 px — duża"),
]
MANGO_FLAG_KEYS = {key for key, _, _ in MANGO_FLAG_OPTIONS}
MANGO_VALUE_KEYS = {"position", "fps_limit", "font_size"}
MANGO_KNOWN_KEYS = set(MANGO_BASELINE) | MANGO_FLAG_KEYS | MANGO_VALUE_KEYS


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
        raise RuntimeError("Brak pakietu python-vdf. Zainstaluj: pacman -S python-vdf")
    return vdf.loads(path.read_text(encoding="utf-8", errors="replace"))


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


@dataclass
class CompatTool:
    name: str
    display: str
    official: bool = False
    install_path: Path | None = None


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
                internal, CompatTool(name=internal, display=name, official=True)
            )

    custom = sorted(
        (t for t in by_name.values() if not t.official),
        key=lambda t: t.display.lower(),
        reverse=True,
    )
    official = sorted(
        (t for t in by_name.values() if t.official),
        key=lambda t: t.display.lower(),
        reverse=True,
    )
    return custom + official


def compat_display(internal: str, tools: list[CompatTool] | None = None) -> str:
    if not internal:
        return "domyślny / Steam Play"
    for tool in tools or []:
        if tool.name == internal:
            return tool.display
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
        "blurb": "GloriousEggroll — gdy nie wiesz, co wybrać.",
        "api": f"{GITHUB_API}/repos/GloriousEggroll/proton-ge-custom/releases",
    },
    {
        "id": "cachyos",
        "name": "Proton-CachyOS",
        "blurb": "Build CachyOS. Wariant x86_64_v3, gdy CPU ma AVX2.",
        "api": f"{GITHUB_API}/repos/CachyOS/proton-cachyos/releases",
    },
]


def compatibilitytools_dir(root: Path | None = None) -> Path:
    root = root or steam_root()
    if root is None:
        raise FileNotFoundError("Nie znaleziono instalacji Steam.")
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
        raise RuntimeError("Niepoprawny plik SHA512.")
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
            raise RuntimeError(
                "GitHub ograniczył zapytania (limit API). Spróbuj za chwilę."
            ) from exc
        raise RuntimeError(f"GitHub HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Nie udało się połączyć z GitHubem: {exc.reason}") from exc


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
        raise ValueError(f"Nieznany rodzaj Protona: {flavor_id}")
    url = f"{flavor['api']}?per_page={int(count)}"
    payload = _http_json(url)
    if not isinstance(payload, list):
        msg = _github_error_message(payload) or "GitHub nie zwrócił listy wydań."
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
        raise ValueError("Podaj nazwę Protona, np. GE-Proton albo cachyos.")
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
            raise FileNotFoundError(f"Brak wydań: {raw}")
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
        raise FileNotFoundError(f"Nie znaleziono Protona: {raw}")
    names = ", ".join(item.name for item in unique.values())
    raise ValueError(f"Kilka pasujących wydań, podaj dokładniejszą nazwę: {names}")


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
                        raise InterruptedError("Anulowano pobieranie.")
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
            raise RuntimeError("Puste archiwum Protona.")
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if target != dest and dest not in target.parents:
                raise RuntimeError(f"Podejrzana ścieżka w archiwum: {member.name}")
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)
    top = names[0].split("/")[0]
    if not top or top in {".", ".."}:
        raise RuntimeError("Archiwum Protona ma dziwny katalog główny.")
    return top


def install_proton_release(
    release: ProtonRelease,
    progress=None,
    cancel=None,
    root: Path | None = None,
) -> Path:
    if not release.download_url:
        raise RuntimeError(f"Brak pliku do pobrania dla {release.name}.")
    dest_dir = compatibilitytools_dir(root)
    target = dest_dir / release.name
    if target.exists():
        raise FileExistsError(f"Już zainstalowane: {release.name}")
    cache = Path.home() / ".cache" / "perun"
    cache.mkdir(parents=True, exist_ok=True)
    filename = Path(urllib.parse.urlparse(release.download_url).path).name
    archive = cache / filename

    def report(fraction: float, phase: str = "download") -> None:
        if progress is None:
            return
        if phase == "download":
            progress(fraction * 0.92, "Pobieram…")
        elif phase == "extract":
            progress(0.92 + fraction * 0.08, "Rozpakowuję…")
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
                raise RuntimeError(
                    f"Suma SHA512 się nie zgadza dla {release.name} — przerwano."
                )
        if cancel is not None and cancel[0]:
            raise InterruptedError("Anulowano pobieranie.")
        report(0.0, "extract")
        top = _safe_extract_tar(archive, dest_dir)
        extracted = dest_dir / top
        if not extracted.is_dir():
            raise RuntimeError("Rozpakowanie nie utworzyło katalogu Protona.")
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
        raise ValueError(
            f"Tego Protona nie można usunąć z Peruna: {tool.display}. "
            "Oficjalne wersje Steam zostaw w kliencie Steam."
        )
    assert tool.install_path is not None
    shutil.rmtree(tool.install_path)


def games_using_tool(name: str, games: list[Game] | None = None) -> list[Game]:
    games = games if games is not None else list_games()
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
            )
        )
    return games


def list_games(root: Path | None = None, include_tools: bool = False) -> list[Game]:
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
                )
            )
    for shortcut in _list_shortcuts(root, compat, account):
        if shortcut.appid in seen:
            continue
        seen.add(shortcut.appid)
        games.append(shortcut)
    games.sort(key=lambda g: (-g.last_played, g.name.lower()))
    return games


def resolve_game(query: str, games: list[Game] | None = None) -> list[Game]:
    games = games if games is not None else list_games()
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
    raise TimeoutError("Steam nie zamknął się w oczekiwanym czasie.")


def start_steam() -> None:
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


def _write_localconfig_launch_options(root: Path, appid: str, options: str) -> Path:
    path = localconfig_path(root)
    if path is None or not path.is_file():
        raise FileNotFoundError("Nie znaleziono localconfig.vdf.")
    _backup_file(path, "localconfig")
    data = load_vdf(path)
    apps = _vdf_ensure(
        data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps"
    )
    app = apps.get(appid)
    if not isinstance(app, dict):
        app = {}
        apps[appid] = app
    options = (options or "").strip()
    if options:
        app["LaunchOptions"] = options
    else:
        app.pop("LaunchOptions", None)
    buf = io.StringIO()
    vdf.dump(data, buf, pretty=True)
    _atomic_write_text(path, buf.getvalue())
    return path


def _write_shortcut_launch_options(root: Path, index: str, options: str) -> Path:
    path = shortcuts_path(root)
    if path is None or not path.is_file():
        raise FileNotFoundError("Nie znaleziono shortcuts.vdf.")
    if vdf is None:
        raise RuntimeError("Brak pakietu python-vdf.")
    _backup_file(path, "shortcuts")
    data = vdf.binary_loads(path.read_bytes())
    shortcuts = data.get("shortcuts")
    if not isinstance(shortcuts, dict) or index not in shortcuts:
        raise FileNotFoundError(f"Nie znaleziono skrótu o indeksie {index}.")
    entry = shortcuts[index]
    if not isinstance(entry, dict):
        raise FileNotFoundError(f"Uszkodzony skrót o indeksie {index}.")
    entry["LaunchOptions"] = (options or "").strip()
    _atomic_write_bytes(path, vdf.binary_dumps(data))
    return path


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


def _write_compat_tool(root: Path, appid: str, tool_name: str) -> Path:
    path = config_vdf_path(root)
    if not path.is_file():
        raise FileNotFoundError("Nie znaleziono config.vdf.")
    _backup_file(path, "config")
    data = load_vdf(path)
    mapping = _vdf_ensure(
        data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping"
    )
    if not tool_name:
        _vdf_pop_ci(mapping, appid)
    else:
        entry = None
        entry_key = appid
        for ck in mapping:
            if str(ck) == appid:
                entry = mapping[ck]
                entry_key = ck
                break
        if not isinstance(entry, dict):
            entry = {}
            mapping[entry_key] = entry
        _vdf_set_ci(entry, "name", tool_name)
        if not any(str(k).lower() == "config" for k in entry):
            entry["config"] = ""
        if not any(str(k).lower() == "priority" for k in entry):
            entry["priority"] = "250"
    buf = io.StringIO()
    vdf.dump(data, buf, pretty=True)
    _atomic_write_text(path, buf.getvalue())
    return path


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
        raise FileNotFoundError("Nie znaleziono instalacji Steam.")
    was_running = is_steam_running()
    if was_running and close_steam:
        shutdown_steam()
    elif was_running and not close_steam:
        raise RuntimeError(
            "Steam jest uruchomiony i nadpisze pliki konfiguracji przy wyjściu. "
            "Zamknij Steam albo użyj zapisu z automatycznym zamknięciem."
        )

    if launch_options is not UNCHANGED:
        options = str(launch_options or "").strip()
        if game.is_shortcut:
            if not game.shortcut_index:
                raise FileNotFoundError("Skrót nie ma indeksu w shortcuts.vdf.")
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
        raise FileNotFoundError("Nie znaleziono pliku konfiguracji Steam.")
    return path


# --- CLI --------------------------------------------------------------------

def _print_games(games: list[Game]) -> None:
    if not games:
        print("Brak zainstalowanych gier.")
        return
    width = max(len(g.name) for g in games)
    for game in games:
        opts = game.launch_options or "—"
        kind = "spoza Steam" if game.is_shortcut else "Steam"
        proton = game.compat_tool or "domyślny"
        print(f"{game.appid:>10}  {game.name:<{width}}  [{kind}]  {proton}  {opts}")


def _pick_one(query: str) -> Game:
    matches = resolve_game(query)
    if not matches:
        raise SystemExit(f"Nie znaleziono gry: {query}")
    if len(matches) > 1:
        print("Kilka pasujących gier, podaj dokładniejszą nazwę albo AppID:")
        _print_games(matches)
        raise SystemExit(2)
    return matches[0]


def cmd_list(_: argparse.Namespace) -> int:
    if steam_root() is None:
        print("Nie znaleziono Steam.", file=sys.stderr)
        return 1
    _print_games(list_games())
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    game = _pick_one(args.game)
    kind = "spoza Steam" if game.is_shortcut else "Steam"
    print(f"{game.name} ({game.appid}, {kind})")
    print(f"Proton: {game.compat_tool or 'domyślny / Steam Play'}")
    print(game.launch_options or "(brak opcji)")
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
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    print(f"Zapisano {game.name}: {options or '(wyczyszczone)'}")
    return 0


def cmd_tools(_: argparse.Namespace) -> int:
    tools = list_compat_tools()
    default = default_compat_tool()
    print(f"domyślny  {default or '(brak globalnego Steam Play)'}")
    if not tools:
        print("Nie znaleziono zainstalowanych wersji Protona.")
        return 0
    width = max(len(t.name) for t in tools)
    for tool in tools:
        kind = "Steam" if tool.official else "własny"
        extra = f"  ({tool.display})" if tool.display != tool.name else ""
        print(f"{tool.name:<{width}}  [{kind}]{extra}")
    return 0


def cmd_proton(args: argparse.Namespace) -> int:
    game = _pick_one(args.game)
    if args.tool is None:
        print(f"{game.name} ({game.appid})")
        print(game.compat_tool or "domyślny / Steam Play")
        return 0
    raw = args.tool.strip()
    if raw.lower() in {"default", "domyślny", "domyslny", "-"}:
        tool_name = ""
        label = "domyślny / Steam Play"
    else:
        tools = list_compat_tools()
        matches = [
            t
            for t in tools
            if t.name.lower() == raw.lower() or t.display.lower() == raw.lower()
        ]
        if not matches:
            matches = [
                t
                for t in tools
                if raw.lower() in t.name.lower() or raw.lower() in t.display.lower()
            ]
        if len(matches) != 1:
            if not matches:
                print(f"Nie znaleziono Protona: {raw}", file=sys.stderr)
            else:
                print("Kilka pasujących wersji, podaj dokładniejszą nazwę:", file=sys.stderr)
                for t in matches:
                    print(f"  {t.name}  ({t.display})", file=sys.stderr)
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
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    print(f"Zapisano Proton dla {game.name}: {label}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    query = (args.version or "").strip()
    if not query:
        try:
            for flavor in PROTON_FLAVORS:
                print(f"# {flavor['name']} — {flavor['blurb']}")
                releases = fetch_proton_releases(flavor["id"])
                if not releases:
                    print("  (brak wydań)")
                    continue
                for item in releases:
                    mark = "  [zainstalowany]" if item.installed else ""
                    print(
                        f"  {item.name:<42}  {item.date}  {format_bytes(item.size)}{mark}"
                    )
        except Exception as exc:
            print(f"Błąd: {exc}", file=sys.stderr)
            return 1
        print("\nZainstaluj:  perun install GE-Proton")
        print("             perun install cachyos")
        print("             perun install GE-Proton11-6")
        return 0
    try:
        release = resolve_proton_release(query)
    except Exception as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    if release.installed:
        print(f"Już zainstalowane: {release.name}")
        return 0
    print(f"Pobieram {release.name} ({format_bytes(release.size)})…")
    last = [-5]

    def progress(fraction: float, phase: str) -> None:
        pct = int(fraction * 100)
        if phase.startswith("Rozpak"):
            if last[0] < 100:
                print("\nRozpakowuję…")
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
        print(f"\nBłąd: {exc}", file=sys.stderr)
        return 1
    print(f"\nZainstalowano {path.name}")
    print("Uruchom Steam ponownie, żeby wersja pojawiła się w kliencie Steam.")
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
            print(f"Nie znaleziono własnego Protona do usunięcia: {query}", file=sys.stderr)
        else:
            print("Kilka pasujących, podaj dokładniejszą nazwę:", file=sys.stderr)
            for tool in matches:
                print(f"  {tool.name}", file=sys.stderr)
        return 1
    tool = matches[0]
    users = games_using_tool(tool.name)
    default = default_compat_tool()
    if users or default == tool.name:
        names = ", ".join(game.name for game in users[:6])
        extra = " (i inne)" if len(users) > 6 else ""
        bits = []
        if default == tool.name:
            bits.append("to globalny Steam Play")
        if names:
            bits.append(f"używa: {names}{extra}")
        print("Uwaga: " + "; ".join(bits) + ".", file=sys.stderr)
    try:
        uninstall_compat_tool(tool)
    except Exception as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    print(f"Usunięto {tool.name}")
    print("Uruchom Steam ponownie, żeby zniknął z listy zgodności.")
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
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
    print("OK" if failed == 0 else f"{failed} failed")
    return 0 if failed == 0 else 1


# --- GUI --------------------------------------------------------------------

def cmd_gui(_: argparse.Namespace) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from threading import Thread

    from gi.repository import Adw, Gdk, Gio, GLib, Gtk

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

            self.toast_overlay = Adw.ToastOverlay()
            self.set_content(self.toast_overlay)

            toolbar = Adw.ToolbarView()
            self.toast_overlay.set_child(toolbar)

            header = Adw.HeaderBar()
            title = Adw.WindowTitle(title=APP_NAME, subtitle="opcje uruchamiania Steam")
            header.set_title_widget(title)
            refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            refresh_btn.set_tooltip_text("Odśwież listę gier")
            refresh_btn.connect("clicked", lambda *_: self.reload())
            header.pack_start(refresh_btn)
            proton_mgr_btn = Gtk.Button.new_from_icon_name("folder-download-symbolic")
            proton_mgr_btn.set_tooltip_text("Zainstaluj albo usuń wersje Protona")
            proton_mgr_btn.connect("clicked", lambda *_: self._open_proton_manager())
            header.pack_end(proton_mgr_btn)
            toolbar.add_top_bar(header)

            self.banner = Adw.Banner()
            self.banner.set_title(
                "Steam jest uruchomiony. Przy zapisie zostanie chwilowo zamknięty, "
                "żeby nie nadpisał zmian."
            )
            toolbar.add_top_bar(self.banner)

            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            paned.set_shrink_start_child(False)
            paned.set_shrink_end_child(False)
            paned.set_wide_handle(True)
            paned.set_position(340)
            toolbar.set_content(paned)

            # lewa kolumna
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            search = Gtk.SearchEntry()
            search.set_placeholder_text("Szukaj gry…")
            search.set_margin_start(10)
            search.set_margin_end(10)
            search.set_margin_top(8)
            search.set_margin_bottom(8)
            search.connect("search-changed", self._on_search)
            left.append(search)

            scroller = Gtk.ScrolledWindow()
            scroller.set_vexpand(True)
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.listbox = Gtk.ListBox()
            self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.listbox.add_css_class("navigation-sidebar")
            self.listbox.set_filter_func(self._filter_row)
            self.listbox.set_placeholder(Gtk.Label(label="Brak gier"))
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

            self.empty = Adw.StatusPage(
                icon_name="input-gaming-symbolic",
                title="Wybierz grę",
                description="Z listy po lewej wybierz grę, której chcesz zmienić opcje uruchamiania.",
            )
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
            self.game_meta = Gtk.Label(xalign=0)
            self.game_meta.add_css_class("dim-label")
            titles.append(self.game_title)
            titles.append(self.game_meta)
            head.append(titles)
            play = Gtk.Button(label="Uruchom")
            play.add_css_class("suggested-action")
            play.set_valign(Gtk.Align.CENTER)
            play.connect("clicked", self._on_play)
            head.append(play)
            self.editor.append(head)

            proton_group = Adw.PreferencesGroup(
                title="Proton",
                description="To samo co w Steam: Właściwości → Zgodność. Dla Battle.net / Diablo 4 wybierz GE-Proton albo CachyOS.",
            )
            self.proton_row = Adw.ComboRow(
                title="Wersja Protona",
                subtitle="Warstwa zgodności Steam Play. Domyślna to ustawienie globalne z Steam Play.",
            )
            self.proton_row.set_model(Gtk.StringList.new(["Domyślna (Steam Play)"]))
            self.proton_row._values = [""]  # type: ignore[attr-defined]
            self.proton_row.connect("notify::selected", self._on_proton_changed)
            proton_group.add(self.proton_row)
            manage = Adw.ActionRow(
                title="Doinstaluj inną wersję",
                subtitle="GE-Proton i Proton-CachyOS z GitHuba — tak jak w ProtonUp-Qt.",
            )
            manage.set_activatable(True)
            manage.add_suffix(Gtk.Image.new_from_icon_name("folder-download-symbolic"))
            manage.connect("activated", lambda *_: self._open_proton_manager())
            proton_group.add(manage)
            self.editor.append(proton_group)

            toggles = Adw.PreferencesGroup(
                title="Nakładki przy starcie",
                description="Owija komendę gry. Steam wstawia właściwy plik gry w miejsce %command%.",
            )
            self.sw_gamemode = Adw.SwitchRow(
                title="GameMode — więcej klatek",
                subtitle="Prosi system o wyższy priorytet CPU/GPU na czas gry. Dopisuje: gamemoderun",
            )
            self.sw_gamemode.connect("notify::active", self._on_toggle)
            toggles.add(self.sw_gamemode)

            self.mango_row = Adw.ExpanderRow(
                title="MangoHud — nakładka FPS",
                subtitle="W grze: prawy Shift+F12 pokazuje/chowa HUD, lewy Shift+F1 przełącza limit FPS.",
            )
            self.mango_row.set_show_enable_switch(True)
            self.mango_row.set_expanded(False)
            self.mango_row.connect("notify::enable-expansion", self._on_mango_master)

            self.mango_position = self._make_combo(
                "Pozycja na ekranie",
                "Róg albo krawędź, w której stoi nakładka.",
                MANGO_POSITIONS,
            )
            self.mango_fps_limit = self._make_combo(
                "Limit FPS",
                "Na 180 Hz bez limitu 130 klatek rwie obraz. 120 trzyma równy czas klatki (także w DX12 / Diablo 4).",
                MANGO_FPS_LIMITS,
            )
            self.mango_font = self._make_combo(
                "Wielkość czcionki",
                "Na ultrawide zwykle 24–28 px jest wygodne.",
                MANGO_FONT_SIZES,
            )
            self.sw_mango_dlsym = Adw.SwitchRow(
                title="OpenGL (--dlsym)",
                subtitle="Potrzebne w niektórych natywnych grach OpenGL. Dopisuje: mangohud --dlsym",
            )
            for combo in (self.mango_position, self.mango_fps_limit, self.mango_font):
                combo.connect("notify::selected", self._on_mango_changed)
                self.mango_row.add_row(combo)
            self.sw_mango_dlsym.connect("notify::active", self._on_mango_changed)
            self.mango_row.add_row(self.sw_mango_dlsym)

            self.mango_flags: dict[str, Adw.SwitchRow] = {}
            for key, title, tip in MANGO_FLAG_OPTIONS:
                row = Adw.SwitchRow(title=title, subtitle=tip)
                row.connect("notify::active", self._on_mango_changed)
                self.mango_flags[key] = row
                self.mango_row.add_row(row)

            toggles.add(self.mango_row)
            self.editor.append(toggles)

            add_icon = "list-add-symbolic"
            for group_title, group_desc, items in PRESET_GROUPS:
                group = Adw.PreferencesGroup(title=group_title, description=group_desc)
                for label, value, tip in items:
                    row = Adw.ActionRow(title=label, subtitle=tip)
                    row.set_activatable(True)
                    row.set_tooltip_text(f"Dopisz do komendy: {value}")
                    row.add_suffix(Gtk.Image.new_from_icon_name(add_icon))
                    row.connect("activated", self._on_preset, value)
                    group.add(row)
                self.editor.append(group)

            cmd_group = Adw.PreferencesGroup(
                title="Pełna komenda",
                description="To samo pole co w Steam: PPM na grę → Właściwości → Opcje uruchamiania. Przyciski powyżej ją składają, tu możesz poprawić ręcznie.",
            )
            self.command = Adw.EntryRow(title="Opcje")
            self.command.set_tooltip_text(
                "np. MANGOHUD_CONFIG=gpu_temp,position=top-right gamemoderun mangohud %command%"
            )
            self.command.connect("changed", self._on_command_changed)
            cmd_group.add(self.command)
            self.editor.append(cmd_group)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            clear_btn = Gtk.Button(label="Wyczyść")
            clear_btn.connect("clicked", self._on_clear)
            buttons.append(clear_btn)
            copy_btn = Gtk.Button(label="Kopiuj")
            copy_btn.connect("clicked", self._on_copy)
            buttons.append(copy_btn)
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            buttons.append(spacer)
            self.save_btn = Gtk.Button(label="Zapisz")
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
                self.games = list_games()
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
                self.empty.set_title("Nie znaleziono Steam")
                self.empty.set_description(
                    "Zainstaluj Steam albo uruchom go raz, żeby powstał katalog ~/.local/share/Steam."
                )

        def _fill_list(self, selected_id: str | None) -> None:
            while (child := self.listbox.get_first_child()) is not None:
                self.listbox.remove(child)
            pick = None
            for game in self.games:
                row = Adw.ActionRow(title=game.name)
                if game.is_shortcut:
                    sub = game.launch_options or "brak opcji"
                    row.set_subtitle(f"spoza Steam · {sub}")
                else:
                    row.set_subtitle(game.launch_options or "brak opcji")
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
            last = (
                datetime.fromtimestamp(game.last_played).strftime("%Y-%m-%d %H:%M")
                if game.last_played
                else "nigdy"
            )
            proton = compat_display(game.compat_tool, self._proton_tools)
            origin = "spoza Steam" if game.is_shortcut else "Steam"
            self.game_meta.set_text(
                f"{origin}  ·  AppID {game.appid}  ·  Proton: {proton}  ·  ostatnio {last}"
            )
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
                f"Domyślna ({self._default_proton})"
                if self._default_proton
                else "Domyślna (Steam Play)"
            )
            pairs: list[tuple[str, str]] = [("", default_label)]
            seen = {""}
            for tool in self._proton_tools:
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                pairs.append((tool.name, tool.display))
            if current and current not in seen:
                pairs.append((current, current.replace("_", " ")))
            labels = [label for _, label in pairs]
            values = [value for value, _ in pairs]
            self.proton_row.set_model(Gtk.StringList.new(labels))
            self.proton_row._values = values  # type: ignore[attr-defined]
            self._combo_set(self.proton_row, current or "")

        def _make_combo(
            self, title: str, subtitle: str, pairs: list[tuple[str, str]]
        ) -> Adw.ComboRow:
            row = Adw.ComboRow(title=title, subtitle=subtitle)
            row.set_model(Gtk.StringList.new([label for _, label in pairs]))
            row._values = [value for value, _ in pairs]  # type: ignore[attr-defined]
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
            self.sw_gamemode.set_active(parsed.gamemode)
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

        def _on_toggle(self, row: Adw.SwitchRow, _pspec=None) -> None:
            if self._syncing or self.selected is None:
                return
            updated = toggle_token(
                self.command.get_text(), "gamemoderun", row.get_active()
            )
            self._write_launch(parse_launch(updated))

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
                self.status.set_text("Zmiany niezapisane.")
            else:
                self._set_status_idle()

        def _set_status_idle(self) -> None:
            if is_steam_running():
                self.status.set_text(
                    "Zapis zamknie Steam na chwilę, zapisze opcje i Protona, potem uruchomi Steam ponownie."
                )
            else:
                self.status.set_text(
                    "Steam jest wyłączony — zapis trafi od razu do plików konfiguracji."
                )

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
            self.toast("Skopiowano opcje uruchamiania")

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
            self.toast(f"Uruchamiam {self.selected.name}")

        def _on_save(self, *_args) -> None:
            if self.selected is None:
                return
            options = self.command.get_text().strip()
            proton = self._combo_get(self.proton_row)
            game = self.selected
            name = game.name
            self.save_btn.set_sensitive(False)
            self.status.set_text("Zapisuję…")
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
                        self.toast("Nie udało się zapisać")
                        dialog = Adw.AlertDialog(
                            heading="Nie zapisano",
                            body=err,
                        )
                        dialog.add_response("ok", "OK")
                        dialog.present(self)
                        return
                    self.toast(f"Zapisano opcje: {name}")
                    self.reload()
                    # przywróć wybór i treść (reload czyta już nowy plik)
                    if close:
                        self.status.set_text("Zapisane. Steam uruchamia się ponownie.")
                    else:
                        self.status.set_text("Zapisane.")

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _open_proton_manager(self) -> None:
            if self._proton_win is not None:
                self._proton_win.present()
                return
            win = Adw.Window(title="Wersje Protona")
            win.set_transient_for(self)
            win.set_modal(True)
            win.set_default_size(560, 620)
            win.connect("close-request", self._on_proton_manager_close)

            toolbar = Adw.ToolbarView()
            win.set_content(toolbar)
            header = Adw.HeaderBar()
            header.set_title_widget(
                Adw.WindowTitle(
                    title="Wersje Protona",
                    subtitle="GE-Proton i Proton-CachyOS → compatibilitytools.d",
                )
            )
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

            self._pm_installed_group = Adw.PreferencesGroup(
                title="Zainstalowane własne wersje",
                description="Oficjalny Proton Steam (Experimental, Hotfix) zostaw w kliencie Steam.",
            )
            self._pm_installed_rows: list[Gtk.Widget] = []
            column.append(self._pm_installed_group)

            add_group = Adw.PreferencesGroup(
                title="Doinstaluj z GitHuba",
                description="Po instalacji uruchom Steam ponownie, żeby nowa wersja weszła na listę zgodności.",
            )
            self._pm_flavor = Adw.ComboRow(
                title="Rodzaj",
                subtitle=PROTON_FLAVORS[0]["blurb"],
            )
            self._pm_flavor.set_model(
                Gtk.StringList.new([item["name"] for item in PROTON_FLAVORS])
            )
            self._pm_flavor._values = [item["id"] for item in PROTON_FLAVORS]  # type: ignore[attr-defined]
            self._pm_flavor.connect("notify::selected", self._pm_on_flavor)
            add_group.add(self._pm_flavor)

            self._pm_version = Adw.ComboRow(
                title="Wydanie",
                subtitle="Pobieram listę z GitHuba…",
            )
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
            self._pm_status.set_text("Wybierz wydanie i zainstaluj.")
            column.append(self._pm_status)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self._pm_cancel_btn = Gtk.Button(label="Anuluj")
            self._pm_cancel_btn.set_sensitive(False)
            self._pm_cancel_btn.connect("clicked", self._pm_on_cancel)
            buttons.append(self._pm_cancel_btn)
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            buttons.append(spacer)
            self._pm_install_btn = Gtk.Button(label="Zainstaluj")
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
            self._proton_win = None
            return False

        def _pm_fill_installed(self) -> None:
            for row in self._pm_installed_rows:
                self._pm_installed_group.remove(row)
            self._pm_installed_rows = []
            tools = [tool for tool in list_compat_tools() if tool_is_removable(tool)]
            if not tools:
                row = Adw.ActionRow(
                    title="Nie ma jeszcze własnych wersji",
                    subtitle="Zainstaluj GE-Proton albo Proton-CachyOS poniżej.",
                )
                self._pm_installed_group.add(row)
                self._pm_installed_rows.append(row)
                return
            default = default_compat_tool()
            for tool in tools:
                users = games_using_tool(tool.name, self.games)
                bits = []
                if tool.name == default:
                    bits.append("domyślny Steam Play")
                if users:
                    bits.append(
                        ", ".join(game.name for game in users[:3])
                        + ("…" if len(users) > 3 else "")
                    )
                row = Adw.ActionRow(title=tool.display)
                row.set_subtitle("; ".join(bits) if bits else "nieprzypisany do gry")
                btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                btn.add_css_class("flat")
                btn.set_valign(Gtk.Align.CENTER)
                btn.set_tooltip_text(f"Usuń {tool.name}")
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
                self._pm_flavor.set_subtitle(flavor["blurb"])
            self._pm_load_versions()

        def _pm_load_versions(self) -> None:
            flavor_id = self._combo_get(self._pm_flavor) or PROTON_FLAVORS[0]["id"]
            self._pm_version.set_subtitle("Pobieram listę z GitHuba…")
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
                        self._pm_version.set_model(Gtk.StringList.new(["nie udało się pobrać listy"]))
                        self._pm_version._values = [""]  # type: ignore[attr-defined]
                        self._pm_version.set_subtitle(err)
                        self._pm_status.set_text(err)
                        self._pm_install_btn.set_sensitive(False)
                        return
                    self._pm_releases = releases
                    if not releases:
                        self._pm_version.set_model(Gtk.StringList.new(["brak wydań"]))
                        self._pm_version._values = [""]  # type: ignore[attr-defined]
                        self._pm_version.set_subtitle("GitHub nie zwrócił wydań.")
                        self._pm_install_btn.set_sensitive(False)
                        return
                    labels = []
                    values = []
                    for item in releases:
                        mark = " · zainstalowany" if item.installed else ""
                        labels.append(
                            f"{item.name}  ·  {format_bytes(item.size)}{mark}"
                        )
                        values.append(item.name)
                    self._pm_version.set_model(Gtk.StringList.new(labels))
                    self._pm_version._values = values  # type: ignore[attr-defined]
                    self._pm_version.set_selected(0)
                    self._pm_version.set_subtitle("Wybierz wydanie do pobrania.")
                    self._pm_install_btn.set_sensitive(True)
                    self._pm_status.set_text("Wybierz wydanie i zainstaluj.")

                GLib.idle_add(done)

            Thread(target=work, daemon=True).start()

        def _pm_selected_release(self) -> ProtonRelease | None:
            name = self._combo_get(self._pm_version)
            for item in self._pm_releases:
                if item.name == name:
                    return item
            return None

        def _pm_on_cancel(self, *_args) -> None:
            self._pm_cancel[0] = True
            self._pm_status.set_text("Anuluję…")

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
                self._pm_status.set_text(f"Już zainstalowane: {release.name}")
                return
            self._pm_cancel[0] = False
            self._pm_set_busy(True)
            self._pm_progress.set_fraction(0)
            self._pm_progress.set_text("0%")
            self._pm_status.set_text(f"Pobieram {release.name} ({format_bytes(release.size)})…")

            def progress(fraction: float, phase: str) -> None:
                def tick() -> None:
                    if self._proton_win is None:
                        return
                    self._pm_progress.set_fraction(max(0.0, min(fraction, 1.0)))
                    self._pm_progress.set_text(f"{int(fraction * 100)}%")
                    self._pm_status.set_text(f"{phase} {release.name}")

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
                        self.toast("Nie udało się zainstalować Protona")
                        return
                    name = path.name if path is not None else release.name
                    self._pm_status.set_text(
                        f"Zainstalowano {name}. Uruchom Steam ponownie, żeby wszedł na listę zgodności."
                    )
                    self.toast(f"Zainstalowano {name}")
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
            users = games_using_tool(tool.name, self.games)
            default = default_compat_tool()
            body = f"Katalog {tool.install_path} zostanie usunięty."
            if tool.name == default:
                body += " To obecnie globalny Proton Steam Play."
            if users:
                body += " Używają go: " + ", ".join(game.name for game in users[:8])
                if len(users) > 8:
                    body += "…"
            dialog = Adw.AlertDialog(
                heading=f"Usunąć {tool.display}?",
                body=body,
            )
            dialog.add_response("cancel", "Anuluj")
            dialog.add_response("delete", "Usuń")
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
                self.toast(f"Usunięto {tool.name}")
                self._pm_fill_installed()
                self._pm_load_versions()
                self.reload()

            dialog.connect("response", on_response)
            parent = self._proton_win or self
            dialog.present(parent)

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
        print("Brak python-vdf. Zainstaluj: pacman -S python-vdf", file=sys.stderr)
        return 1
    Adw.init()
    app = PerunApp()
    return app.run(None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perun",
        description="Perun — opcje uruchamiania i Proton dla gier Steam.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="Pokaż zainstalowane gry i ich opcje")
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="Pokaż opcje jednej gry")
    p_get.add_argument("game", help="Nazwa albo AppID")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="Ustaw opcje (zamyka Steam na czas zapisu)")
    p_set.add_argument("game", help="Nazwa albo AppID")
    p_set.add_argument("options", nargs="?", default="", help="Treść opcji; puste = wyczyść")
    p_set.add_argument(
        "--keep-steam",
        action="store_true",
        help="Nie zamykaj Steam (zmiana może zostać nadpisana)",
    )
    p_set.set_defaults(func=cmd_set)

    p_clear = sub.add_parser("clear", help="Wyczyść opcje gry")
    p_clear.add_argument("game")
    p_clear.add_argument("--keep-steam", action="store_true")
    p_clear.set_defaults(func=cmd_set, options="")

    p_tools = sub.add_parser("tools", help="Pokaż zainstalowane wersje Protona")
    p_tools.set_defaults(func=cmd_tools)

    p_proton = sub.add_parser("proton", help="Pokaż albo ustaw wersję Protona dla gry")
    p_proton.add_argument("game", help="Nazwa albo AppID")
    p_proton.add_argument(
        "tool",
        nargs="?",
        help="Nazwa Protona; 'default' = globalny Steam Play",
    )
    p_proton.add_argument("--keep-steam", action="store_true")
    p_proton.set_defaults(func=cmd_proton)

    p_install = sub.add_parser(
        "install",
        help="Doinstaluj GE-Proton albo Proton-CachyOS (bez nazwy = lista wydań)",
    )
    p_install.add_argument(
        "version",
        nargs="?",
        help="np. GE-Proton, cachyos, GE-Proton11-6",
    )
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="Usuń własną wersję Protona")
    p_uninstall.add_argument("version", help="Nazwa katalogu, np. GE-Proton11-5-x86_64")
    p_uninstall.set_defaults(func=cmd_uninstall)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "selftest":
        return cmd_selftest(argparse.Namespace())
    if not argv or argv[0] not in {
        "list",
        "get",
        "set",
        "clear",
        "tools",
        "proton",
        "install",
        "uninstall",
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
