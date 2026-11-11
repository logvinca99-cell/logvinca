"""조작 화면 서버. 이 PC(127.0.0.1)에서만 열린다."""

import csv
import io
import json
import os
import tempfile
import threading
import time
import uuid

from flask import Flask, Response, jsonify, request, send_from_directory

from . import VERSION, activity, adopt, aiwords, baseprice, srcedit, chem, chrome, clean, eye, excel, mail, nvstate, srctags, ctxkw, templates, trash, config, convert, engine, inventory, keywords, lexicon, naver, optimage, orders, watermark
from .db import DB
from .tasks import Tasks

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FILTER_KEYS = ("q", "status", "category", "ai", "chem", "src_tag", "eye", "adopted", "store_missing", "store_has", "import_id", "max_listings", "price_min", "price_max", "copies",
               "min_names", "store_id", "plan_id", "op", "age_days", "sold", "locked", "nv")
STORE_FIELDS = ("name", "code", "client_id", "client_secret", "store_url", "as_phone", "capacity", "enabled", "memo", "wm_text", "importer",
                "business_id", "chrome_profile", "mail_to")


def _filter_from(src):
    f = {k: src.get(k) for k in FILTER_KEYS if src.get(k) not in (None, "")}
    if "ids" in src and src["ids"] is not None:
        ids = src["ids"]
        # 빈 목록이 오면 '전부'가 아니라 '아무것도 아님' (고른 것 없이 지우기 등이 전체로 번지지 않게)
        f["ids"] = [int(i) for i in (ids.split(",") if isinstance(ids, str) else ids) if str(i).strip()] or [-1]
    if src.get("kinds"):
        f["kinds"] = [str(k) for k in src["kinds"]]
    if src.get("visible"):
        f["visible"] = True
    return f


def _save_upload(f):
    """올린 파일을 임시 파일로 저장 (뒤에서 천천히 읽기 위해)."""
    suffix = os.path.splitext(f.filename)[1].lower()
    fd, path = tempfile.mkstemp(suffix=suffix, dir=config.DATA_DIR)
    with os.fdopen(fd, "wb") as out:
        f.save(out)
    return path


def _clean_old_uploads(hours=6):
    """예전에 올리다 남은 임시 파일(경고 창을 닫았거나 프로그램을 껐을 때) 정리."""
    import glob
    now = time.time()
    for p in glob.glob(os.path.join(config.DATA_DIR, "tmp*")):
        try:
            if p.lower().endswith((".xlsx", ".xlsm", ".csv")) and now - os.path.getmtime(p) > hours * 3600:
                os.remove(p)
        except OSError:
            pass


