"""Who reads the transcript and picks the moments.

Works with every assistant, and with none:

  claude    Claude Code         claude -p                 (prompt on stdin)
  codex     ChatGPT Codex CLI   codex exec -              (also finds wrappers like codex-fugu)
  kimi      Kimi Code           kimi -p "<prompt>"
  gemini    Gemini CLI          gemini -p                 (prompt on stdin)
  cursor    Cursor agent        cursor-agent -p "<prompt>"
  opencode  OpenCode            opencode run "read <file>"
  custom    any other CLI       --brain-cmd "mycli --flag" (prompt on stdin)
  agent     the assistant running this skill answers the prompt files itself (MiniMax,
            Kimi, Codex app, Claude app, anything): no extra subscription, no nested call
  none      no AI at all: moments are picked from loudness, chat and scene changes

`auto` = the CLI of the assistant that launched us, else any installed one, else `none`.
Every nested call runs in a scratch folder and is told the transcript is data, not orders.
"""

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import Problem

ORDER = ("claude", "codex", "kimi", "gemini", "cursor", "opencode")
CHOICES = ("auto", *ORDER, "custom", "agent", "none")

BINARIES = {"claude": ["claude"], "codex": ["codex"], "kimi": ["kimi"], "gemini": ["gemini"],
            "cursor": ["cursor-agent"], "opencode": ["opencode"]}

# Environment variables these tools set for the commands they run.
HOST_HINTS = {
    "claude": ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"),
    "codex": ("CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_MANAGED_BY_NPM"),
    "gemini": ("GEMINI_CLI",),
    "opencode": ("OPENCODE", "OPENCODE_BIN_PATH"),
    "cursor": ("CURSOR_AGENT",),
}

TIMEOUT = 900


class NeedAgent(Exception):
    """Agent mode: some prompt files still need an answer file."""

    def __init__(self, waiting):
        super().__init__(f"{len(waiting)} part(s) waiting for answers")
        self.waiting = waiting


class SignedOut(Problem):
    """The brain CLI is installed but not logged in: stop instead of retrying every part."""


def binary(name):
    """Path of the CLI for a brain, or None. Codex is also found as codex-<wrapper>."""
    for exe in BINARIES.get(name, []):
        found = shutil.which(exe)
        if found:
            return found
    if name == "codex":
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            try:
                for f in sorted(Path(folder).glob("codex-*")):
                    if f.is_file() and os.access(f, os.X_OK) and "." not in f.name:
                        return str(f)
            except OSError:
                continue
    return None


def installed():
    return [n for n in ORDER if binary(n)]


def choose(wanted="auto", custom_cmd=None):
    if wanted == "custom":
        if not custom_cmd:
            raise Problem('--brain custom needs --brain-cmd "<command that reads a prompt on stdin>"')
        return "custom"
    if wanted in ("agent", "none"):
        return wanted
    if wanted and wanted != "auto":
        if not binary(wanted):
            raise Problem(f"--brain {wanted}: its command line is not installed or not on PATH. "
                          f"Use --brain agent to let the assistant you are talking to pick, "
                          f"or --brain none for no AI.")
        return wanted
    for name, hints in HOST_HINTS.items():
        if any(os.environ.get(h) for h in hints):
            if name == "codex":
                return "agent"     # inside Codex/ChatGPT the agent picks itself (sandbox-safe)
            return name if binary(name) else "agent"
    found = installed()
    return found[0] if found else "none"


def _child_env():
    env = dict(os.environ)
    env["NO_COLOR"] = "1"          # plain text replies, no colour codes
    return env


def _call(cmd, stdin_text=None, cwd=None):
    try:
        proc = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              env=_child_env(), cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        raise Problem(f"{Path(cmd[0]).name} did not answer within {TIMEOUT // 60} min") from exc
    except FileNotFoundError as exc:
        raise Problem(f"{cmd[0]} is not installed") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        text = " | ".join(detail[-4:])[:400]
        low = text.lower()
        if any(k in low for k in ("authenticate", "login", "log in", "oauth", "unauthorized",
                                  "api key", "credentials", "not logged", "could not locate",
                                  "nothing to launch", "command not found", "no such file")):
            raise SignedOut(f"the {Path(cmd[0]).name} CLI is not signed in or not working "
                            f"({text[:160]}). Sign in once in a terminal, or use --brain agent / "
                            f"--brain none.")
        raise Problem(f"{Path(cmd[0]).name} failed: " + text)
    return proc.stdout


def ask(brain, prompt, model=None, scratch: Path = None, custom_cmd=None, images=None):
    """Send one prompt, return the raw text reply. Always runs in a scratch folder.
    `images`: picture files the brain should look at (claude reads them, codex attaches them)."""
    scratch = Path(scratch or tempfile.gettempdir())
    run_dir = scratch / "brain-scratch"
    run_dir.mkdir(parents=True, exist_ok=True)
    cwd = str(run_dir)
    exe = binary(brain) if brain in BINARIES else None
    if brain == "claude":
        look = ["--allowedTools", "Read", "--add-dir", str(Path(images[0]).parent)] if images else []
        return _call([exe, "-p", *look, *(["--model", model] if model else [])], prompt, cwd=cwd)
    if brain == "codex":
        out = run_dir / f"codex_reply_{os.getpid()}_{id(prompt)}.txt"
        _call([exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
               "--color", "never", "--output-last-message", str(out),
               *(["-m", model] if model else []),
               *[x for img in (images or []) for x in ("-i", str(img))], "-"], prompt, cwd=cwd)
        try:
            return out.read_text(encoding="utf-8")
        finally:
            out.unlink(missing_ok=True)
    if brain == "kimi":
        return _call([exe, "-p", prompt, *(["-m", model] if model else [])], cwd=cwd)
    if brain == "gemini":
        return _call([exe, *(["-m", model] if model else []), "-p",
                      "Follow the instructions in the text above and reply with only the JSON array"],
                     prompt, cwd=cwd)
    if brain == "cursor":
        return _call([exe, "-p", "--output-format", "text", "--workspace", cwd,
                      *(["--model", model] if model else []), prompt], cwd=cwd)
    if brain == "opencode":
        task = run_dir / f"opencode_task_{os.getpid()}_{id(prompt)}.txt"
        task.write_text(prompt, encoding="utf-8")
        try:
            return _call([exe, "run", *(["-m", model] if model else []),
                          f"Read the file {task} and do exactly what it asks. "
                          f"Reply with only the JSON array it asks for"], cwd=cwd)
        finally:
            task.unlink(missing_ok=True)
    if brain == "custom":
        return _call(shlex.split(custom_cmd), prompt, cwd=cwd)
    raise Problem(f"unknown brain '{brain}'")
