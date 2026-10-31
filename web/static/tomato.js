/* NovelReader/Tomato bridge: uses the existing application API and settings. */
'use strict';
(() => {
  const $t = id => document.getElementById(id);
  const form = $t('tomato-form');
  if (!form) return;

  const idField = $t('tomato-book-id');
  const startButton = $t('tomato-start');
  const cancelButton = $t('tomato-cancel');
  const statusLine = $t('tomato-status');
  const connectionLine = $t('tomato-connection');
  const checkButton = $t('tomato-check');
  const stage = $t('tomato-stage');
  const count = $t('tomato-count');
  const progress = $t('tomato-progress');
  const labels = {
    idle: 'Chưa bắt đầu',
    starting: 'Khởi tạo',
    downloading: 'Tải chương',
    importing: 'Nạp chương',
    translating: 'Chuyển sang dịch/TTS',
    done: 'Đã chuyển sang dịch/TTS',
    error: 'Lỗi',
    canceled: 'Đã hủy'
  };
  let lastStage = null;
  let polling = false;

  async function refreshTomato() {
    if (polling) return;
    polling = true;
    try {
      const info = await api('/api/tomato/status');
      startButton.disabled = !!info.active;
      cancelButton.disabled = !info.active || !['starting', 'downloading'].includes(info.stage);
      stage.textContent = labels[info.stage] || info.stage;
      statusLine.textContent = info.message || '';
      statusLine.classList.toggle('tomato-error', info.stage === 'error');
      count.textContent = Number(info.saved || 0) + ' / ' + Number(info.total || 0) + ' chương';
      progress.value = info.total ? Math.min(100, Math.round(100 * Number(info.saved || 0) / Number(info.total))) : 0;
      if (info.stage !== lastStage) {
        if ((info.stage === 'done' || info.stage === 'translating') && lastStage) {
          await refreshAll();
          if (chapters.length) await selectChapter(chapters[0].id);
          notice('Đã nạp truyện và bắt đầu dịch/TTS theo cấu hình hiện tại.');
        }
        if (info.stage === 'error' && lastStage && lastStage !== 'error') notice(info.message || 'Tải truyện lỗi.', true);
      }
      lastStage = info.stage;
    } catch (error) {
      statusLine.textContent = 'Không cập nhật được tiến độ: ' + error.message;
    } finally {
      polling = false;
    }
  }

  async function checkTomatoConnection() {
    checkButton.disabled = true;
    connectionLine.textContent = 'Đang kiểm tra dịch vụ Rust…';
    try {
      const info = await api('/api/tomato/health');
      const endpoint = info.url || 'chưa cấu hình';
      if (info.connected) {
        connectionLine.textContent = 'Đã kết nối: ' + endpoint + (info.version ? ' · v' + info.version : '');
        connectionLine.classList.remove('tomato-error');
      } else {
        connectionLine.textContent = 'Chưa kết nối: ' + endpoint + '. ' + (info.detail || 'Kiểm tra dịch vụ Rust.');
        connectionLine.classList.add('tomato-error');
      }
    } catch (error) {
      connectionLine.classList.add('tomato-error');
      connectionLine.textContent = 'Kiểm tra kết nối thất bại: ' + error.message;
    } finally {
      checkButton.disabled = false;
    }
  }

  checkButton.addEventListener('click', checkTomatoConnection);

  form.addEventListener('submit', event => {
    event.preventDefault();
    safe(async () => {
      const bookId = idField.value.trim();
      if (!/^[0-9]{8,25}$/.test(bookId)) throw new Error('ID truyện phải có từ 8 đến 25 chữ số.');
      const replace = !!state.book;
      if (state.progress?.active) throw new Error('Hãy dừng tác vụ dịch hiện tại trước.');
      if (replace && !confirm('Thay thế truyện đang mở bằng truyện có ID ' + bookId + '? Dữ liệu hiện tại trong cơ sở dữ liệu sẽ được thay thế.')) return;
      const config = buildTranslatePayload({
        reset: false, start_pos: null, end_pos: null, chapter_ids: null,
        force_retranslate: false
      });
      if (config.engine.startsWith('space') && !confirm('Cấu hình dịch hiện tại sử dụng dịch vụ trực tuyến. Tiếp tục gửi nội dung truyện tới dịch vụ đó?')) return;
      const data = await api('/api/tomato/start', { book_id: bookId, replace_existing: replace, config });
      lastStage = null;
      statusLine.textContent = data.message || 'Đã bắt đầu tải.';
      startButton.disabled = true;
      cancelButton.disabled = false;
      await refreshTomato();
    });
  });

  cancelButton.addEventListener('click', () => safe(async () => {
    if (!confirm('Hủy quá trình tải truyện từ Tomato?')) return;
    await api('/api/tomato/cancel', {});
    await refreshTomato();
  }));

  refreshTomato();
  checkTomatoConnection();
  setInterval(refreshTomato, 3000);
})();
