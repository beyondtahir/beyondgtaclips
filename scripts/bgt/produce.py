"""Build finished clips: fetch the moment's video, sync it to the stream audio, caption it,
dress it in a template, add sound design, encode, and save a check image.

The downloaded source part, its word timings and the facecam analysis are kept, so a clip
can be re-rendered in seconds with a new hook or another template (`remake`)."""

import subprocess
from functools import lru_cache

import numpy as np

from . import art, frame, listen, media, templates
from .common import Problem, decode, probe, read_json, run, say, slug, write_json

PAD = 5.0          # extra seconds fetched on each side; trimmed after syncing
ENV_RATE = 100     # envelope samples per second used for syncing


def _envelope(samples, rate=8000):
    hop = rate // ENV_RATE
    n = len(samples) // hop
    if not n:
        return np.zeros(0, np.float32)
    e = np.log(np.sqrt(np.mean(samples[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-4)
    k = ENV_RATE
    trend = np.convolve(np.pad(e, k // 2, mode="edge"), np.ones(k) / k, mode="valid")[: len(e)]
    return (e - trend).astype(np.float32)


def sync(part, audio, guess, reach=25.0):
    """Stream time of the part's first frame, by matching its sound to the stream audio.
    Returns (seconds, confidence 0-1)."""
    probe_len = 20.0
    a = _envelope(decode(part, 8000, 0.5, probe_len))
    lo = max(0.0, guess + 0.5 - reach)
    b = _envelope(decode(audio, 8000, lo, probe_len + 2 * reach))
    if len(a) < ENV_RATE * 5 or len(b) <= len(a):
        return guess, 0.0
    a = (a - a.mean()) / (a.std() + 1e-6)
    win = np.lib.stride_tricks.sliding_window_view(b, len(a))
    mu, sd = win.mean(axis=1), win.std(axis=1) + 1e-6
    score = (win @ a - mu * a.sum()) / (len(a) * sd)
    k = int(np.argmax(score))
    return lo + k / ENV_RATE - 0.5, float(score[k])


@lru_cache(maxsize=1)
def video_encoder(fast):
    if not fast:
        return "libx264"
    for enc in ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf"):
        probe_cmd = ["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                     "color=c=black:s=256x256:d=0.2", "-c:v", enc, "-f", "null", "-"]
        if subprocess.run(probe_cmd, capture_output=True).returncode == 0:
            return enc
    return "libx264"


def _encode_args(enc, cfg):
    if enc == "libx264":
        return ["-c:v", "libx264", "-preset", cfg["x264_preset"], "-crf", str(cfg["crf"]),
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", enc, "-b:v", "12M", "-maxrate", "16M", "-bufsize", "24M", "-pix_fmt", "yuv420p"]


def check_image(clip, length, dest):
    """Three frames side by side, so a person (or an agent that can see images) can check
    the framing, the hook and the captions without playing the video."""
    from PIL import Image
    shots = []
    for i, f in enumerate((0.12, 0.5, 0.85)):
        tmp = dest.with_name(dest.stem + f"_{i}.jpg")
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{length * f:.2f}", "-i", str(clip),
             "-frames:v", "1", "-vf", "scale=360:-2", str(tmp)])
        with Image.open(tmp) as im:
            shots.append(im.convert("RGB"))
        tmp.unlink(missing_ok=True)
    sheet = Image.new("RGB", (sum(s.width for s in shots) + 20, shots[0].height), (20, 20, 20))
    x = 0
    for s in shots:
        sheet.paste(s, (x, 0))
        x += s.width + 10
    sheet.save(dest, quality=85)
    return dest


def punch_windows(spike_db, start, end, cfg):
    """Clip-time windows for quick zoom-ins on the loudest seconds (max 3, 6 s apart)."""
    if not cfg.get("punch_ins") or spike_db is None or not len(spike_db):
        return []
    a, b = int(start), min(int(end), len(spike_db))
    seg = np.asarray(spike_db[a:b], dtype=np.float32)
    out = []
    for i in np.argsort(-seg):
        if seg[i] < cfg["volume_jump_db"] + 2 or len(out) >= 3:
            break
        t = a + int(i) - start
        if t < 1.2 or t > end - start - 1.6:
            continue
        if all(abs(t - o) >= 6 for o in out):
            out.append(t)
    return [(max(0.0, t - 0.15), t + 1.4) for t in sorted(out)]


def sfx_track(path, length, punches, cfg):
    """One WAV the length of the clip: whoosh on the hook, a soft pop on each punch-in."""
    if not cfg.get("sfx"):
        return None
    rate = 48000
    track = np.zeros(int((length + 0.5) * rate), np.float32)
    folder = path.parent
    wh = folder / "_whoosh.wav"
    pp = folder / "_pop.wav"
    if not wh.exists():
        art.whoosh(wh)
    if not pp.exists():
        art.pop(pp)
    w = decode(wh, rate)
    p = decode(pp, rate)
    track[: len(w)] += w * 0.55
    for s, _ in punches:
        i = int(s * rate)
        seg = p[: max(0, min(len(p), len(track) - i))]
        track[i: i + len(seg)] += seg * 0.45
    art._write_wav(path, track, rate)
    return path


def templates_for(pick, analysis, cfg):
    want = cfg["template"]
    if want == "all":
        names = list(templates.BUILDERS)
    elif want == "auto":
        names = [pick.get("style") or "hookcard"]
    else:
        names = list(want) if isinstance(want, list) else [want]
    out = []
    for n in names:
        r = templates.resolve(n, analysis)
        if r not in out:
            out.append(r)
    return out


def render(name, job, cfg, dest):
    """One template for one prepared clip (see prepare). Writes dest; returns dest."""
    folder = job["folder"] / f"{dest.stem}_parts"
    folder.mkdir(parents=True, exist_ok=True)
    info, length = job["info"], job["length"]
    fps = min(60.0, info["fps"] or 30.0)
    accent = cfg.get("accent") or templates.ACCENT[name]
    ctx = {"info": info, "pick": job["pick"], "accent": accent, "cfg": cfg, "words": job["words"],
           "cam": job["analysis"].get("cam"), "face": job["analysis"].get("face"),
           "talking_graph": job["analysis"].get("talking_graph"),
           "punches": job["punches"] if name in ("stack", "bubble") else [],
           "creator": job.get("creator"), "topic": job.get("topic")}
    extra, graph = templates.build(name, ctx, folder, fps, length)
    sfx = sfx_track(folder / "sfx.wav", length, ctx["punches"], cfg)
    inputs = ["-ss", f"{job['offset']:.3f}", "-t", f"{length:.3f}", "-i", str(job["part"]), *extra]
    audio = "[0:a]aresample=48000"
    if name == "cinematic":
        audio += f",afade=t=in:st=0:d=0.4,afade=t=out:st={max(0.0, length - 0.6):.2f}:d=0.6"
    if sfx:
        inputs += ["-i", str(sfx)]
        sfx_index = 1 + sum(1 for a in extra if a == "-i")
        audio += f"[a0];[{sfx_index}:a]aresample=48000[a1];[a0][a1]amix=inputs=2:duration=first:normalize=0"
    if cfg["loudness"] is not None:
        audio += f",loudnorm=I={cfg['loudness']}:TP=-1.5:LRA=11,aresample=48000"
    graph += f";{audio}[aout]"
    enc = video_encoder(job.get("fast", False))
    tmp = folder / "out.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-nostdin", *inputs, "-filter_complex", graph,
         "-map", "[vout]", "-map", "[aout]", "-t", f"{length:.3f}", *_encode_args(enc, cfg),
         "-r", f"{fps:.3f}", "-c:a", "aac", "-b:a", f"{cfg['audio_kbps']}k",
         "-movflags", "+faststart", str(tmp)], timeout=3600, cwd=str(folder))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(dest)
    checks = dest.parent / "checks"
    checks.mkdir(exist_ok=True)
    try:
        check_image(dest, length, checks / f"{dest.stem}.jpg")
    except Problem:
        pass
    return dest


JOB_VERSION = 3


def refresh(job, cfg, forced_cam=None):
    """Re-run the (cheap, local) on-screen analysis for jobs cached by an older version."""
    if job.get("v") == JOB_VERSION:
        return job
    from pathlib import Path
    part = Path(job["part"])
    if part.exists():
        job["analysis"] = frame.analyze(part, job["offset"], job["length"], job["info"], cfg, {}, forced_cam)
        job["v"] = JOB_VERSION
    return job


def prepare(index, pick, ctx, cfg, memory):
    """Download, sync, transcribe and analyse one moment. Everything is cached on disk."""
    start, end = pick["start"], pick["end"]
    length = end - start
    name = f"{index:02d}_{slug(pick.get('title') or pick.get('type'), 40)}"
    clips_dir = ctx["work"] / "clips"
    clips_dir.mkdir(exist_ok=True)
    key = f"{int(start * 10)}_{int(end * 10)}"
    cached = read_json(clips_dir / f"{key}.job.json")
    part = clips_dir / f"{key}.src.mp4"
    if cached and part.exists():
        job = refresh(cached, cfg, ctx.get("cam"))
        write_json(clips_dir / f"{key}.job.json", job)
    else:
        part = media.video_slice(ctx["url"], ctx["args"], start - PAD, end + PAD, part,
                                 cfg["video_height"], live=ctx.get("live", False))
        info = probe(part)
        if not info["width"]:
            raise Problem("the downloaded video has no picture")
        at, conf = sync(part, ctx["audio"], start - PAD)
        offset = start - at if conf >= 0.45 else min(PAD, max(0.0, start))
        offset = min(max(0.0, offset), max(0.0, info["duration"] - length))
        if conf < 0.45:
            say(f"  weak sound match ({conf:.2f}); using the requested times, may be off by ~1 s", "warn")
        words, _ = listen.transcribe(cfg["caption_model"], decode(part, 16000, offset, length),
                                     ctx["language"])
        analysis = frame.analyze(part, offset, length, info, cfg, memory, ctx.get("cam"))
        job = {"v": JOB_VERSION, "part": str(part), "info": info, "offset": offset, "length": length, "sync": conf,
               "words": words, "analysis": analysis,
               "punches": punch_windows(ctx.get("spike_db"), start, end, cfg)}
        write_json(clips_dir / f"{key}.job.json", job)
    job = dict(job)
    job.update({"folder": clips_dir, "pick": pick, "creator": ctx.get("creator"),
                "topic": ctx.get("topic"), "fast": ctx.get("fast", False), "name": name})
    job["part"] = clips_dir / f"{key}.src.mp4"
    return job


class NotGameplay(Problem):
    """The moment's picture is a menu, a waiting screen or just talking."""


def make(index, pick, ctx, cfg, memory):
    """Prepare one moment and render it in its template(s). Returns the clip record."""
    start, end = pick["start"], pick["end"]
    say(f"clip {index}: {pick.get('title') or pick.get('type')}  ({end - start:.0f}s at "
        f"{int(start // 3600)}:{int(start // 60 % 60):02d}:{int(start % 60):02d})", "step")
    job = prepare(index, pick, ctx, cfg, memory)
    moving = job["analysis"].get("motion", 99)
    if moving < cfg["min_motion"] and not ctx.get("cam"):
        raise NotGameplay(f"the picture barely moves (motion {moving}): a menu, a waiting "
                          f"screen or just talking, not gameplay")
    say(f"  on screen: {job['analysis']['how']}, game motion {moving}")
    files = []
    for name in templates_for(pick, job["analysis"], cfg):
        dest = ctx["outdir"] / f"{job['name']}__{name}.mp4"
        try:
            render(name, job, cfg, dest)
            files.append({"file": dest.name, "template": name})
            say(f"  saved {dest.name}", "good")
        except Problem as exc:
            say(f"  {name} failed: {str(exc)[:300]}", "bad")
    if not files:
        raise Problem("no template could be rendered for this moment")
    return {"files": files, "file": files[0]["file"], "template": files[0]["template"],
            "type": pick.get("type"), "style": pick.get("style"), "hook": pick.get("hook"),
            "alt_hooks": pick.get("alt_hooks", []), "title": pick.get("title"),
            "headline": pick.get("headline"), "caption": pick.get("caption"),
            "hashtags": pick.get("hashtags", []), "score": pick.get("score"), "why": pick.get("why"),
            "picked_by": pick.get("picked_by", "ai"), "start": round(start, 1), "end": round(end, 1),
            "seconds": round(end - start, 1), "sync": round(job["sync"], 2),
            "job": str(ctx["work"] / "clips" / f"{int(start * 10)}_{int(end * 10)}.job.json")}
