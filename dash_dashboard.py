import base64
import json
from pathlib import Path

from flask import abort, send_from_directory

from config import DATASETS_DIR
from table_builder import read_table_json, get_fail_values
import report_db


PAGE_SIZE = 25


def _format_size(bytes_val):
    try:
        b = int(bytes_val or 0)
    except (TypeError, ValueError):
        return "-"
    if b >= 1024 * 1024:
        return f"{b / 1024 / 1024:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def _format_upload_date(ts):
    if not ts:
        return "-"
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "-"


def _build_session_meta_inline(html, dataset_id):
    """`/pe/report/` 검색결과 필드를 topbar 한 줄에 인라인 표시."""
    try:
        sess = report_db.get_session_by_dataset_id(dataset_id)
    except Exception:
        sess = None
    if not sess:
        return []

    pt = (sess.get("product_type") or "").strip()
    pt_badge_cls = "session-badge session-badge-" + (pt if pt in ("MD", "PD", "PM", "SE") else "default")

    file_name = sess.get("file_name") or "-"
    items = [
        html.Span(pt or "-", className=pt_badge_cls),
        html.Span(sess.get("product") or "-", className="meta-inline"),
        html.Span(sess.get("revision") or "-", className="meta-inline"),
        html.Span(sess.get("lot_id") or "-", className="meta-inline"),
        html.Span(sess.get("process") or "-", className="meta-inline"),
        html.Span(file_name, className="meta-inline-file", title=file_name),
        html.Span(_format_upload_date(sess.get("created_at")), className="meta-inline"),
        html.Span(_format_size(sess.get("total_file_size")), className="meta-inline"),
    ]
    return items


def _dash_imports():
    try:
        from dash import Dash, Input, Output, State, dcc, html
        from dash import dash_table
    except ImportError as exc:
        raise RuntimeError("Dash is not installed. Install it with: pip install dash") from exc
    return Dash, Input, Output, State, dcc, html, dash_table


TAB_STYLE = {
    "padding": "4px 10px",
    "fontSize": "11px",
    "lineHeight": "1.1",
    "height": "auto",
    "minHeight": "0",
    "borderBottom": "1px solid #ddd",
    "fontWeight": "700",
}
TAB_SELECTED_STYLE = {
    **TAB_STYLE,
    "borderTop": "2px solid #4a90e2",
    "fontWeight": "700",
    "color": "#1f4d8c",
}
TABS_PARENT_STYLE = {"height": "31px", "minHeight": "0"}


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
    st = str(r.get("bin", "")).strip()
    is_pass = 0 if st == "1" else 1
    try:
        avg = float(r.get("avg") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    return (is_pass, -avg)


def _yield_columns(sources):
    cols = [
        {"name": "bin", "id": "bin"},
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
        "bin": "54px",
        "count": "42px",
        "avg": "58px",
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
            "width": "46px",
            "minWidth": "46px",
            "maxWidth": "46px",
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
    limit_cols  = ["lower_limit", "upper_limit"]
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
        {"if": {"column_id": "units"},   "width": "46px", "minWidth": "40px", "maxWidth": "68px", "textAlign": "center"},
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
        ("Lower Limit", "lower_limit"),
        ("Upper Limit", "upper_limit"),
        ("Units", "units"),
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
            row["lower_limit"] = ""
            row["upper_limit"] = ""
            row["units"] = ""
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


# ── Dashboard 편집 셀 저장소 (SQLite report_dashboard_comment) ────────────────
# kind 별 의미:
#   yield_comment         : { bin: comment_text }
#   summary_yield_comment : { bin: comment_text }
#   cpk_comment           : { "subject|source": comment_text }
#   summary_feature       : 단일 dict → "_singleton" 키에 JSON 문자열로 저장
#   summary_eval          : 단일 dict → "_singleton" 키에 JSON 문자열로 저장
#   issue_comment         : { bin: dict } → 각 bin 값에 JSON 문자열
_SINGLETON_KEY = "_singleton"


def _legacy_json_path(dataset_id, name):
    return DATASETS_DIR / dataset_id / "tables" / name


def _read_legacy_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_flat_comments(dataset_id, kind, legacy_name):
    """value 가 plain text 인 kind (yield_comment / summary_yield_comment / cpk_comment)."""
    data = report_db.get_dashboard_comments(dataset_id, kind)
    if data:
        return data
    return _read_legacy_json(_legacy_json_path(dataset_id, legacy_name))


def _read_singleton_dict(dataset_id, kind, legacy_name):
    """value 전체가 단일 JSON dict 인 kind (summary_feature / summary_eval)."""
    data = report_db.get_dashboard_comments(dataset_id, kind)
    raw = data.get(_SINGLETON_KEY) if data else None
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return _read_legacy_json(_legacy_json_path(dataset_id, legacy_name))


def _write_singleton_dict(dataset_id, kind, data):
    payload = {_SINGLETON_KEY: json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))}
    report_db.replace_dashboard_comments(dataset_id, kind, payload)


