"""네이버에 올리기 전 이미지 형식 맞추기.

네이버 이미지 업로드는 JPG·PNG·GIF·BMP만 받는다 ('올바른 이미지 파일이 아닙니다'). 수집한 상품 이미지에는
WEBP·AVIF가 많고, 주소가 .jpg여도 내용이 WEBP인 경우도 있다. 그래서 그림을 열어 실제 형식을 보고,
받는 형식이 아니거나(WEBP·AVIF·HEIC·TIFF·ICO…) CMYK 같은 특이한 색 형식이거나 너무 크면 RGB JPG로 바꾼다.
그림이 아니면(차단 페이지 HTML·빈 파일) BadImage.
"""

import io

OK_FORMATS = ("JPEG", "PNG", "GIF", "BMP")
MIME = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "GIF": ("gif", "image/gif"), "BMP": ("bmp", "image/bmp")}
MAX_BYTES = 10 * 1024 * 1024    # 네이버 이미지 한 장 최대 10MB
MAX_SIDE = 4000                 # 긴 변이 이보다 크면 줄임 (상세 폭 860px — 충분히 선명)


class BadImage(Exception):
    pass


def sniff(data):
    """바이트 앞부분으로 형식 짐작 (열지 않고)."""
    b = bytes(data[:16]) if data else b""
    if b.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if b.startswith(b"\x89PNG"):
        return "PNG"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if b.startswith(b"BM"):
        return "BMP"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "WEBP"
    if b[4:12] in (b"ftypavif", b"ftypavis"):
        return "AVIF"
    if b[4:8] == b"ftyp":
        return "HEIC"
    return ""


def _looks_html(data):
    head = bytes(data[:512]).lstrip().lower()
    return head.startswith((b"<!doctype", b"<html", b"<?xml", b"<head", b"<body", b"{", b"<")) and b"<svg" not in head


def normalize(data, ctype="", url=""):
    """→ (바이트, content-type). 받는 형식이면 그대로(확장자·형식만 맞춤), 아니면 JPG로. 그림이 아니면 BadImage."""
    if not data:
        raise BadImage(f"원본 이미지가 비어 있음(지워졌거나 막힘): {url}")
    fmt = sniff(data)
    if fmt in OK_FORMATS and len(data) <= MAX_BYTES:
        if fmt == "JPEG" and not _cmyk_or_huge(data):
            return data, MIME[fmt][1]
        if fmt != "JPEG" and not _huge(data):
            return data, MIME[fmt][1]
    try:
        from PIL import Image, ImageOps
        try:
            import pillow_avif  # noqa: F401 - 있으면 AVIF도 열림
        except Exception:  # noqa: BLE001
            pass
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001
        if _looks_html(data):
            raise BadImage(f"원본 이미지가 그림이 아님(막혔거나 지워짐 — 페이지가 내려옴): {url}") from None
        raise BadImage(f"원본 이미지를 그림으로 열지 못함({fmt or '알 수 없는 형식'}): {url}") from None
    if im.format == "GIF" and getattr(im, "is_animated", False) and len(data) <= MAX_BYTES:
        return data, "image/gif"   # 움직이는 GIF는 그대로
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa: BLE001
        pass
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    for q in (90, 82, 72, 60):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        if len(out) <= MAX_BYTES:
            return out, "image/jpeg"
    raise BadImage(f"이미지가 너무 커서 줄여도 10MB를 넘음: {url}")


def _huge(data):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        return max(im.size) > MAX_SIDE * 2   # 아주 큰 그림만 줄임 (조금 큰 건 네이버가 받음)
    except Exception:  # noqa: BLE001
        return False


def _cmyk_or_huge(data):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        return im.mode in ("CMYK", "YCCK") or max(im.size) > MAX_SIDE * 2
    except Exception:  # noqa: BLE001
        return True   # JPG 머리인데 못 엶 → 다시 저장 시도 (안 되면 BadImage)
