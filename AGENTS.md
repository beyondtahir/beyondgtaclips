# beyondgtaclips (for Codex, Kimi, MiniMax and other agents)

Read `SKILL.md` in this folder and follow it exactly. It runs only on the user's own computer;
in a hosted cloud sandbox (ChatGPT website, ChatGPT Work Skills, claude.ai) do not install it,
tell the user to use the desktop app instead. `SECURITY.md` lists everything it touches.

Short version:

1. Ask three questions in one message: how many clips (default 4), how recent (24 hours,
   48 hours or 1 week; default 48 hours), which style (show `assets/styles.png`; default 1, Hook card).
2. `python3 scripts/beyondgtaclips.py find --within 48h --count 6` and show the top streams.
3. `python3 scripts/beyondgtaclips.py clip --pick 1,3 --total 4 --styles 1` (Codex: `--brain auto`;
   any assistant without its own CLI: `--brain agent`). In agent mode it stops twice: answer the
   prompt files listed in `AGENT_TASK.md`, then the frame-check prompts in `STORY_TASK.md` (open the
   images they list), and run the same command again each time.
4. Look at every image in `<folder>/checks/` and fix a hook that doesn't match the picture with
   `python3 scripts/beyondgtaclips.py remake "<folder>" --clip N --hook "..."`.
5. Hand over the folder and `POSTING.md`.
