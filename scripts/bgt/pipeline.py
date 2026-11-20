"""Everything that happens to one stream, start to finish, plus `remake`."""

import datetime
import hashlib
from pathlib import Path

from . import brains, discover, highlights, listen, media, produce, settings, story
from .common import (CACHE, DATA, Problem, Stopwatch, clock, human, parse_clock, probe, read_json,
                     say, slug, tag, write_json)


def work_dir(url):
    key = hashlib.sha1(url.strip().encode()).hexdigest()[:10]
    tail = slug(url.split("://")[-1], 40)
    path = CACHE / f"{tail}_{key}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def section_bounds(opts, total, work, cfg):
    lo, hi = 0.0, total
    if opts.section:
        a, _, b = opts.section.replace(" ", "").lstrip("*").partition("-")
        lo = parse_clock(a) if a else 0.0
        hi = min(parse_clock(b), total) if b else total
    elif opts.new_only:
        done = (read_json(work / "progress.json") or {}).get("done_until", 0.0)
        lo = max(0.0, done - 60)
    elif cfg["max_hours"] and total > cfg["max_hours"] * 3600:
        hi = cfg["max_hours"] * 3600.0
    if hi - lo < 60:
        raise Problem(f"nothing new to clip ({clock(lo)}-{clock(hi)} is under a minute)")
    return lo, hi


def process(url, opts, cfg):
    cfg = dict(cfg)
    if opts.brain_resolved == "agent":                # the assistant reads every part itself
        cfg["max_blocks"] = min(int(cfg["max_blocks"] or 99), int(cfg["agent_blocks"]))
    watch = Stopwatch()
    args = media.ytdlp_args(url)
    work = work_dir(url)
    with watch.lap("look up"):
        meta = media.metadata(url, args, work)
    tag(meta["name"][:18])
    live = meta.get("live_status") == "is_live"
    if live:
        raise Problem("this stream is still LIVE. YouTube only allows cutting parts of a stream "
                      "after it ends (usually ready within an hour of the end). Pick a finished "
                      "stream (`clip --find` does that by itself) or run this again later.")
    duration = float(meta.get("duration") or 0)
    with watch.lap("download audio"):
        audio = media.audio(url, args, work, live=live)
    total = probe(audio)["duration"] or duration
    lo, hi = section_bounds(opts, total, work, cfg)
    say(f"{meta['title'][:70]}  ({human(duration or total)}"
        + (f", clipping {clock(lo)}-{clock(hi)})" if (lo, hi) != (0.0, total) else ")"), "good")

    with watch.lap("look"):
        board = media.storyboard(url, args, work)
        screen = media.screen_activity(board, total)
        if screen is not None:
            moving = float((screen["smooth"][int(lo):int(hi)] >= cfg["static_screen"]).mean())
            say(f"gameplay on screen in {moving * 100:.0f}% of this part of the stream", "good")
    with watch.lap("listen"):
        chat = listen.chat_speed(url, args, work, meta, cfg)
        heard = listen.scan(audio, total, lo, hi, work, cfg, live=live, chat=chat, screen=screen)
        spike_db = listen.spikes(heard["volume"])

    topic = opts.topic or cfg["topic"]
    video = {"title": meta["title"], "name": meta["name"], "url": url, "topic": topic,
             "focus": opts.focus}
    with watch.lap("pick"):
        picks = highlights.pick(heard, spike_db, chat, lo, hi, work, cfg, video,
                                opts.brain_resolved, opts.model, redo=opts.repick,
                                custom_cmd=opts.brain_cmd, trend_words=getattr(opts, "trend_words", None),
                                screen=screen)

    day = datetime.date.today().isoformat()
    outdir = (DATA / day / slug(topic, 30) / f"{slug(meta['name'], 24)}__{slug(meta['title'], 40)}")
    if (outdir / "clips.json").exists():            # never overwrite an earlier run's pack
        n = 2
        while (outdir.parent / f"{outdir.name}-run{n}" / "clips.json").exists():
            n += 1
        outdir = outdir.parent / f"{outdir.name}-run{n}"
    memory = read_json(work / "cam.json", {}) or {}
    ctx = {"url": url, "args": args, "audio": audio, "work": work, "outdir": outdir, "live": live,
           "language": cfg["language"], "fast": opts.fast, "cam": opts.cam_box,
           "spike_db": spike_db, "creator": meta["name"], "topic": topic,
           "brain": opts.brain_resolved, "model": opts.model, "brain_cmd": opts.brain_cmd}
    made, waiting = [], []
    with watch.lap("make clips"):
        for pick in picks:                      # best first; the rest are backups
            if len(made) + len(waiting) >= cfg["clips"]:
                break
            try:
                made.append(produce.make(len(made) + 1, pick, ctx, cfg, memory))
            except brains.NeedAgent as need:          # agent mode: collect, ask all at once
                waiting.extend(need.waiting)
            except story.Drop as exc:
                say(f"  skipped: {exc}; trying the next moment", "warn")
            except produce.NotGameplay as exc:
                say(f"  skipped: {exc}; trying the next moment", "warn")
            except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the rest
                say(f"  clip failed: {str(exc)[:300]}; trying the next moment", "bad")
    write_json(work / "cam.json", memory)
    if waiting:                                     # agent mode: one task file for every clip
        (work / "clips" / "STORY_TASK.md").write_text(
            story.TASK + "".join(f"- prompt: `{q}`\n  answer: `{a}`\n" for q, a in waiting), encoding="utf-8")
        raise brains.NeedAgent(waiting)

    summary = (f"{human(hi - lo)} of stream -> {len(made)} clip(s) in {human(watch.total())} ("
               + ", ".join(f"{k} {human(v)}" for k, v in watch.parts.items()) + ")")
    if made:
        posting_sheet(outdir, video, made, summary, lo, hi, cfg)
        write_json(work / "progress.json", {"done_until": hi, "at": datetime.datetime.now().isoformat()})
        discover.remember(url, meta["title"])
        if not opts.keep_audio and not live:
            audio.unlink(missing_ok=True)
    say(summary, "good")
    tag("")
    return {"name": meta["name"], "title": meta["title"], "outdir": outdir, "clips": made,
            "summary": summary}


