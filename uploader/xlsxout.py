"""내려받는 엑셀 공통 서식: 머리줄 굵게·초록 바탕, 첫 줄 고정, 칸 너비, 코드·번호 칸은 글자(지수로 깨지지 않게), 금액은 천 단위 쉼표."""
import io


def build(sheet, header, rows, widths=None, text_cols=(), money_cols=()):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    ws.append(list(header))
    for r in rows:
        ws.append([("" if v is None else (str(v) if i in text_cols else v)) for i, v in enumerate(r)])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F8F4E")
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    for i in range(len(header)):
        col = get_column_letter(i + 1)
        ws.column_dimensions[col].width = (widths[i] if widths and i < len(widths) else 14)
        if i in text_cols:
            for c in ws[col][1:]:
                c.number_format = "@"
        if i in money_cols:
            for c in ws[col][1:]:
                c.number_format = "#,##0"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
