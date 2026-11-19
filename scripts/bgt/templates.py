"""The five edit templates. Each one turns the source clip into a finished 1080x1920 frame
with ffmpeg + Pillow graphics. Clean rules shared by all of them:
  - one accent colour, at most two fonts, nothing in the platform UI zones
    (TikTok/Reels right rail and bottom caption block, IG's 4:5 feed crop)
  - hook text in the first second, captions every word, a soft whoosh on the hook

  hookcard   story sentence on black, *accent words* in bold red, gameplay 5:4 in the middle,
             red captions on the clip, empty band below (the memezar / viral reel look)
  stack      facecam on top, gameplay below, title sticker on the join, pop captions,
             punch-in zooms on the loudest seconds
  bubble     full-screen gameplay, the streamer's face in a small round bubble at the bottom,
             big 2-word pop captions, title sticker for the first 3 seconds, punch-ins
  cinematic  blurred backdrop, wide clip with a slow push-in, letter-spaced label, quiet
             subtitles, fade in/out
  news       BREAKING tag, condensed headline, clip, red ticker scrolling, source line
"""

from . import art
from .common import even

W, H = 1080, 1920

ACCENT = {"hookcard": "FF3B3B", "stack": "FFD400", "bubble": "FFD400", "cinematic": "E9C46A",
          "news": "E3001B"}


class Graph:
    def __init__(self, folder, fps, length):
        self.folder = folder
        self.fps = fps
        self.length = length
        self.inputs = []          # extra ffmpeg input arg lists (index 1, 2, ...)
        self.chains = []
        self.n = 0
        self.last = None

    def image(self, img, name):
        path = art.save(img, self.folder / f"{name}.png")
        self.inputs.append(["-i", str(path)])
        return f"{len(self.inputs)}:v"

    def concat(self, listing):
        self.inputs.append(["-f", "concat", "-safe", "0", "-i", str(listing)])
        return f"{len(self.inputs)}:v"

    def label(self):
        self.n += 1
        return f"v{self.n}"

    def add(self, chain):
        self.chains.append(chain)

    def over(self, src, x, y, enable=None, name=None):
        """Overlay input `src` onto the current picture."""
        out = name or self.label()
        en = f":enable='{enable}'" if enable else ""
        self.add(f"[{self.last}][{src}]overlay=x={x}:y={y}:eof_action=repeat{en}[{out}]")
        self.last = out
        return out

    def place(self, img, name, x, y, enable=None):
        if img is None or img.width < 3:
            return None
        if x == "center":
            x = (W - img.width) // 2
        return self.over(self.image(img, name), int(x), int(y), enable)

    def captions(self, words, style, y_center):
        if not words:
            return
        listing, band = art.captions(words, self.length, style, self.folder / "caps", W)
        self.over(self.concat(listing), 0, int(y_center - band / 2))


# ------------------------------------------------------------------ helpers

def window(info, aspect, cam=None):
    """A crop of the source with width/height = aspect, centred, slid away from the cam."""
    sw, sh = info["width"], info["height"]
    if sw / sh > aspect:
        cw, ch = sh * aspect, sh
    else:
        cw, ch = sw, sw / aspect
    cx, cy = (sw - cw) / 2, (sh - ch) / 2
    if cam:
        x, _, w, _ = cam
        if cx < x + w and cx + cw > x and cw < sw:     # never show a sliver of the facecam
            pad = 0.18 * w + 16                       # detected boxes can miss the border
            if x + w / 2 < sw / 2:
                cx = min(sw - cw, x + w + pad)
            else:
                cx = max(0.0, x - cw - pad)
    return even(cw), even(ch), even(cx), even(cy)


def punch(g, src, w, h, windows, zoom=1.14):
    """Quick zoom-in (jump cut style) on the loudest seconds. Returns the new label."""
    if not windows:
        return src
    a, b, z, out = g.label(), g.label(), g.label(), g.label()
    expr = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in windows)
    g.add(f"[{src}]split=2[{a}][{b}]")
    g.add(f"[{b}]scale={even(w * zoom)}:{even(h * zoom)}:flags=lanczos,crop={w}:{h}[{z}]")
    g.add(f"[{a}][{z}]overlay=0:0:enable='{expr}'[{out}]")
    return out


