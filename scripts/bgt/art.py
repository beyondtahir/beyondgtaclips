"""Every piece of text and graphics, drawn with Pillow (no libass / freetype needed in
ffmpeg, so it looks the same on every Mac and PC).

  rich text   hook sentences with *accent words* in colour + bold, colour emoji
  captions    word-by-word caption frames, written as one image sequence for ffmpeg
  stickers    title pills, news tags, tickers, labels, the round facecam mask and ring
  sounds      a soft whoosh and a pop, synthesised (no files, no licences)
"""

import math
import re
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .titlecard import _Emoji, _is_emoji

FONTS = {
    "clean": [("/System/Library/Fonts/HelveticaNeue.ttc", 10), ("C:/Windows/Fonts/seguisb.ttf", 0),
              ("C:/Windows/Fonts/segoeui.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)],
    "clean_bold": [("/System/Library/Fonts/HelveticaNeue.ttc", 1), ("C:/Windows/Fonts/segoeuib.ttf", 0),
                   ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
    "heavy": [("/System/Library/Fonts/Supplemental/Arial Black.ttf", 0), ("C:/Windows/Fonts/ariblk.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
    "rounded": [("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 0),
                ("C:/Windows/Fonts/ARLRDBD.TTF", 0), ("C:/Windows/Fonts/arialbd.ttf", 0),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
    "condensed": [("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf", 0),
                  ("/System/Library/Fonts/HelveticaNeue.ttc", 9), ("C:/Windows/Fonts/impact.ttf", 0),
                  ("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf", 0)],
    "label": [("/System/Library/Fonts/Avenir Next.ttc", 2), ("C:/Windows/Fonts/seguisb.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
    "unicode": [("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
                ("/Library/Fonts/Arial Unicode.ttf", 0), ("C:/Windows/Fonts/Nirmala.ttf", 0),
                ("C:/Windows/Fonts/seguisym.ttf", 0),
                ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 0)],
    "elegant": [("/System/Library/Fonts/Avenir Next.ttc", 5), ("C:/Windows/Fonts/segoeui.ttf", 0),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)],
}

_font_cache = {}
_emoji = None


def font(kind, size):
    key = (kind, int(size))
    if key not in _font_cache:
        for path, index in FONTS[kind]:
            if Path(path).exists():
                try:
                    _font_cache[key] = ImageFont.truetype(path, int(size), index=index)
                    break
                except OSError:
                    continue
        else:
            _font_cache[key] = ImageFont.load_default(int(size))
    return _font_cache[key]


def emoji():
    global _emoji
    if _emoji is None:
        _emoji = _Emoji()
    return _emoji


def rgba(hex6, alpha=255):
    h = hex6.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


# ------------------------------------------------------------------ rich text

def parse_rich(text):
    """'Speed gets *attacked by an alligator* in *GTA 6*' -> [(word, accent), ...]."""
    out, accent = [], False
    for piece in re.split(r"(\*)", text or ""):
        if piece == "*":
            accent = not accent
            continue
        for word in piece.split():
            if out and all(_is_emoji(c) for c in word):
                out[-1] = (out[-1][0] + " " + word, out[-1][1])   # keep emoji with its word
            else:
                out.append((word, accent))
    return out


def _pieces(word):
    """('t', text) / ('e', emoji) pieces of one word."""
    pieces, buf = [], ""
    for ch in word:
        if _is_emoji(ch):
            if buf:
                pieces.append(("t", buf))
                buf = ""
            if ch not in ("\u200d", "\ufe0f"):
                pieces.append(("e", ch))
        else:
            buf += ch
    if buf:
        pieces.append(("t", buf))
    return pieces


def rich_block(words, size, width, regular="clean", accent_font="clean_bold", color="FFFFFF",
               accent="FF3B3B", align="center", line_gap=1.28, stroke=0, stroke_color="000000",
               shadow=False, scale=None, upper=False):
    """Draw a paragraph of (word, accent) pairs into a transparent image `width` wide.
    `scale`: optional {word index: factor} to enlarge single words (caption pop)."""
    em = int(size * 1.05)
    glyphs = {}
    items = []
    for i, (word, acc) in enumerate(words):
        if upper:
            word = word.upper()
        kind = accent_font if acc else regular
        if any(ord(c) > 0x24F and not _is_emoji(c) and c not in "’‘“”–—…•·" for c in word):
            kind = "unicode"                       # Hindi, Arabic, Cyrillic... never empty boxes
        f = font(kind, size * (scale or {}).get(i, 1.0))
        parts = []
        w = 0.0
        for kind, value in _pieces(word):
            if kind == "t":
                parts.append(("t", value, f.getlength(value)))
                w += f.getlength(value)
            else:
                if value not in glyphs:
                    glyphs[value] = emoji().draw(value, em)
                if glyphs[value] is not None:
                    parts.append(("e", value, em))
                    w += em
        if parts:
            items.append((parts, w, f, acc, i))
    if not items:
        return Image.new("RGBA", (width, 2), (0, 0, 0, 0))
    space = font(regular, size).getlength(" ")
    pad = stroke + 4
    limit = width - 2 * pad
    lines, cur, cur_w = [], [], 0.0
    for it in items:
        extra = it[1] + (space if cur else 0)
        if cur and cur_w + extra > limit:
            lines.append((cur, cur_w))
            cur, cur_w = [it], it[1]
        else:
            cur.append(it)
            cur_w += extra
    if cur:
        lines.append((cur, cur_w))
    line_h = int(size * line_gap)
    h = int(len(lines) * line_h + size * 0.45 + 2 * pad)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for row, (line, lw) in enumerate(lines):
        if align == "center":
            x = (width - lw) / 2
        elif align == "right":
            x = width - pad - lw
        else:
            x = pad
        base = pad + row * line_h + size
        for k, (parts, w, f, acc, _) in enumerate(line):
            if k:
                x += space
            ink = rgba(accent if acc else color)
            for kind, value, pw in parts:
                if kind == "t":
                    draw.text((x, base), value, font=f, fill=ink, anchor="ls",
                              stroke_width=stroke, stroke_fill=rgba(stroke_color))
                else:
                    g = glyphs[value]
                    img.alpha_composite(g, (int(x), int(base - em * 0.86)))
                x += pw
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sh.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(size * 0.12)).point(lambda a: int(a * 0.7)))
        out = Image.new("RGBA", img.size, (0, 0, 0, 0))
        out.alpha_composite(sh, (0, int(size * 0.05)))
        out.alpha_composite(img)
        img = out
    return img


def skew(img, k=0.2):
    """Lean an image to the right like italics (top moves right by k * height)."""
    if img is None or k == 0:
        return img
    h = img.height
    extra = int(math.ceil(abs(k) * h))
    return img.transform((img.width + extra, h), Image.AFFINE, (1, k, -k * h, 0, 1, 0),
                         resample=Image.BICUBIC)


def slab(text, size, max_width, kind="heavy", fg="FFFFFF", bg="000000", lean=0.2,
         pad=(0.42, 0.16), overlap=0.08):
    """Viral split-screen title: each line on its own black box, leaning like italics
    (the 'AIRPORTS IN GTA 6 ARE INSANE' look). Returns a transparent image."""
    f = font(kind, size)
    words = text.upper().split()
    if not words:
        return None
    px, py = int(size * pad[0]), int(size * pad[1])
    limit = max_width - 2 * px - int(lean * size * 2)
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and f.getlength(trial) > limit:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    lines.append(cur)
    asc, desc = f.getmetrics()
    cap = f.getbbox("H")
    text_h = cap[3] - cap[1]
    box_h = text_h + 2 * py + int(size * 0.12)
    step = int(box_h * (1 - overlap))
    widths = [int(f.getlength(l)) + 2 * px for l in lines]
    w = max(widths)
    img = Image.new("RGBA", (w, step * (len(lines) - 1) + box_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, (line, lw) in enumerate(zip(lines, widths)):
        x0 = (w - lw) // 2
        y0 = i * step
        d.rectangle((x0, y0, x0 + lw, y0 + box_h), fill=rgba(bg))
    for i, (line, lw) in enumerate(zip(lines, widths)):
        x0 = (w - lw) // 2
        y0 = i * step
        d.text((x0 + px, y0 + (box_h - text_h) / 2 - cap[1]), line, font=f, fill=rgba(fg))
    return skew(img, lean)


def save(img, path):
    path = Path(path)
    img.save(path)
    return path


# ------------------------------------------------------------------ stickers

def pill(text, size, bg="FFFFFF", fg="111111", kind="heavy", radius=0.32, pad=(0.6, 0.38),
         max_width=900):
    block = rich_block(parse_rich(text), size, max_width - int(size * pad[0] * 2), regular=kind,
                       accent_font=kind, color=fg, accent=fg, line_gap=1.2)
    box = block.getbbox() or (0, 0, block.width, block.height)
    block = block.crop(box)
    px, py = int(size * pad[0]), int(size * pad[1])
    w, h = block.width + 2 * px, block.height + 2 * py
    img = Image.new("RGBA", (w + 10, h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 9, w + 6, h + 9), radius=int(size * radius), fill=(0, 0, 0, 60))
    d.rounded_rectangle((0, 0, w, h), radius=int(size * radius), fill=rgba(bg))
    img.alpha_composite(block, (px, py))
    return img


def label(text, size, color="D8D8D8", spacing=0.32, kind="label"):
    """Letter-spaced small caps label: 'GTA 6  ·  SPEED'."""
    f = font(kind, size)
    text = text.upper()
    widths = [f.getlength(c) for c in text]
    gap = size * spacing
    w = int(sum(widths) + gap * (len(text) - 1) + 8)
    img = Image.new("RGBA", (max(w, 4), int(size * 1.5)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 4
    for c, cw in zip(text, widths):
        d.text((x, size * 1.1), c, font=f, fill=rgba(color), anchor="ls")
        x += cw + gap
    return img


def tag(text, size, bg="E3001B", fg="FFFFFF", kind="condensed"):
    f = font(kind, size)
    w = int(f.getlength(text.upper()) + size * 0.9)
    h = int(size * 1.35)
    img = Image.new("RGBA", (w, h), rgba(bg))
    ImageDraw.Draw(img).text((w / 2, h * 0.52), text.upper(), font=f, fill=rgba(fg), anchor="mm")
    return img


def ticker(text, size, height, fg="FFFFFF", kind="condensed"):
    """One long strip of text (transparent background) for a scrolling news ticker."""
    f = font(kind, size)
    text = "".join(c for c in text if not _is_emoji(c)).strip()
    text = "   •   ".join([text.upper()] * 3) + "   •   "
    w = int(f.getlength(text) + 20)
    img = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((10, height * 0.54), text, font=f, fill=rgba(fg), anchor="lm")
    return img


def bar(w, h, color, alpha=255):
    return Image.new("RGBA", (w, h), rgba(color, alpha))


def circle_mask(d):
    big = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    return big.resize((d, d), Image.LANCZOS)


def round_mask(w, h, r):
    big = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius=r * 3, fill=255)
    return big.resize((w, h), Image.LANCZOS)


def round_box(w, h, r, color):
    big = Image.new("RGBA", (w * 3, h * 3), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius=r * 3, fill=rgba(color))
    return big.resize((w, h), Image.LANCZOS)


def ring(d, width, color):
    big = Image.new("RGBA", (d * 4, d * 4), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, d * 4 - 1, d * 4 - 1), outline=rgba(color), width=width * 4)
    return big.resize((d, d), Image.LANCZOS)


def credit(name, size, color="9A9A9A", prefix="🎮 "):
    return rich_block([(w, False) for w in (prefix + name).split()], size, 900, regular="clean",
                      color=color, align="left").crop((0, 0, 900, int(size * 1.7)))


# ------------------------------------------------------------------ captions

BREATH = 1.0


def phrases(words, size):
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 9
        punct = w["w"].endswith((".", "!", "?")) or (w["w"].endswith(",") and len(cur) >= 2)
        if len(cur) >= size or nxt > 0.6 or (punct and (len(cur) >= 2 or nxt > 0.25)):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _foreign(c):
    return ord(c) > 0x24F and not _is_emoji(c) and c not in "’‘“”–—…•·´"


def _clean(word):
    word = re.sub(r"[{}\\]", "", word).strip()
    return "" if not word.strip("*") else word        # keep the stars of a masked swear (f**k)


SLURS = re.compile(r"^(nigg(a|er|ah|uh)s?z?|niggaz|fag(got)?s?|retard(ed|s)?|cunts?|tr[a@]nn(y|ies))$", re.I)
SWEARS = re.compile(r"^(mother)?f+u+c*k+\w*|^(bull)?shit(s|ty|ting|ted|ter)?$|^bitch(es|y|ing)?$|^dick(s|head)?$|^puss(y|ies)$|^ass(hole)?s?$", re.I)


def mask(word, level="slurs"):
    """On-screen caption text only (the audio is never touched). level: "off" = as said,
    "slurs" = slurs starred (n****) because TikTok/Reels scan on-screen text for them,
    "all" = swears softened too (f**k)."""
    core = re.sub(r"^\W+|\W+$", "", word)
    if not core or level == "off":
        return word
    lead, tail = word[:word.find(core)], word[word.find(core) + len(core):]
    if SLURS.match(core):
        return lead + core[0] + "*" * (len(core) - 1) + tail
    if level == "all" and SWEARS.match(core) and len(core) > 2:
        return lead + core[0] + "*" * (len(core) - 2) + core[-1] + tail
    return word


def captions(words, length, style, folder, width):
    """Write one PNG per caption state + an ffconcat list. Returns (list_path, band_height).
    style: font, size, color, active, pop, stroke, upper, words, shadow."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("cap_*.png"):
        old.unlink()
    size = style["size"]
    band = int(size * (2.0 + 1.4 * (style.get("lines", 1) - 1)) + 2 * style.get("stroke", 0) + 20)
    blank = folder / "cap_blank.png"
    Image.new("RGBA", (width, band), (0, 0, 0, 0)).save(blank)
    words = [w for w in words if w["e"] > 0 and w["s"] < length and _clean(w["w"])]
    latin = [w for w in words if not any(_foreign(c) for c in w["w"])]
    if words and len(latin) >= 0.7 * len(words):
        # mostly Latin speech: stray CJK/other characters are Whisper mishearing, drop them
        fixed = []
        for w in words:
            kept = "".join(c for c in w["w"] if not _foreign(c))
            if kept != w["w"] and len(_clean(kept).strip("´'")) <= 1:
                continue                      # only a stray letter was left: drop the word
            if _clean(kept):
                fixed.append(dict(w, w=kept))
        words = fixed
    groups = phrases(words, style.get("words", 3))
    events = []                                  # (start, end, image path)
    cache = {}
    for gi, group in enumerate(groups):
        texts = [_clean(w["w"]) for w in group]
        hard_stop = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else length
        for wi, w in enumerate(group):
            start = max(0.0, w["s"])
            if wi + 1 < len(group):
                end = group[wi + 1]["s"]
            elif hard_stop - w["e"] < BREATH:
                end = hard_stop
            else:
                end = w["e"] + 0.35
            end = min(max(end, start + 0.06), length)
            active = wi if style.get("active") else None
            key = (gi, active)
            if key not in cache:
                rich = [(t, j == active) for j, t in enumerate(texts)]
                img = rich_block(rich, size, width - 2 * style.get("margin", 70),
                                 regular=style["font"], accent_font=style["font"],
                                 color=style["color"], accent=style.get("active") or style["color"],
                                 stroke=style.get("stroke", 0), shadow=style.get("shadow", False),
                                 scale={active: style.get("pop", 1.0)} if active is not None else None,
                                 upper=style.get("upper", False), line_gap=1.15)
                if style.get("lean"):
                    img = skew(img.crop(img.getbbox() or (0, 0, img.width, img.height)), style["lean"])
                    if img.width > width:
                        img = img.crop((0, 0, width, img.height))
                canvas = Image.new("RGBA", (width, band), (0, 0, 0, 0))
                y = max(0, (band - img.height) // 2)
                canvas.alpha_composite(img.crop((0, 0, img.width, min(img.height, band))),
                                       ((width - img.width) // 2, y))
                path = folder / f"cap_{len(cache):04d}.png"
                canvas.save(path)
                cache[key] = path
            events.append((start, end, cache[key]))
    events.sort()
    lines = ["ffconcat version 1.0"]
    t = 0.0
    for start, end, path in events:
        if start < t:
            start = t
        if end <= start:
            continue
        if start - t > 0.01:
            lines += [f"file '{blank.name}'", f"duration {start - t:.3f}"]
        lines += [f"file '{path.name}'", f"duration {end - start:.3f}"]
        t = end
    if length - t > 0.01:
        lines += [f"file '{blank.name}'", f"duration {length - t:.3f}"]
    lines += [f"file '{blank.name}'"]
    listing = folder / "captions.ffconcat"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing, band


# ------------------------------------------------------------------ sounds

def _write_wav(path, samples, rate=48000):
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path


def whoosh(path, seconds=0.7, rate=48000):
    """Filtered noise that swells and fades: the classic hook whoosh."""
    n = int(seconds * rate)
    t = np.linspace(0, 1, n)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    # sweep a simple one-pole low-pass from dark to bright and back
    cut = 0.02 + 0.25 * np.sin(np.pi * t) ** 2
    out = np.zeros(n)
    y = 0.0
    for i in range(n):
        y += cut[i] * (noise[i] - y)
        out[i] = y
    env = np.sin(np.pi * np.clip(t * 1.15, 0, 1)) ** 2
    out = out * env
    out /= max(1e-6, np.abs(out).max())
    return _write_wav(path, out * 0.55, rate)


def pop(path, seconds=0.16, rate=48000):
    """A short low thump for punch-ins."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    freq = 150 * np.exp(-t * 18) + 55
    phase = 2 * math.pi * np.cumsum(freq) / rate
    out = np.sin(phase) * np.exp(-t * 26)
    return _write_wav(path, out * 0.8, rate)
