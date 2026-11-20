#!/usr/bin/env python3
"""beyondgtaclips: long streams in, clean viral vertical clips out.

Run with any Python 3; it switches itself into the private env made by setup_env.py.

    beyondgtaclips.py setup
    beyondgtaclips.py doctor
    beyondgtaclips.py find  --topic "Valorant"
    beyondgtaclips.py clip  URL [URL ...] --topic "Valorant"
    beyondgtaclips.py clip  --find --topic "GTA 6" --count 5
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
ENV_DIR = Path.home() / ".beyondgtaclips"
VENV = ENV_DIR / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
SYSTEM_CONF = ENV_DIR / "system-python.json"   # setup --system-python: your own Python + packages folder
GUIDE = "https://github.com/beyondtahir/beyondgtaclips/blob/main/WINDOWS.md"


def system_python():
    """(python, packages folder) when setup chose your own Python, else None."""
    try:
        import json
        conf = json.loads(SYSTEM_CONF.read_text(encoding="utf-8"))
        return Path(conf["python"]), Path(conf["packages"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def blocked(exc):
    text = str(exc).lower()
    return getattr(exc, "winerror", None) == 4551 or "application control" in text


def blocked_stop(what):
    print(f"Windows blocked {what}. This is Smart App Control (or your organisation's app control).\n"
          f"Please do not turn it off. Use the safe Windows setup instead: {GUIDE}", file=sys.stderr)
    sys.exit(2)


def in_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


NOISE = ("is implemented in both", "One of the duplicates must be removed",
         "experimental MPS backend", "unauthenticated requests to the HF Hub")


def _run_quiet(cmd, env):
    """Run the real program, passing its error output through minus harmless library noise
    (a macOS duplicate-class notice from OpenCV + PyAV, Whisper speed tips)."""
    import threading
    proc = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE)

    def pump():
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace")
            if not any(n in line for n in NOISE):
                sys.stderr.write(line)
                sys.stderr.flush()

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        code = proc.wait()
    except KeyboardInterrupt:
        code = proc.wait()
    t.join(timeout=2)
    return code


def main():
    args = sys.argv[1:]
    if args[:1] == ["setup"]:
        sys.exit(subprocess.call([sys.executable, str(HERE / "setup_env.py"), *args[1:]]))
    own = system_python()
    if own and not in_venv():
        py, pkgs = own
        here_already = os.environ.get("BEYONDGTACLIPS_INNER") == "1"
        try:
            here_already = here_already or Path(sys.executable).resolve() == py.resolve()
        except OSError:
            pass
        if not here_already:
            env = dict(os.environ, BEYONDGTACLIPS_INNER="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            try:
                sys.exit(_run_quiet([str(py), str(Path(__file__).resolve()), *args], env))
            except OSError as exc:
                if blocked(exc):
                    blocked_stop(str(py))
                raise
        os.environ["PYTHONPATH"] = str(pkgs) + os.pathsep + os.environ.get("PYTHONPATH", "")
        os.environ["PATH"] = str(pkgs / "bin") + os.pathsep + os.environ.get("PATH", "")
        sys.path.insert(0, str(pkgs))
        return _inner(args)
    if not in_venv():
        if not VENV_PY.exists():
            print("beyondgtaclips is not set up yet. Run:\n  "
                  f"{'python' if IS_WIN else 'python3'} \"{HERE / 'setup_env.py'}\"", file=sys.stderr)
            sys.exit(1)
        env = dict(os.environ)
        bin_dir = str(VENV_PY.parent)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            sys.exit(_run_quiet([str(VENV_PY), str(Path(__file__).resolve()), *args], env))
        except OSError as exc:
            if blocked(exc):
                blocked_stop(f"the private Python ({VENV_PY})")
            raise
    os.environ["PATH"] = str(VENV_PY.parent) + os.pathsep + os.environ.get("PATH", "")
    return _inner(args)


def _inner(args):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(HERE))
    try:
        from bgt.cli import main as cli_main
    except ImportError as exc:
        if blocked(exc):
            blocked_stop("one of the Python packages (" + str(exc)[:120] + ")")
        raise
    sys.exit(cli_main(args) or 0)


if __name__ == "__main__":
    main()
