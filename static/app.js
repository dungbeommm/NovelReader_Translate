'use strict';

const $ = id => document.getElementById(id);
let chapters = [], selected = null, state = { progress: { status: 'ready', active: false } };
let visible = 100, busy = false, ws, retry = 1000;
let availableModels = [];
let currentFontSize = parseInt(localStorage.getItem('novel_font_size') || '17', 10);
let currentViewMode = localStorage.getItem('novel_view_mode') || 'parallel';
let isSelectMode = false;
const selectedChapterIds = new Set();

const titles = {
  ready: 'Sẵn sàng',
  loading: 'Đang nạp model…',
  running: 'Đang dịch…',
  paused: 'Tạm dừng',
  stopping: 'Đang dừng…',
  error: 'Lỗi'
};

const icons = { pending: '◷', translating: '⟳', done: '✓', error: '⚠' };

function notice(message, error = false) {
  $('notice-text').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = false;
}
$('dismiss').onclick = () => $('notice').hidden = true;

async function api(path, body, method) {
  const options = {
    method: method || (body !== undefined ? 'POST' : 'GET'),
    headers: { 'X-App-Request': 'novel-translator' }
  };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const r = await fetch(path, options);
  if (!r.ok) {
    const raw = await r.text();
    let message;
    try {
      const e = JSON.parse(raw);
      message = typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail);
    } catch {
      message = raw;
    }
    throw new Error(message || r.statusText);
  }
  return r.json();
}

async function safe(fn) {
  try {
    await fn();
  } catch (e) {
    notice(e.message, true);
  }
}

// ----------------- FONT & VIEW MODES -----------------
function setFontSize(size) {
  currentFontSize = Math.max(13, Math.min(26, size));
  document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');
  $('font-val').textContent = currentFontSize + 'px';
  localStorage.setItem('novel_font_size', currentFontSize);
  equalizeRows();
}
$('font-dec').onclick = () => setFontSize(currentFontSize - 1);
$('font-inc').onclick = () => setFontSize(currentFontSize + 1);

function setViewMode(mode) {
  currentViewMode = mode;
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  const panes = $('reading-panes');
  panes.classList.remove('mode-target', 'mode-source');
  if (mode === 'target') panes.classList.add('mode-target');
  if (mode === 'source') panes.classList.add('mode-source');
  localStorage.setItem('novel_view_mode', mode);
  if (mode === 'parallel') equalizeRows();
}

document.querySelectorAll('.view-btn').forEach(btn => {
  btn.onclick = () => setViewMode(btn.dataset.mode);
});

// Copy current chapter translation
$('copy-btn').onclick = () => {
  const chapter = chapters.find(c => c.id === selected);
  if (!chapter) {
    notice('Chưa chọn chương để sao chép.');
    return;
  }
  const paras = Array.from($('target-pane').querySelectorAll('.para'))
    .map(p => p.textContent.trim())
    .filter(t => t && !t.startsWith('(') && !t.startsWith('Bản dịch sẽ') && !t.startsWith('Đang chờ'));

  const fullText = (chapter.translated_title || chapter.title) + '\n\n' + paras.join('\n\n');
  navigator.clipboard.writeText(fullText).then(() => {
    notice('✓ Đã sao chép bản dịch chương vào Clipboard!');
  }).catch(() => {
    notice('Không thể truy cập Clipboard.', true);
  });
};

// Mobile Tab Switcher
const workspace = document.querySelector('.workspace');
$('tab-sidebar').onclick = () => {
  $('tab-sidebar').classList.add('active');
  $('tab-reader').classList.remove('active');
  workspace.classList.remove('show-reader');
};
$('tab-reader').onclick = () => {
  $('tab-reader').classList.add('active');
  $('tab-sidebar').classList.remove('active');
  workspace.classList.add('show-reader');
};

// ----------------- HARDWARE & MODELS -----------------
async function loadHardware() {
  try {
    const hw = await api('/api/hardware');
    if (hw) {
      const dev = hw.is_gpu ? 'GPU' : 'CPU';
      $('hw-pill').textContent = `⚡ ${dev}: ${hw.cpu_count} luồng`;
      if (hw.batch_size && !$('batch').value) {
        $('batch').value = hw.batch_size;
      }
    }
  } catch {}
}

