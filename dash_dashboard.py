import base64
import json
from pathlib import Path

from flask import abort, send_from_directory

from config import DATASETS_DIR
from table_builder import read_table_json, get_fail_values


PAGE_SIZE = 25


def _dash_imports():
    try:
        from dash import Dash, Input, Output, State, dcc, html
        from dash import dash_table
    except ImportError as exc:
        raise RuntimeError("Dash is not installed. Install it with: pip install dash") from exc
    return Dash, Input, Output, State, dcc, html, dash_table


TAB_STYLE = {
    "padding": "8px 14px",
    "fontSize": "13px",
    "lineHeight": "1.2",
    "height": "auto",
    "minHeight": "0",
    "borderBottom": "1px solid #ddd",
}
TAB_SELECTED_STYLE = {
    **TAB_STYLE,
    "borderTop": "2px solid #4a90e2",
    "fontWeight": "600",
    "color": "#1f4d8c",
}
TABS_PARENT_STYLE = {"height": "44px", "minHeight": "0"}


def _columns(rows_or_columns):
    if not rows_or_columns:
        return []
    if isinstance(rows_or_columns[0], str):
        names = rows_or_columns
    else:
        names = list(rows_or_columns[0].keys())
    return [{"name": c, "id": c} for c in names]


def _table(dash_table, table_id, rows=None, page_size=PAGE_SIZE, columns=None, **extra):
    rows = rows or []
    style_cell = {
        "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
        "fontSize": 12,
        "padding": "6px 8px",
        "textAlign": "left",
        "minWidth": "90px",
        "maxWidth": "320px",
        "overflow": "hidden",
        "textOverflow": "ellipsis",
    }
    style_cell.update(extra.pop("style_cell", {}))
    return dash_table.DataTable(
        id=table_id,
        columns=columns if columns is not None else _columns(rows),
        data=rows[:page_size],
        page_size=page_size,
        sort_action=extra.pop("sort_action", "native"),
        filter_action=extra.pop("filter_action", "native"),
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell=style_cell,
        style_header={"fontWeight": 600, "background": "#f6f7f9"},
        **extra,
    )