def _read_yield_comments(dataset_id):
    return _read_flat_comments(dataset_id, "yield_comment", "yield_comments.json")


def _write_yield_comments(dataset_id, comments):
    report_db.replace_dashboard_comments(dataset_id, "yield_comment", comments or {})


def _read_summary_comments(dataset_id):
    return _read_flat_comments(dataset_id, "summary_yield_comment", "summary_yield_comments.json")


def _write_summary_comments(dataset_id, comments):
    report_db.replace_dashboard_comments(dataset_id, "summary_yield_comment", comments or {})


def _read_summary_eval(dataset_id):
    return _read_singleton_dict(dataset_id, "summary_eval", "summary_eval.json")


def _write_summary_eval(dataset_id, data):
    _write_singleton_dict(dataset_id, "summary_eval", data)


def _read_summary_feature(dataset_id):
    return _read_singleton_dict(dataset_id, "summary_feature", "summary_feature.json")


def _write_summary_feature(dataset_id, data):
    _write_singleton_dict(dataset_id, "summary_feature", data)


def _read_cpk_comments(dataset_id):
    return _read_flat_comments(dataset_id, "cpk_comment", "cpk_comments.json")


def _write_cpk_comments(dataset_id, comments):
    report_db.replace_dashboard_comments(dataset_id, "cpk_comment", comments or {})


def _cpk_comment_key(subject, source):
    return f"{(subject or '').strip()}|{(source or '').strip()}"


