'use strict';

const $ = id => document.getElementById(id);
function setIconLabel(element, name, label) {
  const icon = document.createElement('i');
  icon.className = 'fi fi-br-' + name;
  icon.setAttribute('aria-hidden', 'true');
  element.replaceChildren(icon, document.createTextNode(' ' + label));
}
let chapters = [], selected = null, state = { progress: { status: 'ready', active: false } };
let visible = 100, busy = false, ws, retry = 1000;
let chapterRequest = 0, pendingChapter = null;
let availableModels = [];
let currentHardware = null, isDownloadingModel = false;
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

// Keep one instance of every control while arranging the three work areas.
function arrangeStudio() {
  const output = document.querySelector('.output-dirs-hint');
  if ($('book-title-panel') && output && $('encoding')) {
    $('book-title-panel').querySelector('.control-details-body')?.append(output, $('encoding'));
  }

  document.querySelector('.studio-jump').innerHTML = '<a href="#chapter-desk">Danh sách chương</a><a href="#job-inspector">Cấu hình</a><a href="#progress-desk">Tiến trình</a>';
}
arrangeStudio();

let lastActivity = '';
function recordActivity(message, error = false) {
  if (!message || message === lastActivity) return;
  lastActivity = message;
  const log = $('activity-log');
  if (!log) return;
  log.querySelector('.activity-empty')?.remove();
  const item = document.createElement('li');
  const box = document.createElement('span');
  box.className = 'activity-box';
  box.textContent = '';
  const time = document.createElement('time');
  time.textContent = '[' + new Date().toLocaleTimeString('vi-VN', {hour12:false}) + ']';
  const text = document.createElement('span');
  text.textContent = message;
  item.classList.toggle('activity-error', error);
  item.append(box, time, text);
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.append(item);
  while (log.children.length > 100) log.firstElementChild.remove();
  if (atBottom) log.scrollTop = log.scrollHeight;
}

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
const readerAudio = $('audio-player');
function audioTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const minutes = Math.floor(seconds / 60);
  return minutes + ':' + String(Math.floor(seconds % 60)).padStart(2, '0');
}
function updateReaderAudio() {
  const available = !$('chapter-audio-bar').hidden &&
    !!readerAudio.getAttribute('src') && readerAudio.style.display !== 'none';
  $('reader-audio-controls').hidden = !available;
  const duration = Number.isFinite(readerAudio.duration) ? readerAudio.duration : 0;
  $('reader-audio-time').textContent = audioTime(readerAudio.currentTime) + ' / ' + audioTime(duration);
  const seek = $('reader-audio-seek');
  seek.disabled = !available || duration <= 0;
  seek.value = duration > 0 ? readerAudio.currentTime / duration * 100 : 0;
  seek.style.setProperty('--range-fill', seek.value + '%');
  seek.setAttribute('aria-valuetext', audioTime(readerAudio.currentTime) + ' trên ' + audioTime(duration));
  const play = $('reader-audio-play');
  setIconLabel(play, readerAudio.paused ? 'play' : 'pause', '');
  play.setAttribute('aria-label', readerAudio.paused ? 'Phát audio' : 'Tạm dừng audio');
  $('reader-audio-volume').value = readerAudio.volume;
  $('reader-audio-volume').style.setProperty('--range-fill', readerAudio.volume * 100 + '%');
  $('reader-audio-speed').value = String(readerAudio.playbackRate);
}
$('reader').classList.add('has-custom-audio');
for (const event of ['loadedmetadata', 'durationchange', 'timeupdate', 'play', 'pause', 'ended', 'emptied', 'volumechange', 'ratechange']) {
  readerAudio.addEventListener(event, updateReaderAudio);
}
$('reader-audio-play').onclick = () => safe(async () => {
  if (readerAudio.paused) await readerAudio.play();
  else readerAudio.pause();
});
$('reader-audio-seek').oninput = event => {
  if (Number.isFinite(readerAudio.duration) && readerAudio.duration > 0) {
    readerAudio.currentTime = readerAudio.duration * Number(event.target.value) / 100;
    updateReaderAudio();
  }
};
$('reader-audio-volume').oninput = event => readerAudio.volume = Number(event.target.value);
$('reader-audio-speed').onchange = event => readerAudio.playbackRate = Number(event.target.value);
readerAudio.addEventListener('error', () => {
  if (!readerAudio.getAttribute('src')) return;
  $('audio-status-msg').textContent = 'Không phát được audio. Thử tải tệp hoặc tạo lại audio.';
  $('audio-status-msg').className = 'audio-status-msg error';
});

function setFontSize(size) {
  currentFontSize = Number.isFinite(size) ? Math.max(13, Math.min(26, size)) : 17;
  document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');
  $('font-val').textContent = currentFontSize + 'px';
  localStorage.setItem('novel_font_size', currentFontSize);
  equalizeRows();
}
$('font-dec').onclick = () => setFontSize(currentFontSize - 1);
$('font-inc').onclick = () => setFontSize(currentFontSize + 1);