async function loadModels() {
  try {
    availableModels = await api('/api/models');
    const select = $('engine');
    const curVal = select.value || 'HachimiMT-60-QT';
    select.replaceChildren();

    const localGroup = document.createElement('optgroup');
    localGroup.label = 'Model CTranslate2 trên máy (Đã tải đủ)';
    const spaceGroup = document.createElement('optgroup');
    spaceGroup.label = 'Trực tuyến Hugging Face Space (Online)';

    availableModels.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.id;
      const sizeText = m.size_mb > 0 ? ` (~${m.size_mb} MB)` : '';
      opt.textContent = `${m.name}${sizeText}`;
      if (m.id.startsWith('space')) {
        spaceGroup.append(opt);
      } else {
        localGroup.append(opt);
      }
    });

    if (localGroup.children.length) select.append(localGroup);
    if (spaceGroup.children.length) select.append(spaceGroup);

    if (availableModels.some(m => m.id === curVal)) {
      select.value = curVal;
    }
    updateModelInfo();
  } catch {}
}

function updateModelInfo() {
  const key = $('engine').value;
  const m = availableModels.find(x => x.id === key);
  const badge = $('model-badge');

  if (!m) return;

  if (m.id === 'space' || m.id.startsWith('space:')) {
    badge.className = 'badge badge-success';
    badge.textContent = '🌐 Space Online';
    $('engine-note-title').textContent = `${m.name} · Trực tuyến HF Space`;
    $('engine-note-desc').textContent = m.desc || 'Dịch trực tuyến qua HF Space (ngocdang83/HachimiMT-demo). Không tốn tài nguyên máy.';
  } else if (m.downloaded) {
    badge.className = 'badge badge-success';
    badge.textContent = '✓ Sẵn sàng';
    $('engine-note-title').textContent = `${m.name} · Offline`;
    $('engine-note-desc').textContent = m.desc || 'Model đã có trên máy, chạy hoàn toàn offline trên CPU.';
  } else {
    badge.className = 'badge badge-warning';
    badge.textContent = `⬇ Chưa tải (~${m.size_mb} MB)`;
    $('engine-note-title').textContent = `Tự động tải khi dịch (~${m.size_mb} MB)`;
    $('engine-note-desc').textContent = m.desc ? `${m.desc} Sẽ tải về một lần duy nhất từ Hugging Face.` : 'Model sẽ được tải tự động trong lần dịch đầu tiên.';
  }
}
// ----------------- TRIPLET CONTROLS (BEAM, CHUNK, NORMALIZE) -----------------
function setChunkMode(mode) {
  const isPara = mode === 'paragraph';
  $('chunk-sentence-label').classList.toggle('active', !isPara);
  $('chunk-paragraph-label').classList.toggle('active', isPara);
  const radios = document.querySelectorAll('input[name="chunk_mode"]');
  radios.forEach(r => {
    r.checked = (r.value === mode);
  });
}
$('chunk-sentence-label').onclick = () => setChunkMode('sentence');
$('chunk-paragraph-label').onclick = () => setChunkMode('paragraph');

$('beam-size').oninput = () => {
  $('beam-val').textContent = $('beam-size').value;
};

// ----------------- GLOSSARY FILE IMPORT -----------------
$('btn-import-glossary').onclick = () => $('glossary-file').click();
$('glossary-file').onchange = e => {

  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    const content = ev.target.result;
    if ($('glossary').value.trim()) {
      $('glossary').value = $('glossary').value.trim() + '\n' + content.trim();
    } else {
      $('glossary').value = content.trim();
    }
    notice(`Đã nạp từ điển từ ${file.name}.`);
  };
  reader.readAsText(file);
  e.target.value = '';
};
$('btn-clear-glossary').onclick = () => {
  if ($('glossary').value && confirm('Xóa toàn bộ nội dung từ điển hiện tại?')) {
    $('glossary').value = '';
  }
};

