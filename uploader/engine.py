"""엑셀 불러오기, 검사, 등록 실행.

등록은 Runner 하나가 맡는다. 상품 여러 개를 동시에(workers) 처리하고,
일시정지/중단을 받으며, 화면이 1초마다 읽어 가는 진행 상황(snapshot)을 만든다.
"""

import collections
import json
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, convert, excel, naver

IMAGE_DOWNLOAD_THREADS = 8
# 기록이 없을 때 예상 시간 계산에 쓰는 값 (초). 실제 등록을 하면 기록으로 바뀐다.
GUESS_BASE_SEC = 2.0
GUESS_PER_IMAGE_SEC = 0.35


# ───────────────────────── 불러오기 / 검사

def classify(row, cfg, categories, registered):
    s = convert.summary(row, cfg)
    errors, warnings = convert.validate(row, cfg, categories)
    if errors:
        return s, errors, warnings, "invalid", ""
    if cfg.get("skip_registered_code", True) and s["seller_code"] and s["seller_code"] in registered:
        return s, errors, warnings, "duplicate", "같은 판매자코드가 이미 등록되어 있습니다."
    return s, errors, warnings, "ready", ""


def import_excel(db, file, name):
    cfg = config.load()
    rows = excel.read(file)
    if not rows:
        raise ValueError("엑셀에 상품이 없습니다. 첫 줄이 열 이름, 둘째 줄부터 상품이어야 합니다.")
    if "상품명" not in rows[0]:
        raise ValueError("'상품명' 열을 찾지 못했습니다. 엑셀 첫 줄의 열 이름을 확인하세요.")
    categories = naver.cached_categories()
    registered = db.registered_codes()
    items = []
    for row in rows:
        s, err, warn, status, msg = classify(row, cfg, categories, registered)
        items.append((s, row, err, warn, status, msg))
    return db.add_batch(name, items)


def revalidate(db, bid):
    """설정이나 카테고리 목록이 바뀐 뒤 다시 검사한다. 등록된 상품은 건드리지 않는다."""
    cfg = config.load()
    categories = naver.cached_categories()
    registered = db.registered_codes(exclude_batch=bid)
    for p in db.products(bid):
        if p["status"] in ("success", "running", "queued"):
            continue
        row = db.product(p["id"])["data"]
        s, err, warn, status, msg = classify(row, cfg, categories, registered)
        if status == "ready" and p["status"] == "fail":
            status, msg = "fail", p["message"]
        db.x("UPDATE products SET errors=?, warnings=?, status=?, message=?, image_count=? WHERE id=?",
             (json.dumps(err, ensure_ascii=False), json.dumps(warn, ensure_ascii=False), status, msg,
              s["image_count"], p["id"]))


def estimate(db, products, cfg):
    """등록 전 예상 시간(초). 최근 기록이 있으면 그 평균, 없으면 이미지 수로 어림한다."""
    workers = max(1, int(cfg.get("workers") or 1))
    recent = db.recent_seconds()
    if len(recent) >= 5:
        per = sum(recent) / len(recent)
        total = per * len(products)
        basis = f"최근 등록 {len(recent)}건 평균 {per:.1f}초"
    else:
        imgs = sum(p["image_count"] for p in products)
        total = GUESS_BASE_SEC * len(products) + GUESS_PER_IMAGE_SEC * imgs
        basis = "어림값 (실제 등록 기록이 쌓이면 정확해집니다)"
    total += float(cfg.get("delay_sec") or 0) * len(products)
    return {"seconds": total / workers, "basis": basis, "workers": workers,
            "count": len(products), "images": sum(p["image_count"] for p in products)}


# ───────────────────────── 실행

class Stopped(Exception):
    pass


