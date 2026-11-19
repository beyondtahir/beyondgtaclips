# beyondgtaclips v1 — what changed from stream-clips

Built by Claude on 19 Nov 2026 from MiniMax's investigation (`OVERVIEW.md`, `DEVELOPER-SPEC.md`,
`REA-REPORT.md` in this folder). The original zip is kept untouched in `~/AI/_rea/stream-clips/`.

## Done

**Smart search (`find`)**
- ~13 YouTube searches per topic (every spelling × stream words + a "live now" search), merged.
- Junk filter: shorts, compilations, re-uploads, trailers, reviews, upcoming, too short, too old,
  already clipped (`~/BeyondGTAClips/clipped.json`).
- Detail lookups in batches until enough usable streams are found.
- Heat ranking: views/hour blended with total views (`recency`), live boost, like-ratio boost,
  trending-word boost, English preferred (YouTube language tag + title words).
- Trend radar: today's most viewed topic Shorts → view-weighted topic words; shown to the user and
  fed to the picker prompt. Cached 3 h.
- Every result prints its reason; `clip --pick 1,3` uses the last find.

**Works in every assistant**
- Brains: claude, codex (finds wrappers like `codex-fugu`), kimi, gemini, cursor, opencode,
  custom (`--brain-cmd`), agent (writes `AGENT_TASK.md`), none (no AI).
- `auto`: the host's CLI → any installed → none. A CLI that is signed out or broken switches to
  agent mode instead of failing.
- Nested calls run in a scratch folder (fixes REA bug B3).

**Gameplay first (sees the stream)**
- YouTube's storyboard (a tiny frame every ~10 s of the whole stream, ~1 MB) shows where the game
  is moving; waiting rooms, menus and just-chatting parts are skipped before anything is downloaded.
- Transcript lines on a still picture are marked `[STATIC SCREEN]`; the picker brief says the page
  posts gameplay only (chases, crashes, NPC madness, glitches, discoveries, cutscene twists).
- Every clip's real frames are checked (game motion); a static one is swapped for a backup moment.
- Search window asked from the user: `--within 24h|48h|week`, ranked by most views (`--rank hot`
  for views per hour).
- Hook card and News captions sit just under the gameplay, never over the game's own subtitles.

**Smart listening**
- Loudness is measured for the whole stream first; only the hottest `max_blocks` (8) 10-minute
  blocks are transcribed, ranked by volume spikes and chat bursts. 3 h of stream in ~1 min.
- `find` listens to 30 s of the top finished streams to detect the spoken language
  (YouTube rarely tags it) and ranks English first; live streams are listed separately.

**Picker**
- New editor brief: hook sentence with `*accent words*`, two A/B hooks, sticker title, news
  headline, style choice per clip, 5-7 hashtags, trending words, short vs long (story arc) rules.
- Prompt-injection guard + single-pass template fill + escaping (REA bugs B1, B2).
- No-AI picker from loudness, chat and talk density; fills gaps so a stream never yields zero clips.
- Speechless streams no longer crash (warning instead of error).

**Edit layer**
- All text drawn with Pillow (the Homebrew ffmpeg has no libass/freetype, so the old ASS
  captions could not work on this Mac): rich hook text with colour emoji, caption frames as an
  ffconcat image sequence, stickers, ticker, bubble mask.
- Five templates: hookcard, stack, bubble, cinematic, news (`scripts/bgt/templates.py`).
- Stack redesigned (2026-11-19, from a viral split-screen reel): streamer in a framed box on
  top at its own shape (no stretching), divider line with the title on leaning boxes, one big
  leaning caption word, the whole 16:9 stream screen below.
- True hooks (2026-11-20, from a real 4-clip run): the AI may only describe what happens in the clip
  (no invented backstory), names the streamer, keeps the streamer and the character (Lucia/Jason)
  apart, 8-16 words. Dashes in hooks, titles and captions become commas. The creator hashtag is
  built from the channel name and misspelt copies are dropped (`#kaicentlive` -> `#kaicenat`).
- Story check (2026-11-20, after clips that cut off the punchline or showed no gun): the picker
  marks the trigger and the payoff and cuts the whole scene (3-10 s before the trigger to just
  after the reaction). Each moment is downloaded with extra seconds, then the AI looks at contact
  sheets of its frames plus the words, re-cuts it, rewrites a hook that claims something not on
  screen, or drops it for a backup (`scripts/bgt/story.py`, setting `story_check`). Claude reads
  the images, Codex gets them with `-i`, agent mode via `STORY_TASK.md`, other brains judge
  from the words only, `--brain none` skips it.
- Clean captions (2026-11-20): slurs are fully starred (n****) and swears softened (f**k) in the
  on-screen captions only; the audio is never changed (`art.mask`, caption style `clean`). Hooks
  use the streamer's plain name ("Kai Cenat", not the channel's "Kai Cenat Live"). Agent mode
  writes one `STORY_TASK.md` for every clip; a brain that can't take images is retried with the
  words only. Each clip remembers the stream time of its footage (`at`) so reruns stay exact.
- README: new demo GIF (three story-checked Hook card clips + Stack and Bubble) and a
  before/after story check picture.
- Punch-in zooms on volume spikes, synthesised whoosh + pop, cinematic push-in and fades,
  platform safe zones, creator credit in every template.
- `--template all` renders every style per clip; `remake` re-renders with a new hook, title,
  headline, caption or template without downloading again.
- Check images per clip; SKILL.md tells the assistant to look at them and fix hooks.

**Other**
- Rename to beyondgtaclips (`~/BeyondGTAClips`, `~/.beyondgtaclips`, `BEYONDGTACLIPS_HOME`).
- `--length short|long`, `--clips` default 4, `--max-hours` listening cap (default 3).
- No shared mutable `opts` across threads (REA bug B4); `--cam` validated (B6); watchlist
  picks a creator's best recent match instead of stopping at the first stale one (B5).
- `prune` for the cache.

## Not done yet (next)

- Clipping streams while they are still live: YouTube refuses partial downloads of live
  streams. v1 says so clearly and `clip --find` picks finished streams.
- Visual scene detection as a third signal (MiniMax Phase 4).
- Cross-stream duplicate killer and the "judge" second pass.
- Montage mode (3-5 moments in one 60-90 s video).
- Free CC0 background music from Openverse (POSTING.md recommends a trending in-app sound instead).
- Optional Remotion renderer for spring-animated captions.