// ----------------- PROGRESS & BOOK STATE -----------------
function renderProgress(progress) {
  state.progress = progress;
  const p = progress;
  $('status').textContent = '● ' + (titles[p.status] || p.status);
  $('status').classList.toggle('busy', ['running', 'loading', 'stopping', 'paused'].includes(p.status));
  $('status').classList.toggle('error', p.status === 'error');

  const percent = p.total ? Math.floor(p.done / p.total * 100) : 0;
  $('progress-text').textContent = `${p.done} / ${p.total} chương`;
  $('percent').textContent = percent + '%';
  $('progress').value = percent;

  $('start').disabled = p.active || !state.book || busy;
  $('pause').disabled = !p.active || p.status === 'stopping';
  $('stop').disabled = !p.active || p.status === 'stopping';
  $('pause').textContent = p.status === 'paused' ? '▷ Tiếp tục' : 'Ⅱ Tạm dừng';

  const inputs = ['engine', 'glossary', 'batch', 'reset', 'load-path', 'file', 'opt-honorific', 'opt-pronoun', 'opt-t2s', 'beam-size', 'normalize-mode', 'btn-delete-book', 'btn-reset-selected', 'btn-delete-selected', 'btn-reset-current', 'btn-delete-current'];
  inputs.forEach(id => {
    const el = $(id);
    if (el) el.disabled = p.active || busy;
  });
  if ($('chunk-sentence-label')) $('chunk-sentence-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('chunk-paragraph-label')) $('chunk-paragraph-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';

  $('save-note').textContent = p.message || 'Tiến độ được lưu tự động trên máy của bạn.';
  for (const id of ['export-txt', 'export-epub']) {
    $(id).setAttribute('aria-disabled', String(!state.book));
  }
}

function updateBook(book) {
  state.book = book;
  $('file-info').hidden = !book;
  $('book-name').textContent = book ? book.title : 'Chưa nạp truyện';
  if (book) {
    $('filename').textContent = book.filename;
    $('encoding').textContent = book.encoding + ' · Đã lưu trên máy';
  } else {
    $('chapter-single-ops').hidden = true;
  }
}

function updateBatchCount() {
  const count = selectedChapterIds.size;
  $('batch-selected-count').textContent = `Đã chọn: ${count}`;
  $('btn-reset-selected').disabled = count === 0;
  $('btn-delete-selected').disabled = count === 0;
}

function renderToc() {
  const query = $('search').value.toLowerCase();
  const filtered = chapters.filter(c => (c.title + ' ' + (c.translated_title || '') + ' ' + c.position).toLowerCase().includes(query));

  $('toc').replaceChildren();
  $('chapter-count').textContent = chapters.length + ' chương';
  $('toc-count').textContent = chapters.length;

  for (const c of filtered.slice(0, visible)) {
    const b = document.createElement('button');
    b.className = 'toc-item ' + c.status + (c.id === selected ? ' selected' : '');
    b.setAttribute('aria-current', c.id === selected ? 'true' : 'false');
    b.title = c.error || c.title;

    if (isSelectMode) {
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'toc-checkbox';
      cb.checked = selectedChapterIds.has(c.id);
      cb.onclick = (e) => {
        e.stopPropagation();
        if (cb.checked) selectedChapterIds.add(c.id);
        else selectedChapterIds.delete(c.id);
        updateBatchCount();
      };
      b.append(cb);
    }

    const n = document.createElement('span');
    n.className = 'num';
    n.textContent = '#' + c.position;

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = c.translated_title || c.title;

    const icon = document.createElement('span');
    icon.className = 'state';
    icon.textContent = icons[c.status] || '◷';

    b.append(n, name, icon);
    b.onclick = (e) => {
      if (isSelectMode && e.target.classList.contains('toc-checkbox')) return;
      safe(() => selectChapter(c.id));
      if (window.innerWidth <= 900) {
        $('tab-reader').click();
      }
    };
    $('toc').append(b);
  }

  if (filtered.length > visible) {
    const b = document.createElement('button');
    b.className = 'more';
    b.textContent = `Xem thêm (${filtered.length - visible} chương)`;
    b.onclick = () => { visible += 100; renderToc(); };
    $('toc').append(b);
  }

  if (!filtered.length) {
    const p = document.createElement('p');
    p.className = 'toc-empty';
    p.textContent = chapters.length ? 'Không tìm thấy chương phù hợp.' : 'Chương truyện sẽ xuất hiện tại đây.';
    $('toc').append(p);
  }

  const i = chapters.findIndex(c => c.id === selected);
  $('prev').disabled = i <= 0;
  $('next').disabled = i < 0 || i === chapters.length - 1;
}

function equalizeRows() {
  if (currentViewMode !== 'parallel') return;
  const a = $('source-pane').children, b = $('target-pane').children;
  for (let i = 0; i < a.length; i++) {
    a[i].style.minHeight = '';
    if (b[i]) b[i].style.minHeight = '';
  }
  for (let i = 0; i < a.length; i++) {
    if (b[i]) {
      const h = Math.max(a[i].getBoundingClientRect().height, b[i].getBoundingClientRect().height);
      a[i].style.minHeight = b[i].style.minHeight = h + 'px';
    }
  }
}

async function selectChapter(id, refresh = false) {
  const chapter = await api('/api/chapters/' + id);
  if (refresh && selected !== id) return;
  selected = id;

  $('reader-empty').hidden = true;
  $('reading-panes').hidden = false;
  $('chapter-single-ops').hidden = false;

  $('chapter-index').textContent = `CHƯƠNG ${chapter.position.toString().padStart(2, '0')} / ${chapters.length}`;
  $('chapter-title').textContent = chapter.translated_title || chapter.title;
  const sub = $('chapter-subtitle');
  if (sub) {
    sub.textContent = chapter.error || '';
    sub.classList.toggle('reader-error', !!chapter.error);
    sub.style.display = chapter.error ? 'block' : 'none';
  }

  const panes = [$('source-pane'), $('target-pane')];
  const scrolls = panes.map(p => p.scrollTop);
  panes.forEach(p => p.replaceChildren());

  const source = chapter.source.length ? chapter.source : ['(Chương không có phần thân.)'];
  source.forEach((text, i) => {
    const p = document.createElement('p');
    p.className = 'para';
    p.textContent = text;
    panes[0].append(p);

    const q = document.createElement('p');
    q.className = 'para';
    q.textContent = chapter.translated[i] || '';
    if (!q.textContent) {
      q.classList.add('waiting');
      q.textContent = chapter.status === 'error'
        ? 'Dịch lỗi · Bắt đầu để thử lại'
        : chapter.status === 'done'
          ? '(Không có nội dung)'
          : chapter.status === 'translating'
            ? 'Đang chờ đoạn dịch…'
            : 'Bản dịch sẽ xuất hiện tại đây.';
    }
    panes[1].append(q);
  });

  equalizeRows();
  panes.forEach((p, i) => p.scrollTop = refresh ? scrolls[i] : 0);

  const doneSegments = chapter.outputs.filter(v => v !== null).length;
  $('segments').textContent = `${doneSegments} / ${chapter.plan.length} segment`;
  $('reader-note').textContent = chapter.status === 'done'
    ? '✓ ĐÃ LƯU BẢN DỊCH'
    : chapter.status === 'error'
      ? '⚠ CHƯƠNG DỊCH LỖI'
      : 'CĂN ĐOẠN 1:1 · TỰ ĐỘNG LƯU';

  renderToc();
}

async function refreshAll() {
  const [s, c] = await Promise.all([api('/api/state'), api('/api/chapters')]);
  updateBook(s.book);
  chapters = c;
  renderProgress(s.progress);
  renderToc();
  if (!s.book || !chapters.length) {
    selected = null;
    $('reader-empty').hidden = false;
    $('reading-panes').hidden = true;
    $('chapter-single-ops').hidden = true;
    $('chapter-index').textContent = '';
    $('chapter-title').textContent = 'Chưa chọn chương';
    const sub = $('chapter-subtitle');
    if (sub) {
      sub.textContent = '';
      sub.style.display = 'none';
    }
  }
  return s;
}

// ----------------- IMPORT LOGIC -----------------
async function importFile(file) {
  if (!file) return;
  if (state.progress.active) throw new Error('Hãy dừng job hiện tại trước khi nạp truyện khác.');
  if (!/\.(txt|epub)$/i.test(file.name)) throw new Error('Chỉ hỗ trợ tệp TXT hoặc EPUB.');
  if (state.book && !confirm('Nạp truyện mới sẽ thay thế truyện và bản dịch đang lưu. Tiếp tục?')) return;
  if (file.size > 50 * 1024 * 1024) throw new Error('File tối đa 50 MB.');

  busy = true;
  renderProgress(state.progress);
  notice('Đang đọc và tách chương…');
  try {
    const fd = new FormData();
    fd.append('file', file);
    await api('/api/upload', fd);
    selected = null;
    visible = 100;
    await refreshAll();
    if (chapters.length) await selectChapter(chapters[0].id);
    notice(`Đã nạp ${chapters.length} chương. Chọn model rồi bấm "Bắt đầu dịch".`);
  } finally {
    busy = false;
    renderProgress(state.progress);
    $('file').value = '';
  }
}

$('file').onchange = e => safe(() => importFile(e.target.files[0]));
$('empty-upload').onclick = () => $('file').click();
$('dropzone').onkeydown = e => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    $('file').click();
  }
};