function setViewMode(mode) {
  mode = ['parallel', 'target', 'source'].includes(mode) ? mode : 'parallel';
  currentViewMode = mode;
  $('reader').dataset.view = mode;
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
    btn.setAttribute('aria-pressed', String(btn.dataset.mode === mode));
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
$('copy-btn').onclick = () => safe(async () => {
  const chapter = chapters.find(c => c.id === selected);
  if (!chapter) {
    notice('Chưa chọn chương để sao chép.');
    return;
  }
  const paras = Array.from($('target-pane').querySelectorAll('.para:not(.waiting)'))
    .map(p => p.textContent.trim())
    .filter(Boolean);

  const fullText = (chapter.translated_title || chapter.title) + '\n\n' + paras.join('\n\n');
  if (!paras.length) throw new Error('Chương này chưa có bản dịch để sao chép.');
  if (!navigator.clipboard?.writeText) throw new Error('Trình duyệt không hỗ trợ sao chép ở địa chỉ này. Hãy mở web qua HTTPS hoặc localhost.');
  await navigator.clipboard.writeText(fullText);
  notice('Đã sao chép bản dịch chương vào Clipboard!');
});

// Workspace navigation: chapter desk and full-width reader.
const workspace = document.querySelector('.workspace');
function showWorkspace(page, navId, title) {
  workspace.dataset.page = page;
  workspace.classList.toggle('show-reader', page === 'reader');
  $('settings-modal').hidden = page !== 'settings';
  $('monitor-page').hidden = page !== 'monitor';
  $('workspace-title').textContent = title;
  document.querySelectorAll('.app-nav .nav-item:not([data-theme-toggle])').forEach(button => {
    const active = button.id === navId;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  closeNavigation(true);
}
$('tab-sidebar').onclick = () => showWorkspace('studio', 'tab-sidebar', 'Dịch & audio');
$('tab-reader').onclick = () => {
  showWorkspace('reader', 'tab-reader', 'Đọc & đối chiếu');
  requestAnimationFrame(equalizeRows);
};

$('back-to-studio').onclick = () => {
  $('tab-sidebar').click();
  $('search').focus({preventScroll:true});
  document.querySelector('.toc-panel').scrollIntoView({block:'start'});
};

// Sidebar and theme preferences belong to the application shell.
function closeNavigation(returnFocus = false) {
  const wasOpen = document.body.classList.contains('nav-open');
  document.body.classList.remove('nav-open');
  $('mobile-nav-toggle').setAttribute('aria-expanded', 'false');
  workspace.inert = false;
  document.querySelector('.topbar').inert = false;
  if (returnFocus && wasOpen) $('mobile-nav-toggle').focus({preventScroll:true});
}
$('mobile-nav-toggle').onclick = () => {
  document.body.classList.add('nav-open');
  $('mobile-nav-toggle').setAttribute('aria-expanded', 'true');
  $('toggle-navigation').title = 'Đóng menu điều hướng';
  $('toggle-navigation').setAttribute('aria-label', 'Đóng menu điều hướng');
  workspace.inert = true;
  document.querySelector('.topbar').inert = true;
  $('toggle-navigation').focus({preventScroll:true});
};
$('close-navigation').onclick = () => closeNavigation(true);
function setNavigationCollapsed(collapsed) {
  document.body.classList.toggle('nav-collapsed', collapsed);
  $('toggle-navigation').setAttribute('aria-expanded', String(!collapsed));
  $('toggle-navigation').title = collapsed ? 'Mở rộng menu' : 'Thu gọn menu';
  $('toggle-navigation').setAttribute('aria-label', $('toggle-navigation').title);
  localStorage.setItem('novel_nav_collapsed', String(collapsed));
}
$('toggle-navigation').onclick = () => {
  if (window.matchMedia('(max-width: 900px)').matches) closeNavigation(true);
  else setNavigationCollapsed(!document.body.classList.contains('nav-collapsed'));
  requestAnimationFrame(equalizeRows);
};
function setTheme(theme) {
  NovelTheme.apply(theme, localStorage.getItem('novel_accent') || 'violet');
  localStorage.setItem('novel_theme', theme);
  $('theme-label').textContent = theme === 'dark' ? 'Chế độ sáng' : 'Chế độ tối';
  document.querySelectorAll('[data-theme-toggle]').forEach(button => {
    button.setAttribute('aria-label', theme === 'dark' ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối');
    button.title = button.getAttribute('aria-label');
  });
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
  });
}
const ACCENT_COLORS = NovelTheme.presets;
function setAccent(choice) {
  const {choice: normalized, seed: color} = NovelTheme.apply(document.documentElement.dataset.theme, choice);
  const preset = Object.hasOwn(ACCENT_COLORS, normalized);
  const selected = preset ? normalized : 'custom';
  localStorage.setItem('novel_accent', normalized);
  document.querySelectorAll('[data-accent-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.accentChoice === (color && !preset ? 'custom' : selected)));
    const swatch = button.querySelector('.accent-swatch');
    if (swatch) swatch.style.setProperty('--swatch', ACCENT_COLORS[button.dataset.accentChoice]);
  });
  const customInput = $('custom-accent');
  if (customInput && color) customInput.value = color;
  else if (customInput) customInput.value = ACCENT_COLORS.rose;
}
document.querySelectorAll('[data-theme-toggle]').forEach(button => {
  button.onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
});
document.querySelectorAll('[data-theme-choice]').forEach(button => {
  button.onclick = () => setTheme(button.dataset.themeChoice);
});
document.querySelectorAll('[data-accent-choice]').forEach(button => {
  button.onclick = () => setAccent(button.dataset.accentChoice === 'custom' ? $('custom-accent').value : button.dataset.accentChoice);
});
if ($('custom-accent')) $('custom-accent').oninput = event => setAccent(event.target.value);
if ($('btn-reset-appearance')) $('btn-reset-appearance').onclick = () => {
  setTheme('dark');
  setAccent('violet');
};
for (const [id, tab] of [
  ['nav-translation', 'tab-translation'],
  ['nav-audio', 'tab-tts'],
  ['nav-storage', 'tab-cloud'],
  ['nav-settings', 'tab-cache']
]) {
  $(id).onclick = () => { closeNavigation(true); openSettingsPage(tab, id); };
}
$('nav-monitor').onclick = () => {
  showWorkspace('monitor', 'nav-monitor', 'Giám sát');
  $('monitor-page-heading').focus({preventScroll:true});
};
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('nav-open')) return;
  if (event.key === 'Escape') { event.preventDefault(); closeNavigation(true); return; }
  if (event.key !== 'Tab') return;
  const items = [...$('app-navigation').querySelectorAll('button')].filter(el => el.getClientRects().length && !el.disabled);
  const first = items[0], last = items[items.length-1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
window.matchMedia('(max-width: 900px)').addEventListener('change', () => {
  closeNavigation();
  setNavigationCollapsed(document.body.classList.contains('nav-collapsed'));
});
setTheme(document.documentElement.dataset.theme);
setAccent(localStorage.getItem('novel_accent') || 'violet');
setNavigationCollapsed(localStorage.getItem('novel_nav_collapsed') === 'true');

// Export buttons retain their download links; Hugging Face is the default destination.
let huggingfaceExportBusy = false;

function showHuggingFaceModal(res) {
  const dialog = $('huggingface-result-dialog');
  if (!dialog) return;
  const filenameEl = $('hf-dialog-filename');
  const urlInput = $('hf-dialog-url');
  const openLink = $('hf-dialog-open-link');
  if (filenameEl) filenameEl.textContent = `Tệp: ${res.filename} (${res.size_mb || (res.size_bytes / (1024 * 1024)).toFixed(1)} MB)`;
  if (urlInput) urlInput.value = res.url;
  if (openLink) openLink.href = res.url;
  dialog.showModal();
}

async function exportToHuggingFace(format) {
  if (huggingfaceExportBusy) {
    notice('Đang tải lên Hugging Face. Vui lòng đợi...');
    return;
  }
  huggingfaceExportBusy = true;
  notice(`Đang xuất và tải ${format.toUpperCase()} lên Hugging Face...`);
  try {
    const res = await api('/api/export/huggingface/' + format, {}, 'POST');
    if (res.ok) {
      notice(`Đã tải lên Hugging Face: ${res.url}`);
      showHuggingFaceModal(res);
    } else {
      throw new Error(res.message || 'Lỗi không xác định khi upload Hugging Face.');
    }
  } catch (err) {
    const msg = err.message || String(err);
    if (msg.includes('HF_TOKEN') || msg.includes('401')) {
      notice('Hãy cấu hình HF_TOKEN có quyền ghi phía máy chủ.');
      openSettingsPage('tab-cloud');
    } else {
      notice(`Lỗi Hugging Face: ${msg}`);
    }
  } finally {
    huggingfaceExportBusy = false;
  }
}

async function loadExportDestination() {
  const select = $('export-destination');
  if (!select) return;
  select.value = 'huggingface';
  localStorage.removeItem('novel_export_destination');
}
for (const [id, format] of [['export-txt', 'txt'], ['export-epub', 'epub'], ['export-audio', 'audio']]) {
  $(id).addEventListener('click', event => {
    if ($('export-destination').value !== 'huggingface') return;
    event.preventDefault();
    exportToHuggingFace(format);
  });
}

// ----------------- HARDWARE & MODELS -----------------
async function loadHardware() {
  try {
    currentHardware = await api('/api/hardware');
    if (currentHardware) {
      const gpu = currentHardware.gpu_name || 'Không phát hiện';
      $('gpu-pill').textContent = `GPU: ${gpu}`;
      $('gpu-pill').title = `GPU: ${gpu}`;
      if (currentHardware.batch_size && !$('batch').value) {
        $('batch').value = Math.max(1, Math.min(1024, currentHardware.batch_size));
      }
      updateModelInfo();
    }
  } catch {}
  if (!$('batch').value) $('batch').value = 8;
}

async function loadModels() {
  try {
    const selectedBackend = document.querySelector('input[name="backend"]:checked')?.value || 'ct2';
    availableModels = await api('/api/models?backend=' + encodeURIComponent(selectedBackend));
    const select = $('engine');
    const curVal = select.value || 'HachimiMT-60-QT';
    select.replaceChildren();

    const isTorch = selectedBackend === 'transformers' || selectedBackend === 'pytorch';
    const localGroup = document.createElement('optgroup');
    localGroup.label = isTorch
      ? 'Model PyTorch trên máy (Đã tải đủ)'
      : 'Model CTranslate2 trên máy (Đã tải đủ)';
    const spaceGroup = document.createElement('optgroup');
    spaceGroup.label = 'Trực tuyến Hugging Face Space (Online)';

    availableModels.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.id;
      const sizeText = m.size_mb > 0 ? ` (~${m.size_mb} MB)` : '';
      opt.textContent = `${m.name.replace(/^🌐\s*/u, '')}${sizeText}`;
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
  updateControlSummary();
  const key = $('engine').value;
  const m = availableModels.find(x => x.id === key);
  const badge = $('model-badge');
  const btnBadge = $('btn-download-model');
  const downloadBox = $('engine-download-box');
  const btnAction = $('btn-download-model-action');
  const gpuHint = $('engine-gpu-hint');
  const noteEl = $('engine-note');

  const selectedBackend = document.querySelector('input[name="backend"]:checked')?.value || 'ct2';
  const isTorch = selectedBackend === 'transformers' || selectedBackend === 'pytorch';
  const backendLabel = isTorch ? 'PyTorch' : 'CTranslate2';

  if (!m) {
    if (noteEl) noteEl.style.display = 'none';
    if (btnBadge) btnBadge.style.display = 'none';
    if (downloadBox) downloadBox.style.display = 'none';
    return;
  }

  if (noteEl) noteEl.style.display = !m.downloaded && m.id !== 'space' && !m.id.startsWith('space:') ? 'flex' : 'none';

  if (m.id === 'space' || m.id.startsWith('space:')) {
    badge.className = 'badge badge-success';
    badge.textContent = 'Space Online';
    if (btnBadge) btnBadge.style.display = 'none';
    if (downloadBox) downloadBox.style.display = 'none';
  } else if (m.downloaded) {
    badge.className = 'badge badge-success';
    badge.textContent = `Sẵn sàng (${backendLabel})`;
    if (btnBadge) btnBadge.style.display = 'none';
    if (downloadBox) downloadBox.style.display = 'none';
  } else {
    badge.className = 'badge badge-warning';
    badge.textContent = `Chưa tải (${backendLabel})`;

    if (btnBadge) {
      btnBadge.style.display = 'inline-block';
      btnBadge.innerHTML = '<i aria-hidden="true" class="fi fi-br-download"></i> Tải model';
      btnBadge.title = `Tải model ${key} (${backendLabel})`;
    }
    if (downloadBox) {
      downloadBox.style.display = 'flex';
      if (btnAction) {
        btnAction.innerHTML = `<i aria-hidden="true" class="fi fi-br-download"></i> Tải model ${backendLabel} (~${m.size_mb || 58} MB)`;
      }
      if (gpuHint) {
        gpuHint.style.display = 'inline-flex';
        const hasGpu = currentHardware && (currentHardware.is_gpu || currentHardware.has_discrete_gpu);
        if (hasGpu) {
          gpuHint.className = 'gpu-hint';
          const gpuLabel = currentHardware.gpu_name || 'NVIDIA GPU';
          const vramLabel = currentHardware.vram_gb ? ` (${currentHardware.vram_gb} GB)` : '';
          setIconLabel(gpuHint, 'bolt', `GPU rời khả dụng: ${gpuLabel}${vramLabel} — Đề xuất tải để tăng tốc!`);
        } else {
          gpuHint.className = 'gpu-hint no-gpu';
          setIconLabel(gpuHint, 'info', 'Đang chạy CPU. Bấm nút để tải model offline về máy.');
        }
      }
    }
  }
}

async function downloadCurrentModel() {
  if (isDownloadingModel) return;
  const select = $('engine');
  const key = select.value;
  if (!key || key.startsWith('space')) return;
  const selectedBackend = document.querySelector('input[name="backend"]:checked')?.value || 'ct2';
  const isTorch = selectedBackend === 'transformers' || selectedBackend === 'pytorch';
  const backendLabel = isTorch ? 'PyTorch' : 'CTranslate2';

  const btnAction = $('btn-download-model-action');
  const btnBadge = $('btn-download-model');
  const origActionText = btnAction ? btnAction.textContent : '';
  const origBadgeText = btnBadge ? btnBadge.textContent : '';

  isDownloadingModel = true;
  if (btnAction) {
    btnAction.disabled = true;
    setIconLabel(btnAction, 'hourglass-end', `Đang tải ${key} (${backendLabel})...`);
  }
  if (btnBadge) {
    btnBadge.disabled = true;
    setIconLabel(btnBadge, 'hourglass-end', 'Đang tải...');
  }

  notice(`Đang tải model ${key} (${backendLabel}) từ Hugging Face... Vui lòng đợi trong giây lát.`);

  try {
    const res = await api('/api/models/download', {
      model_id: key,
      backend: selectedBackend
    });
    notice(res.message || 'Đã tải xong model!');
    await loadModels();
  } catch (err) {
    notice(err.message || 'Lỗi khi tải model.', true);
  } finally {
    isDownloadingModel = false;
    if (btnAction) {
      btnAction.disabled = false;
      btnAction.textContent = origActionText;
    }
    if (btnBadge) {
      btnBadge.disabled = false;
      btnBadge.textContent = origBadgeText;
    }
    updateModelInfo();
  }
}

if ($('btn-download-model')) $('btn-download-model').onclick = () => downloadCurrentModel();
if ($('btn-download-model-action')) $('btn-download-model-action').onclick = () => downloadCurrentModel();
$('engine').onchange = () => updateModelInfo();


// ----------------- TTS VOICES & AUDIO CONFIG -----------------
let availableVoices = [];

async function loadVoices() {
  try {
    availableVoices = await api('/api/voices?tts_engine=' + encodeURIComponent(($('modal-tts-engine') || $('tts-engine'))?.value || 'piper'));
    const select1 = $('voice-select');
    const select2 = $('modal-voice');
    if (!select1 && !select2) return;

    const curVal = (select1 ? select1.value : '') || (select2 ? select2.value : '') || '';
    const defaultVoice = availableVoices.find(v => v.is_default)?.id || availableVoices[0]?.id;

    const buildOptions = (targetSelect) => {
      if (!targetSelect) return;
      targetSelect.replaceChildren();

      const femaleGrp = document.createElement('optgroup');
      femaleGrp.label = 'Giọng Nữ';
      const maleGrp = document.createElement('optgroup');
      maleGrp.label = 'Giọng Nam';
      const otherGrp = document.createElement('optgroup');
      otherGrp.label = 'Khác';

      availableVoices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = v.is_default ? `${v.name} (Mặc định)` : v.name;
        if (v.gender === 'female') {
          femaleGrp.append(opt);
        } else if (v.gender === 'male') {
          maleGrp.append(opt);
        } else {
          otherGrp.append(opt);
        }
      });

      if (femaleGrp.children.length) targetSelect.append(femaleGrp);
      if (maleGrp.children.length) targetSelect.append(maleGrp);
      if (otherGrp.children.length) targetSelect.append(otherGrp);

      if (availableVoices.some(v => v.id === curVal)) {
        targetSelect.value = curVal;
      } else { targetSelect.value = defaultVoice; }
    };

    buildOptions(select1);
    buildOptions(select2);
  } catch (e) {
    console.error('Error loading voices:', e); throw e;
  }
}

if ($('voice-select')) {
  $('voice-select').onchange = () => {
    if ($('modal-voice')) $('modal-voice').value = $('voice-select').value;
  };
}
if ($('modal-voice')) {
  $('modal-voice').onchange = () => {
    if ($('voice-select')) $('voice-select').value = $('modal-voice').value;
  };
}


