"""Browser regressions. Optional: pip install playwright; playwright install chromium."""
import os
import io
import socket
import subprocess
import sys
import time
import wave
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
from urllib.request import urlopen

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def browser_app(tmp_path_factory):
    root = tmp_path_factory.mktemp('browser-app')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, NOVEL_DATA=str(root/'data'),
               NOVEL_OUTPUT_TEXT=str(root/'text'), NOVEL_OUTPUT_AUDIO=str(root/'audio'),
               HF_HUB_OFFLINE='1')
    # Never inherit a tunnel password or remote-host configuration for a local test.
    for key in ('NOVEL_WEB_ACCESS_TOKEN', 'ALLOW_TUNNEL', 'ALLOWED_HOSTS', 'COLAB_GPU', 'HF_TOKEN'):
        env.pop(key, None)
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app', '--host',
                               '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                with urlopen(url, timeout=1):
                    break
            except OSError:
                if server.poll() is not None:
                    pytest.fail('Isolated test server exited before startup')
                time.sleep(.1)
        else:
            pytest.fail('Isolated test server did not start')
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except playwright.Error as exc:
                pytest.skip(f'Chromium unavailable: {exc}')
            yield browser, url
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture
def page(browser_app):
    browser, url = browser_app
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.set_default_timeout(5000)
    page.goto(url)
    page.wait_for_function("document.querySelector('#connection').textContent.includes('Đã kết nối')")
    yield page
    page.close()


def navigate(page, target):
    button = page.locator('#'+target)
    if page.viewport_size['width'] <= 900:
        if not page.evaluate("document.body.classList.contains('nav-open')"):
            page.locator('#mobile-nav-toggle').click()
    button.click()


# Use actual chapter rendering and copy handlers, with deterministic network timing/data.
CHAPTERS = """
ws.onmessage = null; ws.onclose = null; ws.close();
while (updating) await new Promise(r => setTimeout(r, 10));
const fixture = id => ({id,position:id,title:'Chương '+id,
 source:['一','二','三'],translated:['(Một lời chú thích)','Bản dịch sẽ thay đổi.','Đang chờ mùa xuân.'],
 status:'done',outputs:['a','b','c'],plan:['a','b','c'],audio_status:'pending'});
chapters = [fixture(1), fixture(2)];
"""


def test_latest_chapter_selection_wins(page):
    result = page.evaluate('''async () => {''' + CHAPTERS + '''
      const originalApi = api;
      api = async path => {
        const id = Number(path.split('/').pop());
        await new Promise(r => setTimeout(r, id === 1 ? 180 : 10));
        return fixture(id);
      };
      try {
        await Promise.all([selectChapter(1), selectChapter(2)]);
        return document.querySelector('#chapter-title').textContent;
      } finally { api = originalApi; }
    }''')
    assert result == 'Chương 2'


def test_background_refresh_does_not_override_pending_selection(page):
    result = page.evaluate('''async () => {''' + CHAPTERS + '''
      const originalApi = api;
      selected = 1;
      api = async path => {
        const id = Number(path.split('/').pop());
        await new Promise(r => setTimeout(r, id === 2 ? 120 : 10));
        return fixture(id);
      };
      try {
        await Promise.all([selectChapter(2), selectChapter(1, true)]);
        return document.querySelector('#chapter-title').textContent;
      } finally { api = originalApi; }
    }''')
    assert result == 'Chương 2'


def test_copy_preserves_real_paragraphs_and_reports_unavailable_clipboard(page):
    copied = page.evaluate('''async () => {''' + CHAPTERS + '''
      const originalApi = api;
      api = async () => fixture(1);
      try { await selectChapter(1); } finally { api = originalApi; }
      let text = '';
      Object.defineProperty(navigator, 'clipboard', {configurable:true,
        value:{writeText:async value => {text=value}}});
      await document.querySelector('#copy-btn').onclick();
      Object.defineProperty(navigator, 'clipboard', {configurable:true,value:undefined});
      await document.querySelector('#copy-btn').onclick();
      return {text, error:document.querySelector('#notice-text').textContent};
    }''')
    assert copied['text'] == 'Chương 1\n\n(Một lời chú thích)\n\nBản dịch sẽ thay đổi.\n\nĐang chờ mùa xuân.'
    assert 'HTTPS' in copied['error']