for (const event of ['dragenter', 'dragover']) {
  $('dropzone').addEventListener(event, e => {
    e.preventDefault();
    $('dropzone').classList.add('drag');
  });
}
for (const event of ['dragleave', 'drop']) {
  $('dropzone').addEventListener(event, e => {
    e.preventDefault();
    $('dropzone').classList.remove('drag');
    if (event === 'drop') safe(() => importFile(e.dataTransfer.files[0]));
  });
}

$('path-form').onsubmit = e => {
  e.preventDefault();
  safe(async () => {
    if (state.book && !confirm('Thay thế truyện và bản dịch đang lưu?')) return;
    busy = true;
    renderProgress(state.progress);
    try {
      await api('/api/load-path', { path: $('path').value });
      selected = null;
      await refreshAll();
      if (chapters.length) await selectChapter(chapters[0].id);
      notice('Đã nạp truyện từ máy chạy backend.');
    } finally {
      busy = false;
      renderProgress(state.progress);
    }
  });
};

// ----------------- TRANSLATION CONTROLS -----------------
$('start').onclick = () => safe(async () => {
  const batch = Number($('batch').value);
  if (!Number.isInteger(batch) || batch < 1 || batch > 64) {
    throw new Error('Batch size phải từ 1 đến 64.');
  }
  if ($('reset').checked && !confirm('Xóa toàn bộ bản dịch hiện tại và dịch lại từ đầu?')) {
    return;
  }
  if ($('engine').value.startsWith('space') && !confirm('Chế độ Space gửi nội dung truyện tới Hugging Face để dịch trực tuyến. Tiếp tục?')) {
    return;
  }

  const selectedChunkMode = document.querySelector('input[name="chunk_mode"]:checked')?.value || 'sentence';
  const p = await api('/api/translate/start', {
    engine: $('engine').value,
    glossary: $('glossary').value,
    batch_size: batch,
    reset: $('reset').checked,
    honorific_mode: $('opt-honorific').checked ? 'safe' : 'off',
    pronoun_harmonizer: $('opt-pronoun').checked,
    normalize_t2s: $('normalize-mode').value !== 'none',
    beam_size: Number($('beam-size').value) || 2,
    chunk_mode: selectedChunkMode,
    normalize_mode: $('normalize-mode').value || 'auto'
  });


  $('reset').checked = false;
  renderProgress(p);
  notice('Bắt đầu dịch truyện…');
});