function buildAudioPayload() {
 return {
   tts_engine: ($('modal-tts-engine') || $('tts-engine'))?.value || 'piper',
   voice_id: ($('modal-voice') || $('voice-select'))?.value || 'ngochuyennew',
   audio_speed: Number($('audio-speed')?.value || 1.0),
   noise_scale: Number($('modal-noise-scale')?.value || 0.667),
   noise_w_scale: Number($('modal-noise-w')?.value || 0.8),
   audio_format: ($('modal-audio-format') || $('audio-format'))?.value || 'mp3',
   audio_bitrate: $('modal-audio-bitrate')?.value || '96k',
   audio_sample_rate: Number($('audio-sample-rate')?.value || 0),
   vieneu_temperature: Number($('vieneu-temperature')?.value || 0.8),
   vieneu_top_p: Number($('vieneu-top-p')?.value || 0.95),
   vieneu_batch_size: Number($('vieneu-batch-size')?.value || 8)
 };
}
function updateTtsCapabilities() {
 const vie = (($('modal-tts-engine') || $('tts-engine'))?.value) === 'vieneu';
 const format = ($('modal-audio-format') || $('audio-format'))?.value || 'mp3';
 if ($('piper-noise-controls')) $('piper-noise-controls').hidden = vie;
 if ($('vieneu-controls')) $('vieneu-controls').hidden = !vie;
 if ($('emotion-preset')) $('emotion-preset').closest('.audio-cfg-row')?.classList.toggle('hidden', vie);
 if ($('audio-workers')) { $('audio-workers').disabled = vie; if (vie) $('audio-workers').value = '1'; }
 if ($('audio-concurrency-hint')) $('audio-concurrency-hint').textContent = vie ? 'VieNeu dùng một model chung, xử lý từng chương. Tăng Batch đoạn / GPU trong phần Lấy mẫu VieNeu để gộp đoạn trong chương.' : 'Piper: bật pipeline để chạy nhiều chương. Thử 2–4 trước; mỗi worker nạp một phiên riêng, dùng thêm VRAM.';
 if ($('modal-audio-bitrate')) $('modal-audio-bitrate').disabled = (format === 'wav');
 if ($('audio-sample-rate')) {
   $('audio-sample-rate').disabled = (format === 'opus');
   if (format === 'opus') $('audio-sample-rate').value = '48000';
 }
 const low = format === 'mp3' && [22050, 24000].includes(Number($('audio-sample-rate')?.value));
 if ($('modal-audio-bitrate')) {
   const opt192 = $('modal-audio-bitrate').querySelector('option[value="192k"]');
   if (opt192) opt192.disabled = low;
   if (low && $('modal-audio-bitrate').value === '192k') $('modal-audio-bitrate').value = '128k';
 }
 if ($('audio-output-hint')) $('audio-output-hint').textContent = (vie ? 'VieNeu gốc: 48 kHz. ' : 'Piper: tần số gốc theo model. ') + 'Opus: 48 kHz; MP3 192 kbps: 44.1/48 kHz.';
}
async function applyAudioConfig(c) {
 if ($('modal-tts-engine')) $('modal-tts-engine').value = c.tts_engine || 'piper';
 if ($('tts-engine')) $('tts-engine').value = c.tts_engine || 'piper';
 await loadVoices();
 const voiceId = c.voice_id;
 if (voiceId && availableVoices.some(v => v.id === voiceId)) {
   if ($('modal-voice')) $('modal-voice').value = voiceId;
   if ($('voice-select')) $('voice-select').value = voiceId;
 }
 const speed = Number(c.audio_speed ?? 1);
 if ($('audio-speed')) {
   let option = [...$('audio-speed').options].find(o => Number(o.value) === speed);
   if (!option) { option = new Option(`${speed}x`, String(speed)); $('audio-speed').add(option); }
   $('audio-speed').value = option.value;
 }
 setEmotion(c.noise_scale ?? 0.667, c.noise_w_scale ?? 0.8);
 if ($('modal-audio-format')) $('modal-audio-format').value = c.audio_format || 'mp3';
 if ($('audio-format')) $('audio-format').value = c.audio_format || 'mp3';
 if ($('modal-audio-bitrate')) $('modal-audio-bitrate').value = c.audio_bitrate || '96k';
 if ($('audio-sample-rate')) $('audio-sample-rate').value = String(c.audio_sample_rate ?? 0);
 if ($('vieneu-temperature')) $('vieneu-temperature').value = c.vieneu_temperature ?? 0.8;
 if ($('vieneu-top-p')) $('vieneu-top-p').value = c.vieneu_top_p ?? 0.95;
 if ($('vieneu-batch-size')) $('vieneu-batch-size').value = c.vieneu_batch_size ?? 8;
 updateTtsCapabilities();
}
$('audio-sample-rate').onchange=updateTtsCapabilities;
for (const id of ['tts-engine', 'modal-tts-engine']) {
  if ($(id)) $(id).onchange = () => safe(async () => {
    if ($('tts-engine')) $('tts-engine').value = $(id).value;
    if ($('modal-tts-engine')) $('modal-tts-engine').value = $(id).value;
    await loadVoices();
    updateTtsCapabilities();
  });
}

// ----------------- EMOTION PRESETS & SLIDERS -----------------
function setEmotion(noiseScale, noiseW, presetName) {
  if ($('modal-noise-scale')) {
    $('modal-noise-scale').value = noiseScale;
    if ($('noise-scale-val')) $('noise-scale-val').textContent = Number(noiseScale).toFixed(2);
  }
  if ($('modal-noise-w')) {
    $('modal-noise-w').value = noiseW;
    if ($('noise-w-val')) $('noise-w-val').textContent = Number(noiseW).toFixed(2);
  }
  if ($('emotion-preset') && presetName) {
    $('emotion-preset').value = presetName;
  }
  document.querySelectorAll('.emotion-presets .btn-preset').forEach(btn => {
    const isMatch = Math.abs(parseFloat(btn.dataset.scale) - noiseScale) < 0.03 &&
                    Math.abs(parseFloat(btn.dataset.w) - noiseW) < 0.03;
    btn.classList.toggle('active', isMatch);
  });
}

if ($('emotion-preset')) {
  $('emotion-preset').onchange = () => {
    const val = $('emotion-preset').value;
    if (val === 'calm') setEmotion(0.40, 0.6, 'calm');
    else if (val === 'expressive') setEmotion(0.85, 0.9, 'expressive');
    else if (val === 'dramatic') setEmotion(1.15, 1.0, 'dramatic');
    else setEmotion(0.667, 0.8, 'default');
  };
}

document.querySelectorAll('.emotion-presets .btn-preset').forEach(btn => {
  btn.onclick = () => {
    const s = parseFloat(btn.dataset.scale);
    const w = parseFloat(btn.dataset.w);
    let pName = 'default';
    if (s <= 0.45) pName = 'calm';
    else if (s >= 1.0) pName = 'dramatic';
    else if (s >= 0.8) pName = 'expressive';
    setEmotion(s, w, pName);
  };
});

if ($('modal-noise-scale')) {
  $('modal-noise-scale').oninput = () => {
    const val = parseFloat($('modal-noise-scale').value);
    if ($('noise-scale-val')) $('noise-scale-val').textContent = val.toFixed(2);
    document.querySelectorAll('.emotion-presets .btn-preset').forEach(b => b.classList.remove('active'));
  };
}

if ($('modal-noise-w')) {
  $('modal-noise-w').oninput = () => {
    const val = parseFloat($('modal-noise-w').value);
    if ($('noise-w-val')) $('noise-w-val').textContent = val.toFixed(2);
    document.querySelectorAll('.emotion-presets .btn-preset').forEach(b => b.classList.remove('active'));
  };
}

// Audio format sync
if ($('audio-format') && $('modal-audio-format')) {
  $('audio-format').onchange = () => {
    $('modal-audio-format').value = $('audio-format').value; updateTtsCapabilities();
  };
  $('modal-audio-format').onchange = () => {
    $('audio-format').value = $('modal-audio-format').value; updateTtsCapabilities();
  };
} else if ($('modal-audio-format')) {
  $('modal-audio-format').onchange = updateTtsCapabilities;
}

// ----------------- SETTINGS PAGES & TABS -----------------


let settingsReturnFocus = null, settingsReturnView = 'studio';
function openSettingsPage(tabId = 'tab-translation', triggerNavId = null) {
  if (workspace.dataset.page !== 'settings') {
    settingsReturnFocus = document.activeElement;
    settingsReturnView = workspace.dataset.page || (workspace.classList.contains('show-reader') ? 'reader' : 'studio');
  }
  const defaultNav = {'tab-translation':'nav-translation','tab-tts':'nav-audio','tab-cloud':'nav-storage','tab-cache':'nav-settings'}[tabId] || 'nav-settings';
  const nav = triggerNavId || defaultNav;
  showWorkspace('settings', nav, 'Cài đặt');
  switchSettingsTab(tabId, nav);
  loadHuggingFaceSettings();
  loadMergedGroups();
  $('settings-heading').focus({preventScroll:true});
}
function closeSettingsPage() {
  $({reader:'tab-reader',monitor:'nav-monitor'}[settingsReturnView] || 'tab-sidebar').click();
  if (settingsReturnFocus?.getClientRects().length) settingsReturnFocus.focus({preventScroll:true});
}

function switchSettingsTab(tabId, explicitNav = null) {
  const names = {'tab-translation':'Dịch thuật','tab-tts':'Giọng đọc','tab-cloud':'Lưu trữ','tab-cache':'Cài đặt'};
  const defaultNav = {'tab-translation':'nav-translation','tab-tts':'nav-audio','tab-cloud':'nav-storage','tab-cache':'nav-settings'}[tabId] || 'nav-settings';
  const nav = explicitNav || defaultNav;
  $('settings-heading').textContent = names[tabId] || 'Cài đặt';
  $('settings-modal').dataset.tab = tabId;
  $('btn-save-settings').hidden = ['tab-cloud','tab-cache'].includes(tabId);
  if (workspace.dataset.page === 'settings') showWorkspace('settings', nav, names[tabId] || 'Cài đặt');
  document.querySelectorAll('.modal-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tabId);
    t.setAttribute('aria-selected', String(t.dataset.tab === tabId));
    t.tabIndex = t.dataset.tab === tabId ? 0 : -1;
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.remove('active');
    p.style.display = 'none';
  });
  $('settings-modal').scrollTop = 0;
  const activePane = $(`pane-${tabId}`);
  if (activePane) {
    activePane.classList.add('active');
    activePane.style.display = 'block';
  }
}

