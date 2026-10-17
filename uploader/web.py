"""조작 화면 서버. 이 PC(127.0.0.1)에서만 열린다."""

import csv
import io
import os
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from . import config, convert, engine, naver
from .db import DB

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app(db=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    db = db or DB()
    runner = engine.Runner(db)

    def fail(msg, code=400):
        return jsonify({"error": msg}), code

    @app.errorhandler(Exception)
    def on_error(e):
        code = getattr(e, "code", 500)
        if not isinstance(code, int):
            code = 500
        return jsonify({"error": str(e)}), code

    # ── 화면

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html", max_age=0)

    @app.get("/static/<path:name>")
    def static_file(name):
        return send_from_directory(STATIC, name, max_age=0)

    # ── 설정

    @app.get("/api/state")
    def state():
        cfg = config.load()
        cats = naver.cached_categories()
        return jsonify({
            "settings": config.public(cfg),
            "has_keys": config.has_keys(cfg),
            "fake_api": os.environ.get("UPLOADER_FAKE_API") == "1",
            "categories": len(cats) if cats else 0,
            "stats": db.stats(),
        })

    @app.post("/api/settings")
    def save_settings():
        values = request.get_json(force=True) or {}
        for k in ("return_fee", "exchange_fee", "workers"):
            if k in values:
                values[k] = convert.to_int(values[k], config.DEFAULTS[k])
        if "workers" in values:
            values["workers"] = max(1, min(values["workers"], 8))
        if "delay_sec" in values:
            try:
                values["delay_sec"] = max(0.0, float(values["delay_sec"]))
            except (TypeError, ValueError):
                values["delay_sec"] = config.DEFAULTS["delay_sec"]
        cfg = config.save(values)
        return jsonify({"settings": config.public(cfg)})

    @app.post("/api/settings/test")
    def test_connection():
        cfg = config.load()
        try:
            client = naver.make_client(cfg)
            client.test()
            cats = client.categories(refresh=True)
        except naver.ApiError as e:
            return fail(str(e))
        return jsonify({"ok": True, "categories": len(cats)})

    # ── 작업(엑셀)

    @app.get("/api/batches")
    def batches():
        return jsonify(db.batches())

    @app.post("/api/batches")
    def upload_batch():
        f = request.files.get("file")
        if not f or not f.filename:
            return fail("엑셀 파일을 골라 주세요.")
        if not f.filename.lower().endswith((".xlsx", ".xlsm")):
            return fail("xlsx 형식의 엑셀만 불러올 수 있습니다.")
        try:
            bid = engine.import_excel(db, io.BytesIO(f.read()), f.filename)
        except ValueError as e:
            return fail(str(e))
        return jsonify({"id": bid})

    @app.delete("/api/batches/<int:bid>")
    def delete_batch(bid):
        snap = runner.snapshot()
        if snap["running"] and snap["batch_id"] == bid:
            return fail("등록 중인 작업은 지울 수 없습니다.")
        db.delete_batch(bid)
        return jsonify({"ok": True})

    @app.get("/api/batches/<int:bid>/products")
    def products(bid):
        return jsonify(db.products(bid))

    @app.post("/api/batches/<int:bid>/revalidate")
    def revalidate(bid):
        if runner.snapshot()["running"]:
            return fail("등록이 끝난 뒤에 다시 검사할 수 있습니다.")
        engine.revalidate(db, bid)
        return jsonify({"ok": True})

    @app.post("/api/batches/<int:bid>/estimate")
    def estimate(bid):
        body = request.get_json(force=True) or {}
        ids = set(body.get("ids") or [])
        statuses = ("ready", "fail", "duplicate") if ids else ("ready", "fail")
        items = [p for p in db.products(bid) if p["status"] in statuses and (not ids or p["id"] in ids)]
        if body.get("limit"):
            items = items[:int(body["limit"])]
        return jsonify(engine.estimate(db, items, config.load()))

    @app.get("/api/batches/<int:bid>/export.csv")
    def export(bid):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["순번", "id", "판매자코드", "상품명", "판매가", "상태", "원상품번호", "채널상품번호", "메시지"])
        for p in db.products(bid):
            w.writerow([p["idx"] + 1, p["row_key"], p["seller_code"], p["name"], p["price"], p["status"],
                        p["origin_no"], p["channel_no"], p["message"] or " / ".join(p["errors"])])
        name = f"upload_result_{bid}_{time.strftime('%Y%m%d_%H%M')}.csv"
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={name}"})

    # ── 상품 하나

    @app.get("/api/products/<int:pid>")
    def product(pid):
        p = db.product(pid)
        if not p:
            return fail("상품이 없습니다.", 404)
        cfg = config.load()
        row = p["data"]
        cats = naver.cached_categories() or {}
        cat = str(row.get("카테고리") or "").strip()
        srcs = convert.images_to_upload(row, cfg)
        url_map = db.image_map(srcs)
        try:
            body = convert.build_body(row, cfg, cats.get(cat) or f"(카테고리 번호 확인 필요) {cat}", url_map)
        except convert.ConvertError as e:
            body = {"검사 오류": str(e)}
        opts = convert.options(row) or {}
        return jsonify({
            **{k: v for k, v in p.items() if k != "data"},
            "category_id": cats.get(cat),
            "thumbnails": convert.thumbnails(row),
            "detail_images": convert.detail_images(row),
            "images_on_naver": len(url_map),
            "images_total": len(srcs),
            "tags": convert.tags(row),
            "options": opts.get("optionCombinations") or [],
            "option_group": (opts.get("optionCombinationGroupNames") or {}).get("optionGroupName1", ""),
            "fields": {k: row.get(k) for k in ("브랜드", "제조사", "모델명", "원산지", "재고수", "배송비",
                                               "판매상태", "할인가") if row.get(k) not in (None, "")},
            "detail_html": row.get("상세설명") or "",
            "body": body,
            "store_url": cfg.get("store_url", "").rstrip("/"),
        })

    # ── 등록 실행

    @app.post("/api/run")
    def run_start():
        body = request.get_json(force=True) or {}
        try:
            runner.start(int(body["batch_id"]), ids=set(body.get("ids") or []) or None,
                         limit=body.get("limit"))
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
        return jsonify(db.runs())

    return app