$('pause').onclick = () => safe(async () => {
  const action = state.progress.status === 'paused' ? 'resume' : 'pause';
  renderProgress(await api('/api/translate/' + action, {}));
});

$('stop').onclick = () => safe(async () => {
  if (confirm('Dừng job? Các đoạn đã dịch vẫn được lưu trên máy để tiếp tục sau.')) {
    renderProgress(await api('/api/translate/stop', {}));
  }
});

// Delete Book (Clear Library)
$('btn-delete-book').onclick = () => safe(async () => {
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi xóa truyện.', true);
    return;
  }
  const bookTitle = state.book ? state.book.title : 'truyện này';
  if (!confirm(`Bạn có chắc chắn muốn xóa toàn bộ dữ liệu truyện "${bookTitle}"? Thao tác này sẽ xóa sạch nguyên tác và các chương đã dịch.`)) {
    return;
  }
  await api('/api/book/delete', {});
  selected = null;
  selectedChapterIds.clear();
  isSelectMode = false;
  $('btn-toggle-select').classList.remove('active');
  $('toc-batch-bar').hidden = true;
  await refreshAll();
  notice('✓ Đã xóa toàn bộ dữ liệu truyện.');
});

// TOC Chapter Multi-select
$('btn-toggle-select').onclick = () => {
  isSelectMode = !isSelectMode;
  $('btn-toggle-select').classList.toggle('active', isSelectMode);
  $('toc-batch-bar').hidden = !isSelectMode;
  if (!isSelectMode) {
    selectedChapterIds.clear();
  }
  updateBatchCount();
  renderToc();
};