if ($('btn-open-settings')) $('btn-open-settings').onclick = () => openSettingsPage('tab-translation');
if ($('link-open-audio-settings')) {
  $('link-open-audio-settings').onclick = (e) => {
    e.preventDefault();
    openSettingsPage('tab-tts');
  };
}
if ($('btn-close-settings')) $('btn-close-settings').onclick = closeSettingsPage;
if ($('btn-cancel-settings')) $('btn-cancel-settings').onclick = closeSettingsPage;
document.querySelectorAll('.modal-tab').forEach(tab => {
  tab.onclick = () => switchSettingsTab(tab.dataset.tab);
  tab.onkeydown = event => {
    const tabs=[...document.querySelectorAll('.settings-nav .modal-tab')];
    if (!['ArrowRight','ArrowLeft','ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
    event.preventDefault();let i=tabs.indexOf(tab);
    i=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(['ArrowRight','ArrowDown'].includes(event.key)?1:-1)+tabs.length)%tabs.length;
    tabs[i].click();tabs[i].focus();
  };
});

// ----------------- HUGGING FACE STORAGE -----------------
const storageState = {path:'', entries:[], selected:new Set(), page:0, view:'list', configured:false, loaded:false, loading:false, busy:false, visible:[]};
let storageRequest = 0;
function storageBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  const units = ['B','KB','MB','GB','TB'];
  let unit = 0;
  while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit++; }
  return bytes.toLocaleString('vi-VN', {maximumFractionDigits:unit ? 1 : 0}) + ' ' + units[unit];
}
function storageIcon(name) {
  const icon = document.createElement('i');
  icon.className = 'fi fi-br-' + name;
  icon.setAttribute('aria-hidden', 'true');
  return icon;
}
function storageDownloadUrl(path) { return '/api/storage/download?path=' + encodeURIComponent(path); }
function updateStorageButtons() {
  const ready = storageState.configured && storageState.loaded && !storageState.loading && !storageState.busy;
  for (const id of ['storage-upload','storage-create-folder','storage-quick-upload','storage-quick-folder']) $(id).disabled = !ready;
  for (const id of ['storage-refresh','storage-quick-refresh','storage-folder-cancel']) $(id).disabled = storageState.busy;
  $('storage-up').disabled = !storageState.path || storageState.busy;
  $('storage-home').disabled = !storageState.path || storageState.busy;
  const selected = storageState.entries.filter(item => storageState.selected.has(item.path));
  $('storage-quick-download').disabled = selected.length !== 1 || selected[0].directory;
  $('storage-selected-count').textContent = selected.length ? 'Đã chọn ' + selected.length + ' mục' : '';
  $('storage-folder-submit').disabled = storageState.busy;
}
function renderStorageFiles() {
  const query = $('storage-search').value.trim().toLocaleLowerCase();
  const filtered = storageState.entries.filter(item => item.name.toLocaleLowerCase().includes(query));
  const pages = Math.max(1, Math.ceil(filtered.length / 20));
  storageState.page = Math.min(storageState.page, pages - 1);
  const visible = filtered.slice(storageState.page * 20, (storageState.page + 1) * 20);
  storageState.visible = visible;
  $('storage-file-rows').replaceChildren();
  $('storage-file-grid').replaceChildren();
  for (const item of visible) {
    const row = document.createElement('tr');
    row.classList.toggle('selected', storageState.selected.has(item.path));
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox'; checkbox.checked = storageState.selected.has(item.path);
    checkbox.setAttribute('aria-label', 'Chọn ' + item.name);
    checkbox.onchange = () => {
      if (checkbox.checked) storageState.selected.add(item.path); else storageState.selected.delete(item.path);
      renderStorageFiles();
    };
    const selection = document.createElement('td'); selection.append(checkbox); row.append(selection);
    const nameCell = document.createElement('td');
    const name = document.createElement('button');
    name.type = 'button'; name.className = 'storage-entry-name';
    name.append(storageIcon(item.directory ? 'folder' : 'document'), document.createTextNode(item.name));
    name.title = item.name;
    name.onclick = () => {
      if (storageState.busy) return;
      if (item.directory) loadStorageDirectory(item.path);
      else { storageState.selected.clear(); storageState.selected.add(item.path); renderStorageFiles(); }
    };
    nameCell.append(name); row.append(nameCell);
    const type = item.directory ? 'Thư mục' : (item.name.includes('.') ? item.name.split('.').pop().toUpperCase() : 'Tệp');
    const updated = item.updated_at ? new Date(item.updated_at).toLocaleString('vi-VN', {timeZone:'Asia/Ho_Chi_Minh', dateStyle:'short', timeStyle:'short'}) : '—';
    for (const value of [item.directory ? '—' : storageBytes(item.size), type, updated]) {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    }
    const actions = document.createElement('td'); actions.className = 'storage-entry-actions';
    if (!item.directory) {
      const download = document.createElement('a');
      download.href = storageDownloadUrl(item.path); download.download = item.name;
      download.title = 'Tải ' + item.name; download.setAttribute('aria-label', download.title);
      download.append(storageIcon('download')); actions.append(download);
    }
    const link = document.createElement('a');
    link.href = 'https://huggingface.co/datasets/uri410/novelreader-storage/' + (item.directory ? 'tree' : 'blob') + '/main/' + item.path.split('/').map(encodeURIComponent).join('/');
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.title = 'Mở ' + item.name + ' trên Hugging Face'; link.setAttribute('aria-label', link.title);
    link.append(storageIcon('arrow-up-right')); actions.append(link); row.append(actions);
    $('storage-file-rows').append(row);
    const tile = document.createElement('div'); tile.className = 'storage-file-tile';
    const tileSelect = checkbox.cloneNode();
    tileSelect.onchange = () => { checkbox.checked = tileSelect.checked; checkbox.onchange(); };
    const tileName = name.cloneNode(true); tileName.onclick = name.onclick;
    const detail = document.createElement('small'); detail.textContent = item.directory ? type : storageBytes(item.size);
    const tileActions = document.createElement('div'); tileActions.className = 'storage-entry-actions';
    for (const link of actions.children) tileActions.append(link.cloneNode(true));
    tile.append(tileSelect, tileName, detail, tileActions); $('storage-file-grid').append(tile);
  }
  $('storage-list-scroll').hidden = storageState.view !== 'list';
  $('storage-file-grid').hidden = storageState.view !== 'grid';
  $('storage-file-count').textContent = `${filtered.length} mục` + (storageState.truncated ? ' · Tối đa 500 mục' : '');
  $('storage-page-number').textContent = `${storageState.page + 1} / ${pages}`;
  $('storage-page-prev').disabled = storageState.page === 0;
  $('storage-page-next').disabled = storageState.page >= pages - 1;
  $('storage-select-all').checked = visible.length > 0 && visible.every(item => storageState.selected.has(item.path));
  $('storage-select-all').disabled = !visible.length;
  if (storageState.loaded && !storageState.loading && !storageState.busy) $('storage-feedback').textContent = !filtered.length ? (query ? 'Không tìm thấy tệp trong thư mục này.' : 'Thư mục trống.') : (storageState.truncated ? 'Thư mục có hơn 500 mục. Mở thư mục con để xem đầy đủ.' : '');
  updateStorageButtons();
}
async function loadStorageDirectory(path = '') {
  if (!storageState.configured) {
    storageRequest++; storageState.loading = false;
    storageState.entries = []; storageState.selected.clear(); storageState.loaded = false;
    renderStorageFiles();
    $('storage-feedback').textContent = 'Cấu hình HF_TOKEN phía máy chủ để duyệt kho.';
    updateStorageButtons(); return;
  }
  const request = ++storageRequest;
  if (storageState.path !== path) $('storage-search').value = '';
  storageState.path = path; storageState.page = 0; storageState.entries = [];
  storageState.selected.clear(); storageState.loaded = false; storageState.loading = true;
  $('storage-path').textContent = '/ novelreader-storage' + (path ? ' / ' + path : '');
  $('storage-path').title = $('storage-path').textContent;
  $('storage-feedback').textContent = 'Đang tải thư mục…';
  renderStorageFiles();
  try {
    const data = await api('/api/storage/files?path=' + encodeURIComponent(path));
    if (request !== storageRequest) return;
    storageState.entries = data.entries; storageState.truncated = data.truncated;
    storageState.loaded = true;
    $('storage-connection-state').textContent = 'Đã truy cập kho';
  } catch (error) {
    if (request !== storageRequest) return;
    $('storage-feedback').textContent = error.message;
    $('storage-connection-state').textContent = 'Chưa truy cập được';
  } finally {
    if (request === storageRequest) { storageState.loading = false; renderStorageFiles(); }
  }
}
for (const [id, mode] of [['storage-tab-overview','overview'],['storage-tab-files','files']]) {
  $(id).onclick = () => {
    $('storage-layout').dataset.mode = mode;
    $('storage-connection-panel').hidden = mode === 'files';
    $('storage-tab-overview').setAttribute('aria-pressed', String(mode === 'overview'));
    $('storage-tab-files').setAttribute('aria-pressed', String(mode === 'files'));
  };
}
for (const view of ['list','grid']) $('storage-view-' + view).onclick = () => {
  storageState.view = view;
  for (const mode of ['list','grid']) $('storage-view-' + mode).setAttribute('aria-pressed', String(mode === view));
  renderStorageFiles();
};
$('storage-search').oninput = () => { storageState.page = 0; renderStorageFiles(); };
$('storage-select-all').onchange = event => {
  for (const item of storageState.visible) {
    if (event.target.checked) storageState.selected.add(item.path); else storageState.selected.delete(item.path);
  }
  renderStorageFiles();
};
$('storage-page-prev').onclick = () => { storageState.page--; renderStorageFiles(); };
$('storage-page-next').onclick = () => { storageState.page++; renderStorageFiles(); };
$('storage-up').onclick = () => loadStorageDirectory(storageState.path.split('/').slice(0, -1).join('/'));
$('storage-home').onclick = () => loadStorageDirectory('');
for (const id of ['storage-refresh','storage-quick-refresh']) $(id).onclick = () => loadHuggingFaceSettings();
for (const id of ['storage-upload','storage-quick-upload']) $(id).onclick = () => $('storage-file-input').click();
for (const id of ['storage-create-folder','storage-quick-folder']) $(id).onclick = () => {
  $('storage-folder-name').value = ''; $('storage-folder-error').textContent = '';
  $('storage-folder-dialog').showModal(); $('storage-folder-name').focus();
};
$('storage-folder-cancel').onclick = () => $('storage-folder-dialog').close();
$('storage-folder-dialog').oncancel = event => { if (storageState.busy) event.preventDefault(); };
$('storage-folder-form').onsubmit = async event => {
  event.preventDefault();
  if (storageState.busy) return;
  storageState.busy = true; updateStorageButtons();
  try {
    await api('/api/storage/folders', {path:storageState.path, name:$('storage-folder-name').value});
    $('storage-folder-dialog').close(); notice('Đã tạo thư mục.');
    await loadStorageDirectory(storageState.path);
  } catch (error) { $('storage-folder-error').textContent = error.message; }
  finally { storageState.busy = false; updateStorageButtons(); }
};
$('storage-file-input').onchange = () => safe(async () => {
  if (storageState.busy) return;
  const files = [...$('storage-file-input').files];
  if (!files.length) return;
  storageState.busy = true; updateStorageButtons();
  try {
    for (const file of files) {
      if (file.size > 50 * 1024 * 1024) throw new Error('Tệp tối đa 50 MB: ' + file.name);
      $('storage-feedback').textContent = 'Đang tải lên ' + file.name + '…';
      const data = new FormData(); data.append('file', file); data.append('path', storageState.path);
      await api('/api/storage/upload', data);
    }
    notice('Đã tải lên ' + files.length + ' tệp.');
  } finally {
    $('storage-file-input').value = ''; storageState.busy = false;
    await loadStorageDirectory(storageState.path); updateStorageButtons();
  }
});
$('storage-quick-download').onclick = () => {
  const item = storageState.entries.find(item => storageState.selected.has(item.path));
  if (!item || item.directory) return;
  const link = document.createElement('a'); link.href = storageDownloadUrl(item.path); link.download = item.name;
  document.body.append(link); link.click(); link.remove();
};

async function loadHuggingFaceSettings() {
  const status = $('huggingface-key-status');
  try {
    const info = await api('/api/storage/status');
    storageState.configured = info.has_key;
    $('storage-token-state').textContent = info.has_key ? 'Đã cấu hình HF_TOKEN phía máy chủ' : 'Chưa cấu hình HF_TOKEN';
    updateStorageButtons();
    if ($('settings-modal').dataset.tab === 'tab-cloud') await loadStorageDirectory(storageState.path);
  } catch (error) {
    storageRequest++; storageState.configured = false; storageState.loaded = false;
    storageState.loading = false; storageState.entries = []; storageState.selected.clear();
    renderStorageFiles();
    $('storage-feedback').textContent = error.message;
    $('storage-token-state').textContent = 'Không kiểm tra được cấu hình token.';
    status.textContent = error.message;
  }
  try {
    const checkpoint = await api('/api/checkpoints/status');
    if (checkpoint.last_cloud?.url?.startsWith('https://huggingface.co/datasets/uri410/novelreader-storage/')) {
      const output = $('checkpoint-status');
      const link = document.createElement('a');
      link.href = checkpoint.last_cloud.url;
      link.textContent = checkpoint.last_cloud.created_at;
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      output.replaceChildren(document.createTextNode('Checkpoint gần nhất: '), link);
    }
  } catch (error) { $('checkpoint-status').textContent = error.message; }
}
$('btn-test-huggingface').onclick = () => safe(async () => {
  $('btn-test-huggingface').disabled = true;
  $('huggingface-key-status').textContent = 'Đang kiểm tra kết nối…';
  try {
    const result = await api('/api/storage/test', {});
    $('huggingface-key-status').textContent = result.message;
    $('storage-connection-state').textContent = 'Đã kết nối';
    $('storage-account').textContent = result.username || 'Không có thông tin';
    $('storage-privacy').textContent = result.private ? 'Riêng tư' : 'Công khai';
    await loadHuggingFaceSettings();
  } catch (error) {
    $('huggingface-key-status').textContent = error.message;
    $('storage-connection-state').textContent = 'Kết nối thất bại';
    throw error;
  } finally { $('btn-test-huggingface').disabled = false; }
});

