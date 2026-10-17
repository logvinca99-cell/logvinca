"""엑셀 → 상품 사전 목록. 첫 시트의 첫 줄을 열 이름으로 본다."""

import ast
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
            except (ValueError, SyntaxError):
                pass
    return s


def read(path_or_file):
    wb = openpyxl.load_workbook(path_or_file, data_only=True, read_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, [])]
        out = []
        for r in rows:
            if all(v is None or str(v).strip() == "" for v in r):
                continue
            out.append({h: parse_value(v) for h, v in zip(header, r) if h})
        return out
    finally:
        wb.close()
