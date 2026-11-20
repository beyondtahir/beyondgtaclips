"""Smart search: find the streams worth clipping RIGHT NOW. No API keys.

1. Many searches, not one. Every way people spell the topic ("GTA 6", "GTA VI", "GTA6") x
   the words stream titles really use ("live", "gameplay", "first time playing", ...), plus
   a "live now" search. Merged, de-duplicated.
2. Junk is dropped: shorts, compilations, re-uploads, trailers, upcoming streams, videos
   too short to be a stream, too old, or already clipped.
3. The best candidates are looked up in full (upload time, likes, live viewers) and ranked
   by HEAT: views per hour blended with total views, a boost for streams that are live
   right now and for strong like ratios. A 2-hour-old stream at 3K views/hour beats
   yesterday's 800K.
4. Trend radar: today's most viewed Shorts for the topic tell us what people are watching
   (police chases, NPCs, secrets...). Those words steer both the ranking and the picker.
5. The user's watchlist (YouTube, Twitch and Kick creators) is checked the same way.
Every result says WHY it ranked where it did.
"""

import base64
import json
import re
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .common import DATA, Problem, read_json, run, say, write_json
from .media import ytdlp_args

WHEN = {"hour": 1, "today": 2, "week": 3, "month": 4}
SORT = {"relevance": 0, "date": 2, "views": 3}
DURATION = {"short": 1, "long": 2, "medium": 3}
HISTORY = DATA / "clipped.json"

STOP = set("""a an the and or but of to in on at for with from by is are was were be been it its
this that these those i you he she we they my your his her our their me him them us not no so
if then than too very just can will would should could do does did done have has had get got
gets out up down off over into about after before again new now what who how why when where
which all any some more most only own same such both each few other one two first last vs
live stream streaming gameplay part ep episode full game reaction reacts playing play played
shorts short video official trailer gta gta6 vi 6 grand theft auto rockstar here time pro
early launch playthrough walkthrough xbox ps5 pc fps 4k 1080p 60fps hd day night today
finally best ever insane crazy omg wow lol real really try tried trying first time things
part1 part2 jugando directo vivo jogando ao en el la los las del con por para que una
subathon marathon hours hour minutes days ago free giveaway giveaways watch watching love
loves literally going goes actually thought think found finds minute compilation release
released every everything people world look looks thing makes making made bad good nobody
someone something gets got why having causes caused channel channels""".split())

FOREIGN = (" de ", "las ", "aventuras", "ínicio", " é ", " o início", "jogando", "jugando", "directo", "en vivo", "ao vivo", "saatnya", "oynuyor", "agora",
           "inicio", "início", "siap", "tamat", "jogo", "parte ", "primeira", "juego", "primera",
           "canlı", "जीटीए", "ライブ", "直播", "jouer", "spielen", "na żywo", "в прямом")


# ---------------------------------------------------------------- YouTube search helpers

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, value):
    return _varint(num << 3) + _varint(value)


def search_filter(sort="views", when="week", duration="long", live=False):
    """YouTube's `sp` search parameter (a tiny protobuf)."""
    inner = b""
    if when:
        inner += _field(1, WHEN[when])
    inner += _field(2, 1)                              # type: video
    if duration:
        inner += _field(3, DURATION[duration])
    if live:
        inner += _field(8, 1)
    raw = _field(1, SORT[sort]) + _varint((2 << 3) | 2) + _varint(len(inner)) + inner
    return base64.b64encode(raw).decode()


def _listing(url, limit, args):
    try:
        out = run(["yt-dlp", "--flat-playlist", "--playlist-end", str(limit), "-J", *args, url],
                  timeout=150)
        return json.loads(out).get("entries") or []
    except (Problem, ValueError) as exc:
        say(f"could not read {url[:70]} ({str(exc)[:90]})", "warn")
        return []


def youtube_search(query, limit, **filters):
    url = ("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
           + "&sp=" + urllib.parse.quote(search_filter(**filters)))
    found = []
    for e in _listing(url, limit, ytdlp_args("youtube")):
        if not e.get("id") or e.get("ie_key", "Youtube") not in ("Youtube", None):
            continue
        found.append({
            "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}",
            "platform": "youtube", "name": e.get("channel") or e.get("uploader") or "?",
            "title": e.get("title") or "", "views": e.get("view_count") or 0,
            "seconds": e.get("duration") or 0,
            "live": e.get("live_status") == "is_live" or bool(filters.get("live")),
            "from": f'search "{query}"'})
    return found


