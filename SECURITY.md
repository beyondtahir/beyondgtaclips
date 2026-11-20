# Security and privacy

Beyond GTA Clips runs on **your own computer**. This page lists everything it touches, so you
(or your IT person, or your AI assistant) can check it before installing.

## What it never does

- Never asks for, reads or stores passwords, logins, browser cookies or API keys.
- Never uploads your clips, your files or anything about you. It never posts for you.
- Never runs as administrator. Anything that installs software system-wide (ffmpeg, deno)
  is done through the official package manager, only after asking you.
- No tracking, no analytics, no accounts, no subscription.

## What it connects to

| Where | Why |
|---|---|
| YouTube, Twitch, Kick (public pages only) | search for streams, read public view counts and chat replay, download the audio and the few seconds of video it clips |
| pypi.org | install its Python packages, once, into a private folder |
| huggingface.co | download the Whisper speech models, once (~220 MB) |
| github.com (opencv_zoo) | download the face-finder model, once; its SHA-256 checksum is verified before use |

Age-restricted, subscriber-only and private videos are skipped: it only clips what anyone can
watch without logging in.

## What it writes on your computer

| Folder | What is inside |
|---|---|
| `~/.beyondgtaclips/` | its private Python environment and the speech and face models |
| `~/BeyondGTAClips/` | your finished clips, `POSTING.md` files, settings, and a cache of downloads (`prune --days 7` clears old ones) |
| the skill's own folder | nothing at run time |

To uninstall, delete those two folders and the skill folder.

## What it runs

`ffmpeg`, `ffprobe`, `yt-dlp` and, to pick moments, the AI assistant you already use:
`claude -p` (with only the Read tool, to look at frame images), `codex exec --sandbox read-only`,
or another assistant's CLI. With `--brain agent` your assistant answers the prompt files itself,
and with `--brain none` no AI is used at all.

## Prompt injection

Transcripts, stream titles and chat come from strangers. Every prompt marks them as data and
tells the AI to ignore any instruction inside them. Template slots are filled in one pass so a
transcript can't add its own instructions.

## Python packages

Installed into `~/.beyondgtaclips/venv` only, never into your system Python. Versions are kept
within tested major versions (`scripts/setup_env.py`). `yt-dlp` stays current because YouTube
changes often.

## Where it runs

On a Mac or Windows PC inside **Claude Code / the Claude desktop app** or **Codex (the ChatGPT
desktop app or the Codex CLI)**. It does **not** run in hosted cloud sandboxes such as the
ChatGPT website, ChatGPT Work "Skills" uploads or claude.ai: those can't run ffmpeg, keep files
or download streams, and their automatic safety scans can reject skills that download video.

## Reporting a problem

Open an issue on GitHub: https://github.com/beyondtahir/beyondgtaclips/issues
