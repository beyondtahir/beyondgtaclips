# Windows 11 with Smart App Control

**Keep Smart App Control on.** You never need to turn off Windows security for this skill,
and setup never asks you to.

## Why Windows may block it

Smart App Control only runs programs that are signed with a trusted certificate or that
Microsoft's cloud already knows are safe. It has no list of exceptions you can add to.

The skill needs ffmpeg (the video tool) and Python packages with compiled parts (NumPy,
OpenCV, Whisper). Many of those files are free open-source builds without a code-signing
certificate, so Smart App Control may block some of them. That is Smart App Control doing its
job, not a problem with your PC.

So there are two ways. **Way 1 always works with Smart App Control on.** Way 2 can work, but
Windows decides file by file whether it is allowed.

| | Way 1: WSL (recommended) | Way 2: straight on Windows |
|---|---|---|
| Smart App Control | stays on | stays on |
| Works for sure | yes | only if Windows allows every file |
| Setup time | about 15 minutes, once | about 10 minutes |
| Your clips | in a folder you can open from Windows | in your Windows home folder |

---

## Way 1: WSL (recommended)

WSL ("Windows Subsystem for Linux") is a free part of Windows, made and signed by Microsoft.
It runs a small Linux system inside Windows. Smart App Control checks Windows programs; the
Linux programs inside WSL are run by Microsoft's own WSL, so nothing is switched off or
bypassed. If your PC is managed by a company or school that does not allow WSL, ask your IT
team. Don't try to work around their rules.

**1. Turn on WSL.** Right-click **Start**, choose **Terminal (Admin)**, and paste:

```powershell
wsl --install -d Ubuntu
```

Restart the PC when it asks. Ubuntu opens and asks you to create a username and password.
This is a local account on your own PC, not an online account.

**2. Install the tools.** In the Ubuntu window, paste:

```bash
sudo apt update
```

```bash
sudo apt install -y python3 python3-venv python3-pip ffmpeg git fonts-dejavu fonts-noto-core fonts-noto-color-emoji
```

**3. Add the skill** to your assistant's skills folder inside Ubuntu (first line for Claude,
second for Codex):

```bash
git clone --depth 1 https://github.com/beyondtahir/beyondgtaclips ~/.claude/skills/beyondgtaclips
```

```bash
git clone --depth 1 https://github.com/beyondtahir/beyondgtaclips ~/.codex/skills/beyondgtaclips
```

**4. Set it up** (about 5 minutes, once). Use the folder from step 3:

```bash
python3 ~/.claude/skills/beyondgtaclips/scripts/setup_env.py
```

It makes a private Python folder, adds the official Deno (needed for YouTube), downloads the
speech models and ends with **READY**.

**5. Use your assistant inside Ubuntu.** Install Claude Code or the Codex CLI in the Ubuntu
window, following their official install pages, or use VS Code connected to WSL (see below).
Then say *"make GTA 6 clips"*.

**6. Find your clips.** They are saved in `~/BeyondGTAClips` inside Ubuntu. To open that folder
in Windows File Explorer, type `explorer.exe ~/BeyondGTAClips` in Ubuntu. To save them straight
into your Windows Videos folder instead, run this once (change `<you>` to your Windows user
name):

```bash
echo 'export BEYONDGTACLIPS_HOME="/mnt/c/Users/<you>/Videos/BeyondGTAClips"' >> ~/.bashrc
```

---

## Way 2: straight on Windows

**1. Install the tools** in PowerShell. These come from their official publishers through
winget:

```powershell
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Gyan.FFmpeg
```

Python (signed by the Python Software Foundation) and Node.js (signed by the OpenJS
Foundation) are signed programs. Close and reopen PowerShell afterwards.

**2. Add the skill** to `C:\Users\<you>\.claude\skills\beyondgtaclips` (Claude) or
`C:\Users\<you>\.codex\skills\beyondgtaclips` (Codex). Use `git clone --depth 1
https://github.com/beyondtahir/beyondgtaclips` or **Code > Download ZIP** on GitHub.

**3. Run setup** with the Python you just installed:

```powershell
py -3.12 "$HOME\.claude\skills\beyondgtaclips\scripts\setup_env.py" --system-python
```

(Setup also switches to this mode by itself when it sees Smart App Control is on.) In this mode
setup:

- uses **your own Python**: it does not create or download another `python.exe`;
- puts the packages in `C:\Users\<you>\.beyondgtaclips\packages` and leaves your Python unchanged;
- runs yt-dlp through your Python, so there is no extra `.exe`;
- uses Node.js, which is signed, for YouTube instead of Deno;
- loads every package once as a test, and checks that ffmpeg runs.

If Windows blocks anything, setup stops and tells you which file was blocked. Nothing is
changed, and no security setting is touched. In that case use **Way 1**.

`--system-python` works on any computer. Use `--venv` to go back to the private Python folder.

---

## Which Python versions work

| Python | |
|---|---|
| 3.12 | recommended, tested |
| 3.10, 3.11, 3.13, 3.14 | supported |
| 3.15 and newer | not yet: the speech package (onnxruntime) has no builds for it |
| 3.9 and older | too old |

The packages are installed at these versions: faster-whisper 1.x, OpenCV 4.9 or newer, NumPy
1.26 or 2.x, Pillow 10 or newer, and the newest yt-dlp. On Windows they need the 64-bit
Python, which is what `winget install Python.Python.3.12` installs.

## Which assistants work

| Assistant | |
|---|---|
| **Claude Code** / Claude desktop app | Windows or WSL |
| **Codex CLI** / ChatGPT desktop app with Codex | Windows or WSL |
| **GitHub Copilot agent mode** (VS Code) | Open the skill folder in VS Code. For WSL, connect VS Code to WSL first. Then ask Copilot to *"read AGENTS.md and make GTA 6 clips"*. Copilot runs the commands in its terminal and answers the skill's prompt files itself (`--brain agent`), so no other AI is needed. Not tested by us yet. |
| Websites (chatgpt.com, claude.ai, ChatGPT Work "Skills" upload) | won't work: they are cloud sandboxes |

Everything above still needs the local setup on your PC (ffmpeg, Python and the setup step).
The assistant only does the thinking and runs the commands.

## Still blocked?

Open an issue with the **Something went wrong** form and paste what setup printed:
https://github.com/beyondtahir/beyondgtaclips/issues/new/choose

Please don't paste passwords, keys or tokens.
