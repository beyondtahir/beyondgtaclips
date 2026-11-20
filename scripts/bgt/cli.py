"""Command line: find / clip / remake / doctor / prune."""

import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import brains, discover, pipeline, settings
from .common import CACHE, DATA, MODELS, Problem, has, need, read_json, say, write_json

AGENT_EXIT = 3
LAST_FIND = DATA / "last_find.json"


def _common(p):
    p.add_argument("--topic", help='what the clips are about (default "GTA 6")')
    p.add_argument("--keywords", help="extra comma-separated spellings a title may use")


def _window(p):
    p.add_argument("--within", choices=["24h", "48h", "week"],
                   help="only streams from the last 24 hours, 48 hours or week (default 48h)")
    p.add_argument("--rank", choices=["views", "hot"],
                   help="views = most viewed (default); hot = fastest growing (views per hour)")


def _look(p):
    p.add_argument("--template", "--styles", dest="template",
                   help="styles: all, auto (the AI picks per clip), numbers like 1,3 or names "
                        "(1 hookcard, 2 stack, 3 bubble, 4 cinematic, 5 news). See `styles`.")
    p.add_argument("--accent", help="accent colour as hex, e.g. FF3B3B")
    p.add_argument("--fast", action="store_true", help="hardware video encoding if available")


def parser():
    p = argparse.ArgumentParser(prog="beyondgtaclips",
                                description="Find the hottest streams, cut clean viral vertical clips.")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("find", help="rank the hottest streams for a topic right now")
    _common(f)
    f.add_argument("--count", type=int, default=10)
    _window(f)
    f.add_argument("--search", help="exact YouTube search words (skips the smart query list)")
    f.add_argument("--all", action="store_true", help="include streams you already clipped")

    c = sub.add_parser("clip", help="make clips from streams")
    _common(c)
    _look(c)
    c.add_argument("urls", nargs="*", help="stream / video links (YouTube, Twitch, Kick, ...)")
    c.add_argument("--find", action="store_true", help="find the hottest streams and clip them")
    c.add_argument("--pick", help="clip numbers from the last `find`, e.g. 1,3")
    c.add_argument("--count", type=int, help="with --find: how many streams (default 3, or from --total)")
    _window(c)
    c.add_argument("--search", help="with --find: exact YouTube search words")
    c.add_argument("--clips", type=int, help="clips per stream (default 4)")
    c.add_argument("--total", type=int, help="total clips wanted; spread over the streams")
    c.add_argument("--length", choices=list(settings.LENGTHS), help="short (20-45 s) or long (60-90 s)")
    c.add_argument("--focus", help='extra direction for the picker, e.g. "police chases and NPC chaos"')
    c.add_argument("--brain", default="auto", choices=list(brains.CHOICES),
                   help="who picks the moments (default: the assistant running this, else none)")
    c.add_argument("--brain-cmd", help='with --brain custom: a command that reads a prompt on stdin')
    c.add_argument("--model", help="model name for the brain CLI, e.g. sonnet")
    c.add_argument("--section", help='only part of the stream, "1:00:00-2:30:00"')
    c.add_argument("--new-only", action="store_true", help="only what is new since the last run (live)")
    c.add_argument("--cam", help="facecam box as fractions x,y,w,h (e.g. 0.75,0.0,0.25,0.3)")
    c.add_argument("--min", dest="min_len", type=int, help="shortest clip, seconds")
    c.add_argument("--max", dest="max_len", type=int, help="longest clip, seconds")
    c.add_argument("--max-hours", type=float, help="listen to at most this many hours (default 3)")
    c.add_argument("--language", help="speech language code, e.g. en, hi, es (default: detect)")
    c.add_argument("--parallel", type=int, default=2, help="streams processed at once")
    c.add_argument("--repick", action="store_true", help="pick moments again (keeps downloads)")
    c.add_argument("--keep-audio", action="store_true", help="keep the stream audio afterwards")

    r = sub.add_parser("remake", help="re-render finished clips: new hook, title or template")
    _look(r)
    r.add_argument("folder", help="a clip folder (the one with POSTING.md)")
    r.add_argument("--clip", type=int, action="append", help="only this clip number (repeatable)")
    r.add_argument("--hook", help="new hook sentence; *stars* mark accent words")
    r.add_argument("--title", help="new sticker title")
    r.add_argument("--headline", help="new news/cinematic headline")
    r.add_argument("--caption", help="new post caption")

    pr = sub.add_parser("prune", help="delete cached downloads and transcripts older than N days")
    pr.add_argument("--days", type=int, default=7)

    sub.add_parser("styles", help="show the five edit styles (a screenshot to pick from)")
    sub.add_parser("doctor", help="check the install")
    return p


