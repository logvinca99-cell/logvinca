"""조작 화면 서버. 이 PC(127.0.0.1)에서만 열린다."""

import csv
import io
import os
import tempfile
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from . import config, convert, engine, inventory, naver, orders
from .db import DB
from .tasks import Tasks

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FILTER_KEYS = ("q", "status", "category", "store_missing", "store_has", "import_id", "max_listings",
               "min_names", "store_id", "plan_id", "op", "age_days", "sold")
STORE_FIELDS = ("name", "code", "client_id", "client_secret", "store_url", "as_phone", "capacity", "enabled", "memo")


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
        ints = ("max_copies", "return_fee", "exchange_fee", "workers_per_store", "max_parallel_stores", "price_round",
                "name_max_len", "ai_names_per_product", "ai_products_per_call", "ai_workers")
        floats = ("delay_sec", "price_jitter_pct", "recombine_max_overlap", "image_cache_gb")
        for k in ints:
            if k in v:
                v[k] = convert.to_int(v[k], config.DEFAULTS[k])
        for k in floats:
            if k in v:
                try:
                    v[k] = max(0.0, float(v[k]))
                except (TypeError, ValueError):
                    v[k] = config.DEFAULTS[k]
        return jsonify({"settings": config.public(config.save(v))})

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
        for k in ("name", "code", "client_id", "client_secret", "store_url", "as_phone", "memo"):
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
        return jsonify(s)

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
        with db.tx() as c:
            added, dup = inventory.add_names(c, int(b["source_id"]), [b.get("name", "")], "manual")
        db.recount_sources([int(b["source_id"])])
        if not added:
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
                                                                 b.get("title") or "", **kw))
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
                                           as_phone=l["as_phone"] or cfg.get("as_phone"))
        except convert.ConvertError as e:
            l["body"] = {"검사 오류": str(e)}
        l["thumb"] = (convert.thumbnails(row) or [""])[0]
        l["source_name"] = row.get("상품명")
        l["source_price"] = convert.to_int(row.get("판매가"))
        return jsonify(l)

    @app.post("/api/listings/schedule")
    def schedule():
        """올라가 있는 건에 새로고침(지우고 다시 올리기) 또는 내리기를 예약한다."""
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
        days = body().get("days")
        try:
            tid = tasks.start("orders", f"주문 가져오기 · 스토어 {len(pairs)}곳",
                              lambda **kw: orders.sync_stores(db, pairs, days=days, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/orders/import")
    def orders_import():
        return file_task("orders", "판매 이력 파일 가져오기", orders.import_sales_file)

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
        targets = engine.listing_targets(db, _filter_from(body()))
        return jsonify(engine.estimate(db, targets, config.load()))

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

    return app
