"""상세 옵션표 → 2열 그림.

네이버 스마트스토어 모바일은 상세에 표(table)·링크(a)·네이버 밖 이미지가 있으면 HTML을 그대로 보여 주지 않고
PC 화면을 캡처한 그림(흐림, '원본보기'를 눌러야 선명)을 보여 준다. 또 네이버는 grid·flex 같은 배치 CSS를 지워
옵션 사진이 한 줄에 하나씩 쌓인다. 그래서 옵션표를 표나 CSS 대신 2열 그림으로 그려 네이버 이미지 서버에 올린다.
CSS를 쓰지 않으니 어떤 화면에서도 2열이 그대로이고, 상세는 사진(<img>)만이라 모바일에서도 HTML 그대로(선명) 나온다.

box = {"title": 색 띠에 넣을 제목('' 이면 띠 없음), "cards": [[사진 주소들], 옵션 이름]}
"""

import hashlib
import io
import json
import math
import os

from . import config

VER = "1"                 # 그림 모양을 바꾸면 올려 둔 그림을 다시 만들도록 키에 넣는다
W = 1000                  # 그림 너비 (네이버 상세 860px보다 조금 크게 — 휴대폰 고해상도 화면에서도 선명)
SIDE, GAP, ROW_GAP = 20, 24, 28
ROWS_PER_IMAGE = 3        # 그림 한 장에 2열 × 3줄까지 (옵션이 많으면 여러 장을 이어 붙임)
MAX_LINES = 4
DIR = os.path.join(config.DATA_DIR, "optimg")