$('btn-select-all').onclick = () => {
  const query = $('search').value.toLowerCase();
  const filtered = chapters.filter(c => (c.title + ' ' + (c.translated_title || '') + ' ' + c.position).toLowerCase().includes(query));
  filtered.forEach(c => selectedChapterIds.add(c.id));
  updateBatchCount();
  renderToc();
};

$('btn-deselect-all').onclick = () => {
  selectedChapterIds.clear();
  updateBatchCount();
  renderToc();
};

$('btn-reset-selected').onclick = () => safe(async () => {
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi đặt lại chương.', true);
    return;
  }
  const ids = Array.from(selectedChapterIds);
  if (!ids.length) {
    notice('Chưa chọn chương nào để xóa bản dịch.');
    return;
  }
  if (!confirm(`Xóa bản dịch của ${ids.length} chương đã chọn để dịch lại?`)) return;
  await api('/api/chapters/reset', { ids });
  selectedChapterIds.clear();
  updateBatchCount();
  await refreshAll();
  if (selected && ids.includes(selected)) {
    await selectChapter(selected, true);
  }
  notice(`✓ Đã xóa bản dịch của ${ids.length} chương đã chọn.`);
});

$('btn-delete-selected').onclick = () => safe(async () => {
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi xóa chương.', true);
    return;
  }
  const ids = Array.from(selectedChapterIds);
  if (!ids.length) {
    notice('Chưa chọn chương nào để xóa.');
    return;
  }
  if (!confirm(`Xóa hẳn ${ids.length} chương đã chọn khỏi truyện? Thao tác này sẽ xóa cả nguyên tác các chương này.`)) return;
  await api('/api/chapters/delete', { ids });
  selectedChapterIds.clear();
  updateBatchCount();
  await refreshAll();
  if (selected && ids.includes(selected)) {
    if (chapters.length) {
      await selectChapter(chapters[0].id);
    } else {
      selected = null;
      $('reader-empty').hidden = false;
      $('reading-panes').hidden = true;
      $('chapter-single-ops').hidden = true;
    }
  }
  notice(`✓ Đã xóa ${ids.length} chương khỏi truyện.`);
});

// Single Chapter Actions (Reset / Delete)
$('btn-reset-current').onclick = () => safe(async () => {
  if (!selected) return;
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi đặt lại chương.', true);
    return;
  }
  const chapter = chapters.find(c => c.id === selected);
  const chapName = chapter ? (chapter.translated_title || chapter.title) : 'chương này';
  if (!confirm(`Xóa bản dịch của "${chapName}" để dịch lại?`)) return;
  await api(`/api/chapters/${selected}/reset`, {});
  await refreshAll();
  await selectChapter(selected, true);
  notice(`✓ Đã xóa bản dịch của "${chapName}".`);
});

$('btn-delete-current').onclick = () => safe(async () => {
  if (!selected) return;
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi xóa chương.', true);
    return;
  }
  const chapter = chapters.find(c => c.id === selected);
  const chapName = chapter ? (chapter.translated_title || chapter.title) : 'chương này';
  if (!confirm(`Xóa hẳn "${chapName}" khỏi truyện? Thao tác này sẽ xóa cả nguyên tác chương này.`)) return;
  const currentIdx = chapters.findIndex(c => c.id === selected);
  await api(`/api/chapters/${selected}/delete`, {});
  await refreshAll();
  if (chapters.length) {
    const nextIdx = Math.min(currentIdx, chapters.length - 1);
    await selectChapter(chapters[nextIdx].id);
  } else {
    selected = null;
    $('reader-empty').hidden = false;
    $('reading-panes').hidden = true;
    $('chapter-single-ops').hidden = true;
  }
  notice(`✓ Đã xóa "${chapName}" khỏi truyện.`);
});