def _yield_sort_key(r):
    st = str(r.get("student_type", "")).strip()
    is_pass = 0 if st == "1" else 1
    try:
        avg = float(r.get("avg") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    return (is_pass, -avg)


def _yield_columns(sources):
    cols = [
        {"name": "student_type", "id": "student_type"},
        {"name": "count", "id": "count", "type": "numeric"},
    ]
    for src in sources or []:
        cols.append({"name": str(src), "id": f"portion_{src}", "type": "numeric"})
    cols.append({"name": "avg", "id": "avg", "type": "numeric"})
    cols.append({"name": "Main Fail subject", "id": "Main Fail subject"})
    cols.append({"name": "comment", "id": "comment", "editable": True})
    return cols


def _yield_style(sources):
    narrow_widths = {
        "student_type": "78px",
        "count": "60px",
        "avg": "82px",
    }
    rules = []
    for col, w in narrow_widths.items():
        rules.append({
            "if": {"column_id": col},
            "width": w,
            "minWidth": w,
            "maxWidth": w,
            "textAlign": "center",
        })
    for src in sources or []:
        rules.append({
            "if": {"column_id": f"portion_{src}"},
            "width": "64px",
            "minWidth": "64px",
            "maxWidth": "64px",
            "textAlign": "center",
        })
    rules.append({
        "if": {"column_id": "avg"},
        "backgroundColor": "#eef4fb",
        "fontWeight": "600",
    })
    rules.append({
        "if": {"column_id": "Main Fail subject"},
        "width": "180px",
        "minWidth": "150px",
        "maxWidth": "220px",
    })
    rules.append({
        "if": {"column_id": "comment"},
        "width": "260px",
        "minWidth": "180px",
        "maxWidth": "400px",
        "backgroundColor": "#fffdf3",
    })
    return rules


def _cpk_style():
    # Widths tuned so total ≈ 1090px — fits most 1200px+ viewports without horizontal scroll
    # subject(150) + lo(56) + hi(56) + unit(46) + source(82)
    # + min(56) + median(56) + max(56) + avg(60)
    # + stdev(52) + cpl(52) + cpu(52) + cp(52) + cpk(52)
    # + comment(200) = ~1088px
    metric_cols = ["stdev", "cp", "cpl", "cpu", "cpk"]
    limit_cols  = ["lo_limit", "hi_limit"]
    stat_cols   = ["min", "median", "max"]
    return [
        {"if": {"column_id": col}, "width": "52px", "minWidth": "46px", "maxWidth": "72px", "textAlign": "right"}
        for col in metric_cols
    ] + [
        {"if": {"column_id": col}, "width": "56px", "minWidth": "48px", "maxWidth": "80px", "textAlign": "right"}
        for col in limit_cols
    ] + [
        {"if": {"column_id": col}, "width": "56px", "minWidth": "48px", "maxWidth": "80px", "textAlign": "right"}
        for col in stat_cols
    ] + [
        {"if": {"column_id": "average"}, "width": "60px", "minWidth": "52px", "maxWidth": "80px", "textAlign": "right"},
        {"if": {"column_id": "unit"},    "width": "46px", "minWidth": "40px", "maxWidth": "68px", "textAlign": "center"},
        {"if": {"column_id": "subject"}, "width": "150px", "minWidth": "120px", "maxWidth": "220px"},
        {"if": {"column_id": "source"},  "width": "82px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "center"},
        {"if": {"column_id": "comment"}, "width": "200px", "minWidth": "140px", "maxWidth": "360px",
         "backgroundColor": "#fffdf3", "textAlign": "left"},
    ]


def _cpk_data_style():
    return [
        {
            "if": {"filter_query": '{subject} != ""'},
            "borderTop": "2px solid #b8c4d4",
        },
        {
            "if": {"filter_query": "{source} = total"},
            "backgroundColor": "#eef4fb",
            "fontWeight": "600",
        },
        {
            "if": {"filter_query": "{cpk} < 1.33 && {cpk} != 'N/A'", "column_id": "cpk"},
            "backgroundColor": "#fff3bf",
            "color": "#5c4400",
            "fontWeight": "650",
        },
    ]


def _cpk_columns():
    spec = [
        ("subject", "subject"),
        ("lo", "lo_limit"),
        ("hi", "hi_limit"),
        ("units", "unit"),
        ("source", "source"),
        ("min", "min"),
        ("median", "median"),
        ("max", "max"),
        ("average", "average"),
        ("stdev", "stdev"),
        ("cpl", "cpl"),
        ("cpu", "cpu"),
        ("cp", "cp"),
        ("cpk", "cpk"),
    ]
    cols = [{"name": name, "id": col_id} for name, col_id in spec]
    cols.append({"name": "comment", "id": "comment", "editable": True})
    return cols


def _merge_cpk_subject(rows):
    merged = []
    prev = None
    for row in rows:
        row = dict(row)
        cur = row.get("subject")
        if cur == prev:
            row["subject"] = ""
            row["lo_limit"] = ""
            row["hi_limit"] = ""
            row["unit"] = ""
        else:
            prev = cur
        merged.append(row)
    return merged


def _load_small_tables(dataset_id):
    return {
        "meta": read_table_json(dataset_id, "meta") or {},
        "yield": read_table_json(dataset_id, "yield") or [],
        "cpk": read_table_json(dataset_id, "cpk") or [],
        "fail_items": read_table_json(dataset_id, "fail_items") or {"rows": []},
    }


def _read_yield_comments(dataset_id):
    path = DATASETS_DIR / dataset_id / "tables" / "yield_comments.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_yield_comments(dataset_id, comments):
    path = DATASETS_DIR / dataset_id / "tables" / "yield_comments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comments, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _read_summary_comments(dataset_id):
    path = DATASETS_DIR / dataset_id / "tables" / "summary_yield_comments.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_summary_comments(dataset_id, comments):
    path = DATASETS_DIR / dataset_id / "tables" / "summary_yield_comments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comments, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _read_summary_eval(dataset_id):
    path = DATASETS_DIR / dataset_id / "tables" / "summary_eval.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_summary_eval(dataset_id, data):
    path = DATASETS_DIR / dataset_id / "tables" / "summary_eval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _read_cpk_comments(dataset_id):
    path = DATASETS_DIR / dataset_id / "tables" / "cpk_comments.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cpk_comments(dataset_id, comments):
    path = DATASETS_DIR / dataset_id / "tables" / "cpk_comments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comments, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _cpk_comment_key(subject, source):
    return f"{(subject or '').strip()}|{(source or '').strip()}"


def _issue_columns(sources):
    cols = [
        {"name": "student_type", "id": "student_type"},
        {"name": "subject", "id": "subject"},
        {"name": "average", "id": "avg", "type": "numeric"},
    ]
    for src in sources or []:
        cols.append({"name": str(src), "id": f"portion_{src}", "type": "numeric"})
    cols.append({"name": "Distribution", "id": "distribution", "presentation": "markdown"})
    cols.append({"name": "Issue Point", "id": "issue_point", "editable": True})
    cols.append({"name": "Comment", "id": "issue_comment", "editable": True})
    cols.append({"name": "개발팀 1차 Comment", "id": "dev_comment", "editable": True})
    cols.append({"name": "PTE 1차 comment", "id": "pte_comment", "editable": True})
    return cols


def _issue_style(sources):
    rules = [
        {"if": {"column_id": "student_type"}, "width": "90px", "minWidth": "90px", "maxWidth": "90px", "textAlign": "center"},
        {"if": {"column_id": "subject"}, "width": "180px", "minWidth": "150px", "maxWidth": "220px"},
        {"if": {"column_id": "avg"}, "width": "82px", "minWidth": "82px", "maxWidth": "82px", "textAlign": "center"},
    ]
    for src in sources or []:
        rules.append({
            "if": {"column_id": f"portion_{src}"},
            "width": "82px",
            "minWidth": "60px",
            "maxWidth": "140px",
            "textAlign": "center",
        })
    rules.append({
        "if": {"column_id": "distribution"},
        "width": "200px",
        "minWidth": "160px",
        "maxWidth": "260px",
        "textAlign": "center",
    })
    for cid in ("issue_point", "issue_comment", "dev_comment", "pte_comment"):
        rules.append({
            "if": {"column_id": cid},
            "width": "220px",
            "minWidth": "180px",
            "maxWidth": "360px",
            "textAlign": "left",
        })
    return rules


def _issue_data_style():
    return [
        {"if": {"column_id": "avg"}, "backgroundColor": "#eef4fb", "fontWeight": "600"},
        {"if": {"column_id": "issue_point"}, "backgroundColor": "#fffdf3"},
        {"if": {"column_id": "issue_comment"}, "backgroundColor": "#fffdf3"},
        {"if": {"column_id": "dev_comment"}, "backgroundColor": "#fffdf3"},
        {"if": {"column_id": "pte_comment"}, "backgroundColor": "#fffdf3"},
    ]


def _read_issue_comments(dataset_id):
    path = DATASETS_DIR / dataset_id / "tables" / "issue_comments.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_issue_comments(dataset_id, comments):
    path = DATASETS_DIR / dataset_id / "tables" / "issue_comments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comments, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _project_issue_rows(fail_items, sources, comments, dataset_id):
    rows = []
    pass_type = "1"
    for r in (fail_items or {}).get("rows", []) or []:
        st = str(r.get("student_type", "")).strip()
        fail_subjects = r.get("fail_subjects") or []
        if st == pass_type:
            subject = "Pass"
            distribution = "Pass"
        elif fail_subjects:
            top = fail_subjects[0]
            subject = top.get("subject", "N/A")
            sid = top.get("subject_id")
            distribution = f"![](/api/{dataset_id}/thumb/{sid})" if sid is not None else "N/A"
        else:
            subject = "N/A"
            distribution = "N/A"
        saved = comments.get(st) or {}
        if not isinstance(saved, dict):
            saved = {}
        row = {
            "student_type": st,
            "subject": subject,
            "avg": r.get("avg"),
            "distribution": distribution,
            "issue_point": saved.get("issue_point", ""),
            "issue_comment": saved.get("comment", ""),
            "dev_comment": saved.get("dev_comment", ""),
            "pte_comment": saved.get("pte_comment", ""),
        }
        for src in sources or []:
            row[f"portion_{src}"] = r.get(f"portion_{src}")
        rows.append(row)
    return rows


def _fail_item_row(html, dataset_id, row):
    subjects = row.get("fail_subjects") or []
    if not subjects:
        subject_content = html.Span(row.get("Fail Subjects", "Pass"), className="pass-label")
    else:
        subject_content = html.Div([
            html.Div([
                html.Div(f"{item['subject']} {item['count']}ea", className="subject-meta"),
                html.Img(src=f"/api/{dataset_id}/thumb/{item['subject_id']}"),
            ], className="subject-card", title=item["subject"])
            for item in subjects
        ], className="subject-strip")
    return html.Div([
        html.Div(row.get("student_type", ""), className="fail-cell type"),
        html.Div(row.get("count", ""), className="fail-cell count"),
        html.Div(row.get("portion (%)", ""), className="fail-cell portion"),
        html.Div(row.get("Main Fail subject", ""), className="fail-cell main"),
        html.Div(subject_content, className="fail-cell subjects"),
    ], className="fail-row")


def _build_low_cpk_groups(cpk_rows, subjects_meta):
    name_to_id = {s["subject"]: s["subject_id"] for s in (subjects_meta or [])}
    grouped = {}
    order = []
    for r in cpk_rows or []:
        if r.get("source") == "total":
            continue
        try:
            cpk_val = float(r.get("cpk"))
        except (TypeError, ValueError):
            continue
        if cpk_val > 1.0:
            continue
        subject = r.get("subject") or ""
        if subject not in grouped:
            grouped[subject] = []
            order.append(subject)
        grouped[subject].append({
            "source": r.get("source", ""),
            "cpk": r.get("cpk"),
            "cpk_value": cpk_val,
        })
    out = []
    for subject in order:
        items = sorted(grouped[subject], key=lambda x: x["cpk_value"])
        out.append({
            "subject": subject,
            "subject_id": name_to_id.get(subject),
            "items": items,
            "min_cpk": items[0]["cpk_value"],
        })
    out.sort(key=lambda x: x["min_cpk"])
    return out


def _low_cpk_row(html, dataset_id, group):
    sid = group.get("subject_id")
    cards = []
    for it in group["items"]:
        thumb = (
            html.Img(src=f"/api/{dataset_id}/thumb/{sid}")
            if sid is not None
            else html.Span("—", className="pass-label")
        )
        cards.append(html.Div([
            html.Div(f"{it['source']} · {it['cpk']}", className="low-cpk-meta"),
            thumb,
        ], className="low-cpk-card", title=f"{it['source']} (cpk {it['cpk']})"))
    subject_label = html.Div([
        html.Div(group["subject"], className="low-cpk-subject-name"),
        html.Div(f"min cpk {group['items'][0]['cpk']} · {len(group['items'])} sheet(s)", className="low-cpk-subject-sub"),
    ], className="fail-cell low-cpk-subject")
    return html.Div([
        subject_label,
        html.Div(cards, className="fail-cell low-cpk-strip"),
    ], className="fail-row")


def register_dash(app):
    Dash, Input, Output, State, dcc, html, dash_table = _dash_imports()
    dash_app = Dash(
        __name__,
        server=app,
        url_base_pathname="/dash/",
        suppress_callback_exceptions=True,
        title="Plotly Data Dashboard",
    )

    dash_app.layout = html.Div([
        dcc.Location(id="url"),
        dcc.Store(id="dataset-id"),
        dcc.Store(id="summary-store"),
        html.Div(id="page"),
    ])

    @dash_app.callback(
        Output("dataset-id", "data"),
        Output("summary-store", "data"),
        Output("page", "children"),
        Input("url", "pathname"),
    )
    def render(pathname):
        dataset_id = (pathname or "").strip("/").split("/")[-1] or "current"
        tables = _load_small_tables(dataset_id)
        if not (DATASETS_DIR / dataset_id).exists():
            return dataset_id, {}, html.Div(f"Dataset not found: {dataset_id}", className="error")
        meta = tables["meta"]
        return dataset_id, tables, html.Div([
            html.Div([
                html.H1("Plotly Data Dashboard"),
                html.Div(
                    f"dataset: {dataset_id} | rows: {meta.get('row_count', 0)} | subjects: {len(meta.get('subjects', []))}",
                    className="meta",
                ),
                html.A("Open distribution full page", href=f"/view/{dataset_id}", target="_blank", className="link"),
                html.Button("Download Raw XLSX", id="download-xlsx-btn", n_clicks=0, className="download-btn"),
                html.Span(id="download-status", className="download-status"),
                html.Button("Download Report XLSX", id="download-report-btn", n_clicks=0, className="download-btn download-btn-report"),
                html.Span(id="download-report-status", className="download-status"),
            ], className="topbar"),
            dcc.Tabs(
                id="tabs",
                value="summary",
                className="main-tabs",
                parent_style=TABS_PARENT_STYLE,
                content_style={"display": "none"},
                children=[
                    dcc.Tab(label="Summary", value="summary", style=TAB_STYLE, selected_style=TAB_SELECTED_STYLE),
                    dcc.Tab(label="Yield", value="yield", style=TAB_STYLE, selected_style=TAB_SELECTED_STYLE),
                    dcc.Tab(label="CPK", value="cpk", style=TAB_STYLE, selected_style=TAB_SELECTED_STYLE),
                    dcc.Tab(label="Fail Item", value="fail", style=TAB_STYLE, selected_style=TAB_SELECTED_STYLE),
                    dcc.Tab(label="Issue Table", value="issues", style=TAB_STYLE, selected_style=TAB_SELECTED_STYLE),
                    dcc.Tab(label="Distribution", value="distribution", style=TAB_STYLE, selected_style=TAB_SELECTED_STYLE),
                ],
            ),
            html.Div(id="tab-content", className="content"),
        ], className="dash-root")

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"),
        State("dataset-id", "data"),
        State("summary-store", "data"),
    )
    def render_tab(tab, dataset_id, tables):
        tables = tables or _load_small_tables(dataset_id)
        if tab == "summary":
            meta = tables.get("meta") or {}
            yield_rows = tables.get("yield") or []
            fail_items_rows = (tables.get("fail_items") or {}).get("rows", [])
            sources = meta.get("sources") or []
            subjects = meta.get("subjects") or []

            pass_row = next((r for r in yield_rows if str(r.get("student_type", "")) == "1"), {})
            avg_val = pass_row.get("avg")
            pass_yield_str = f"{avg_val:.2f}%" if avg_val is not None else "-"
            non_pass = [r for r in fail_items_rows if str(r.get("student_type", "")) != "1"]

            feature_row = {
                "dataset": dataset_id,
                "total_dut": meta.get("row_count", "-"),
                "pass_count": pass_row.get("count", "-"),
                "fail_types": len(non_pass),
                "sources": len(sources),
                "subjects": len(subjects),
            }

            smry_comments = _read_summary_comments(dataset_id)
            yield_summary_rows = []
            for i, r in enumerate(non_pass[:5], 1):
                st = str(r.get("student_type", ""))
                fail_subjects = r.get("fail_subjects") or []
                main_fail = fail_subjects[0].get("subject", "N/A") if fail_subjects else "N/A"
                avg_r = r.get("avg")
                fail_ratio = f"{avg_r:.2f}%" if avg_r is not None else "-"
                yield_summary_rows.append({
                    "rank": i,
                    "student_type": st,
                    "main_fail_subject": main_fail,
                    "fail_ratio": fail_ratio,
                    "comment": smry_comments.get(st, ""),
                })

            eval_data = _read_summary_eval(dataset_id)
            eval_rows = [
                {"category": "Yield",  "result": eval_data.get("yield",  "")},
                {"category": "CPK",    "result": eval_data.get("cpk",    "")},
                {"category": "Temp",   "result": eval_data.get("temp",   "")},
                {"category": "ETC",    "result": eval_data.get("etc",    "")},
            ]

            _hdr = {"fontWeight": 600, "background": "#f6f7f9", "fontSize": 11,
                    "padding": "4px 8px", "textAlign": "center"}
            _cell = {
                "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                "fontSize": 12, "padding": "6px 10px",
            }

            return html.Div([
                html.Div("Feature", className="section-title"),
                dash_table.DataTable(
                    id="summary-feature-table",
                    columns=[
                        {"name": "Dataset ID",   "id": "dataset"},
                        {"name": "Total DUT",    "id": "total_dut"},
                        {"name": "Pass (type 1)","id": "pass_count"},
                        {"name": "Fail Types",   "id": "fail_types"},
                        {"name": "Sources",      "id": "sources"},
                        {"name": "Subjects",     "id": "subjects"},
                    ],
                    data=[feature_row],
                    editable=False,
                    sort_action="none",
                    filter_action="none",
                    style_table={"overflowX": "auto", "marginBottom": "24px"},
                    style_cell={**_cell, "textAlign": "center"},
                    style_header=_hdr,
                ),

                html.Div("Yield Summary", className="section-title small"),
                html.Div(
                    f"Overall Pass Yield (student_type 1): {pass_yield_str}",
                    className="summary-yield-avg",
                ),
                html.Div("Major Fail Bins (top 5)", className="summary-sub-title"),
                dash_table.DataTable(
                    id="summary-yield-table",
                    columns=[
                        {"name": "Rank",              "id": "rank"},
                        {"name": "Fail Type",         "id": "student_type"},
                        {"name": "Main Fail Subject", "id": "main_fail_subject"},
                        {"name": "Fail Ratio",        "id": "fail_ratio"},
                        {"name": "Comment",           "id": "comment", "editable": True},
                    ],
                    data=yield_summary_rows,
                    editable=False,
                    sort_action="none",
                    filter_action="none",
                    style_table={"overflowX": "auto", "marginBottom": "8px"},
                    style_cell={**_cell, "textAlign": "left"},
                    style_cell_conditional=[
                        {"if": {"column_id": c}, "textAlign": "center", "width": w}
                        for c, w in [("rank","48px"),("student_type","80px"),("fail_ratio","90px")]
                    ] + [
                        {"if": {"column_id": "main_fail_subject"}, "width": "260px"},
                        {"if": {"column_id": "comment"}, "width": "320px",
                         "backgroundColor": "#fffdf3"},
                    ],
                    style_header=_hdr,
                ),
                html.Div(id="summary-yield-save-status", className="save-status"),

                html.Div("Evaluation Summary", className="section-title small"),
                dash_table.DataTable(
                    id="summary-eval-table",
                    columns=[
                        {"name": "Category", "id": "category"},
                        {"name": "Result",   "id": "result", "editable": True},
                    ],
                    data=eval_rows,
                    editable=False,
                    sort_action="none",
                    filter_action="none",
                    style_table={"maxWidth": "640px", "marginBottom": "8px"},
                    style_cell={**_cell, "textAlign": "left"},
                    style_cell_conditional=[
                        {"if": {"column_id": "category"},
                         "width": "100px", "fontWeight": 600,
                         "backgroundColor": "#f6f7f9", "textAlign": "center"},
                        {"if": {"column_id": "result"},
                         "width": "520px", "backgroundColor": "#fffdf3"},
                    ],
                    style_header=_hdr,
                ),
                html.Div(id="summary-eval-save-status", className="save-status"),
            ], className="summary-tab-content")
        if tab == "yield":
            rows = tables.get("yield") or []
            sources = (tables.get("meta") or {}).get("sources") or []
            comments = _read_yield_comments(dataset_id)
            merged = []
            for row in rows:
                row = dict(row)
                key = str(row.get("student_type", ""))
                row["comment"] = comments.get(key, row.get("comment", "") or "")
                merged.append(row)

            merged.sort(key=_yield_sort_key)

            return html.Div([
                html.Div("Yield", className="section-title"),
                dash_table.DataTable(
                    id="yield-table",
                    columns=_yield_columns(sources),
                    data=merged,
                    page_size=50,
                    sort_action="none",
                    filter_action="none",
                    editable=False,
                    style_table={"overflowX": "auto", "minWidth": "100%"},
                    style_cell={
                        "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                        "fontSize": 12,
                        "padding": "6px 8px",
                        "textAlign": "left",
                        "minWidth": "60px",
                        "maxWidth": "400px",
                        "overflow": "hidden",
                        "textOverflow": "ellipsis",
                    },
                    style_cell_conditional=_yield_style(sources),
                    style_header={
                        "fontWeight": 600,
                        "background": "#f6f7f9",
                        "fontSize": 10,
                        "whiteSpace": "normal",
                        "height": "auto",
                        "wordBreak": "break-word",
                        "padding": "2px 4px",
                        "lineHeight": "1.15",
                    },
                ),
                html.Div(id="yield-save-status", className="save-status"),
            ])
        if tab == "cpk":
            raw_cpk = tables.get("cpk") or []
            cpk_comments = _read_cpk_comments(dataset_id)
            for r in raw_cpk:
                r["comment"] = cpk_comments.get(_cpk_comment_key(r.get("subject"), r.get("source")), "")
            rows = _merge_cpk_subject(raw_cpk)
            return html.Div([
                html.Div("CPK", className="section-title"),
                html.Div([
                    dcc.Input(
                        id="cpk-subject-search",
                        type="text",
                        placeholder="Search subject (Enter to jump)",
                        debounce=True,
                        autoComplete="off",
                        className="cpk-search-input",
                    ),
                    html.Span(id="cpk-search-status", className="cpk-search-status"),
                    html.Span(id="cpk-save-status", className="save-status"),
                    html.Div([
                        html.Button("◀", id="cpk-prev", n_clicks=0, className="cpk-page-btn"),
                        html.Span(id="cpk-page-indicator", className="cpk-page-indicator", children="1 / 1"),
                        html.Button("▶", id="cpk-next", n_clicks=0, className="cpk-page-btn"),
                    ], className="cpk-pager"),
                ], className="cpk-search-bar"),
                html.Div(
                    dash_table.DataTable(
                        id="cpk-table",
                        columns=_cpk_columns(),
                        data=rows,
                        page_size=200,
                        sort_action="none",
                        filter_action="none",
                        editable=False,
                        fixed_rows={"headers": True},
                        style_table={"overflowX": "auto", "minWidth": "100%", "height": "calc(100vh - 200px)"},
                        style_cell={
                            "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                            "fontSize": 12,
                            "padding": "4px 6px",
                            "textAlign": "left",
                            "minWidth": "46px",
                            "maxWidth": "220px",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                        },
                        style_cell_conditional=_cpk_style(),
                        style_data_conditional=_cpk_data_style(),
                        style_header={"fontWeight": 600, "background": "#f6f7f9"},
                    ),
                    className="cpk-table-wrap",
                ),
            ])
        if tab == "fail":
            fail_items = tables.get("fail_items") or {"rows": []}
            rows = fail_items.get("rows", [])

            # ── Fail Values: per-student per-subject fail records ──────────────
            try:
                fv_rows = get_fail_values(dataset_id)
            except Exception:
                fv_rows = []

            fv_columns = [
                {"name": "Source (Sheet)", "id": "source"},
                {"name": "Call",           "id": "call"},
                {"name": "Grade",          "id": "grade"},
                {"name": "Class",          "id": "class"},
                {"name": "Type",           "id": "student_type"},
                {"name": "Subject",        "id": "subject"},
                {"name": "Value",          "id": "value",    "type": "numeric"},
                {"name": "Lo Limit",       "id": "lo_limit", "type": "numeric"},
                {"name": "Hi Limit",       "id": "hi_limit", "type": "numeric"},
                {"name": "Fail",           "id": "fail"},
            ]
            fv_col_style = [
                {"if": {"column_id": "source"},       "width": "140px", "minWidth": "110px", "maxWidth": "200px"},
                {"if": {"column_id": "call"},         "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "grade"},        "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "class"},        "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "student_type"}, "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "subject"},      "width": "220px", "minWidth": "160px", "maxWidth": "300px"},
                {"if": {"column_id": "value"},        "width": "90px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "right"},
                {"if": {"column_id": "lo_limit"},     "width": "90px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "right"},
                {"if": {"column_id": "hi_limit"},     "width": "90px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "right"},
                {"if": {"column_id": "fail"},         "width": "68px",  "minWidth": "58px",  "maxWidth": "90px",  "textAlign": "center", "fontWeight": "600"},
            ]
            fv_data_style = [
                {
                    "if": {"filter_query": '{fail} = "< lo"', "column_id": "fail"},
                    "backgroundColor": "#DBEAFE", "color": "#1E40AF",
                },
                {
                    "if": {"filter_query": '{fail} = "> hi"', "column_id": "fail"},
                    "backgroundColor": "#FEE2E2", "color": "#991B1B",
                },
                {
                    "if": {"filter_query": '{fail} = "< lo"', "column_id": "value"},
                    "color": "#1E40AF", "fontWeight": "600",
                },
                {
                    "if": {"filter_query": '{fail} = "> hi"', "column_id": "value"},
                    "color": "#991B1B", "fontWeight": "600",
                },
            ]

            return html.Div([
                html.Div("Fail Item", className="section-title"),
                html.Div("student_type != 1 rows use the same yield counts, with subject thumbnails sorted by portion.", className="table-note"),
                html.Div(
                    html.Div([
                        html.Div([
                            html.Div("student_type", className="fail-cell head type"),
                            html.Div("count", className="fail-cell head count"),
                            html.Div("portion (%)", className="fail-cell head portion"),
                            html.Div("Main Fail subject", className="fail-cell head main"),
                            html.Div("Fail Subjects", className="fail-cell head subjects"),
                        ], className="fail-row header"),
                        *[_fail_item_row(html, dataset_id, row) for row in rows],
                    ], className="fail-table"),
                    className="fail-table-scroll",
                ),

                # ── Fail Values ────────────────────────────────────────────────
                html.Div("Fail Values", className="section-title small", style={"marginTop": "32px"}),
                html.Div(
                    f"student_type ≠ 1 인 모든 학생의 개별 fail 기록 — "
                    f"총 {len(fv_rows):,}건 (subject별, source별 분리). "
                    "첫 로드 시 계산 후 캐시됩니다.",
                    className="table-note",
                ),
                dcc.Loading(
                    type="circle",
                    children=dash_table.DataTable(
                        id="fail-values-table",
                        columns=fv_columns,
                        data=fv_rows,
                        page_size=50,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto", "minWidth": "100%"},
                        style_cell={
                            "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                            "fontSize": 12,
                            "padding": "5px 8px",
                            "textAlign": "left",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                        },
                        style_cell_conditional=fv_col_style,
                        style_data_conditional=fv_data_style,
                        style_header={"fontWeight": 600, "background": "#f6f7f9", "fontSize": 11},
                    ),
                ),
            ])
        if tab == "issues":
            fail_items = tables.get("fail_items") or {"rows": []}
            sources = (tables.get("meta") or {}).get("sources") or []
            issue_comments = _read_issue_comments(dataset_id)
            rows = _project_issue_rows(fail_items, sources, issue_comments, dataset_id)
            rows.sort(key=_yield_sort_key)
            low_cpk_groups = _build_low_cpk_groups(
                tables.get("cpk") or [],
                (tables.get("meta") or {}).get("subjects") or [],
            )
            return html.Div([
                html.Div("Yield", className="section-title"),
                html.Div(
                    "Most-failed subject per student_type (ties broken by count, then alphabetical). Issue Point and Comment fields are editable and auto-saved.",
                    className="table-note",
                ),
                html.Div(
                    html.Div(className="issue-top-scroll-inner"),
                    id="issue-top-scroll",
                    className="issue-top-scroll",
                ),
                dash_table.DataTable(
                    id="issue-table",
                    columns=_issue_columns(sources),
                    data=rows,
                    page_size=200,
                    sort_action="none",
                    filter_action="none",
                    editable=False,
                    fixed_columns={"headers": True, "data": 1},
                    fixed_rows={"headers": True},
                    markdown_options={"html": False},
                    style_table={"overflowX": "auto", "minWidth": "100%"},
                    style_cell={
                        "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                        "fontSize": 12,
                        "padding": "6px 8px",
                        "textAlign": "left",
                        "minWidth": "70px",
                        "maxWidth": "360px",
                        "height": "120px",
                        "whiteSpace": "normal",
                        "overflow": "hidden",
                        "textOverflow": "ellipsis",
                    },
                    style_cell_conditional=_issue_style(sources),
                    style_data_conditional=_issue_data_style(),
                    style_header={
                        "fontWeight": 600,
                        "background": "#f6f7f9",
                        "height": "18px",
                        "lineHeight": "11px",
                        "padding": "3px 6px",
                        "whiteSpace": "nowrap",
                    },
                ),
                html.Div(id="issue-save-status", className="save-status"),
                html.Details([
                    html.Summary("Low cpk", className="section-title collapsible-summary"),
                    html.Div("Subjects with any source CPK ≤ 1.0; sheets shown side-by-side, sorted by lowest CPK.", className="table-note"),
                    html.Div(
                        html.Div([
                            html.Div([
                                html.Div("subject", className="fail-cell head low-cpk-subject"),
                                html.Div("sheets (cpk · thumbnail)", className="fail-cell head low-cpk-strip"),
                            ], className="fail-row header"),
                            *[_low_cpk_row(html, dataset_id, g) for g in low_cpk_groups],
                        ], className="fail-table low-cpk-table"),
                        className="fail-table-scroll",
                    ),
                ], open=True, className="low-cpk-details"),
            ], className="issue-table-wrap")
        return html.Div([
            html.Iframe(src=f"/view/{dataset_id}", className="distribution-frame"),
        ], className="distribution-tab")

    @dash_app.callback(
        Output("summary-yield-save-status", "children"),
        Input("summary-yield-table", "data_timestamp"),
        State("summary-yield-table", "data"),
        State("dataset-id", "data"),
        prevent_initial_call=True,
    )
    def save_summary_yield_comments(_ts, data, dataset_id):
        if not dataset_id or not data:
            return ""
        payload = {}
        for row in data:
            key = str(row.get("student_type", "")).strip()
            comment = (row.get("comment") or "").strip()
            if key and comment:
                payload[key] = comment
        _write_summary_comments(dataset_id, payload)
        return f"saved {len(payload)} comment(s)"

    @dash_app.callback(
        Output("summary-eval-save-status", "children"),
        Input("summary-eval-table", "data_timestamp"),
        State("summary-eval-table", "data"),
        State("dataset-id", "data"),
        prevent_initial_call=True,
    )
    def save_summary_eval(_ts, data, dataset_id):
        if not dataset_id or not data:
            return ""
        payload = {}
        for row in data:
            cat = (row.get("category") or "").lower()
            result = (row.get("result") or "").strip()
            if cat:
                payload[cat] = result
        _write_summary_eval(dataset_id, payload)
        return "saved"

    @dash_app.callback(
        Output("yield-save-status", "children"),
        Input("yield-table", "data_timestamp"),
        State("yield-table", "data"),
        State("dataset-id", "data"),
        prevent_initial_call=True,
    )
    def save_yield_comments(_ts, data, dataset_id):
        if not dataset_id or not data:
            return ""
        payload = {}
        for row in data:
            key = str(row.get("student_type", "")).strip()
            comment = (row.get("comment") or "").strip()
            if key and comment:
                payload[key] = comment
        _write_yield_comments(dataset_id, payload)
        return f"saved {len(payload)} comment(s)"

    @dash_app.callback(
        Output("cpk-save-status", "children"),
        Input("cpk-table", "data_timestamp"),
        State("cpk-table", "data"),
        State("dataset-id", "data"),
        prevent_initial_call=True,
    )
    def save_cpk_comments(_ts, data, dataset_id):
        if not dataset_id or not data:
            return ""
        payload = {}
        prev_subject = ""
        for row in data:
            s = (row.get("subject") or "").strip()
            if s:
                prev_subject = s
            subject = prev_subject
            source = (row.get("source") or "").strip()
            comment = (row.get("comment") or "").strip()
            if subject and source and comment:
                payload[_cpk_comment_key(subject, source)] = comment
        _write_cpk_comments(dataset_id, payload)
        return f"saved {len(payload)} comment(s)"

    @dash_app.callback(
        Output("issue-save-status", "children"),
        Input("issue-table", "data_timestamp"),
        State("issue-table", "data"),
        State("dataset-id", "data"),
        prevent_initial_call=True,
    )
    def save_issue_comments(_ts, data, dataset_id):
        if not dataset_id or not data:
            return ""
        payload = {}
        for row in data:
            key = str(row.get("student_type", "")).strip()
            if not key:
                continue
            entry = {
                "issue_point": (row.get("issue_point") or "").strip(),
                "comment": (row.get("issue_comment") or "").strip(),
                "dev_comment": (row.get("dev_comment") or "").strip(),
                "pte_comment": (row.get("pte_comment") or "").strip(),
            }
            if any(entry.values()):
                payload[key] = entry
        _write_issue_comments(dataset_id, payload)
        return f"saved {len(payload)} row(s)"

    dash_app.clientside_callback(
        """
        function(tab) {
            if (tab !== 'issues') return '';
            const init = (tries) => {
                const topScroll = document.getElementById('issue-top-scroll');
                const table = document.getElementById('issue-table');
                if (!topScroll || !table) {
                    if (tries > 0) setTimeout(() => init(tries - 1), 80);
                    return;
                }
                const inner = topScroll.querySelector('.issue-top-scroll-inner');
                if (!inner) return;
                const candidates = table.querySelectorAll('.dash-spreadsheet-container, .dash-spreadsheet-inner');
                let scrollable = null;
                for (const c of candidates) {
                    if (c.scrollWidth > c.clientWidth + 1) {
                        scrollable = c;
                        break;
                    }
                }
                if (!scrollable) {
                    if (tries > 0) setTimeout(() => init(tries - 1), 80);
                    return;
                }
                if (scrollable.dataset.topScrollBound === '1') {
                    inner.style.width = scrollable.scrollWidth + 'px';
                    return;
                }
                scrollable.dataset.topScrollBound = '1';
                const updateWidth = () => {
                    inner.style.width = scrollable.scrollWidth + 'px';
                };
                updateWidth();
                let syncing = false;
                topScroll.addEventListener('scroll', () => {
                    if (syncing) return;
                    syncing = true;
                    scrollable.scrollLeft = topScroll.scrollLeft;
                    requestAnimationFrame(() => { syncing = false; });
                });
                scrollable.addEventListener('scroll', () => {
                    if (syncing) return;
                    syncing = true;
                    topScroll.scrollLeft = scrollable.scrollLeft;
                    requestAnimationFrame(() => { syncing = false; });
                });
                if (window.ResizeObserver) {
                    new ResizeObserver(updateWidth).observe(scrollable);
                } else {
                    window.addEventListener('resize', updateWidth);
                }
            };
            setTimeout(() => init(15), 120);
            return '';
        }
        """,
        Output("issue-top-scroll", "title"),
        Input("tabs", "value"),
    )

    @dash_app.callback(
        Output("cpk-table", "page_current", allow_duplicate=True),
        Input("cpk-subject-search", "value"),
        State("cpk-table", "data"),
        State("cpk-table", "page_size"),
        prevent_initial_call=True,
    )
    def cpk_jump_page(subject, data, page_size):
        if not subject or not data:
            return 0
        q = subject.strip().lower()
        if not q:
            return 0
        page_size = page_size or 200
        for idx, row in enumerate(data):
            s = (row.get("subject") or "").strip()
            if s and q in s.lower():
                return idx // page_size
        return 0

    dash_app.clientside_callback(
        """
        function(subject, _page) {
            if (!subject) return '';
            const q = String(subject).trim().toLowerCase();
            if (!q) return '';
            const findAndScroll = (tries) => {
                const table = document.getElementById('cpk-table');
                if (!table) {
                    if (tries > 0) setTimeout(() => findAndScroll(tries - 1), 80);
                    return;
                }
                const rows = table.querySelectorAll('tbody tr');
                let target = null;
                let matchedName = '';
                for (const row of rows) {
                    const firstCell = row.querySelector('td');
                    if (!firstCell) continue;
                    const t = (firstCell.textContent || '').trim();
                    if (t && t.toLowerCase().includes(q)) {
                        target = row;
                        matchedName = t;
                        break;
                    }
                }
                if (target) {
                    document.querySelectorAll('.cpk-row-highlight').forEach(r => r.classList.remove('cpk-row-highlight'));
                    target.classList.add('cpk-row-highlight');
                    target.scrollIntoView({behavior: 'smooth', block: 'center'});
                    setTimeout(() => target.classList.remove('cpk-row-highlight'), 2800);
                    return 'jumped to ' + matchedName;
                }
                if (tries > 0) setTimeout(() => findAndScroll(tries - 1), 80);
                else return 'no match for "' + subject + '"';
            };
            setTimeout(() => findAndScroll(12), 100);
            return '';
        }
        """,
        Output("cpk-search-status", "children"),
        Input("cpk-subject-search", "value"),
        Input("cpk-table", "page_current"),
        prevent_initial_call=True,
    )

    dash_app.clientside_callback(
        """
        function(prev_clicks, next_clicks, current, page_size, data) {
            const ctx = dash_clientside.callback_context;
            if (!ctx || !ctx.triggered || !ctx.triggered.length) return dash_clientside.no_update;
            const id = ctx.triggered[0].prop_id.split('.')[0];
            const total = (data || []).length;
            const pages = Math.max(1, Math.ceil(total / (page_size || 200)));
            const cur = current || 0;
            if (id === 'cpk-prev') return Math.max(0, cur - 1);
            if (id === 'cpk-next') return Math.min(pages - 1, cur + 1);
            return dash_clientside.no_update;
        }
        """,
        Output("cpk-table", "page_current", allow_duplicate=True),
        Input("cpk-prev", "n_clicks"),
        Input("cpk-next", "n_clicks"),
        State("cpk-table", "page_current"),
        State("cpk-table", "page_size"),
        State("cpk-table", "data"),
        prevent_initial_call=True,
    )

    dash_app.clientside_callback(
        """
        function(current, data, page_size) {
            const total = (data || []).length;
            const pages = Math.max(1, Math.ceil(total / (page_size || 200)));
            return ((current || 0) + 1) + ' / ' + pages;
        }
        """,
        Output("cpk-page-indicator", "children"),
        Input("cpk-table", "page_current"),
        Input("cpk-table", "data"),
        State("cpk-table", "page_size"),
    )

    dash_app.clientside_callback(
        """
        async function(n_clicks, dataset_id) {
          if (!n_clicks || !dataset_id) return '';
          const filename = `${dataset_id}_raw.xlsx`;
          const url = `/api/${dataset_id}/raw_xlsx`;
          try {
            const resp = await fetch(url, { cache: 'no-store' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const blob = await resp.blob();
            if (window.showSaveFilePicker) {
              try {
                const handle = await window.showSaveFilePicker({
                  suggestedName: filename,
                  types: [{
                    description: 'Excel Workbook',
                    accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] }
                  }],
                });
                const writable = await handle.createWritable();
                await writable.write(blob);
                await writable.close();
                return `saved: ${handle.name}`;
              } catch (err) {
                if (err && err.name === 'AbortError') return 'cancelled';
                // fall through to anchor fallback
              }
            }
            const objUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = objUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(objUrl);
            return `downloaded: ${filename}`;
          } catch (err) {
            return 'error: ' + (err && err.message ? err.message : err);
          }
        }
        """,
        Output("download-status", "children"),
        Input("download-xlsx-btn", "n_clicks"),
        State("dataset-id", "data"),
    )

    dash_app.clientside_callback(
        """
        async function(n_clicks, dataset_id) {
          if (!n_clicks || !dataset_id) return '';
          const filename = `${dataset_id}_report.xlsx`;
          const url = `/api/${dataset_id}/report_xlsx`;
          try {
            const resp = await fetch(url, { cache: 'no-store' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const blob = await resp.blob();
            if (window.showSaveFilePicker) {
              try {
                const handle = await window.showSaveFilePicker({
                  suggestedName: filename,
                  types: [{
                    description: 'Excel Workbook',
                    accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] }
                  }],
                });
                const writable = await handle.createWritable();
                await writable.write(blob);
                await writable.close();
                return `saved: ${handle.name}`;
              } catch (err) {
                if (err && err.name === 'AbortError') return 'cancelled';
              }
            }
            const objUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = objUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(objUrl);
            return `downloaded: ${filename}`;
          } catch (err) {
            return 'error: ' + (err && err.message ? err.message : err);
          }
        }
        """,
        Output("download-report-status", "children"),
        Input("download-report-btn", "n_clicks"),
        State("dataset-id", "data"),
    )

    dash_app.index_string = """<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
      body { margin: 0; background: #fafafa; color: #222; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      .topbar { padding: 14px 18px; background: #fff; border-bottom: 1px solid #ddd; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
      .dash-root > .topbar { position: sticky; top: 0; z-index: 60; background: #fff; }
      .topbar h1 { font-size: 18px; margin: 0; }
      .meta, .table-note { font-size: 12px; color: #666; }
      .link { font-size: 12px; color: #2369b3; text-decoration: none; }
      .download-btn { font-size: 12px; padding: 5px 12px; border: 1px solid #2369b3; background: #f7fbff; color: #1f4d8c; border-radius: 4px; cursor: pointer; }
      .download-btn:hover { background: #eaf3fc; }
      .download-btn-report { border-color: #2d7d46; background: #f4fbf6; color: #1a4d2b; }
      .download-btn-report:hover { background: #e6f5eb; }
      .download-status { font-size: 11px; color: #555; min-height: 14px; }
      .save-status { font-size: 11px; color: #2d6b2d; margin-top: 6px; min-height: 14px; }
      .cpk-search-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
      .cpk-search-input { width: 320px; font-size: 12px; padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px; outline: none; transition: border-color 0.15s ease, background 0.15s ease; }
      .cpk-search-input:focus { border-color: #4a90e2; }
      .cpk-search-status { font-size: 11px; color: #2369b3; min-height: 14px; }
      .cpk-pager { display: flex; align-items: center; gap: 6px; margin-left: auto; }
      .cpk-page-btn { font-size: 12px; padding: 3px 10px; border: 1px solid #ccc; background: #fff; border-radius: 4px; cursor: pointer; line-height: 1; }
      .cpk-page-btn:hover { background: #f6f7f9; }
      .cpk-page-btn:active { background: #eaeef3; }
      .cpk-page-indicator { font-size: 12px; color: #444; min-width: 56px; text-align: center; }
      .cpk-table-wrap .previous-next-container { display: none !important; }
      .cpk-row-highlight td { animation: cpk-pulse 2.8s ease-out; }
      @keyframes cpk-pulse {
        0% { background-color: #ffe17a; }
        60% { background-color: #fff5b8; }
        100% { background-color: transparent; }
      }
      .main-tabs { position: sticky; top: 52px; z-index: 55; background: #fff; border-bottom: 1px solid #ddd; height: 44px; min-height: 0; }
      .main-tabs .tab-parent, .main-tabs .tab-container { height: 44px !important; min-height: 0 !important; }
      .main-tabs .tab { padding: 8px 14px !important; font-size: 13px !important; line-height: 1.2 !important; height: auto !important; min-height: 0 !important; }
      .main-tabs .tab--selected { padding: 8px 14px !important; font-size: 13px !important; line-height: 1.2 !important; height: auto !important; min-height: 0 !important; }
      .content { padding: 16px; }
      .section-title { font-size: 16px; font-weight: 650; margin: 0 0 12px; }
      .section-title.small { margin-top: 18px; font-size: 14px; }
      .fail-table-scroll { border: 1px solid #ddd; border-radius: 6px; overflow-y: auto; max-height: 65vh; }
      .fail-table { width: 100%; overflow: clip; background: #fff; }
      .fail-row { display: grid; grid-template-columns: 96px 88px 110px 180px minmax(360px, 1fr); border-top: 1px solid #eee; min-height: 92px; background: #fff; }
      .fail-row:first-child { border-top: none; }
      .fail-row.header { min-height: 27px; background: #f6f7f9; }
      .fail-table-scroll .fail-row.header { position: sticky; top: 0; z-index: 10; }
      .fail-cell { padding: 8px; font-size: 12px; border-left: 1px solid #eee; overflow: hidden; }
      .fail-cell:first-child { border-left: none; }
      .fail-cell.head { font-weight: 650; color: #333; display: flex; align-items: center; padding: 4px 8px; }
      .fail-cell.type, .fail-cell.count, .fail-cell.portion, .fail-cell.main { display: flex; align-items: center; }
      .subject-strip { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
      .subject-card { flex: 0 0 154px; border: 1px solid #ddd; border-radius: 5px; background: #fff; padding: 4px; }
      .subject-card img { display: block; width: 100%; aspect-ratio: 16 / 11; object-fit: contain; background: #fff; }
      .subject-meta { font-size: 10px; color: #666; margin-bottom: 3px; }
      .low-cpk-table .fail-row { grid-template-columns: 220px minmax(420px, 1fr); min-height: 84px; }
      .low-cpk-table .fail-row.header { min-height: 32px; }
      .low-cpk-subject { display: flex; flex-direction: column; justify-content: center; gap: 2px; }
      .low-cpk-subject-name { font-size: 12px; font-weight: 600; color: #222; word-break: break-word; }
      .low-cpk-subject-sub { font-size: 10px; color: #888; }
      .low-cpk-strip { display: flex; gap: 5px; overflow-x: auto; padding-bottom: 4px; align-items: stretch; }
      .low-cpk-card { flex: 0 0 88px; border: 1px solid #ddd; border-radius: 4px; background: #fff; padding: 3px; }
      .low-cpk-card img { display: block; width: 100%; aspect-ratio: 16 / 11; object-fit: contain; background: #fff; }
      .low-cpk-meta { font-size: 9px; color: #b04040; font-weight: 600; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .pass-label { color: #2d6b2d; font-weight: 650; }
      #issue-table img { max-width: 180px; max-height: 100px; display: block; margin: 0 auto; }
      #issue-table .dash-cell-value p { margin: 0; }
      .issue-table-wrap .previous-next-container { display: none !important; }
      .issue-top-scroll { overflow-x: auto; overflow-y: hidden; height: 14px; margin-bottom: 6px; background: #fafafa; border: 1px solid #e1e1e1; border-radius: 3px; }
      .issue-top-scroll-inner { height: 1px; min-height: 1px; }
      .low-cpk-details { margin-top: 18px; }
      .low-cpk-details > summary.collapsible-summary { cursor: pointer; list-style: none; user-select: none; display: flex; align-items: center; gap: 8px; margin: 0 0 12px; }
      .low-cpk-details > summary.collapsible-summary::-webkit-details-marker { display: none; }
      .low-cpk-details > summary.collapsible-summary::before { content: '▼'; font-size: 10px; color: #666; display: inline-block; width: 12px; }
      .low-cpk-details:not([open]) > summary.collapsible-summary::before { content: '▶'; }
      .low-cpk-details > summary.collapsible-summary:hover::before { color: #2369b3; }
      .image-strip { display: flex; gap: 12px; overflow-x: auto; padding: 12px 0 18px; align-items: flex-start; }
      .image-card { flex: 0 0 520px; background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 8px; }
      .image-card img { display: block; width: 100%; height: auto; min-height: 280px; object-fit: contain; }
      .image-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .content:has(.distribution-tab) { padding: 0; }
      .distribution-tab { height: calc(100vh - 96px); }
      .distribution-frame { width: 100%; height: 100%; border: none; background: #fff; display: block; }
      .error { padding: 32px; color: #a40000; }
      .summary-tab-content { max-width: 1100px; }
      .summary-yield-avg { font-size: 14px; font-weight: 600; color: #1f4d8c; margin: 8px 0 12px; }
      .summary-sub-title { font-size: 13px; font-weight: 600; color: #444; margin: 0 0 8px; }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>"""
    return dash_app


def send_fail_png(dataset_id, subject_id):
    if not (DATASETS_DIR / dataset_id).exists():
        abort(404)
    png_dir = DATASETS_DIR / dataset_id / "fail_pngs"
    png_dir.mkdir(parents=True, exist_ok=True)
    name = f"{int(subject_id)}.png"
    path = png_dir / name
    if not path.exists():
        _render_fail_png(dataset_id, int(subject_id), path)
    resp = send_from_directory(png_dir, name)
    resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
    return resp


def _render_fail_png(dataset_id, subject_id, out_path):
    try:
        import plotly.io as pio
    except ImportError:
        abort(503, "plotly is required for PNG export")
    chart_path = DATASETS_DIR / dataset_id / "charts" / f"{subject_id}.json"
    if not chart_path.exists():
        abort(404)
    try:
        payload = json.loads(chart_path.read_text(encoding="utf-8"))
        img = pio.to_image({"data": payload["data"], "layout": payload["layout"]}, format="png", width=800, height=550, scale=1)
    except Exception as exc:
        svg_path = DATASETS_DIR / dataset_id / "thumbs" / f"{subject_id}.svg"
        if svg_path.exists():
            svg_text = svg_path.read_text(encoding="utf-8")
            encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
            html = f"<html><body><img src='data:image/svg+xml;base64,{encoded}'></body></html>"
            abort(503, f"PNG export failed. Install kaleido. {exc}")
        abort(503, f"PNG export failed. Install kaleido. {exc}")
    Path(out_path).write_bytes(img)