BOLD = [r"C:\Windows\Fonts\malgunbd.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
REGULAR = [r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"] + BOLD


class OptionImageError(Exception):
    pass


def key(box, style, color):
    raw = json.dumps([VER, style, color, box.get("title") or "", box["cards"]], ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def count(n_cards):
    """옵션 칸 수 → 그림 장 수."""
    return max(1, math.ceil(math.ceil(n_cards / 2) / ROWS_PER_IMAGE))


_fonts = {}


def _font(size, bold):
    from PIL import ImageFont
    k = (size, bold)
    if k not in _fonts:
        for f in (BOLD if bold else REGULAR):
            if os.path.exists(f):
                try:
                    _fonts[k] = ImageFont.truetype(f, size)
                    break
                except OSError:
                    continue
        else:
            raise OptionImageError("한글 글꼴(맑은 고딕)을 찾지 못해 옵션표 그림을 만들 수 없습니다.")
    return _fonts[k]


def _photo(data):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        if os.environ.get("UPLOADER_FAKE_API") == "1":   # 시연 모드: 가짜 사진
            return Image.new("RGB", (600, 600), (201, 206, 214))
        raise OptionImageError("옵션 사진을 그림으로 열지 못했습니다.")
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def _wrap(text, font, width):
    """글자 폭에 맞춰 줄 나눔 (띄어쓰기 우선, 긴 단어는 글자 단위). 최대 MAX_LINES줄, 넘으면 …"""
    lines, cur = [], ""
    for word in text.split(" "):
        cand = f"{cur} {word}" if cur else word
        if font.getlength(cand) <= width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:
            if font.getlength(cur + ch) <= width:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
    if cur:
        lines.append(cur)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        while lines[-1] and font.getlength(lines[-1] + "…") > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines or [""]


def render(box, style, color, fetch):
    """box → JPEG 바이트 목록 (2열 × 최대 3줄씩). fetch(주소) → 사진 바이트."""
    from PIL import Image, ImageDraw
    strong = style == "strong"
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    bw, line_c, bg = (4, rgb, (245, 246, 248)) if strong else (2, (234, 236, 240), (255, 255, 255))
    cap_font = _font(38 if strong else 34, strong)
    cap_pad, line_h = (20, 52) if strong else (16, 46)
    cw = (W - SIDE * 2 - GAP) // 2          # 칸 너비
    inner = cw - bw * 2
    cards = []
    for srcs, cap in box["cards"]:
        photos = []
        for u in srcs:
            p = _photo(fetch(u))
            h = max(1, round(p.height * inner / p.width))
            photos.append(p.resize((inner, min(h, inner * 2)), Image.LANCZOS))
        cards.append((photos, _wrap(cap, cap_font, inner - 24) if cap else []))
    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    out = []
    for n, part in enumerate(rows[i:i + ROWS_PER_IMAGE] for i in range(0, len(rows), ROWS_PER_IMAGE)):
        band = 120 if strong and n == 0 and box.get("title") else 0
        sizes = []
        for row in part:
            ph = max(sum(p.height for p in c[0]) for c in row)
            nl = max(len(c[1]) for c in row)
            sizes.append((ph, nl * line_h + cap_pad * 2 if nl else 0))
        height = band + 24 + sum(ph + capt + bw * 2 for ph, capt in sizes) + ROW_GAP * (len(part) - 1) + 24
        im = Image.new("RGB", (W, height), (255, 255, 255))
        d = ImageDraw.Draw(im)
        if band:
            title, num = box["title"], f"  총 {len(box['cards'])}종" if "옵션" in box["title"] else ""
            tf, nf = _font(52, True), _font(34, False)
            tw = tf.getlength(title) + (nf.getlength(num) if num else 0)
            d.rectangle([0, 0, W, band], fill=rgb)
            x = (W - tw) / 2
            d.text((x, band / 2), title, font=tf, fill=(255, 255, 255), anchor="lm")
            if num:
                d.text((x + tf.getlength(title), band / 2 + 4), num, font=nf, fill=(255, 255, 255), anchor="lm")
        y = band + 24
        for row, (ph, capt) in zip(part, sizes):
            for col, (photos, lines) in enumerate(row):
                x0 = (W - cw) // 2 if len(cards) == 1 else SIDE + col * (cw + GAP)   # 옵션이 하나면 가운데
                d.rectangle([x0, y, x0 + cw - 1, y + ph + capt + bw * 2 - 1], fill=bg, outline=line_c, width=bw)
                py = y + bw + (ph - sum(p.height for p in photos)) // 2   # 사진은 칸 가운데
                for p in photos:
                    im.paste(p, (x0 + bw, py))
                    py += p.height
                cy = y + bw + ph + cap_pad
                for ln in lines:
                    d.text((x0 + cw / 2, cy + line_h / 2), ln, font=cap_font, fill=(17, 17, 17), anchor="mm")
                    cy += line_h
            y += ph + capt + bw * 2 + ROW_GAP
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
        out.append(buf.getvalue())
    return out


def build(box, style, color, fetch):
    """디스크에 만들어 둔 그림이 있으면 그것, 없으면 그려서 저장. → JPEG 바이트 목록."""
    k = key(box, style, color)
    paths = [os.path.join(DIR, f"{k}_{i}.jpg") for i in range(count(len(box["cards"])))]
    if all(os.path.exists(p) for p in paths):
        return [open(p, "rb").read() for p in paths]
    imgs = render(box, style, color, fetch)
    os.makedirs(DIR, exist_ok=True)
    for p, data in zip(paths, imgs):
        with open(p, "wb") as f:
            f.write(data)
    return imgs


def remember(box, style, color):
    """화면 미리보기용: 나중에 주소로 그릴 수 있게 내용을 적어 둔다. → 키"""
    k = key(box, style, color)
    p = os.path.join(DIR, f"{k}.json")
    if not os.path.exists(p):
        os.makedirs(DIR, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"box": box, "style": style, "color": color}, f, ensure_ascii=False)
    return k


def preview(k, i, fetch):
    """remember로 적어 둔 옵션표의 i번째 그림 (없으면 None)."""
    p = os.path.join(DIR, f"{os.path.basename(k)}.json")
    if not os.path.exists(p):
        return None
    spec = json.load(open(p, encoding="utf-8"))
    imgs = build(spec["box"], spec["style"], spec["color"], fetch)
    return imgs[i] if 0 <= i < len(imgs) else None
