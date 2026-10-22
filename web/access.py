"""Optional per-Colab-session access secret, exchanged for an HttpOnly cookie."""
import hmac
import os
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from urllib.parse import parse_qs, urlsplit

COOKIE = 'novel_session_access'


def has_access(headers, cookies):
    required = os.getenv('NOVEL_WEB_ACCESS_TOKEN', '')
    if not required:
        return True
    supplied = headers.get('x-novel-access') or cookies.get(COOKIE, '')
    return _matches(str(supplied).strip(), required)


def protect_request(request):
    required = os.getenv('NOVEL_WEB_ACCESS_TOKEN', '')
    if not required:
        return None
    token = request.query_params.get('access_token', '').strip()
    if request.url.path == '/' and token and _matches(token, required):
        return _grant(request, required)
    if has_access(request.headers, request.cookies):
        return None
    if request.url.path == '/' and request.method == 'GET':
        return login_page(bool(token), request.query_params.get('cookie_check') == '1')
    return Response(
        'Chưa được phép truy cập.\n\n'
        'Quay lại tab Colab, mở ô Web đang chạy và bấm “Mở NovelReader”.\n'
        'Không dùng riêng địa chỉ trycloudflare.com hoặc link của phiên cũ.\n'
        'Sau khi khởi động lại Web, hãy dùng link mới được in trong notebook.\n'
        'Nếu mở trong trình duyệt khác hoặc chế độ ẩn danh, cần mở lại link riêng ở đó.\n'
        'Không chia sẻ link riêng vì link cấp quyền truy cập ứng dụng.\n',
        status_code=403, media_type='text/plain; charset=utf-8',
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


def _matches(supplied, required):
    return hmac.compare_digest(str(supplied).strip().encode('utf-8'), required.strip().encode('utf-8'))


def _grant(request, required):
    response = RedirectResponse('/?cookie_check=1', status_code=303)
    response.set_cookie(COOKIE, required, httponly=True, samesite='lax',
                        secure=request.url.scheme == 'https', path='/')
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


def login_page(wrong=False, cookie_blocked=False):
    message = ('Trình duyệt chưa lưu cookie. Hãy mở Web trong tab riêng và cho phép cookie của trang này.'
               if cookie_blocked else
               'Mã không đúng hoặc đã hết hạn. Dùng mã của ô Web đang chạy trong Colab.'
               if wrong else
               'Nhập mã truy cập được in dưới nút Mở NovelReader trong Colab.')
    html = '\n'.join([
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>Đăng nhập NovelReader</title>',
        '<style>body{font:16px system-ui;background:#101812;color:#e5f0e8;max-width:480px;margin:12vh auto;padding:24px}input,button{box-sizing:border-box;width:100%;padding:14px;margin:10px 0;border-radius:8px;font:inherit}button{background:#40d47e;border:0;cursor:pointer}p{line-height:1.6}</style>',
        '</head><body><h1>NovelReader</h1><p>' + message + '</p>',
        '<form method="post" action="/auth/login"><label for="token">Mã truy cập</label>',
        '<input id="token" name="token" type="password" maxlength="256" required autocomplete="off" autofocus>',
        '<button type="submit">Vào ứng dụng</button></form>',
        '<p>Mở trong tab trình duyệt riêng, không nhúng trong Colab. Không chia sẻ mã hoặc link riêng.</p>',
        '</body></html>'])
    return HTMLResponse(html, status_code=200, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'same-origin',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        'X-Content-Type-Options': 'nosniff'})


async def handle_login(request):
    if request.method != 'POST':
        return Response(status_code=405, headers={'Allow': 'POST'})
    origin = request.headers.get('origin')
    if origin:
        origin_host = urlsplit(origin).netloc.split(':')[0].lower()
        req_host = (request.headers.get('x-forwarded-host') or request.headers.get('host', '')).split(':')[0].lower()
        if origin_host and req_host and origin_host != req_host:
            return Response('Origin không hợp lệ.', status_code=403, media_type='text/plain')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            return Response(status_code=413)
    try:
        token = parse_qs(body.decode('utf-8'), max_num_fields=4).get('token', [''])[0].strip()
    except (UnicodeDecodeError, ValueError):
        return login_page(wrong=True)
    required = os.getenv('NOVEL_WEB_ACCESS_TOKEN', '')
    if required and _matches(token, required):
        return _grant(request, required)
    return login_page(wrong=True)