# ---------------------------------------------------------------- words

def spellings(topic, cfg, extra=None):
    """Every way a title may spell the topic, lower case."""
    t = (topic or "").lower().strip()
    words = list(cfg["aliases"].get(t, []))          # configured order = search order
    for w in ([t, t.replace(" ", "")] if t else []) + (
            [x.strip().lower() for x in extra.split(",") if x.strip()] if extra else []):
        if w not in words:
            words.append(w)
    return words


def matches(title, words):
    low = title.lower()
    return not words or any(w in low for w in words)


def is_junk(item, cfg):
    low = item["title"].lower()
    if any(w in low for w in cfg["skip_words"]):
        return "compilation / re-upload / trailer"
    if item["seconds"] and item["seconds"] < cfg["min_minutes"] * 60 and not item["live"]:
        return "too short to be a stream"
    return None


# ---------------------------------------------------------------- trend radar

def trends(topic, words, cfg):
    """What is blowing up in Shorts for this topic today: the most common words in the
    titles of the most viewed Shorts. Cached for 3 hours."""
    if not cfg["trends"] or not topic:
        return []
    cache = DATA / ".cache" / "trends.json"
    data = read_json(cache, {}) or {}
    hit = data.get(topic.lower())
    if hit and time.time() - hit.get("at", 0) < 3 * 3600:
        return hit["words"]
    base = words[0] if words else topic
    shorts = []
    for when in ("today", "week"):
        for q in (f"{base} #shorts", f"{base} clip", f"{base} funny"):
            shorts += youtube_search(q, 50, sort="views", when=when, duration=None)
        shorts = [x for x in {x["id"]: x for x in shorts}.values() if x["seconds"] and x["seconds"] <= 180]
        if len(shorts) >= 15:
            break
    skip = STOP | {w for s in words for w in s.split()}
    skip |= {t for x in shorts for t in re.findall(r"[a-z][a-z']{2,}", x["name"].lower())}
    count, titles = Counter(), Counter()
    for s in shorts:
        tokens = [t for t in (re.sub(r"'s?$", "", t) for t in re.findall(r"[a-z][a-z']{2,}", s["title"].lower()))
                  if len(t) > 2 and t not in skip]
        weight = max(1.0, (s["views"] or 1000) / 1000.0) ** 0.5     # views matter, not just counts
        grams = set(tokens) | {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}
        for t in grams:
            count[t] += weight
            titles[t] += 1
    top = [w for w, n in count.most_common(60) if " " not in w or titles[w] >= 2]
    # keep a phrase instead of its parts when both made the list
    out = []
    for w in top:
        if " " not in w and any(w in p.split() for p in top if " " in p and count[p] >= count[w] - 1):
            continue
        out.append(w)
    out = out[:12]
    data[topic.lower()] = {"at": time.time(), "words": out}
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache, data)
    return out


# ---------------------------------------------------------------- full lookups + ranking

def enrich(item):
    """Upload time, likes, live viewers. Returns the item (updated) or None if unusable."""
    try:
        full = json.loads(run(["yt-dlp", "-J", "--skip-download", *ytdlp_args(item["url"]),
                               item["url"]], timeout=120))
    except (Problem, ValueError):
        return item
    status = full.get("live_status")
    if status == "is_upcoming":
        return None
    item.update({
        "views": full.get("view_count") or item["views"] or 0,
        "watching": full.get("concurrent_view_count") or 0,
        "likes": full.get("like_count") or 0,
        "comments": full.get("comment_count") or 0,
        "seconds": full.get("duration") or item["seconds"] or 0,
        "live": status == "is_live",
        "posted": full.get("release_timestamp") or full.get("timestamp") or 0,
        "name": full.get("channel") or full.get("uploader") or item["name"],
        "followers": full.get("channel_follower_count") or 0,
        "language": full.get("language") or next(
            (k[:-5] for k in (full.get("automatic_captions") or {}) if k.endswith("-orig")), None),
        "full": True})
    return item