def background(g, color="000000"):
    out = g.label()
    g.add(f"color=c=0x{color}:s={W}x{H}:r={g.fps:.3f}:d={g.length + 0.5:.3f}[{out}]")
    g.last = out
    return out


def clip_box(g, info, aspect, w, h, cam=None, grade=None):
    cw, ch, cx, cy = window(info, aspect, cam)
    out = g.label()
    extra = f",{grade}" if grade else ""
    g.add(f"[src_main]crop={cw}:{ch}:{cx}:{cy},scale={w}:{h}:flags=lanczos,setsar=1{extra}[{out}]")
    return out


def hook_words(pick, field="hook"):
    text = pick.get(field) or pick.get("title") or ""
    return art.parse_rich(text)


def creator_credit(g, ctx, x, y, color="9A9A9A"):
    if ctx["cfg"].get("show_creator", True) and ctx.get("creator"):
        g.place(art.credit(ctx["creator"], 30, color), "credit", x, y)


# ------------------------------------------------------------------ templates

def hookcard(g, ctx):
    info, pick, accent = ctx["info"], ctx["pick"], ctx["accent"]
    clip_w, clip_h = W, 864                                  # 5:4, like the viral reels
    clip_y = (H - clip_h) // 2 + 60
    background(g, "000000")
    clip = clip_box(g, info, 1.25, clip_w, clip_h, ctx.get("cam"))
    g.over(clip, 0, clip_y)
    hook = art.rich_block(hook_words(pick), 56, W - 110, regular="clean", accent_font="clean_bold",
                          color="FFFFFF", accent=accent, line_gap=1.3)
    hook = hook.crop(hook.getbbox() or (0, 0, hook.width, hook.height))
    g.place(hook, "hook", "center", clip_y - 46 - hook.height)
    # captions just under the gameplay: never on top of the game's own subtitles
    g.captions(ctx["words"], {"font": "rounded", "size": 58, "color": accent, "stroke": 6,
                              "words": 4, "margin": 80}, clip_y + clip_h + 62)
    creator_credit(g, ctx, 56, clip_y + clip_h + 120)


