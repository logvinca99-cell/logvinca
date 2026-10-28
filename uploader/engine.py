"""등록 실행. 여러 스토어를 동시에, 스토어마다 몇 개씩 함께 등록한다.

네이버 호출 한도는 애플리케이션(스토어)마다 따로 매겨지므로, 스토어를 나란히 돌리면 그만큼 빨라진다.
같은 이미지는 디스크 캐시로 한 번만 내려받고, 스토어마다 네이버 서버에 올린다(대표·추가 이미지).
상세 이미지는 모든 스토어가 같은 네이버 주소를 함께 쓴다.
"""

import collections
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import activity, bait, config, convert, naver, optimage, orders, templates, watermark

IMAGE_DOWNLOAD_THREADS = 16
DETAIL_SCOPE = 0
GUESS_BASE_SEC = 2.0
GUESS_PER_IMAGE_SEC = 0.35


KIND_COND = {   # 시작할 때 고르는 종류
    "create": "(l.status='planned' AND l.op='create')",
    "refresh": "(l.status='planned' AND l.op='refresh')",
    "delete": "(l.status='planned' AND l.op='delete')",
    "reupload": "(l.status='planned' AND l.op='reupload')",
    "fail": "(l.status='fail')",
}


def listing_targets(db, f):
    """처리할 건: 조건에 맞는 대기·실패 건 (새 등록 / 최신화 / 내리기).
    f['kinds']: 고른 종류만 (create·refresh·delete·fail, 없으면 전부). f['ids']: 고른 복사본만.
    f['status'] 등 화면 거르기 조건을 주면 그 조건에 맞는 것만 ('보이는 것만 시작')."""
    from .inventory import listing_where
    where, args = listing_where(f if f.get("visible") else {**f, "status": "all"})
    kinds = [k for k in (f.get("kinds") or KIND_COND) if k in KIND_COND]
    # 상품명을 아직 안 바꾼(원본 상품명 그대로인) 새 등록은 올리지 않는다 → 복사본 화면 '상품명 변경 필요'
    cond = f"({' OR '.join(KIND_COND[k] for k in kinds) or '0'}) AND NOT (l.op IN ('create','reupload') AND l.name_id IS NULL)"
    where = (where + f" AND {cond}") if where else f" WHERE {cond}"
    return db.q(f"""SELECT l.id, l.store_id, l.source_id, l.name, l.price, l.status, l.message, l.op, l.round,
        l.origin_no, l.channel_no, l.seller_code, l.registered_at, l.bait_want, l.name_id, l.round_reset, CASE WHEN l.op='delete' THEN 0 ELSE s.image_count END AS image_count
        FROM listings l JOIN sources s ON s.id=l.source_id{where} ORDER BY l.id""", args)


def estimate(db, targets, cfg):
    workers = max(1, int(cfg.get("workers_per_store") or 1))
    parallel = max(1, int(cfg.get("max_parallel_stores") or 1))
    recent = db.recent_seconds()
    per_store = collections.Counter(t["store_id"] for t in targets)
    if len(recent) >= 5:
        per = sum(recent) / len(recent) + float(cfg.get("delay_sec") or 0)
        basis = f"최근 등록 {len(recent)}건 평균 {per:.1f}초"
        store_sec = {sid: n * per / workers for sid, n in per_store.items()}
    else:
        imgs = collections.Counter()
        for t in targets:
            imgs[t["store_id"]] += t["image_count"]
        store_sec = {sid: (GUESS_BASE_SEC * n + GUESS_PER_IMAGE_SEC * imgs[sid]
                           + float(cfg.get("delay_sec") or 0) * n) / workers for sid, n in per_store.items()}
        basis = "어림값 (실제 등록 기록이 쌓이면 정확해집니다)"
    # 스토어를 parallel개씩 나란히 돌릴 때 걸리는 시간 (긴 스토어부터 빈 자리에 배정)
    lanes = [0.0] * min(parallel, max(1, len(store_sec)))
    for sec in sorted(store_sec.values(), reverse=True):
        i = lanes.index(min(lanes))
        lanes[i] += sec
    return {"seconds": max(lanes) if store_sec else 0, "basis": basis, "count": len(targets),
            "stores": len(per_store), "workers": workers, "parallel": min(parallel, len(per_store) or 1)}


