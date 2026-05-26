"""
Excel report exporter — builds a 7-sheet .xlsx from a dataset.

Sheets (in order):
  1. summary      — Feature table, yield bins, evaluation, web link
  2. yield        — Full yield table with comments
  3. cpk          — CPK table with color coding and comments
  4. fail_data    — Fail item table with per-subject PNG thumbnails
  5. fail_values  — Per-student per-subject raw fail records (source/call/grade/class/type/subject/value/limits)
  6. issue_table  — Issue table with distribution PNG + editable fields
  7. distribution — Combined thumbnail grid PNG + link to web page

Thumbnail strategy (no live server calls, reads disk directly):
  - Try cairosvg  : SVG thumbs/  → PNG  (fast, install: pip install cairosvg)
  - Fallback PIL  : resize any pre-cached fail_pngs/ entry
  - Fallback none : cell left blank, image skipped

Combined distribution PNG requires pillow (pip install pillow).
"""

from __future__ import annotations

import json
import re
import threading
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config import DATASETS_DIR, SERVER_BASE_URL
from table_builder import read_table_json, get_fail_values

# ── private helpers duplicated from dash_dashboard to avoid Dash import ────────

def _read_json_file(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_yield_comments(dataset_id: str) -> dict:
    return _read_json_file(DATASETS_DIR / dataset_id / "tables" / "yield_comments.json") or {}


def _read_cpk_comments(dataset_id: str) -> dict:
    return _read_json_file(DATASETS_DIR / dataset_id / "tables" / "cpk_comments.json") or {}


def _read_issue_comments(dataset_id: str) -> dict:
    return _read_json_file(DATASETS_DIR / dataset_id / "tables" / "issue_comments.json") or {}


def _read_summary_comments(dataset_id: str) -> dict:
    return _read_json_file(DATASETS_DIR / dataset_id / "tables" / "summary_yield_comments.json") or {}


def _read_summary_eval(dataset_id: str) -> dict:
    return _read_json_file(DATASETS_DIR / dataset_id / "tables" / "summary_eval.json") or {}


def _cpk_comment_key(subject, source) -> str:
    return f"{(subject or '').strip()}|{(source or '').strip()}"


def _merge_cpk_subject(rows: list) -> list:
    merged = []
    prev = None
    for row in rows:
        row = dict(row)
        cur = row.get("subject")
        if cur == prev:
            row["subject"] = ""
            row["lower_limit"] = ""
            row["upper_limit"] = ""
            row["units"] = ""
        else:
            prev = cur
        merged.append(row)
    return merged


def _yield_sort_key(r: dict):
    st = str(r.get("bin", "")).strip()
    is_pass = 0 if st == "1" else 1
    try:
        avg = float(r.get("avg") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    return (is_pass, -avg)


def _build_issue_rows(fail_items: dict, sources: list, issue_comments: dict) -> list:
    rows = []
    for r in (fail_items or {}).get("rows", []) or []:
        st = str(r.get("bin", "")).strip()
        fail_subjects = r.get("fail_subjects") or []
        is_pass = st == "1"
        if is_pass or not fail_subjects:
            subject = "Pass" if is_pass else "N/A"
            subject_id = None
        else:
            top = fail_subjects[0]
            subject = top.get("subject", "N/A")
            subject_id = top.get("subject_id")
        saved = issue_comments.get(st) or {}
        if not isinstance(saved, dict):
            saved = {}
        row = {
            "bin": st,
            "subject": subject,
            "subject_id": subject_id,
            "avg": r.get("avg"),
            "issue_point": saved.get("issue_point", ""),
            "issue_comment": saved.get("comment", ""),
            "dev_comment": saved.get("dev_comment", ""),
            "pte_comment": saved.get("pte_comment", ""),
        }
        for src in sources or []:
            row[f"portion_{src}"] = r.get(f"portion_{src}")
        rows.append(row)
    return rows


# ── Style constants ─────────────────────────────────────────────────────────────

_FILL_HDR     = PatternFill("solid", fgColor="F6F7F9")
_FILL_SECTION = PatternFill("solid", fgColor="D0DFF0")
_FILL_COMMENT = PatternFill("solid", fgColor="FFFDF3")
_FILL_TOTAL   = PatternFill("solid", fgColor="EEF4FB")
_FILL_LOW_CPK = PatternFill("solid", fgColor="FFF3BF")
_FILL_PASS    = PatternFill("solid", fgColor="F0F8F0")

_FONT_TITLE   = Font(bold=True, size=14)
_FONT_SECTION = Font(bold=True, size=12, color="1F3D6B")
_FONT_HDR     = Font(bold=True, size=11)
_FONT_LINK    = Font(bold=True, size=12, color="2369B3", underline="single")
_FONT_SMALL   = Font(size=9, color="666666")
_FONT_BOLD    = Font(bold=True)

_THIN   = Side(style="thin",   color="CCCCCC")
_MEDIUM = Side(style="medium", color="B8C4D4")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_ALIGN_C  = Alignment(horizontal="center", vertical="center", wrap_text=True)
_ALIGN_L  = Alignment(horizontal="left",   vertical="center", wrap_text=True)
_ALIGN_LT = Alignment(horizontal="left",   vertical="top",    wrap_text=True)

# thumbnail dimensions embedded in xlsx cells
THUMB_W_PX  = 120
THUMB_H_PX  = 83
THUMB_ROW_H = 65   # row height in points
THUMB_COL_W = 18   # column width in chars

# ── Cell / row helpers ──────────────────────────────────────────────────────────

def _c(ws, row, col, value=None, *, font=None, fill=None, align=None,
       border=_BORDER, num_fmt=None):
    cell = ws.cell(row=row, column=col, value=value)
    if font   is not None: cell.font      = font
    if fill   is not None: cell.fill      = fill
    if align  is not None: cell.alignment = align
    if border is not None: cell.border    = border
    if num_fmt:            cell.number_format = num_fmt
    return cell


def _header_row(ws, row_num: int, headers: list[str], widths: list[float] | None = None):
    for i, h in enumerate(headers, 1):
        _c(ws, row_num, i, h, font=_FONT_HDR, fill=_FILL_HDR, align=_ALIGN_C)
    if widths:
        for i, w in enumerate(widths, 1):
            if w:
                ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row_num].height = 20


def _section_row(ws, row_num: int, text: str, span: int = 8):
    _c(ws, row_num, 1, text, font=_FONT_SECTION, fill=_FILL_SECTION,
       align=_ALIGN_L, border=None)
    if span > 1:
        ws.merge_cells(
            start_row=row_num, start_column=1,
            end_row=row_num,   end_column=span,
        )
    ws.row_dimensions[row_num].height = 22


def _blank_row(ws, row_num: int, height: float = 6):
    ws.row_dimensions[row_num].height = height


# ── PNG helpers (disk-only, no server requests) ─────────────────────────────────

_png_lock = threading.Lock()


def _try_cairosvg(svg_path: Path, w: int, h: int) -> bytes | None:
    try:
        import cairosvg  # optional
        return cairosvg.svg2png(url=str(svg_path), output_width=w, output_height=h)
    except Exception:
        return None


def _try_pil_resize(png_bytes: bytes, w: int, h: int) -> bytes | None:
    try:
        from PIL import Image as PILImage
        img = PILImage.open(BytesIO(png_bytes)).convert("RGB")
        img = img.resize((w, h), PILImage.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _try_kaleido(dataset_id: str, subject_id: int, w: int, h: int) -> bytes | None:
    """Render chart JSON → PNG via kaleido (already a project dependency)."""
    chart_path = DATASETS_DIR / dataset_id / "charts" / f"{subject_id}.json"
    if not chart_path.exists():
        return None
    try:
        import plotly.io as pio
        payload = json.loads(chart_path.read_text(encoding="utf-8"))
        raw = pio.to_image(
            {"data": payload["data"], "layout": payload["layout"]},
            format="png", width=w, height=h, scale=1,
        )
        return raw
    except Exception:
        return None


def _get_thumb_png(dataset_id: str, subject_id: int,
                   w: int = THUMB_W_PX, h: int = THUMB_H_PX,
                   allow_kaleido: bool = True) -> bytes | None:
    """
    Return PNG bytes for a subject thumbnail.
    Priority:
      1. Disk cache        (fail_pngs/<sid>_s.png  for default size)
      2. cairosvg          from thumbs/<sid>.svg    (needs cairo system lib)
      3. PIL resize        of any pre-cached kaleido PNG in fail_pngs/<sid>.png
      4. kaleido           from charts/<sid>.json   (always works, cached on disk)
    Results at default size are cached to fail_pngs/<sid>_s.png.
    Pass allow_kaleido=False to skip step 4 (e.g. for large batch operations).
    """
    use_cache  = (w == THUMB_W_PX and h == THUMB_H_PX)
    cache_dir  = DATASETS_DIR / dataset_id / "fail_pngs"
    cache_path = cache_dir / f"{subject_id}_s.png"

    if use_cache:
        with _png_lock:
            if cache_path.exists():
                return cache_path.read_bytes()

    svg_path = DATASETS_DIR / dataset_id / "thumbs"    / f"{subject_id}.svg"
    full_png = DATASETS_DIR / dataset_id / "fail_pngs" / f"{subject_id}.png"

    png: bytes | None = None

    # cairosvg — fast, lossless; requires libcairo system library
    if svg_path.exists():
        png = _try_cairosvg(svg_path, w, h)

    # PIL resize of an already-cached full-size kaleido PNG
    if png is None and full_png.exists():
        png = _try_pil_resize(full_png.read_bytes(), w, h)

    # kaleido from chart JSON — reliable fallback, result is cached so cost is once-per-subject
    if png is None and allow_kaleido:
        png = _try_kaleido(dataset_id, subject_id, w, h)

    if png is not None and use_cache:
        with _png_lock:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(png)

    return png


def _add_image(ws, png_bytes: bytes, anchor: str, w_px: int, h_px: int):
    if not png_bytes:
        return
    try:
        img = XLImage(BytesIO(png_bytes))
        img.width  = w_px
        img.height = h_px
        ws.add_image(img, anchor)
    except Exception:
        pass


# ── Sheet 1: summary ────────────────────────────────────────────────────────────

def _sheet_summary(wb, dataset_id, meta, yield_rows, fail_items,
                   summary_comments, eval_data):
    ws = wb.create_sheet("summary")
    ws.sheet_view.showGridLines = False

    sources  = meta.get("sources")  or []
    subjects = meta.get("subjects") or []

    pass_row     = next((r for r in yield_rows if str(r.get("bin",""))=="1"), {})
    avg_val      = pass_row.get("avg")
    pass_yield   = f"{avg_val:.2f}%" if avg_val is not None else "-"
    non_pass     = [r for r in (fail_items.get("rows") or [])
                    if str(r.get("bin","")) != "1"]

    ROW = 1

    # Title
    _c(ws, ROW, 1, f"Plotly Data Dashboard — {dataset_id}", font=_FONT_TITLE, border=None)
    ws.merge_cells(f"A{ROW}:F{ROW}")
    ws.row_dimensions[ROW].height = 28
    ROW += 1

    # Web link — summary/dashboard
    dash_url = f"{SERVER_BASE_URL}/dash/{dataset_id}"
    lnk = _c(ws, ROW, 1, "🌐  대시보드 웹으로 열기 (서버 실행 중일 때 클릭)", font=_FONT_LINK, align=_ALIGN_L, border=None)
    lnk.hyperlink = dash_url
    ws.merge_cells(f"A{ROW}:F{ROW}")
    ws.row_dimensions[ROW].height = 22
    ROW += 1

    _blank_row(ws, ROW); ROW += 1

    # ── Feature ──────────────────────────────────────────────────────────────
    _section_row(ws, ROW, "Feature", span=6); ROW += 1

    feat_headers = ["Dataset ID", "Total DUT", "Pass (type 1)", "Fail Types", "Sources", "Subjects"]
    feat_widths  = [22, 10, 14, 12, 10, 10]
    _header_row(ws, ROW, feat_headers, feat_widths); ROW += 1

    feat_vals = [
        dataset_id,
        meta.get("row_count", "-"),
        pass_row.get("count", "-"),
        len(non_pass),
        len(sources),
        len(subjects),
    ]
    for i, v in enumerate(feat_vals, 1):
        _c(ws, ROW, i, v, align=_ALIGN_C)
    ws.row_dimensions[ROW].height = 18; ROW += 1

    _blank_row(ws, ROW); ROW += 1

    # ── Yield Summary ─────────────────────────────────────────────────────────
    _section_row(ws, ROW, "Yield Summary", span=6); ROW += 1

    _c(ws, ROW, 1,
       f"Overall Pass Yield (Bin 1):  {pass_yield}",
       font=Font(bold=True, size=12, color="1F4D8C"), align=_ALIGN_L, border=None)
    ws.merge_cells(f"A{ROW}:F{ROW}")
    ws.row_dimensions[ROW].height = 22; ROW += 1

    _c(ws, ROW, 1, "Major Fail Bins (top 5)",
       font=Font(bold=True, size=11, color="444444"), align=_ALIGN_L, border=None)
    ws.merge_cells(f"A{ROW}:F{ROW}")
    ws.row_dimensions[ROW].height = 18; ROW += 1

    ys_headers = ["Rank", "Fail Type", "Main Fail Subject", "Fail Ratio", "Comment"]
    ys_widths  = [6, 10, 34, 12, 40]
    _header_row(ws, ROW, ys_headers, ys_widths); ROW += 1

    for rank, r in enumerate(non_pass[:5], 1):
        st           = str(r.get("bin",""))
        fail_subs    = r.get("fail_subjects") or []
        main_fail    = fail_subs[0].get("subject","N/A") if fail_subs else "N/A"
        avg_r        = r.get("avg")
        fail_ratio   = f"{avg_r:.2f}%" if avg_r is not None else "-"
        comment      = summary_comments.get(st, "")
        row_data     = [rank, st, main_fail, fail_ratio, comment]
        aligns       = [_ALIGN_C, _ALIGN_C, _ALIGN_L, _ALIGN_C, _ALIGN_LT]
        fills        = [None, None, None, None, _FILL_COMMENT]
        for i, (v, al, fi) in enumerate(zip(row_data, aligns, fills), 1):
            _c(ws, ROW, i, v, align=al, fill=fi)
        ws.row_dimensions[ROW].height = 18; ROW += 1

    _blank_row(ws, ROW); ROW += 1

    # ── Evaluation Summary ────────────────────────────────────────────────────
    _section_row(ws, ROW, "Evaluation Summary", span=2); ROW += 1
    _header_row(ws, ROW, ["Category", "Result"], [14, 52]); ROW += 1

    for cat, key in [("Yield","yield"), ("CPK","cpk"), ("Temp","temp"), ("ETC","etc")]:
        _c(ws, ROW, 1, cat, font=_FONT_BOLD, fill=_FILL_HDR, align=_ALIGN_C)
        _c(ws, ROW, 2, eval_data.get(key,""), fill=_FILL_COMMENT, align=_ALIGN_LT)
        ws.row_dimensions[ROW].height = 18; ROW += 1

    # column A width
    ws.column_dimensions["A"].width = 22


# ── Sheet 2: yield ──────────────────────────────────────────────────────────────

def _sheet_yield(wb, yield_rows, sources, yield_comments):
    ws = wb.create_sheet("yield")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"

    headers = ["bin", "count"]
    widths  = [12, 8]
    for src in sources:
        headers.append(str(src))
        widths.append(10)
    headers += ["avg", "Main Fail Subject", "comment"]
    widths  += [10, 30, 40]

    _header_row(ws, 1, headers, widths)

    merged = []
    for row in yield_rows:
        row = dict(row)
        key = str(row.get("bin",""))
        row["comment"] = yield_comments.get(key, row.get("comment","") or "")
        merged.append(row)
    merged.sort(key=_yield_sort_key)

    for r_idx, row in enumerate(merged, 2):
        is_pass = str(row.get("bin","")) == "1"
        bg = _FILL_PASS if is_pass else None

        col = 1
        _c(ws, r_idx, col, row.get("bin"), fill=bg, align=_ALIGN_C); col += 1
        _c(ws, r_idx, col, row.get("count"),         fill=bg, align=_ALIGN_C); col += 1
        for src in sources:
            _c(ws, r_idx, col, row.get(f"portion_{src}"), fill=bg, align=_ALIGN_C, num_fmt="0.00")
            col += 1
        _c(ws, r_idx, col, row.get("avg"),              fill=_FILL_TOTAL, align=_ALIGN_C, num_fmt="0.00"); col += 1
        _c(ws, r_idx, col, row.get("Main Fail subject"), fill=bg,          align=_ALIGN_L); col += 1
        _c(ws, r_idx, col, row.get("comment",""),         fill=_FILL_COMMENT, align=_ALIGN_LT)
        ws.row_dimensions[r_idx].height = 18


# ── Sheet 3: cpk ────────────────────────────────────────────────────────────────

def _sheet_cpk(wb, cpk_rows, cpk_comments):
    ws = wb.create_sheet("cpk")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"

    headers = ["subject", "lower_limit", "upper_limit", "units", "source",
               "min", "median", "max", "average", "stdev",
               "cpl", "cpu", "cp", "cpk", "comment"]
    widths  = [28, 9, 9, 8, 14, 9, 9, 9, 9, 9, 9, 9, 9, 9, 40]
    _header_row(ws, 1, headers, widths)

    for r in cpk_rows:
        r["comment"] = cpk_comments.get(
            _cpk_comment_key(r.get("subject"), r.get("source")), "")
    rows = _merge_cpk_subject(cpk_rows)

    numeric_cols = {"lower_limit","upper_limit","min","median","max","average","stdev","cpl","cpu","cp","cpk"}
    center_cols  = numeric_cols | {"units","source"}

    for r_idx, row in enumerate(rows, 2):
        is_total = row.get("source") == "total"
        is_new   = bool(row.get("subject"))  # non-empty → new subject group

        try:
            cpk_v = float(row.get("cpk",""))
            low   = cpk_v < 1.33
        except (TypeError, ValueError):
            low = False

        top_side = _MEDIUM if is_new else _THIN
        grp_border = Border(left=_THIN, right=_THIN, bottom=_THIN, top=top_side)

        for i, key in enumerate(headers, 1):
            v    = row.get(key, "")
            fill = (_FILL_COMMENT if key == "comment"
                    else _FILL_LOW_CPK if (key == "cpk" and low)
                    else _FILL_TOTAL   if is_total
                    else None)
            font = Font(bold=True, color="5C4400") if (key == "cpk" and low) else None
            al   = _ALIGN_C if key in center_cols else _ALIGN_L
            nf   = "0.000" if key in numeric_cols else None
            c    = _c(ws, r_idx, i, v, fill=fill, align=al, border=grp_border, num_fmt=nf)
            if font:
                c.font = font

        ws.row_dimensions[r_idx].height = 16


# ── Sheet 4: fail_data ──────────────────────────────────────────────────────────

MAX_FAIL_SUBS = 5   # how many fail subjects to show per row


def _sheet_fail_data(wb, dataset_id, fail_items):
    ws = wb.create_sheet("fail_data")
    ws.sheet_view.showGridLines = False

    headers = ["bin", "count", "portion (%)", "Main Fail Subject"]
    widths  = [12, 8, 12, 28]
    for i in range(1, MAX_FAIL_SUBS + 1):
        headers.append(f"Fail Subject {i}")
        widths.append(THUMB_COL_W)

    _header_row(ws, 1, headers, widths)

    for r_idx, row in enumerate((fail_items.get("rows") or []), 2):
        st       = str(row.get("bin",""))
        is_pass  = st == "1"
        fail_sub = row.get("fail_subjects") or []

        _c(ws, r_idx, 1, st,                   align=_ALIGN_C)
        _c(ws, r_idx, 2, row.get("count"),      align=_ALIGN_C)
        _c(ws, r_idx, 3, row.get("portion (%)"), align=_ALIGN_C, num_fmt="0.00")
        _c(ws, r_idx, 4,
           row.get("Main Fail subject", "Pass" if is_pass else "N/A"),
           align=_ALIGN_L)

        if is_pass or not fail_sub:
            _c(ws, r_idx, 5, "Pass" if is_pass else "N/A", align=_ALIGN_C)
            ws.row_dimensions[r_idx].height = 20
            continue

        ws.row_dimensions[r_idx].height = THUMB_ROW_H

        for j, subj in enumerate(fail_sub[:MAX_FAIL_SUBS], 1):
            col_idx  = 4 + j
            sid      = subj.get("subject_id")
            label    = f"{subj.get('subject','')[:24]}\n{subj.get('count','')}ea"
            _c(ws, r_idx, col_idx, label, font=_FONT_SMALL, align=_ALIGN_LT)

            if sid is not None:
                png = _get_thumb_png(dataset_id, sid)
                if png:
                    _add_image(ws, png, f"{get_column_letter(col_idx)}{r_idx}",
                               THUMB_W_PX, THUMB_H_PX)


# ── Sheet 5: fail_values ────────────────────────────────────────────────────────

_FILL_LO = PatternFill("solid", fgColor="DBEAFE")   # blue-100
_FILL_HI = PatternFill("solid", fgColor="FEE2E2")   # red-100
_FONT_LO = Font(bold=True, color="1E40AF")           # blue-800
_FONT_HI = Font(bold=True, color="991B1B")           # red-800


def _sheet_fail_values(wb, dataset_id: str):
    ws = wb.create_sheet("fail_values")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"

    headers = ["Source (Sheet)", "DUT", "XCoord", "YCoord", "Bin",
               "Subject", "Value", "Lower Limit", "Upper Limit", "Fail"]
    ids     = ["source", "dut", "x_coord", "y_coord", "bin",
               "subject", "value", "lower_limit", "upper_limit", "fail"]
    widths  = [22, 8, 8, 8, 8, 28, 12, 12, 12, 9]

    _header_row(ws, 1, headers, widths)

    try:
        rows = get_fail_values(dataset_id)
    except Exception:
        rows = []

    if not rows:
        _c(ws, 2, 1, "데이터 없음 (non-pass DUT가 없거나 fail 기준 미설정)",
           font=Font(size=11, color="888888"), border=None)
        return

    center_cols = {"dut", "x_coord", "y_coord", "bin", "value",
                   "lower_limit", "upper_limit", "fail"}

    for r_idx, row in enumerate(rows, 2):
        is_lo  = row.get("fail") == "< lo"
        is_hi  = row.get("fail") == "> hi"
        v_fill = _FILL_LO if is_lo else (_FILL_HI if is_hi else None)
        v_font = _FONT_LO if is_lo else (_FONT_HI if is_hi else None)
        f_fill = v_fill
        f_font = v_font

        for col_idx, key in enumerate(ids, 1):
            val  = row.get(key, "")
            al   = _ALIGN_C if key in center_cols else _ALIGN_L
            fill = (v_fill if key in ("value", "fail") else None)
            c    = _c(ws, r_idx, col_idx, val, align=al, fill=fill)
            if key in ("value", "fail") and (v_font is not None):
                c.font = v_font

        ws.row_dimensions[r_idx].height = 16

    ws.auto_filter.ref = f"A1:{get_column_letter(len(ids))}1"


# ── Sheet 6: issue_table ────────────────────────────────────────────────────────

def _sheet_issue_table(wb, dataset_id, fail_items, sources, issue_comments):
    ws = wb.create_sheet("issue_table")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"

    headers = ["bin", "subject", "average"]
    widths  = [12, 26, 10]
    for src in sources:
        headers.append(str(src))
        widths.append(10)
    headers += ["Distribution", "Issue Point", "Comment", "개발팀 1차 Comment", "PTE 1차 comment"]
    widths  += [THUMB_COL_W, 32, 32, 32, 32]

    _header_row(ws, 1, headers, widths)

    rows = _build_issue_rows(fail_items, sources, issue_comments)
    rows.sort(key=_yield_sort_key)

    dist_col = 4 + len(sources)  # 1-based column index of "Distribution"

    for r_idx, row in enumerate(rows, 2):
        st      = str(row.get("bin",""))
        is_pass = st == "1"

        _c(ws, r_idx, 1, st,               align=_ALIGN_C)
        _c(ws, r_idx, 2, row.get("subject",""), align=_ALIGN_L)
        _c(ws, r_idx, 3, row.get("avg"),   align=_ALIGN_C, fill=_FILL_TOTAL, num_fmt="0.0000")

        col = 4
        for src in sources:
            _c(ws, r_idx, col, row.get(f"portion_{src}"), align=_ALIGN_C, num_fmt="0.00")
            col += 1

        # Distribution cell (image will overlay)
        _c(ws, r_idx, dist_col, "", align=_ALIGN_C)

        # Comment fields
        for off, key in enumerate(
            ["issue_point","issue_comment","dev_comment","pte_comment"], 1
        ):
            _c(ws, r_idx, dist_col + off, row.get(key,""),
               fill=_FILL_COMMENT, align=_ALIGN_LT)

        if is_pass:
            ws.row_dimensions[r_idx].height = 20
            continue

        ws.row_dimensions[r_idx].height = THUMB_ROW_H
        sid = row.get("subject_id")
        if sid is not None:
            png = _get_thumb_png(dataset_id, sid)
            if png:
                _add_image(ws, png, f"{get_column_letter(dist_col)}{r_idx}",
                           THUMB_W_PX, THUMB_H_PX)


# ── Sheet 6: distribution ───────────────────────────────────────────────────────

_GRID_COLS   = 5    # thumbnails per row in the combined PNG
_GRID_TW     = 100  # thumbnail width  (px) inside combined PNG
_GRID_TH     = 69   # thumbnail height (px) inside combined PNG
_GRID_LABEL  = 14   # label strip height (px) per thumbnail


def _build_combined_png(dataset_id: str, subjects: list) -> bytes | None:
    """
    Compose a grid image of all subject thumbnails.
    Requires: pillow  (pip install pillow)

    Kaleido is used only when subjects <= KALEIDO_LIMIT to avoid long waits.
    For large datasets without cairosvg, returns None (link-only fallback).
    """
    try:
        from PIL import Image as PILImage, ImageDraw
    except ImportError:
        return None

    n = len(subjects)
    if n == 0:
        return None

    # Kaleido renders ~0.5-2s per image; allow it only for small datasets.
    # cairosvg users are not affected (fast regardless of count).
    KALEIDO_LIMIT = 150
    use_kaleido = (n <= KALEIDO_LIMIT)

    rows_count = (n + _GRID_COLS - 1) // _GRID_COLS
    cell_h     = _GRID_TH + _GRID_LABEL
    grid_w     = _GRID_COLS * _GRID_TW
    grid_h     = rows_count * cell_h

    grid = PILImage.new("RGB", (grid_w, grid_h), (255, 255, 255))
    draw = ImageDraw.Draw(grid)

    any_thumb = False
    for i, subj in enumerate(subjects):
        sid  = subj.get("subject_id", i)
        col  = i % _GRID_COLS
        row  = i // _GRID_COLS
        x    = col * _GRID_TW
        y    = row * cell_h

        # label
        name = str(subj.get("subject",""))[:22]
        draw.text((x + 2, y + 1), name, fill=(80, 80, 80))

        # thumbnail
        png = _get_thumb_png(dataset_id, sid, w=_GRID_TW, h=_GRID_TH,
                              allow_kaleido=use_kaleido)
        if png:
            try:
                thumb = PILImage.open(BytesIO(png)).convert("RGB")
                thumb = thumb.resize((_GRID_TW, _GRID_TH), PILImage.LANCZOS)
                grid.paste(thumb, (x, y + _GRID_LABEL))
                any_thumb = True
            except Exception:
                draw.rectangle([x, y + _GRID_LABEL, x + _GRID_TW - 1, y + cell_h - 1],
                               outline=(200, 200, 200))
        else:
            draw.rectangle([x, y + _GRID_LABEL, x + _GRID_TW - 1, y + cell_h - 1],
                           fill=(240, 240, 240), outline=(200, 200, 200))

    if not any_thumb:
        return None

    buf = BytesIO()
    grid.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


def _sheet_distribution(wb, dataset_id, subjects):
    ws = wb.create_sheet("distribution")
    ws.sheet_view.showGridLines = False

    view_url = f"{SERVER_BASE_URL}/view/{dataset_id}"
    n_sub    = len(subjects)

    ROW = 1

    # Web link
    lnk = _c(ws, ROW, 1,
              "🌐  산포 분포 페이지 웹으로 열기 (서버 실행 중일 때 클릭)",
              font=_FONT_LINK, align=_ALIGN_L, border=None)
    lnk.hyperlink = view_url
    ws.merge_cells(f"A{ROW}:J{ROW}")
    ws.row_dimensions[ROW].height = 26; ROW += 1

    # Info
    _c(ws, ROW, 1,
       f"아래 PNG: {n_sub}개 subject 썸네일 전체 그리드 | "
       "※ 150개 초과 데이터셋은 cairosvg 필요 (Windows: GTK 런타임 + pip install cairosvg)",
       font=Font(size=10, color="666666"), align=_ALIGN_L, border=None)
    ws.merge_cells(f"A{ROW}:J{ROW}")
    ws.row_dimensions[ROW].height = 16; ROW += 1

    _blank_row(ws, ROW); ROW += 1

    # Combined PNG
    combined = _build_combined_png(dataset_id, subjects)
    if combined:
        try:
            img        = XLImage(BytesIO(combined))
            rows_count = (n_sub + _GRID_COLS - 1) // _GRID_COLS
            img.width  = _GRID_COLS * _GRID_TW
            img.height = rows_count * (_GRID_TH + _GRID_LABEL)
            ws.add_image(img, f"A{ROW}")
        except Exception as e:
            _c(ws, ROW, 1, f"PNG 삽입 실패: {e}",
               font=Font(size=10, color="AA0000"), border=None)
    else:
        KALEIDO_LIMIT = 150
        if n_sub > KALEIDO_LIMIT:
            msg = (
                f"썸네일 그리드 PNG 미생성 — subject {n_sub}개 > {KALEIDO_LIMIT}개 한도\n"
                "Windows에서 대규모 그리드를 생성하려면 GTK 런타임 설치 후 pip install cairosvg\n"
                "위 링크로 웹에서 전체 산포를 확인할 수 있습니다."
            )
        else:
            msg = (
                "썸네일 그리드 PNG 미생성 — pillow 설치 확인: pip install pillow\n"
                "위 링크로 웹에서 산포를 확인하세요."
            )
        _c(ws, ROW, 1, msg, font=Font(size=11, color="888888"), align=_ALIGN_LT, border=None)
        ws.merge_cells(f"A{ROW}:J{ROW}")
        ws.row_dimensions[ROW].height = 52

    ws.column_dimensions["A"].width = 20


# ── Public entry point ──────────────────────────────────────────────────────────

def build_report_xlsx(dataset_id: str) -> bytes:
    """Build and return the 7-sheet report XLSX as bytes."""
    meta     = read_table_json(dataset_id, "meta")       or {}
    yield_r  = read_table_json(dataset_id, "yield")      or []
    cpk_r    = read_table_json(dataset_id, "cpk")        or []
    fail_i   = read_table_json(dataset_id, "fail_items") or {"rows": []}

    sources  = meta.get("sources")  or []
    subjects = meta.get("subjects") or []

    ycomm  = _read_yield_comments(dataset_id)
    ccomm  = _read_cpk_comments(dataset_id)
    icomm  = _read_issue_comments(dataset_id)
    scomm  = _read_summary_comments(dataset_id)
    edata  = _read_summary_eval(dataset_id)

    wb = Workbook()
    wb.remove(wb.active)  # remove the default blank sheet

    _sheet_summary(wb, dataset_id, meta, yield_r, fail_i, scomm, edata)
    _sheet_yield(wb, yield_r, sources, ycomm)
    _sheet_cpk(wb, cpk_r, ccomm)
    _sheet_fail_data(wb, dataset_id, fail_i)
    _sheet_fail_values(wb, dataset_id)          # ← new
    _sheet_issue_table(wb, dataset_id, fail_i, sources, icomm)
    _sheet_distribution(wb, dataset_id, subjects)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
