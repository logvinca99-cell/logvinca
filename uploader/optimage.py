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


NEW_STYLES = ("a", "b", "c", "d", "e")   # 시안 A~E: 그 스토어 이름이 그림에 들어감
VER_NEW = "2"


def key(box, style, color, store_name=""):
    """같은 그림이면 같은 키 (한 번 올린 그림은 다시 씀). 새 모양(a~e)은 스토어 이름이 들어가므로 키에도 넣는다."""
    if style in NEW_STYLES:
        raw = json.dumps([VER_NEW, style, color, store_name or "", box.get("title") or "", box["cards"]], ensure_ascii=False)
    else:
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


def render(box, style, color, fetch, store_name=""):
    """box → JPEG 바이트 목록 (2열 × 최대 3줄씩). fetch(주소) → 사진 바이트."""
    if style in NEW_STYLES:
        return _render_new(box, style, color, fetch, store_name or "")
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


def build(box, style, color, fetch, store_name=""):
    """디스크에 만들어 둔 그림이 있으면 그것, 없으면 그려서 저장. → JPEG 바이트 목록."""
    k = key(box, style, color, store_name)
    paths = [os.path.join(DIR, f"{k}_{i}.jpg") for i in range(count(len(box["cards"])))]
    if all(os.path.exists(p) for p in paths):
        return [open(p, "rb").read() for p in paths]
    imgs = render(box, style, color, fetch, store_name)
    os.makedirs(DIR, exist_ok=True)
    for p, data in zip(paths, imgs):
        with open(p, "wb") as f:
            f.write(data)
    return imgs


def remember(box, style, color, store_name=""):
    """화면 미리보기용: 나중에 주소로 그릴 수 있게 내용을 적어 둔다. → 키"""
    k = key(box, style, color, store_name)
    p = os.path.join(DIR, f"{k}.json")
    if not os.path.exists(p):
        os.makedirs(DIR, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"box": box, "style": style, "color": color, "store": store_name or ""}, f, ensure_ascii=False)
    return k


def preview(k, i, fetch):
    """remember로 적어 둔 옵션표의 i번째 그림 (없으면 None)."""
    p = os.path.join(DIR, f"{os.path.basename(k)}.json")
    if not os.path.exists(p):
        return None
    spec = json.load(open(p, encoding="utf-8"))
    imgs = build(spec["box"], spec["style"], spec["color"], fetch, spec.get("store") or "")
    return imgs[i] if 0 <= i < len(imgs) else None


# ───────────────────────── 새 모양 a~e (스토어 템플릿에서 고름 — 시안 A 배경판·굵은 테두리 / B 번호 배지·색 캡션 /
# C 다크 프레임 / D 미니멀·그림자 / E 이름 탭·안내 띠). 강조색 = 템플릿 색. 그 스토어 이름이 그림에 들어감.