def test_invalid_reader_preferences_recover(page):
    page.evaluate("localStorage.setItem('novel_font_size','broken');localStorage.setItem('novel_view_mode','broken')")
    page.reload()
    page.wait_for_function("document.querySelector('#font-val').textContent === '17px'")
    assert page.locator('.view-btn.active').get_attribute('data-mode') == 'parallel'
    navigate(page, 'tab-reader')
    page.locator('#font-inc').click()
    assert page.locator('#font-val').inner_text() == '18px'


@pytest.mark.parametrize('width,height', [(1440,900),(768,1024),(390,844),(320,740)])
def test_layout_settings_export_and_mobile_reader(page, width, height):
    page.set_viewport_size({'width':width,'height':height})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#sidebar').is_visible()
    assert page.locator('#reader').is_hidden()
    if width == 1440 and 'has-book' in page.locator('#sidebar').get_attribute('class'):
        chapters_box = page.locator('.toc-panel').bounding_box()
        config_box = page.locator('.config-panel').bounding_box()
        assert chapters_box['y'] < 600
        assert config_box['x'] > chapters_box['x'] + chapters_box['width']
        assert abs(config_box['y'] - chapters_box['y']) < 2
    if width <= 900:
        assert page.locator('.topbar').bounding_box()['height'] < 120
        navigate(page, 'tab-reader')
        assert page.locator('#reader').is_visible()
        navigate(page, 'tab-sidebar')
        assert page.locator('#sidebar').is_visible()
    page.locator('#btn-open-settings').click()
    panel = page.locator('#pane-tab-translation')
    assert panel.is_visible()
    assert panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    page.locator('.translation-advanced > summary').click()
    page.locator('#btn-translation-cleanup').click()
    assert page.locator('#pane-tab-cache').is_visible()
    page.locator('#settings-nav-translation').click()
    page.keyboard.press('Escape')
    assert page.locator('#settings-modal').is_visible()
    page.locator('#btn-close-settings').click()
    assert page.locator('#settings-modal').is_hidden()
    response = page.request.post(page.url.rstrip('/')+'/api/upload', headers={'X-App-Request':'novel-translator'},
        multipart={'file': {'name':'sample.txt', 'mimeType':'text/plain',
                            'buffer':'第一章 开始\n你好。\n第二章 归来\n世界！'.encode()}})
    assert response.ok
    page.reload()
    page.wait_for_function("document.querySelector('#chapter-title').textContent !== 'Chưa chọn chương'")
    page.locator('.toc-item').first.click()
    page.wait_for_function("document.activeElement.id === 'chapter-title'")
    assert page.locator('#tab-reader').get_attribute('aria-pressed') == 'true'
    assert page.locator('#sidebar').is_hidden()
    assert page.locator('#reader').is_visible()
    if width == 1440:
        assert page.locator('#reader').bounding_box()['width'] == width - page.locator('#app-navigation').bounding_box()['width']
    assert page.locator('#source-pane .para').count() > 0
    assert page.locator('#source-pane').bounding_box()['height'] > 80
    for selector in ('.chapter-toolbar', '.reading-panes'):
        assert page.locator(selector).evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    assert page.locator('#source-heading').is_visible()
    assert page.locator('#target-heading').is_visible()
    assert abs(page.locator('.source-column').bounding_box()['width'] -
               page.locator('.target-column').bounding_box()['width']) <= 1
    page.locator('#btn-open-export').click()
    assert page.locator('#export-dialog').is_visible()
    page.locator('input[name=export-kind][value=audio]').check()
    assert page.locator('#btn-confirm-export').is_disabled()
    page.keyboard.press('Escape')
    assert page.locator('#export-dialog').is_hidden()
    if height > 650:
        page.locator('#back-to-studio').click()
    else:
        navigate(page, 'tab-sidebar')
    assert page.locator('#sidebar').is_visible()
    assert page.locator('#reader').is_hidden()
    page.locator('#search').fill('归来')
    assert page.locator('.toc-item').count() == 1
    page.locator('#search').fill('a chapter that does not exist')
    assert page.locator('.toc-item').count() == 0
    assert page.locator('.toc-empty').is_visible()


