"""yt-dlp wrappers. A stream is fetched as audio first; video only for the seconds that
become clips, so a 6-hour stream costs a few hundred MB instead of many GB."""

import shutil
import time
from pathlib import Path

from .common import Problem, read_json, run, say, write_json

META_KEYS = ("id", "title", "channel", "uploader", "duration", "view_count", "live_status",
             "is_live", "was_live", "webpage_url", "extractor_key", "timestamp",
             "release_timestamp", "upload_date")


def ytdlp_args(url, cookies=None):
    """Options every yt-dlp call for this URL needs."""
    args = ["--no-playlist", "--no-warnings"]
    youtube = "youtu" in url
    if youtube and not shutil.which("deno"):
        for runtime in ("node", "bun"):
            path = shutil.which(runtime)
            if path:
                args += ["--js-runtimes", f"{runtime}:{path}"]
                break
    if cookies:
        args += ["--cookies-from-browser", cookies]
    return args


def friendly(exc, url):
    """Turn common yt-dlp failures into the fix the user needs."""
    text = str(exc)
    low = text.lower()
    if "confirm your age" in low or "sign in to confirm" in low or "age-restricted" in low:
        return Problem("YouTube needs a login for this video (age-restricted). Run again with "
                       "--cookies chrome (or the browser you are signed in with).")
    if "kick" in url and ("403" in text or "forbidden" in low):
        return Problem("Kick blocked the download. Run again with --cookies chrome.")
    if "subscriber" in low or "sub-only" in low or "only available to" in low:
        return Problem("This VOD is subscriber-only. Run again with --cookies <browser> from an "
                       "account that can watch it.")
    if "not a bot" in low:
        return Problem("YouTube is asking to confirm you're not a bot. Run again with "
                       "--cookies chrome, or wait a while.")
    return exc if isinstance(exc, Problem) else Problem(text)


def metadata(url, args, work, refresh=False):
    cached = work / "meta.json"
    meta = read_json(cached)
    stale = meta and meta.get("live_status") == "is_live" and time.time() - meta.get("_at", 0) > 300
    if meta and not refresh and not stale:
        return meta
    import json
    try:
        full = json.loads(run(["yt-dlp", "-J", *args, url], timeout=240))
    except Problem as exc:
        raise friendly(exc, url) from None
    meta = {k: full.get(k) for k in META_KEYS}
    meta["name"] = meta.get("channel") or meta.get("uploader") or "creator"
    meta["_at"] = time.time()
    write_json(cached, meta)
    return meta


def _finished(folder, stem):
    return [p for p in folder.glob(stem + ".*")
            if not p.name.endswith((".part", ".ytdl", ".json", ".tmp")) and ".part-" not in p.name]


def audio(url, args, work, live=False, until=None):
    """The audio track of the stream, from the start (up to `until` seconds when given).
    Reused between runs unless the stream is live or a longer part is needed now."""
    have = _finished(work, "audio")
    if have and not live:
        say(f"reusing downloaded audio ({have[0].stat().st_size / 1e6:.0f} MB)", "good")
        return have[0]
    for old in work.glob("audio.*"):
        old.unlink(missing_ok=True)
    say("downloading the audio track (video comes later, only for the clips)...", "step")
    extra = ["--live-from-start"] if live and "youtu" in url else []
    try:
        run(["yt-dlp", *args, *extra, "-f", "ba/b", "-N", "4",
             "-o", str(work / "audio.%(ext)s"), url], timeout=4 * 3600)
    except Problem as exc:
        raise friendly(exc, url) from None
    have = _finished(work, "audio")
    if not have:
        raise Problem("the download finished but no audio file appeared")
    say(f"audio ready ({have[0].stat().st_size / 1e6:.0f} MB)", "good")
    return have[0]


