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
VENV = Path.home() / ".beyondgtaclips" / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


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
        sys.exit(_run_quiet([str(VENV_PY), str(Path(__file__).resolve()), *args], env))

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ["PATH"] = str(VENV_PY.parent) + os.pathsep + os.environ.get("PATH", "")
    sys.path.insert(0, str(HERE))
    from bgt.cli import main as cli_main
    sys.exit(cli_main(args) or 0)


if __name__ == "__main__":
    main()