def test_reference_sidebar_collapse_and_theme_persist(page):
    assert page.locator('html').get_attribute('data-theme') == 'dark'
    original = page.locator('#app-navigation').bounding_box()['width']
    page.locator('#toggle-navigation').click()
    assert page.locator('#app-navigation').bounding_box()['width'] < original / 2
    assert page.locator('#toggle-navigation').get_attribute('aria-expanded') == 'false'
    page.locator('.header-theme').click()
    assert page.locator('html').get_attribute('data-theme') == 'light'
    page.reload()
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    assert page.locator('#app-navigation').bounding_box()['width'] == 72
    page.locator('#toggle-navigation').click()
    page.locator('#nav-audio').click()
    assert page.locator('#pane-tab-tts').is_visible()
    page.keyboard.press('Escape')
    page.locator('#nav-storage').click()
    assert page.locator('#pane-tab-cloud').is_visible()


def test_mobile_navigation_closes_and_restores_focus(page):
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('#app-navigation').is_hidden()
    page.locator('#mobile-nav-toggle').click()
    assert page.locator('#app-navigation').is_visible()
    assert page.locator('#mobile-nav-toggle').get_attribute('aria-expanded') == 'true'
    page.keyboard.press('Escape')
    assert page.locator('#app-navigation').is_hidden()
    assert page.evaluate("document.activeElement.id === 'mobile-nav-toggle'")
    page.locator('#mobile-nav-toggle').click()
    page.locator('#nav-audio').click()
    assert page.locator('#settings-modal').is_visible()
    assert page.locator('#app-navigation').is_hidden()
    assert page.locator('#btn-close-settings').is_hidden()
    navigate(page, 'tab-sidebar')
    assert page.evaluate("document.activeElement.id === 'mobile-nav-toggle'")


@pytest.mark.parametrize('width', [1440,390])
def test_tools_are_full_pages_and_dock_is_removed(page,width):
    page.set_viewport_size({'width':width,'height':900})
    assert page.locator('.monitor-dock').count() == 0
    assert page.locator('dialog#resource-popup,dialog#task-popup').count() == 0
    for nav,panel in [('nav-audio','pane-tab-tts'),('nav-storage','pane-tab-cloud'),
                       ('nav-backup','pane-tab-backup'),('nav-settings','pane-tab-translation')]:
        navigate(page,nav)
        assert page.locator('#'+panel).is_visible()
        assert page.locator('#settings-modal').get_attribute('role') == 'region'
        assert page.locator('dialog[open]').count() == 0
        assert page.locator('#sidebar').is_hidden()
        assert page.locator('#reader').is_hidden()
        assert page.locator('#settings-modal').bounding_box()['width'] == page.locator('.workspace').bounding_box()['width']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#'+nav).get_attribute('aria-pressed') == 'true'
        if nav == 'nav-audio':
            for selector in ('#btn-close-settings', '.translation-tabs', '.glossary-box', '.translation-credits'):
                assert page.locator(selector).is_hidden()
    navigate(page,'nav-monitor')
    assert page.locator('#monitor-page').is_visible()
    assert page.locator('#settings-modal').is_hidden()
    assert page.locator('#resource-cards .resource-card').count() == 5
    assert page.locator('#translation-detail').is_visible()
    assert page.locator('dialog[open]').count() == 0
    navigate(page,'tab-sidebar')
    assert page.locator('#monitor-page').is_hidden()
    assert page.locator('#sidebar').is_visible()


def test_saving_settings_keeps_tool_page_open(page):
    navigate(page,'nav-audio')
    page.locator('#modal-audio-format').select_option('wav')
    assert page.locator('#modal-audio-bitrate').is_disabled()
    page.locator('#modal-audio-format').select_option('mp3')
    assert page.locator('#modal-audio-bitrate').is_enabled()
    page.locator('#modal-audio-bitrate').select_option('128k')
    page.locator('#audio-speed').select_option('1.15')
    page.locator('#btn-save-settings').click()
    page.wait_for_function("document.querySelector('#notice-text').textContent === 'Đã lưu cài đặt.'")
    assert page.locator('#settings-modal').is_visible()
    assert page.locator('#pane-tab-tts').is_visible()
    payload = page.evaluate('buildAudioPayload()')
    assert payload['audio_format'] == 'mp3'
    assert payload['audio_bitrate'] == '128k'
    assert payload['audio_speed'] == 1.15


