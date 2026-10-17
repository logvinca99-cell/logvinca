"""오래 걸리는 일(엑셀 불러오기, 상품명 만들기, 계획 만들기)을 뒤에서 돌리고 진행률을 알려준다."""

import itertools
import logging
import threading
import time


class Tasks:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}
        self._ids = itertools.count(1)

    def start(self, kind, title, fn, *args, **kwargs):
        """fn(*args, progress=..., should_stop=..., **kwargs) 를 스레드에서 실행."""
        with self.lock:
            if any(t["status"] == "running" and t["kind"] == kind for t in self.items.values()):
                raise RuntimeError("같은 종류의 작업이 이미 진행 중입니다. 끝난 뒤에 다시 시도하세요.")
            tid = next(self._ids)
            stop = threading.Event()
            t = {"id": tid, "kind": kind, "title": title, "status": "running", "done": 0, "total": None,
                 "message": "", "result": None, "error": "", "started_at": time.time(), "ended_at": None,
                 "_stop": stop}
            self.items[tid] = t

        def progress(done, total, message=""):
            t.update(done=done, total=total, message=message)

        def run():
            try:
                t["result"] = fn(*args, progress=progress, should_stop=stop.is_set, **kwargs)
                t["status"] = "stopped" if stop.is_set() else "done"
            except Exception as e:  # noqa: BLE001 - 화면에 보여준다
                t["status"] = "error"
                t["error"] = str(e)
                logging.getLogger("uploader").exception("작업 실패: %s", title)
            t["ended_at"] = time.time()

        threading.Thread(target=run, daemon=True).start()
        return tid

    def stop(self, tid):
        t = self.items.get(tid)
        if t:
            t["_stop"].set()

    def list(self):
        now = time.time()
        with self.lock:
            # 끝난 지 10분 넘은 작업은 목록에서 뺀다
            for tid in [k for k, v in self.items.items() if v["ended_at"] and now - v["ended_at"] > 600]:
                self.items.pop(tid)
            return [{k: v for k, v in t.items() if not k.startswith("_")}
                    for t in sorted(self.items.values(), key=lambda x: -x["id"])]