let checkpointBusy = false;
async function checkpointAction(action) {
  if (checkpointBusy) return;
  checkpointBusy = true;
  const buttons = document.querySelectorAll('.checkpoint-card button');
  buttons.forEach(b => b.disabled = true);
  $('checkpoint-status').textContent = 'Đang xử lý… Không đóng runtime.';
  try { await action(); }
  catch (e) { $('checkpoint-status').textContent = e.message; notice(e.message, true); }
  finally { checkpointBusy = false; buttons.forEach(b => b.disabled = false); }
}
if ($('btn-save-draft')) $('btn-save-draft').onclick = () => checkpointAction(async () => {
  await api('/api/checkpoints/draft', buildTranslatePayload());
  $('checkpoint-status').textContent = 'Đã lưu cấu hình bảng tạm tại backend; sẽ đi kèm checkpoint.';
});
if ($('btn-load-draft')) $('btn-load-draft').onclick = () => checkpointAction(async () => {
  const {config: c} = await api('/api/checkpoints/draft');
  setBackend(c.backend); $('engine').value = c.engine;
  $('glossary').value = c.glossary; $('batch').value = c.batch_size;
  $('opt-audio').checked = c.generate_audio; $('opt-audio-pipeline').checked = c.audio_pipeline;
  $('audio-workers').value = c.audio_workers; $('audio-queue-size').value = c.audio_queue_size;
  $('cloud-checkpoint-auto').checked = c.cloud_checkpoint;
  $('checkpoint-include-audio').checked = c.checkpoint_include_audio;
  $('opt-honorific').checked = c.honorific_mode !== 'off';
  $('opt-pronoun').checked = c.pronoun_harmonizer;
  $('beam-size').value = c.beam_size; $('beam-val').textContent = c.beam_size;
  setChunkMode(c.chunk_mode); setNormalizeMode(c.normalize_mode || (c.normalize_t2s === false ? 'none' : 'auto'));
  $('voice-select').value = c.voice_id; $('modal-voice').value = c.voice_id;
  const speedSelect = $('audio-speed');
  let speedOption = Array.from(speedSelect.options).find(o => Number(o.value) === Number(c.audio_speed));
  if (!speedOption) {
    speedOption = new Option(`${c.audio_speed}x`, String(c.audio_speed));
    speedSelect.add(speedOption);
  }
  speedSelect.value = speedOption.value;
  $('audio-format').value = c.audio_format;
  $('modal-audio-format').value = c.audio_format; $('modal-audio-bitrate').value = c.audio_bitrate;
  $('modal-noise-scale').value = c.noise_scale; $('modal-noise-w').value = c.noise_w_scale;
  $('noise-scale-val').textContent = Number(c.noise_scale).toFixed(2);
  $('noise-w-val').textContent = Number(c.noise_w_scale).toFixed(2);
  $('reset').checked = c.reset; $('opt-auto-group').checked = c.auto_group_audio;
  for (const id of ['toc-group-size', 'opt-group-size', 'modal-group-size']) if ($(id)) $(id).value = c.group_size;
  $('trans-range-start').value = c.start_pos ?? ''; $('trans-range-end').value = c.end_pos ?? '';
  await applyAudioConfig(c);
  $('checkpoint-status').textContent = 'Đã nạp cấu hình bảng tạm. Kiểm tra phạm vi/reset trước khi chạy.';
});
if ($('btn-checkpoint-cloud')) $('btn-checkpoint-cloud').onclick = () => checkpointAction(async () => {
  await api('/api/checkpoints/draft', buildTranslatePayload());
  const result = await api('/api/checkpoints/huggingface', {include_audio: $('checkpoint-include-audio').checked});
  showHuggingFaceModal(result);
  $('checkpoint-status').textContent = 'Đã lưu checkpoint lên Hugging Face. Hãy giữ link để khôi phục runtime khác.';
});
if ($('btn-checkpoint-download')) $('btn-checkpoint-download').onclick = () => checkpointAction(async () => {
  await api('/api/checkpoints/draft', buildTranslatePayload());
  const response = await fetch('/api/checkpoints/download', {method: 'POST',
    headers: {'X-App-Request': 'novel-translator', 'Content-Type': 'application/json'},
    body: JSON.stringify({include_audio: $('checkpoint-include-audio').checked})});
  if (!response.ok) throw new Error((await response.json()).detail || 'Không tải được checkpoint.');
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement('a'); a.href = url; a.download = 'NovelReader_checkpoint.zip';
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
  $('checkpoint-status').textContent = 'Đã tạo checkpoint để tải về. Giới hạn khôi phục: 2 GB/ZIP.';
});
async function finishRestore(result) {
  selected = null; await refreshAll();
  $('checkpoint-status').textContent = result.message;
  notice(result.message);
}
if ($('checkpoint-file')) $('checkpoint-file').onchange = () => checkpointAction(async () => {
  const file = $('checkpoint-file').files[0];
  if (!file) { $('checkpoint-status').textContent = ''; return; }
  if (!confirm('Thay dữ liệu truyện hiện tại bằng checkpoint? Bản xuất cũ vẫn được giữ trong thư mục riêng.')) return;
  if (file.size > 2 * 1024 ** 3) throw new Error('Checkpoint tối đa 2 GB.');
  const data = new FormData(); data.append('file', file);
  await finishRestore(await api('/api/checkpoints/restore', data));
  $('checkpoint-file').value = '';
});
if ($('btn-checkpoint-restore')) $('btn-checkpoint-restore').onclick = () => checkpointAction(async () => {
  if (!confirm('Tải checkpoint Hugging Face và thay truyện hiện tại?')) return;
  await finishRestore(await api('/api/checkpoints/restore-huggingface', {file_id: $('checkpoint-id').value.trim()}));
});

if ($('hf-dialog-close')) $('hf-dialog-close').onclick = () => $('huggingface-result-dialog')?.close();
if ($('hf-btn-copy')) {
  $('hf-btn-copy').onclick = () => {
    const url = $('hf-dialog-url')?.value;
    if (url) {
      navigator.clipboard.writeText(url).then(() => notice('Đã sao chép link Hugging Face vào clipboard!'));
    }
  };
}

if ($('btn-save-settings')) {
  $('btn-save-settings').onclick = () => safe(async () => {
    await api('/api/checkpoints/draft', buildTranslatePayload());
    await api('/api/settings/audio', buildAudioPayload());
    notice('Đã lưu cài đặt.');
  });
}

// ----------------- SYSTEM PURGE CACHE & DATA -----------------
function setPurgeStatus(msg, isError = false) {
  const el = $('purge-status-msg');
  if (el) {
    el.textContent = msg;
    el.style.color = isError ? 'var(--red, #f87171)' : 'var(--accent, #f2f3f5)';
  }
}

if ($('btn-purge-cache-only')) {
  $('btn-purge-cache-only').onclick = () => safe(async () => {
    if (state.progress.active) {
      notice('Hãy dừng job dịch trước khi dọn cache.', true);
      return;
    }
    setPurgeStatus('Đang dọn dẹp cache & file tạm...');
    const res = await api('/api/system/purge', { purge_data: false, purge_cache: true }, 'POST');
    setPurgeStatus(`${res.message}`);
    notice(`${res.message}`);
  });
}

if ($('btn-purge-data-only')) {
  $('btn-purge-data-only').onclick = () => safe(async () => {
    if (state.progress.active) {
      notice('Hãy dừng job dịch trước khi xóa dữ liệu.', true);
      return;
    }
    if (!confirm('Xóa bản dịch và output của truyện hiện tại? Output các truyện khác được giữ. Thao tác này không thể hoàn tác.')) {
      return;
    }
    setPurgeStatus('Đang xóa toàn bộ dữ liệu output...');
    const res = await api('/api/system/purge', { purge_data: true, purge_cache: false }, 'POST');
    selected = null;
    selectedChapterIds.clear();
    isSelectMode = false;

    await refreshAll();
    setPurgeStatus(`${res.message}`);
    notice(`Đã xóa sạch toàn bộ data truyện và file output.`);
  });
}

if ($('btn-purge-everything')) {
  $('btn-purge-everything').onclick = () => safe(async () => {
    if (state.progress.active) {
      notice('Hãy dừng job dịch trước khi xóa tất cả.', true);
      return;
    }
    if (!confirm('CẢNH BÁO: Xóa dữ liệu và output của truyện hiện tại cùng cache ứng dụng. Output các truyện khác được giữ.\n\nBạn có chắc chắn muốn tiếp tục?')) {
      return;
    }
    setPurgeStatus('Đang xóa sạch toàn bộ data và cache của mọi thứ...');
    const res = await api('/api/system/purge', { purge_data: true, purge_cache: true }, 'POST');
    selected = null;
    selectedChapterIds.clear();
    isSelectMode = false;

    await refreshAll();
    setPurgeStatus(`${res.message}`);
    notice(`${res.message}`);
  });
}

// ----------------- AUDIO GROUPING & MERGING -----------------
async function loadMergedGroups() {
  const container = $('merged-groups-container');
  if (!container) return;
  try {
    const res = await api('/api/audio/groups');
    const groups = Array.isArray(res) ? res : (res.groups || []);
    if (!groups.length) {
      container.innerHTML = '<p class="text-dim" style="font-size:13px; color:var(--text-muted);">Chưa có tập audio nào được gộp.</p>';
      return;
    }
    container.replaceChildren();
    const list = document.createElement('div');
    list.style.display = 'flex';
    list.style.flexDirection = 'column';
    list.style.gap = '8px';

    groups.forEach(g => {
      const row = document.createElement('div');
      row.style.display = 'flex';
      row.style.alignItems = 'center';
      row.style.justifyContent = 'space-between';
      row.style.padding = '8px 12px';
      row.style.background = 'rgba(255,255,255,0.05)';
      row.style.borderRadius = '6px';

      const info = document.createElement('div');
      const sizeText = g.size_mb !== undefined ? `${g.size_mb} MB` : `${((g.size || 0) / (1024 * 1024)).toFixed(1)} MB`;
      info.innerHTML = `<strong>${g.filename}</strong> <span style="font-size:12px; color:var(--text-muted);">(${sizeText})</span>`;

      const actions = document.createElement('div');
      actions.style.display = 'flex';
      actions.style.gap = '6px';
      actions.style.alignItems = 'center';

      const downloadLink = document.createElement('a');
      downloadLink.href = g.url || g.download_url;
      downloadLink.download = g.filename;
      downloadLink.className = 'btn-tool';
      downloadLink.innerHTML = '<i aria-hidden="true" class="fi fi-br-download"></i> Tải file';

      const hfBtn = document.createElement('button');
      hfBtn.type = 'button';
      hfBtn.className = 'btn-tool';
      hfBtn.innerHTML = '<i aria-hidden="true" class="fi fi-br-cloud"></i> Hugging Face';
      hfBtn.title = 'Tải file này lên Hugging Face và lấy link chia sẻ';
      hfBtn.onclick = async () => {
        notice(`Đang tải ${g.filename} lên Hugging Face...`);
        try {
          const res = await api('/api/export/huggingface/file/' + encodeURIComponent(g.filename), {}, 'POST');
          if (res.ok) {
            notice(`Đã tải lên Hugging Face: ${res.url}`);
            showHuggingFaceModal(res);
          } else {
            throw new Error(res.message || 'Lỗi khi upload Hugging Face.');
          }
        } catch (err) {
          const msg = err.message || String(err);
          if (msg.includes('HF_TOKEN') || msg.includes('401')) {
            notice('Hãy cấu hình HF_TOKEN có quyền ghi phía máy chủ.');
            openSettingsPage('tab-cloud');
          } else {
            notice(`Lỗi Hugging Face: ${msg}`);
          }
        }
      };

      actions.append(downloadLink, hfBtn);
      row.append(info, actions);
      list.append(row);
    });
    container.append(list);
  } catch (e) {
    container.innerHTML = `<p class="text-dim" style="color:var(--red,var(--danger));">${e.message}</p>`;
  }
}

if ($('btn-run-merge')) {
  $('btn-run-merge').onclick = () => safe(async () => {
    const groupSize = parseInt($('modal-group-size') ? $('modal-group-size').value : '50', 10) || 50;
    const format = $('audio-format') ? $('audio-format').value : 'mp3';

    notice(`Đang gộp các chương đã có audio thành nhóm ${groupSize} chương...`);
    const res = await api('/api/audio/merge', {
      group_size: groupSize,
      format: format
    }, 'POST');

    const count = res.groups ? res.groups.length : 0;
    notice(`Đã tạo thành công ${count} tập audio lớn!`);
    await loadMergedGroups();
  });
}

// ----------------- EMPTY CHAPTER PURGING -----------------
async function purgeEmptyChapters() {
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi dọn dẹp chương.', true);
    return;
  }
  if (!confirm('Bạn có chắc muốn tự động quét và xóa sạch tất cả các chương không có nội dung chữ (chương rỗng)? Thao tác này không thể hoàn tác.')) {
    return;
  }
  notice('Đang quét và xóa các chương rỗng…');
  const res = await api('/api/chapters/purge-empty', {}, 'POST');
  await refreshAll();
  if (chapters.length) {
    await selectChapter(chapters[0].id);
  } else {
    chapterRequest++;
    selected = null;
    $('reader-empty').hidden = false;
    $('reading-panes').hidden = true;
    $('chapter-single-ops').hidden = true;
  }
  notice(`${res.message}`);
}

if ($('btn-purge-empty')) $('btn-purge-empty').onclick = () => safe(purgeEmptyChapters);
if ($('btn-modal-purge-empty')) $('btn-modal-purge-empty').onclick = () => safe(purgeEmptyChapters);

// ----------------- ENGINE / BACKEND CONTROLS (CTranslate2, PyTorch) -----------------
function setBackend(backend) {
  const isTorch = backend === 'transformers' || backend === 'pytorch';
  const val = isTorch ? 'transformers' : 'ct2';
  if ($('backend-ct2-label')) $('backend-ct2-label').classList.toggle('active', !isTorch);
  if ($('backend-torch-label')) $('backend-torch-label').classList.toggle('active', isTorch);
  const radios = document.querySelectorAll('input[name="backend"]');
  radios.forEach(r => {
    r.checked = (r.value === val);
  });
  localStorage.setItem('novel_backend', val);
  loadModels();
}
if ($('backend-ct2-label')) $('backend-ct2-label').onclick = () => setBackend('ct2');
if ($('backend-torch-label')) $('backend-torch-label').onclick = () => setBackend('transformers');

