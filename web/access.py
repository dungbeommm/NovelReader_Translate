"""Optional per-Colab-session access secret, exchanged for an HttpOnly cookie."""
import hmac
import os
from fastapi.responses import RedirectResponse, Response

COOKIE = 'novel_session_access'


def has_access(headers, cookies):
    required = os.getenv('NOVEL_WEB_ACCESS_TOKEN', '')
    if not required:
        return True  # local-only deployments keep the existing behavior
    supplied = headers.get('x-novel-access') or cookies.get(COOKIE, '')
    return hmac.compare_digest(str(supplied), required)


def protect_request(request):
    required = os.getenv('NOVEL_WEB_ACCESS_TOKEN', '')
    if not required:
        return None
    token = request.query_params.get('access_token', '')
    if request.url.path == '/' and token and hmac.compare_digest(token, required):
        response = RedirectResponse('/', status_code=303)
        response.set_cookie(COOKIE, required, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', path='/')
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response
    if has_access(request.headers, request.cookies):
        return None
    return Response('Chưa được phép truy cập. Hãy mở link riêng được in trong notebook Colab.',
                    status_code=403, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
