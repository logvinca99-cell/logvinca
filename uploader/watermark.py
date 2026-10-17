"""대표 이미지에 스토어 워터마크를 넣는다 (스토어마다 다르게).

워터마크: 스토어 화면에서 올린 로고 PNG(투명 배경 권장), 없으면 글자(스토어 이름 또는 직접 정한 글자).
위치: 네 모서리 또는 위·아래 가운데.

직사각형 이미지는 네이버 목록에서 가운데 정사각형으로 잘려 보이므로, 기본(safe)은
'가운데 정사각형' 안쪽 모서리에 넣는다 → 잘려도 보이고, 상세에서 전체가 보여도 어색하지 않다.
pad를 고르면 이미지를 흰 여백으로 정사각형으로 만든 뒤 넣는다(상품이 잘리지 않음).
"""

import hashlib
import io
import os

from . import config

WM_DIR = os.path.join(config.DATA_DIR, "watermarks")
FONTS = [
    r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def logo_path(store_id):
    return os.path.join(WM_DIR, f"store_{store_id}.png")


def enabled(cfg):
    return bool(cfg.get("wm_enabled"))


def signature(cfg, store):
    """설정·로고가 바뀌면 다시 올리도록 이미지 저장 키에 붙이는 값."""
    p = logo_path(store["id"])
    parts = [str(cfg.get(k)) for k in ("wm_position", "wm_size_pct", "wm_opacity", "wm_margin_pct", "wm_square")]
    parts += [store.get("wm_text") or store.get("name") or "", str(os.path.getmtime(p)) if os.path.exists(p) else ""]
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:10]


def _font(size):
    from PIL import ImageFont
    for f in [config.load().get("wm_font")] + FONTS:
        if f and os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_mark(text, width):
    """글자 워터마크: 반투명 어두운 둥근 상자에 흰 글자."""
    from PIL import Image, ImageDraw
    size = max(12, int(width / max(4, len(text)) * 1.3))
    font = _font(size)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = tmp.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad = int(size * 0.45)
    im = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=int(size * 0.4), fill=(0, 0, 0, 140))
    d.text((pad - box[0], pad - box[1]), text, font=font, fill=(255, 255, 255, 255))
    return im


def _mark(store, side, cfg):
    from PIL import Image
    width = max(40, int(side * float(cfg.get("wm_size_pct") or 22) / 100))
    p = logo_path(store["id"])
    if os.path.exists(p):
        m = Image.open(p).convert("RGBA")
        h = int(m.height * width / m.width)
        m = m.resize((width, max(1, h)), Image.LANCZOS)
    else:
        m = _text_mark(store.get("wm_text") or store.get("name") or "", width * 2)  # 크게 그려 줄이면 글자가 또렷함
        m = m.resize((width, max(1, int(m.height * width / m.width))), Image.LANCZOS)
    op = float(cfg.get("wm_opacity") if cfg.get("wm_opacity") is not None else 0.85)
    if op < 1:
        a = m.getchannel("A").point(lambda v: int(v * op))
        m.putalpha(a)
    return m


def place(w, h, mw, mh, cfg):
    """워터마크 왼쪽 위 좌표. 가운데 정사각형(잘려 보이는 범위) 안쪽 기준."""
    side = min(w, h)
    x0, y0 = (w - side) // 2, (h - side) // 2
    if cfg.get("wm_square") == "full":
        x0, y0, sw, sh = 0, 0, w, h
    else:
        sw = sh = side
    margin = int(min(sw, sh) * float(cfg.get("wm_margin_pct") or 3) / 100)
    pos = cfg.get("wm_position") or "bottom-right"
    vert, horiz = (pos.split("-") + ["right"])[:2]
    x = {"left": x0 + margin, "center": x0 + (sw - mw) // 2, "right": x0 + sw - mw - margin}[horiz]
    y = y0 + margin if vert == "top" else y0 + sh - mh - margin
    return x, y


def apply(data, store, cfg):
    """이미지 바이트 → 워터마크 넣은 JPEG 바이트."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("RGB")
    if cfg.get("wm_square") == "pad" and im.width != im.height:
        side = max(im.width, im.height)
        bg = Image.new("RGB", (side, side), (255, 255, 255))
        bg.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        im = bg
    m = _mark(store, min(im.width, im.height), cfg)
    x, y = place(im.width, im.height, m.width, m.height, cfg)
    im.paste(m, (x, y), m)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


def sample(w, h):
    """미리보기용 회색 그라데이션 이미지 + 가운데 정사각형 표시."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (225, 228, 232))
    d = ImageDraw.Draw(im)
    for i in range(0, w + h, 40):
        d.line([(i, 0), (0, i)], fill=(210, 214, 220), width=12)
    side = min(w, h)
    x0, y0 = (w - side) // 2, (h - side) // 2
    d.rectangle([x0, y0, x0 + side - 1, y0 + side - 1], outline=(30, 160, 90), width=max(2, side // 150))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()