def test_translation_choices_are_readable_and_keyboard_accessible(page):
    navigate(page,'nav-settings')
    for theme in ('light','dark'):
        if page.locator('html').get_attribute('data-theme') != theme:
            page.locator('.header-theme').click()
        ratios = page.locator('.triplet-card .chunk-radio strong').evaluate_all(r"""items => {
          const luminance = color => {
            const rgb = color.match(/[\d.]+/g).slice(0,3).map(Number).map(v => {
              v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
            });
            return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
          };
          return items.map(item => {
            const ink = luminance(getComputedStyle(item).color);
            const paper = luminance(getComputedStyle(item.closest('.triplet-card')).backgroundColor);
            return (Math.max(ink,paper)+.05)/(Math.min(ink,paper)+.05);
          });
        }""")
        assert len(ratios) == 2 and min(ratios) >= 4.5
    paragraph = page.locator('input[name=chunk_mode][value=paragraph]')
    assert paragraph.is_visible()
    paragraph.focus()
    page.keyboard.press('Space')
    assert paragraph.is_checked()
    page.evaluate("renderProgress({active:true,status:'running',total:2,done:0})")
    assert paragraph.is_disabled()


def test_monochrome_studio_has_three_work_areas_and_reachable_advanced_controls(page):
    page.set_viewport_size({'width':1680,'height':1050})
    page.evaluate('''async () => {''' + CHAPTERS + '''
      updateBook({title:'Truyện kiểm thử',filename:'sample.txt',encoding:'UTF-8'});
      renderToc();
    }''')
    boxes = page.evaluate("""['.toc-panel','.config-panel','.progress-panel'].map(s=>{
      const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y};
    })""")
    assert all(abs(box['y']-boxes[0]['y']) < 2 for box in boxes)
    assert boxes[0]['x'] < boxes[1]['x'] < boxes[2]['x']
    assert page.locator('#engine').is_visible()
    assert page.locator('#glossary').is_visible()
    assert page.locator('#opt-audio').is_visible()
    assert page.locator('#translation-advanced').count() == 0
    assert page.locator('#audio-controls').count() == 0
    navigate(page, 'nav-translation')
    assert page.locator('#batch').is_visible()
    assert page.locator('#pane-tab-translation #glossary').count() == 0
    navigate(page, 'nav-audio')
    for target in ('opt-audio-pipeline','audio-workers','audio-queue-size','btn-auto-group-audio'):
        assert page.locator('#'+target).is_visible()
    navigate(page, 'tab-sidebar')
    page.locator('#book-title-panel > summary').click()
    assert page.locator('#output-text-path').is_visible()
    assert page.locator('#encoding').is_visible()


def test_activity_log_uses_actual_messages_and_is_bounded(page):
    page.evaluate("recordActivity('Đang tải model');recordActivity('Đang tải model')")
    assert page.locator('#activity-log li').count() == 1
    assert page.locator('#activity-log li').inner_text().endswith('Đang tải model')
    page.evaluate("for(let i=0;i<110;i++)recordActivity('Cập nhật '+i)")
    assert page.locator('#activity-log li').count() == 100
    assert page.locator('#activity-log li').last.inner_text().endswith('Cập nhật 109')


@pytest.mark.parametrize('width', [1680, 768, 390])
def test_source_card_keeps_proportions_while_loading(page, width):
    page.on('dialog', lambda dialog: dialog.accept())
    page.set_viewport_size({'width': width, 'height': 1000})
    page.evaluate('updateBook(null)')
    selectors = ['#project-source', '.book-cover-wrap', '.source-main-col',
                 '.source-side-col', '#dropzone']
    before = {selector: page.locator(selector).bounding_box() for selector in selectors}
    held_uploads = []
    page.route('**/api/upload', lambda route: held_uploads.append(route))
    page.locator('#file').set_input_files({
        'name': 'stable-layout.txt', 'mimeType': 'text/plain',
        'buffer': '第一章 开始\n你好。'.encode(),
    })
    page.wait_for_function('busy === true')

    def assert_proportions():
        for selector, original in before.items():
            current = page.locator(selector).bounding_box()
            assert abs(current['width'] - original['width']) <= 1, selector
        card = page.locator('#project-source')
        assert card.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
        assert abs(card.bounding_box()['x'] - before['#project-source']['x']) <= 1

    assert_proportions()
    assert len(held_uploads) == 1
    held_uploads[0].continue_()
    page.wait_for_function("busy === false && document.querySelector('#filename').textContent === 'stable-layout.txt'")
    navigate(page, 'tab-sidebar')
    assert_proportions()


