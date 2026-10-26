"""Browser regressions. Optional: pip install playwright; playwright install chromium."""
import os
import socket
import subprocess
import sys
import time
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
    for key in ('NOVEL_WEB_ACCESS_TOKEN', 'ALLOW_TUNNEL', 'ALLOWED_HOSTS', 'COLAB_GPU'):
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
    for tab in page.locator('.settings-nav .modal-tab').all():
        tab.click()
        panel = page.locator('#pane-'+tab.get_attribute('data-tab'))
        assert panel.is_visible()
        assert panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
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
    page.locator('#btn-close-settings').click()
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
    page.locator('#btn-save-settings').click()
    page.wait_for_function("document.querySelector('#notice-text').textContent === 'Đã lưu cài đặt.'")
    assert page.locator('#settings-modal').is_visible()
    assert page.locator('#pane-tab-tts').is_visible()


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
    page.locator('#translation-advanced > summary').click()
    assert page.locator('#batch').is_visible()
    assert page.locator('#btn-translation-settings').is_visible()
    page.locator('#audio-controls > summary').click()
    for target in ('opt-audio-pipeline','audio-workers','audio-queue-size','btn-auto-group-audio'):
        assert page.locator('#'+target).is_visible()
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
