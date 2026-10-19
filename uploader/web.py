"""조작 화면 서버. 이 PC(127.0.0.1)에서만 열린다."""

import csv
import io
import os
import tempfile
import threading
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from . import bait, config, convert, engine, inventory, keywords, lexicon, naver, orders, watermark
from .db import DB
from .tasks import Tasks

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FILTER_KEYS = ("q", "status", "category", "store_missing", "store_has", "import_id", "max_listings",
               "min_names", "store_id", "plan_id", "op", "age_days", "sold", "locked")
STORE_FIELDS = ("name", "code", "client_id", "client_secret", "store_url", "as_phone", "capacity", "enabled", "memo", "wm_text", "importer")


def _filter_from(src):
    f = {k: src.get(k) for k in FILTER_KEYS if src.get(k) not in (None, "")}
    if src.get("ids"):
        f["ids"] = [int(i) for i in src["ids"]]
    return f


def _save_upload(f):
    """올린 파일을 임시 파일로 저장 (뒤에서 천천히 읽기 위해)."""
    suffix = os.path.splitext(f.filename)[1].lower()
    fd, path = tempfile.mkstemp(suffix=suffix, dir=config.DATA_DIR)
    with os.fdopen(fd, "wb") as out:
        f.save(out)
    return path


def create_app(db=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 ** 3
    os.makedirs(config.DATA_DIR, exist_ok=True)
    db = db or DB()
    runner = engine.Runner(db)
    if getattr(db, "_v3", False):
        orders.recount_sold(db)
        db.x("PRAGMA user_version=3")
    tasks = Tasks()

    def fail(msg, code=400):
        return jsonify({"error": msg}), code

    def body():
        return request.get_json(force=True, silent=True) or {}

    @app.errorhandler(Exception)
    def on_error(e):
        code = getattr(e, "code", 500)
        return jsonify({"error": str(e)}), code if isinstance(code, int) else 500

    def file_task(kind, title, fn):
        f = request.files.get("file")
        if not f or not f.filename:
            return fail("파일을 골라 주세요.")
        if not f.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
            return fail("xlsx 또는 csv 파일만 불러올 수 있습니다.")
        path = _save_upload(f)
        name = f.filename

        def job(progress, should_stop):
            try:
                with open(path, "rb") as fh:
                    return fn(db, fh, name, progress=progress, should_stop=should_stop)
            finally:
                os.remove(path)
        try:
            return jsonify({"task": tasks.start(kind, f"{title} · {name}", job)})
        except RuntimeError as e:
            os.remove(path)
            return fail(str(e))

    # ── 화면

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html", max_age=0)

    @app.get("/static/<path:name>")
    def static_file(name):
        return send_from_directory(STATIC, name, max_age=0)

    # ── 전체 상태

    @app.get("/api/state")
    def state():
        cfg = config.load()
        cats = naver.cached_categories()
        return jsonify({
            "settings": config.public(cfg),
            "fake_api": os.environ.get("UPLOADER_FAKE_API") == "1",
            "categories": len(cats) if cats else 0,
            "stats": db.stats(),
            "tasks": tasks.list(),
            "running": runner.state["running"],
        })

    @app.get("/api/tasks")
    def task_list():
        return jsonify(tasks.list())

    @app.post("/api/tasks/<int:tid>/stop")
    def task_stop(tid):
        tasks.stop(tid)
        return jsonify({"ok": True})

    # ── 설정

    @app.post("/api/settings")
    def save_settings():
        v = body()
        ints = ("recombine_fixed_prefix", "recombine_new_min", "recombine_new_max", "max_word_repeat", "opendict_daily_limit", "kipris_limit", "bait_amount", "kw_daily_limit", "kw_min_volume", "kw_related_max", "kw_refresh_days", "kw_max_words", "core_scan_words", "orders_auto_sync_minutes", "orders_initial_days", "max_copies", "return_fee", "exchange_fee", "workers_per_store", "max_parallel_stores", "price_round",
                "name_max_len", "ai_names_per_product", "ai_products_per_call", "ai_workers")
        floats = ("wm_size_pct", "wm_opacity", "wm_margin_pct", "recombine_replace_ratio", "delay_sec", "price_jitter_pct", "recombine_max_overlap", "image_cache_gb")
        for k in ints:
            if k in v:
                v[k] = convert.to_int(v[k], config.DEFAULTS[k])
        for k in floats:
            if k in v:
                try:
                    v[k] = max(0.0, float(v[k]))
                except (TypeError, ValueError):
                    v[k] = config.DEFAULTS[k]
        before = config.load()
        cfg = config.save(v)
        if any(before.get(k) != cfg.get(k) for k in ("lock_sold", "lock_canceled_too")):
            orders.recount_sold(db)  # 잠금 기준이 바뀌었으면 전체 다시 계산
        if any(before.get(k) != cfg.get(k) for k in ("origin_force", "origin_country", "origin_codes", "origin_default")):
            try:  # 원산지 기준이 바뀌었으면 전체 원본을 다시 검사 (오류 표시가 바로 바뀌게)
                tasks.start("revalidate", "원산지 설정이 바뀌어 전체 다시 검사", lambda **kw: inventory.revalidate(db, **kw))
            except RuntimeError:
                pass
        if before.get("kipris_block_pending") != cfg.get("kipris_block_pending"):
            with db.tx() as c:
                lexicon._bump(c)  # 상표 단어 기준이 바뀌었으면 사전 다시 읽게
        return jsonify({"settings": config.public(cfg)})

    @app.post("/api/settings/reapply")
    def settings_reapply():
        """바꾼 설정을 이미 만든 것에 다시 적용: prices(대기 중 복사본 가격) / names(안 쓴 이름 후보 지우기)."""
        what = body().get("what")
        cfg = config.load()
        if what == "prices":
            rows = db.q("""SELECT l.id, l.store_id, s.price, s.source_key FROM listings l JOIN sources s ON s.id=l.source_id
                WHERE l.origin_no='' AND l.status IN ('planned','fail')""")
            with db.tx() as c:
                for r in rows:
                    c.execute("UPDATE listings SET price=? WHERE id=?",
                              (convert.adjusted_price(r["price"], f"{r['source_key']}|{r['store_id']}", cfg), r["id"]))
            return jsonify({"count": len(rows)})
        if what == "names":
            n = db.one("SELECT COUNT(*) AS n FROM names WHERE listing_id IS NULL AND origin IN ('recombine','ai')")["n"]
            db.x("DELETE FROM names WHERE listing_id IS NULL AND origin IN ('recombine','ai')")
            db.recount_sources()
            return jsonify({"count": n})
        return fail("알 수 없는 작업입니다.")

    @app.post("/api/categories/refresh")
    def refresh_categories():
        s = next((x for x in db.stores(with_secret=True) if x["has_keys"]), None)
        if not s and os.environ.get("UPLOADER_FAKE_API") != "1":
            return fail("API 키가 있는 스토어가 하나 이상 있어야 카테고리를 받을 수 있습니다.")
        try:
            cats = naver.make_client(s or {}).categories(refresh=True)
        except naver.ApiError as e:
            return fail(str(e))
        tid = tasks.start("revalidate", "카테고리 받은 뒤 전체 다시 검사", lambda **kw: inventory.revalidate(db, **kw))
        return jsonify({"categories": len(cats), "task": tid})

    # ── 스토어

    @app.get("/api/stores")
    def stores():
        return jsonify(db.stores())

    @app.post("/api/stores")
    def save_store():
        v = {k: body().get(k) for k in STORE_FIELDS if k in body()}
        sid = body().get("id")
        if "capacity" in v:
            v["capacity"] = max(0, convert.to_int(v["capacity"], 10000))
        if "enabled" in v:
            v["enabled"] = int(bool(v["enabled"]))
        for k in ("name", "code", "client_id", "client_secret", "store_url", "as_phone", "memo", "wm_text", "importer"):
            if k in v:
                v[k] = str(v[k] or "").strip()
        if sid:
            if not v.get("client_secret"):
                v.pop("client_secret", None)  # 빈칸이면 기존 시크릿 유지
            if v:
                db.x(f"UPDATE stores SET {', '.join(f'{k}=?' for k in v)} WHERE id=?", (*v.values(), int(sid)))
        else:
            if not v.get("name"):
                return fail("스토어 이름을 넣어 주세요.")
            v["created_at"] = time.time()
            sid = db.x(f"INSERT INTO stores({', '.join(v)}) VALUES({', '.join('?' * len(v))})", tuple(v.values()))
        return jsonify(db.store(int(sid)))

    @app.post("/api/stores/bulk")
    def bulk_stores():
        """한 줄에 한 스토어: 이름, 애플리케이션 ID, 시크릿, 스토어 주소, A/S 전화, 코드 (쉼표나 탭으로 구분)."""
        text = body().get("text") or ""
        existing = {s["name"]: s["id"] for s in db.stores()}
        added = updated = 0
        for line in text.splitlines():
            parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(","))]
            if not parts or not parts[0] or parts[0] in ("이름", "스토어"):
                continue
            parts += [""] * (6 - len(parts))
            name, cid, sec, url, phone, code = parts[:6]
            if name in existing:
                fields = {k: v for k, v in (("client_id", cid), ("client_secret", sec), ("store_url", url),
                                            ("as_phone", phone), ("code", code)) if v}
                if fields:
                    db.x(f"UPDATE stores SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                         (*fields.values(), existing[name]))
                updated += 1
            else:
                db.x("INSERT INTO stores(name, code, client_id, client_secret, store_url, as_phone, created_at) "
                     "VALUES(?,?,?,?,?,?,?)", (name, code, cid, sec, url, phone, time.time()))
                added += 1
        return jsonify({"added": added, "updated": updated})

    @app.delete("/api/stores/<int:sid>")
    def delete_store(sid):
        n = db.one("SELECT COUNT(*) AS n FROM listings WHERE store_id=? AND (origin_no!='' OR status IN ('queued','running'))",
                   (sid,))["n"]
        if n:
            return fail(f"이 스토어에 등록된 상품 기록이 {n:,}건 있어 지울 수 없습니다. '사용 안 함'으로 바꾸세요.")
        inventory.cancel_listings(db, "store_id=?", (sid,))
        db.x("DELETE FROM stores WHERE id=?", (sid,))
        return jsonify({"ok": True})

    @app.post("/api/stores/<int:sid>/test")
    def test_store(sid):
        s = db.store(sid, with_secret=True)
        if not s:
            return fail("스토어가 없습니다.", 404)
        try:
            client = naver.make_client(s)
            client.test()
            count = client.product_count()
        except naver.ApiError as e:
            return fail(str(e))
        db.x("UPDATE stores SET naver_count=?, naver_count_at=? WHERE id=?", (count, time.time(), sid))
        if not naver.cached_categories():
            try:
                client.categories(refresh=True)
                # 카테고리를 처음 받았으면, 그 전에 불러온 원본의 카테고리를 다시 검사한다.
                tasks.start("revalidate", "카테고리 받은 뒤 전체 다시 검사",
                            lambda **kw: inventory.revalidate(db, **kw))
            except (naver.ApiError, RuntimeError):
                pass
        return jsonify({"ok": True, "naver_count": count, "store": db.store(sid)})

    # ── 원본 (인벤토리)

    @app.get("/api/sources")
    def sources():
        f = _filter_from(request.args)
        page, size = int(request.args.get("page", 0)), min(int(request.args.get("size", 100)), 500)
        return jsonify({**inventory.query_sources(db, f, page, size), "counts": inventory.source_counts(db)})

    @app.get("/api/sources/<int:sid>")
    def source(sid):
        s = inventory.source_detail(db, sid)
        if not s:
            return fail("상품이 없습니다.", 404)
        row = s.pop("row")
        opts = convert.options(row) or {}
        s.update({
            "thumbnails": convert.thumbnails(row),
            "detail_images": convert.detail_images(row),
            "tags_list": convert.tags(row),
            "options": opts.get("optionCombinations") or [],
            "option_group": (opts.get("optionCombinationGroupNames") or {}).get("optionGroupName1", ""),
            "fields": {k: row.get(k) for k in ("브랜드", "제조사", "모델명", "원산지", "재고수", "배송비", "판매상태")
                       if row.get(k) not in (None, "")},
            "detail_html": row.get("상세설명") or "",
        })
        s["kw"] = _source_kw(sid, row)
        return jsonify(s)

    def _source_kw(sid, row):
        """원본의 핵심 키워드와 네이버에서 모은 단어 (재조합에 쓰는 것 / 빠진 이유)."""
        cfg = config.load()
        lex = lexicon.get(db)
        src = db.one("SELECT id, name, core_kw, core_manual, kw_at FROM sources WHERE id=?", (sid,))
        core, used = keywords.words_for(db, [{**src, "data": None, "_row": row}], {**cfg, "use_naver_keywords": True},
                                        lex)[sid]
        off = {r["word"] for r in db.q("SELECT word FROM kw_off WHERE core IN ('', ?)", (core,))}
        text = None
        words = []
        for r in db.q("""SELECT k.word, k.malls, k.share, v.pc, v.mobile FROM source_kw k LEFT JOIN kw_volume v ON v.word=k.word
                WHERE k.source_id=? ORDER BY k.malls DESC""", (sid,)):
            why = ""
            if r["word"] not in used:
                if r["word"] in off:
                    why = "끈 단어"
                elif not lex.ok_new_word(r["word"]):
                    why = "상표 단어" if lex.mark_of(r["word"]) else "금지 단어"
                elif lexicon.attrs_in(r["word"], lex):
                    why = "원본에 없는 속성"
                else:
                    why = "순위 밖"
            words.append({**r, "used": r["word"] in used, "why": why,
                          "volume": (r["pc"] or 0) + (r["mobile"] or 0) if r["pc"] is not None else None})
        return {"core": core, "manual": bool(src["core_manual"]), "collected_at": src["kw_at"], "words": words}

    @app.post("/api/sources/<int:sid>/core")
    def source_core(sid):
        """핵심 키워드 직접 정하기 → 이 원본에 쓰고, 단어를 기억해 같은 단어가 나오는 다른 원본에도 씀."""
        core = (body().get("core") or "").strip()
        old = db.one("SELECT core_kw FROM sources WHERE id=?", (sid,))
        db.x("UPDATE sources SET core_kw=?, core_manual=?, kw_at=NULL WHERE id=?", (core, 1 if core else 0, sid))
        if core:
            keywords.learn_core(db, core, other=(old or {}).get("core_kw"))
        return jsonify({"ok": True})

    @app.post("/api/sources/import")
    def import_sources():
        return file_task("import", "원본 불러오기", inventory.import_products)

    @app.post("/api/sources/revalidate")
    def revalidate():
        try:
            return jsonify({"task": tasks.start("revalidate", "전체 다시 검사",
                                                lambda **kw: inventory.revalidate(db, **kw))})
        except RuntimeError as e:
            return fail(str(e))

    @app.post("/api/sources/count")
    def count_matching():
        return jsonify({"count": len(inventory.source_ids(db, _filter_from(body())))})

    @app.get("/api/imports")
    def imports():
        return jsonify(db.q("SELECT * FROM imports ORDER BY id DESC LIMIT 50"))

    # ── 상품명

    @app.post("/api/names/import")
    def names_import():
        return file_task("names", "상품명 가져오기", inventory.import_names)

    @app.post("/api/names/generate")
    def names_generate():
        b = body()
        ids = inventory.source_ids(db, {**_filter_from(b), "status": b.get("status") or "valid"})
        if not ids:
            return fail("대상 상품이 없습니다.")
        per = max(1, min(int(b.get("per_source") or 5), 100))
        method = b.get("method")
        try:
            if method == "ai":
                cfg = config.load()
                if not cfg.get("anthropic_api_key") and os.environ.get("UPLOADER_FAKE_API") != "1":
                    return fail("설정 → AI 상품명에서 Anthropic API 키를 먼저 넣어 주세요.")
                tid = tasks.start("names", f"AI 상품명 · {len(ids):,}개 상품",
                                  lambda **kw: inventory.generate_ai(db, ids, per, **kw))
            else:
                tid = tasks.start("names", f"재조합 상품명 · {len(ids):,}개 상품",
                                  lambda **kw: inventory.generate_recombine(db, ids, per, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid, "count": len(ids)})

    @app.post("/api/names")
    def add_name():
        b = body()
        cfg = {**config.load(), "_lex": lexicon.get(db)}
        rejected = []
        with db.tx() as c:
            added, dup = inventory.add_names(c, int(b["source_id"]), [b.get("name", "")], "manual", cfg=cfg, rejected=rejected)
        db.recount_sources([int(b["source_id"])])
        if not added:
            if rejected:
                return fail(f"쓸 수 없는 이름입니다: {rejected[0]}")
            return fail("이미 다른 상품이나 스토어에서 쓰는(또는 후보에 있는) 이름입니다." if dup else "이름을 넣어 주세요.")
        return jsonify({"ok": True})

    @app.delete("/api/names/<int:nid>")
    def delete_name(nid):
        n = db.one("SELECT source_id, listing_id FROM names WHERE id=?", (nid,))
        if not n:
            return fail("이름이 없습니다.", 404)
        if n["listing_id"]:
            return fail("등록에 쓰인 이름은 지울 수 없습니다.")
        db.x("DELETE FROM names WHERE id=?", (nid,))
        db.recount_sources([n["source_id"]])
        return jsonify({"ok": True})

    # ── 계획

    @app.post("/api/plans")
    def make_plan():
        b = body()
        ids = inventory.source_ids(db, _filter_from(b))
        store_ids = [int(i) for i in b.get("store_ids") or []]
        if not ids:
            return fail("대상 상품이 없습니다.")
        if not store_ids:
            return fail("스토어를 하나 이상 골라 주세요.")
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 계획을 만들 수 없습니다. 끝난 뒤에 다시 시도하세요.")
        mode = "spread" if b.get("mode") == "spread" else "all"
        per = max(1, int(b.get("per_product") or 1))
        try:
            tid = tasks.start("plan", f"등록 계획 · 상품 {len(ids):,}개 × 스토어 {len(store_ids)}곳",
                              lambda **kw: inventory.create_plan(db, ids, store_ids, mode, per,
                                                                 b.get("title") or "", bait=b.get("bait"), **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.get("/api/plans")
    def plans():
        return jsonify(db.q("""SELECT p.*, COUNT(l.id) AS total, SUM(l.status='success') AS success,
            SUM(l.status='fail') AS fail, SUM(l.status IN ('planned','queued','running')) AS pending,
            COUNT(DISTINCT l.store_id) AS stores
            FROM plans p LEFT JOIN listings l ON l.plan_id=p.id GROUP BY p.id ORDER BY p.id DESC LIMIT 200"""))

    # ── 등록 건

    @app.get("/api/listings")
    def listings():
        f = _filter_from(request.args)
        page, size = int(request.args.get("page", 0)), min(int(request.args.get("size", 100)), 500)
        return jsonify({**inventory.query_listings(db, f, page, size),
                        "counts": inventory.listing_counts(db, f.get("store_id"), f.get("plan_id"))})

    @app.get("/api/listings/<int:lid>")
    def listing(lid):
        l = db.one("SELECT l.*, t.name AS store_name, t.store_url, t.as_phone, t.code AS store_code FROM listings l "
                   "JOIN stores t ON t.id=l.store_id WHERE l.id=?", (lid,))
        if not l:
            return fail("등록 건이 없습니다.", 404)
        cfg = config.load()
        row = db.source_row(l["source_id"])
        cats = naver.cached_categories() or {}
        cat = str(row.get("카테고리") or "").strip()
        url_map = {**db.image_map(l["store_id"], convert.thumbnails(row)[:10]),
                   **db.image_map(engine.DETAIL_SCOPE, convert.detail_images_to_upload(row, cfg))}
        store = db.store(l["store_id"])
        nxt = {**l, "round": l["round"] + (1 if l["op"] == "refresh" and l["origin_no"] else 0)}
        l["next_seller_code"] = engine.seller_code(cfg, store, nxt)
        l["history"] = db.q("SELECT * FROM listing_history WHERE listing_id=? ORDER BY round DESC", (lid,))
        l["orders"] = db.q("SELECT * FROM orders WHERE listing_id=? ORDER BY ordered_at DESC LIMIT 50", (lid,))
        l["siblings"] = db.q("""SELECT l.id, l.name, l.status, l.round, t.name AS store_name FROM listings l
            JOIN stores t ON t.id=l.store_id WHERE l.source_id=? AND l.id!=? AND l.status!='deleted'""",
                             (l["source_id"], lid))
        try:
            l["body"] = convert.build_body(row, cfg, cats.get(cat) or f"(카테고리 번호 확인 필요) {cat}", url_map,
                                           name=l["name"], price=l["price"], seller_code=l["next_seller_code"],
                                           as_phone=l["as_phone"] or cfg.get("as_phone"),
                                           importer=convert.importer_for(store, cfg))
        except convert.ConvertError as e:
            l["body"] = {"검사 오류": str(e)}
        l["thumb"] = (convert.thumbnails(row) or [""])[0]
        l["source_name"] = row.get("상품명")
        l["source_price"] = convert.to_int(row.get("판매가"))
        return jsonify(l)

    @app.post("/api/listings/schedule")
    def schedule():
        """올라가 있는 건에 최신화(지우고 다시 올리기) 또는 내리기를 예약한다."""
        b = body()
        op = b.get("op")
        if op not in ("refresh", "delete"):
            return fail("알 수 없는 작업입니다.")
        if runner.state["running"]:
            return fail("등록이 끝난 뒤에 예약할 수 있습니다.")
        f = _filter_from(b)
        f.pop("op", None)  # 'op'는 여기서 거르기 조건이 아니라 걸 작업
        n, skipped = inventory.schedule_op(db, f, op)
        return jsonify({"scheduled": n, "skipped_sold": skipped})

    # ── 판매 이력

    @app.post("/api/orders/sync")
    def orders_sync():
        """네이버에서 결제된 주문을 가져온다 (스토어마다 마지막으로 가져온 때부터)."""
        ids = set(int(i) for i in body().get("store_ids") or [])
        pairs = []
        for s in db.stores(with_secret=True):
            if (ids and s["id"] not in ids) or not s["enabled"]:
                continue
            if not s["has_keys"] and os.environ.get("UPLOADER_FAKE_API") != "1":
                continue
            pairs.append((s, naver.make_client(s)))
        if not pairs:
            return fail("주문을 가져올 스토어가 없습니다 (API 키가 있는 사용 중 스토어).")
        days = body().get("days") or config.load().get("orders_initial_days")
        since = _date_ts(body().get("from"))
        until = _date_ts(body().get("to"), end=True)
        title = f"주문 가져오기 · 스토어 {len(pairs)}곳" + (f" · {body().get('from')}~{body().get('to') or '오늘'}" if since else "")
        try:
            tid = tasks.start("orders", title,
                              lambda **kw: orders.sync_stores(db, pairs, days=days, since=since, until=until, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/orders/import")
    def orders_import():
        return file_task("orders", "판매 이력 파일 가져오기", orders.import_sales_file)

    @app.post("/api/listings/rename")
    def listings_rename():
        """고른 복사본(아직 안 올린 것)의 상품명을 재조합·AI·만들어 둔 후보로 바꾼다."""
        b = body()
        f = _filter_from(b)
        f.pop("op", None)
        ids = inventory.listing_ids(db, f)
        if not ids:
            return fail("고른 복사본이 없습니다.")
        method = b.get("method") if b.get("method") in ("recombine", "ai", "pool") else "recombine"
        if method == "ai" and not config.load().get("anthropic_api_key") and os.environ.get("UPLOADER_FAKE_API") != "1":
            return fail("설정 → AI 상품명에서 Anthropic API 키를 먼저 넣어 주세요.")
        label = {"recombine": "재조합", "ai": "AI", "pool": "만들어 둔 후보"}[method]
        try:
            tid = tasks.start("rename", f"상품명 바꾸기({label}) · 복사본 {len(ids):,}건",
                              lambda **kw: inventory.rename_listings(db, ids, method, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/listings/<int:lid>/name")
    def listing_set_name(lid):
        try:
            name = inventory.set_listing_name(db, lid, (body().get("name") or "").strip())
        except ValueError as e:
            return fail(str(e))
        return jsonify({"ok": True, "name": name})

    @app.post("/api/listings/lock")
    def lock():
        """직접 잠금/풀기 (판매 이력과 상관없이). 판매 이력으로 걸린 잠금은 풀리지 않는다."""
        b = body()
        ids = inventory.listing_ids(db, _filter_from(b))
        n, still = orders.set_manual_lock(db, ids, bool(b.get("lock")))
        return jsonify({"count": n, "still_locked": still})

    # ── 단어 사전 (재조합 새 단어, 금지 단어)

    @app.get("/api/lexicon")
    def lexicon_get():
        return jsonify(lexicon.export_text(db))

    @app.post("/api/lexicon")
    def lexicon_save():
        b = body()
        lexicon.save_text(db, b.get("groups", ""), b.get("blocked", ""), b.get("opendict"), b.get("attrs"))
        return jsonify(lexicon.export_text(db))

    @app.post("/api/lexicon/preview")
    def lexicon_preview():
        """재조합 미리보기: 상품명(또는 원본 번호)으로 이름 몇 개를 만들어 본다. 저장하지 않음."""
        from . import namegen
        b = body()
        name, category = (b.get("name") or "").strip(), (b.get("category") or "").strip()
        cfg = config.load()
        lex = lexicon.get(db)
        core, kw = (b.get("core") or "").strip(), []
        if b.get("source_id"):
            src = db.one("SELECT id, name, category, core_kw, data FROM sources WHERE id=?", (int(b["source_id"]),))
            if src:
                name, category = src["name"], src["category"]
                core, kw = keywords.words_for(db, [src], cfg, lex)[src["id"]]
        if not name:
            return fail("상품명을 넣어 주세요.")
        core = core or keywords.detect_core(name, lex, None, keywords._learned(db))
        out = namegen.recombine(name, int(b.get("count") or 5), set(), [name], cfg, seed=f"preview:{time.time()}",
                                lex=lex, category=category, core=core, kw_words=kw)
        orig = name.split()
        cand = namegen.new_word_candidates(name, cfg, lex, category, core, kw)
        return jsonify({
            "original": name, "category": category, "original_len": len(name), "core": core,
            "candidates": [w for w, _, _ in cand], "new_min": int(cfg.get("recombine_new_min") or 0),
            "new_max": int(cfg.get("recombine_new_max") or 0),
            "original_repeat": lexicon.repeated_word(orig, lex, int(cfg.get("max_word_repeat") or 2)),
            "pool": {"synonyms": list(dict.fromkeys(w for t in orig for w in lex.synonyms(t)))[:30],
                     "keywords": kw,
                     "category": lexicon.category_words(category) if cfg.get("use_category_words") else []},
            "marks": [{"word": w, "verdict": v} for w, v in lexicon.marks_in(name, lex)],
            "names": [{"name": n, "len": len(n), "new": [w for w in n.split() if w not in orig]} for n in out],
        })

    @app.post("/api/lexicon/dictfolder")
    def lexicon_dictfolder():
        try:
            tid = tasks.start("dictfile", "사전 폴더 읽기", lambda **kw: lexicon.import_dict_folder(db, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/lexicon/dictfile")
    def lexicon_dictfile():
        """우리말샘·표준국어대사전 '사전 내려받기' 파일 (zip / xml / json)."""
        f = request.files.get("file")
        if not f or not f.filename:
            return fail("파일을 골라 주세요.")
        if not f.filename.lower().endswith((".zip", ".xml", ".json")):
            return fail("사전 내려받기 파일(zip, xml, json)만 넣을 수 있습니다.")
        path = _save_upload(f)
        name = f.filename

        def job(progress, should_stop):
            try:
                with open(path, "rb") as fh:
                    return lexicon.import_dictionary(db, fh, name, progress=progress, should_stop=should_stop)
            finally:
                os.remove(path)
        try:
            return jsonify({"task": tasks.start("dictfile", f"사전 파일 넣기 · {name}", job)})
        except RuntimeError as e:
            os.remove(path)
            return fail(str(e))

    @app.post("/api/lexicon/fetch")
    def lexicon_fetch():
        cfg = config.load()
        try:
            tid = tasks.start("lexicon", "우리말샘에서 유의어 받기", lambda **kw: lexicon.fetch_opendict(db, cfg, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    # ── 상표 확인 (키프리스)

    @app.get("/api/trademark")
    def trademark_list():
        from . import kipris
        cfg = config.load()
        st = db.one("""SELECT COUNT(*) AS checked, SUM(verdict='registered') AS registered, SUM(verdict='pending') AS pending,
            SUM(verdict='error') AS errors, SUM(allowed) AS allowed FROM trademark_check""")
        generic, dict_words = kipris._generic(db), kipris._dict_words(db)
        rows = [r for r in db.q("""SELECT word, verdict, allowed, marks, classes, titles, message, checked_at FROM trademark_check
            WHERE verdict IN ('registered','pending','error') ORDER BY allowed, verdict DESC, checked_at DESC LIMIT 2000""")
                if len(r["word"]) >= 3 and r["word"] not in generic and not lexicon.is_dict_word(r["word"], dict_words)][:500]
        fake = os.environ.get("UPLOADER_FAKE_API") == "1"
        return jsonify({
            "stats": {k: st[k] or 0 for k in ("checked", "registered", "pending", "errors", "allowed")},
            "in_dict": db.one("SELECT COUNT(*) AS n FROM word_dict WHERE in_dict=1")["n"],
            "todo": len(kipris.words_to_check(db, "all", 10 ** 6)),
            "has_key": bool(cfg.get("kipris_key")) or fake,
            "has_opendict": bool(cfg.get("opendict_key")) or bool(dict_words),
            "rows": rows,
        })

    @app.post("/api/trademark/check")
    def trademark_check():
        from . import kipris
        b = body()
        scope = b.get("scope") if b.get("scope") in ("original", "keywords", "names", "all") else "all"
        cfg = config.load()
        if not cfg.get("kipris_key") and os.environ.get("UPLOADER_FAKE_API") != "1":
            return fail("설정 → 상표 확인에 키프리스(KIPRIS Plus) 키를 먼저 넣어 주세요.")
        try:
            tid = tasks.start("kipris", "키프리스 상표 확인", lambda **kw: kipris.check_words(db, cfg, scope, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/trademark/allow")
    def trademark_allow():
        b = body()
        word = (b.get("word") or "").strip()
        with db.tx() as c:
            c.execute("UPDATE trademark_check SET allowed=? WHERE word=?", (1 if b.get("allowed") else 0, word))
            lexicon._bump(c)
        return jsonify({"ok": True})

    # ── 도둑방지

    @app.get("/api/bait")
    def bait_info():
        on = db.q("""SELECT l.id, l.name, l.price, l.bait, l.bait_state, l.bait_note, l.registered_at, l.channel_no,
            l.sold_count, st.name AS store_name, st.store_url FROM listings l JOIN stores st ON st.id=l.store_id
            WHERE l.bait_state IN ('on','fail') AND l.origin_no!='' ORDER BY l.registered_at LIMIT 2000""")
        return jsonify({"stats": bait.stats(db), "on": on})

    @app.post("/api/bait/restore")
    def bait_restore():
        b = body()
        if b.get("filter"):
            ids = inventory.listing_ids(db, {**b["filter"], "status": "bait"})
        elif b.get("all"):
            ids = [r["id"] for r in db.q("SELECT id FROM listings WHERE bait_state IN ('on','fail') AND origin_no!=''")]
        else:
            ids = [int(i) for i in b.get("ids") or []]
        if not ids:
            return fail("원래 가격으로 되돌릴 복사본이 없습니다.")
        try:
            tid = tasks.start("bait", f"원래 가격으로 {len(ids)}건", lambda **kw: bait.restore(db, ids, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/stores/<int:sid>/watermark")
    def store_watermark(sid):
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return fail("로고 이미지(PNG 권장, 투명 배경)를 골라 주세요.")
        from PIL import Image
        os.makedirs(watermark.WM_DIR, exist_ok=True)
        try:
            Image.open(f.stream).convert("RGBA").save(watermark.logo_path(sid), "PNG")
        except Exception as e:  # noqa: BLE001
            return fail(f"이미지를 읽지 못했습니다: {e}")
        return jsonify({"ok": True})

    @app.delete("/api/stores/<int:sid>/watermark")
    def store_watermark_del(sid):
        p = watermark.logo_path(sid)
        if os.path.exists(p):
            os.remove(p)
        return jsonify({"ok": True})

    @app.get("/api/watermark/preview")
    def watermark_preview():
        """워터마크 미리보기: 원본 번호가 있으면 그 대표 이미지, 없으면 w×h 예시 이미지 (초록 테두리 = 잘려 보이는 정사각형)."""
        from flask import Response
        a = request.args
        cfg = {**config.load(), **{k: a[k] for k in ("wm_position", "wm_square") if a.get(k)}}
        for k in ("wm_size_pct", "wm_opacity", "wm_margin_pct"):
            if a.get(k):
                cfg[k] = float(a[k])
        st = db.store(int(a["store_id"])) if a.get("store_id") else (db.stores() or [{"id": 0, "name": "내 스토어"}])[0]
        if a.get("wm_text") is not None and a.get("wm_text") != "":
            st = {**st, "wm_text": a["wm_text"]}
        data = None
        if a.get("source_id"):
            row = db.source_row(int(a["source_id"]))
            thumbs = convert.thumbnails(row or {})
            if thumbs:
                try:
                    data, _ = naver.downloader()(thumbs[0], naver.image_cache())
                except Exception:  # noqa: BLE001
                    data = None
        if not data or data == b"fake":
            data = watermark.sample(int(a.get("w") or 1000), int(a.get("h") or 1000))
        try:
            out = watermark.apply(data, st, cfg)
        except Exception as e:  # noqa: BLE001
            return fail(f"워터마크를 넣지 못했습니다: {e}")
        return Response(out, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    # ── 네이버 키워드

    @app.get("/api/keywords")
    def keywords_list():
        a = request.args
        cfg = config.load()
        lex = lexicon.get(db)
        page, size = int(a.get("page", 0)), 30
        q = (a.get("q") or "").strip()
        where, args = "WHERE kw_at IS NOT NULL", []
        if q:
            where += " AND core_kw LIKE ?"
            args.append(f"%{q}%")
        total = db.one(f"SELECT COUNT(DISTINCT core_kw) AS n FROM sources {where}", args)["n"]
        cores = db.q(f"""SELECT core_kw AS core, COUNT(*) AS n FROM sources {where} GROUP BY core_kw
            ORDER BY n DESC, core_kw LIMIT ? OFFSET ?""", args + [size, page * size])
        off = {}
        for r in db.q("SELECT core, word FROM kw_off"):
            off.setdefault(r["core"], set()).add(r["word"])
        for c in cores:
            ws = db.q("""SELECT k.word, COUNT(*) AS n, MAX(k.malls) AS malls, v.pc, v.mobile FROM source_kw k
                JOIN sources s ON s.id=k.source_id LEFT JOIN kw_volume v ON v.word=k.word
                WHERE s.core_kw=? GROUP BY k.word ORDER BY n DESC, malls DESC LIMIT 40""", (c["core"],))
            dead = off.get("", set()) | off.get(c["core"], set())
            c["words"] = [{"word": w["word"], "n": w["n"], "malls": w["malls"],
                           "volume": (w["pc"] or 0) + (w["mobile"] or 0) if w["pc"] is not None else None,
                           "off": w["word"] in dead, "all_off": w["word"] in off.get("", set()),
                           "attr": bool(lexicon.attrs_in(w["word"], lex)),
                           "bad": "" if lex.ok_new_word(w["word"]) else ("상표" if lex.mark_of(w["word"]) else "금지")}
                          for w in ws]
        st = db.one("""SELECT COUNT(*) AS total, SUM(kw_at IS NOT NULL) AS done, SUM(core_manual) AS manual
            FROM sources WHERE valid=1""")
        fake = os.environ.get("UPLOADER_FAKE_API") == "1"
        return jsonify({
            "cores": cores, "total": total, "page": page, "size": size,
            "stats": {"sources": st["total"] or 0, "done": st["done"] or 0, "manual": st["manual"] or 0,
                      "queries": db.one("SELECT COUNT(*) AS n FROM kw_query")["n"],
                      "words": db.one("SELECT COUNT(DISTINCT word) AS n FROM source_kw")["n"],
                      "volumes": db.one("SELECT COUNT(*) AS n FROM kw_volume")["n"]},
            "has_key": keywords.has_keys(cfg),
            "has_searchad": bool(cfg.get("searchad_api_key") and cfg.get("searchad_secret")
                                 and cfg.get("searchad_customer_id")) or fake,
            "enabled": bool(cfg.get("use_naver_keywords", True)),
        })

    @app.post("/api/keywords/collect")
    def keywords_collect():
        b = body()
        cfg = config.load()
        ids = None
        if b.get("filter"):
            ids = inventory.source_ids(db, {**_filter_from(b["filter"]), "status": b["filter"].get("status") or "valid"})
            if not ids:
                return fail("대상 상품이 없습니다.")
        elif b.get("source_id"):
            ids = [int(b["source_id"])]
        try:
            tid = tasks.start("keywords", "네이버 키워드 모으기", lambda **kw: keywords.collect(db, cfg, ids, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/keywords/off")
    def keywords_off():
        b = body()
        word, core = (b.get("word") or "").strip(), "" if b.get("all") else (b.get("core") or "").strip()
        if not word:
            return fail("단어가 없습니다.")
        if b.get("off"):
            db.x("INSERT OR IGNORE INTO kw_off(core, word) VALUES(?,?)", (core, word))
        else:
            db.x("DELETE FROM kw_off WHERE word=? AND (core=? OR ?)", (word, core, 1 if b.get("all") else 0))
        return jsonify({"ok": True})

    @app.get("/api/orders/list")
    def order_rows():
        a = request.args
        f = {k: a.get(k) for k in ("store_id", "matched", "status", "q", "source_id") if a.get(k)}
        if a.get("from"):
            f["from_ts"] = _date_ts(a.get("from"))
        if a.get("to"):
            f["to_ts"] = _date_ts(a.get("to"), end=True)
        page, size = int(a.get("page", 0)), min(int(a.get("size", 100)), 500)
        res = orders.query_orders(db, f, page, size)
        res["auto"] = auto
        res["stores"] = [{"id": s["id"], "name": s["name"], "code": s["code"], "synced_to": s["orders_synced_to"],
                          "has_keys": s["has_keys"]} for s in db.stores()]
        return jsonify(res)

    @app.post("/api/orders/rematch")
    def order_rematch():
        return jsonify({"matched": orders.rematch(db)})

    @app.get("/api/orders")
    def order_list():
        lid = request.args.get("listing_id")
        if lid:
            return jsonify(db.q("SELECT * FROM orders WHERE listing_id=? ORDER BY ordered_at DESC LIMIT 200", (int(lid),)))
        return jsonify(db.one("""SELECT COUNT(*) AS orders, SUM(listing_id IS NOT NULL) AS matched,
            SUM(listing_id IS NULL) AS unmatched, MAX(created_at) AS last_at FROM orders"""))

    @app.post("/api/listings/cancel")
    def cancel():
        f = _filter_from(body())
        where, args = inventory.listing_where(f)
        if runner.state["running"]:
            return fail("등록이 끝난 뒤에 취소할 수 있습니다.")
        ids = inventory.listing_ids(db, f)
        if not ids:
            return jsonify({"cancelled": 0})
        n = 0
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            n += inventory.cancel_listings(db, f"id IN ({','.join('?' * len(chunk))})", chunk)
        return jsonify({"cancelled": n})

    @app.get("/api/listings/export.csv")
    def export():
        f = _filter_from(request.args)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["스토어", "판매자 관리코드", "회차", "등록 상품명", "원본 번호", "원본 판매자코드", "원본 상품명",
                    "판매가", "원본가", "상태", "할 일", "올린 날", "원상품번호", "채널상품번호", "메시지"])
        page = 0
        while True:
            res = inventory.query_listings(db, f, page, 500)
            for r in res["rows"]:
                w.writerow([r["store_name"], r["seller_code"], r["round"], r["name"], r["source_id"], r["source_code"],
                            r["source_name"], r["price"], r["source_price"], r["status"], r["op"],
                            time.strftime("%Y-%m-%d", time.localtime(r["registered_at"])) if r["registered_at"] else "",
                            r["origin_no"], r["channel_no"], r["message"]])
            if len(res["rows"]) < 500:
                break
            page += 1
        name = f"listings_{time.strftime('%Y%m%d_%H%M')}.csv"
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={name}"})

    # ── 등록 실행

    @app.post("/api/run/estimate")
    def run_estimate():
        f = _filter_from(body())
        targets = engine.listing_targets(db, f)
        where, args = inventory.listing_where({**f, "status": "noname"})
        noname = db.one(f"SELECT COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id{where}", args)["n"]
        return jsonify({**engine.estimate(db, targets, config.load()), "noname": noname})

    @app.post("/api/run")
    def run_start():
        b = body()
        try:
            runner.start({**_filter_from(b), "limit": b.get("limit")})
        except (RuntimeError, naver.ApiError) as e:
            return fail(str(e))
        return jsonify(runner.snapshot())

    @app.get("/api/run")
    def run_state():
        return jsonify(runner.snapshot())

    @app.post("/api/run/<action>")
    def run_control(action):
        if action not in ("pause", "resume", "stop"):
            return fail("알 수 없는 명령입니다.", 404)
        getattr(runner, action)()
        return jsonify(runner.snapshot())

    @app.get("/api/runs")
    def runs():
        return jsonify(db.q("SELECT * FROM runs ORDER BY id DESC LIMIT 200"))

    # ── 주문 자동 가져오기: 프로그램이 켜져 있는 동안 정해진 간격마다

    auto = {"minutes": 0, "last_at": None, "next_at": None, "last_result": ""}

    def auto_sync_loop():
        while True:
            try:
                cfg = config.load()
                minutes = int(cfg.get("orders_auto_sync_minutes") or 0)
                auto["minutes"] = minutes
                now = time.time()
                if minutes <= 0:
                    auto["next_at"] = None
                else:
                    if auto["next_at"] is None:
                        auto["next_at"] = now + 120  # 켜고 2분 뒤 첫 실행
                    if now >= auto["next_at"]:
                        auto["next_at"] = now + minutes * 60
                        pairs = [(s, naver.make_client(s)) for s in db.stores(with_secret=True)
                                 if s["enabled"] and (s["has_keys"] or os.environ.get("UPLOADER_FAKE_API") == "1")]
                        if pairs:
                            tasks.start("orders", f"주문 자동 가져오기 · 스토어 {len(pairs)}곳",
                                        lambda **kw: orders.sync_stores(db, pairs, days=cfg.get("orders_initial_days"), **kw))
                            auto["last_at"] = now
            except RuntimeError:
                pass  # 이미 주문 가져오기가 돌고 있음 → 다음 차례에
            except Exception as e:  # noqa: BLE001
                auto["last_result"] = str(e)
            time.sleep(30)

    def dict_folder_check():
        """켤 때 data/사전 폴더에 새 사전 파일이 있으면 뒤에서 읽는다."""
        time.sleep(3)
        try:  # 이번 업데이트에서 원산지 검사가 바뀜 → 한 번 전체 다시 검사
            if not db.one("SELECT 1 FROM meta WHERE k='revalidate_origin_v2'") and db.one("SELECT 1 FROM sources LIMIT 1"):
                tasks.start("revalidate", "원산지 검사 변경 · 전체 다시 검사", lambda **kw: inventory.revalidate(db, **kw))
            db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('revalidate_origin_v2', '1')")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
        try:
            if lexicon.dict_folder_new(db):
                tasks.start("dictfile", "사전 폴더 읽기 (새 파일)", lambda **kw: lexicon.import_dict_folder(db, **kw))
        except Exception:  # noqa: BLE001
            pass

    if not app.config.get("TESTING"):
        threading.Thread(target=auto_sync_loop, daemon=True).start()
        threading.Thread(target=dict_folder_check, daemon=True).start()

    return app


def _date_ts(v, end=False):
    """'2026-10-01' → 그날 0시(한국 시간) 타임스탬프. end면 다음날 0시."""
    if not v:
        return None
    import datetime
    kst = datetime.timezone(datetime.timedelta(hours=9))
    d = datetime.datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=kst)
    if end:
        d += datetime.timedelta(days=1)
    return d.timestamp()