def seller_code(cfg, store, t):
    """스토어에 등록하는 판매자 관리코드. 기본 '스토어코드-원본번호-회차' (예: S07-0012345-2)."""
    fmt = cfg.get("seller_code_format") or "{store}-{source:07d}-{round}"
    try:
        return fmt.format(store=store.get("code") or f"S{store['id']:02d}", source=t["source_id"], round=t["round"])
    except (KeyError, ValueError, IndexError):
        return f"{store.get('code')}-{t['source_id']:07d}-{t['round']}"


class Stopped(Exception):
    pass


class Runner:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.pause_ev = threading.Event()
        self.stop_ev = threading.Event()
        self.log = collections.deque(maxlen=400)
        self._reset(0)

    def _reset(self, total):
        self.state = {
            "running": False, "paused": False, "stopping": False, "total": total, "done": 0, "ok": 0,
            "fail": 0, "skipped": 0, "images": 0, "images_reused": 0, "started_at": None, "ended_at": None,
            "paused_sec": 0.0, "paused_at": None, "current": {}, "stores": {}, "error": "",
        }

    # ── 조작

    def start(self, f):
        with self.lock:
            if self.state["running"]:
                raise RuntimeError("이미 등록 중입니다.")
            self._name_ctx = {}   # 최신화 새 이름용 스토어 정보 (실행마다 새로 읽음)
            self._tpl_cache = {}  # 스토어 템플릿 상단·하단 HTML (실행마다 새로 만듦)
            cfg = config.load()
            targets = listing_targets(self.db, f)
            if f.get("limit"):
                targets = targets[:int(f["limit"])]
            if not targets:
                from .inventory import listing_where
                where, args = listing_where({**f, "status": "noname"})
                n = self.db.one(f"SELECT COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id{where}", args)["n"]
                if n:
                    raise RuntimeError(f"처리할 건이 없습니다. 상품명을 아직 안 바꾼 복사본 {n:,}건은 올리지 않습니다 "
                                       "— 복사본 화면 '상품명 변경 필요'에서 상품명을 바꾸세요.")
                raise RuntimeError("처리할 건이 없습니다. (고른 범위·종류 안의 대기·실패 건만 처리합니다)")
            by_store = collections.defaultdict(list)
            for t in targets:
                by_store[t["store_id"]].append(t)
            stores = {}
            for sid in by_store:
                s = self.db.store(sid, with_secret=True)
                phone = (s.get("as_phone") or cfg.get("as_phone") or "").strip()
                if not phone:
                    raise RuntimeError(f"'{s['name']}' 스토어의 A/S 전화번호가 없습니다. 스토어나 설정에서 넣어 주세요.")
                stores[sid] = (s, naver.make_client(s))
            ids = [t["id"] for t in targets]
            with self.db.tx() as c:
                for i in range(0, len(ids), 900):
                    chunk = ids[i:i + 900]
                    c.execute(f"UPDATE listings SET status='queued', stage='', message='' "
                              f"WHERE id IN ({','.join('?' * len(chunk))})", chunk)
            self._reset(len(targets))
            self.state.update(running=True, started_at=time.time())
            self.state["stores"] = {sid: {"name": stores[sid][0]["name"], "total": len(v), "done": 0, "ok": 0,
                                          "fail": 0, "skipped": 0, "status": "대기"} for sid, v in by_store.items()}
            self.pause_ev.clear()
            self.stop_ev.clear()
            self.log.clear()
            threading.Thread(target=self._main, args=(cfg, stores, by_store), daemon=True).start()

    def pause(self):
        with self.lock:
            if self.state["running"] and not self.state["paused"]:
                self.pause_ev.set()
                self.state.update(paused=True, paused_at=time.time())
                self._log("info", "일시정지. 지금 처리 중인 건까지만 마칩니다.")

    def resume(self):
        with self.lock:
            if self.state["paused"]:
                self.state["paused_sec"] += time.time() - self.state["paused_at"]
                self.state.update(paused=False, paused_at=None)
                self.pause_ev.clear()
                self._log("info", "계속합니다.")

    def stop(self):
        with self.lock:
            if self.state["running"]:
                self.stop_ev.set()
                self.state["stopping"] = True
                self._log("info", "중단합니다. 지금 처리 중인 건까지만 마칩니다.")
        self.resume()

    # ── 진행 상황

    def _log(self, level, msg, store=""):
        self.log.append({"t": time.time(), "level": level, "msg": msg, "store": store})

    def snapshot(self):
        with self.lock:
            s = dict(self.state)
            s["current"] = [{"lid": k, **v} for k, v in self.state["current"].items()]
            s["stores"] = [{"id": k, **v} for k, v in self.state["stores"].items()]
            now = s["ended_at"] or time.time()
            paused = s["paused_sec"] + ((now - s["paused_at"]) if s["paused_at"] else 0)
            elapsed = (now - s["started_at"] - paused) if s["started_at"] else 0
            s["elapsed"] = elapsed
            s["rate_per_min"] = (s["done"] / elapsed * 60) if elapsed > 0 and s["done"] else None
            s["eta"] = ((s["total"] - s["done"]) / s["done"] * elapsed) if s["done"] and s["running"] else None
            s["log"] = list(self.log)[-150:]
            return s

    # ── 실행

    def _main(self, cfg, stores, by_store):
        run_id = self.db.start_run(self.state["total"], len(stores),
                                   note=f"스토어 {len(stores)}곳 · 스토어당 {cfg.get('workers_per_store')}개")
        names = [stores[k][0].get("name") or "" for k in list(stores)[:3]]
        act = activity.add(self.db, "복사·등록", "upload", f"네이버 등록 · 스토어 {len(stores)}곳", count=self.state["total"],
                           status="running", store=", ".join(n for n in names if n) + (" 외" if len(stores) > 3 else ""))
        try:
            self._log("info", f"{self.state['total']:,}건 등록 시작 · 스토어 {len(stores)}곳")
            categories = naver.cached_categories()
            if not categories:
                first = next(iter(stores.values()))[1]
                categories = first.categories()
            cache = naver.image_cache(cfg)
            parallel = max(1, min(int(cfg.get("max_parallel_stores") or 1), 64))
            store_q = queue.Queue()
            # 할 일이 많은 스토어부터
            for sid in sorted(by_store, key=lambda k: -len(by_store[k])):
                store_q.put(sid)
            with ThreadPoolExecutor(IMAGE_DOWNLOAD_THREADS) as pool:
                lanes = [threading.Thread(target=self._lane, daemon=True,
                                          args=(cfg, stores, by_store, store_q, categories, pool, cache))
                         for _ in range(min(parallel, len(by_store)))]
                for t in lanes:
                    t.start()
                for t in lanes:
                    t.join()
        except Exception as e:  # noqa: BLE001
            self.state["error"] = str(e)
            self._log("err", f"등록을 시작하지 못했습니다: {e}")
        finally:
            # 중단·오류로 남은 건은 원래 상태로
            self.db.x("UPDATE listings SET status='planned' WHERE status='queued'")
            touched = {t["source_id"] for v in by_store.values() for t in v}
            self.db.recount_sources(touched)
            try:
                orders.rematch(self.db)  # 새로 올린 복사본에 이미 받아 둔 주문이 맞는지
            except Exception:  # noqa: BLE001
                pass
            with self.lock:
                s = self.state
                if s["paused_at"]:
                    s["paused_sec"] += time.time() - s["paused_at"]
                s.update(running=False, paused=False, paused_at=None, stopping=False,
                         ended_at=time.time(), current={})
                self.db.end_run(run_id, s["ok"], s["fail"], s["images"])
                try:
                    self.db.x("UPDATE activity SET ended_at=?, status=?, result=?, error=? WHERE id=?",
                              (s["ended_at"], "error" if s.get("error") else "done",
                               f"성공 {s['ok']:,}건 · 실패 {s['fail']:,}건" + (f" · 판매 이력으로 건너뜀 {s['skipped']:,}건" if s["skipped"] else "")
                               + f" · 새 이미지 {s['images']:,}장", str(s.get("error") or "")[:500], act))
                except Exception:  # noqa: BLE001
                    pass
                self._log("ok" if not s["fail"] else "info",
                          f"끝: 성공 {s['ok']:,}건, 실패 {s['fail']:,}건"
                          + (f", 판매 이력으로 건너뜀 {s['skipped']:,}건" if s["skipped"] else "")
                          + f", 새로 올린 이미지 {s['images']:,}장")

    def _lane(self, cfg, stores, by_store, store_q, categories, pool, cache):
        """스토어 하나씩 맡아 끝까지 등록하고 다음 스토어로."""
        while not self.stop_ev.is_set():
            try:
                sid = store_q.get_nowait()
            except queue.Empty:
                return
            store, client = stores[sid]
            q = queue.Queue()
            for t in by_store[sid]:
                q.put(t)
            # 지우는 일(최신화·내리기)이 있으면 먼저 이 스토어의 주문을 가져와 판매 이력을 최신으로 만든다.
            sales_ok = True
            if any(t["op"] in ("refresh", "delete", "reupload") and t["origin_no"] for t in by_store[sid]):
                with self.lock:
                    self.state["stores"][sid]["status"] = "판매 이력 확인 중"
                try:
                    # 처음이면 최근 며칠만 (요청 수·시간당 한도를 아끼려고, 설정 orders_refresh_days 기본 7일)
                    r = orders.sync_store(self.db, self.db.store(sid), client, days=int(cfg.get("orders_refresh_days") or 7))
                    if r["new"]:
                        self._log("info", f"새 주문 {r['new']}건을 가져왔습니다", store["name"])
                except Exception as e:  # noqa: BLE001
                    sales_ok = False
                    self._log("err", f"주문을 가져오지 못해 이 스토어의 최신화·내리기는 하지 않습니다: {e}", store["name"])
            store = {**store, "_sales_ok": sales_ok}
            with self.lock:
                self.state["stores"][sid]["status"] = "처리 중"
            workers = max(1, min(int(cfg.get("workers_per_store") or 1), 8))
            ths = [threading.Thread(target=self._worker, daemon=True,
                                    args=(cfg, store, client, categories, q, pool, cache)) for _ in range(workers)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            with self.lock:
                ss = self.state["stores"][sid]
                ss["status"] = "중단" if self.stop_ev.is_set() and ss["done"] < ss["total"] else "끝"

    def _wait_if_paused(self):
        while self.pause_ev.is_set() and not self.stop_ev.is_set():
            time.sleep(0.3)
        if self.stop_ev.is_set():
            raise Stopped

    def _worker(self, cfg, store, client, categories, q, pool, cache):
        delay = float(cfg.get("delay_sec") or 0)
        while True:
            try:
                self._wait_if_paused()
                t = q.get_nowait()
            except (Stopped, queue.Empty):
                return
            self._one(cfg, store, client, categories, pool, cache, t)
            if delay:
                time.sleep(delay)

    def _stage(self, lid, label, stage):
        with self.lock:
            self.state["current"][lid] = {"name": label, "stage": stage}

    def _one(self, cfg, store, client, categories, pool, cache, t):
        """한 건 처리. op: create(새로 등록) / refresh(지우고 다시 등록) / delete(내리기)."""
        lid, sid, op = t["id"], store["id"], t["op"]
        label = f"[{store['name']}] {t['name']}"
        t0 = time.time()
        self.db.set_listing(lid, "running", stage="준비")
        self._stage(lid, label, "준비")
        on_wait = lambda m: self._stage(lid, label, m)  # noqa: E731
        notes = []
        try:
            if op in ("create", "reupload") and not t.get("name_id"):
                raise naver.ApiError("이름 변경 필요 · 원본 상품명 그대로는 올리지 않습니다 (복사본 화면에서 상품명 바꾸기)")
            if op in ("create", "reupload"):
                from . import lexicon
                rw = lexicon.repeated_word(str(t["name"] or "").split(), lexicon.get(self.db), int(cfg.get("max_word_repeat") or 2))
                if rw:
                    raise naver.ApiError(f"상품명에 '{rw}'가 3번 이상 나옵니다 · 복사본 화면에서 상품명 바꾸기로 다시 만드세요")
            if op in ("refresh", "delete", "reupload") and t["origin_no"]:
                # 판매된 상품은 지우지 않는다 (예약 뒤에 팔렸을 수 있으니 실행 직전에 다시 확인).
                if not store.get("_sales_ok", True):
                    raise naver.ApiError("주문(판매 이력)을 확인하지 못해 지우지 않았습니다. 다시 시도하세요.")
                lk = self.db.one("SELECT locked, lock_note FROM listings WHERE id=?", (lid,))
                if lk["locked"]:
                    self.db.set_listing(lid, "success", op="create", stage="",
                                        message=f"잠금이라 지우지 않음 ({lk['lock_note']})")
                    self._log("info", f"건너뜀 · {t['name'][:40]} · 잠금 ({lk['lock_note']})", store["name"])
                    self._count(sid, lid, None)
                    return
                self._stage(lid, label, "네이버에서 지우는 중")
                removed = client.delete_product(t["origin_no"], on_wait=on_wait)
                # 이미 스토어에서 지운 상품이면 지난 연결 확인 수에 이미 빠져 있을 수 있어, 남은 자리 계산에 '지움'으로 세지 않는다
                self._archive(t, op, counted=removed is not False)
                if op == "delete":
                    self.db.set_listing(lid, "deleted", op="create", stage="", message="", origin_no="",
                                        channel_no="", deleted_at=time.time(), seconds=time.time() - t0)
                    self._log("ok", f"내림 · {t['name'][:40]}", store["name"])
                    self._count(sid, lid, True)
                    return
                # 지웠으니 이제부터는 다음 회차 '새 등록'. 여기서 실패해도 다시 시도하면 등록만 한다.
                # 회차 초기화한 건은 +1 하지 않고 1회차로
                t = {**t, "round": 1 if t.get("round_reset") else t["round"] + 1, "origin_no": ""}
                self.db.set_listing(lid, None, op="create", round=t["round"], origin_no="", channel_no="",
                                    deleted_at=time.time(), round_reset=0)
                if op == "refresh" and cfg.get("refresh_new_name"):   # 다시 올리기는 늘 같은 이름
                    t["name"] = self._new_name(cfg, t) or t["name"]
            elif op == "delete":
                self.db.set_listing(lid, "deleted", op="create", stage="", deleted_at=time.time())
                self._count(sid, lid, True)
                return

            row = self.db.source_row(t["source_id"])
            cat_id, _ = convert.find_category(row.get("카테고리"), categories, cfg)
            if not cat_id:
                raise convert.ConvertError(f"카테고리 '{row.get('카테고리')}'를 스마트스토어에서 찾지 못했습니다.")
            code = seller_code(cfg, store, t)
            # 가격은 올리는 이 순간의 기준으로 다시 정한다 (원본가·스토어 가격 조정·흔들기). 등록·최신화·다시 올리기 모두 같게.
            key = (self.db.one("SELECT source_key FROM sources WHERE id=?", (t["source_id"],)) or {}).get("source_key", "")
            price = convert.store_price(convert.net_price(row), f"{key}|{sid}", cfg, store)
            if price != t["price"]:
                self.db.set_listing(lid, None, price=price)
                t = {**t, "price": price}
            # 도둑방지: 새로 올라가는 모든 경우 가격을 높여 둠 (나중에 원래 가격으로)
            bait_amt = bait.applies(cfg, t, op)
            kw = dict(name=t["name"], price=t["price"], bait=bait_amt, importer=convert.importer_for(store, cfg),
                      as_phone=store.get("as_phone") or cfg.get("as_phone"), seller_code=code, store=store)
            convert.build_body(row, cfg, cat_id, **kw)  # 이미지 올리기 전에 빠진 값부터 확인
            # 스토어 템플릿 상단·하단 (이미지는 이 스토어 이름으로 한 번만 올리고 이번 실행 동안 같이 씀)
            tpl = self.__dict__.setdefault("_tpl_cache", {})
            if store["id"] not in tpl:
                self._stage(lid, label, "스토어 상단·하단 이미지 올리는 중")
                tpl[store["id"]] = templates.html(self.db, client, store, on_wait)
            kw["store"] = {**store, "_tpl_top": tpl[store["id"]][0], "_tpl_bottom": tpl[store["id"]][1]}

            thumbs = convert.thumbnails(row)[:10]
            wm = None
            if watermark.enabled(cfg) and thumbs:
                marked = set(thumbs if cfg.get("wm_scope") == "all" else thumbs[:1])
                wm = (marked, lambda data: watermark.apply(data, store, cfg), watermark.signature(cfg, store))
            url_map, n1, _ = self._images(client, pool, cache, sid, thumbs, True, lid, label, on_wait, wm=wm)
            details = convert.detail_images_to_upload(row, cfg)
            dmap, n2, failed = self._images(client, pool, cache, DETAIL_SCOPE, details, False, lid, label, on_wait)
            url_map.update(dmap)
            if failed:
                notes.append(f"상세 이미지 {len(failed)}장은 내려받지 못해 원래 주소로 둠")
            # 옵션 사진 묶음 → 2열 그림 (표·CSS 없이: 모바일에서도 선명하고 늘 2열)
            boxes = convert.option_boxes(row, cfg, store)
            if boxes:
                kw["opt_urls"] = self._option_images(client, cache, boxes, convert.option_look(cfg, store), lid, label, on_wait)

            self._stage(lid, label, "상품 등록 중")
            body = convert.build_body(row, cfg, cat_id, url_map, **kw)
            iss = convert.mobile_issues(body["originProduct"]["detailContent"])
            if iss:   # 스토어 상단·하단 HTML 등에 남은 것
                notes.append("모바일에서 흐린 캡처로 보일 수 있음: " + ", ".join(iss))
            res = client.create_product(body, on_wait=on_wait)
            if ((body["originProduct"].get("detailAttribute") or {}).get("unitCapacity") or {}).get("unitPriceYn") is False:
                notes.append("가격표시제 대상 카테고리 → 단위가격 '사용 안 함'으로 등록")
            shown = int(body["originProduct"]["salePrice"]) - convert.round_up(bait_amt or 0, max(1, convert.to_int(cfg.get("price_round"), 100)))
            sec = time.time() - t0
            self.db.set_listing(lid, "success", op="create", stage="", message=" / ".join(notes), seconds=sec,
                                seller_code=code, registered_at=time.time(),
                                bait=bait_amt, bait_state="on" if bait_amt else "", bait_note="", bait_restored_at=None, sale_shown=shown,
                                origin_no=str(res.get("originProductNo", "")),
                                channel_no=str(res.get("smartstoreChannelProductNo", "")))
            what = {"refresh": "최신화", "reupload": "다시 올리기"}.get(op, "등록")
            extra = f", 도둑방지 +{bait_amt:,}원" if bait_amt else ""
            self._log("ok", f"{what} 완료 · {t['name'][:40]} ({sec:.1f}초, 새 이미지 {n1 + n2}장{extra})", store["name"])
            self._count(sid, lid, True)
        except Exception as e:  # noqa: BLE001 - 한 건의 실패는 기록하고 다음으로
            self.db.set_listing(lid, "fail", stage="", message=str(e)[:1000], seconds=time.time() - t0)
            self._log("err", f"실패 · {t['name'][:40]} · {e}", store["name"])
            self._count(sid, lid, False)

    def _count(self, sid, lid, ok):
        """ok: True 성공 / False 실패 / None 건너뜀"""
        key = "skipped" if ok is None else "ok" if ok else "fail"
        with self.lock:
            s, ss = self.state, self.state["stores"][sid]
            s["done"] += 1
            ss["done"] += 1
            s[key] += 1
            ss[key] += 1
            s["current"].pop(lid, None)

    def _archive(self, t, reason, counted=True):
        """지운 회차를 기록에 남긴다. counted=False면 남은 자리 계산(연결 확인 뒤 지운 수)에 넣지 않는다."""
        self.db.x("""INSERT INTO listing_history(listing_id, round, name, price, seller_code, origin_no, channel_no,
            registered_at, deleted_at, reason) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (t["id"], t["round"], t["name"], t["price"], t["seller_code"] or "", t["origin_no"],
                   t["channel_no"] or "", t["registered_at"], time.time() if counted else 0, reason))

    def _new_name(self, cfg, t):
        """최신화 때 새 이름을 쓰는 설정이면: 안 쓴 AI 맥락 후보, 없으면 셔플로 새 이름 (AI를 부르지 않음)."""
        from . import inventory, lexicon
        cfg = {**cfg, "_lex": lexicon.get(self.db)}
        src = self.db.one("SELECT id, name FROM sources WHERE id=?", (t["source_id"],))
        now = time.time()
        with self.db.tx() as c:
            nm = inventory.refresh_name(c, src, t["store_id"], cfg, now)
            if not nm:
                return None
            c.execute("UPDATE names SET listing_id=? WHERE id=?", (t["id"], nm["id"]))
            c.execute("UPDATE listings SET name_id=?, name=? WHERE id=?", (nm["id"], nm["name"], t["id"]))
        return nm["name"]

    def _option_images(self, client, cache, boxes, look, lid, label, on_wait):
        """옵션 사진 묶음마다 2열 그림을 그려 네이버에 올린 주소들. 같은 그림은 한 번만 올리고 모든 스토어가 같이 쓴다.
        못 만들면(옵션 사진을 못 받음, 글꼴 없음) 등록하지 않는다 — 한 줄에 하나씩 쌓이거나 흐린 상세로 올라가지 않게."""
        style, color = look
        dl = naver.downloader()
        out = []
        for box in boxes:
            k = optimage.key(box, style, color)
            keys = [f"optimg:{k}:{i}" for i in range(optimage.count(len(box["cards"])))]
            saved = self.db.image_map(DETAIL_SCOPE, keys)
            if len(saved) < len(keys):
                self._stage(lid, label, "옵션표 그림 만드는 중")
                try:
                    imgs = optimage.build(box, style, color, lambda u: dl(u, cache)[0])
                except Exception as e:  # noqa: BLE001 - 사진 받기·그리기 실패는 이 건만 실패로
                    raise convert.ConvertError(f"옵션표 그림을 만들지 못했습니다 ({e}). 다시 시도해 주세요.") from None
                need = [(kk, data) for kk, data in zip(keys, imgs) if kk not in saved]
                for j in range(0, len(need), naver.IMAGES_PER_CALL):
                    chunk = need[j:j + naver.IMAGES_PER_CALL]
                    urls = client.upload_images([(kk, data, "image/jpeg") for kk, data in chunk], on_wait=on_wait)
                    pairs = [(kk, u) for (kk, _), u in zip(chunk, urls)]
                    self.db.save_images(DETAIL_SCOPE, pairs)
                    saved.update(pairs)
                    with self.lock:
                        self.state["images"] += len(chunk)
            out.append([saved[kk] for kk in keys])
        return out

    def _images(self, client, pool, cache, scope, srcs, required, lid, label, on_wait, wm=None):
        """(원본→네이버 주소, 새로 올린 수, 못 받은 주소). required면 하나라도 못 받으면 실패.
        wm=(워터마크 넣을 원본 주소들, 변환 함수, 서명): 그 이미지는 워터마크를 넣어 따로 올리고 따로 기억한다."""
        if not srcs:
            return {}, 0, []
        marked, fn, sig = wm or (set(), None, "")
        key = {u: (f"{u}#wm{sig}" if u in marked else u) for u in srcs}
        saved = self.db.image_map(scope, list(key.values()))
        url_map = {u: saved[k] for u, k in key.items() if k in saved}
        need = [u for u in srcs if u not in url_map]
        with self.lock:
            self.state["images_reused"] += len(srcs) - len(need)
        if not need:
            return url_map, 0, []
        kind = "대표·추가" if required else "상세"
        self._stage(lid, label, f"{kind} 이미지 받는 중 0/{len(need)}")
        dl = naver.downloader()
        futures = [(u, pool.submit(dl, u, cache)) for u in need]
        got, failed = [], []
        for i, (u, fut) in enumerate(futures, 1):
            try:
                data, ctype = fut.result()
                if u in marked and fn:
                    try:
                        data, ctype = fn(data), "image/jpeg"
                    except Exception as e:  # noqa: BLE001 - 그림이 아니면(시연 모드 등) 워터마크 없이
                        self._log("warn", f"워터마크 못 넣음 · {e}")
                got.append((u, data, ctype))
            except Exception as e:  # noqa: BLE001
                if required:
                    raise naver.ApiError(f"대표/추가 이미지를 내려받지 못했습니다: {e}")
                failed.append(u)
            if i % 5 == 0 or i == len(need):
                self._stage(lid, label, f"{kind} 이미지 받는 중 {i}/{len(need)}")
        sent = 0
        for i in range(0, len(got), naver.IMAGES_PER_CALL):
            chunk = got[i:i + naver.IMAGES_PER_CALL]
            self._stage(lid, label, f"{kind} 이미지 올리는 중 {sent}/{len(got)}")
            new_urls = client.upload_images(chunk, on_wait=on_wait)
            pairs = list(zip([u for u, _, _ in chunk], new_urls))
            self.db.save_images(scope, [(key[u], n) for u, n in pairs])
            url_map.update(pairs)
            sent += len(chunk)
            with self.lock:
                self.state["images"] += len(chunk)
        return url_map, sent, failed
