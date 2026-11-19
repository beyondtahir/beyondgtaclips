"""Every knob in one place. Override any of them in ~/BeyondGTAClips/settings.json."""

from .common import DATA, Problem, read_json

TEMPLATES = ("hookcard", "stack", "bubble", "cinematic", "news")

DEFAULTS = {
    # finding streams
    "topic": "GTA 6",                # default topic when none is given
    "aliases": {                     # how people really spell a topic in titles
        "gta 6": ["gta 6", "gta vi", "gta6", "grand theft auto vi", "grand theft auto 6"],
    },
    "search_suffixes": ["stream", "live", "gameplay", "first time playing", "reaction", "full game"],
    "search_when": "week",           # hour | today | week | month (YouTube upload window)
    "per_query": 25,                 # results read per search
    "enrich": 24,                    # top candidates looked up in full (age, likes, live viewers)
    "within": "48h",                 # search window: 24h | 48h | week (ask the user)
    "rank": "views",                 # views = most viewed in the window; hot = views per hour
    "recency": 0.6,                  # with rank "hot": 0 = total views, 1 = views per hour
    "min_views": 2000,
    "min_minutes": 20,               # shorter videos are not streams
    "max_age_hours": 168,            # older videos are skipped
    "skip_words": ["compilation", "best moments", "highlights", "top 10", "top 5", "#shorts",
                   "trailer", "review", "reupload", "re-upload", "funny moments", "montage"],
    "trends": True,                  # read today's top Shorts for the topic to learn what's hot
    "prefer_english": True,          # rank English streams above others
    "language_check": True,          # listen to 30 s of the top streams to detect their language
    "max_hours": 10,                 # longest part of a stream considered (from the start)
    "static_screen": 15.0,           # storyboard activity below this = menu / waiting / talking
    "min_motion": 5.0,               # real-frame motion below this = not gameplay, use a backup

    # listening
    "scan_model": "tiny",            # Whisper model for the whole stream (fast)
    "caption_model": "base",         # Whisper model for each clip's captions (accurate)
    "language": None,                # None = detect per block, or e.g. "en", "hi", "es"
    "block_minutes": 10,
    "max_blocks": 10,                # transcribe only the 10 hottest 10-min blocks (0 = all)
    "volume_jump_db": 7.0,           # this much louder than the surrounding minutes = a spike
    "chat_jump": 3.0,                # chat this many times its usual speed = a spike
    "chat_replay": True,
    "chat_timeout": 360,

    # picking
    "clips": 4,                      # clips per stream (3-5 recommended)
    "length": "short",               # short (20-45 s) | long (60-90 s, hook -> build -> payoff)
    "min_len": None,                 # None = from `length`
    "max_len": None,
    "part_minutes": 10,
    "part_overlap": 20,
    "picks_per_part": 3,
    "brain_parallel": 2,             # AI calls at the same time
    "agent_blocks": 6,               # agent mode: fewer, bigger transcript parts to read
    "min_score": 40,

    # look
    "template": "hookcard",          # default style #1; all | auto | numbers "1,3" | names
    "accent": None,                  # None = each template's own accent, or a hex like "FF2D2D"
    "width": 1080,
    "height": 1920,
    "cam_share": 0.32,               # stack: share of the height given to the facecam
    "big_face": 0.13,                # face wider than this share of the frame = talking head
    "punch_ins": True,               # quick zoom on the loudest seconds (bubble, stack)
    "sfx": True,                     # a soft whoosh on the hook, made locally (no files)
    "show_creator": True,            # small credit with the streamer's name

    # output
    "video_height": 1080,
    "crf": 18,
    "x264_preset": "medium",
    "loudness": -14,                 # LUFS; None to leave the audio as it is
    "audio_kbps": 192,
}

LENGTHS = {"short": (20, 45), "long": (60, 90)}

NUMBERS = {str(i): name for i, name in enumerate(TEMPLATES, 1)}   # 1 hookcard ... 5 news


def parse_templates(value):
    """'auto', 'all', 'hookcard', '1,3', 'hookcard,bubble' or a list -> 'auto'/'all'/[names]."""
    if isinstance(value, list):
        items = value
    else:
        text = str(value or "auto").strip().lower()
        if text in ("auto", "all"):
            return text
        items = [x.strip() for x in text.replace(" ", ",").split(",") if x.strip()]
    names = []
    for x in items:
        name = NUMBERS.get(str(x), str(x).lower())
        if name not in TEMPLATES:
            raise Problem(f"unknown style '{x}'. Use all, auto, numbers 1-5 or: {', '.join(TEMPLATES)}")
        if name not in names:
            names.append(name)
    if not names:
        raise Problem("no style given")
    return names


def load(cli=None):
    cfg = dict(DEFAULTS)
    user = DATA / "settings.json"
    if user.exists():
        data = read_json(user)
        if not isinstance(data, dict):
            raise Problem(f"{user} is not valid JSON")
        unknown = set(data) - set(DEFAULTS)
        if unknown:
            raise Problem(f"{user}: unknown setting(s) {', '.join(sorted(unknown))}")
        cfg.update(data)
    for key, value in (cli or {}).items():
        if value is not None:
            cfg[key] = value
    if cfg["length"] not in LENGTHS:
        raise Problem(f"length must be one of {', '.join(LENGTHS)}")
    lo, hi = LENGTHS[cfg["length"]]
    cfg["min_len"] = int(cfg["min_len"] or lo)
    cfg["max_len"] = int(cfg["max_len"] or hi)
    if cfg["min_len"] >= cfg["max_len"]:
        raise Problem("min length must be shorter than max length")
    windows = {"24h": ("today", 24), "48h": ("week", 48), "week": ("week", 168)}
    if cfg["within"] not in windows:
        raise Problem("within must be 24h, 48h or week")
    cfg["search_when"], cfg["max_age_hours"] = windows[cfg["within"]]
    cfg["template"] = parse_templates(cfg["template"])
    return cfg
