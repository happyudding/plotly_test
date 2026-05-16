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
  .content { padding: 16px 156px 16px 16px; }
  .sidebar {
    position: fixed;
    right: 0;
    top: 48px;
    bottom: 0;
    width: 140px;
    background: #fff;
    border-left: 1px solid #ddd;
    padding: 12px 10px;
    overflow-y: auto;
    z-index: 80;
    box-sizing: border-box;
  }
  .sidebar-title {
    font-size: 11px; color: #666; margin: 0 0 8px 2px; font-weight: 600;
  }
  .sidebar-hint { font-size: 10px; color: #999; margin-bottom: 8px; }
  .sidebar-item {
    display: flex; align-items: center; gap: 8px;
    width: 100%; padding: 5px 8px; margin-bottom: 4px;
    border: 1px solid #e0e0e0; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 12px;
    text-align: left; transition: opacity 0.1s, background 0.1s;
    font-family: inherit;
  }
  .sidebar-item:hover { background: #f5f5f5; }
  .sidebar-item.off { opacity: 0.35; text-decoration: line-through; }
  .sidebar-item .swatch {
    width: 14px; height: 14px; border-radius: 2px; flex-shrink: 0;
    border: 1px solid rgba(0,0,0,0.1);
  }
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
  .note {
    position: absolute;
    background: #fff8c5;
    border: 1px solid #d4a72c;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    z-index: 50;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 120px;
    min-height: 70px;
    resize: both;
  }
  .note-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 2px 4px;
    background: rgba(0,0,0,0.06);
    user-select: none;
    cursor: move;
  }
  .note-drag { color: #666; padding: 2px 6px; font-size: 12px; }
  .note-del {
    border: none; background: transparent; cursor: pointer;
    font-size: 16px; color: #888; width: 22px; height: 22px;
    border-radius: 50%; padding: 0; line-height: 1;
  }
  .note-del:hover { background: rgba(0,0,0,0.1); color: #c00; }
  .note-body {
    flex: 1; padding: 6px 8px; outline: none; overflow: auto;
    font-size: 13px; line-height: 1.4; background: transparent;
  }
  .cell .modebar-container, .cell .modebar { display: none !important; }
  .cell.active .modebar-container, .cell.active .modebar {
    display: flex !important;
    position: fixed !important;
    top: 6px !important;
    right: 156px !important;
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
  <button id="btn-add-note" type="button" title="메모 추가" style="padding:5px 10px;cursor:pointer;background:#fff8c5;border:1px solid #d4a72c;border-radius:4px;font-size:13px;">+ 메모</button>
  <span class="active-label">활성: <strong id="active-name">셀에 마우스를 올리세요</strong></span>
</div>
<div class="content">
  <div class="grid">
__CELLS__
  </div>
</div>
<aside class="sidebar">
  <div class="sidebar-title">학교</div>
  <div class="sidebar-hint">클릭=숨김 토글</div>
__SIDEBAR_ITEMS__
</aside>
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

const HIDDEN_KEY = 'dashboard-hidden-schools-v1';
let hiddenSchools = new Set();
try { hiddenSchools = new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')); } catch (_) {}
function saveHidden() { localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hiddenSchools])); }

function applyHiddenToData(traces) {
  for (const t of traces) t.visible = !hiddenSchools.has(t.name);
  return traces;
}

function syncSidebarUI() {
  document.querySelectorAll('.sidebar-item').forEach((el) => {
    el.classList.toggle('off', hiddenSchools.has(el.dataset.school));
  });
}

function toggleSchool(name) {
  if (hiddenSchools.has(name)) hiddenSchools.delete(name);
  else hiddenSchools.add(name);
  saveHidden();
  syncSidebarUI();
  document.querySelectorAll('.cell.loaded').forEach((cell) => {
    const div = cell.querySelector('.plot');
    if (!div || !div.data) return;
    const vis = div.data.map((t) => !hiddenSchools.has(t.name));
    try { Plotly.restyle(div, { visible: vis }); } catch (_) {}
  });
}

document.querySelector('.sidebar').addEventListener('click', (e) => {
  const item = e.target.closest('.sidebar-item');
  if (!item) return;
  toggleSchool(item.dataset.school);
});
syncSidebarUI();

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
        const resp = await fetch(`./api/chart/${cell.dataset.id}?_=${Date.now()}`, { signal: ctrl.signal, cache: 'no-store' });
        if (!resp.ok) throw new Error('http ' + resp.status);
        const p = await resp.json();
        if (ctrl.signal.aborted) continue;
        let div = cell.querySelector('.plot');
        if (!div) {
          div = document.createElement('div');
          div.className = 'plot';
          cell.appendChild(div);
        }
        applyHiddenToData(p.data);
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

const NOTE_KEY = 'dashboard-notes-v1';
let notes = (() => {
  try { return JSON.parse(localStorage.getItem(NOTE_KEY) || '[]'); }
  catch { return []; }
})();
function saveNotes() { localStorage.setItem(NOTE_KEY, JSON.stringify(notes)); }

function renderNote(note) {
  const el = document.createElement('div');
  el.className = 'note';
  el.dataset.id = note.id;
  el.style.left = note.x + 'px';
  el.style.top  = note.y + 'px';
  if (note.w) el.style.width  = note.w + 'px';
  if (note.h) el.style.height = note.h + 'px';
  el.innerHTML = '<div class="note-header"><span class="note-drag">⋮⋮ 드래그</span><button class="note-del" title="삭제">×</button></div><div class="note-body" contenteditable="true"></div>';
  el.querySelector('.note-body').innerHTML = note.text || '';
  document.body.appendChild(el);
  wireNote(el, note);
  return el;
}

function wireNote(el, note) {
  const header = el.querySelector('.note-header');
  let drag = null;
  header.addEventListener('pointerdown', (e) => {
    if (e.target.classList.contains('note-del')) return;
    drag = { sx: e.clientX, sy: e.clientY, nx: parseFloat(el.style.left), ny: parseFloat(el.style.top) };
    header.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  header.addEventListener('pointermove', (e) => {
    if (!drag) return;
    el.style.left = (drag.nx + e.clientX - drag.sx) + 'px';
    el.style.top  = (drag.ny + e.clientY - drag.sy) + 'px';
  });
  header.addEventListener('pointerup', () => {
    if (!drag) return;
    drag = null;
    note.x = parseFloat(el.style.left);
    note.y = parseFloat(el.style.top);
    saveNotes();
  });
  el.querySelector('.note-del').addEventListener('click', () => {
    el.remove();
    notes = notes.filter(n => n.id !== note.id);
    saveNotes();
  });
  const body = el.querySelector('.note-body');
  body.addEventListener('blur', () => { note.text = body.innerHTML; saveNotes(); });
  const ro = new ResizeObserver(() => {
    note.w = el.offsetWidth;
    note.h = el.offsetHeight;
    saveNotes();
  });
  ro.observe(el);
}

notes.forEach(renderNote);

document.getElementById('btn-add-note').addEventListener('click', () => {
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const note = {
    id,
    x: window.scrollX + Math.max(40, window.innerWidth / 2 - 110),
    y: window.scrollY + Math.max(80, window.innerHeight / 2 - 60),
    w: 220, h: 130, text: '',
  };
  notes.push(note);
  saveNotes();
  const el = renderNote(note);
  el.querySelector('.note-body').focus();
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


def _sidebar_item_html(school: dict) -> str:
    name = str(school["name"]).replace('"', "&quot;")
    color = str(school["color"]).replace('"', "&quot;")
    return (
        f'  <button class="sidebar-item" type="button" data-school="{name}">'
        f'<span class="swatch" style="background:{color}"></span>'
        f'<span class="label">{name}</span>'
        f'</button>'
    )


def write_html(out_path: Path, subjects: list[str], schools: list[dict]) -> None:
    cells = "\n".join(_cell_html(i, name) for i, name in enumerate(subjects))
    sidebar_items = "\n".join(_sidebar_item_html(s) for s in schools)
    html = (
        HTML_TEMPLATE
        .replace("__COLS__", str(COLS_PER_ROW))
        .replace("__AW__", str(CELL_ASPECT_W))
        .replace("__AH__", str(CELL_ASPECT_H))
        .replace("__N__", str(len(subjects)))
        .replace("__CELLS__", cells)
        .replace("__SIDEBAR_ITEMS__", sidebar_items)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