def styles():
    from pathlib import Path
    img = Path(__file__).resolve().parents[2] / "assets" / "styles.png"
    print(f"\n  Screenshot of all five styles: {img}\n")
    rows = [("1", "hookcard", "Hook card", "story text on top, action words in red, no facecam"),
            ("2", "stack", "Stack", "streamer on top, full game below"),
            ("3", "bubble", "Bubble", "full-screen gameplay, face bubble at the bottom"),
            ("4", "cinematic", "Cinematic", "movie look, slow push-in, no facecam"),
            ("5", "news", "Breaking news", "headline and red ticker, no facecam")]
    for n, key, name, what in rows:
        print(f"   {n}. {name:14} ({key}): {what}")
    print("\n  Use: --styles all   or   --styles 1,3   or   --styles hookcard,bubble\n")
    return 0


def doctor():
    ok = True
    for tool in ("ffmpeg", "ffprobe", "yt-dlp"):
        found = has(tool)
        print(f"  {'ok ' if found else 'MISSING'} {tool}")
        ok &= bool(found)
    print(f"  python: {sys.executable} ({sys.version.split()[0]})")
    js = shutil.which("deno") or shutil.which("node")
    print(f"  {'ok ' if js else 'MISSING'} JavaScript runtime (deno/node) for YouTube")
    for b in brains.ORDER:
        path = brains.binary(b)
        print(f"  {'ok ' if path else ' - '} {b} CLI{'  (' + path + ')' if path else ''}")
    print(f"  brain chosen with --brain auto: {brains.choose('auto')}")
    print(f"  {'ok ' if (MODELS / 'face_yunet.onnx').exists() else ' - '} face model")
    print(f"  output folder: {DATA}")
    return 0 if ok else 1


def print_found(found, trend_words):
    print()
    if trend_words:
        print("  Trending in Shorts right now: " + ", ".join(trend_words) + "\n")
    shown_live = False
    if found and not found[0]["live"]:
        print("  READY TO CLIP (finished streams, most viewed first):\n")
    for i, s in enumerate(found, 1):
        if s["live"] and not shown_live:
            print("\n  LIVE NOW (hot, but can only be clipped after the stream ends):\n")
            shown_live = True
        print(f"  {i:>2}. [{s['score']:>3}] {s['name'][:22]:22}  {s['title'][:62]}")
        print(f"        {s['why']}")
        print(f"        {s['url']}")
    print("\n  Clip some:  clip --pick 1,3     (numbers from this list)\n")


def prune(days):
    cutoff = time.time() - days * 86400
    removed = 0
    for d in CACHE.glob("*") if CACHE.exists() else []:
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    say(f"removed {removed} cached stream folder(s) older than {days} days", "good")
    return 0