def create_app(db=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 ** 3
    os.makedirs(config.DATA_DIR, exist_ok=True)
    _clean_old_uploads()
    db = db or DB()
    runner = engine.Runner(db)
    if getattr(db, "_v3", False):
        orders.recount_sold(db)
        db.x("PRAGMA user_version=3")
    tasks = Tasks(*activity.task_hooks(db))

    def _store_names(b, va):
        """요청이 다룬 스토어 이름 (작업 기록용): 주소·본문의 스토어, 아니면 고른 복사본들의 스토어 (최대 3곳)."""
        sid = va.get("sid") or b.get("store_id") or ((b.get("listing_filter") or {}).get("store_id") if isinstance(b.get("listing_filter"), dict) else None)
        if sid and str(sid).isdigit():
            return (db.store(int(sid)) or {}).get("name") or ""
        lids = [int(x) for x in (b.get("ids") or [])[:2000] if str(x).isdigit()] if request.path.startswith("/api/listings") else []
        if va.get("lid"):
            lids = [int(va["lid"])]
        if not lids:
            return ""
        names = [r["name"] for r in db.q(f"""SELECT DISTINCT t.name FROM listings l JOIN stores t ON t.id=l.store_id
            WHERE l.id IN ({','.join('?' * len(lids))}) LIMIT 4""", lids)]
        return ", ".join(names[:3]) + (" 외" if len(names) > 3 else "")

    @app.after_request
    def log_action(resp):
        """성공한 요청(복사본 삭제·대기에 넣기·카테고리 저장 …)을 작업 기록에 한 줄 (작업을 시작한 요청은 작업 쪽에서)."""
        if request.method in ("POST", "PUT", "DELETE") and resp.status_code < 400 and request.endpoint:
            try:
                b = request.get_json(silent=True) or {k: v for k, v in request.form.items()}
                b = b if isinstance(b, dict) else {}
                va = request.view_args or {}
                r = resp.get_json(silent=True) if resp.is_json else None
                store = _store_names(b, va)
                if isinstance(r, dict) and r.get("task"):   # 작업을 시작한 요청: 작업 기록 줄에 스토어·대상 수만 채움
                    n = next((len(b[k]) for k in ("ids", "listing_ids", "source_ids") if isinstance(b.get(k), list)), None)
                    db.x("UPDATE activity SET store=CASE WHEN store='' THEN ? ELSE store END, count=COALESCE(count, ?) WHERE task_id=? "
                         "AND id=(SELECT MAX(id) FROM activity WHERE task_id=?)", (store, n, r["task"], r["task"]))
                else:
                    activity.from_request(db, request.endpoint, va, b, r, store)
            except Exception:  # noqa: BLE001 - 기록 실패로 응답을 막지 않는다
                pass
        return resp

    def fail(msg, code=400):
        return jsonify({"error": msg}), code

    def body():
        return request.get_json(force=True, silent=True) or {}

    @app.errorhandler(Exception)
    def on_error(e):
        code = getattr(e, "code", 500)
        return jsonify({"error": str(e)}), code if isinstance(code, int) else 500

    price_hold = {}   # 가격 칸 확인으로 잡아 둔 파일: 토큰 → (경로, 파일 이름, 잡은 때)

    def _upload_or_held(price_check):
        """올린 파일(또는 가격 확인 뒤 다시 보낸 토큰) → ((경로, 이름), None) 또는 (None, 돌려줄 응답)."""
        tok = request.form.get("token") or ""
        if tok:
            v = price_hold.pop(tok, None)
            if not v or not os.path.exists(v[0]):
                return None, fail("잡아 둔 파일이 없습니다. 파일을 다시 올려 주세요.")
            return (v[0], v[1]), None
        f = request.files.get("file")
        if not f or not f.filename:
            return None, fail("파일을 골라 주세요.")
        if not f.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
            return None, fail("xlsx 또는 csv 파일만 불러올 수 있습니다.")
        path = _save_upload(f)
        if price_check and request.form.get("price_ok") != "1":
            try:   # 가격 칸 + 대표 이미지 주소 겹침 (상품명이 다른데 이미지가 같은 줄)
                scan = inventory.upload_scan(db, excel.iter_rows(path, f.filename))
            except Exception:  # noqa: BLE001 - 읽기 오류는 불러오기 작업에서 알림
                scan = {"price": {"n": 0}, "img": {"n": 0}, "dup": {"n": 0}}
            if scan["price"]["n"] or scan["img"]["n"] or scan["dup"]["n"]:
                now = time.time()
                for k, v in list(price_hold.items()):   # 한 시간 넘게 둔 것은 지움
                    if now - v[2] > 3600:
                        price_hold.pop(k, None)
                        try:
                            os.remove(v[0])
                        except OSError:
                            pass
                tok = uuid.uuid4().hex
                price_hold[tok] = (path, f.filename, now)
                return None, jsonify({"price_warn": scan["price"], "img_dup": scan["img"], "name_dup": scan["dup"], "token": tok, "file": f.filename})
        return (path, f.filename), None

    @app.post("/api/upload/drop")
    def upload_drop():
        v = price_hold.pop(str(body().get("token") or ""), None)
        if v:
            try:
                os.remove(v[0])
            except OSError:
                pass
        return jsonify({"ok": True})

    def file_task(kind, title, fn, price_check=False):
        got, resp = _upload_or_held(price_check)
        if resp is not None:
            return resp
        path, name = got

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
            "data_dir": config.DATA_DIR,
            "version": VERSION, "program_dir": config.ROOT,
            "categories": len(cats) if cats else 0,
            "stats": db.stats(),
            "tasks": tasks.list(),
            "running": runner.state["running"],
            "ctx": ctxkw.live_status(db),   # AI 키워드 일괄 처리·실패 현황 (오른쪽 아래)
            "mail_warn_open": db.one("SELECT COUNT(*) AS n FROM mails WHERE kind='warn' AND handled=0")["n"],
        })

    # ── 상세 정리 (셀업 엑셀 → 정리함 → 원본)

    @app.post("/api/clean/import")
    def clean_import():
        got, resp = _upload_or_held(True)
        if resp is not None:
            return resp
        path, name = got
        opts = {k: request.form.get(k, "1") == "1" for k in ("price", "code", "info", "store_tag")}
        opts["tags"] = request.form.get("tags") or ""
        opts["skip_img_dup"] = request.form.get("img_dup") == "drop"

        def job(**kw):
            try:
                return clean.import_excel(db, path, name, opts, **kw)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        try:
            return jsonify({"task": tasks.start("clean_import", f"상세 정리 · 엑셀 올리기 · {name}", job)})
        except RuntimeError as e:
            try:
                os.remove(path)
            except OSError:
                pass
            return fail(str(e))

    @app.get("/api/clean/<int:bid>/tags")
    def clean_tags_get(bid):
        return jsonify(clean.batch_tags(db, bid))

    @app.post("/api/clean/<int:bid>/tags")
    def clean_tags(bid):
        b = body()
        return jsonify(clean.set_batch_tags(db, bid, b.get("tags"), b.get("store_tag", True)))

    @app.get("/api/clean/batches")
    def clean_batches():
        return jsonify(clean.batches(db))

    @app.get("/api/clean/<int:bid>")
    def clean_batch(bid):
        b = db.one("SELECT * FROM clean_batch WHERE id=?", (bid,))
        if not b:
            return fail("정리함 묶음이 없습니다.", 404)
        return jsonify({**b, "counts": clean.counts(db, bid)})

    @app.get("/api/clean/<int:bid>/items")
    def clean_items(bid):
        a = request.args
        return jsonify(clean.items(db, bid, a.get("status") or "", (a.get("q") or "").strip(), int(a.get("page") or 1),
                                   min(500, int(a.get("size") or 100))))

    @app.get("/api/clean/item")
    def clean_item_get():
        a = request.args
        r = clean.item(db, int(a.get("id") or 0) or None, int(a.get("batch_id") or 0) or None, int(a.get("ord") or 0) or None)
        return jsonify(r) if r else fail("그 행의 상품이 없습니다.", 404)

    @app.post("/api/clean/item/<int:iid>/detail")
    def clean_item_detail(iid):
        try:
            return jsonify(clean.save_detail(db, iid, body().get("html")))
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/clean/item/<int:iid>/revert")
    def clean_item_revert(iid):
        return jsonify({"ok": clean.revert_detail(db, iid)})

    @app.post("/api/clean/items/delete")
    def clean_items_delete():
        return jsonify({"count": clean.delete_items(db, body().get("ids") or [])})

    @app.post("/api/clean/items/restore")
    def clean_items_restore():
        return jsonify({"count": clean.restore_items(db, body().get("ids") or [])})

    @app.post("/api/clean/<int:bid>/common")
    def clean_common(bid):
        return jsonify(clean.common_images(db, bid, int(body().get("min") or 10)))

    @app.post("/api/clean/<int:bid>/common/remove")
    def clean_common_remove(bid):
        b = body()
        try:
            return jsonify(clean.remove_common(db, bid, b.get("srcs") or [], bool(b.get("remember"))))
        except ValueError as e:
            return fail(str(e))

    @app.get("/api/clean/rules")
    def clean_rules():
        return jsonify(clean.rules(db))

    @app.post("/api/clean/rules/delete")
    def clean_rules_delete():
        return jsonify({"count": clean.delete_rules(db, body().get("ids") or [])})

    @app.post("/api/clean/<int:bid>/phones")
    def clean_phones(bid):
        return jsonify(clean.find_phones(db, bid))

    @app.post("/api/clean/phones/remove")
    def clean_phones_remove():
        return jsonify(clean.remove_phones(db, body().get("picks") or []))

    @app.post("/api/clean/<int:bid>/broken")
    def clean_broken(bid):
        return jsonify(clean.broken_details(db, bid))

    @app.post("/api/clean/<int:bid>/missing")
    def clean_missing(bid):
        return jsonify(clean.missing_fields(db, bid, body().get("cols")))

    @app.post("/api/clean/<int:bid>/categories")
    def clean_categories(bid):
        return jsonify(clean.categories(db, bid))

    @app.post("/api/clean/<int:bid>/category")
    def clean_category(bid):
        b = body()
        try:
            return jsonify({"count": clean.set_category(db, bid, b.get("to"), b.get("from"), b.get("ids"))})
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/clean/<int:bid>/chem")
    def clean_chem(bid):
        try:
            return jsonify({"task": tasks.start("clean_chem", f"상세 정리 · 생활화학 판정 · 묶음 #{bid}",
                                                lambda **kw: clean.judge_chem(db, bid, **kw))})
        except RuntimeError as e:
            return fail(str(e))

    @app.get("/api/clean/<int:bid>/hold")
    def clean_hold(bid):
        return jsonify(clean.hold_list(db, bid))

    @app.post("/api/clean/items/chem")
    def clean_items_chem():
        b = body()
        try:
            return jsonify({"count": clean.set_chem(db, b.get("ids") or [], b.get("kind"))})
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/clean/<int:bid>/send")
    def clean_send(bid):
        b = body()
        try:
            return jsonify({"task": tasks.start("clean_send", f"상세 정리 → 원본 상품 · 묶음 #{bid}",
                                                lambda **kw: clean.to_sources(db, bid, b.get("ids"), **kw))})
        except RuntimeError as e:
            return fail(str(e))

    @app.get("/api/clean/<int:bid>/export")
    def clean_export(bid):
        try:
            data, name = clean.export_xlsx(db, bid)
        except ValueError as e:
            return fail(str(e))
        from urllib.parse import quote
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    # ── 생활화학/살생물제 인증 판정 (이미 넣은 원본·실패한 복사본)

    @app.post("/api/chem/judge")
    def chem_judge():
        ids = _ctx_sources(body())
        if not ids:
            return fail("고른 원본이 없습니다.")
        try:
            return jsonify({"task": tasks.start("chem", f"생활화학 판정 · 원본 {len(ids):,}개",
                                                lambda **kw: chem.judge_sources(db, ids, **kw))})
        except RuntimeError as e:
            return fail(str(e))

    @app.post("/api/chem/set")
    def chem_set():
        b = body()
        ids = _ctx_sources(b)
        if not ids:
            return fail("고른 원본이 없습니다.")
        try:
            return jsonify({"count": chem.set_judge(db, ids, b.get("kind") or "")})
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/chem/delete_preview")
    def chem_delete_preview():
        ids = _ctx_sources(body())
        # 실제 삭제와 같은 판정: 잠긴 줄(상태 상관없음)이 있는 원본은 남김, 잠기지 않은 판매 중(·처리 중) 복사본은 내림
        agg = {r["source_id"]: r for r in db.q(f"""SELECT source_id, MAX(locked) AS locked,
            SUM(locked=0 AND status!='deleted' AND (origin_no!='' OR status IN ('queued','running'))) AS n FROM listings
            WHERE source_id IN ({','.join('?' * len(ids)) or 'NULL'}) GROUP BY source_id""", ids)} if ids else {}
        kept = sum(1 for r in agg.values() if r["locked"])
        later = [r for r in agg.values() if r["locked"] or r["n"]]
        return jsonify({"sources": len(ids), "now": len(ids) - len(later), "drop_sources": sum(1 for r in later if not r["locked"]),
                        "drop_listings": sum(r["n"] or 0 for r in later), "kept_sold": kept})

    @app.post("/api/chem/delete")
    def chem_delete():
        """원본·복사본 모두 삭제: 안 올라간 것은 바로 휴지통, 판매 중인 복사본은 네이버에서 내린 뒤 원본도 휴지통 (판매 이력·잠금은 남김).
        등록이 도는 중이면 지금 처리 중인 것은 건드리지 않고, 내리기는 대기에 넣는다(끝난 뒤 시작에서)."""
        b = body()
        ids = _ctx_sources(b)
        if not ids:
            return fail("고른 원본이 없습니다.")
        out = chem.delete_sources_everywhere(db, ids)
        drop = out.pop("drop_scheduled")
        out.update(dropping=len(drop), started=False, queued=bool(drop) and runner.state["running"], drop_ids=drop)
        if drop and b.get("now", True) and not runner.state["running"]:
            try:
                runner.start({"ids": drop, "kinds": ["delete"]})
                out["started"] = True
            except (RuntimeError, naver.ApiError) as e:
                out["error"] = str(e)
        return jsonify(out)

    # ── 구글 메일함

    @app.get("/api/mails")
    def mails():
        a = request.args
        return jsonify(mail.query(db, a.get("kind") or "", a.get("store_id") or None, (a.get("q") or "").strip(),
                                  a.get("handled"), int(a.get("page") or 1), min(500, int(a.get("size") or 100))))

    @app.post("/api/mails/fetch")
    def mails_fetch():
        cfg, days = config.load(), body().get("days")
        try:
            return jsonify({"task": tasks.start("mail", "구글 메일함 가져오기", lambda **kw: mail.fetch(db, cfg, days, **kw))})
        except RuntimeError as e:
            return fail(str(e))

    @app.post("/api/mails/<int:mid>/handled")
    def mail_handled(mid):
        db.x("UPDATE mails SET handled=? WHERE id=?", (int(bool(body().get("handled", True))), mid))
        return jsonify({"ok": True})

    # ── 판매자센터를 스토어별 크롬 프로필로 열기

    @app.get("/api/chrome/profiles")
    def chrome_profiles():
        return jsonify({"profiles": chrome.profiles(), "chrome": chrome.find_chrome()})

    @app.post("/api/stores/<int:sid>/open_seller")
    def store_open_seller(sid):
        st = db.store(sid)
        if not st:
            return fail("스토어를 찾지 못했습니다.", 404)
        url = str(body().get("url") or "https://sell.smartstore.naver.com/")
        if not url.startswith("https://sell.smartstore.naver.com/"):
            return fail("판매자센터 주소만 열 수 있습니다.")
        if not st.get("chrome_profile"):
            return jsonify({"opened": False, "reason": "이 스토어에 크롬 프로필이 정해져 있지 않습니다 (스토어 '수정')."})
        return jsonify(chrome.open_url(url, st["chrome_profile"]))

    @app.get("/api/activity")
    def activity_list():
        a = request.args
        return jsonify(activity.query(db, a.get("grp") or "", (a.get("q") or "").strip(), a.get("days") or None,
                                      int(a.get("page") or 1), min(500, int(a.get("size") or 100))))

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
        ints = ("recombine_fixed_prefix", "recombine_new_min", "recombine_new_max", "max_word_repeat", "opendict_daily_limit", "kipris_limit", "kw_daily_limit", "kw_min_volume", "kw_related_max", "kw_refresh_days", "kw_max_words", "core_scan_words", "orders_auto_sync_minutes", "orders_initial_days", "mail_days", "mail_auto_minutes", "max_copies", "return_fee", "exchange_fee", "workers_per_store", "max_parallel_stores", "price_round",
                "name_max_len", "ai_names_per_product", "ai_products_per_call", "ai_workers")
        floats = ("wm_size_pct", "wm_opacity", "wm_margin_pct", "recombine_replace_ratio", "delay_sec", "price_jitter_pct", "price_jitter_min", "price_jitter_max", "display_discount_pct", "recombine_max_overlap", "image_cache_gb")
        for k in ints:
            if k in v:
                v[k] = convert.to_int(v[k], config.DEFAULTS[k])
        for k in floats:
            if k in v:
                try:
                    f = float(v[k])
                    v[k] = max(-30.0, min(30.0, f)) if k in ("price_jitter_min", "price_jitter_max") else max(0.0, f)   # 흔들기는 음수 허용
                except (TypeError, ValueError):
                    v[k] = config.DEFAULTS[k]
        if "stock_fixed" in v:
            v["stock_fixed"] = max(0, convert.to_int(v["stock_fixed"], 1000))
        if "display_discount_pct" in v and not 0 <= v["display_discount_pct"] < 90:
            return fail("표시 할인율은 0~89% 사이로 넣어 주세요.")
        if v.get("price_jitter_min", 0) > v.get("price_jitter_max", 0) and "price_jitter_min" in v and "price_jitter_max" in v:
            return fail("흔들기 최소 %가 최대 %보다 클 수 없습니다.")
        before = config.load()
        cfg = config.save(v)
        activity.settings_changed(db, before, cfg)
        if any(before.get(k) != cfg.get(k) for k in ("lock_sold", "lock_canceled_too")):
            orders.recount_sold(db)  # 잠금 기준이 바뀌었으면 전체 다시 계산
        if any(before.get(k) != cfg.get(k) for k in ("origin_force", "origin_country", "origin_codes", "origin_default")):
            try:  # 원산지 기준이 바뀌었으면 전체 원본을 다시 검사 (오류 표시가 바로 바뀌게)
                tasks.start("revalidate", "원산지 설정이 바뀌어 전체 다시 검사", lambda **kw: inventory.revalidate(db, **kw))
            except RuntimeError:
                pass
        if any(before.get(k) != cfg.get(k) for k in ("price_jitter_min", "price_jitter_max", "price_round")):
            inventory.reprice_pending(db)   # 가격 기본값이 바뀌면 아직 안 올린 복사본 가격도 바로 (템플릿을 바꿀 때와 같게)
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
            rows = db.q("""SELECT l.id, l.store_id, s.price, COALESCE(NULLIF(s.price_seed,''), s.source_key) AS source_key, st.tpl_price_pct, st.tpl_jitter_min, st.tpl_jitter_max FROM listings l
                JOIN sources s ON s.id=l.source_id JOIN stores st ON st.id=l.store_id
                WHERE l.origin_no='' AND l.status IN ('planned','fail') AND l.price_fixed=0""")
            with db.tx() as c:
                for r in rows:
                    c.execute("UPDATE listings SET price=? WHERE id=?",
                              (convert.store_price(r["price"], f"{r['source_key']}|{r['store_id']}", cfg, r),
                               r["id"]))
            return jsonify({"count": len(rows)})
        if what == "names":
            n = db.one("SELECT COUNT(*) AS n FROM names WHERE listing_id IS NULL AND origin IN ('recombine','ai','ctx','shuffle')")["n"]
            db.x("DELETE FROM names WHERE listing_id IS NULL AND origin IN ('recombine','ai','ctx','shuffle')")
            db.x("UPDATE ctx_kw SET names_made=0 WHERE status='ok'")   # 맥락 키워드는 그대로, 이름은 다음에 다시 만듦
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

    @app.get("/api/categories/unmatched")
    def categories_unmatched():
        """원본 카테고리 중 네이버에서 못 찾은 것 (개수 많은 순) + 비슷한 네이버 카테고리."""
        cats = naver.cached_categories()
        info = {"cached": len(cats or {}), "cached_at": naver.category_cache_time()}
        if not cats:
            return jsonify({**info, "items": []})
        cfg = config.load()
        items = []
        for r in db.q("SELECT category, COUNT(*) AS n FROM sources WHERE category_fix='' GROUP BY category ORDER BY n DESC"):
            if not r["category"]:
                continue
            cid, _ = convert.find_category(r["category"], cats, cfg)
            if not cid:
                g, gname = convert.find_category(r["category"], cats, cfg, guess=True)
                sug = convert.category_suggestions(r["category"], cats)
                if g:   # 이름이 거의 같은 네이버 카테고리 → 맨 앞에 두고 미리 골라 둠 (저장해야 등록됨)
                    sug = [gname] + [x for x in sug if x != gname]
                items.append({"category": r["category"], "count": r["n"], "how": "", "guess": gname if g else "", "suggest": sug})
        return jsonify({**info, "items": items})

    @app.post("/api/sources/category")
    def sources_category():
        """원본의 네이버 카테고리를 직접 정함 (복사본 화면에서 고르면 그 원본에) — set_category가 비면 엑셀 카테고리로 되돌림.
        (category는 화면 거르기 조건이라 고른 값은 set_category로 받음)"""
        b = body()
        path = str(b.get("set_category") or "").strip()
        ids = _ctx_sources(b)
        if not ids:
            return fail("고른 원본이 없습니다.")
        try:
            n = inventory.set_category_fix(db, ids, path)
        except ValueError as e:
            return fail(str(e))
        return jsonify({"count": n, "category": path})

    @app.get("/api/optimg/<k>/<int:i>.jpg")
    def option_image(k, i):
        """상세 옵션표 그림 미리보기 (올리기 전, 이 PC에서 그림)."""
        try:
            data = optimage.preview(k, i, lambda u: naver.downloader()(u, naver.image_cache(config.load()))[0])
        except Exception as e:  # noqa: BLE001
            return Response(f"옵션표 그림을 만들지 못했습니다: {e}", status=500, mimetype="text/plain")
        if data is None:
            return fail("옵션표 그림이 없습니다.", 404)
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/categories/search")
    def categories_search():
        cats = naver.cached_categories() or {}
        words = [w for w in (request.args.get("q") or "").split() if w]
        if not words:
            return jsonify([])
        out = [n for n in cats if all(w in n for w in words)]
        out.sort(key=len)
        return jsonify(out[:40])

    @app.post("/api/categories/map")
    def categories_map():
        """엑셀 카테고리를 네이버 카테고리로 맞춰 두기 (to를 비우면 지움). 저장 뒤 전체 다시 검사."""
        b = body()
        pairs = b.get("items") or [{"from": b.get("from"), "to": b.get("to")}]
        cats = naver.cached_categories() or {}
        m = dict(config.load().get("category_map") or {})
        for p in pairs:
            src, to = str(p.get("from") or "").strip(), str(p.get("to") or "").strip()
            if not src:
                continue
            if to and to not in cats:
                return fail(f"네이버 카테고리 '{to}'가 목록에 없습니다.")
            if to:
                m[src] = to
            else:
                m.pop(src, None)
        config.save({"category_map": m})
        try:
            tasks.start("revalidate", "카테고리 맞춘 뒤 전체 다시 검사", lambda **kw: inventory.revalidate(db, **kw))
        except RuntimeError:
            pass
        return jsonify({"ok": True, "count": len(m)})

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
        if "business_id" in v:
            v["business_id"] = int(v["business_id"]) if str(v["business_id"] or "").isdigit() else None
            if v["business_id"]:
                n = db.one("SELECT COUNT(*) AS n FROM stores WHERE business_id=? AND id!=?", (v["business_id"], int(sid or 0)))["n"]
                if n >= 3:
                    return fail("이 사업자에는 이미 스토어가 3개 있습니다 (사업자 하나에 최대 3개).")
        for k in ("name", "code", "client_id", "client_secret", "store_url", "as_phone", "memo", "wm_text", "importer", "chrome_profile", "mail_to"):
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

    # ── 사업자: 스토어를 사업자별로 묶고 순서를 정한다

    @app.get("/api/businesses")
    def businesses():
        return jsonify(db.q("SELECT * FROM businesses ORDER BY sort, id"))

    @app.post("/api/businesses")
    def save_business():
        b = body()
        name = str(b.get("name") or "").strip()
        if not name:
            return fail("사업자 이름을 넣어 주세요.")
        vals = (name, str(b.get("reg_no") or "").strip(), str(b.get("memo") or "").strip())
        if b.get("id"):
            db.x("UPDATE businesses SET name=?, reg_no=?, memo=? WHERE id=?", (*vals, int(b["id"])))
            bid = int(b["id"])
        else:
            mx = db.one("SELECT COALESCE(MAX(sort), 0) AS m FROM businesses")["m"]
            bid = db.x("INSERT INTO businesses(name, reg_no, memo, sort, created_at) VALUES(?,?,?,?,?)", (*vals, mx + 1, time.time()))
        return jsonify(db.one("SELECT * FROM businesses WHERE id=?", (bid,)))

    @app.delete("/api/businesses/<int:bid>")
    def delete_business(bid):
        db.x("UPDATE stores SET business_id=NULL WHERE business_id=?", (bid,))   # 스토어는 '사업자 없음'으로
        db.x("DELETE FROM businesses WHERE id=?", (bid,))
        return jsonify({"ok": True})

    @app.post("/api/businesses/order")
    def order_businesses():
        with db.tx() as c:
            for i, bid in enumerate(body().get("ids") or [], 1):
                c.execute("UPDATE businesses SET sort=? WHERE id=?", (i, int(bid)))
        return jsonify({"ok": True})

    @app.post("/api/stores/order")
    def order_stores():
        """스토어 순서 (사업자 안에서). ids: 그 사업자의 스토어 id를 원하는 순서로. business_id를 주면 그 사업자로 옮김."""
        b = body()
        ids = [int(i) for i in b.get("ids") or []]
        bid = b.get("business_id", "keep")
        if bid != "keep":
            bid = int(bid) if bid not in (None, "") else None
            if bid and db.one(f"SELECT COUNT(*) AS n FROM stores WHERE business_id=? AND id NOT IN ({','.join('?' * len(ids)) or 'NULL'})",
                              (bid, *ids))["n"] + len(ids) > 3:
                return fail("사업자 하나에 스토어는 최대 3개입니다.")
        with db.tx() as c:
            for i, sid in enumerate(ids, 1):
                if bid == "keep":
                    c.execute("UPDATE stores SET sort=? WHERE id=?", (i, sid))
                else:
                    c.execute("UPDATE stores SET sort=?, business_id=? WHERE id=?", (i, bid, sid))
        return jsonify({"ok": True})

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
            st = client.status_counts()   # 상품 목록을 끝까지 받아 상태별로 셈 (판매 중·판매중지 구분)
            count = st.get("_total", 0)
        except naver.ApiError as e:
            return fail(str(e))
        hidden = st.get("_disp_SUSPENSION", 0)   # 고구마 = 전시중지 상품 (판매중지는 고구마가 아님)
        db.x("UPDATE stores SET naver_count=?, naver_count_at=?, naver_sale=?, naver_suspended=?, naver_status=? WHERE id=?",
             (count, time.time(), count - hidden, hidden, json.dumps(st), sid))
        if not s.get("store_url"):   # 스토어 주소를 아직 안 넣었으면 네이버에서 받아 채움 (스토어 바로 가기 버튼)
            url = client.store_url()
            if url:
                db.x("UPDATE stores SET store_url=? WHERE id=?", (url, sid))
        if not naver.cached_categories():
            try:
                client.categories(refresh=True)
                # 카테고리를 처음 받았으면, 그 전에 불러온 원본의 카테고리를 다시 검사한다.
                tasks.start("revalidate", "카테고리 받은 뒤 전체 다시 검사",
                            lambda **kw: inventory.revalidate(db, **kw))
            except (naver.ApiError, RuntimeError):
                pass
        return jsonify({"ok": True, "naver_count": count, "sale": count - hidden, "suspended": hidden,
                        "status": {k: v for k, v in st.items() if not k.startswith("_")}, "store": db.store(sid)})

    @app.post("/api/stores/<int:sid>/goguma")
    def store_goguma(sid):
        """고구마(판매중지) 상품 수를 직접 넣기. 비우면 연결 확인 때 받은 수를 씀."""
        v = body().get("count")
        db.x("UPDATE stores SET goguma_manual=? WHERE id=?", (None if v in (None, "") else max(0, int(v)), sid))
        return jsonify(db.store(sid))

    @app.post("/api/stores/<int:sid>/memo")
    def store_memo(sid):
        """스토어 메모 (이 스토어를 무슨 상품으로 채웠고 앞으로 어떻게 할지 — 나만 보는 메모, 적는 대로 저장)."""
        now = time.time()
        db.x("UPDATE stores SET memo=?, memo_at=? WHERE id=?", (str(body().get("memo") or "")[:20000], now, sid))
        return jsonify({"memo_at": now})

    # ── 기존 상품 가져오기 (이미 올린 상품: 업로드했던 엑셀 + 스토어 상품 목록 → 원본 + 판매 중 복사본)

    @app.post("/api/adopt/prepare")
    def adopt_prepare():
        f = request.files.get("file")
        if not f or not f.filename:
            return fail("업로드했던 엑셀 파일을 골라 주세요.")
        if not f.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
            return fail("xlsx 또는 csv 파일만 됩니다.")
        token, path = adopt.save_upload(f, f.filename)
        try:
            return jsonify({"token": token, "file": f.filename, **adopt.prepare(db, path, f.filename)})
        except Exception as e:  # noqa: BLE001
            return fail(f"파일을 읽지 못했습니다: {e}")

    @app.post("/api/adopt/check")
    def adopt_check():
        """가져오기 전에 맞춰 보기 (아무것도 바꾸지 않음): 스토어 상품 목록을 받아 연결될 수·버릴 수·예시."""
        b = body()
        try:
            return jsonify({"task": adopt.check(db, tasks, b.get("token"), b.get("store_id"), b)})
        except (ValueError, RuntimeError) as e:
            return fail(str(e))

    @app.post("/api/adopt/start")
    def adopt_start():
        b = body()
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 가져올 수 없습니다 (처리 중인 복사본과 겹치지 않게). 등록이 끝난 뒤에 다시 시도하세요.")
        try:
            return jsonify({"task": adopt.start(db, tasks, b.get("token"), b.get("store_id"), b)})
        except (ValueError, RuntimeError) as e:
            return fail(str(e))

    @app.get("/api/adopt/<int:rid>/undo")
    def adopt_undo_preview(rid):
        try:
            return jsonify(adopt.undo_preview(db, rid))
        except ValueError as e:
            return fail(str(e), 404)

    @app.post("/api/adopt/<int:rid>/undo")
    def adopt_undo(rid):
        """가져오기 되돌리기: 이 프로그램에서만 뺌 (네이버 상품은 그대로)."""
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 되돌릴 수 없습니다. 끝난 뒤에 다시 시도하세요.")
        try:
            return jsonify(adopt.undo_run(db, rid))
        except ValueError as e:
            return fail(str(e))

    @app.get("/api/adopt/runs")
    def adopt_runs():
        return jsonify(adopt.runs(db))

    # ── 기준 가격 수정 (역마진 등) — 원본 상세 창·엑셀

    @app.get("/api/baseprice/template.xlsx")
    def baseprice_template():
        from urllib.parse import quote
        return Response(baseprice.template_xlsx(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('기준가격_수정양식.xlsx')}"})

    @app.post("/api/baseprice/preview")
    def baseprice_preview():
        """수정 엑셀 미리보기 (아무것도 안 바꿈) — 또는 json {source_id, price}로 한 개."""
        if request.files.get("file"):
            f = request.files["file"]
            path = _save_upload(f)
            try:
                return jsonify(baseprice.preview(db, path, f.filename))
            except Exception as e:  # noqa: BLE001
                return fail(f"파일을 읽지 못했습니다: {e}")
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        b = body()
        new = convert.to_int(b.get("price"))
        if new <= 0 or not db.one("SELECT 1 FROM sources WHERE id=?", (int(b.get("source_id") or 0),)):
            return fail("새 기준 가격을 넣어 주세요.")
        it = {"line": 0, "key": "", "how": "원본 상세", "new": new, "memo": str(b.get("memo") or ""), "status": "ok",
              **baseprice.effect(db, int(b["source_id"]), new)}
        return jsonify({"items": [it], "ok": 1, "bad": 0, "live": it["n_live"], "pending": it["n_pending"], "file": ""})

    @app.post("/api/baseprice/apply")
    def baseprice_apply():
        """기준 가격 바꾸기 → 안 올린 복사본은 바로, 판매 중 복사본은 네이버 가격만 바로 바꾸는 작업."""
        b = body()
        items = [x for x in (b.get("items") or []) if x.get("source_id") and convert.to_int(x.get("price")) > 0]
        if not items:
            return fail("바꿀 원본이 없습니다.")
        st = baseprice.apply(db, items, str(b.get("how") or ""))
        out = {"sources": st["sources"], "pending": st["pending"], "live": len(st["live"]), "task": None}
        if st["live"]:
            try:
                out["task"] = tasks.start("baseprice", f"네이버 가격 바꾸기 · {len(st['live']):,}건",
                                          lambda **kw: baseprice.push_live(db, st["live"], **kw))
            except RuntimeError as e:
                out["error"] = f"네이버 가격 바꾸기를 시작하지 못함 ({e}) — 다음 최신화 때 새 가격으로 올라갑니다"
        return jsonify(out)

    # ── 원본 상세·옵션 고치기 (원본 상세 창)

    @app.get("/api/sources/<int:sid>/content")
    def source_content(sid):
        try:
            return jsonify(srcedit.content(db, sid))
        except ValueError as e:
            return fail(str(e), 404)

    @app.post("/api/sources/<int:sid>/content")
    def source_content_save(sid):
        b = body()
        try:
            return jsonify(srcedit.save(db, sid, detail=b.get("detail"), options=b.get("options"), memo=b.get("memo") or ""))
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/sources/<int:sid>/content_undo")
    def source_content_undo(sid):
        try:
            return jsonify(srcedit.undo_last(db, sid))
        except ValueError as e:
            return fail(str(e))

    @app.get("/api/sources/<int:sid>/price_log")
    def source_price_log(sid):
        return jsonify(baseprice.log(db, sid))

    @app.get("/api/adopt/<int:rid>/drop_sources")
    def adopt_drop_sources(rid):
        return jsonify({"ids": adopt.drop_source_ids(db, rid)})

    @app.get("/api/adopt/<int:rid>/items.csv")
    def adopt_items_csv(rid):
        try:
            data, name = adopt.items_csv(db, rid, request.args.get("kind") or "store_only")
        except ValueError as e:
            return fail(str(e), 404)
        from urllib.parse import quote
        return Response(data, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.get("/api/home/memo")
    def home_memo_get():
        r = {x["k"]: x["v"] for x in db.q("SELECT k, v FROM meta WHERE k IN ('home_memo','home_memo_at')")}
        return jsonify({"memo": r.get("home_memo") or "", "at": float(r["home_memo_at"]) if r.get("home_memo_at") else None})

    @app.post("/api/home/memo")
    def home_memo_set():
        """한눈에 보기 맨 위 업무 메모 (매일 할 일·하고 있는 일 — 적는 대로 저장)."""
        now = time.time()
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('home_memo', ?)", (str(body().get("memo") or "")[:50000],))
            c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('home_memo_at', ?)", (str(now),))
        return jsonify({"at": now})

    @app.post("/api/stores/<int:sid>/region")
    def store_region(sid):
        """스토어 출고 형태 표시 (해외·국내·안 정함)."""
        v = str(body().get("region") or "")
        if v not in ("", "overseas", "domestic"):
            return fail("해외·국내 중에서 골라 주세요.")
        db.x("UPDATE stores SET ship_region=? WHERE id=?", (v, sid))
        return jsonify(db.store(sid))

    # ── 원본 (인벤토리)

    @app.get("/api/sources")
    def sources():
        f = _filter_from(request.args)
        page, size = int(request.args.get("page", 0)), min(int(request.args.get("size", 100)), 500)
        return jsonify({**inventory.query_sources(db, f, page, size), "counts": inventory.source_counts(db)})

    def _source_url(row):
        u = str(row.get("수집URL") or row.get("상품URL") or row.get("원본URL") or "").strip()
        return u if u.lower().startswith(("http://", "https://")) else ""

    @app.get("/api/sources/<int:sid>/origin")
    def source_origin(sid):
        """원본 상품 페이지(엑셀 '수집URL')로 바로 이동."""
        row = db.source_row(sid)
        url = _source_url(row or {})
        if not url:
            return Response("<meta charset=utf-8><p>이 원본에는 수집URL이 없습니다.</p>", status=404, mimetype="text/html")
        return Response(status=302, headers={"Location": url})

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
            "source_url": _source_url(row),
        })
        s["kw"] = _source_kw(sid, row)
        s["ai"] = _source_ai(sid, row)
        s["ctx"] = ctxkw.source_info(db, sid)
        return jsonify(s)

    def _source_ai(sid, row):
        """원본에 받아 둔 AI 단어 (재조합에 쓰는 것 / 빠진 이유)."""
        cfg = config.load()
        lex = lexicon.get(db)
        src = db.one("SELECT id, name FROM sources WHERE id=?", (sid,))
        used = {w for w, _ in aiwords.words_for(db, [{**src, "data": None, "_row": row}], {**cfg, "ai_words_enabled": True},
                                                 lex).get(sid, [])}
        d = aiwords.source_words(db, sid)
        for w in d["words"]:
            w["used"] = w["word"] in used
            w["why"] = "" if w["used"] else ("끈 단어" if w["off"] or w["all_off"] else
                                             "상표 단어" if lex.mark_of(w["word"]) else
                                             "금지 단어" if not lex.ok_new_word(w["word"]) else "원본에 없는 속성")
        d["has_key"] = aiwords.has_key(cfg)
        d["enabled"] = aiwords.enabled(cfg)
        return d

    @app.post("/api/sources/<int:sid>/aiwords")
    def source_aiwords(sid):
        b = request.get_json(force=True) or {}
        if b.get("reset"):
            aiwords.forget(db, sid)
        elif b.get("word"):
            aiwords.set_off(db, sid, str(b["word"]), bool(b.get("off")), bool(b.get("all")))
        return jsonify({"ok": True})

    def _source_kw(sid, row):
        """원본의 네이버 연관 키워드에서 온 새 단어 (재조합에 쓰는 것 / 빠진 이유)."""
        cfg = config.load()
        lex = lexicon.get(db)
        src = db.one("SELECT id, name, kw_at FROM sources WHERE id=?", (sid,))
        _, used = keywords.words_for(db, [{**src, "data": None, "_row": row}], {**cfg, "use_naver_keywords": True},
                                     lex)[sid]
        toks = keywords.head_tokens(src["name"], int(cfg.get("core_scan_words") or 5), lex)
        off = {r["word"] for r in db.q(f"SELECT word FROM kw_off WHERE core IN ('', {','.join('?' * len(toks))})", toks)} \
            if toks else {r["word"] for r in db.q("SELECT word FROM kw_off WHERE core=''")}
        words = []
        for r in db.q("SELECT word, malls FROM source_kw WHERE source_id=? ORDER BY malls DESC", (sid,)):
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
            words.append({**r, "used": r["word"] in used, "why": why})
        return {"tokens": toks, "collected_at": src["kw_at"], "words": words, "has_key": keywords.has_keys(cfg)}

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
        tags, store = request.form.get("tags") or "", request.form.get("store_tag", "0") == "1"
        skip = request.form.get("img_dup") == "drop"   # 대표 이미지 주소 겹치는 줄 버리기 (올릴 때 창에서 고름)
        return file_task("import", "원본 불러오기", lambda db_, fh, name, **kw: inventory.import_products(
            db_, fh, name, src_tags=tags, store_tag=store, skip_img_dup=skip, **kw), price_check=True)

    # ── 출처 태그 (어디서·언제 가져온 원본인지)

    @app.get("/api/srctags")
    def srctags_list():
        return jsonify(srctags.counts(db))

    @app.post("/api/srctags/apply")
    def srctags_apply():
        b = body()
        ids = inventory.source_ids(db, _filter_from(b))
        if not ids:
            return fail("고른 원본이 없습니다.")
        try:
            add, remove = srctags.parse(b.get("add") or []), srctags.parse(b.get("remove") or [])
            return jsonify({"count": srctags.apply(db, ids, add, remove), "target": len(ids), "add": add, "remove": remove})
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/srctags/rename")
    def srctags_rename():
        b = body()
        try:
            return jsonify({"count": srctags.rename(db, b.get("old"), b.get("new"))})
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/srctags/backfill")
    def srctags_backfill():
        b = body()
        try:
            return jsonify({"task": tasks.start("srctags", "예전 원본에 출처 태그 채우기", lambda **kw: srctags.backfill(
                db, bool(b.get("store", True)), bool(b.get("date", True)), **kw))})
        except RuntimeError as e:
            return fail(str(e))

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
        f = _filter_from(b)
        if b.get("reviewed_only"):   # 검수 완료한 원본만 복사
            f["eye"] = "done"
        ids = inventory.source_ids(db, f)
        store_ids = [int(i) for i in b.get("store_ids") or []]
        if not ids:
            return fail("대상 상품이 없습니다." + (" (검수 완료한 원본이 없습니다 — 눈검수를 하거나 '검수 완료로 표시')" if b.get("reviewed_only") else ""))
        if not store_ids:
            return fail("스토어를 하나 이상 골라 주세요.")
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 계획을 만들 수 없습니다. 끝난 뒤에 다시 시도하세요.")
        mode = "spread" if b.get("mode") == "spread" else "all"
        per = max(1, int(b.get("per_product") or 1))
        seed = b.get("seed")   # 미리보기와 같은 배정이 나오게
        try:
            tid = tasks.start("plan", f"등록 계획 · 상품 {len(ids):,}개 × 스토어 {len(store_ids)}곳",
                              lambda **kw: inventory.create_plan(db, ids, store_ids, mode, per,
                                                                 b.get("title") or "", seed=seed, **kw))
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"task": tid})

    @app.post("/api/plans/preview")
    def plan_preview():
        """'원본마다 N곳 골고루' 미리보기: 스토어별 배정 수, 두 스토어가 같은 원본을 공유하는 비율 (계획은 만들지 않음)."""
        b = body()
        ids = inventory.source_ids(db, _filter_from(b))
        store_ids = [int(i) for i in b.get("store_ids") or []]
        if not ids or not store_ids:
            return fail("상품과 스토어를 골라 주세요.")
        seed = int(time.time() * 1000) % 1_000_000_007
        try:
            _, pv = inventory.plan_spread(db, ids, store_ids, max(1, int(b.get("per_product") or 1)), seed)
        except ValueError as e:
            return fail(str(e))
        return jsonify(pv)

    # ── 맥락 키워드 (AI): 실행 전 비용 안내 → 일괄(기본)/즉시

    def _ctx_sources(b):
        if b.get("retry"):   # 실패(재시도 대기)한 원본만 다시
            return [r["source_id"] for r in db.q("SELECT source_id FROM ctx_kw WHERE status='retry' ORDER BY source_id")]
        if b.get("listing_filter"):
            f = _filter_from(b["listing_filter"])
            f.pop("op", None)
            lids = inventory.listing_ids(db, f)
            out = []
            for i in range(0, len(lids), 900):
                chunk = lids[i:i + 900]
                out += [r["source_id"] for r in db.q(f"SELECT DISTINCT source_id FROM listings WHERE id IN ({','.join('?' * len(chunk))})", chunk)]
            return sorted(set(out))
        return inventory.source_ids(db, _filter_from(b))

    @app.post("/api/ctx/estimate")
    def ctx_estimate():
        b = body()
        cfg = config.load()
        return jsonify(ctxkw.estimate(db, cfg, _ctx_sources(b), b.get("mode"), bool(b.get("refresh"))))

    @app.post("/api/ctx/start")
    def ctx_start():
        b = body()
        ids = _ctx_sources(b)
        mode = b.get("mode") or config.load().get("ctx_mode") or "batch"
        refresh = bool(b.get("refresh"))
        if not ctxkw.targets(db, ids, refresh):
            return jsonify({"started": False, "message": "고른 원본은 모두 키워드가 있습니다 (요청 0건). AI를 부르지 않습니다."})
        try:
            if mode == "instant":
                tid = tasks.start("ctxkw", f"AI 키워드 받기(즉시) · 원본 {len(ids):,}개",
                                  lambda **kw: ctxkw.run_instant(db, ids, refresh=refresh, **kw))
                return jsonify({"task": tid})
            r = ctxkw.start_batch(db, ids, refresh)
        except RuntimeError as e:
            return fail(str(e))
        return jsonify({"started": True, **r})

    @app.post("/api/ctx/cancel")
    def ctx_cancel():
        return jsonify(ctxkw.cancel(db))

    @app.post("/api/ctx/check")
    def ctx_check():
        return jsonify(ctxkw.poll(db))

    @app.get("/api/ctx/review")
    def ctx_review():
        kind = request.args.get("kind") if request.args.get("kind") in ("core", "core2", "ctx") else "core"
        return jsonify(ctxkw.core_review(db, kind))

    @app.post("/api/ctx/block")
    def ctx_block():
        b = body()
        try:
            return jsonify(ctxkw.set_block(db, b.get("word"), bool(b.get("block", True))))
        except ValueError as e:
            return fail(str(e))

    @app.get("/api/ctx/status")
    def ctx_status():
        return jsonify({**ctxkw.status(db), "runs": ctxkw.runs(db, 20)})

    @app.get("/api/ctx/runs")
    def ctx_runs():
        return jsonify(ctxkw.runs(db))

    @app.post("/api/lexicon/blocked")
    def lexicon_blocked_save():
        n = lexicon.save_blocked(db, body().get("text") or "")
        return jsonify({"count": n, **lexicon.export_text(db)})

    @app.post("/api/lexicon/blocked/import")
    def lexicon_blocked_import():
        f = request.files.get("file")
        if not f:
            return fail("파일을 골라 주세요.")
        raw = f.read()
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return fail("파일 글자 인코딩을 읽지 못했습니다 (UTF-8 또는 CP949 텍스트 파일).")
        added, existed = lexicon.import_blocked(db, text)
        return jsonify({"added": added, "existed": existed, **lexicon.export_text(db)})

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

    # ── 휴지통: 지우면 휴지통으로 옮기고, 되살리거나 완전히 지운다

    @app.post("/api/sources/bulk_edit")
    def sources_bulk_edit():
        """원본 일괄 수정: 판매자코드 비우기, 재고수(상품·옵션 모두) 바꾸기."""
        b = body()
        ids = inventory.source_ids(db, _filter_from(b))
        if not ids:
            return fail("고른 원본이 없습니다.")
        stock = b.get("stock")
        stock = None if stock in (None, "") else max(0, int(stock))
        clear = bool(b.get("clear_seller_code"))
        if stock is None and not clear:
            return fail("바꿀 항목을 고르세요.")
        return jsonify(inventory.bulk_edit_sources(db, ids, clear, stock))

    @app.post("/api/sources/delete")
    def sources_delete():
        """원본을 휴지통으로. keep_naver: 판매 중인 복사본이 있어도 이 프로그램에서만 뺌 (네이버 상품은 그대로 — 내리지 않음).
        listing_filter: 복사본 화면에서 고른 복사본의 원본."""
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 지울 수 없습니다. 끝난 뒤에 다시 시도하세요.")
        b = body()
        ids = _ctx_sources(b) if b.get("listing_filter") else inventory.source_ids(db, _filter_from(b))
        if not ids:
            return fail("고른 원본이 없습니다.")
        return jsonify(trash.trash_sources(db, ids, keep_naver=bool(b.get("keep_naver"))))

    @app.post("/api/listings/delete")
    def listings_delete():
        # 등록이 도는 중에도 됨: 지금 처리 중(queued·running)이거나 네이버에 올라간 것은 trash 쪽에서 건너뜀
        b = body()
        f = _filter_from(b)
        f.pop("op", None)
        ids = inventory.listing_ids(db, f)
        if not ids:
            return fail("고른 복사본이 없습니다.")
        sids = _source_ids_of(ids)
        keep = bool(b.get("keep_naver"))   # 판매 중인 것도 이 프로그램에서만 뺌 (네이버 상품은 그대로)
        out = trash.trash_listings(db, ids, keep_naver=keep)
        if b.get("with_source"):   # 원본도 휴지통으로 (그 원본의 다른 스토어 복사본도 함께 — 네이버에 올라가 있는 원본은 뺌)
            s = trash.trash_sources(db, sids, keep_naver=keep)
            out.update(sources_moved=s["moved"], sources_skipped_live=s["skipped_live"])
        return jsonify(out)

    def _source_ids_of(ids):
        out = set()
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            out |= {r["source_id"] for r in db.q(f"SELECT DISTINCT source_id FROM listings WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
        return sorted(out)

    # ── 눈검수 (복사본 썸네일 그리드)

    @app.get("/api/eye/page")
    def eye_page():
        """눈검수 한 쪽: 번호 순으로 from_id부터 size개 (before_id면 그 앞 size개). kind=listing(복사본)·source(원본).
        번호로 넘기므로 쪽에서 지운 것이 있어도 다음 쪽이 밀리거나 건너뛰지 않는다.
        눈검수에서 지운 것(eye_dead)은 그 자리에 '삭제됨'으로 계속 넣는다 ('안 한 것만'이면 이번에 지운 것만)."""
        a = request.args
        f = _filter_from(a)
        kind = "source" if a.get("kind") == "source" else "listing"
        size = max(1, min(int(a.get("size", 48)), 500))
        if kind == "source":
            f.pop("store_id", None)
            where, args = inventory.source_where(f)
            base, idc, store = "FROM sources", "id", 0
        else:
            where, args = inventory.listing_where(f)
            base, idc, store = "FROM listings l JOIN sources s ON s.id=l.source_id", "l.id", int(f.get("store_id") or 0)
        cond = lambda c: where + (" AND " if where else " WHERE ") + c   # noqa: E731
        since = float(a.get("dead_since") or 0) if f.get("eye") == "todo" else 0
        tomb = eye.dead_map(db, kind, store, since)
        # 지운 것 중 아직 남아 있는 것(내리기 대기 등)은 살아 있는 줄과 겹침 → 겹치지 않는 것만 따로 넣음
        live_dead = set()
        tids = list(tomb)
        for i in range(0, len(tids), 900):
            ch = tids[i:i + 900]
            live_dead |= {r["id"] for r in db.q(f"SELECT {idc} AS id {base}{cond(f'{idc} IN ({chr(44).join(chr(63) * len(ch))})')}", (*args, *ch))}
        only_dead = sorted(set(tids) - live_dead)

        def live(op, val, desc):
            return [r["id"] for r in db.q(f"SELECT {idc} AS id {base}{cond(f'{idc}{op}?') if val is not None else where} "
                                          f"ORDER BY {idc} {'DESC' if desc else ''} LIMIT ?", (*args, *(() if val is None else (val,)), size))]
        if a.get("before_id"):
            v = int(a["before_id"])
            ids = sorted(set(live("<", v, True)) | {x for x in only_dead if x < v}, reverse=True)[:size][::-1]
        else:
            v = int(a.get("from_id") or 0)
            ids = sorted(set(live(">=", v, False)) | {x for x in only_dead if x >= v})[:size]
            if not ids and a.get("from_id"):   # 끝을 넘었으면 마지막 쪽
                ids = sorted(set(live(None, None, True)) | set(only_dead), reverse=True)[:size][::-1]
        total = db.one(f"SELECT COUNT(*) AS n {base}{where}", args)["n"] + len(only_dead)
        before = (db.one(f"SELECT COUNT(*) AS n {base}{cond(f'{idc}<?')}", (*args, ids[0]))["n"] + sum(1 for x in only_dead if x < ids[0])) if ids else 0
        after = (db.one(f"SELECT COUNT(*) AS n {base}{cond(f'{idc}>?')}", (*args, ids[-1]))["n"] + sum(1 for x in only_dead if x > ids[-1])) if ids else 0
        live_ids = [i for i in ids if i not in only_dead]
        if kind == "source":
            got = {r["id"]: r for r in db.q(f"""SELECT id, id AS source_id, name, thumb, price, category, eye_at, n_listings, drop_pending, valid
                FROM sources WHERE id IN ({','.join('?' * len(live_ids)) or 'NULL'})""", live_ids)} if live_ids else {}
        else:
            got = {r["id"]: r for r in inventory.query_listings(db, {"ids": live_ids}, 0, size)["rows"]} if live_ids else {}
        rows, stale = [], []
        for i in ids:
            t = tomb.get(i)
            r = got.get(i)
            if r is None:   # 지워져 없어진 것 → '삭제됨' 칸
                r = {"id": i, "source_id": t["source_id"], "name": t["name"], "thumb": t["thumb"], "eye_at": None, "status": "", "op": ""}
                r["dead"] = {"label": "삭제됨", "cls": "gone", "at": t["at"]}
            elif t:
                going = r.get("drop_pending") if kind == "source" else (r.get("op") == "delete" and r.get("status") in ("planned", "queued", "running"))
                if going:
                    r["dead"] = {"label": "삭제됨", "sub": "네이버에서 내릴 예정", "cls": "gone", "at": t["at"]}
                else:
                    stale.append(i)   # 휴지통에서 되살린 것 등 → 다시 보통 칸으로
            rows.append(r)
        if stale:
            eye.drop_dead(db, kind, stale)
        page = -(-before // size) + 1   # 앞에 남은 것 기준 (이 앞 쪽에서 지운 것이 있어도 쪽 번호가 줄지 않게)
        lex = lexicon.get(db)
        for r in rows:   # 사진 밑 키워드 4개: 금지어·상표 단어 표시
            r["kw"] = _eye_words(r["name"], lex)
        live_rows = [r for r in rows if not r.get("dead")]
        return jsonify({"rows": rows, "total": total, "after": after, "page": page, "pages": page + -(-after // size) if ids else 1,
                        "has_prev": before > 0, "has_next": after > 0, "done": bool(live_rows) and all(r["eye_at"] for r in live_rows)})

    @app.post("/api/eye/dead")
    def eye_dead_add():
        """눈검수에서 지운 것을 기록 → 눈검수 쪽에 '삭제됨'으로 계속 남김."""
        b = body()
        eye.add_dead(db, "source" if b.get("kind") == "source" else "listing", int(b.get("store_id") or 0), b.get("rows") or [])
        return jsonify({"ok": True})

    def _eye_words(name, lex):
        """상품명 앞 키워드 4개와 표시: blocked(금지어) / mark(상표). 붙여 쓴 두 단어 상표도 둘 다 표시."""
        words = str(name or "").split()[:4]
        out = []
        for i, w in enumerate(words):
            why = ""
            if lexicon.blocked_in(w, lex):
                why = "blocked"
            elif lex and lex.marks and (lex.mark_of(w) or (i + 1 < len(words) and lex.mark_of(w + words[i + 1]))
                                        or (i > 0 and lex.mark_of(words[i - 1] + w))):
                why = "mark"
            out.append([w, why])
        return out

    @app.get("/api/eye/state")
    def eye_state():
        return jsonify(eye.state(db, int(request.args.get("store_id") or 0)))

    @app.post("/api/eye/memo")
    def eye_memo():
        b = body()
        return jsonify(eye.save_memo(db, int(b.get("store_id") or 0), b.get("memo")))

    @app.post("/api/eye/reset")
    def eye_reset():
        eye.reset_pos(db, int(body().get("store_id") or 0))
        return jsonify({"ok": True})

    @app.post("/api/eye/deleted")
    def eye_deleted():
        b = body()
        eye.log(db, int(b.get("store_id") or 0), "deleted", int(b.get("n") or 0))
        return jsonify(eye.stats(db, int(b.get("store_id") or 0)))

    @app.post("/api/eye/undo")
    def eye_undo():
        b = body()
        sid = int(b.get("store_id") or 0)
        out = eye.undo(db, sid, b.get("source_ids") or [], b.get("since") or time.time(), int(b.get("n") or 0))
        return jsonify({**out, **eye.stats(db, sid)})

    @app.post("/api/eye/commit")
    def eye_commit():
        """눈검수에서 미뤄 둔 네이버 내리기 시작 ('이 쪽 완료·다음'이나 닫을 때). 등록이 도는 중이면 대기로 남김."""
        ids = [int(i) for i in body().get("ids") or []]
        live = [r["id"] for i in range(0, len(ids), 900) for r in db.q(
            f"SELECT id FROM listings WHERE id IN ({','.join('?' * len(ids[i:i + 900]))}) AND op='delete' AND status='planned'", ids[i:i + 900])]
        if not live:
            return jsonify({"started": False, "count": 0})
        if runner.state["running"]:
            return jsonify({"started": False, "queued": True, "count": len(live)})
        try:
            runner.start({"ids": live, "kinds": ["delete"]})
        except (RuntimeError, naver.ApiError) as e:
            return jsonify({"started": False, "count": len(live), "error": str(e)})
        return jsonify({"started": True, "count": len(live)})

    @app.post("/api/eye/set")
    def eye_set():
        """검수 완료로 표시(done=true) / 풀기. 대상: 고른 원본·원본 거르기 조건, 또는 listing_filter(복사본)의 원본."""
        b = body()
        sids = _ctx_sources(b)
        if not sids:
            return fail("고른 상품이 없습니다.")
        val = time.time() if b.get("done", True) else None
        n = 0
        with db.tx() as c:
            for i in range(0, len(sids), 900):
                chunk = sids[i:i + 900]
                n += c.execute(f"UPDATE sources SET eye_at=? WHERE id IN ({','.join('?' * len(chunk))}) AND (eye_at IS NULL) = ?",
                               (val, *chunk, int(val is not None))).rowcount
        return jsonify({"count": n, "target": len(sids)})

    @app.post("/api/eye/mark")
    def eye_mark():
        """이 쪽 눈검수 완료 (복사본 번호들 → 그 원본에 표시). clear면 표시 지움. store_id·last_id가 오면 이어서 시작할 자리로."""
        b = body()
        ids = [int(i) for i in b.get("ids") or []]
        sids = ids if b.get("kind") == "source" else _source_ids_of(ids)
        val = None if b.get("clear") else time.time()
        with db.tx() as c:
            for i in range(0, len(sids), 900):
                chunk = sids[i:i + 900]
                c.execute(f"UPDATE sources SET eye_at=? WHERE id IN ({','.join('?' * len(chunk))})", (val, *chunk))
        if b.get("store_id") is not None and b.get("last_id") and not b.get("clear"):
            eye.page_done(db, int(b["store_id"]), int(b["last_id"]), len(b.get("ids") or []), b.get("size"), b.get("todo"))
            return jsonify({"count": len(sids), **eye.stats(db, int(b["store_id"]))})
        return jsonify({"count": len(sids)})

    @app.post("/api/listings/nvcheck")
    def listings_nvcheck():
        """그 스토어 판매 중 복사본의 네이버 상태(판매 중·품절·판매중지·판매금지·스토어에 없음)를 확인한다."""
        st = db.store(int(body().get("store_id") or 0), with_secret=True)
        if not st:
            return fail("스토어를 골라 주세요.")
        if not st.get("has_keys") and os.environ.get("UPLOADER_FAKE_API") != "1":
            return fail(f"'{st['name']}' 스토어의 API 키가 없습니다.")

        def job(progress=None, should_stop=None):
            res = nvstate.check_store(db, st["id"], naver.make_client(st), progress=progress, should_stop=should_stop)
            res["message"] = f"{st['name']} · " + nvstate.summary(res)
            return res
        try:
            return jsonify({"task": tasks.start("nvcheck", f"네이버 상태 확인 · {st['name']}", job)})
        except RuntimeError as e:
            return fail(str(e))

    @app.post("/api/listings/revert")
    def listings_revert():
        """복사본 → 원본으로 되돌리기 (아직 안 올린 것·내린 것만)."""
        f = _filter_from(body())
        f.pop("op", None)
        ids = inventory.listing_ids(db, f)
        if not ids:
            return fail("고른 복사본이 없습니다.")
        return jsonify(inventory.revert_listings(db, ids))

    @app.post("/api/listings/move")
    def listings_move():
        """복사본을 다른 스토어로 보내기 (아직 안 올린 것·내린 것만, 받는 스토어 남은 자리만큼)."""
        b = body()
        f = _filter_from(b)
        f.pop("op", None)
        ids = inventory.listing_ids(db, f)
        if not ids:
            return fail("고른 복사본이 없습니다.")
        try:
            return jsonify(inventory.move_listings(db, ids, b.get("to_store")))
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/listings/delete_preview")
    def listings_delete_preview():
        """삭제 창에 보여 줄 수: 고른 복사본의 원본 수, 그 원본의 다른 복사본 수, 다른 스토어에 올라가 있어 원본은 못 지우는 수."""
        f = _filter_from(body())
        f.pop("op", None)
        ids = inventory.listing_ids(db, f)
        sids = _source_ids_of(ids)
        other = live = 0
        idset = set(ids)
        for i in range(0, len(sids), 900):
            chunk = sids[i:i + 900]
            rows = db.q(f"""SELECT id, source_id, origin_no, status FROM listings WHERE source_id IN ({','.join('?' * len(chunk))})""", chunk)
            other += sum(1 for r in rows if r["id"] not in idset)
            live += len({r["source_id"] for r in rows if r["status"] != "deleted" and (r["origin_no"] or r["status"] in ("queued", "running"))})
        return jsonify({"copies": len(ids), "sources": len(sids), "other_copies": other, "live_sources": live})

    @app.post("/api/listings/reset_round")
    def listings_reset_round():
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 회차를 바꿀 수 없습니다. 끝난 뒤에 다시 시도하세요.")
        b = body()
        if b.get("all"):
            ids = [r["id"] for r in db.q("SELECT id FROM listings")]
        else:
            f = _filter_from(b)
            f.pop("op", None)
            ids = inventory.listing_ids(db, f)
        if not ids:
            return fail("고른 복사본이 없습니다.")
        return jsonify({"count": inventory.reset_rounds(db, ids)})

    @app.get("/api/trash")
    def trash_list():
        a = request.args
        page, size = int(a.get("page", 0)), min(int(a.get("size", 100)), 500)
        return jsonify(trash.listing(db, a.get("kind") or "source", (a.get("q") or "").strip(), page, size))

    @app.get("/api/trash/<int:tid>")
    def trash_detail(tid):
        d = trash.detail(db, tid)
        return jsonify(d) if d else fail("휴지통에 없습니다.", 404)

    def _trash_ids(b):
        if b.get("all"):
            return trash.ids(db, b.get("kind") or "source", (b.get("q") or "").strip())
        return [int(i) for i in b.get("ids") or []]

    @app.post("/api/trash/restore")
    def trash_restore():
        if runner.state["running"]:
            return fail("등록이 진행 중일 때는 되살릴 수 없습니다.")
        ids = _trash_ids(body())
        if not ids:
            return fail("고른 항목이 없습니다.")
        return jsonify(trash.restore(db, ids))

    @app.post("/api/trash/purge")
    def trash_purge():
        b = body()
        if b.get("empty"):
            return jsonify(trash.purge(db))
        ids = _trash_ids(b)
        if not ids:
            return fail("고른 항목이 없습니다.")
        return jsonify(trash.purge(db, ids))

    @app.get("/api/listings/stores")
    def listing_stores():
        return jsonify(inventory.store_summaries(db))

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
        nxt = {**l, "round": l["round"] + (1 if l["op"] in ("refresh", "reupload") and l["origin_no"] else 0)}
        l["next_seller_code"] = engine.seller_code(cfg, store, nxt)
        unit = max(1, convert.to_int(cfg.get("price_round"), 100))
        l["disc_pct"] = convert.store_discount_pct(store, cfg)
        l["shown"], l["off"], l["final"] = convert.display_prices(l["price"], l["disc_pct"], unit)
        l["history"] = db.q("SELECT * FROM listing_history WHERE listing_id=? ORDER BY round DESC", (lid,))
        l["orders"] = db.q("SELECT * FROM orders WHERE listing_id=? ORDER BY ordered_at DESC LIMIT 50", (lid,))
        l["siblings"] = db.q("""SELECT l.id, l.name, l.status, l.round, l.store_id, t.name AS store_name FROM listings l
            JOIN stores t ON t.id=l.store_id WHERE l.source_id=? AND l.id!=? AND l.status!='deleted'""",
                             (l["source_id"], lid))
        nm = db.one("SELECT origin FROM names WHERE id=?", (l["name_id"],)) if l["name_id"] else None
        l["name_origin"] = nm["origin"] if nm else ""
        k = db.one("SELECT words FROM ctx_kw WHERE source_id=?", (l["source_id"],))
        src = db.one("SELECT name FROM sources WHERE id=?", (l["source_id"],))["name"]
        l["nd"] = ctxkw.name_parts(l["name"], src, ctxkw.kw_of(k["words"]) if k and k["words"] else {}, l["name_origin"])
        # 옵션표 그림: 이미 올린 것은 네이버 주소, 아니면 이 PC에서 그려 보여 줄 주소 (올릴 때 그려서 올림)
        look = convert.option_look(cfg, store)
        opt_urls = []
        for box in convert.option_boxes(row, cfg, store):
            k = optimage.remember(box, *look)
            keys = [f"optimg:{k}:{i}" for i in range(optimage.count(len(box["cards"])))]
            up = db.image_map(engine.DETAIL_SCOPE, keys)
            opt_urls.append([up.get(kk) or f"/api/optimg/{k}/{i}.jpg" for i, kk in enumerate(keys)])
        try:
            l["body"] = convert.build_body(row, cfg, cats.get(cat) or f"(카테고리 번호 확인 필요) {cat}", url_map,
                                           name=l["name"], price=l["price"], seller_code=l["next_seller_code"],
                                           as_phone=l["as_phone"] or cfg.get("as_phone"),
                                           importer=convert.importer_for(store, cfg), store=store, opt_urls=opt_urls)
            # 네이버 모바일이 흐린 캡처로 보여 주게 만드는 것 (스토어 상단·하단 HTML 포함)
            l["mobile_issues"] = convert.mobile_issues(l["body"]["originProduct"]["detailContent"])
        except convert.ConvertError as e:
            l["body"] = {"검사 오류": str(e)}
        l["thumb"] = (convert.thumbnails(row) or [""])[0]
        l["source_name"] = row.get("상품명")
        l["source_price"] = convert.net_price(row)
        l["category"] = cat
        l["category_excel"] = row.get("엑셀카테고리") or cat
        l["category_fixed"] = bool(row.get("엑셀카테고리"))
        return jsonify(l)

    @app.post("/api/listings/schedule")
    def schedule():
        """올라가 있는 건에 최신화(지우고 다시 올리기) 또는 내리기를 예약한다."""
        b = body()
        op = b.get("op")
        if op not in ("refresh", "delete", "reupload"):
            return fail("알 수 없는 작업입니다.")
        if runner.state["running"]:
            return fail("등록이 끝난 뒤에 예약할 수 있습니다.")
        f = _filter_from(b)
        f.pop("op", None)  # 'op'는 여기서 거르기 조건이 아니라 걸 작업
        n, skipped, ids = inventory.schedule_op(db, f, op)
        out = {"scheduled": n, "skipped_sold": skipped, "started": False}
        if b.get("now") and ids:   # '바로 하기': 방금 건 것만 바로 처리 (다른 대기 건은 그대로)
            if runner.snapshot().get("running"):
                out["busy"] = True
            else:
                try:
                    runner.start({"ids": ids, "kinds": [op]})
                    out["started"] = True
                except (RuntimeError, naver.ApiError) as e:
                    out["error"] = str(e)
        return jsonify(out)

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

    @app.get("/api/stores/<int:sid>/sales")
    def store_sales(sid):
        try:
            return jsonify(orders.sales_status(db, sid))
        except ValueError as e:
            return fail(str(e), 404)

    @app.post("/api/stores/<int:sid>/sales_confirm")
    def store_sales_confirm(sid):
        """가져온 상품의 판매 이력을 직접 확인함 (주문 파일·직접 잠금) → 그 날부터 판매 이력을 아는 것으로."""
        try:
            return jsonify(orders.confirm_sales(db, sid, _date_ts(body().get("from"))))
        except ValueError as e:
            return fail(str(e))

    @app.post("/api/orders/import")
    def orders_import():
        return file_task("orders", "판매 이력 파일 가져오기", orders.import_sales_file)

    @app.post("/api/listings/rename")
    def listings_rename():
        """고른 복사본(아직 안 올린 것)의 상품명 바꾸기: AI 맥락 키워드(기본) / AI로 짓기 / 셔플."""
        b = body()
        f = _filter_from(b)
        f.pop("op", None)
        ids = inventory.listing_ids(db, f)
        if not ids:
            return fail("고른 복사본이 없습니다.")
        method = b.get("method") if b.get("method") in ("ctx", "ai", "shuffle") else "ctx"
        if method == "shuffle":
            fixed = max(0, int(b.get("fixed_n") if b.get("fixed_n") not in (None, "") else config.load().get("shuffle_fixed") or 3))
            extra = [w for w in str(b.get("extra") or "").replace(",", " ").split() if w]
            try:
                tid = tasks.start("rename", f"상품명 바꾸기(셔플, 앞 {fixed}단어 고정) · 복사본 {len(ids):,}건",
                                  lambda **kw: inventory.rename_shuffle(db, ids, fixed, extra, **kw))
            except RuntimeError as e:
                return fail(str(e))
            return jsonify({"task": tid})
        if method == "ctx":
            fb = False
            try:
                tid = tasks.start("rename", f"상품명 바꾸기(AI 키워드) · 복사본 {len(ids):,}건",
                                  lambda **kw: inventory.rename_ctx(db, ids, fb, redo=bool(b.get("redo", True)), **kw))
            except RuntimeError as e:
                return fail(str(e))
            return jsonify({"task": tid})
        if method == "ai" and not config.load().get("anthropic_api_key") and os.environ.get("UPLOADER_FAKE_API") != "1":
            return fail("설정 → AI 상품명에서 Anthropic API 키를 먼저 넣어 주세요.")
        label = {"ai": "AI로 짓기"}[method]
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
        kw, kw_error, kw_state = [], None, "off"
        if b.get("source_id"):
            sid = int(b["source_id"])
            if keywords.has_keys(cfg) and cfg.get("use_naver_keywords", True):
                kw_error, _ = keywords.ensure_collected(db, cfg, [sid])  # 아직 안 모았으면 지금 네이버에서
            src = db.one("SELECT id, name, category, core_kw, kw_at, data FROM sources WHERE id=?", (sid,))
            if src:
                name, category = src["name"], src["category"]
                _, kw = keywords.words_for(db, [src], cfg, lex)[src["id"]]
                kw_state = "ok" if src["kw_at"] else ("error" if kw_error else "nokey")
        elif name and keywords.has_keys(cfg) and cfg.get("use_naver_keywords", True):
            try:
                kw = keywords.words_for_name(db, cfg, name, lex)
                kw_state = "ok"
            except Exception as e:  # noqa: BLE001
                kw_error, kw_state = str(e)[:300], "error"
        if not keywords.has_keys(cfg):
            kw_state = "nokey"
        if not name:
            return fail("상품명을 넣어 주세요.")
        lex = lexicon.get(db)  # 키워드를 모으며 사전이 다시 읽혔을 수 있음
        out = namegen.recombine(name, int(b.get("count") or 5), set(), [name], cfg, seed=f"preview:{time.time()}",
                                lex=lex, category=category, kw_words=kw)
        orig = name.split()
        detail = namegen.new_word_detail(name, cfg, lex, category, kw)
        return jsonify({
            "original": name, "category": category, "original_len": len(name),
            "candidates": [w for w, _, _, _ in detail],
            "sources": [{"word": w, "from": o, "rank": pr} for w, _, pr, o in detail],
            "new_min": int(cfg.get("recombine_new_min") or 0), "new_max": int(cfg.get("recombine_new_max") or 0),
            "original_repeat": lexicon.repeated_word(orig, lex, int(cfg.get("max_word_repeat") or 2)),
            "kw_state": kw_state, "kw_error": kw_error, "kw_count": len(kw),
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

    # ── 스토어 템플릿: 상세 상단·하단(이미지 + HTML), 관부가세 코드, 스토어 가격 차이 %, 표시 할인율 %

    @app.get("/api/stores/<int:sid>/template")
    def store_template(sid):
        st = db.store(sid)
        if not st:
            return fail("스토어가 없습니다.", 404)
        return jsonify({**templates.summary(st), "name": st["name"]})

    @app.get("/api/stores/<int:sid>/addresses")
    def store_addresses(sid):
        """판매자센터 주소록 (템플릿에서 출고지·반품지 고르기)."""
        s = db.store(sid, with_secret=True)
        if not s:
            return fail("스토어가 없습니다.", 404)
        try:
            return jsonify(naver.make_client(s).address_books())
        except Exception as e:
            return fail(f"{s['name']}: {e}")

    @app.post("/api/stores/<int:sid>/template")
    def store_template_save(sid):
        b = body()

        def num_or_none(v):
            if v in (None, ""):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                raise ValueError(f"숫자를 넣어 주세요: {v}") from None
        try:
            price_pct, disc = num_or_none(b.get("price_pct")), num_or_none(b.get("discount_pct"))
            jlo, jhi = num_or_none(b.get("jitter_min")), num_or_none(b.get("jitter_max"))
        except ValueError as e:
            return fail(str(e))
        if (jlo is None) != (jhi is None):
            return fail("가격 흔들기는 최소·최대를 둘 다 넣거나 둘 다 비워 주세요.")
        if jlo is not None and (jlo > jhi or abs(jlo) > 30 or abs(jhi) > 30):
            return fail("가격 흔들기는 -30~+30% 사이, 최소 ≤ 최대로 넣어 주세요.")
        if disc is not None and not 0 <= disc < 90:
            return fail("표시 할인율은 0~89% 사이로 넣어 주세요.")
        try:
            ship, ret = (int(num_or_none(b.get(k)) or 0) or None for k in ("ship_addr", "return_addr"))
        except ValueError:
            return fail("출고지·반품지는 주소록 번호(숫자)로 넣어 주세요.")
        old = db.store(sid) or {}
        # 옵션표 모양·색 (보내지 않으면 그대로, 비우면 설정 공통값)
        opt_style = str((b.get("opt_style") if "opt_style" in b else old.get("tpl_opt_style")) or "")
        opt_style = "basic" if opt_style == "original" else opt_style   # 예전 '원본 그대로' → 원본 모양 2열 표
        opt_color = str((b.get("opt_color") if "opt_color" in b else old.get("tpl_opt_color")) or "").strip()
        if opt_style and opt_style not in convert.OPTION_STYLES:
            return fail("옵션표 모양을 목록에서 골라 주세요.")
        if opt_color and not (len(opt_color) == 7 and opt_color[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in opt_color[1:])):
            return fail("옵션표 색은 #1F2937처럼 # 뒤에 6자리로 넣어 주세요.")
        db.x("UPDATE stores SET tpl_opt_style=?, tpl_opt_color=? WHERE id=?", (opt_style, opt_color.upper(), sid))
        repriced = (old.get("tpl_price_pct"), old.get("tpl_jitter_min"), old.get("tpl_jitter_max")) != (price_pct, jlo, jhi)
        db.x("""UPDATE stores SET tpl_jitter_min=?, tpl_jitter_max=?, wm_text=? WHERE id=?""",
             (jlo, jhi, str((b.get("wm_text") if "wm_text" in b else old.get("wm_text")) or "").strip(), sid))
        db.x("""UPDATE stores SET tpl_top_html=?, tpl_bottom_html=?, tpl_customs=?, tpl_price_pct=?, tpl_discount_pct=?,
            tpl_ship_addr=?, tpl_return_addr=? WHERE id=?""",
             (str(b.get("top_html") or ""), str(b.get("bottom_html") or ""), config.customs_code(b.get("customs")),
              price_pct, disc, ship, ret, sid))
        activity.template_changed(db, old, old, db.store(sid) or {})
        n = inventory.reprice_pending(db, sid) if repriced else 0   # 스토어 가격 차이 %를 바꾸면 아직 안 올린 복사본 가격도 다시
        return jsonify({**templates.summary(db.store(sid)), "repriced": n})

    @app.post("/api/stores/<int:sid>/template/image")
    def store_template_image(sid):
        f = request.files.get("file")
        part = request.form.get("part") or "top"
        if not f:
            return fail("이미지를 골라 주세요.")
        try:
            templates.save_image(sid, part, f.filename, f.read())
        except ValueError as e:
            return fail(str(e))
        return jsonify(templates.summary(db.store(sid)))

    @app.delete("/api/stores/<int:sid>/template/image/<name>")
    def store_template_image_del(sid, name):
        templates.delete_image(sid, name)
        return jsonify(templates.summary(db.store(sid)))

    @app.get("/api/stores/<int:sid>/template/image/<name>")
    def store_template_image_get(sid, name):
        from flask import send_file
        p = templates.path_of(sid, name)
        if not p:
            return fail("이미지가 없습니다.", 404)
        return send_file(p)

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
        """상품명 속 단어별로 받아 둔 연관 키워드 → 새 단어 후보 (끈 단어·사전에 없는 말·속성 표시)."""
        a = request.args
        cfg = config.load()
        lex = lexicon.get(db)
        page, size = int(a.get("page", 0)), 30
        q = (a.get("q") or "").strip()
        where, args = "WHERE query LIKE 'rel:%'", []
        if q:
            where += " AND query LIKE ?"
            args.append(f"rel:%{q}%")
        total = db.one(f"SELECT COUNT(*) AS n FROM kw_query {where}", args)["n"]
        rows = db.q(f"SELECT query, data, fetched_at FROM kw_query {where} ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
                    args + [size, page * size])
        off = {}
        for r in db.q("SELECT core, word FROM kw_off"):
            off.setdefault(r["core"], set()).add(r["word"])
        tokens = []
        for r in rows:
            t = r["query"][4:]
            cand = keywords.token_words(t, keywords._unpack(r["data"]), cfg, lex)
            ws = list(cand)
            known = {x["word"]: x["in_dict"] for x in db.q(
                f"SELECT word, in_dict FROM word_dict WHERE word IN ({','.join('?' * len(ws))})", ws)} if ws else {}
            dict_words = {w for g in lex.syn.values() for w in g} | set(lex.syn) | lex.attrs
            dead = off.get("", set()) | off.get(t, set())
            words = []
            for w, (v, kind) in sorted(cand.items(), key=lambda x: -x[1][0])[:40]:
                in_dict = True if w in dict_words else (None if w not in known else bool(known[w]))
                words.append({"word": w, "n": 0, "malls": v, "kind": kind, "off": w in dead,
                              "all_off": w in off.get("", set()), "attr": bool(lexicon.attrs_in(w, lex)),
                              "bad": "" if lex.ok_new_word(w) else ("상표" if lex.mark_of(w) else "금지"),
                              "nodict": cfg.get("kw_dict_only", True) and in_dict is False})
            tokens.append({"core": t, "n": len(words), "words": words, "fetched_at": r["fetched_at"]})
        st = db.one("SELECT COUNT(*) AS total, SUM(kw_at IS NOT NULL) AS done FROM sources WHERE valid=1")
        return jsonify({
            "cores": tokens, "total": total, "page": page, "size": size,
            "stats": {"sources": st["total"] or 0, "done": st["done"] or 0,
                      "queries": db.one("SELECT COUNT(*) AS n FROM kw_query WHERE query LIKE 'rel:%'")["n"],
                      "words": db.one("SELECT COUNT(DISTINCT word) AS n FROM source_kw")["n"],
                      "volumes": db.one("SELECT COUNT(*) AS n FROM kw_volume")["n"]},
            "has_key": keywords.has_keys(cfg), "has_searchad": keywords.has_keys(cfg),
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
                          "known_from": orders.known_from(s), "has_keys": s["has_keys"]} for s in db.stores()]
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
                    "판매가", "기준 가격", "상태", "할 일", "올린 날", "원상품번호", "채널상품번호", "메시지"])
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
        where, args = inventory.listing_where({**f, "status": "noname"} if not f.get("visible") else f)
        noname = db.one(f"""SELECT COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id{where}
            {'AND' if where else 'WHERE'} l.name_id IS NULL AND l.status!='deleted' AND l.origin_no=''""", args)["n"]
        # 눈검수 안 한 원본이라 새 등록을 안 하는 복사본 (상품명은 바꾼 것)
        uw, ua = inventory.listing_where({**f, "status": "all"} if not f.get("visible") else f)
        unreviewed = db.one(f"""SELECT COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id{uw}
            {'AND' if uw else 'WHERE'} l.status IN ('planned','fail') AND l.name_id IS NOT NULL
            AND {engine.UNREVIEWED_NEW}""", ua)["n"]
        # 종류별 건수 (지금 범위 안에서, 종류 고르기와 무관하게)
        kinds = {}
        for t in engine.listing_targets(db, {**f, "kinds": None}):
            k = "fail" if t["status"] == "fail" else t["op"]
            kinds[k] = kinds.get(k, 0) + 1
        return jsonify({**engine.estimate(db, targets, config.load()), "noname": noname, "unreviewed": unreviewed, "count": len(targets), "kinds": kinds})

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

    auto = {"minutes": 0, "last_at": None, "next_at": None, "last_result": "", "task": None}

    def auto_sync_loop():
        while True:
            try:
                # 자동 가져오기를 화면에서 '중단'했으면 자동 가져오기를 끈다 (설정에서 다시 켬)
                t = next((x for x in tasks.list() if x["id"] == auto["task"]), None)
                if t and t["status"] == "stopped":
                    config.save({"orders_auto_sync_minutes": 0})
                    auto.update(task=None, last_result="중단해서 자동 가져오기를 껐습니다")
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
                            auto["task"] = tasks.start(
                                "orders", f"주문 자동 가져오기 · 스토어 {len(pairs)}곳 (중단하면 자동 가져오기 꺼짐)",
                                lambda **kw: orders.sync_stores(db, pairs, days=cfg.get("orders_initial_days"), **kw))
                            auto["last_at"] = now
            except RuntimeError:
                pass  # 이미 주문 가져오기가 돌고 있음 → 다음 차례에
            except Exception as e:  # noqa: BLE001
                auto["last_result"] = str(e)
            try:   # 구글 메일함 자동 가져오기 (설정 간격, 0이면 끔)
                cfg = config.load()
                mm = int(cfg.get("mail_auto_minutes") or 0)
                now = time.time()
                if mm <= 0 or not (cfg.get("gmail_user") and cfg.get("gmail_app_password")):
                    auto["mail_next"] = None
                else:
                    if not auto.get("mail_next"):
                        auto["mail_next"] = now + 60
                    if now >= auto["mail_next"]:
                        auto["mail_next"] = now + mm * 60
                        tasks.start("mail", "구글 메일함 자동 가져오기", lambda **kw: mail.fetch(db, cfg, **kw))
            except RuntimeError:
                pass
            except Exception as e:  # noqa: BLE001
                auto["last_result"] = str(e)
            time.sleep(30)

    def dict_folder_check():
        """켤 때 data/사전 폴더에 새 사전 파일이 있으면 뒤에서 읽는다."""
        time.sleep(3)
        try:  # 이번 업데이트에서 카테고리 찾기·동영상 경고가 바뀜 → 한 번 전체 다시 검사
            if not db.one("SELECT 1 FROM meta WHERE k='revalidate_v5'") and db.one("SELECT 1 FROM sources LIMIT 1"):
                tasks.start("revalidate", "검사 방식 변경(카테고리 확인·동영상·반복) · 전체 다시 검사", lambda **kw: inventory.revalidate(db, **kw))
            db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('revalidate_v5', '1')")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
        try:
            if lexicon.dict_folder_new(db):
                tasks.start("dictfile", "사전 폴더 읽기 (새 파일)", lambda **kw: lexicon.import_dict_folder(db, **kw))
        except Exception:  # noqa: BLE001
            pass

    if not db.one("SELECT 1 FROM meta WHERE k='ctx_v2_reset'"):
        ctxkw.reset_v1(db)   # AI 키워드 방식이 keep·core·ctx로 바뀜 → 예전 맥락 키워드 초기화 (한 번만)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('ctx_v2_reset', '1')")
    if not db.one("SELECT 1 FROM meta WHERE k='ab_pair_v1'"):
        # 이름 다시 바꾸기가 다른 스토어 몫 B까지 써 버린 원본 → A·B 짝을 되살림 (안 올린 이름만, AI 안 부름, 한 번만)
        ctxkw.rebuild_pairs(db)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('ab_pair_v1', '1')")
    if not db.one("SELECT 1 FROM meta WHERE k='ab_split_v2'"):
        # A·B가 달라 보이게 (보라는 자기 몫 먼저·자리 남으면 상대 몫도, 맥락은 반씩, B는 앞 3단어만 두고 앞쪽이 A와 다르게 섞기)
        # → 안 올린 AI 이름을 받은 키워드로 한 번 다시 조립 (AI 안 부름)
        ctxkw.rebuild_unused(db)
        for k in ("ab_split_v2", "ab_split_v1", "rep_compound_v2", "rep_compound_v1"):
            db.x("INSERT OR REPLACE INTO meta(k, v) VALUES(?, '1')", (k,))
    if not db.one("SELECT 1 FROM meta WHERE k='rep_compound_v2'"):
        # 반복 검사가 붙여 쓴 단어 속까지 세고(보물탐지·금속탐지·탐지장비), 한 글자가 더 붙은 말은 다른 단어로 봄(탐지기 ≠ 탐지)
        # → 안 올린 AI 이름을 받은 키워드로 한 번 다시 조립 (AI 안 부름, 올린 것은 그대로)
        ctxkw.rebuild_unused(db)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('rep_compound_v2', '1')")
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('rep_compound_v1', '1')")
    if not db.one("SELECT 1 FROM meta WHERE k='ctx_core_all_v1'"):
        ctxkw.rebuild_unused(db)   # 이름에 다른 이름(core)을 1개만 넣던 것을 전부로 → 안 올린 AI 이름 다시 조립 (AI 안 부름, 한 번만)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('ctx_core_all_v1', '1')")
    if not db.one("SELECT 1 FROM meta WHERE k='copies_dead_v1'"):
        db.recount_sources()   # 내림도 원본당 최대 수에 세도록 바뀜 → 복사 수 다시 세기 (한 번만)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('copies_dead_v1', '1')")
    if not db.one("SELECT 1 FROM meta WHERE k='price_store_v2'"):
        inventory.reprice_net(db)   # 가격 흔들기를 스토어 템플릿 범위로 옮김 → 아직 안 올린 복사본 가격 다시 (한 번만)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('price_store_v2', '1')")
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('price_net_v1', '1')")
    if not db.one("SELECT 1 FROM meta WHERE k='price_net_v1'"):
        inventory.reprice_net(db)   # 이번 버전부터 기준 가격 = 판매가 - 할인가 (예전 원본·대기 복사본 가격을 한 번 다시 계산)
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('price_net_v1', '1')")

    if not app.config.get("TESTING"):
        threading.Thread(target=auto_sync_loop, daemon=True).start()
        threading.Thread(target=dict_folder_check, daemon=True).start()
        ctxkw.poll_loop(db)   # 진행 중인 일괄 처리를 켜자마자, 그 뒤 1분마다 확인 (껐다 켜도 이어서)

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
