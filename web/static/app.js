'use strict';

const $ = id => document.getElementById(id);
let chapters = [], selected = null, state = { progress: { status: 'ready', active: false } };
let visible = 100, busy = false, ws, retry = 1000;
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

function exportBook(format) {
  const link = document.createElement('a');
  link.href = '/api/export/' + format;
  document.body.append(link);
  link.click();
  link.remove();
}

async function loadHardware() {
  try {
    currentHardware = await api('/api/hardware');
    if (currentHardware) {
      const dev = currentHardware.is_gpu ? 'GPU' : (currentHardware.has_discrete_gpu ? 'GPU rời' : 'CPU');
      const devName = currentHardware.gpu_name ? ` (${currentHardware.gpu_name})` : '';
      if ($('hw-pill')) {
        $('hw-pill').textContent = `${dev}: ${currentHardware.cpu_count} luồng${devName}`;
        $('hw-pill').title = currentHardware.summary || '';
      }
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

  if (noteEl) noteEl.style.display = 'flex';

  if (m.id === 'space' || m.id.startsWith('space:')) {
    badge.className = 'badge badge-success';
    badge.textContent = ' Space Online';
    if (btnBadge) btnBadge.style.display = 'none';
    if (downloadBox) downloadBox.style.display = 'none';
    $('engine-note-title').textContent = `${m.name} · Trực tuyến HF Space`;
    $('engine-note-desc').textContent = m.desc || 'Dịch trực tuyến qua HF Space (ngocdang83/HachimiMT-demo). Không tốn tài nguyên máy.';
  } else if (m.downloaded) {
    badge.className = 'badge badge-success';
    badge.textContent = `✓ Sẵn sàng (${backendLabel})`;
    if (btnBadge) btnBadge.style.display = 'none';
    if (downloadBox) downloadBox.style.display = 'none';
    $('engine-note-title').textContent = `${m.name} · Offline (${backendLabel})`;
    $('engine-note-desc').textContent = m.desc || `Model đã có trên máy, chạy hoàn toàn offline qua ${backendLabel}.`;
  } else {
    badge.className = 'badge badge-warning';
    badge.textContent = `⬇ Chưa tải (${backendLabel})`;
    $('engine-note-title').textContent = `Chưa có trọng số model (~${m.size_mb || 58} MB) · ${backendLabel}`;
    $('engine-note-desc').textContent = m.desc ? `${m.desc} Bấm nút bên dưới để tải về máy hoặc hệ thống sẽ tự động tải khi bắt đầu dịch.` : `Model sẽ được tải tự động (${backendLabel}) khi dịch hoặc bạn có thể tải trước.`;

    if (btnBadge) {
      btnBadge.style.display = 'inline-block';
      btnBadge.textContent = '⬇ Tải model';
      btnBadge.title = `Tải model ${key} (${backendLabel})`;
    }
    if (downloadBox) {
      downloadBox.style.display = 'flex';
      if (btnAction) {
        btnAction.textContent = `⬇ Tải model ${backendLabel} (~${m.size_mb || 58} MB)`;
      }
      if (gpuHint) {
        gpuHint.style.display = 'inline-flex';
        const hasGpu = currentHardware && (currentHardware.is_gpu || currentHardware.has_discrete_gpu);
        if (hasGpu) {
          gpuHint.className = 'gpu-hint';
          const gpuLabel = currentHardware.gpu_name || 'NVIDIA GPU';
          const vramLabel = currentHardware.vram_gb ? ` (${currentHardware.vram_gb} GB)` : '';
          gpuHint.textContent = `⚡ GPU rời khả dụng: ${gpuLabel}${vramLabel} — Đề xuất tải để tăng tốc!`;
        } else {
          gpuHint.className = 'gpu-hint no-gpu';
          gpuHint.textContent = `ℹ Đang chạy CPU. Bấm nút để tải model offline về máy.`;
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
    btnAction.textContent = `⏳ Đang tải ${key} (${backendLabel})...`;
  }
  if (btnBadge) {
    btnBadge.disabled = true;
    btnBadge.textContent = '⏳ Đang tải...';
  }

  notice(`⏳ Đang tải model ${key} (${backendLabel}) từ Hugging Face... Vui lòng đợi trong giây lát.`);

  try {
    const res = await api('/api/models/download', {
      model_id: key,
      backend: selectedBackend
    });
    notice(`✅ ${res.message || 'Đã tải xong model!'}`);
    await loadModels();
  } catch (err) {
    notice(`❌ ${err.message || 'Lỗi khi tải model.'}`, true);
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


let availableVoices = [];

async function loadVoices() {
  try {
    availableVoices = await api('/api/voices?tts_engine=' + encodeURIComponent($('tts-engine')?.value || 'piper'));
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
 return {tts_engine:$('tts-engine').value,voice_id:$('voice-select').value,audio_speed:Number($('audio-speed').value),noise_scale:Number($('modal-noise-scale').value),noise_w_scale:Number($('modal-noise-w').value),audio_format:$('audio-format').value,audio_bitrate:$('modal-audio-bitrate').value,audio_sample_rate:Number($('audio-sample-rate').value),vieneu_temperature:Number($('vieneu-temperature').value),vieneu_top_p:Number($('vieneu-top-p').value),vieneu_batch_size:Number($('vieneu-batch-size').value)};
}
function updateTtsCapabilities() {
 const vie=$('tts-engine').value==='vieneu', format=$('audio-format').value;
 $('piper-noise-controls').hidden=vie; $('vieneu-controls').hidden=!vie; $('emotion-preset').closest('.audio-cfg-row').hidden=vie;
 $('audio-workers').disabled=vie; if(vie)$('audio-workers').value='1';
 $('audio-concurrency-hint').textContent=vie?'VieNeu dùng một model chung, xử lý từng chương. Tăng Batch đoạn / GPU trong Nâng cao để gộp đoạn trong chương.':'Piper: bật pipeline để chạy nhiều chương. Thử 2–4 trước; mỗi worker nạp một phiên riêng, dùng thêm VRAM.';
 $('modal-audio-bitrate').disabled=format==='wav'; $('audio-sample-rate').disabled=format==='opus';if(format==='opus')$('audio-sample-rate').value='48000';
 const low=format==='mp3'&&[22050,24000].includes(Number($('audio-sample-rate').value));
 $('modal-audio-bitrate').querySelector('option[value="192k"]').disabled=low;
 if(low&&$('modal-audio-bitrate').value==='192k')$('modal-audio-bitrate').value='128k';
 $('audio-output-hint').textContent=(vie?'VieNeu gốc: 48 kHz. ':'Piper: tần số gốc tùy model. ')+'Tăng kHz không tạo thêm chi tiết. WAV bỏ qua kbps; Opus luôn 48 kHz. MP3 192 kbps cần 44.1/48 kHz (kể cả khi model gốc thấp hơn).';
}
async function applyAudioConfig(c) {
 $('tts-engine').value=c.tts_engine||'piper';$('modal-tts-engine').value=$('tts-engine').value;await loadVoices();
 if(c.voice_id&&availableVoices.some(v=>v.id===c.voice_id)){$('voice-select').value=c.voice_id;$('modal-voice').value=c.voice_id;}
 const speed=Number(c.audio_speed??1);let option=[...$('audio-speed').options].find(o=>Number(o.value)===speed);
 if(!option){option=new Option(`${speed}x`,String(speed));$('audio-speed').add(option);}$('audio-speed').value=option.value;
 setEmotion(c.noise_scale??0.667,c.noise_w_scale??0.8);
 $('audio-format').value=c.audio_format||'mp3';$('modal-audio-format').value=$('audio-format').value;
 $('modal-audio-bitrate').value=c.audio_bitrate||'96k';$('audio-sample-rate').value=String(c.audio_sample_rate??0);
 $('vieneu-temperature').value=c.vieneu_temperature??0.8;$('vieneu-top-p').value=c.vieneu_top_p??0.95;$('vieneu-batch-size').value=c.vieneu_batch_size??8;updateTtsCapabilities();
}
$('audio-sample-rate').onchange=updateTtsCapabilities;
for(const id of ['tts-engine','modal-tts-engine'])$(id).onchange=()=>safe(async()=>{$('tts-engine').value=$(id).value;$('modal-tts-engine').value=$(id).value;await loadVoices();updateTtsCapabilities();});

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

if ($('audio-format') && $('modal-audio-format')) {
  $('audio-format').onchange = () => {
    $('modal-audio-format').value = $('audio-format').value; updateTtsCapabilities();
  };
  $('modal-audio-format').onchange = () => {
    $('audio-format').value = $('modal-audio-format').value; updateTtsCapabilities();
  };
}

let settingsReturnFocus = null;
function openSettingsModal(tabId = 'tab-translation') {
  settingsReturnFocus = document.activeElement;
  if ($('settings-modal')) $('settings-modal').hidden = false;
  switchSettingsTab(tabId);
  loadBucketSettings();
  loadMergedGroups();
  $('settings-modal').querySelector('.modal-tab.active')?.focus({preventScroll:true});
}

function closeSettingsModal() {
  if ($('settings-modal')) $('settings-modal').hidden = true;
  settingsReturnFocus?.focus({preventScroll:true});
}

function switchSettingsTab(tabId) {
  document.querySelectorAll('.modal-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tabId);
    t.setAttribute('aria-selected', String(t.dataset.tab === tabId));
    t.tabIndex = t.dataset.tab === tabId ? 0 : -1;
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.remove('active');
    p.style.display = 'none';
  });
  document.querySelector('#settings-modal .modal-body').scrollTop = 0;
  const activePane = $(`pane-${tabId}`);
  if (activePane) {
    activePane.classList.add('active');
    activePane.style.display = 'block';
  }
}

if ($('btn-open-settings')) $('btn-open-settings').onclick = () => openSettingsModal('tab-translation');
if ($('link-open-audio-settings')) {
  $('link-open-audio-settings').onclick = (e) => {
    e.preventDefault();
    openSettingsModal('tab-tts');
  };
}
if ($('btn-close-settings')) $('btn-close-settings').onclick = closeSettingsModal;
if ($('btn-cancel-settings')) $('btn-cancel-settings').onclick = closeSettingsModal;
if ($('settings-modal')) {
  $('settings-modal').onclick = (e) => {
    if (e.target === $('settings-modal')) closeSettingsModal();
  };
}

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

async function loadBucketSettings() {
  const status = $('hf-bucket-status');
  if (!status) return;
  try {
    const info = await api('/api/bucket/status');
    const cloud = state?.progress?.cloud_sync;
    $('hf-bucket-name').textContent = `${info.bucket_id} · ${info.visibility === 'public' ? 'Công khai' : 'Kiểm tra quyền chia sẻ'}`;
    status.textContent = info.write_enabled
      ? (cloud?.last_error ? `Lỗi đồng bộ: ${cloud.last_error}` : info.books_error ? `Có token · Không tải được danh sách: ${info.books_error}` : `Đã cấu hình token · ${info.books.length} truyện · ${cloud?.pending || 0} tệp đang chờ`)
      : (info.books_error ? `Nhập token Hugging Face có quyền ghi để bật tự lưu: ${info.books_error}` : 'Nhập token Hugging Face có quyền ghi để bật tự lưu.');
    status.className = info.write_enabled ? 'bucket-connected' : 'bucket-readonly';
    const select = $('hf-bucket-books');
    const selectedValue = select.value;
    select.replaceChildren(new Option('Chọn truyện để khôi phục', ''));
    for (const book of info.books) {
      const option = new Option(`${book.book_id} · ${book.created_at || ''}`, book.book_id);
      select.add(option);
    }
    if ([...select.options].some(option => option.value === selectedValue)) select.value = selectedValue;
  } catch (error) {
    status.textContent = `Không kết nối được Bucket: ${error.message}`;
  }
}

if ($('btn-hf-bucket-token')) $('btn-hf-bucket-token').onclick = () => safe(async () => {
  const input = $('hf-bucket-token');
  const result = await api('/api/bucket/token', {token: input.value.trim()});
  input.value = '';
  $('hf-bucket-status').textContent = result.write_enabled ? 'Đã kết nối ghi Bucket trong phiên này.' : 'Đã ngắt kết nối ghi Bucket.';
  await loadBucketSettings();
});
if ($('btn-bucket-refresh')) $('btn-bucket-refresh').onclick = () => safe(loadBucketSettings);
if ($('btn-bucket-save')) $('btn-bucket-save').onclick = () => checkpointAction(async () => {
  $('checkpoint-status').textContent = 'Đang tạo snapshot và đồng bộ Bucket…';
  $('hf-bucket-status').textContent = 'Đang lưu checkpoint lên Bucket…';
  const result = await api('/api/bucket/checkpoint', {});
  $('checkpoint-status').textContent = `Đã lưu checkpoint ${result.created_at}.`;
  notice(`Đã lưu checkpoint ${result.created_at} lên Bucket.`);
  await loadBucketSettings();
});
if ($('btn-bucket-restore')) $('btn-bucket-restore').onclick = () => checkpointAction(async () => {
  const bookId = $('hf-bucket-books').value;
  if (!bookId) throw new Error('Chọn một truyện trong Bucket trước.');
  if (!confirm('Thay truyện hiện tại bằng checkpoint trong Bucket? Bản xuất cũ được giữ nguyên.')) return;
  $('checkpoint-status').textContent = 'Đang tải checkpoint từ Bucket…';
  const result = await api('/api/bucket/restore', {book_id: bookId});
  selected = null;
  await refreshAll();
  $('checkpoint-status').textContent = `Đã khôi phục ${result.book?.title || bookId}.`;
  notice($('checkpoint-status').textContent);
});
if ($('btn-bucket-audio')) $('btn-bucket-audio').onclick = () => checkpointAction(async () => {
  const bookId = $('hf-bucket-books').value;
  if (!bookId) throw new Error('Chọn truyện đang mở trong Bucket trước.');
  $('checkpoint-status').textContent = 'Đang tải audio của truyện…';
  const result = await api('/api/bucket/audio', {book_id: bookId});
  $('checkpoint-status').textContent = `Đã nạp ${result.files} file audio (${(result.bytes / 1024 ** 2).toFixed(1)} MB).`;
  notice($('checkpoint-status').textContent);
});
if ($('btn-end-session')) $('btn-end-session').onclick = () => safe(async () => {
  if (!confirm('Dừng tác vụ, đồng bộ checkpoint lên Bucket và kết thúc công việc trong phiên này? Sau đó quay lại Molab để dừng runtime.')) return;
  const button = $('btn-end-session');
  button.disabled = true;
  try {
    if (state.progress.active) {
      await api('/api/translate/stop', {});
      for (let attempt = 0; attempt < 120; attempt++) {
        const current = await api('/api/state');
        renderProgress(current.progress);
        if (!current.progress.active) break;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      if (state.progress.active) throw new Error('Tác vụ chưa dừng sau 2 phút; hãy thử lại khi tác vụ đã dừng.');
    }
    const checkpoint = await api('/api/bucket/checkpoint', {});
    notice(`Đã lưu checkpoint ${checkpoint.created_at}. Quay lại Molab để dừng runtime.`);
    await loadBucketSettings();
  } finally {
    button.disabled = false;
  }
});

let checkpointBusy = false;
async function checkpointAction(action) {
  if (checkpointBusy) return;
  checkpointBusy = true;
  const buttons = document.querySelectorAll('.checkpoint-card button, .bucket-card button');
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
  $('checkpoint-status').textContent = result.message + ' Bấm Nạp bảng tạm để áp dụng cấu hình đã sao lưu.';
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
if ($('btn-save-settings')) {
  $('btn-save-settings').onclick = () => safe(async () => {
    await api('/api/checkpoints/draft', buildTranslatePayload());
    await api('/api/settings/audio', buildAudioPayload());
    closeSettingsModal();
    notice('✓ Đã lưu cài đặt nâng cao.');
  });
}

function setPurgeStatus(msg, isError = false) {
  const el = $('purge-status-msg');
  if (el) {
    el.textContent = msg;
    el.style.color = isError ? 'var(--red, #f87171)' : 'var(--green, #4ade80)';
  }
}

if ($('btn-purge-cache-only')) {
  $('btn-purge-cache-only').onclick = () => safe(async () => {
    if (state.progress.active) {
      notice('Hãy dừng job dịch trước khi dọn cache.', true);
      return;
    }
    setPurgeStatus('⏳ Đang dọn dẹp cache & file tạm...');
    const res = await api('/api/system/purge', { purge_data: false, purge_cache: true }, 'POST');
    setPurgeStatus(`✓ ${res.message}`);
    notice(`✓ ${res.message}`);
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
    setPurgeStatus('⏳ Đang xóa toàn bộ dữ liệu output...');
    const res = await api('/api/system/purge', { purge_data: true, purge_cache: false }, 'POST');
    selected = null;
    selectedChapterIds.clear();
    isSelectMode = false;

    await refreshAll();
    setPurgeStatus(`✓ ${res.message}`);
    notice(`✓ Đã xóa sạch toàn bộ data truyện và file output.`);
  });
}

if ($('btn-purge-everything')) {
  $('btn-purge-everything').onclick = () => safe(async () => {
    if (state.progress.active) {
      notice('Hãy dừng job dịch trước khi xóa tất cả.', true);
      return;
    }
    if (!confirm('⚠ CẢNH BÁO: Xóa dữ liệu và output của truyện hiện tại cùng cache ứng dụng. Output các truyện khác được giữ.\n\nBạn có chắc chắn muốn tiếp tục?')) {
      return;
    }
    setPurgeStatus('⏳ Đang xóa sạch toàn bộ data và cache của mọi thứ...');
    const res = await api('/api/system/purge', { purge_data: true, purge_cache: true }, 'POST');
    selected = null;
    selectedChapterIds.clear();
    isSelectMode = false;

    await refreshAll();
    setPurgeStatus(`✓ ${res.message}`);
    notice(`✓ ${res.message}`);
  });
}

async function loadMergedGroups() {
  const container = $('merged-groups-container');
  if (!container) return;
  try {
    const res = await api('/api/audio/groups');
    const groups = Array.isArray(res) ? res : (res.groups || []);
    if (!groups.length) {
      container.innerHTML = '<p class="text-dim" style="font-size:13px; color:#888;">Chưa có tập audio nào được gộp.</p>';
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
      info.innerHTML = `<strong>${g.filename}</strong> <span style="font-size:12px; color:#888;">(${sizeText})</span>`;

      const actions = document.createElement('div');
      actions.style.display = 'flex';
      actions.style.gap = '6px';
      actions.style.alignItems = 'center';

      const downloadLink = document.createElement('a');
      downloadLink.href = g.url || g.download_url;
      downloadLink.download = g.filename;
      downloadLink.className = 'btn-tool';
      downloadLink.textContent = '⬇ Tải file';

      actions.append(downloadLink);
      row.append(info, actions);
      list.append(row);
    });
    container.append(list);
  } catch (e) {
    container.innerHTML = `<p class="text-dim" style="color:var(--red,#f87171);">${e.message}</p>`;
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
    notice(`✓ Đã tạo thành công ${count} tập audio lớn!`);
    await loadMergedGroups();
  });
}

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
    selected = null;
    $('reader-empty').hidden = false;
    $('reading-panes').hidden = true;
    $('chapter-single-ops').hidden = true;
  }
  notice(`✓ ${res.message}`);
}

if ($('btn-purge-empty')) $('btn-purge-empty').onclick = () => safe(purgeEmptyChapters);
if ($('btn-modal-purge-empty')) $('btn-modal-purge-empty').onclick = () => safe(purgeEmptyChapters);

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
$('btn-translation-settings').onclick=()=>openSettingsModal('tab-translation');

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

function renderProgress(progress) {
  state.progress = progress;
  const p = progress;
  $('status').textContent = '● ' + (titles[p.status] || p.status);
  $('status').classList.toggle('busy', ['running', 'loading', 'stopping', 'paused'].includes(p.status));
  $('status').classList.toggle('error', p.status === 'error');

  const percent = p.total ? Math.floor(p.done / p.total * 100) : 0;
  $('progress-text').textContent = `${p.done}/${p.total}`;
  $('progress-text').title = p.scope ? `Phạm vi: ${p.scope}` : 'Toàn bộ truyện';
  $('percent').textContent = percent + '%';
  $('progress').value = percent;

  $('start').disabled = p.active || !state.book || busy;
  $('pause').disabled = !p.active || p.status === 'stopping';
  $('stop').disabled = !p.active || p.status === 'stopping';
  $('pause').textContent = p.status === 'paused' ? '▷ Tiếp tục' : 'Ⅱ Tạm dừng';

  const inputs = ['engine', 'glossary', 'batch', 'reset', 'load-path', 'file', 'opt-audio-pipeline', 'audio-workers', 'audio-queue-size', 'checkpoint-include-audio', 'opt-honorific', 'opt-pronoun', 'opt-t2s', 'beam-size', 'normalize-mode', 'btn-delete-book', 'btn-save-book-title', 'book-output-title', 'btn-trans-range', 'btn-auto-group-audio', 'range-start', 'range-end', 'trans-range-start', 'trans-range-end', 'toc-group-size', 'btn-reset-current', 'btn-delete-current', 'btn-download-model', 'btn-download-model-action'];
  inputs.forEach(id => {
    const el = $(id);
    if (el) el.disabled = p.active || busy || isDownloadingModel;
  });
  if ($('chunk-sentence-label')) $('chunk-sentence-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('chunk-paragraph-label')) $('chunk-paragraph-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('backend-ct2-label')) $('backend-ct2-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';
  if ($('backend-torch-label')) $('backend-torch-label').style.pointerEvents = (p.active || busy) ? 'none' : 'auto';

  $('btn-save-settings').disabled = p.active || busy;
  $('btn-open-export').disabled = !state.book;
  $('save-note').textContent = p.message || 'Tiến độ được lưu tự động trên máy của bạn.';
  const runtimeStatus = $('runtime-session-status');
  if (runtimeStatus) {
    const parts = [];
    if (Number.isFinite(p.session_seconds_remaining)) {
      const minutes = Math.floor(p.session_seconds_remaining / 60);
      parts.push(`Ngân sách phiên còn ${Math.floor(minutes / 60)}h ${minutes % 60}m`);
    }
    if (p.cloud_sync) {
      parts.push(`Bucket: ${p.cloud_sync.pending} đang chờ`);
      if (p.cloud_sync.last_success) parts.push(`đồng bộ gần nhất ${new Date(p.cloud_sync.last_success).toLocaleTimeString()}`);
      if (p.cloud_sync.last_error) parts.push(`lỗi: ${p.cloud_sync.last_error}`);
    }
    runtimeStatus.textContent = parts.join(' · ');
  }
}

function updateBook(book) {
  state.book = book;
  const outputFolder = book ? (book.output_folder || book.title) + '/' : '';
  if ($('output-text-path')) $('output-text-path').textContent = 'output_text/' + outputFolder;
  if ($('output-audio-path')) $('output-audio-path').textContent = 'output_audio/' + outputFolder;
  if ($('book-title-panel')) $('book-title-panel').hidden = !book;
  if ($('book-output-title') && document.activeElement !== $('book-output-title')) {
    $('book-output-title').value = book?.title || '';
  }
  $('file-info').hidden = !book;
  $('book-name').textContent = book ? book.title : 'Chưa nạp truyện';
  if (book) {
    $('filename').textContent = book.filename;
    $('encoding').textContent = book.encoding + ' · Đã lưu trên máy';
  } else {
    $('chapter-single-ops').hidden = true;
  }
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

    if (c.audio_status === 'done') {
      const audioBadge = document.createElement('span');
      audioBadge.className = 'toc-audio-badge';
      audioBadge.textContent = '';
      audioBadge.title = 'Đã có audio MP3';
      b.append(n, name, audioBadge, icon);
    } else if (['queued', 'generating'].includes(c.audio_status)) {
      const audioBadge = document.createElement('span');
      audioBadge.className = 'toc-audio-badge generating';
      audioBadge.textContent = '';
      audioBadge.title = 'Đang tạo audio...';
      b.append(n, name, audioBadge, icon);
    } else {
      b.append(n, name, icon);
    }
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
  let chapter;
  try {
    chapter = await api('/api/chapters/' + id);
  } catch (err) {
    console.warn(`Không thể tải chương ${id}:`, err);
    return;
  }
  if (!chapter) return;
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

  const audioBar = $('chapter-audio-bar');
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
        downloadBtn.textContent = `⬇ Tải ${fmt.toUpperCase()}`;
        msg.textContent = '✓ Audio chương đã sẵn sàng';
        msg.className = 'audio-status-msg';
      } else if (['queued', 'generating'].includes(chapter.audio_status)) {
        player.style.display = 'none';
        downloadBtn.hidden = true;
        msg.textContent = '⏳ Đang tạo audio…';
        msg.className = 'audio-status-msg';
        regenBtn.disabled = true;
      } else if (chapter.audio_status === 'error') {
        player.style.display = 'none';
        downloadBtn.hidden = true;
        msg.textContent = '⚠ Lỗi tạo audio. Bấm "Tạo Audio" để thử lại.';
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
    if ($('chapter-audio-bar')) $('chapter-audio-bar').hidden = true;
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

function buildTranslatePayload(extraConfig = {}) {
  const batch = Number($('batch').value);
  if (!Number.isInteger(batch) || batch < 1 || batch > 1024) {
    throw new Error('Batch size phải từ 1 đến 1024.');
  }

  const selectedChunkMode = document.querySelector('input[name="chunk_mode"]:checked')?.value || 'sentence';
  const autoGroup = $('opt-auto-group') ? $('opt-auto-group').checked : ($('modal-auto-group') ? $('modal-auto-group').checked : false);
  const groupSize = Number($('toc-group-size')?.value ?? $('opt-group-size')?.value ?? '50');

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
    voice_id: $('voice-select') ? $('voice-select').value : 'ngochuyennew',
    noise_scale: Number.isFinite(parseFloat($('modal-noise-scale')?.value)) ? parseFloat($('modal-noise-scale').value) : 0.667,
    noise_w_scale: Number.isFinite(parseFloat($('modal-noise-w')?.value)) ? parseFloat($('modal-noise-w').value) : 0.8,
    audio_format: $('audio-format') ? $('audio-format').value : 'mp3',
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
    notice(`▷ Bắt đầu dịch & tạo audio từ chương ${payload.start_pos} đến ${payload.end_pos}…`);
  } else if (payload.chapter_ids && payload.chapter_ids.length) {
    notice(`▷ Bắt đầu dịch & tạo audio cho ${payload.chapter_ids.length} chương đã chọn…`);
  } else {
    notice('▷ Bắt đầu dịch toàn bộ truyện…');
  }
}

$('start').onclick = () => safe(async () => {
  await startTranslate();
});

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

if ($('btn-regen-audio')) {
  $('btn-regen-audio').onclick = () => safe(async () => {
    if (!selected) return;
    const btn = $('btn-regen-audio');
    btn.disabled = true;
    $('audio-status-msg').textContent = '⏳ Đang tạo audio…';
    $('audio-status-msg').className = 'audio-status-msg';
    try {
      await api(`/api/chapters/${selected}/audio`, buildAudioPayload(), 'POST');
      notice('✓ Đã tạo xong audio cho chương!');
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
  await refreshAll();
  notice('✓ Đã xóa toàn bộ dữ liệu truyện.');
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
    <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(74,222,128,0.15);">
      <div>
        <strong style="color:var(--green,#4ade80);">${g.title || g.filename}</strong>
        <span style="color:#aaa; font-size:10px; margin-left:6px;">(${g.chapter_count} chương · ${g.size_mb} MB)</span>
      </div>
      <div style="display:flex; gap:6px;">
        <a href="${g.url}" download="${g.filename}" style="font-size:11px; color:#4ade80; text-decoration:none;">⬇ Tải</a>
        <button type="button" class="btn-play-group-item" data-url="${g.url}" data-name="${g.filename}" style="padding:2px 6px; font-size:10px; background:#1e2d23; border:1px solid #2d4534; border-radius:3px; color:#a7f3d0; cursor:pointer;"> Nghe</button>
      </div>
    </div>
  `).join('');

  resultBox.style.display = 'flex';
  resultBox.className = 'merge-result-card';
  resultBox.innerHTML = `
    <div class="merge-result-msg">
      <strong style="color:var(--green,#4ade80);">✓ Đã tự động gộp thành ${groups.length} file audio lớn (nhóm ${groupSize} chương):</strong>
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
      resultBox.innerHTML = `<span>⏳ Đang quét và tự động gộp file audio theo nhóm ${groupSize} chương...</span>`;
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
      notice(`✓ Đã tự động gộp thành ${groups.length} file audio lớn (nhóm ${groupSize} chương)!`);
      if (typeof loadMergedGroups === 'function') loadMergedGroups();
    } catch (err) {
      if (resultBox) {
        resultBox.className = 'merge-result-card error';
        resultBox.innerHTML = `<span>✗ Lỗi tự động gộp: ${err.message}</span>`;
      }
      notice(err.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

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
  resetBtn.innerHTML = '⏳ Đang đặt lại…';

  try {
    await api(`/api/chapters/${chapId}/reset`, {});
    await refreshAll();
    await selectChapter(chapId, true);
    notice(`✓ Đã xóa bản dịch của "${chapName}".`);
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

  selected = nextChapterId;

  const player = $('audio-player');
  if (player) {
    player.pause();
    player.removeAttribute('src');
    player.load();
  }

  deleteBtn.disabled = true;
  const origText = deleteBtn.innerHTML;
  deleteBtn.innerHTML = '⏳ Đang xóa…';

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
    notice(`✓ Đã xóa "${chapName}" khỏi truyện.`);
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

window.addEventListener('keydown', e => {
  if (!$('settings-modal').hidden || document.querySelector('dialog[open]')) return;
  if (['input', 'textarea', 'select'].includes(document.activeElement.tagName.toLowerCase())) return;
  if (e.key === '[' || e.key === 'ArrowLeft') {
    if (!$('prev').disabled) $('prev').click();
  } else if (e.key === ']' || e.key === 'ArrowRight') {
    if (!$('next').disabled) $('next').click();
  }
});

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

let updating = false, dirty = false;
async function handleEvent(event) {
  if (event.progress) renderProgress(event.progress);
  if (event.type === 'error') notice(event.message || 'Chương dịch lỗi.', true);
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

safe(async () => {
  setFontSize(currentFontSize);
  setViewMode(currentViewMode);
  const savedBackend = localStorage.getItem('novel_backend') || 'ct2';
  setBackend(savedBackend);
  await Promise.all([loadHardware(), loadModels(), loadVoices(), loadBucketSettings()]);
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
  connect();
});

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

let exportOptions = null;
function updateExportReview() {
  const kind = document.querySelector('input[name="export-kind"]:checked')?.value || 'txt';
  const total = exportOptions?.chapters ?? chapters.length;
  const done = exportOptions?.translated ?? chapters.filter(c => c.status === 'done').length;
  const count = exportOptions?.audio_files ?? 0;
  $('export-book-name').textContent = exportOptions?.book_title || state.book?.title || 'Chưa nạp truyện';
  $('export-progress-summary').textContent = `${done}/${total} chương đã dịch · ${count} tệp audio`;
  $('export-result-summary').textContent = kind === 'audio' ? 'Một file ZIP chứa audio đã có' : kind === 'epub' ? 'Một file EPUB' : 'Một file TXT UTF-8';
  $('export-format-hint').textContent = kind === 'audio'
    ? 'Tải các tệp audio hiện có, gồm cả các tập đã gộp. Không tạo audio mới.'
    : 'Tải bản dịch hiện có theo thứ tự chương; chương chưa dịch được đánh dấu.';
  const problem = !state.book ? 'Nạp truyện trước khi tải.'
    : !exportOptions ? 'Chưa kiểm tra được dữ liệu.'
    : kind === 'audio' && exportOptions.busy ? 'Dừng job trước khi tải audio.'
    : kind === 'audio' && !count ? 'Chưa có audio. Tạo audio trước.' : '';
  $('export-inline-status').textContent = problem || 'Tệp sẽ được tải về thiết bị của bạn.';
  const sync = state.progress?.cloud_sync;
  $('export-bucket-status').textContent = sync?.write_enabled
    ? (sync.last_error ? `Bucket đang thử lại: ${sync.last_error}` : `Hugging Face Bucket tự lưu · ${sync.pending || 0} tệp đang chờ`)
    : 'Chưa bật tự lưu Bucket. Kết nối token Hugging Face trong Cài đặt.';
  $('btn-confirm-export').disabled = !!problem;
}
$('btn-open-export').onclick=()=>safe(async()=>{
 if(!$('export-dialog').open)$('export-dialog').showModal();
 exportOptions=null;updateExportReview();
 try {exportOptions=await api('/api/export/options');updateExportReview();}
 catch(e){$('export-inline-status').textContent=e.message;}
});
$('btn-close-export').onclick=$('btn-cancel-export').onclick=()=>$('export-dialog').close();
document.querySelectorAll('input[name="export-kind"]').forEach(el=>el.onchange=updateExportReview);
$('btn-confirm-export').onclick=()=>{
 if($('btn-confirm-export').disabled)return;
 const kind=document.querySelector('input[name="export-kind"]:checked').value;
 $('export-dialog').close();
 exportBook(kind);
};
$('export-storage-settings').onclick=()=>{$('export-dialog').close();openSettingsModal('tab-cloud');};
$('settings-modal').addEventListener('keydown',event=>{
 if(event.key==='Escape'){event.preventDefault();closeSettingsModal();return;}
 if(event.key!=='Tab')return;
 const visible=[...$('settings-modal').querySelectorAll('button,input,select,summary,a[href],textarea')].filter(e=>!e.disabled&&e.getClientRects().length&&e.tabIndex!==-1);
 const first=visible[0],last=visible[visible.length-1];
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
});
