from pathlib import Path

from config import CELL_ASPECT_H, CELL_ASPECT_W, COLS_PER_ROW

HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Cumulative Distribution by Subject</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #fafafa; }
  .topbar {
    position: sticky; top: 0; z-index: 100;
    background: #fff; border-bottom: 1px solid #ddd;
    padding: 8px 16px; display: flex; gap: 6px; align-items: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }
  .topbar h1 { font-size: 14px; margin: 0 12px 0 0; color: #333; font-weight: 600; }
  .topbar .active-label { color: #666; font-size: 12px; }
  .topbar .active-label strong { color: #333; }
  .topbar input#search-input {
    padding: 5px 10px; font-size: 13px; min-width: 220px;
    border: 1px solid #ccc; border-radius: 4px; outline: none;
    transition: border-color 0.15s ease, background 0.15s ease;
  }
  .topbar input#search-input:focus { border-color: #4a90e2; }
  .topbar input#search-input.no-match { border-color: #e57373; background: #fff5f5; }
  .content { padding: 16px; }
  .grid {
    display: grid;
    grid-template-columns: repeat(__COLS__, 1fr);
    gap: 16px;
  }
  .cell {
    position: relative;
    aspect-ratio: __AW__ / __AH__;
    background: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    overflow: hidden;
    transition: border-color 0.1s ease, box-shadow 0.1s ease;
  }
  .cell::before {
    content: 'loading...';
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #bbb;
    font-size: 12px;
    pointer-events: none;
  }
  .cell.loaded::before { display: none; }
  .cell .plot { width: 100%; height: 100%; }
  .cell.active { border-color: #4a90e2; box-shadow: 0 0 0 2px rgba(74,144,226,0.25); }
  .cell.flash { animation: cell-flash 1.5s ease-out; }
  @keyframes cell-flash {
    0%   { box-shadow: 0 0 0 0 rgba(255,193,7,0); border-color: #e0e0e0; }
    15%  { box-shadow: 0 0 0 6px rgba(255,193,7,0.7); border-color: #ffc107; }
    100% { box-shadow: 0 0 0 0 rgba(255,193,7,0); }
  }
  .cell .modebar-container, .cell .modebar { display: none !important; }
  .cell.active .modebar-container, .cell.active .modebar {
    display: flex !important;
    position: fixed !important;
    top: 6px !important;
    right: 24px !important;
    z-index: 200 !important;
    background: rgba(255,255,255,0.96) !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15) !important;
    opacity: 1 !important;
  }
</style>
</head>
<body>
<div class="topbar">
  <h1>Cumulative Distribution (n=__N__)</h1>
  <input id="search-input" type="text" placeholder="검색 (Enter: 해당 차트로 이동)" autocomplete="off">
  <span class="active-label">활성: <strong id="active-name">셀에 마우스를 올리세요</strong></span>
</div>
<div class="content">
  <div class="grid">
__CELLS__
  </div>
</div>
<script>
const cfg = {
  scrollZoom: true,
  displaylogo: false,
  displayModeBar: true,
  responsive: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d'],
};
const inflight = new Map();
let activeCell = null;

const activeNameEl = document.getElementById('active-name');
function updateActiveLabel() {
  activeNameEl.textContent = activeCell
    ? (activeCell.dataset.name || ('subject_' + activeCell.dataset.id))
    : '셀에 마우스를 올리세요';
}

const observer = new IntersectionObserver(async (entries) => {
  for (const entry of entries) {
    const cell = entry.target;
    if (entry.isIntersecting) {
      if (cell.dataset.loaded === '1' || cell.dataset.loaded === 'loading') continue;
      cell.dataset.loaded = 'loading';
      const ctrl = new AbortController();
      inflight.set(cell, ctrl);
      try {
        const resp = await fetch(`./api/chart/${cell.dataset.id}`, { signal: ctrl.signal });
        if (!resp.ok) throw new Error('http ' + resp.status);
        const p = await resp.json();
        if (ctrl.signal.aborted) continue;
        let div = cell.querySelector('.plot');
        if (!div) {
          div = document.createElement('div');
          div.className = 'plot';
          cell.appendChild(div);
        }
        await Plotly.newPlot(div, p.data, p.layout, cfg);
        cell.classList.add('loaded');
        cell.dataset.loaded = '1';
      } catch (err) {
        if (err.name !== 'AbortError') {
          console.error('cell', cell.dataset.id, err);
          cell.dataset.loaded = '';
        }
      } finally {
        inflight.delete(cell);
      }
    } else {
      const ctrl = inflight.get(cell);
      if (ctrl) ctrl.abort();
      const div = cell.querySelector('.plot');
      if (div) {
        try { Plotly.purge(div); } catch (_) {}
        div.remove();
      }
      cell.classList.remove('loaded', 'active');
      if (cell === activeCell) {
        activeCell = null;
        updateActiveLabel();
      }
      cell.dataset.loaded = '';
    }
  }
}, { rootMargin: '600px 0px', threshold: 0 });

document.querySelectorAll('.cell').forEach((el) => observer.observe(el));

const grid = document.querySelector('.grid');
grid.addEventListener('mouseover', (e) => {
  const cell = e.target.closest('.cell.loaded');
  if (!cell || cell === activeCell) return;
  if (activeCell) activeCell.classList.remove('active');
  activeCell = cell;
  activeCell.classList.add('active');
  updateActiveLabel();
});

const searchInput = document.getElementById('search-input');
let filterTimer = null;

function applyFilter(q) {
  q = q.trim().toLowerCase();
  const cells = document.querySelectorAll('.cell');
  for (const cell of cells) {
    const name = (cell.dataset.name || '').toLowerCase();
    const match = q === '' || name.includes(q) || cell.dataset.id === q;
    cell.style.display = match ? '' : 'none';
  }
}

searchInput.addEventListener('input', () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    applyFilter(searchInput.value);
    searchInput.classList.remove('no-match');
  }, 150);
});

searchInput.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const q = searchInput.value.trim().toLowerCase();
  if (!q) return;
  let target = null;
  document.querySelectorAll('.cell').forEach((cell) => {
    if (target) return;
    const name = (cell.dataset.name || '').toLowerCase();
    if (name.includes(q) || cell.dataset.id === q) target = cell;
  });
  if (!target) {
    searchInput.classList.add('no-match');
    setTimeout(() => searchInput.classList.remove('no-match'), 800);
    return;
  }
  document.querySelectorAll('.cell').forEach((c) => { c.style.display = ''; });
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.remove('flash');
  void target.offsetWidth;
  target.classList.add('flash');
  setTimeout(() => target.classList.remove('flash'), 1500);
});
</script>
</body>
</html>
"""


def _cell_html(subject_id: int, name: str) -> str:
    safe_name = name.replace('"', "&quot;")
    return f'    <div class="cell" data-id="{subject_id}" data-name="{safe_name}"></div>'


def write_html(out_path: Path, subjects: list[str]) -> None:
    cells = "\n".join(_cell_html(i, name) for i, name in enumerate(subjects))
    html = (
        HTML_TEMPLATE
        .replace("__COLS__", str(COLS_PER_ROW))
        .replace("__AW__", str(CELL_ASPECT_W))
        .replace("__AH__", str(CELL_ASPECT_H))
        .replace("__N__", str(len(subjects)))
        .replace("__CELLS__", cells)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
