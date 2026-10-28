"""스토어 템플릿: 스토어마다 상세페이지 상단·하단(이미지 + HTML), 관부가세 코드, 가격 조정 %, 표시 할인율 %.

원본 상품에는 스토어 상하단이 없다. 복사본을 특정 스토어에 올릴 때 그 스토어의 상단·하단을 상세설명 앞뒤에 붙인다.
상단·하단 이미지는 이 PC에 저장해 두고, 올릴 때 그 스토어 이름으로 네이버 이미지 서버에 한 번 올려 주소를 기억한다.
"""

import os
import re
import time

from . import config

PARTS = ("top", "bottom")
_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


def folder(store_id):
    return os.path.join(config.DATA_DIR, "templates", f"store_{int(store_id)}")


def images(store_id, part):
    """[(파일 이름, 전체 경로)] 이름 순 (올린 순서)."""
    d = folder(store_id)
    if not os.path.isdir(d):
        return []
    out = [(f, os.path.join(d, f)) for f in os.listdir(d) if f.startswith(part + "_")]
    return sorted(out)


def save_image(store_id, part, filename, data):
    if part not in PARTS:
        raise ValueError("상단(top) 또는 하단(bottom)만 됩니다.")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        raise ValueError("이미지 파일(JPG·PNG·GIF·WEBP)만 올릴 수 있습니다.")
    d = folder(store_id)
    os.makedirs(d, exist_ok=True)
    name = f"{part}_{int(time.time() * 1000)}_{_SAFE.sub('', os.path.splitext(filename)[0])[:30]}{ext}"
    with open(os.path.join(d, name), "wb") as f:
        f.write(data)
    return name


def delete_image(store_id, name):
    p = os.path.join(folder(store_id), os.path.basename(name))
    if os.path.exists(p):
        os.remove(p)


def path_of(store_id, name):
    p = os.path.join(folder(store_id), os.path.basename(name))
    return p if os.path.exists(p) else None


def _key(path):
    return f"tpl:{path}:{int(os.path.getmtime(path))}"


def html(db, client, store, on_wait=None):
    """(상단 HTML, 하단 HTML): 템플릿 이미지를 네이버에 올린 주소로 <img>를 만들고 적어 둔 HTML을 붙인다.
    한 번 올린 이미지는 스토어별로 기억해 다시 올리지 않는다."""
    out = []
    for part in PARTS:
        files = images(store["id"], part)
        keys = {p: _key(p) for _, p in files}
        saved = db.image_map(store["id"], list(keys.values()))
        need = [p for p in keys if keys[p] not in saved]
        for i in range(0, len(need), 10):
            chunk = need[i:i + 10]
            items = []
            for p in chunk:
                with open(p, "rb") as f:
                    items.append((p, f.read(), ""))
            urls = client.upload_images(items, on_wait=on_wait)
            db.save_images(store["id"], [(keys[p], u) for p, u in zip(chunk, urls)])
            saved.update({keys[p]: u for p, u in zip(chunk, urls)})
        imgs = "".join(f'<p style="text-align:center"><img src="{saved[keys[p]]}" style="max-width:100%"></p>'
                       for _, p in files if keys[p] in saved)
        text = store.get(f"tpl_{part}_html") or ""
        out.append(imgs + text if part == "top" else text + imgs)
    return out[0], out[1]


def summary(store):
    sid = store["id"]
    return {"top": [f for f, _ in images(sid, "top")], "bottom": [f for f, _ in images(sid, "bottom")],
            "top_html": store.get("tpl_top_html") or "", "bottom_html": store.get("tpl_bottom_html") or "",
            "customs": config.customs_code(store.get("tpl_customs")), "price_pct": store.get("tpl_price_pct"),
            "discount_pct": store.get("tpl_discount_pct"),
            "ship_addr": store.get("tpl_ship_addr"), "return_addr": store.get("tpl_return_addr"),
            "jitter_min": store.get("tpl_jitter_min"), "jitter_max": store.get("tpl_jitter_max"), "wm_text": store.get("wm_text") or "",
            "opt_style": store.get("tpl_opt_style") or "", "opt_color": store.get("tpl_opt_color") or ""}