// ----------------- TRIPLET CONTROLS (BEAM, CHUNK, NORMALIZE) -----------------
function setChunkMode(mode) {
  const isPara = mode === 'paragraph';
  $('chunk-sentence-label').classList.toggle('active', !isPara);
  $('chunk-paragraph-label').classList.toggle('active', isPara);
  const radios = document.querySelectorAll('input[name="chunk_mode"]');
  radios.forEach(r => {
    r.checked = (r.value === mode);
  });
  updateTranslationSummary();
}
$('chunk-sentence-label').onclick = () => setChunkMode('sentence');
$('chunk-paragraph-label').onclick = () => setChunkMode('paragraph');

$('beam-size').oninput = () => {
  $('beam-val').textContent = $('beam-size').value;
  updateTranslationSummary();
};

let lastEnabledNormalizeMode = 'auto';
function setNormalizeMode(mode) {
  mode = ['auto','t2s','none'].includes(mode) ? mode : 'auto';
  $('normalize-mode').value=mode; $('opt-t2s').checked=mode!=='none';
  if(mode!=='none') lastEnabledNormalizeMode=mode;
  updateTranslationSummary();
}
function updateTranslationSummary() {
  const summary=$('translation-settings-summary');if(!summary)return;
  const paragraph=document.querySelector('input[name="chunk_mode"]:checked')?.value==='paragraph';
  summary.textContent=`Beam ${$('beam-size').value} · ${paragraph?'Theo đoạn':'Theo câu'} · ${$('normalize-mode').value==='none'?'Giữ chữ gốc':'Phồn → Giản'}`;
}
$('normalize-mode').onchange=()=>setNormalizeMode($('normalize-mode').value);
$('opt-t2s').onchange=()=>setNormalizeMode($('opt-t2s').checked?lastEnabledNormalizeMode:'none');
if ($('btn-translation-settings')) $('btn-translation-settings').onclick=()=>openSettingsPage('tab-translation');

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

  const percent = p.total ? Math.floor(p.done / p.total * 100) : 0;
  $('progress-text').textContent = p.scope ? `${p.done} / ${p.total} chương (${p.scope})` : `${p.done} / ${p.total} chương`;
  $('percent').textContent = percent + '%';
  $('progress').value = percent;
  $('progress').style.setProperty('--progress', percent + '%');
  recordActivity(p.message || (p.active ? titles[p.status] : ''), p.status === 'error');

  $('start').disabled = p.active || !state.book || busy;
  if ($('job-controls')) $('job-controls').classList.toggle('active', !!p.active);
  $('pause').disabled = !p.active || p.status === 'stopping';
  $('stop').disabled = !p.active || p.status === 'stopping';
  $('pause').innerHTML = p.status === 'paused' ? '<i aria-hidden="true" class="fi fi-br-play"></i> Tiếp tục' : '<i aria-hidden="true" class="fi fi-br-pause"></i> Tạm dừng';

  const inputs = ['engine', 'glossary', 'batch', 'reset', 'load-path', 'file', 'opt-audio-pipeline', 'audio-workers', 'audio-queue-size', 'cloud-checkpoint-auto', 'checkpoint-include-audio', 'opt-honorific', 'opt-pronoun', 'opt-t2s', 'beam-size', 'normalize-mode', 'btn-delete-book', 'btn-save-book-title', 'book-output-title', 'btn-trans-range', 'btn-auto-group-audio', 'btn-run-merge', 'modal-group-size', 'range-start', 'range-end', 'trans-range-start', 'trans-range-end', 'toc-group-size', 'btn-reset-current', 'btn-delete-current', 'btn-download-model', 'btn-download-model-action'];
  inputs.forEach(id => {
    const el = $(id);
    if (el) el.disabled = p.active || busy || isDownloadingModel;
  });
  if ($('chunk-sentence-label')) $('chunk-sentence-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('chunk-paragraph-label')) $('chunk-paragraph-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('backend-ct2-label')) $('backend-ct2-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('backend-torch-label')) $('backend-torch-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';

  document.querySelectorAll('input[name=backend],input[name=chunk_mode]').forEach(input => input.disabled = p.active || busy || isDownloadingModel);
  $('btn-save-settings').disabled = p.active || busy;
  $('btn-open-export').disabled = !state.book;
  $('save-note').textContent = p.message || 'Tiến độ được lưu tự động trên máy của bạn.';
  for (const id of ['export-txt', 'export-epub']) {
    $(id).setAttribute('aria-disabled', String(!state.book));
  }
}

function updateBook(book) {
  $('sidebar').classList.toggle('has-book', !!book);
  state.book = book;
  const outputFolder = book ? (book.output_folder || book.title) + '/' : '';
  if ($('output-text-path')) $('output-text-path').textContent = 'output_text/' + outputFolder;
  if ($('output-audio-path')) $('output-audio-path').textContent = 'output_audio/' + outputFolder;
  if ($('book-title-panel')) $('book-title-panel').hidden = !book;
  if ($('book-output-title') && document.activeElement !== $('book-output-title')) {
    $('book-output-title').value = book?.title || '';
  }
  $('dropzone').querySelector('strong').textContent = book ? 'Thay tệp truyện' : 'Nạp tệp truyện';
  $('book-name').textContent = book ? book.title : 'Tạo bản dịch mới';
  $('reader-book-name').textContent = book ? book.title : 'Chưa nạp truyện';
  const kicker = document.querySelector('.source-label .section-kicker');
  if (kicker) kicker.textContent = book ? 'Bản thảo nguồn' : 'NovelReader';
  if (book) {
    $('filename').textContent = book.filename;
    $('book-format').textContent = book.filename?.split('.').pop().toUpperCase() || 'TXT';
    $('encoding').textContent = book.encoding + ' · Đã lưu trên máy';
    if ($('book-size')) $('book-size').textContent = (book.filename && book.filename.toLowerCase().endsWith('.epub')) ? '12.6 MB' : '4.2 MB';
    if ($('book-cover-img')) {
      $('book-cover-img').src = '/static/cover-sample.png';
      $('book-cover-img').style.display = 'block';
    }
    if ($('book-cover-fallback')) $('book-cover-fallback').style.display = 'none';
  } else {
    $('chapter-single-ops').hidden = true;
    $('book-format').textContent = 'TXT / EPUB';
    if ($('book-size')) $('book-size').textContent = '—';
    if ($('book-cover-img')) $('book-cover-img').style.display = 'none';
    if ($('book-cover-fallback')) $('book-cover-fallback').style.display = 'flex';
  }
}

// Kept for existing chapter-refresh calls; bulk selection controls were removed.
function updateBatchCount() {}

function renderToc() {
  const query = $('search').value.toLowerCase();
  const filtered = chapters.filter(c => (c.title + ' ' + (c.translated_title || '') + ' ' + c.position).toLowerCase().includes(query));

  $('toc').replaceChildren();
  $('chapter-count').textContent = chapters.length + ' chương';
  $('toc-count').textContent = chapters.length;
  $('trans-range-end').placeholder = String(chapters.length || 'Cuối');

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
    setIconLabel(icon, {done:'check',translating:'hourglass-end',error:'exclamation'}[c.status] || 'circle', {done:'Hoàn thành',translating:'Đang xử lý',pending:'Chờ xử lý',error:'Lỗi dịch'}[c.status] || 'Chờ xử lý');

    const audioStatus = document.createElement('span');
    audioStatus.className = 'toc-audio-status';
    audioStatus.dataset.status = c.audio_status || 'pending';
    audioStatus.textContent = {done:'Sẵn sàng',queued:'Đang chờ',generating:'Đang tạo',error:'Lỗi audio'}[c.audio_status] || '—';
    audioStatus.hidden = audioStatus.textContent === '—';
    b.append(n, name, icon, audioStatus);
    b.onclick = (e) => {
      if (isSelectMode && e.target.classList.contains('toc-checkbox')) return;
      safe(async () => {
        await selectChapter(c.id);
        if (selected === c.id && workspace.classList.contains('show-reader')) {
          $('chapter-title').focus({preventScroll:true});
        }
      });
      $('tab-reader').click();
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
    p.textContent = chapters.length ? 'Không tìm thấy chương phù hợp.' : 'Nạp bản thảo TXT hoặc EPUB để quản lý, dịch và nghe từng chương tại đây.';
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
  if (refresh && pendingChapter !== null) return;
  if (!refresh) pendingChapter = id;
  const request = ++chapterRequest;
  let chapter;
  try {
    chapter = await api('/api/chapters/' + id);
  } catch (err) {
    if (request === chapterRequest) {
      pendingChapter = null;
      notice(`Không thể tải chương: ${err.message}`, true);
    }
    return;
  }
  if (request !== chapterRequest) return;
  pendingChapter = null;
  if (!chapter) return;
  if (refresh && selected !== id) return;
  selected = id;

  $('reader-empty').hidden = true;
  $('reading-panes').hidden = false;
  $('chapter-single-ops').hidden = false;

  $('chapter-index').textContent = `Chương ${chapter.position.toString().padStart(2, '0')} / ${chapters.length}`;
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
    ? 'ĐÃ LƯU BẢN DỊCH'
    : chapter.status === 'error'
      ? 'CHƯƠNG DỊCH LỖI'
      : 'CĂN ĐOẠN 1:1 · TỰ ĐỘNG LƯU';

  const audioBar = $('chapter-audio-bar');
  if (readerAudio.getAttribute('src') &&
      (chapter.audio_status !== 'done' || !readerAudio.src.includes(`/api/chapters/${chapter.id}/audio`))) {
    readerAudio.pause();
    readerAudio.removeAttribute('src');
    readerAudio.load();
  }
  if (audioBar) {
    if (chapter.status === 'done') {
      audioBar.hidden = false;
      const player = $('audio-player');
      const downloadBtn = $('btn-download-audio');
      const msg = $('audio-status-msg');
      const regenBtn = $('btn-regen-audio');
      regenBtn.disabled = false;

      if (chapter.audio_status === 'done') {
        const audioUrl = `/api/chapters/${chapter.id}/audio`;
        if (!player.src.includes(`/api/chapters/${chapter.id}/audio`)) {
          player.src = audioUrl;
        }
        player.style.display = 'block';
        downloadBtn.hidden = false;
        downloadBtn.href = audioUrl;
        const fmt = $('audio-format') ? $('audio-format').value : 'mp3';
        downloadBtn.download = `chuong_${chapter.position.toString().padStart(4, '0')}.${fmt}`;
        downloadBtn.innerHTML = `<i aria-hidden="true" class="fi fi-br-download"></i> Tải ${fmt.toUpperCase()}`;
        msg.textContent = '';
        msg.className = 'audio-status-msg';
      } else if (['queued', 'generating'].includes(chapter.audio_status)) {
        player.style.display = 'none';
        downloadBtn.hidden = true;
        msg.textContent = 'Đang tạo audio…';
        msg.className = 'audio-status-msg';
        regenBtn.disabled = true;
      } else if (chapter.audio_status === 'error') {
        player.style.display = 'none';
        downloadBtn.hidden = true;
        msg.textContent = 'Lỗi tạo audio. Bấm "Tạo Audio" để thử lại.';
        msg.className = 'audio-status-msg error';
      } else {
        player.style.display = 'none';
        downloadBtn.hidden = true;
        msg.textContent = 'Chưa có audio cho chương này.';
        msg.className = 'audio-status-msg';
      }
    } else {
      audioBar.hidden = true;
    }
  }

  if (audioBar.hidden) readerAudio.pause();
  updateReaderAudio();
  renderToc();
}

async function refreshAll() {
  const [s, c] = await Promise.all([api('/api/state'), api('/api/chapters')]);
  updateBook(s.book);
  chapters = c;
  renderProgress(s.progress);
  renderToc();
  if (!s.book || !chapters.length) {
    chapterRequest++;
    pendingChapter = null;
    selected = null;
    $('reader-empty').hidden = false;
    $('reading-panes').hidden = true;
    $('chapter-single-ops').hidden = true;
    if ($('chapter-audio-bar')) $('chapter-audio-bar').hidden = true;
    readerAudio.pause();
    readerAudio.removeAttribute('src');
    readerAudio.load();
    updateReaderAudio();
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
  if (state.book && !confirm('Nạp truyện mới sẽ thay thư viện hiện tại. File output của truyện trước vẫn được giữ. Tiếp tục?')) return;
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

// ----------------- TRANSLATION CONTROLS & RANGE SCOPING -----------------
function buildTranslatePayload(extraConfig = {}) {
  const batch = Number($('batch').value);
  if (!Number.isInteger(batch) || batch < 1 || batch > 1024) {
    throw new Error('Batch size phải từ 1 đến 1024.');
  }

  const selectedChunkMode = document.querySelector('input[name="chunk_mode"]:checked')?.value || 'sentence';
  const autoGroup = $('opt-auto-group') ? $('opt-auto-group').checked : ($('modal-auto-group') ? $('modal-auto-group').checked : false);
  const groupSize = Number($('toc-group-size')?.value ?? $('opt-group-size')?.value ?? '50');

  // Explicit IDs and a range must never be mixed.
  const hasIds = extraConfig.chapter_ids !== undefined && extraConfig.chapter_ids !== null;
  const rawStart = extraConfig.start_pos !== undefined ? extraConfig.start_pos : $('trans-range-start')?.value;
  const rawEnd = extraConfig.end_pos !== undefined ? extraConfig.end_pos : $('trans-range-end')?.value;
  let startPos = hasIds || rawStart === '' || rawStart == null ? null : Number(rawStart);
  let endPos = hasIds || rawEnd === '' || rawEnd == null ? null : Number(rawEnd);
  const maxPos = chapters.length ? Math.max(...chapters.map(c => c.position || 0)) : 1;
  if (!hasIds) {
    if (startPos !== null && endPos === null) {
      endPos = maxPos;
    } else if (startPos === null && endPos !== null) {
      startPos = 1;
    }
  }
  if (startPos !== null && (!Number.isInteger(startPos) || !Number.isInteger(endPos) || startPos < 1 || endPos < startPos)) {
    throw new Error('Dải chương không hợp lệ. Nhập số nguyên từ 1 và chương bắt đầu không lớn hơn chương kết thúc.');
  }
  if (!Number.isInteger(groupSize) || groupSize < 2 || groupSize > 500) throw new Error('Số chương mỗi nhóm phải từ 2 đến 500.');

  const selectedBackend = document.querySelector('input[name="backend"]:checked')?.value || 'ct2';

  return {
    engine: $('engine').value,
    backend: selectedBackend,
    glossary: $('glossary').value,
    batch_size: batch,
    audio_pipeline: $('opt-audio-pipeline') ? $('opt-audio-pipeline').checked : true,
    audio_workers: Number($('audio-workers')?.value || 1),
    audio_queue_size: Number($('audio-queue-size')?.value || 4),
    cloud_checkpoint: !!$('cloud-checkpoint-auto')?.checked,
    checkpoint_include_audio: !!$('checkpoint-include-audio')?.checked,
    reset: extraConfig.reset !== undefined ? extraConfig.reset : $('reset').checked,
    honorific_mode: $('opt-honorific').checked ? 'safe' : 'off',
    pronoun_harmonizer: $('opt-pronoun').checked,
    normalize_t2s: $('opt-t2s').checked,
    beam_size: Number($('beam-size').value) || 2,
    chunk_mode: selectedChunkMode,
    normalize_mode: $('opt-t2s').checked ? ($('normalize-mode').value === 'none' ? 'auto' : $('normalize-mode').value) : 'none',
    generate_audio: extraConfig.generate_audio !== undefined
      ? !!extraConfig.generate_audio
      : ($('opt-audio') ? $('opt-audio').checked : true),
    audio_speed: Number.isFinite(parseFloat($('audio-speed')?.value)) ? parseFloat($('audio-speed').value) : 1.0,
    voice_id: ($('modal-voice') || $('voice-select'))?.value || 'ngochuyennew',
    noise_scale: Number.isFinite(parseFloat($('modal-noise-scale')?.value)) ? parseFloat($('modal-noise-scale').value) : 0.667,
    noise_w_scale: Number.isFinite(parseFloat($('modal-noise-w')?.value)) ? parseFloat($('modal-noise-w').value) : 0.8,
    audio_format: ($('modal-audio-format') || $('audio-format'))?.value || 'mp3',
    audio_bitrate: $('modal-audio-bitrate')?.value || '96k',
    ...buildAudioPayload(),
    auto_group_audio: ($('opt-audio') && !$('opt-audio').checked) ? false : (extraConfig.auto_group_audio !== undefined ? !!extraConfig.auto_group_audio : autoGroup),
    group_size: groupSize,
    start_pos: startPos,
    end_pos: endPos,
    chapter_ids: extraConfig.chapter_ids || null,
    force_retranslate: extraConfig.force_retranslate ?? (startPos !== null ? true : false)
  };
}

async function startTranslate(extraConfig = {}) {
  const payload = buildTranslatePayload(extraConfig);
  if (payload.reset && !confirm(payload.start_pos !== null || payload.chapter_ids ? 'Xóa bản dịch trong phạm vi đã chọn và dịch lại?' : 'Xóa toàn bộ bản dịch hiện tại và dịch lại từ đầu?')) {
    return;
  }
  if (payload.engine.startsWith('space') && !confirm('Chế độ Space gửi nội dung truyện tới Hugging Face để dịch trực tuyến. Tiếp tục?')) {
    return;
  }

  const p = await api('/api/translate/start', payload);
  $('reset').checked = false;
  renderProgress(p);

  if (payload.start_pos && payload.end_pos) {
    notice(`Bắt đầu dịch & tạo audio từ chương ${payload.start_pos} đến ${payload.end_pos}…`);
  } else if (payload.chapter_ids && payload.chapter_ids.length) {
    notice(`Bắt đầu dịch & tạo audio cho ${payload.chapter_ids.length} chương đã chọn…`);
  } else {
    notice('Bắt đầu dịch toàn bộ truyện…');
  }
}

$('start').onclick = () => safe(async () => {
  await startTranslate();
});

// Đồng bộ 2 chiều dải chương giữa Section 02 và Section 03
function syncRangeInputs(sourceId) {
  const isSec2 = sourceId.startsWith('trans-range');
  const sVal = isSec2 ? $('trans-range-start')?.value : $('range-start')?.value;
  const eVal = isSec2 ? $('trans-range-end')?.value : $('range-end')?.value;

  if (isSec2) {
    if ($('range-start')) $('range-start').value = sVal;
    if ($('range-end')) $('range-end').value = eVal;
  } else {
    if ($('trans-range-start')) $('trans-range-start').value = sVal;
    if ($('trans-range-end')) $('trans-range-end').value = eVal;
  }
}

['trans-range-start', 'trans-range-end'].forEach(id => {
  const el = $(id);
  if (el) {
    el.addEventListener('input', () => syncRangeInputs(id));
    el.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        $('start')?.click();
      }
    });
  }
});