def test_reader_audio_transport_and_view_modes(page):
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 8000 * 3)
    def serve_audio(route):
        data = audio.getvalue()
        start = int(route.request.headers.get('range', 'bytes=0-').split('=')[1].split('-')[0])
        route.fulfill(status=206, content_type='audio/wav', body=data[start:], headers={
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{len(data)-1}/{len(data)}',
        })
    page.route('**/api/chapters/*/audio', serve_audio)
    page.evaluate('''async () => {''' + CHAPTERS + '''
      chapters[0].audio_status = 'done';
      api = async path => chapters.find(c => c.id === Number(path.split('/').pop()));
      await selectChapter(1);
    }''')
    navigate(page, 'tab-reader')
    page.wait_for_function("document.querySelector('#audio-player').duration === 3")
    assert page.locator('#reader-audio-controls').is_visible()
    assert page.locator('#reader-audio-time').inner_text() == '0:00 / 0:03'
    page.locator('#reader-audio-play').click()
    page.wait_for_function("document.querySelector('#audio-player').paused === false")
    page.locator('#reader-audio-play').click()
    assert page.locator('#audio-player').evaluate('(e) => e.paused')
    page.locator('#reader-audio-volume').fill('0.4')
    assert page.locator('#audio-player').evaluate('(e) => e.volume') == 0.4
    page.locator('#reader-audio-speed').select_option('1.5')
    assert page.locator('#audio-player').evaluate('(e) => e.playbackRate') == 1.5
    page.locator('#reader-audio-seek').fill('50')
    assert abs(page.locator('#audio-player').evaluate('(e) => e.currentTime') - 1.5) < .1
    page.locator('.view-btn[data-mode=target]').click()
    assert page.locator('.source-column').is_hidden()
    assert page.locator('.target-column').is_visible()
    page.locator('.view-btn[data-mode=parallel]').click()
    assert page.locator('.source-column').is_visible()
    page.evaluate('selectChapter(2)')
    assert page.locator('#reader-audio-controls').is_hidden()
    assert page.locator('#audio-player').get_attribute('src') is None


def test_translation_settings_restore_and_save_without_removed_sections(page):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.evaluate("updateBook({title:'Truyện kiểm thử',filename:'sample.txt',encoding:'UTF-8'})")
    page.locator('#glossary').fill('姜尘 -> Khương Trần')
    model = page.locator('#engine').input_value()
    navigate(page, 'nav-translation')
    assert page.locator('#nav-translation .nav-label').inner_text() == 'Dịch thuật'
    assert page.locator('#engine').count() == 1
    for selector in ('.translation-tabs', '.glossary-box', '.translation-credits'):
        assert page.locator('#pane-tab-translation ' + selector).count() == 0
    page.locator('#beam-size').fill('4')
    page.locator('input[name=chunk_mode][value=paragraph]').check()
    page.locator('#opt-honorific').uncheck()
    page.locator('#batch').fill('64')
    page.locator('#btn-reset-translation').click()
    assert page.locator('#beam-size').input_value() == '2'
    assert page.locator('input[name=chunk_mode][value=sentence]').is_checked()
    assert page.locator('#opt-honorific').is_checked()
    assert page.locator('#glossary').input_value() == '姜尘 -> Khương Trần'
    assert page.locator('#engine').input_value() == model
    page.locator('#btn-save-settings').click()
    page.wait_for_function("document.querySelector('#notice-text').textContent === 'Đã lưu cài đặt.'")
    saved = page.request.get(page.url.rstrip('/') + '/api/checkpoints/draft').json()['config']
    assert saved['glossary'] == '姜尘 -> Khương Trần'
    assert saved['beam_size'] == 2
    assert not errors


