import base64
import json
from pathlib import Path

from flask import abort, send_from_directory

from config import DATASETS_DIR
from table_builder import load_raw_page, read_table_json


PAGE_SIZE = 25


def _dash_imports():
    try:
        from dash import Dash, Input, Output, State, dcc, html
        from dash import dash_table
    except ImportError as exc:
        raise RuntimeError("Dash is not installed. Install it with: pip install dash") from exc
    return Dash, Input, Output, State, dcc, html, dash_table


def _columns(rows_or_columns):
    if not rows_or_columns:
        return []
    if isinstance(rows_or_columns[0], str):
        names = rows_or_columns
    else:
        names = list(rows_or_columns[0].keys())
    return [{"name": c, "id": c} for c in names]


def _table(dash_table, table_id, rows=None, page_size=PAGE_SIZE, **extra):
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
        columns=_columns(rows),
        data=rows[:page_size],
        page_size=page_size,
        sort_action=extra.pop("sort_action", "native"),
        filter_action=extra.pop("filter_action", "native"),
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell=style_cell,
        style_header={"fontWeight": 600, "background": "#f6f7f9"},
        **extra,
    )


def _yield_style():
    narrow = ["student_type", "count", "portion (%)"]
    return [
        {"if": {"column_id": col}, "width": "92px", "minWidth": "80px", "maxWidth": "110px"}
        for col in narrow
    ] + [
        {"if": {"column_id": "Main Fail subject"}, "width": "180px", "minWidth": "150px", "maxWidth": "220px"},
    ]


def _cpk_style():
    metric_cols = ["stdev", "cp", "cpl", "cpu", "cpk"]
    return [
        {"if": {"column_id": col}, "width": "88px", "minWidth": "78px", "maxWidth": "100px"}
        for col in metric_cols
    ] + [
        {"if": {"filter_query": "{cpk} < 1.33 && {cpk} != 'N/A'", "column_id": "cpk"}, "backgroundColor": "#fff3bf", "color": "#5c4400", "fontWeight": "650"},
    ]


def _load_small_tables(dataset_id):
    return {
        "meta": read_table_json(dataset_id, "meta") or {},
        "yield": read_table_json(dataset_id, "yield") or [],
        "cpk": read_table_json(dataset_id, "cpk") or [],
        "fail_items": read_table_json(dataset_id, "fail_items") or {"rows": []},
    }


