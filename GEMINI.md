# beyondgtaclips (for Codex, Kimi, MiniMax and other agents)

Read `SKILL.md` in this folder and follow it exactly. Short version:

1. Ask "last 24h, 48h or 1 week?" and show `assets/styles.png`: "all 5 styles or which numbers?". Then `python3 scripts/beyondgtaclips.py find --within 48h` and show the ranked list with its reasons.
2. `python3 scripts/beyondgtaclips.py clip --pick 1,3 --styles all` (Codex CLI: `--brain auto`;
   any assistant without its own CLI: `--brain agent` and answer the prompt files).
3. Look at every image in `<folder>/checks/` and fix hooks that don't match the picture with
   `python3 scripts/beyondgtaclips.py remake "<folder>" --clip N --hook "..."`.
4. Hand over the folder and `POSTING.md`.