def _mix(a, b, t):
    """a와 b를 t(0~1) 비율로 섞은 색."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _ellipsis(text, font, width):
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text + "…"


NEW_LOOK = {
    #     위 띠 높이, 칸 사이, 줄 사이, 칸 테두리, 사진 여백, 캡션 글자, 캡션 줄 높이, 캡션 위아래, 아래 띠
    "a": dict(head=150, side=28, gap=24, row_gap=26, bw=7, pad=7, cap=36, line=48, cap_pad=18, foot=70),
    "b": dict(head=136, side=28, gap=24, row_gap=30, bw=6, pad=6, cap=36, line=48, cap_pad=18, foot=0),
    "c": dict(head=160, side=28, gap=24, row_gap=26, bw=0, pad=12, cap=36, line=48, cap_pad=16, foot=70),
    "d": dict(head=156, side=28, gap=26, row_gap=30, bw=5, pad=14, cap=36, line=48, cap_pad=14, foot=0),
    "e": dict(head=150, side=28, gap=24, row_gap=26, bw=5, pad=20, cap=32, line=42, cap_pad=12, foot=0),
}


def _render_new(box, style, color, fetch, store):
    from PIL import Image, ImageDraw, ImageFilter
    L = NEW_LOOK[style]
    acc = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    white, ink = (255, 255, 255), (20, 20, 20)
    dark = _mix((24, 28, 38), acc, .12)                 # C 바탕: 강조색을 아주 조금 섞은 짙은 남색
    bg = {"a": _mix(acc, white, .88), "b": white, "c": dark, "d": (250, 250, 249), "e": white}[style]
    soft = _mix(acc, white, .92)
    n_all = len(box["cards"])
    title = box.get("title") or "옵션 선택"
    cap_font = _font(L["cap"], True)
    cw = (W - L["side"] * 2 - L["gap"]) // 2
    inner = cw - (L["bw"] + L["pad"]) * 2 if style != "a" and style != "b" else cw - L["bw"] * 2
    cards = []
    for srcs, cap in box["cards"]:
        photos = []
        for u in srcs:
            ph = _photo(fetch(u))
            h = max(1, round(ph.height * inner / ph.width))
            photos.append(ph.resize((inner, min(h, inner * 2)), Image.LANCZOS))
        if not photos:
            photos = [Image.new("RGB", (inner, inner), (238, 240, 243))]
        tab_w = cw - 40
        lines = (_wrap(cap, cap_font, (tab_w if style == "e" else inner) - 28)[:2 if style == "e" else MAX_LINES]) if cap else []
        cards.append((photos, lines))
    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    parts = [rows[i:i + ROWS_PER_IMAGE] for i in range(0, len(rows), ROWS_PER_IMAGE)]
    out, idx = [], 0
    for n, part in enumerate(parts):
        first, last = n == 0, n == len(parts) - 1
        head = L["head"] if first else 0
        foot = L["foot"] if last else 0
        sizes = []
        for row in part:
            ph = max(sum(p.height for p in c[0]) for c in row)
            nl = max(len(c[1]) for c in row)
            capt = (nl * L["line"] + L["cap_pad"] * 2) if nl else 0
            sizes.append((ph, capt))
        top_pad = 30 if first else 24
        body_h = sum(ph + capt + (L["bw"] + L["pad"]) * 2 for ph, capt in sizes) + L["row_gap"] * (len(part) - 1)
        if style in ("a", "b"):
            body_h = sum(ph + capt + L["bw"] * 2 for ph, capt in sizes) + L["row_gap"] * (len(part) - 1)
        height = head + top_pad + body_h + 30 + foot
        im = Image.new("RGB", (W, height), bg)
        d = ImageDraw.Draw(im)
        if first:
            _new_head(d, style, acc, dark, title, n_all, store)
        y = head + top_pad
        for row, (ph, capt) in zip(part, sizes):
            ch_body = ph + capt
            for col, (photos, lines) in enumerate(row):
                x0 = (W - cw) // 2 if len(cards) == 1 else L["side"] + col * (cw + L["gap"])
                idx += 1
                _new_card(im, d, style, L, acc, soft, ink, x0, y, cw, ph, capt, photos, lines, idx, cap_font)
            y += ch_body + ((L["bw"] * 2) if style in ("a", "b") else (L["bw"] + L["pad"]) * 2) + L["row_gap"]
        if foot:
            msg = {"a": f"{store}에서 고른 옵션 그대로 보내 드립니다" if store else "고른 옵션 그대로 보내 드립니다",
                   "c": f"{store} · 옵션명을 꼭 확인 후 주문해 주세요" if store else "옵션명을 꼭 확인 후 주문해 주세요"}[style]
            fc = _mix(acc, (0, 0, 0), .35) if style == "a" else (190, 198, 210)
            d.text((W / 2, height - foot / 2 - 6), msg, font=_font(28, False), fill=fc, anchor="mm")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
        out.append(buf.getvalue())
    return out


def _new_head(d, style, acc, dark, title, n, store):
    white = (255, 255, 255)
    cnt = f"총 {n}종"
    if style == "a":
        d.rectangle([0, 0, W, 150], fill=acc)
        if store:
            d.text((W / 2, 46), store, font=_font(30, False), fill=_mix(acc, white, .7), anchor="mm")
        d.text((W / 2, 100 if store else 75), f"{title}  ·  {cnt}", font=_font(50, True), fill=white, anchor="mm")
    elif style == "b":
        d.rectangle([0, 128, W, 136], fill=acc)
        d.text((28, 66), "OPTION", font=_font(56, True), fill=acc, anchor="lm")
        x = 28 + _font(56, True).getlength("OPTION") + 20
        d.text((x, 72), f"옵션 {n}종을 확인하세요", font=_font(32, False), fill=(60, 60, 60), anchor="lm")
        if store:
            f = _font(30, True)
            name = _ellipsis(store, f, 300)
            tw = f.getlength(name) + 40
            d.rounded_rectangle([W - 28 - tw, 44, W - 28, 92], 24, fill=acc)
            d.text((W - 28 - tw / 2, 68), name, font=f, fill=white, anchor="mm")
    elif style == "c":
        if store:
            d.text((W / 2, 50), store, font=_font(28, False), fill=_mix(acc, white, .55), anchor="mm")
        d.text((W / 2, 104), title if title != "옵션 선택" else "옵션 한눈에 보기", font=_font(52, True), fill=white, anchor="mm")
        d.line([W / 2 - 60, 148, W / 2 + 60, 148], fill=acc, width=5)
    elif style == "d":
        d.text((28, 60), title, font=_font(50, True), fill=(20, 20, 20), anchor="lm")
        d.text((28, 112), f"{cnt}" + (f" · {store}" if store else ""), font=_font(30, False), fill=(110, 110, 110), anchor="lm")
        d.rectangle([28, 146, W - 28, 152], fill=(20, 20, 20))
    elif style == "e":
        d.rounded_rectangle([28, 24, W - 28, 140], 26, fill=acc)
        d.text((W / 2, 64), "구매 전 옵션을 확인해 주세요", font=_font(44, True), fill=white, anchor="mm")
        d.text((W / 2, 110), (f"{store}  |  " if store else "") + cnt, font=_font(28, False), fill=_mix(acc, white, .75), anchor="mm")


def _new_card(im, d, style, L, acc, soft, ink, x, y, cw, ph, capt, photos, lines, idx, cap_font):
    from PIL import Image, ImageDraw, ImageFilter
    white = (255, 255, 255)
    bw, pad = L["bw"], L["pad"]
    if style in ("a", "b"):
        h = ph + capt + bw * 2
        line_c = acc if style == "a" else (40, 40, 46)
        d.rectangle([x, y, x + cw - 1, y + h - 1], fill=white, outline=line_c, width=bw)
        py = y + bw + (ph - sum(p.height for p in photos)) // 2
        for p in photos:
            im.paste(p, (x + bw, py))
            py += p.height
        cy0 = y + bw + ph
        if capt:
            if style == "a":
                d.rectangle([x + bw, cy0, x + cw - bw - 1, y + h - bw - 1], fill=_mix(acc, white, .95))
                d.line([x + bw, cy0, x + cw - bw - 1, cy0], fill=acc, width=3)
            else:
                d.rectangle([x + bw, cy0, x + cw - bw - 1, y + h - bw - 1], fill=acc)
            cy = cy0 + L["cap_pad"]
            for ln in lines:
                d.text((x + cw / 2, cy + L["line"] / 2), ln, font=cap_font, fill=ink if style == "a" else white, anchor="mm")
                cy += L["line"]
        if style == "b":
            d.ellipse([x + 18, y + 18, x + 86, y + 86], fill=(40, 40, 46))
            d.text((x + 52, y + 52), str(idx), font=_font(40 if idx < 100 else 28, True), fill=white, anchor="mm")
        return
    h = ph + capt + (bw + pad) * 2
    if style == "d":   # 그림자
        sh = Image.new("RGBA", (cw + 40, h + 40), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([20, 26, cw + 20, h + 26], 18, fill=(0, 0, 0, 60))
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        im.paste(sh, (x - 20, y - 20), sh)
        d = ImageDraw.Draw(im)
    fill = {"c": white, "d": white, "e": soft}[style]
    outline = {"c": None, "d": (20, 20, 20), "e": acc}[style]
    r = {"c": 22, "d": 18, "e": 20}[style]
    d.rounded_rectangle([x, y, x + cw - 1, y + h - 1], r, fill=fill, outline=outline, width=bw if outline else 0)
    if style == "e":   # 이름 탭(위) → 사진
        cy = y + bw + pad // 2
        f = cap_font
        if lines:
            tw = min(cw - 40, max(f.getlength(ln) for ln in lines) + 48)
            th = len(lines) * L["line"] + 12
            d.rounded_rectangle([x + (cw - tw) / 2, cy, x + (cw + tw) / 2, cy + th], min(27, th // 2), fill=acc)
            ty = cy + 6
            for ln in lines:
                d.text((x + cw / 2, ty + L["line"] / 2), ln, font=f, fill=white, anchor="mm")
                ty += L["line"]
        py = y + bw + pad + capt + (ph - sum(p.height for p in photos)) // 2
        for p in photos:
            im.paste(p, (x + bw + pad, py))
            py += p.height
        return
    py = y + bw + pad + (ph - sum(p.height for p in photos)) // 2
    for p in photos:
        if style == "c":   # 둥근 모서리 사진
            m = Image.new("L", p.size, 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, p.width - 1, p.height - 1], 16, fill=255)
            im.paste(p, (x + bw + pad, py), m)
        else:
            im.paste(p, (x + bw + pad, py))
        py += p.height
    cy = y + bw + pad + ph + L["cap_pad"]
    for ln in lines:
        d.text((x + cw / 2, cy + L["line"] / 2), ln, font=cap_font, fill=ink, anchor="mm")
        cy += L["line"]
