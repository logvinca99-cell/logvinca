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


def _rows_to_dicts(rows, parse=True):
    header = None
    for r in rows:
        if header is None:
            header = [str(h).strip() if h is not None else "" for h in r]
            continue
        if all(v is None or str(v).strip() == "" for v in r):
            continue
        yield {h: (parse_value(v) if parse else v) for h, v in zip(header, r) if h}


def iter_rows(path_or_file, filename="", parse=True):
    """첫 줄을 열 이름으로 보고 둘째 줄부터 사전을 하나씩 돌려준다."""
    name = (filename or getattr(path_or_file, "name", "") or str(path_or_file)).lower()
    if name.endswith(".csv"):
        raw = path_or_file.read() if hasattr(path_or_file, "read") else open(path_or_file, "rb").read()
        text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
        yield from _rows_to_dicts(csv.reader(io.StringIO(text)), parse)
        return
    wb = openpyxl.load_workbook(path_or_file, data_only=True, read_only=True)
    try:
        yield from _rows_to_dicts(wb.worksheets[0].iter_rows(values_only=True), parse)
    finally:
        wb.close()


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