SOUND_TIP = ("Add a trending sound inside the app at 5-10% volume under the original audio "
             "(Reels: Add audio > Trending; TikTok: Sounds > Trending). Trending audio is a "
             "discovery boost and is always licensed in-app.")


def posting_sheet(outdir, video, clips, summary, lo, hi, cfg):
    lines = [f"# {video['name']}: {video['title']}", "",
             f"Source: {video['url']}  ",
             f"Covered: {clock(lo)} to {clock(hi)}  ",
             summary, "",
             "Watch every clip before posting. Only clip creators who allow it "
             "(many run paid clipping programs). Always credit the streamer.", "",
             f"**Sound:** {SOUND_TIP}", ""]
    for n, c in enumerate(clips, 1):
        files = ", ".join(f"`{f['file']}` ({f['template']})" for f in c.get("files", []))
        lines += [f"## Clip {n}: {c.get('title') or c.get('type')}", "",
                  f"{c['type']} · {c['seconds']:.0f}s · score {c['score']} · from {clock(c['start'])} "
                  f"· picked by {c.get('picked_by', 'ai')}  ",
                  f"Files: {files}", "",
                  f"**Hook on screen:** {(c.get('hook') or '').replace('*', '')}", ""]
        if c.get("alt_hooks"):
            lines += ["**A/B test hooks** (remake with `--hook` to try one):", ""]
            lines += [f"- {h}" for h in c["alt_hooks"]]
            lines += [""]
        lines += ["Caption to paste:", "", "```", (c.get("caption") or "") + "\n\n"
                  + " ".join(c.get("hashtags") or []) + f"\n\n🎮 {video['name']}", "```", "",
                  f"_Why it should work: {c.get('why') or ''}_", "", "---", ""]
    (outdir / "POSTING.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(outdir / "clips.json", {"source": video, "covered": [lo, hi], "clips": clips,
                                       "settings": {k: cfg[k] for k in ("template", "length", "accent")}})


def remake(outdir, opts, cfg):
    """Re-render clips of a finished folder: new hook/title, other template. No downloads."""
    outdir = Path(outdir).expanduser()
    data = read_json(outdir / "clips.json")
    if not data:
        raise Problem(f"no clips.json in {outdir}")
    video = data["source"]
    which = set(opts.clip or []) or set(range(1, len(data["clips"]) + 1))
    for n, clip in enumerate(data["clips"], 1):
        if n not in which:
            continue
        job = read_json(clip.get("job", ""))
        if job:
            job = produce.refresh(job, cfg)
            write_json(clip["job"], job)
        if not job:
            say(f"clip {n}: its source part is gone (cache pruned); run clip again", "bad")
            continue
        pick = {k: clip.get(k) for k in ("type", "style", "hook", "alt_hooks", "title", "headline",
                                          "caption", "hashtags", "score", "why")}
        for field in ("hook", "title", "headline", "caption"):
            value = getattr(opts, field, None)
            if value:
                pick[field] = value
                clip[field] = value
        job.update({"folder": Path(clip["job"]).parent, "pick": pick, "creator": video["name"],
                    "topic": video.get("topic"), "fast": opts.fast})
        job["part"] = Path(job["part"])
        if not job["part"].exists():
            say(f"clip {n}: its source part is gone (cache pruned); run clip again", "bad")
            continue
        names = produce.templates_for(pick, job["analysis"], cfg)
        base = clip["file"].split("__")[0]
        files = [f for f in clip.get("files", []) if f["template"] not in names]
        for name in names:
            dest = outdir / f"{base}__{name}.mp4"
            produce.render(name, job, cfg, dest)
            files.append({"file": dest.name, "template": name})
            say(f"clip {n}: saved {dest.name}", "good")
        clip["files"] = files
    posting_sheet(outdir, video, data["clips"], "remade " + datetime.datetime.now().strftime("%H:%M"),
                  data["covered"][0], data["covered"][1], cfg)
    return outdir