@pytest.fixture
def storage_browser_page(page):
    entries = {
        '': [{'name': 'audio', 'path': 'audio', 'directory': True, 'size': None, 'updated_at': None}] +
            [{'name': f'book-{i:02}.txt', 'path': f'book-{i:02}.txt', 'directory': False,
              'size': 1024, 'updated_at': '2026-10-26T12:00:00+00:00'} for i in range(24)],
        'audio': [{'name': 'chapter.mp3', 'path': 'audio/chapter.mp3', 'directory': False,
                   'size': 4096, 'updated_at': None}],
    }
    operations = []
    current_path = ''
    page.route('**/api/storage/status', lambda route: route.fulfill(json={
        'has_key': True, 'repo_id': 'uri410/novelreader-storage', 'default_destination': 'huggingface'}))
    def list_files(route):
        nonlocal current_path
        current_path = parse_qs(urlsplit(route.request.url).query).get('path', [''])[0]
        rows = entries.get(current_path, [])
        route.fulfill(json={'path': current_path, 'entries': rows, 'truncated': False,
                            'file_bytes': sum(row['size'] or 0 for row in rows)})
    page.route('**/api/storage/files?*', list_files)
    page.route('**/api/storage/test', lambda route: route.fulfill(json={
        'ok': True, 'message': 'Đã kết nối kho.', 'username': 'reader', 'private': True}))
    def create_folder(route):
        payload = route.request.post_data_json
        operations.append(('folder', payload))
        path = (payload['path'] + '/' if payload['path'] else '') + payload['name']
        entries.setdefault(payload['path'], []).append({'name': payload['name'], 'path': path,
            'directory': True, 'size': None, 'updated_at': None})
        entries[path] = []
        route.fulfill(json={'ok': True, 'path': path})
    page.route('**/api/storage/folders', create_folder)
    def upload(route):
        operations.append(('upload', route.request.post_data_buffer))
        path = (current_path + '/' if current_path else '') + 'upload.txt'
        entries[current_path].append({'name': 'upload.txt', 'path': path, 'directory': False,
                                      'size': 4, 'updated_at': None})
        route.fulfill(json={'ok': True, 'path': path})
    page.route('**/api/storage/upload', upload)
    page.route('**/api/storage/download?*', lambda route: route.fulfill(body=b'audio',
        headers={'Content-Disposition': 'attachment; filename="chapter.mp3"'}, content_type='audio/mpeg'))
    navigate(page, 'nav-storage')
    page.wait_for_function('storageState.loaded === true')
    return page, operations


def test_storage_browser_navigation_upload_folder_and_download(storage_browser_page):
    page, operations = storage_browser_page
    assert page.locator('#pane-tab-cloud .fi').evaluate_all("items => items.every(e => !['none', 'normal', '\"\"'].includes(getComputedStyle(e, '::before').content))")
    assert page.locator('#storage-file-rows tr').count() == 20
    page.locator('#storage-page-next').click()
    assert page.locator('#storage-file-rows tr').count() == 5
    page.locator('#storage-search').fill('book-23')
    assert page.locator('#storage-file-rows tr').count() == 1
    page.locator('#storage-search').fill('')
    page.locator('#storage-file-rows').get_by_role('button', name='audio', exact=True).click()
    page.wait_for_function("storageState.path === 'audio' && storageState.loaded")
    assert page.locator('#storage-file-rows tr').count() == 1
    assert page.locator('#storage-byte-total').inner_text() == '4 KB'
    page.locator('#storage-file-rows input[type=checkbox]').check()
    with page.expect_download() as download:
        page.locator('#storage-quick-download').click()
    assert download.value.suggested_filename == 'chapter.mp3'
    page.locator('#storage-view-grid').click()
    assert page.locator('#storage-file-grid .storage-file-tile').count() == 1
    assert page.locator('#storage-list-scroll').is_hidden()
    page.locator('#storage-create-folder').click()
    page.locator('#storage-folder-name').fill('new')
    page.locator('#storage-folder-submit').click()
    page.wait_for_function("storageState.entries.some(e => e.path === 'audio/new')")
    assert operations[0] == ('folder', {'path': 'audio', 'name': 'new'})
    page.locator('#storage-file-input').set_input_files({
        'name': 'upload.txt', 'mimeType': 'text/plain', 'buffer': b'data'})
    page.wait_for_function("storageState.entries.some(e => e.path === 'audio/upload.txt')")
    assert operations[-1][0] == 'upload'
    assert b'filename="upload.txt"' in operations[-1][1]
    page.locator('#btn-test-huggingface').click()
    page.wait_for_function("document.querySelector('#storage-account').textContent === 'reader'")
    assert page.locator('#storage-privacy').inner_text() == 'Riêng tư'
    page.route('**/api/storage/files?*', lambda route: route.fulfill(status=502,
        json={'detail': 'Không truy cập được kho.'}))
    page.locator('#storage-refresh').click()
    page.wait_for_function('storageState.loaded === false && storageState.loading === false')
    assert page.locator('#storage-feedback').inner_text() == 'Không truy cập được kho.'
    assert page.locator('#storage-upload').is_disabled()