if ($('btn-clear-trans-range')) {
  $('btn-clear-trans-range').onclick = () => {
    if ($('trans-range-start')) $('trans-range-start').value = '';
    if ($('trans-range-end')) $('trans-range-end').value = '';
    if ($('range-start')) $('range-start').value = '';
    if ($('range-end')) $('range-end').value = '';
    notice('Đã chuyển về chế độ dịch toàn bộ truyện.');
  };
}

// Đồng bộ kích thước nhóm gộp audio
function syncGroupSize(val) {
  ['toc-group-size', 'opt-group-size', 'modal-group-size'].forEach(id => {
    if ($(id)) $(id).value = val;
  });
  if ($('auto-group-size-lbl')) $('auto-group-size-lbl').textContent = val || '…';
}
['toc-group-size', 'opt-group-size', 'modal-group-size'].forEach(id => {
  if ($(id)) $(id).addEventListener('input', () => syncGroupSize($(id).value));
});
if ($('opt-auto-group') && $('modal-auto-group')) {
  $('opt-auto-group').addEventListener('change', () => { $('modal-auto-group').checked = $('opt-auto-group').checked; });
  $('modal-auto-group').addEventListener('change', () => { $('opt-auto-group').checked = $('modal-auto-group').checked; });
}

if ($('opt-audio')) {
  const updateAudioControls = () => {
    const enabled = $('opt-audio').checked;
    const grid = document.querySelector('.audio-cfg-grid');
    if (grid) {
      grid.style.opacity = enabled ? '1' : '0.4';
      grid.querySelectorAll('select, input').forEach(el => el.disabled = !enabled);
    }
  };
  $('opt-audio').addEventListener('change', updateAudioControls);
  updateAudioControls();
}

// Single Chapter Audio Generation
if ($('btn-regen-audio')) {
  $('btn-regen-audio').onclick = () => safe(async () => {
    if (!selected) return;
    const btn = $('btn-regen-audio');
    btn.disabled = true;
    $('audio-status-msg').textContent = 'Đang tạo audio…';
    $('audio-status-msg').className = 'audio-status-msg';
    try {
      await api(`/api/chapters/${selected}/audio`, buildAudioPayload(), 'POST');
      notice('Đã tạo xong audio cho chương!');
      await selectChapter(selected, true);
    } catch (e) {
      notice('Lỗi tạo audio: ' + e.message, true);
      await selectChapter(selected, true);
    } finally {
      btn.disabled = false;
    }
  });
}

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
  // Range controls stay visible after deleting a book.
  await refreshAll();
  notice('Đã xóa toàn bộ dữ liệu truyện.');
});



function renderMergeResult(groups, groupSize) {
  const resultBox = $('merge-audio-result');
  if (!resultBox) return;
  if (!groups || !groups.length) {
    resultBox.style.display = 'flex';
    resultBox.className = 'merge-result-card error';
    resultBox.innerHTML = `<span>Chưa có nhóm audio nào có thể gộp.</span>`;
    return;
  }

  const groupListHtml = groups.map(g => `
    <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(220,220,220,0.15);">
      <div>
        <strong style="color:var(--accent,var(--text));">${g.title || g.filename}</strong>
        <span style="color:var(--text-muted); font-size:10px; margin-left:6px;">(${g.chapter_count} chương · ${g.size_mb} MB)</span>
      </div>
      <div style="display:flex; gap:6px;">
        <a href="${g.url}" download="${g.filename}" style="font-size:11px; color:var(--text); text-decoration:none;"><i aria-hidden="true" class="fi fi-br-download"></i> Tải</a>
        <button type="button" class="btn-play-group-item" data-url="${g.url}" data-name="${g.filename}" style="padding:2px 6px; font-size:10px; background:var(--border); border:1px solid var(--border); border-radius:3px; color:var(--text); cursor:pointer;"><i aria-hidden="true" class="fi fi-br-headphones"></i> Nghe</button>
      </div>
    </div>
  `).join('');

  resultBox.style.display = 'flex';
  resultBox.className = 'merge-result-card';
  resultBox.innerHTML = `
    <div class="merge-result-msg">
      <strong style="color:var(--accent,var(--text));"><i aria-hidden="true" class="fi fi-br-check"></i> Đã tự động gộp thành ${groups.length} file audio lớn (nhóm ${groupSize} chương):</strong>
      <div style="margin-top:6px; max-height:160px; overflow-y:auto;">${groupListHtml}</div>
    </div>
  `;

  resultBox.querySelectorAll('.btn-play-group-item').forEach(btn => {
    btn.onclick = () => {
      const player = $('audio-player');
      if (player) {
        player.src = btn.dataset.url;
        player.play();
        $('chapter-audio-bar').hidden = false;
        notice('Đang phát file audio: ' + btn.dataset.name);
      }
    };
  });
}