class Runner:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.pause_ev = threading.Event()
        self.stop_ev = threading.Event()
        self.thread = None
        self.log = collections.deque(maxlen=300)
        self._reset(None, 0)

    def _reset(self, bid, total):
        self.state = {
            "running": False, "paused": False, "stopping": False, "batch_id": bid,
            "total": total, "done": 0, "ok": 0, "fail": 0, "images": 0, "images_reused": 0,
            "started_at": None, "ended_at": None, "paused_sec": 0.0, "paused_at": None,
            "current": {}, "error": "",
        }

    # ── 조작

    def start(self, bid, ids=None, limit=None):
        with self.lock:
            if self.state["running"]:
                raise RuntimeError("이미 등록 중입니다.")
            cfg = config.load()
            if not str(cfg.get("as_phone") or "").strip():
                raise RuntimeError("설정에서 A/S 전화번호를 먼저 넣어 주세요. (네이버 필수 항목)")
            client = naver.make_client(cfg)
            statuses = ("ready", "fail", "duplicate") if ids else ("ready", "fail")
            targets = [p for p in self.db.products(bid) if p["status"] in statuses
                       and (not ids or p["id"] in ids)]
            if limit:
                targets = targets[:limit]
            if not targets:
                raise RuntimeError("등록할 상품이 없습니다. (등록 대기·실패 상태인 상품만 등록합니다)")
            for p in targets:
                self.db.set_status(p["id"], "queued", stage="", message="")
            self._reset(bid, len(targets))
            self.state.update(running=True, started_at=time.time())
            self.pause_ev.clear()
            self.stop_ev.clear()
            self.log.clear()
            self.thread = threading.Thread(target=self._main, args=(cfg, client, bid, targets), daemon=True)
            self.thread.start()

    def pause(self):
        with self.lock:
            if self.state["running"] and not self.state["paused"]:
                self.pause_ev.set()
                self.state.update(paused=True, paused_at=time.time())
                self._log("info", "일시정지. 지금 처리 중인 상품까지만 마칩니다.")

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
                self._log("info", "중단합니다. 지금 처리 중인 상품까지만 마칩니다.")
        self.resume()

    # ── 진행 상황

    def _log(self, level, msg, pid=None):
        self.log.append({"t": time.time(), "level": level, "msg": msg, "pid": pid})

    def snapshot(self):
        with self.lock:
            s = dict(self.state)
            s["current"] = [{"pid": k, **v} for k, v in self.state["current"].items()]
            now = s["ended_at"] or time.time()
            paused = s["paused_sec"] + ((now - s["paused_at"]) if s["paused_at"] else 0)
            elapsed = (now - s["started_at"] - paused) if s["started_at"] else 0
            s["elapsed"] = elapsed
            s["rate_per_min"] = (s["done"] / elapsed * 60) if elapsed > 0 and s["done"] else None
            remaining = s["total"] - s["done"]
            s["eta"] = (remaining / s["done"] * elapsed) if s["done"] and s["running"] else None
            s["log"] = list(self.log)[-120:]
            return s

    # ── 작업 스레드

    def _main(self, cfg, client, bid, targets):
        run_id = self.db.start_run(bid, len(targets), note=f"동시 {cfg.get('workers')}개")
        try:
            self._log("info", f"{len(targets)}개 등록을 시작합니다. (동시 {cfg.get('workers')}개)")
            categories = client.categories()
            q = queue.Queue()
            for p in targets:
                q.put(p)
            workers = max(1, min(int(cfg.get("workers") or 1), 8))
            with ThreadPoolExecutor(IMAGE_DOWNLOAD_THREADS) as pool:
                threads = [threading.Thread(target=self._worker, args=(cfg, client, categories, q, pool),
                                            daemon=True) for _ in range(workers)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        except Exception as e:  # noqa: BLE001 - 화면에 그대로 보여준다
            self.state["error"] = str(e)
            self._log("err", f"등록을 시작하지 못했습니다: {e}")
        finally:
            # 시작하지 못했거나 중단해서 남은 상품은 원래 상태로 돌린다.
            for p in targets:
                cur = self.db.product(p["id"])
                if cur and cur["status"] == "queued":
                    self.db.set_status(p["id"], p["status"], message=p["message"])
            with self.lock:
                s = self.state
                if s["paused_at"]:
                    s["paused_sec"] += time.time() - s["paused_at"]
                s.update(running=False, paused=False, paused_at=None, stopping=False,
                         ended_at=time.time(), current={})
                self.db.end_run(run_id, s["ok"], s["fail"], s["images"])
                self._log("ok" if not s["fail"] else "info",
                          f"끝: 성공 {s['ok']}개, 실패 {s['fail']}개, 새로 올린 이미지 {s['images']}장")

    def _wait_if_paused(self):
        while self.pause_ev.is_set() and not self.stop_ev.is_set():
            time.sleep(0.3)
        if self.stop_ev.is_set():
            raise Stopped

    def _worker(self, cfg, client, categories, q, pool):
        while True:
            try:
                self._wait_if_paused()
                p = q.get_nowait()
            except (Stopped, queue.Empty):
                return
            self._one(cfg, client, categories, pool, p)
            delay = float(cfg.get("delay_sec") or 0)
            if delay:
                time.sleep(delay)

    def _stage(self, pid, name, stage):
        with self.lock:
            self.state["current"][pid] = {"name": name, "stage": stage}
        self.db.set_stage(pid, stage)

    def _one(self, cfg, client, categories, pool, p):
        pid, name = p["id"], p["name"]
        t0 = time.time()
        self.db.set_status(pid, "running", stage="준비")
        self._stage(pid, name, "준비")
        notes = []
        try:
            row = self.db.product(pid)["data"]
            cat_id = categories.get(str(row.get("카테고리") or "").strip())
            if not cat_id:
                raise convert.ConvertError(f"카테고리 '{row.get('카테고리')}'를 스마트스토어에서 찾지 못했습니다.")
            convert.build_body(row, cfg, cat_id)  # 이미지 올리기 전에 빠진 값부터 확인

            url_map, n_new, failed = self._images(cfg, client, pool, row, pid, name)
            if failed:
                notes.append(f"상세 이미지 {len(failed)}장은 내려받지 못해 원래 주소로 둠")

            self._stage(pid, name, "상품 등록 중")
            on_wait = lambda m: self._stage(pid, name, m)  # noqa: E731
            res = client.create_product(convert.build_body(row, cfg, cat_id, url_map), on_wait=on_wait)
            sec = time.time() - t0
            self.db.set_status(pid, "success", stage="", message=" / ".join(notes), seconds=sec,
                               origin_no=str(res.get("originProductNo", "")),
                               channel_no=str(res.get("smartstoreChannelProductNo", "")))
            with self.lock:
                self.state["ok"] += 1
            self._log("ok", f"등록 완료 · {name[:40]} ({sec:.1f}초, 새 이미지 {n_new}장)", pid)
        except Exception as e:  # noqa: BLE001 - 상품 하나의 실패는 기록하고 다음으로
            self.db.set_status(pid, "fail", stage="", message=str(e), seconds=time.time() - t0)
            with self.lock:
                self.state["fail"] += 1
            self._log("err", f"실패 · {name[:40]} · {e}", pid)
        finally:
            with self.lock:
                self.state["done"] += 1
                self.state["current"].pop(pid, None)

    def _images(self, cfg, client, pool, row, pid, name):
        """이미지를 네이버 서버에 올리고 (원본→네이버 주소, 새로 올린 수, 실패한 상세 이미지)."""
        srcs = convert.images_to_upload(row, cfg)
        thumbs = set(convert.thumbnails(row)[:10])
        url_map = self.db.image_map(srcs)
        need = [u for u in srcs if u not in url_map]
        with self.lock:
            self.state["images_reused"] += len(srcs) - len(need)
        if not need:
            return url_map, 0, []

        self._stage(pid, name, f"이미지 내려받는 중 0/{len(need)}")
        got, failed, done = [], [], 0
        futures = {pool.submit(client.download, u): u for u in need}
        for fut, u in futures.items():
            try:
                data, ctype = fut.result()
                got.append((u, data, ctype))
            except Exception as e:  # noqa: BLE001
                if u in thumbs:
                    raise naver.ApiError(f"대표/추가 이미지를 내려받지 못했습니다: {e}")
                failed.append(u)
            done += 1
            if done % 5 == 0 or done == len(need):
                self._stage(pid, name, f"이미지 내려받는 중 {done}/{len(need)}")

        on_wait = lambda m: self._stage(pid, name, m)  # noqa: E731
        sent = 0
        for i in range(0, len(got), naver.IMAGES_PER_CALL):
            chunk = got[i:i + naver.IMAGES_PER_CALL]
            self._stage(pid, name, f"이미지 올리는 중 {sent}/{len(got)}")
            new_urls = client.upload_images(chunk, on_wait=on_wait)
            pairs = list(zip([u for u, _, _ in chunk], new_urls))
            self.db.save_images(pairs)
            url_map.update(pairs)
            sent += len(chunk)
            with self.lock:
                self.state["images"] += len(chunk)
        return url_map, sent, failed