$('search').oninput = () => {
  visible = 100;
  renderToc();
};

$('prev').onclick = () => safe(() => {
  const idx = chapters.findIndex(c => c.id === selected);
  if (idx > 0) selectChapter(chapters[idx - 1].id);
});

$('next').onclick = () => safe(() => {
  const idx = chapters.findIndex(c => c.id === selected);
  if (idx >= 0 && idx < chapters.length - 1) selectChapter(chapters[idx + 1].id);
});

// Keyboard navigation
window.addEventListener('keydown', e => {
  if (['input', 'textarea', 'select'].includes(document.activeElement.tagName.toLowerCase())) return;
  if (e.key === '[' || e.key === 'ArrowLeft') {
    if (!$('prev').disabled) $('prev').click();
  } else if (e.key === ']' || e.key === 'ArrowRight') {
    if (!$('next').disabled) $('next').click();
  }
});

// Synchronized scrolling
let syncFrame = false;
for (const [from, to] of [['source-pane', 'target-pane'], ['target-pane', 'source-pane']]) {
  $(from).onscroll = () => {
    if (!$('sync').checked || syncFrame || currentViewMode !== 'parallel') return;
    syncFrame = true;
    $(to).scrollTop = $(from).scrollTop;
    requestAnimationFrame(() => syncFrame = false);
  };
}

window.addEventListener('resize', equalizeRows);
document.fonts.ready.then(equalizeRows);

// ----------------- WEBSOCKET & SYNC -----------------
let updating = false, dirty = false;
async function handleEvent(event) {
  if (event.progress) renderProgress(event.progress);
  if (event.type === 'error') notice(event.message || 'Chương dịch lỗi.', true);
  if (event.type === 'book_deleted') {
    selected = null;
    selectedChapterIds.clear();
    isSelectMode = false;
    $('btn-toggle-select').classList.remove('active');
    $('toc-batch-bar').hidden = true;
    updateBook(null);
  }
  if (updating) {
    dirty = true;
    return;
  }
  updating = true;
  try {
    do {
      dirty = false;
      await refreshAll();
      if (selected) await selectChapter(selected, true);
    } while (dirty);
  } catch (e) {
    notice(e.message, true);
  } finally {
    updating = false;
  }
}

function connect() {
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/progress`);
  ws.onopen = () => {
    retry = 1000;
    $('connection').textContent = '● Đã kết nối';
  };
  ws.onmessage = e => {
    try {
      handleEvent(JSON.parse(e.data));
    } catch {}
  };
  ws.onclose = () => {
    $('connection').textContent = '○ Đang kết nối lại';
    setTimeout(connect, retry);
    retry = Math.min(15000, retry * 2);
  };
  ws.onerror = () => ws.close();
}

// ----------------- INITIALIZATION -----------------
safe(async () => {
  setFontSize(currentFontSize);
  setViewMode(currentViewMode);
  await Promise.all([loadHardware(), loadModels()]);
  const s = await refreshAll();

  if (s.book) {
    try {
      const c = JSON.parse(s.book.config);
      if (c.engine) $('engine').value = c.engine === 'local' ? 'HachimiMT-60-QT' : c.engine;
      $('glossary').value = c.glossary || '';
      $('batch').value = c.batch_size || 8;
      if (c.honorific_mode !== undefined) $('opt-honorific').checked = c.honorific_mode !== 'off';
      if (c.pronoun_harmonizer !== undefined) $('opt-pronoun').checked = !!c.pronoun_harmonizer;
      if (c.beam_size) {
        $('beam-size').value = c.beam_size;
        $('beam-val').textContent = c.beam_size;
      }
      if (c.chunk_mode) {
        setChunkMode(c.chunk_mode);
      }
      if (c.normalize_mode) {
        $('normalize-mode').value = c.normalize_mode;
      }
      updateModelInfo();

    } catch {}
    if (chapters.length) {
      await selectChapter(chapters.find(c => c.status !== 'done')?.id || chapters[0].id);
    }
  }
  connect();
});

// Periodic fallback polling
setInterval(() => safe(async () => {
  const s = await api('/api/state');
  updateBook(s.book);
  renderProgress(s.progress);
}), 4000);