// Tự động gộp theo nhóm N chương (mặc định 50 chương)
if ($('btn-auto-group-audio')) {
  $('btn-auto-group-audio').onclick = () => safe(async () => {
    const groupSize = Number($('toc-group-size')?.value ?? $('opt-group-size')?.value ?? '50');
    if (!Number.isInteger(groupSize) || groupSize < 2 || groupSize > 500) throw new Error('Số chương mỗi nhóm phải từ 2 đến 500.');
    const button = $('btn-auto-group-audio');
    button.disabled = true;
    const resultBox = $('merge-audio-result');
    if (resultBox) {
      resultBox.style.display = 'flex';
      resultBox.className = 'merge-result-card';
      resultBox.innerHTML = `<span><i aria-hidden="true" class="fi fi-br-hourglass-end"></i> Đang quét và tự động gộp file audio theo nhóm ${groupSize} chương...</span>`;
    }
    const fmt = $('audio-format') ? $('audio-format').value : 'mp3';

    try {
      const res = await api('/api/audio/auto-group', { group_size: groupSize, format: fmt }, 'POST');
      const groups = res.groups || [];
      if (!groups.length) {
        if (resultBox) {
          resultBox.className = 'merge-result-card error';
          resultBox.innerHTML = `<span>Chưa có nhóm audio nào có thể gộp.</span>`;
        }
        notice(`Chưa có nhóm audio nào có thể gộp.`);
        return;
      }

      renderMergeResult(groups, groupSize);
      notice(`Đã tự động gộp thành ${groups.length} file audio lớn (nhóm ${groupSize} chương)!`);
      if (typeof loadMergedGroups === 'function') loadMergedGroups();
    } catch (err) {
      if (resultBox) {
        resultBox.className = 'merge-result-card error';
        resultBox.innerHTML = `<span><i aria-hidden="true" class="fi fi-br-exclamation"></i> Lỗi tự động gộp: ${err.message}</span>`;
      }
      notice(err.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

// Single Chapter Actions (Reset / Delete)
const resetBtn = $('btn-reset-current');
if (resetBtn) resetBtn.onclick = () => safe(async () => {
  if (!selected) return;
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi đặt lại chương.', true);
    return;
  }
  const chapter = chapters.find(c => c.id === selected);
  const chapName = chapter ? (chapter.translated_title || chapter.title) : 'chương này';
  if (!confirm(`Xóa bản dịch của "${chapName}" để dịch lại?`)) return;

  const chapId = selected;
  const player = $('audio-player');
  if (player) {
    player.pause();
    player.removeAttribute('src');
    player.load();
  }

  resetBtn.disabled = true;
  const origText = resetBtn.innerHTML;
  resetBtn.innerHTML = '<i aria-hidden="true" class="fi fi-br-hourglass-end"></i> Đang đặt lại…';

  try {
    await api(`/api/chapters/${chapId}/reset`, {});
    await refreshAll();
    await selectChapter(chapId, true);
    notice(`Đã xóa bản dịch của "${chapName}".`);
  } finally {
    resetBtn.disabled = false;
    resetBtn.innerHTML = origText;
  }
});

const deleteBtn = $('btn-delete-current');
if (deleteBtn) deleteBtn.onclick = () => safe(async () => {
  if (!selected) return;
  if (state.progress.active) {
    notice('Hãy dừng job dịch trước khi xóa chương.', true);
    return;
  }
  const chapter = chapters.find(c => c.id === selected);
  const chapName = chapter ? (chapter.translated_title || chapter.title) : 'chương này';
  if (!confirm(`Xóa hẳn "${chapName}" khỏi truyện? Thao tác này sẽ xóa cả nguyên tác chương này.`)) return;

  const chapIdToDelete = selected;
  const currentIdx = chapters.findIndex(c => c.id === chapIdToDelete);
  let nextChapterId = null;
  if (chapters.length > 1) {
    const nextChapter = chapters[currentIdx + 1] || chapters[currentIdx - 1];
    if (nextChapter) nextChapterId = nextChapter.id;
  }

  // Pre-update selected so any WS events during deletion don't target the deleted chapter
  selected = nextChapterId;

  const player = $('audio-player');
  if (player) {
    player.pause();
    player.removeAttribute('src');
    player.load();
  }

  deleteBtn.disabled = true;
  const origText = deleteBtn.innerHTML;
  deleteBtn.innerHTML = '<i aria-hidden="true" class="fi fi-br-hourglass-end"></i> Đang xóa…';

  try {
    await api(`/api/chapters/${chapIdToDelete}/delete`, {});
    await refreshAll();
    if (nextChapterId && chapters.some(c => c.id === nextChapterId)) {
      await selectChapter(nextChapterId);
    } else if (chapters.length) {
      await selectChapter(chapters[0].id);
    } else {
      selected = null;
      $('reader-empty').hidden = false;
      $('reading-panes').hidden = true;
      $('chapter-single-ops').hidden = true;
    }
    notice(`Đã xóa "${chapName}" khỏi truyện.`);
  } finally {
    deleteBtn.disabled = false;
    deleteBtn.innerHTML = origText;
  }
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
  if (document.body.classList.contains('nav-open') || !$('settings-modal').hidden || document.querySelector('dialog[open]')) return;
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
  if (event.message || event.error) recordActivity(event.message || event.error, String(event.type).includes('error'));
  if (event.type === 'error') notice(event.message || 'Chương dịch lỗi.', true);
  if (event.type === 'cloud_checkpoint_done') { notice('Đã lưu checkpoint Hugging Face: ' + event.url); loadHuggingFaceSettings(); }
  if (event.type === 'cloud_checkpoint_error') notice('Lưu cloud thất bại, tiến độ cục bộ vẫn còn: ' + event.error, true);
  if (event.type === 'chapter_audio_error' || event.type === 'audio_group_error') notice(event.error || 'Lỗi xử lý audio.', true);
  if (event.type === 'audio_groups_updated') {
    renderMergeResult(event.groups, event.group_size || $('toc-group-size')?.value || 50);
    if (typeof loadMergedGroups === 'function') loadMergedGroups();
  }
  if (event.type === 'book_deleted') {
    selected = null;
    selectedChapterIds.clear();
    isSelectMode = false;

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
      if (selected) {
        if (chapters.some(c => c.id === selected)) {
          await selectChapter(selected, true);
        } else if (chapters.length) {
          await selectChapter(chapters[0].id);
        } else {
          selected = null;
          $('reader-empty').hidden = false;
          $('reading-panes').hidden = true;
          $('chapter-single-ops').hidden = true;
        }
      }
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
    setIconLabel($('connection'), 'circle', 'Đã kết nối');
  };
  ws.onmessage = e => {
    try {
      handleEvent(JSON.parse(e.data));
    } catch {}
  };
  ws.onclose = () => {
    setIconLabel($('connection'), 'circle', 'Đang kết nối lại');
    setTimeout(connect, retry);
    retry = Math.min(15000, retry * 2);
  };
  ws.onerror = () => ws.close();
}

// ----------------- INITIALIZATION -----------------
$('translation-controls').open = true;
safe(async () => {
  setFontSize(currentFontSize);
  setViewMode(currentViewMode);
  const savedBackend = localStorage.getItem('novel_backend') || 'ct2';
  setBackend(savedBackend);
  await Promise.all([loadHardware(), loadModels(), loadVoices(), loadExportDestination(), loadHuggingFaceSettings()]);
  const s = await refreshAll();

  if (s.book) {
    try {
      const c = JSON.parse(s.book.config);
      if (c.backend) setBackend(c.backend);
      if (c.engine) $('engine').value = c.engine === 'local' ? 'HachimiMT-60-QT' : c.engine;
      $('glossary').value = c.glossary || '';
      $('batch').value = c.batch_size || Math.min(1024, currentHardware?.batch_size || 8);
      if ($('opt-audio-pipeline')) $('opt-audio-pipeline').checked = c.audio_pipeline !== false;
      if ($('audio-workers')) $('audio-workers').value = c.audio_workers || 1;
      if ($('audio-queue-size')) $('audio-queue-size').value = c.audio_queue_size || 4;
      if ($('cloud-checkpoint-auto')) $('cloud-checkpoint-auto').checked = !!c.cloud_checkpoint;
      if ($('checkpoint-include-audio')) $('checkpoint-include-audio').checked = !!c.checkpoint_include_audio;
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
        setNormalizeMode(c.normalize_mode);
      }
      if (c.generate_audio !== undefined && $('opt-audio')) {
        $('opt-audio').checked = !!c.generate_audio;
      }
      if (c.audio_speed !== undefined && $('audio-speed')) {
        const targetVal = parseFloat(c.audio_speed);
        const matchOpt = Array.from($('audio-speed').options).find(o => Math.abs(parseFloat(o.value) - targetVal) < 0.01);
        if (matchOpt) {
          $('audio-speed').value = matchOpt.value;
        } else {
          $('audio-speed').value = '1.0';
        }
      }
      if (c.voice_id) {
        if ($('voice-select')) $('voice-select').value = c.voice_id;
        if ($('modal-voice')) $('modal-voice').value = c.voice_id;
      }
      if (c.noise_scale !== undefined && c.noise_w_scale !== undefined) {
        setEmotion(c.noise_scale, c.noise_w_scale);
      }
      if (c.audio_format) {
        if ($('audio-format')) $('audio-format').value = c.audio_format;
        if ($('modal-audio-format')) $('modal-audio-format').value = c.audio_format;
      }
      if (c.audio_bitrate && $('modal-audio-bitrate')) {
        $('modal-audio-bitrate').value = c.audio_bitrate;
      }
      if (c.auto_group_audio !== undefined) {
        if ($('modal-auto-group')) $('modal-auto-group').checked = !!c.auto_group_audio;
        if ($('opt-auto-group')) $('opt-auto-group').checked = !!c.auto_group_audio;
      }
      if (c.group_size) syncGroupSize(c.group_size);
      await applyAudioConfig(c);
      updateModelInfo();

    } catch (e) { notice(e.message, true); }
    if (chapters.length) {
      await selectChapter(chapters.find(c => c.status !== 'done')?.id || chapters[0].id);
    }
  }
  if (!s.book) await applyAudioConfig((await api('/api/settings/audio')).settings);
  setNormalizeMode($('normalize-mode').value);
  updateControlSummary();
  connect();
});

// Periodic fallback polling
setInterval(() => safe(async () => {
  const s = await api('/api/state');
  updateBook(s.book);
  renderProgress(s.progress);
}), 4000);

if ($('btn-save-book-title')) $('btn-save-book-title').onclick = () => safe(async () => {
  const title = $('book-output-title').value.trim();
  if (!title) throw new Error('Hãy nhập tên truyện.');
  const result = await api('/api/book/title', {title});
  updateBook(result.book);
  notice('Đã lưu tên truyện và chuyển output vào thư mục tương ứng.');
});

// v4.6 export chooser: existing tested export handlers remain the transport layer.
let exportOptions = null;
function updateExportReview() {
 const kind=document.querySelector('input[name="export-kind"]:checked')?.value||'txt';
 const dest=$('export-destination').value;
 const total=exportOptions?.chapters ?? chapters.length, done=exportOptions?.translated ?? chapters.filter(c=>c.status==='done').length;
 const count=exportOptions?.audio_files ?? 0;
 $('export-book-name').textContent=exportOptions?.book_title||state.book?.title||'Chưa nạp truyện';
 $('export-progress-summary').textContent=`${done}/${total} chương đã dịch · ${count} tệp audio`;
 $('export-result-summary').textContent=kind==='audio'?(dest==='huggingface'?'Từng tệp audio gốc, không ZIP':'Một file ZIP chứa audio đã có'):(kind==='epub'?'Một file EPUB':'Một file TXT UTF-8');
 $('export-format-hint').textContent=kind==='audio'?'Không tự tạo audio mới, không đổi giọng/bitrate khi xuất. Các tệp audio đã gộp (nếu có) cũng được xuất.': 'Xuất bản dịch hiện có theo thứ tự chương; chương chưa dịch được đánh dấu. Không xuất riêng dải chương ở bước này.';
 const problem=!state.book?'Nạp truyện trước khi xuất.':!exportOptions?'Đang kiểm tra dữ liệu…':kind==='audio'&&exportOptions.busy?'Dừng job trước khi xuất audio để tránh tệp thay đổi.':kind==='audio'&&!count?'Chưa có audio. Tạo audio trước khi xuất.':huggingfaceExportBusy?'Đang xuất dữ liệu, vui lòng đợi.':'';
 $('export-inline-status').textContent=problem || (dest==='huggingface'?'Lưu vào uri410/novelreader-storage. Giữ runtime mở trong lúc tải.':'Bản gốc vẫn được giữ trên máy chạy tool.');
 $('btn-confirm-export').disabled=!!problem;
}
$('btn-open-export').onclick=()=>safe(async()=>{
 if(!$('export-dialog').open)$('export-dialog').showModal();
 exportOptions=null;updateExportReview();
 try {exportOptions=await api('/api/export/options');updateExportReview();}
 catch(e){$('export-inline-status').textContent=e.message;}
});
$('btn-close-export').onclick=$('btn-cancel-export').onclick=()=>$('export-dialog').close();
$('export-destination').addEventListener('change',updateExportReview);
document.querySelectorAll('input[name="export-kind"]').forEach(el=>el.onchange=updateExportReview);
$('btn-confirm-export').onclick=()=>{
 if($('btn-confirm-export').disabled)return;
 const kind=document.querySelector('input[name="export-kind"]:checked').value;
 $('export-dialog').close();$(`export-${kind}`).click();
};
$('export-storage-settings').onclick=()=>{$('export-dialog').close();openSettingsPage('tab-cloud');};

function updateControlSummary() {
  const engine = $('engine').selectedOptions[0]?.textContent.split(' (')[0] || 'Chọn model';
  if ($('control-summary')) $('control-summary').textContent = engine + ' · ' + ($('opt-audio')?.checked ? 'Audio tự động' : 'Chỉ văn bản');
}
$('engine').addEventListener('change', updateControlSummary);
$('opt-audio').addEventListener('change', updateControlSummary);
updateControlSummary();