def main(argv):
    opts = parser().parse_args(argv)
    try:
        if opts.command == "doctor":
            return doctor()
        if opts.command == "styles":
            return styles()
        if opts.command == "prune":
            return prune(opts.days)
        need("yt-dlp", "Run setup first.")
        need("ffmpeg", "Install ffmpeg (macOS: brew install ffmpeg, Windows: winget install Gyan.FFmpeg).")
        cfg = settings.load({
            "within": getattr(opts, "within", None), "rank": getattr(opts, "rank", None),
            "clips": getattr(opts, "clips", None),
            "template": getattr(opts, "template", None), "min_len": getattr(opts, "min_len", None),
            "max_len": getattr(opts, "max_len", None), "language": getattr(opts, "language", None),
            "length": getattr(opts, "length", None), "accent": getattr(opts, "accent", None),
            "max_hours": getattr(opts, "max_hours", None)})

        if opts.command == "remake":
            pipeline.remake(opts.folder, opts, cfg)
            return 0

        opts.topic = opts.topic or cfg["topic"]
        words = discover.spellings(opts.topic, cfg, opts.keywords)

        if opts.command == "find":
            found, trend_words = discover.find(opts.topic, words, cfg, opts.count, opts.search,
                                               include_done=opts.all)
            if not found:
                raise Problem("nothing found. Try --when month, other --keywords, or add creators "
                              f"to {DATA / 'watchlist.txt'}")
            write_json(LAST_FIND, {"topic": opts.topic, "trends": trend_words, "found": found})
            print_found(found, trend_words)
            return 0

        urls = list(opts.urls)
        opts.trend_words = []
        if opts.pick:
            last = read_json(LAST_FIND) or {}
            listed = last.get("found") or []
            try:
                nums = [int(x) for x in opts.pick.replace(" ", "").split(",") if x]
            except ValueError:
                raise Problem("--pick needs numbers like 1,3") from None
            for n in nums:
                if not 1 <= n <= len(listed):
                    raise Problem(f"--pick {n}: the last find listed {len(listed)} stream(s)")
                urls.append(listed[n - 1]["url"])
            opts.trend_words = last.get("trends") or []
        if opts.find:
            if not opts.count:
                opts.count = max(1, -(-opts.total // 3)) if opts.total else 3   # ~3 clips per stream
            found, trend_words = discover.find(opts.topic, words, cfg, opts.count, opts.search,
                                               include_live=False)
            print_found(found, trend_words)
            urls += [s["url"] for s in found]
            opts.trend_words = trend_words
        if not urls:
            raise Problem("give one or more links, --pick numbers from `find`, or use --find")
        quota = {}
        if opts.total:
            n = len(urls)
            if opts.total < n:
                urls = urls[: opts.total]
                n = len(urls)
            for i, u in enumerate(urls):
                quota[u] = opts.total // n + (1 if i < opts.total % n else 0)
            say(f"{opts.total} clip(s) from {n} stream(s): "
                + ", ".join(str(quota[u]) for u in urls) + " per stream", "info")
        opts.cam_box = None
        if opts.cam:
            try:
                box = tuple(float(v) for v in opts.cam.split(","))
                assert len(box) == 4 and all(0 <= v <= 1 for v in box) and box[2] > 0 and box[3] > 0
                assert box[0] + box[2] <= 1.001 and box[1] + box[3] <= 1.001
                opts.cam_box = box
            except (ValueError, AssertionError):
                raise Problem("--cam needs four fractions x,y,w,h inside the frame, "
                              "e.g. 0.75,0.0,0.25,0.3") from None
        opts.brain_resolved = brains.choose(opts.brain, opts.brain_cmd)
        say(f"moments will be picked by: {opts.brain_resolved}"
            + ("  (no AI: loudness + chat)" if opts.brain_resolved == "none" else ""), "info")

        results, waiting, failed = [], [], []
        brain_lock = {"switched": False}

        def one(url):
            mine = argparse.Namespace(**vars(opts))       # no shared state between threads
            mycfg = dict(cfg, clips=quota.get(url, cfg["clips"]))
            try:
                try:
                    return pipeline.process(url, mine, mycfg)
                except brains.SignedOut as exc:
                    if opts.brain != "auto":
                        raise
                    say(f"{exc} Switching to agent mode.", "warn")
                    brain_lock["switched"] = True
                    mine.brain_resolved = "agent"
                    return pipeline.process(url, mine, mycfg)
            except brains.NeedAgent as need_more:
                waiting.extend(need_more.waiting)
            except Exception as exc:  # noqa: BLE001
                failed.append((url, str(exc)))
                say(f"{url}: {str(exc)[:400]}", "bad")
            return None

        with ThreadPoolExecutor(max_workers=max(1, opts.parallel)) as pool:
            results = [r for r in pool.map(one, urls) if r]

        print()
        total = sum(len(r["clips"]) for r in results)
        if results:
            say(f"done: {total} clip(s) from {len(results)} stream(s)", "good")
        for r in results:
            print(f"\n  {r['name']}: {r['title'][:64]}\n  {r['summary']}\n  folder: {r['outdir']}")
            for c in r["clips"]:
                print(f"    [{c['score']}] {c['seconds']:>3.0f}s  {c['title'] or ''}")
                for f in c.get("files", []):
                    print(f"           {f['file']}")
            print(f"  check images: {r['outdir'] / 'checks'}")
        if waiting:
            folders = sorted({str(q.parent) for q, _ in waiting})
            print("\nAGENT MODE: you (the assistant) do this step yourself. Instructions are in:")
            for f in folders:
                task = "STORY_TASK.md" if any(q.name.endswith(".story.prompt.txt") for q, _ in waiting
                                              if str(q.parent) == f) else "AGENT_TASK.md"
                print(f"  {f}/{task}")
            print("Answer every prompt file, then run the SAME command again.\n")
            for q, a in waiting:
                print(f"  {q}\n    -> {a}")
            return AGENT_EXIT
        if failed and not results:
            return 1
        return 0
    except Problem as exc:
        say(str(exc), "bad")
        return 1
    except KeyboardInterrupt:
        print("\nstopped. Run the same command again to resume.", file=sys.stderr)
        return 130