def stack(g, ctx):
    info, pick, accent, cfg = ctx["info"], ctx["pick"], ctx["accent"], ctx["cfg"]
    cam = ctx["cam"]
    top = even(H * cfg["cam_share"])
    low = H - top
    sw, sh = info["width"], info["height"]
    x, y, w, h = cam
    aim = W / top
    cw, ch = (h * aim, h) if w / h > aim else (w, w / aim)
    face = ctx.get("face")
    if face:                                   # centre on the face, not on the whole overlay
        fcx, fcy = face[0] + face[2] / 2, face[1] + face[3] / 2
        cx = min(max(fcx - cw / 2, x), x + w - cw)
        cy = min(max(fcy - ch * 0.45, y), y + h - ch)
    else:
        cx, cy = x + (w - cw) / 2, y + (h - ch) / 2
    cx = min(max(cx, 0), sw - cw)
    cy = min(max(cy, 0), sh - ch)
    gw, gh, gx, gy = window(info, W / low, cam)
    c1, g1, out = g.label(), g.label(), g.label()
    g.add(f"[src_cam]crop={even(cw)}:{even(ch)}:{even(cx)}:{even(cy)},scale={W}:{top}:flags=lanczos,setsar=1[{c1}]")
    g.add(f"[src_main]crop={gw}:{gh}:{gx}:{gy},scale={W}:{low}:flags=lanczos,setsar=1[{g1}]")
    g1 = punch(g, g1, W, low, ctx["punches"])
    g.add(f"[{c1}][{g1}]vstack=inputs=2,format=yuv420p[{out}]")
    g.last = out
    title = (pick.get("title") or "").upper()
    if title:
        sticker = art.pill(title, 54, bg="FFFFFF", fg="111111", max_width=W - 160)
        g.place(sticker, "title", "center", top - sticker.height // 2)
    if cfg.get("show_creator", True) and ctx.get("creator"):
        g.place(art.pill(ctx["creator"], 28, bg="111111", fg="FFFFFF", kind="label"), "chip", 40, 70)
    g.captions(ctx["words"], {"font": "heavy", "size": 78, "color": "FFFFFF", "active": accent,
                              "pop": 1.12, "stroke": 8, "upper": True, "words": 3},
               int(H * 0.70))


def bubble(g, ctx):
    info, pick, accent = ctx["info"], ctx["pick"], ctx["accent"]
    cam = ctx.get("cam")
    if ctx.get("talking_graph"):
        base = g.label()
        g.add(ctx["talking_graph"].replace("[0:v]", "[src_main]").replace("[framed]", f"[{base}]"))
    else:
        base = clip_box(g, info, W / H, W, H, cam)
    base = punch(g, base, W, H, ctx["punches"])
    g.last = base
    if cam:
        x, y, w, h = cam
        face = ctx.get("face")
        if face:                               # a tight circle around the face
            side = min(w, h, face[3] * 2.6, face[2] * 3.0)
            sx = face[0] + face[2] / 2 - side / 2
            sy = face[1] + face[3] * 0.55 - side / 2
        else:
            side = min(w, h) * 0.92
            sx, sy = x + (w - side) / 2, y + (h - side) / 2
        sx = min(max(sx, 0), info["width"] - side)
        sy = min(max(sy, 0), info["height"] - side)
        d = 340
        m, cm, cb = g.label(), g.label(), g.label()
        mask = g.image(art.circle_mask(d), "mask")
        g.add(f"[src_cam]crop={even(side)}:{even(side)}:{even(sx)}:{even(sy)},scale={d}:{d}:flags=lanczos,"
              f"format=rgba[{cm}]")
        g.add(f"[{mask}]format=gray,scale={d}:{d}[{m}]")
        g.add(f"[{cm}][{m}]alphamerge[{cb}]")
        by = H - 440 - d                         # bottom-left, above the app's caption area
        g.over(cb, 56, by)
        g.place(art.ring(d + 16, 7, accent), "ring", 48, by - 8)
    title = (pick.get("title") or "").upper()
    if title:
        sticker = art.pill(title, 62, bg="FFFFFF", fg="111111", max_width=W - 140)
        g.place(sticker, "title", "center", int(H * 0.22), enable="between(t,0,3.2)")
    g.captions(ctx["words"], {"font": "heavy", "size": 84, "color": "FFFFFF", "active": accent,
                              "pop": 1.12, "stroke": 9, "upper": True, "words": 2, "margin": 40},
               int(H * 0.50))
    if ctx["cfg"].get("show_creator", True) and ctx.get("creator"):
        chip = art.pill(ctx["creator"], 28, bg="111111", fg="FFFFFF", kind="label")
        g.place(chip, "chip", W - 50 - chip.width, 96)


def cinematic(g, ctx):
    info, pick, accent, fps, length = ctx["info"], ctx["pick"], ctx["accent"], g.fps, g.length
    fw, fh = W, 608
    fy = (H - fh) // 2 - 10
    bg, fg, out = g.label(), g.label(), g.label()
    frames = max(1, int(length * fps))
    cw, ch, cx, cy = window(info, 16 / 9, ctx.get("cam"))
    g.add(f"[src_bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"boxblur=30:3,eq=brightness=-0.30:saturation=0.75,vignette=PI/4,setsar=1[{bg}]")
    g.add(f"[src_main]crop={cw}:{ch}:{cx}:{cy},scale=2160:1216:flags=lanczos,"
          f"zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
          f"s={fw}x{fh}:fps={fps:.3f},eq=contrast=1.06:saturation=1.12,setsar=1[{fg}]")
    g.add(f"[{bg}][{fg}]overlay=0:{fy}[{out}]")
    g.last = out
    topic = ctx.get("topic") or ""
    lab = art.label("  ·  ".join(x for x in (topic, ctx.get("creator") or "") if x), 28, "D0D0D0")
    title = art.rich_block(art.parse_rich(pick.get("headline") or pick.get("title") or ""), 50, W - 160,
                           regular="elegant", accent_font="elegant", color="FFFFFF", accent=accent)
    title = title.crop(title.getbbox() or (0, 0, title.width, title.height))
    g.place(title, "title", "center", fy - 60 - title.height)
    g.place(lab, "label", "center", fy - 60 - title.height - 34 - lab.height)
    g.captions(ctx["words"], {"font": "clean", "size": 44, "color": "FFFFFF", "shadow": True,
                              "words": 7, "lines": 2, "margin": 110}, fy + fh + 120)
    last = g.label()
    g.add(f"[{g.last}]fade=t=in:st=0:d=0.5,fade=t=out:st={max(0.0, length - 0.6):.2f}:d=0.6[{last}]")
    g.last = last


def news(g, ctx):
    info, pick, accent = ctx["info"], ctx["pick"], ctx["accent"]
    clip_w, clip_h = W, 608
    background(g, "0B0B0F")
    t = art.tag("Breaking", 46, bg=accent)
    g.place(t, "tag", 56, 300)
    if ctx.get("creator"):
        g.place(art.label(f"{ctx['creator']}  ·  live", 26, "BBBBBB"), "who", 56 + t.width + 22,
                300 + (t.height - 39) // 2)
    head = art.rich_block(art.parse_rich((pick.get("headline") or pick.get("title") or "").upper().replace("*", "")),
                          88, W - 100, regular="condensed", accent_font="condensed", color="FFFFFF",
                          align="left", line_gap=1.0)
    head = head.crop(head.getbbox() or (0, 0, head.width, head.height))
    head_y = 300 + t.height + 34
    g.place(head, "headline", 54, head_y)
    clip_y = max(head_y + head.height + 50, 720)
    clip = clip_box(g, info, 16 / 9, clip_w, clip_h, None, grade="eq=contrast=1.04:saturation=1.08")
    g.over(clip, 0, clip_y)
    g.place(art.bar(W, 8, accent), "line", 0, clip_y + clip_h)
    bar_y = clip_y + clip_h + 8
    g.place(art.bar(W, 72, "16161C"), "tickerbar", 0, bar_y)
    text = (pick.get("caption") or pick.get("headline") or "").split("#")[0].strip()
    strip = art.ticker(f"{text}  •  clipped from {ctx.get('creator') or 'the stream'}", 36, 72)
    src = g.image(strip, "ticker")
    out = g.label()
    g.add(f"[{g.last}][{src}]overlay=x='W-mod(t*170,W+w)':y={bar_y}[{out}]")
    g.last = out
    g.captions(ctx["words"], {"font": "heavy", "size": 58, "color": "FFFFFF", "active": "FFD400",
                              "pop": 1.08, "stroke": 7, "upper": True, "words": 3},
               bar_y + 72 + 64)
    g.place(art.label(f"source: {ctx.get('creator') or 'stream'}", 24, "8A8A8A"), "source", 56,
            bar_y + 72 + 130)


BUILDERS = {"hookcard": hookcard, "stack": stack, "bubble": bubble, "cinematic": cinematic,
            "news": news}


def resolve(wanted, analysis):
    """The template actually used: stack needs a facecam; everything else always works."""
    if wanted == "stack" and not analysis.get("cam"):
        return "bubble" if analysis.get("talking_graph") else "hookcard"
    return wanted


def build(name, ctx, folder, fps, length):
    """Returns (extra input args, filter_complex video part ending in [vout])."""
    g = Graph(folder, fps, length)
    g.add("[0:v]setsar=1,split=3[src_main][src_cam][src_bg]")
    BUILDERS[name](g, ctx)
    g.add(f"[{g.last}]format=yuv420p,setsar=1[vout]")
    graph = ";".join(g.chains)
    for lab in ("src_main", "src_cam", "src_bg"):      # unused copies must still be consumed
        if graph.count(f"[{lab}]") == 1:
            graph += f";[{lab}]nullsink"
    args = [a for inp in g.inputs for a in inp]
    return args, graph