def _issue_columns(sources):
    cols = [
        {"name": "bin", "id": "bin"},
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
        {"if": {"column_id": "bin"}, "width": "62px", "minWidth": "62px", "maxWidth": "62px", "textAlign": "center"},
        {"if": {"column_id": "subject"}, "width": "180px", "minWidth": "150px", "maxWidth": "220px"},
        {"if": {"column_id": "avg"}, "width": "58px", "minWidth": "58px", "maxWidth": "58px", "textAlign": "center"},
    ]
    for src in sources or []:
        rules.append({
            "if": {"column_id": f"portion_{src}"},
            "width": "58px",
            "minWidth": "46px",
            "maxWidth": "80px",
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
    data = report_db.get_dashboard_comments(dataset_id, "issue_comment")
    if data:
        result = {}
        for st, raw in data.items():
            try:
                result[st] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
        if result:
            return result
    return _read_legacy_json(_legacy_json_path(dataset_id, "issue_comments.json"))


def _write_issue_comments(dataset_id, comments):
    payload = {}
    for st, entry in (comments or {}).items():
        if entry:
            payload[str(st)] = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    report_db.replace_dashboard_comments(dataset_id, "issue_comment", payload)


def _project_issue_rows(fail_items, sources, comments, dataset_id):
    rows = []
    pass_type = "1"
    for r in (fail_items or {}).get("rows", []) or []:
        st = str(r.get("bin", "")).strip()
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
            "bin": st,
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
        html.Div(row.get("bin", ""), className="fail-cell type"),
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
        title="Report",
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
        meta_items = _build_session_meta_inline(html, dataset_id)
        return dataset_id, tables, html.Div([
            html.Div([
                html.H1("Report"),
                html.Div(meta_items, className="topbar-meta"),
                html.Div([
                    html.Button("Excel Download", id="download-report-btn", n_clicks=0, className="download-btn"),
                    html.Span(id="download-report-status", className="download-status"),
                    html.A("Exit", href="/pe/report/", className="exit-btn"),
                ], className="topbar-actions"),
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

            pass_row = next((r for r in yield_rows if str(r.get("bin", "")) == "1"), {})
            pass_portion = pass_row.get("portion (%)")
            if isinstance(pass_portion, (int, float)):
                pass_yield_str = f"{pass_portion:.2f}%"
            elif pass_portion is not None:
                pass_yield_str = str(pass_portion)
            else:
                pass_yield_str = "-"
            non_pass = [r for r in fail_items_rows if str(r.get("bin", "")) != "1"]

            # ── Feature Table ─────────────────────────────────────────────────
            saved_feat = _read_summary_feature(dataset_id)
            feature_row = {
                "subject":       saved_feat.get("subject",       dataset_id),
                "customer_type": saved_feat.get("customer_type", ""),
                "gd":            saved_feat.get("gd",            ""),
                "process":       saved_feat.get("process",       ""),
                "line":          saved_feat.get("line",          ""),
                "version":       saved_feat.get("version",       ""),
            }

            # ── Yield Summary ─────────────────────────────────────────────────
            smry_comments = _read_summary_comments(dataset_id)
            try:
                _sess_meta = report_db.get_session_by_dataset_id(dataset_id)
                lot_id_val = (_sess_meta or {}).get("lot_id") or "-"
            except Exception:
                lot_id_val = "-"
            _ordinals = ["1st", "2nd", "3rd", "4th", "5th"]
            yield_summary_rows = []
            for i, r in enumerate(non_pass[:5], 1):
                st = str(r.get("bin", ""))
                fail_subjects = r.get("fail_subjects") or []
                main_fail = (fail_subjects[0].get("subject", "N/A")
                             if fail_subjects else r.get("Main Fail subject", "N/A"))
                portion = r.get("portion (%)", "")
                pct_str = f"{portion}%" if portion != "" else ""
                yield_summary_rows.append({
                    "lotid":             lot_id_val if i == 1 else "",
                    "yield":             pass_yield_str if i == 1 else "",
                    "mfy_rank":          _ordinals[i - 1],
                    "mfy_subject":       main_fail,
                    "mfy_pct":           pct_str,
                    "comment":           smry_comments.get(st, ""),
                    "_key":              st,
                })

            # ── Evaluation Summary ────────────────────────────────────────────
            eval_data = _read_summary_eval(dataset_id)
            eval_rows = [
                {"category": "Yield", "condition_limit": eval_data.get("yield_cond", ""), "result": eval_data.get("yield",  "")},
                {"category": "CPK",   "condition_limit": eval_data.get("cpk_cond",   ""), "result": eval_data.get("cpk",    "")},
                {"category": "Temp",  "condition_limit": eval_data.get("temp_cond",  ""), "result": eval_data.get("temp",   "")},
                {"category": "ETC",   "condition_limit": eval_data.get("etc_cond",   ""), "result": eval_data.get("etc",    "")},
            ]

            _hdr = {"fontWeight": 600, "background": "#f6f7f9", "fontSize": 11,
                    "padding": "4px 8px", "textAlign": "center"}
            _cell = {
                "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                "fontSize": 12, "padding": "6px 10px",
            }

            return html.Div([
                # ── Feature ───────────────────────────────────────────────────
                html.Div("Feature", className="section-title"),
                dash_table.DataTable(
                    id="summary-feature-table",
                    columns=[
                        {"name": "subject",        "id": "subject",       "editable": True},
                        {"name": "Customer Type",  "id": "customer_type", "editable": True},
                        {"name": "GD",             "id": "gd",            "editable": True},
                        {"name": "Process",        "id": "process",       "editable": True},
                        {"name": "Line",           "id": "line",          "editable": True},
                        {"name": "version",        "id": "version",       "editable": True},
                    ],
                    data=[feature_row],
                    editable=False,
                    sort_action="none",
                    filter_action="none",
                    style_table={"overflowX": "auto", "marginBottom": "24px"},
                    style_cell={**_cell, "textAlign": "center", "backgroundColor": "#fffdf3"},
                    style_header=_hdr,
                ),
                html.Div(id="summary-feature-save-status", className="save-status"),

                # ── Yield Summary ─────────────────────────────────────────────
                html.Div("Yield", className="section-title small"),
                dash_table.DataTable(
                    id="summary-yield-table",
                    columns=[
                        {"name": ["", "LOTID"],                   "id": "lotid"},
                        {"name": ["", "Yield"],                   "id": "yield"},
                        {"name": ["Major Fail Yield", "Rank"],    "id": "mfy_rank"},
                        {"name": ["Major Fail Yield", "Subject"], "id": "mfy_subject"},
                        {"name": ["Major Fail Yield", "Yield %"], "id": "mfy_pct"},
                        {"name": ["", "Comment"],                 "id": "comment", "editable": True},
                    ],
                    data=yield_summary_rows,
                    merge_duplicate_headers=True,
                    editable=False,
                    sort_action="none",
                    filter_action="none",
                    style_table={"overflowX": "auto", "marginBottom": "8px"},
                    style_cell={**_cell, "textAlign": "left"},
                    style_cell_conditional=[
                        {"if": {"column_id": "lotid"},      "width": "120px", "textAlign": "center", "fontWeight": 600},
                        {"if": {"column_id": "yield"},      "width": "90px",  "textAlign": "center", "fontWeight": 600},
                        {"if": {"column_id": "mfy_rank"},   "width": "60px",  "textAlign": "center"},
                        {"if": {"column_id": "mfy_subject"},"width": "240px"},
                        {"if": {"column_id": "mfy_pct"},    "width": "80px",  "textAlign": "center", "fontWeight": 600},
                        {"if": {"column_id": "comment"},    "width": "300px", "backgroundColor": "#fffdf3"},
                    ],
                    style_data_conditional=(
                        [
                            {"if": {"column_id": "lotid"}, "backgroundColor": "#eef4fb"},
                            {"if": {"column_id": "yield"}, "backgroundColor": "#eef4fb"},
                        ] + [
                            {"if": {"row_index": idx, "column_id": col}, "borderTop": "none"}
                            for idx in range(1, len(yield_summary_rows))
                            for col in ("lotid", "yield")
                        ] + [
                            {"if": {"row_index": idx, "column_id": col}, "borderBottom": "none"}
                            for idx in range(0, max(0, len(yield_summary_rows) - 1))
                            for col in ("lotid", "yield")
                        ]
                    ),
                    style_header=_hdr,
                ),
                html.Div(id="summary-yield-save-status", className="save-status"),

                # ── Evaluation Summary ────────────────────────────────────────
                html.Div("Evaluation Summary", className="section-title small"),
                dash_table.DataTable(
                    id="summary-eval-table",
                    columns=[
                        {"name": "Category",             "id": "category"},
                        {"name": "Condition * Judge Limit", "id": "condition_limit", "editable": True},
                        {"name": "Result",               "id": "result",  "editable": True},
                    ],
                    data=eval_rows,
                    editable=False,
                    sort_action="none",
                    filter_action="none",
                    style_table={"overflowX": "auto", "maxWidth": "900px", "marginBottom": "8px"},
                    style_cell={**_cell, "textAlign": "left"},
                    style_cell_conditional=[
                        {"if": {"column_id": "category"},
                         "width": "100px", "fontWeight": 600,
                         "backgroundColor": "#f6f7f9", "textAlign": "center"},
                        {"if": {"column_id": "condition_limit"},
                         "width": "360px", "backgroundColor": "#fffdf3"},
                        {"if": {"column_id": "result"},
                         "width": "360px", "backgroundColor": "#fffdf3"},
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
                key = str(row.get("bin", ""))
                row["comment"] = comments.get(key, row.get("comment", "") or "")
                merged.append(row)
            merged.sort(key=_yield_sort_key)

            return html.Div([
                html.Div("Yield", className="section-title"),
                html.Div(
                    "Excel처럼 셀을 드래그 또는 Ctrl/Shift+클릭으로 다중 선택하면 하단 상태바에 합계·평균·개수·최대·최소가 자동 표시됩니다.",
                    className="table-note",
                ),
                dash_table.DataTable(
                    id="yield-table",
                    columns=_yield_columns(sources),
                    data=merged,
                    page_size=50,
                    sort_action="none",
                    filter_action="none",
                    editable=False,
                    cell_selectable=True,
                    selected_cells=[],
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
                    style_data_conditional=[
                        {"if": {"state": "selected"},
                         "backgroundColor": "#cfe2ff",
                         "border": "1px solid #3b82f6"},
                    ],
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
                html.Div([
                    html.Span("선택 영역 집계:", className="agg-bar-label"),
                    html.Span("Sum: -",   id="yield-agg-sum",   className="agg-stat"),
                    html.Span("Avg: -",   id="yield-agg-avg",   className="agg-stat"),
                    html.Span("Count: 0", id="yield-agg-count", className="agg-stat"),
                    html.Span("Min: -",   id="yield-agg-min",   className="agg-stat"),
                    html.Span("Max: -",   id="yield-agg-max",   className="agg-stat"),
                ], className="agg-bar"),
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

            # ── Fail Values: per-DUT per-subject fail records ──────────────
            try:
                fv_rows = get_fail_values(dataset_id)
            except Exception:
                fv_rows = []

            fv_columns = [
                {"name": "Source (Sheet)", "id": "source"},
                {"name": "DUT",            "id": "dut"},
                {"name": "XCoord",         "id": "x_coord"},
                {"name": "YCoord",         "id": "y_coord"},
                {"name": "Bin",            "id": "bin"},
                {"name": "Subject",        "id": "subject"},
                {"name": "Value",          "id": "value",       "type": "numeric"},
                {"name": "Lower Limit",    "id": "lower_limit", "type": "numeric"},
                {"name": "Upper Limit",    "id": "upper_limit", "type": "numeric"},
                {"name": "Fail",           "id": "fail"},
            ]
            fv_col_style = [
                {"if": {"column_id": "source"},       "width": "140px", "minWidth": "110px", "maxWidth": "200px"},
                {"if": {"column_id": "dut"},          "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "x_coord"},      "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "y_coord"},      "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "bin"},          "width": "60px",  "minWidth": "50px",  "maxWidth": "80px",  "textAlign": "center"},
                {"if": {"column_id": "subject"},      "width": "220px", "minWidth": "160px", "maxWidth": "300px"},
                {"if": {"column_id": "value"},        "width": "90px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "right"},
                {"if": {"column_id": "lower_limit"},  "width": "90px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "right"},
                {"if": {"column_id": "upper_limit"},  "width": "90px",  "minWidth": "70px",  "maxWidth": "120px", "textAlign": "right"},
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
                html.Div("Bin != 1 rows use the same yield counts, with subject thumbnails sorted by portion.", className="table-note"),
                html.Div(
                    html.Div([
                        html.Div([
                            html.Div("Bin", className="fail-cell head type"),
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
                    f"Bin ≠ 1 인 모든 DUT의 개별 fail 기록 — "
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
                    "Most-failed subject per Bin (ties broken by count, then alphabetical). Issue Point and Comment fields are editable and auto-saved.",
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
        Output("summary-feature-save-status", "children"),
        Input("summary-feature-table", "data_timestamp"),
        State("summary-feature-table", "data"),
        State("dataset-id", "data"),
        prevent_initial_call=True,
    )
    def save_summary_feature(_ts, data, dataset_id):
        if not dataset_id or not data:
            return ""
        row = data[0]
        payload = {
            "subject":       (row.get("subject")       or "").strip(),
            "customer_type": (row.get("customer_type") or "").strip(),
            "gd":            (row.get("gd")            or "").strip(),
            "process":       (row.get("process")       or "").strip(),
            "line":          (row.get("line")          or "").strip(),
            "version":       (row.get("version")       or "").strip(),
        }
        _write_summary_feature(dataset_id, payload)
        return "saved"

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
            key = str(row.get("_key", "")).strip()
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
            if cat:
                payload[cat]            = (row.get("result")          or "").strip()
                payload[f"{cat}_cond"]  = (row.get("condition_limit") or "").strip()
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
            key = str(row.get("bin", "")).strip()
            comment = (row.get("comment") or "").strip()
            if key and comment:
                payload[key] = comment
        _write_yield_comments(dataset_id, payload)
        return f"saved {len(payload)} comment(s)"

    # ── Yield 탭: Excel-like 셀 선택 집계 (clientside, 서버 부하 0) ──────────
    dash_app.clientside_callback(
        """
        function(selectedCells, data) {
            if (!selectedCells || !selectedCells.length || !data) {
                return ['Sum: -', 'Avg: -', 'Count: 0', 'Min: -', 'Max: -'];
            }
            const nums = [];
            for (const c of selectedCells) {
                const row = data[c.row];
                if (!row) continue;
                const v = row[c.column_id];
                const f = parseFloat(v);
                if (!isNaN(f) && isFinite(f)) nums.push(f);
            }
            if (!nums.length) {
                return ['Sum: -', 'Avg: -',
                        'Count: ' + selectedCells.length + ' (no numbers)',
                        'Min: -', 'Max: -'];
            }
            const sum = nums.reduce(function(a, b) { return a + b; }, 0);
            const avg = sum / nums.length;
            const mn  = Math.min.apply(null, nums);
            const mx  = Math.max.apply(null, nums);
            const fmt = function(x) {
                if (Number.isInteger(x)) return String(x);
                return x.toFixed(4).replace(/\\.?0+$/, '');
            };
            return [
                'Sum: '   + fmt(sum),
                'Avg: '   + fmt(avg),
                'Count: ' + nums.length,
                'Min: '   + fmt(mn),
                'Max: '   + fmt(mx),
            ];
        }
        """,
        Output("yield-agg-sum",   "children"),
        Output("yield-agg-avg",   "children"),
        Output("yield-agg-count", "children"),
        Output("yield-agg-min",   "children"),
        Output("yield-agg-max",   "children"),
        Input("yield-table", "selected_cells"),
        State("yield-table", "data"),
    )

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
            key = str(row.get("bin", "")).strip()
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
      .topbar { padding: 6px 12px; background: #fff; border-bottom: 1px solid #ddd; display: flex; gap: 10px; align-items: center; flex-wrap: nowrap; min-height: 34px; }
      .dash-root > .topbar { position: sticky; top: 0; z-index: 60; background: #fff; }
      .topbar h1 { font-size: 13px; margin: 0; font-weight: 700; color: #1a1a2e; white-space: nowrap; flex-shrink: 0; }
      .topbar-meta { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; overflow: hidden; }
      .topbar-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
      .meta-inline { font-size: 11px; color: #444; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 130px; }
      .meta-inline-file { font-size: 11px; color: #1a1a2e; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px; }
      .meta-inline-sess { font-family: "Consolas", "Menlo", monospace; color: #888; font-size: 10px; max-width: 110px; }
      .topbar-meta > * + * { position: relative; padding-left: 10px; }
      .topbar-meta > * + *::before { content: ""; position: absolute; left: 0; top: 50%; transform: translateY(-50%); height: 12px; width: 1px; background: #d8dde5; }
      .table-note { font-size: 12px; color: #666; }
      .link { font-size: 11px; color: #2369b3; text-decoration: none; white-space: nowrap; }
      .link:hover { text-decoration: underline; }
      .download-btn { font-size: 11px; padding: 3px 12px; border: 1px solid #2d7d46; background: #f4fbf6; color: #1a4d2b; border-radius: 4px; cursor: pointer; white-space: nowrap; }
      .download-btn:hover { background: #e6f5eb; }
      .download-status { font-size: 10px; color: #555; min-height: 12px; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .exit-btn { font-size: 11px; padding: 3px 14px; border: 1px solid #d0d5dd; background: #fff; color: #555; border-radius: 4px; cursor: pointer; white-space: nowrap; text-decoration: none; font-weight: 600; line-height: 1.8; }
      .exit-btn:hover { background: #fee2e2; border-color: #dc2626; color: #dc2626; }
      .session-badge { display: inline-block; padding: 1px 8px; border-radius: 9px; font-size: 10px; font-weight: 700; line-height: 1.3; }
      .session-badge-MD { background: #dbeafe; color: #1d4ed8; }
      .session-badge-PD { background: #dcfce7; color: #15803d; }
      .session-badge-PM { background: #fef9c3; color: #854d0e; }
      .session-badge-SE { background: #fce7f3; color: #9d174d; }
      .session-badge-default { background: #e5e7eb; color: #555; }
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
      .main-tabs { position: sticky; top: 34px; z-index: 55; background: #fff; border-bottom: 1px solid #ddd; height: 31px; min-height: 0; box-shadow: 0 2px 4px rgba(0,0,0,.05); }
      .main-tabs .tab-parent, .main-tabs .tab-container { height: 31px !important; min-height: 0 !important; }
      .main-tabs .tab { padding: 4px 10px !important; font-size: 11px !important; line-height: 1.1 !important; height: auto !important; min-height: 0 !important; font-weight: 700 !important; }
      .main-tabs .tab--selected { padding: 4px 10px !important; font-size: 11px !important; line-height: 1.1 !important; height: auto !important; min-height: 0 !important; font-weight: 700 !important; }
      .content { padding: 16px; }
      .section-title { font-size: 16px; font-weight: 650; margin: 0 0 12px; }
      .section-title.small { margin-top: 18px; font-size: 14px; }
      .fail-table-scroll { border: 1px solid #ddd; border-radius: 6px; overflow-y: auto; max-height: 65vh; }
      .fail-table { width: 100%; overflow: clip; background: #fff; }
      .fail-row { display: grid; grid-template-columns: 66px 62px 76px 180px minmax(360px, 1fr); border-top: 1px solid #eee; min-height: 92px; background: #fff; }
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
      .agg-bar { display: flex; align-items: center; gap: 18px; padding: 8px 14px; margin-top: 8px;
                 background: #f0f4fa; border: 1px solid #c5d3e7; border-radius: 4px; font-size: 12px; }
      .agg-bar-label { font-weight: 600; color: #1f4d8c; }
      .agg-stat { font-family: "Consolas", "Menlo", monospace; color: #333; min-width: 90px; }
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