def probe_language(item):
    """Listen to 30 s from the middle of the first hour and detect the spoken language."""
    import tempfile
    from .common import decode
    from .listen import whisper
    start = min(1800, max(300, (item.get("seconds") or 3600) // 4))
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run(["yt-dlp", *ytdlp_args(item["url"]), "-f", "ba/b",
                 "--download-sections", f"*{start}-{start + 30}", "-o", f"{tmp}/p.%(ext)s",
                 item["url"]], timeout=120)
            files = [f for f in __import__("pathlib").Path(tmp).glob("p.*") if not f.name.endswith(".part")]
            if not files:
                return None
            samples = decode(files[0], 16000)
            _, info = whisper("tiny").transcribe(samples, beam_size=1, vad_filter=True)
            return info.language if info.language_probability >= 0.5 else None
        except Exception:  # noqa: BLE001 - a probe is only a hint
            return None


def heat(item, cfg, trend_words):
    """Higher = more worth clipping right now. Also fills item['why']."""
    now = time.time()
    age_h = max(0.5, (now - item["posted"]) / 3600) if item.get("posted") else None
    views = item.get("views") or 0
    per_hour = views / age_h if age_h else 0.0
    if item.get("live") and item.get("watching"):
        per_hour = max(per_hour, item["watching"] * 4.0)
    r = 0.0 if cfg.get("rank") == "views" else float(cfg["recency"])
    base = (max(per_hour, 1.0) ** r) * (max(views, 1.0) ** (1 - r)) if age_h else max(views, 1.0)
    why = [f"{_k(views)} views"]
    if age_h:
        why.append(f"{_k(per_hour)}/h")
        why.append(f"posted {_age(age_h)} ago")
    mult = 1.0
    if item.get("live"):
        mult *= 1.35
        why.insert(0, f"LIVE NOW (clip after it ends){' · ' + _k(item['watching']) + ' watching' if item.get('watching') else ''}")
    if views and item.get("likes"):
        ratio = item["likes"] / views
        mult *= 1.0 + min(0.4, ratio * 8)
        if ratio >= 0.03:
            why.append(f"{ratio * 100:.0f}% likes")
    low = item["title"].lower()
    lang = (item.get("language") or "").lower()
    if cfg.get("prefer_english", True) and ((lang and not lang.startswith("en"))
                                             or any(f in low for f in FOREIGN)
                                             or sum(ord(c) > 0x2FF for c in low) > 6):
        mult *= 0.45
        why.append("not English")
    hits = [w for w in trend_words if w in low]
    if hits:
        mult *= 1.0 + 0.12 * min(3, len(hits))
        why.append("trending: " + ", ".join(hits[:3]))
    if item.get("seconds"):
        why.append(f"{item['seconds'] // 3600}h{item['seconds'] // 60 % 60:02d}m")
    item["why"] = " · ".join(why)
    item["per_hour"] = per_hour
    return base * mult


def _k(n):
    n = float(n or 0)
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}K" if n >= 1e3 else f"{n:.0f}"


def _age(h):
    return f"{h * 60:.0f}m" if h < 1 else f"{h:.0f}h" if h < 48 else f"{h / 24:.0f}d"


# ---------------------------------------------------------------- watchlist (YouTube / Twitch / Kick)

def watchlist_entries(topic):
    path = DATA / "watchlist.txt"
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        who, _, only = line.partition("|")
        if only.strip() and topic and only.strip().lower() not in topic.lower():
            continue
        platform, _, handle = who.strip().partition(":")
        if platform in ("twitch", "youtube", "kick") and handle.strip():
            out.append((platform, handle.strip()))
    return out


def _from_watchlist(platform, handle, words, cfg):
    """The creator's best recent matching video (not just the newest), or None."""
    if platform == "twitch":
        page = f"https://www.twitch.tv/{handle}/videos?filter=archives&sort=time"
    elif platform == "youtube":
        page = f"https://www.youtube.com/{handle if handle.startswith('@') else '@' + handle}/streams"
    else:
        page = f"https://kick.com/{handle}/videos"
    args = ytdlp_args(page)
    best = None
    for e in _listing(page, 6, args):
        title = e.get("title") or ""
        if not matches(title, words):
            continue
        url = e.get("url") or e.get("webpage_url") or ""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={e.get('id')}"
        item = {"id": e.get("id") or url, "url": url, "platform": platform, "name": handle,
                "title": title, "views": e.get("view_count") or 0, "seconds": e.get("duration") or 0,
                "live": e.get("live_status") == "is_live", "from": "watchlist"}
        item = enrich(item)
        if not item:
            continue
        if item.get("posted") and time.time() - item["posted"] > cfg["max_age_hours"] * 3600:
            continue
        if not best or (item.get("views") or 0) > (best.get("views") or 0):
            best = item
    return best


# ---------------------------------------------------------------- the whole search

def find(topic, words, cfg, count=5, search=None, include_done=False,
         include_live=True):
    """Hottest first, at most one per creator, with a reason on every line."""
    base = words[:2] if words else [topic]
    if search:
        queries = [(search, {})]
    else:
        queries = [(f"{w} {s}", {}) for w in base for s in cfg["search_suffixes"]]
        queries += [(f"{base[0]} live", {"live": True, "when": None, "duration": None})]
    say(f"smart search: {len(queries)} searches for {', '.join(repr(w) for w in base)}...", "step")

    def one(q):
        text, extra = q
        opts = {"sort": "views", "when": cfg["search_when"], "duration": "long"}
        opts.update(extra)
        return youtube_search(text, cfg["per_query"], **opts)

    trend_words = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        trend_job = pool.submit(trends, topic, words, cfg)
        pages = list(pool.map(one, queries))
        try:
            trend_words = trend_job.result()
        except Exception:  # noqa: BLE001 - trends are a bonus
            trend_words = []
    if trend_words:
        say("trending in Shorts right now: " + ", ".join(trend_words), "good")

    seen, pool_items, dropped = set(), [], Counter()
    done = set((read_json(HISTORY, {}) or {}).keys()) if not include_done else set()
    for page in pages:
        for item in page:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            if not matches(item["title"], words):
                dropped["not about the topic"] += 1
                continue
            junk = is_junk(item, cfg)
            if junk:
                dropped[junk] += 1
                continue
            if item["url"] in done:
                dropped["already clipped"] += 1
                continue
            pool_items.append(item)

    # look the most promising ones up in full, in batches, until there are enough usable ones
    if not include_live:
        pool_items = [s for s in pool_items if not s["live"]]
    pool_items.sort(key=lambda s: (not s["live"], -(s["views"] or 0)))
    people = watchlist_entries(topic)
    full, start, batch = [], 0, cfg["enrich"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        while start < len(pool_items):
            head = pool_items[start:start + batch]
            say(f"checking {len(head)} of {len(pool_items)} candidate streams in detail...", "step")
            full += [x for x in pool.map(enrich, head) if x]
            start += batch
            usable = [x for x in full if not x.get("live")]
            if len({x["name"].lower() for x in usable}) >= count + 3 or start >= 4 * batch:
                break
        if people:
            say(f"checking {len(people)} creator(s) on your watchlist...", "step")
            full += [r for r in pool.map(
                lambda p: _from_watchlist(p[0], p[1], words, cfg), people) if r]

    ranked = []
    for item in full:
        if item.get("posted") and time.time() - item["posted"] > cfg["max_age_hours"] * 3600:
            dropped["too old"] += 1
            continue
        if item["live"] and not include_live:
            dropped["live right now (clip it after it ends, or use --live)"] += 1
            continue
        if not item["live"] and (item.get("views") or 0) < cfg["min_views"]:
            dropped["too few views"] += 1
            continue
        if item.get("seconds") and item["seconds"] < cfg["min_minutes"] * 60 and not item["live"]:
            dropped["too short to be a stream"] += 1
            continue
        item["heat"] = heat(item, cfg, trend_words)
        ranked.append(item)

    best = {}
    for item in ranked:
        key = item["name"].lower()
        if key not in best or item["heat"] > best[key]["heat"]:
            best[key] = item
    out = sorted(best.values(), key=lambda s: -s["heat"])
    live_now = [s for s in out if s["live"]][:3] if include_live else []
    out = [s for s in out if not s["live"]]
    if cfg.get("prefer_english", True) and cfg.get("language_check", True):
        unknown = [s for s in out[: count + 4] if not s.get("language") and not s["live"]]
        if unknown:
            say(f"listening to 30 s of {len(unknown)} stream(s) to check the spoken language...", "step")
            with ThreadPoolExecutor(max_workers=4) as pool:
                langs = list(pool.map(probe_language, unknown))
            for s, lang in zip(unknown, langs):
                if lang:
                    s["language"] = lang
                    if not lang.startswith("en"):
                        s["heat"] *= 0.35
                        s["why"] += f" · speaks {lang}"
            out.sort(key=lambda s: -s["heat"])
    out = out[:count] + live_now
    if out:
        top = max(s["heat"] for s in out)
        import math
        for s in out:
            s["score"] = max(1, round(100 * s["heat"] / top))
    if dropped:
        say("skipped: " + ", ".join(f"{n} {why}" for why, n in dropped.most_common()), "info")
    return out, trend_words


def remember(url, title):
    """Mark a stream as clipped, so later searches skip it."""
    data = read_json(HISTORY, {}) or {}
    data[url] = {"title": title, "at": time.time()}
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    write_json(HISTORY, data)
