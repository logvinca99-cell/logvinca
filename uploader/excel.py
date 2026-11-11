"""엑셀/CSV → 상품 사전. 수십만 줄도 메모리에 다 올리지 않고 한 줄씩 읽는다."""

import ast
import csv
import io
import json

import openpyxl


def parse_value(v):
    """엑셀 칸의 "['a', 'b']" / "{'k': True}" 같은 글자를 파이썬 값으로 바꾼다."""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return None
    if s[0] in "[{":
        for loader in (json.loads, ast.literal_eval):
            try:
                return loader(s)
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                pass
    return s


def _rows_to_dicts(rows, parse=True, lines=False):
    header = None
    for n, r in enumerate(rows, 1):
        if header is None:
            header = [str(h).strip() if h is not None else "" for h in r]
            continue
        if all(v is None or str(v).strip() == "" for v in r):
            continue
        d = {h: (parse_value(v) if parse else v) for h, v in zip(header, r) if h}
        yield (n, d) if lines else d


def _csv_text(raw):
    """CSV 글자: UTF-8, 안 되면 엑셀 한글 CSV(cp949)."""
    if not isinstance(raw, bytes):
        return raw
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp949")
        except UnicodeDecodeError:
            return raw.decode("utf-8-sig", errors="replace")


def iter_rows(path_or_file, filename="", parse=True, lines=False):
    """첫 줄을 열 이름으로 보고 둘째 줄부터 사전을 하나씩 돌려준다. lines=True면 (엑셀 실제 행 번호, 사전) — 빈 줄을 건너뛰어도 번호가 맞음."""
    name = (filename or getattr(path_or_file, "name", "") or str(path_or_file)).lower()
    if name.endswith(".csv"):
        raw = path_or_file.read() if hasattr(path_or_file, "read") else open(path_or_file, "rb").read()
        if hasattr(path_or_file, "seek"):
            path_or_file.seek(0)
        yield from _rows_to_dicts(csv.reader(io.StringIO(_csv_text(raw))), parse, lines)
        return
    wb = openpyxl.load_workbook(path_or_file, data_only=True, read_only=True)
    try:
        yield from _rows_to_dicts(wb.worksheets[0].iter_rows(values_only=True), parse, lines)
    finally:
        wb.close()
        if hasattr(path_or_file, "seek"):
            path_or_file.seek(0)


def header(path_or_file, filename=""):
    """첫 줄(열 이름들)."""
    name = (filename or getattr(path_or_file, "name", "") or str(path_or_file)).lower()
    try:
        if name.endswith(".csv"):
            raw = path_or_file.read() if hasattr(path_or_file, "read") else open(path_or_file, "rb").read()
            if hasattr(path_or_file, "seek"):
                path_or_file.seek(0)
            return [h.strip() for h in next(csv.reader(io.StringIO(_csv_text(raw))), [])]
        wb = openpyxl.load_workbook(path_or_file, data_only=True, read_only=True)
        try:
            return [str(h or "").strip() for h in next(wb.worksheets[0].iter_rows(values_only=True), ())]
        finally:
            wb.close()
            if hasattr(path_or_file, "seek"):
                path_or_file.seek(0)
    except Exception:  # noqa: BLE001
        return []


def need_name_column(path_or_file, filename=""):
    """원본 엑셀(셀업 양식)인지: 첫 줄에 '상품명' 열이 없으면 이유를 알려 주는 오류."""
    cols = header(path_or_file, filename)
    if "상품명" not in cols:
        raise ValueError("첫 줄에서 '상품명' 열을 찾지 못했습니다 — 셀업 양식 엑셀인지, 첫 줄이 열 이름인지 확인하세요"
                         + (f" (이 파일의 첫 줄: {', '.join(c for c in cols if c)[:120]})" if any(cols) else ""))


def read(path_or_file, filename=""):
    return list(iter_rows(path_or_file, filename))


def count_rows(path_or_file, filename=""):
    """진행률 표시용 대략의 줄 수 (엑셀은 시트 크기 정보로)."""
    name = (filename or str(path_or_file)).lower()
    if name.endswith(".csv"):
        return None
    try:
        wb = openpyxl.load_workbook(path_or_file, read_only=True)
        n = (wb.worksheets[0].max_row or 1) - 1
        wb.close()
        if hasattr(path_or_file, "seek"):
            path_or_file.seek(0)
        return n
    except Exception:  # noqa: BLE001 - 진행률이 없을 뿐
        if hasattr(path_or_file, "seek"):
            path_or_file.seek(0)
        return None