def _fail_item_row(html, dataset_id, row):
    subjects = row.get("fail_subjects") or []
    if not subjects:
        subject_content = html.Span(row.get("Fail Subjects", "Pass"), className="pass-label")
    else:
        subject_content = html.Div([
            html.Div([
                html.Div(item["subject"], className="subject-title", title=item["subject"]),
                html.Div(f"{item['count']} rows | {item['portion (%)']}%", className="subject-meta"),
                html.Img(src=f"/api/{dataset_id}/thumb/{item['subject_id']}"),
            ], className="subject-card")
            for item in subjects
        ], className="subject-strip")
    return html.Div([
        html.Div(row.get("student_type", ""), className="fail-cell type"),
        html.Div(row.get("count", ""), className="fail-cell count"),
        html.Div(row.get("portion (%)", ""), className="fail-cell portion"),
        html.Div(row.get("Main Fail subject", ""), className="fail-cell main"),
        html.Div(subject_content, className="fail-cell subjects"),
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
                html.Div(f"dataset: {dataset_id} | rows: {meta.get('row_count', 0)} | subjects: {len(meta.get('subjects', []))}", className="meta"),
                html.A("Open distribution full page", href=f"/view/{dataset_id}", target="_blank", className="link"),
            ], className="topbar"),
            dcc.Tabs(id="tabs", value="raw", className="main-tabs", children=[
                dcc.Tab(label="Raw Data", value="raw"),
                dcc.Tab(label="Yield", value="yield"),
                dcc.Tab(label="CPK", value="cpk"),
                dcc.Tab(label="Fail Item", value="fail"),
                dcc.Tab(label="Distribution", value="distribution"),
            ]),
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
        if tab == "raw":
            meta = tables.get("meta") or {}
            sources = ["__all__", *(meta.get("sources") or [])]
            return html.Div([
                html.Div("Raw Data", className="section-title"),
                dcc.Tabs(
                    id="raw-source-tabs",
                    value="__all__",
                    className="subtabs",
                    children=[
                        dcc.Tab(label="All" if source == "__all__" else source, value=source)
                        for source in sources
                    ],
                ),
                dash_table.DataTable(
                    id="raw-table",
                    columns=_columns(meta.get("raw_columns") or []),
                    data=[],
                    page_current=0,
                    page_size=PAGE_SIZE,
                    page_action="custom",
                    sort_action="custom",
                    sort_mode="multi",
                    sort_by=[],
                    filter_action="custom",
                    filter_query="",
                    style_table={"overflowX": "auto"},
                    style_cell={"fontSize": 12, "padding": "6px 8px", "textAlign": "left", "minWidth": "90px", "maxWidth": "280px", "overflow": "hidden", "textOverflow": "ellipsis"},
                    style_header={"fontWeight": 600, "background": "#f6f7f9"},
                ),
                html.Div(id="raw-count", className="table-note"),
            ])
        if tab == "yield":
            rows = tables.get("yield") or []
            return html.Div([
                html.Div("Yield", className="section-title"),
                _table(
                    dash_table,
                    "yield-table",
                    rows,
                    page_size=50,
                    style_cell_conditional=_yield_style(),
                    style_cell={"width": "120px", "minWidth": "80px", "maxWidth": "180px"},
                ),
            ])
        if tab == "cpk":
            rows = tables.get("cpk") or []
            return html.Div([
                html.Div("CPK", className="section-title"),
                _table(
                    dash_table,
                    "cpk-table",
                    rows,
                    page_size=50,
                    style_cell_conditional=_cpk_style(),
                    style_data_conditional=_cpk_style(),
                ),
            ])
        if tab == "fail":
            fail_items = tables.get("fail_items") or {"rows": []}
            rows = fail_items.get("rows", [])
            return html.Div([
                html.Div("Fail Item", className="section-title"),
                html.Div("student_type != 1 rows use the same yield counts, with subject thumbnails sorted by portion.", className="table-note"),
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
            ])
        return html.Div([
            html.Div("Distribution", className="section-title"),
            html.Iframe(src=f"/view/{dataset_id}", className="distribution-frame"),
        ])

    @dash_app.callback(
        Output("raw-table", "data"),
        Output("raw-table", "columns"),
        Output("raw-count", "children"),
        Input("raw-source-tabs", "value"),
        Input("raw-table", "page_current"),
        Input("raw-table", "page_size"),
        Input("raw-table", "sort_by"),
        Input("raw-table", "filter_query"),
        State("dataset-id", "data"),
    )
    def update_raw(source_file, page_current, page_size, sort_by, filter_query, dataset_id):
        if not dataset_id:
            return [], [], ""
        rows, total, columns = load_raw_page(dataset_id, page_current, page_size, sort_by, filter_query, source_file)
        source_label = "All files" if not source_file or source_file == "__all__" else source_file
        return rows, _columns(columns), f"{source_label} | page {(page_current or 0) + 1}, filtered rows: {total}"

    dash_app.index_string = """<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
      body { margin: 0; background: #fafafa; color: #222; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      .topbar { padding: 14px 18px; background: #fff; border-bottom: 1px solid #ddd; display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
      .dash-root > .topbar { position: sticky; top: 0; z-index: 60; background: #fff; }
      .main-tabs { position: sticky; top: 52px; z-index: 55; background: #fff; border-bottom: 1px solid #ddd; }
      .topbar h1 { font-size: 18px; margin: 0; }
      .meta, .table-note { font-size: 12px; color: #666; }
      .link { font-size: 12px; color: #2369b3; text-decoration: none; }
      .content { padding: 16px; }
      .section-title { font-size: 16px; font-weight: 650; margin: 0 0 12px; }
      .section-title.small { margin-top: 18px; font-size: 14px; }
      .subtabs { margin: 0 0 12px; }
      .fail-table { width: 100%; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; background: #fff; }
      .fail-row { display: grid; grid-template-columns: 96px 88px 110px 180px minmax(360px, 1fr); border-top: 1px solid #eee; min-height: 92px; }
      .fail-row:first-child { border-top: none; }
      .fail-row.header { min-height: 38px; background: #f6f7f9; }
      .fail-cell { padding: 8px; font-size: 12px; border-left: 1px solid #eee; overflow: hidden; }
      .fail-cell:first-child { border-left: none; }
      .fail-cell.head { font-weight: 650; color: #333; display: flex; align-items: center; }
      .fail-cell.type, .fail-cell.count, .fail-cell.portion, .fail-cell.main { display: flex; align-items: center; }
      .subject-strip { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
      .subject-card { flex: 0 0 220px; border: 1px solid #ddd; border-radius: 6px; background: #fff; padding: 6px; }
      .subject-card img { display: block; width: 100%; aspect-ratio: 16 / 11; object-fit: contain; background: #fff; }
      .subject-title { font-size: 11px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 3px; }
      .subject-meta { font-size: 10px; color: #666; margin-bottom: 4px; }
      .pass-label { color: #2d6b2d; font-weight: 650; }
      .image-strip { display: flex; gap: 12px; overflow-x: auto; padding: 12px 0 18px; align-items: flex-start; }
      .image-card { flex: 0 0 520px; background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 8px; }
      .image-card img { display: block; width: 100%; height: auto; min-height: 280px; object-fit: contain; }
      .image-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .distribution-frame { width: 100%; height: calc(100vh - 170px); border: 1px solid #ddd; border-radius: 6px; background: #fff; }
      .error { padding: 32px; color: #a40000; }
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
