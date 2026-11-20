#!/usr/bin/env python3
"""One-time setup for beyondgtaclips. Uses only the Python standard library, so it runs
before anything is installed. Safe to run again. Ends with the word READY.

    macOS / Linux / WSL:  python3 scripts/setup_env.py
    Windows:              python  scripts\\setup_env.py

Options:
    --system-python   use the Python you ran this with; no new interpreter is created.
                      Packages go into ~/.beyondgtaclips/packages, never into that Python.
                      Chosen automatically on Windows when Smart App Control is on.
    --venv            make a private Python env (the default everywhere else).
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
ENV_DIR = Path.home() / ".beyondgtaclips"
VENV = ENV_DIR / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
PKGS = ENV_DIR / "packages"                      # --system-python mode: packages live here
SYSTEM_CONF = ENV_DIR / "system-python.json"     # --system-python mode: which Python to use
MODELS = ENV_DIR / "models"
DATA = Path(os.environ.get("BEYONDGTACLIPS_HOME") or Path.home() / "BeyondGTAClips")
HERE = Path(__file__).resolve().parent
WINDOWS_GUIDE = "https://github.com/beyondtahir/beyondgtaclips/blob/main/WINDOWS.md"

# Tested versions. Each stays within its major version so an update can't change behaviour
# unexpectedly; yt-dlp has no ceiling because YouTube changes often and old versions stop working.
PACKAGES = ["faster-whisper>=1.2,<2", "opencv-python-headless>=4.9,<6", "pillow>=10,<14",
            "numpy>=1.26,<3", "yt-dlp[default]>=2026.10.26"]
DENO = "deno>=2.4,<3"    # official Deno build on PyPI (published by denoland/deno_pypi)
FACE_MODEL_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
                  "face_detection_yunet/face_detection_yunet_2023mar.onnx")
FACE_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
BLOCK_SIGNS = ("application control", "winerror 4551", "smart app control", "0x800711c7")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def good(msg):
    print(f"  [ok]   {msg}", flush=True)


def bad(msg, fix):
    print(f"  [MISSING] {msg}\n          fix: {fix}", flush=True)


def hint(mac, win, linux):
    return mac if IS_MAC else win if IS_WIN else linux


def smart_app_control():
    """'on', 'evaluation', 'off', or None when unknown / not Windows. Read-only registry check."""
    if not IS_WIN:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Policy") as key:
            value, _ = winreg.QueryValueEx(key, "VerifiedAndReputablePolicyState")
        return {0: "off", 1: "on", 2: "evaluation"}.get(value)
    except OSError:
        return None


def blocked_stop(what):
    print(f"""
  Windows blocked a file while {what}.
  This is Smart App Control (or your organisation's app control) protecting your PC.
  Please do NOT turn it off for this skill. Use the safe Windows setup instead, which keeps
  every protection on: open WINDOWS.md in the skill folder, or
  {WINDOWS_GUIDE}
""", flush=True)
    sys.exit(2)


def is_block(text):
    low = str(text).lower()
    return any(sign in low for sign in BLOCK_SIGNS)


def step(cmd, what, env=None):
    """Run one setup command. Shows its output only when it fails, and explains Windows blocks."""
    try:
        proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
    except OSError as exc:
        if is_block(exc) or getattr(exc, "winerror", None) == 4551:
            blocked_stop(what)
        raise
    if proc.returncode != 0:
        out = (proc.stdout + "\n" + proc.stderr).strip()
        if is_block(out):
            blocked_stop(what)
        print("\n".join(out.splitlines()[-25:]), flush=True)
        print(f"\n  Setup stopped while {what}. Fix the error above and run setup again.")
        sys.exit(1)
    return proc.stdout


def check_tools(sac):
    missing = False
    print("Checking tools")
    if not (3, 10) <= sys.version_info[:2] <= (3, 14):
        word = "too old" if sys.version_info < (3, 10) else "too new for the speech packages"
        bad(f"Python {sys.version.split()[0]} is {word} (works with 3.10 to 3.14, 3.12 recommended)",
            hint("brew install python@3.12, then run setup with python3.12",
                 "winget install Python.Python.3.12, then run setup with: py -3.12",
                 "sudo apt install python3 python3-venv"))
        missing = True
    else:
        good(f"Python {sys.version.split()[0]} ({sys.executable})")
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if not path:
            bad(f"{tool} not found",
                hint("brew install ffmpeg", "winget install Gyan.FFmpeg  (then open a new terminal)",
                     "sudo apt install ffmpeg"))
            missing = True
            continue
        try:
            subprocess.run([path, "-version"], capture_output=True, timeout=60)
        except OSError as exc:
            if is_block(exc) or getattr(exc, "winerror", None) == 4551:
                blocked_stop(f"starting {tool} ({path})")
            raise
        good(tool)
    if not (shutil.which("deno") or shutil.which("node") or shutil.which("bun")):
        if IS_WIN:
            bad("no JavaScript runtime (YouTube downloads need one)",
                "winget install OpenJS.NodeJS.LTS  (signed by the OpenJS Foundation; then open a new terminal)")
            missing = True
        else:
            print("  [note] no deno or node found: setup adds the official Deno to the private folder")
    else:
        good("JavaScript runtime (YouTube downloads need one)")
    brains = [b for b in ("claude", "codex", "kimi", "gemini", "cursor-agent", "opencode") if shutil.which(b)]
    if brains:
        good("AI CLI for picking moments: " + ", ".join(brains))
    else:
        print("  [note] no AI CLI on PATH: your assistant picks the moments (--brain agent), "
              "or no AI at all (--brain none)")
    if sac in ("on", "evaluation"):
        print(f"  [note] Windows Smart App Control is {sac}: using your own Python, no new interpreter")
    free = shutil.disk_usage(Path.home()).free / 1e9
    if free < 3:
        bad(f"only {free:.1f} GB free", "free up space: setup needs ~1 GB, clipping ~0.15 GB per stream hour")
        missing = True
    else:
        good(f"disk: {free:.0f} GB free")
    return not missing


def need_deno():
    return not IS_WIN and not (shutil.which("deno") or shutil.which("node") or shutil.which("bun"))


# ---- private env (default) -------------------------------------------------------------

def make_venv():
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    SYSTEM_CONF.unlink(missing_ok=True)
    if VENV_PY.exists():
        good("private Python env exists")
        return VENV_PY
    print("Creating a private Python env in ~/.beyondgtaclips (keeps your system Python clean)...")
    uv = None if IS_WIN else shutil.which("uv")    # on Windows: only ever copy the signed Python you have
    if uv:
        for version in ("3.12", "3.11", None):
            cmd = [uv, "venv", "-q", str(VENV)] + (["--python", version] if version else [])
            if subprocess.run(cmd).returncode == 0 and VENV_PY.exists():
                break
    if not VENV_PY.exists():
        step([sys.executable, "-m", "venv", str(VENV)], "creating the private Python env")
    good("private Python env created")
    return VENV_PY


def install_venv(py):
    print("Installing Python packages (Whisper, OpenCV, Pillow, yt-dlp)... this takes a minute")
    pkgs = PACKAGES + ([DENO] if need_deno() else [])
    uv = None if IS_WIN else shutil.which("uv")
    if uv:
        step([uv, "pip", "install", "-q", "--python", str(py), "-U", *pkgs], "installing packages")
    else:
        step([py, "-m", "pip", "install", "-q", "-U", "pip"], "updating pip")
        step([py, "-m", "pip", "install", "-q", "-U", *pkgs], "installing packages")
    good("Python packages")


# ---- your own Python (--system-python) --------------------------------------------------

def use_system_python():
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Using your own Python, no new interpreter: {sys.executable}")
    print("Installing Python packages into ~/.beyondgtaclips/packages (Whisper, OpenCV, Pillow, "
          "yt-dlp)... this takes a minute")
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode != 0:
        print("  This Python has no pip. Install Python from python.org or with "
              "'winget install Python.Python.3.12' and run setup with that one.")
        sys.exit(1)
    pkgs = PACKAGES + ([DENO] if need_deno() else [])
    step([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "--no-warn-script-location",
          "--target", str(PKGS), *pkgs], "installing packages")
    SYSTEM_CONF.write_text(json.dumps({"python": sys.executable, "packages": str(PKGS),
                                       "version": sys.version.split()[0]}, indent=2), encoding="utf-8")
    good("Python packages (in ~/.beyondgtaclips/packages; your Python itself is unchanged)")
    return Path(sys.executable)


def child_env():
    env = dict(os.environ)
    if SYSTEM_CONF.exists():
        env["PYTHONPATH"] = str(PKGS) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def self_test(py):
    """Load every native part once, so a Windows block shows up now with a clear message."""
    code = "import numpy, cv2, PIL.Image, av, ctranslate2, faster_whisper, yt_dlp; print('ok')"
    step([py, "-c", code], "loading the Python packages (numpy, OpenCV, Whisper)", env=child_env())
    good("packages load")


def download_models(py):
    print("Downloading Whisper speech models (tiny + base, ~220 MB, first time only)...")
    code = (
        "import sys\n"
        "from faster_whisper import WhisperModel\n"
        "for n in ('tiny', 'base'):\n"
        "    WhisperModel(n, device='cpu', compute_type='int8', download_root=sys.argv[1])\n"
    )
    (MODELS / "whisper").mkdir(parents=True, exist_ok=True)
    step([py, "-c", code, str(MODELS / "whisper")], "downloading the speech models", env=child_env())
    good("Whisper models (tiny = scanning the stream, base = captions)")
    face = MODELS / "face_yunet.onnx"
    if not _sha_ok(face):
        try:
            tmp = face.with_suffix(".part")
            urllib.request.urlretrieve(FACE_MODEL_URL, tmp)
            if _sha_ok(tmp):
                tmp.replace(face)
            else:
                tmp.unlink(missing_ok=True)
                print("  [note] the face model did not match its checksum, so it was not used; "
                      "a simpler face finder will be used")
        except Exception as exc:  # noqa: BLE001
            print(f"  [note] face model download failed ({exc}); a simpler face finder will be used")
    if _sha_ok(face):
        good("face finder (OpenCV YuNet, checksum verified)")


def _sha_ok(path):
    """True when the file exists and is exactly the published model."""
    import hashlib
    if not path.exists():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == FACE_MODEL_SHA256


def make_data_dir():
    DATA.mkdir(parents=True, exist_ok=True)
    watch = DATA / "watchlist.txt"
    if not watch.exists():
        shutil.copy(HERE.parent / "watchlist.txt", watch)
    good(f"output folder: {DATA}")
    good(f"watchlist: {watch}")


def main(argv):
    print("beyondgtaclips setup\n")
    sac = smart_app_control()
    if "--venv" in argv:
        system = False
    else:
        system = "--system-python" in argv or sac in ("on", "evaluation") or SYSTEM_CONF.exists()
    if not check_tools(sac):
        print("\nInstall the MISSING items above, open a new terminal, and run setup again.")
        sys.exit(1)
    if system:
        py = use_system_python()
    else:
        py = make_venv()
        install_venv(py)
    self_test(py)
    download_models(py)
    make_data_dir()
    launcher = HERE / "beyondgtaclips.py"
    cmd = "python" if IS_WIN else "python3"
    print(f"\nREADY. Try:  {cmd} \"{launcher}\" find")


if __name__ == "__main__":
    main(sys.argv[1:])