def video_slice(url, args, start, end, dest: Path, max_height, live=False):
    """Only [start, end] seconds of the video, as an mp4."""
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest
    for old in dest.parent.glob(dest.stem + ".*"):
        old.unlink(missing_ok=True)
    fmt = (f"bv*[height<={max_height}][vcodec^=avc1]+ba/bv*[height<={max_height}]+ba/"
           f"b[height<={max_height}]/bv*+ba/b")
    try:
        run(["yt-dlp", *args, *(["--live-from-start"] if live and "youtu" in url else []),
             "-f", fmt, "--merge-output-format", "mp4",
             "--download-sections", f"*{max(0, start):.2f}-{end:.2f}",
             "-o", str(dest.with_suffix(".%(ext)s")), url], timeout=1800)
    except Problem as exc:
        raise friendly(exc, url) from None
    got = _finished(dest.parent, dest.stem)
    if not got:
        raise Problem(f"no video came back for {start:.0f}-{end:.0f}s")
    if got[0] != dest:
        got[0].replace(dest)
    return dest


# ------------------------------------------------------------------ storyboard (see the whole stream)

def storyboard(url, args, work):
    """YouTube's storyboard: a tiny frame every ~10 s of the whole video (about 1 MB for a
    10-hour stream). Returns (times in seconds, gray frames float32 [n, h, w]) or None.
    Used to tell gameplay from menus and talking before any video is downloaded."""
    import io
    import json
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np
    from PIL import Image

    cache = work / "storyboard.npz"
    if cache.exists():
        data = np.load(cache)
        return data["times"], data["frames"]
    if "youtu" not in url:
        return None
    try:
        full = json.loads(run(["yt-dlp", "-J", "--skip-download", *args, url], timeout=180))
    except Problem:
        return None
    boards = [f for f in full.get("formats") or [] if str(f.get("format_id", "")).startswith("sb")
              and f.get("fragments") and (f.get("width") or 0) >= 60]
    if not boards:
        return None
    sb = min(boards, key=lambda f: f.get("width") or 999)          # the smallest tiles are enough
    rows, cols = int(sb.get("rows") or 1), int(sb.get("columns") or 1)
    tw, th = int(sb["width"]), int(sb["height"])
    step = 1.0 / float(sb.get("fps") or 0.1)
    frags = sb["fragments"]

    def get(frag):
        req = urllib.request.Request(frag["url"], headers={"User-Agent": "Mozilla/5.0"})
        for _ in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return Image.open(io.BytesIO(resp.read())).convert("L")
            except OSError:
                continue
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        sheets = list(pool.map(get, frags))
    tiles, times, t = [], [], 0.0
    duration = float(full.get("duration") or 0)
    for frag, sheet in zip(frags, sheets):
        n_here = max(1, int(round(float(frag.get("duration") or step * rows * cols) / step)))
        for k in range(min(n_here, rows * cols)):
            if sheet is not None:
                r, c = divmod(k, cols)
                box = (c * tw, r * th, (c + 1) * tw, (r + 1) * th)
                if box[2] <= sheet.width and box[3] <= sheet.height:
                    tiles.append(np.asarray(sheet.crop(box), dtype=np.float32))
                    times.append(t)
            t += step
    if len(tiles) < 10:
        return None
    times = np.array(times, dtype=np.float32)
    frames = np.stack(tiles)
    keep = times <= (duration or times[-1]) + step
    np.savez_compressed(cache, times=times[keep], frames=frames[keep])
    say(f"looked at the whole stream: {int(keep.sum())} preview frames", "good")
    return times[keep], frames[keep]


def screen_activity(board, total):
    """Per-second 'is the game moving' score from the storyboard: how much the picture
    changes between preview frames (menus, waiting screens and pure talking stay low)."""
    import numpy as np
    if not board:
        return None
    times, frames = board
    if len(frames) < 3:
        return None
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    diff = np.concatenate([[diff[0]], diff])
    secs = int(np.ceil(total))
    curve = np.interp(np.arange(secs), times, diff).astype(np.float32)
    k = 7                                                    # smooth over ~1 minute of previews
    smooth = np.convolve(np.pad(diff, k // 2, mode="edge"), np.ones(k) / k, mode="valid")[: len(diff)]
    return {"raw": curve, "smooth": np.interp(np.arange(secs), times, smooth).astype(np.float32)}
