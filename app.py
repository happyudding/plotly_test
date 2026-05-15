from config import EXCEL_PATH, OUTPUT_PATH
from data_loader import load_excel
from plot_builder import build_figure


CUSTOM_CSS = """
<style>
.js-plotly-plot text,
.js-plotly-plot .annotation-text,
.js-plotly-plot .gtitle,
.js-plotly-plot .xtitle,
.js-plotly-plot .ytitle {
  -webkit-user-select: text !important;
  -moz-user-select: text !important;
  -ms-user-select: text !important;
  user-select: text !important;
  cursor: text !important;
  pointer-events: all !important;
}
.js-plotly-plot .modebar-container,
.js-plotly-plot .modebar {
  position: fixed !important;
  top: 10px !important;
  right: 20px !important;
  z-index: 9999 !important;
  background: rgba(255, 255, 255, 0.9) !important;
  padding: 4px 6px !important;
  border-radius: 4px !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.15) !important;
  opacity: 1 !important;
}
</style>
"""


def main() -> None:
    data = load_excel(EXCEL_PATH)
    print(f"Loaded {len(data.subjects)} subjects, {len(data.scores)} student rows")

    fig = build_figure(data)

    html = fig.to_html(
        include_plotlyjs="cdn",
        config={"scrollZoom": True, "displaylogo": False, "displayModeBar": True},
    )
    html = html.replace("</head>", CUSTOM_CSS + "</head>", 1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Saved {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
