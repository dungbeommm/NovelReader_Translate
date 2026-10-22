"""Drive API for Kaggle: Desktop OAuth + PKCE, no Colab mount/OOB flow.
Credentials live outside notebook outputs and are never returned through status.
"""
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SCOPES = ['https://www.googleapis.com/auth/drive.file']
REDIRECT = 'http://127.0.0.1:8765/'
_lock = threading.RLock()


def private_dir():
    path = Path(os.getenv('NOVEL_DRIVE_CREDENTIAL_DIR', '/tmp/novelreader-drive'))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _write(name, value):
    path = private_dir()/name
    temp = path.with_name(name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read(name):
    path = private_dir()/name
    return json.loads(path.read_text()) if path.is_file() else None


def status():
    with _lock:
        token = _read('token.json') or {}
        return {'connected': bool(token.get('token') or token.get('refresh_token')),
                'method': 'desktop_pkce', 'scope': SCOPES[0]}


def _client(raw):
    if len(raw.encode('utf-8')) > 32768:
        raise ValueError('File OAuth JSON quá lớn (tối đa 32 KB).')
    try:
        data = json.loads(raw)['installed']
        client_id = data['client_id']
        secret = data['client_secret']
    except (ValueError, KeyError, TypeError):
        raise ValueError('Cần JSON OAuth loại Desktop app tải từ Google Cloud, không phải service account/Web app.')
    if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]+\.apps\.googleusercontent\.com', client_id):
        raise ValueError('Client ID không hợp lệ.')
    if not isinstance(secret, str) or not secret or len(secret)>4096:
        raise ValueError('Thiếu client secret hợp lệ trong JSON.')
    return {'installed': {'client_id': client_id, 'client_secret': secret,
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token', 'redirect_uris': [REDIRECT]}}


def _flow(config, verifier):
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(config, scopes=SCOPES, redirect_uri=REDIRECT,
                                   code_verifier=verifier)


def begin(client_json):
    config = _client(client_json)
    verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    flow = _flow(config, verifier)
    url, _ = flow.authorization_url(access_type='offline', prompt='consent',
                                    state=state, code_challenge_method='S256')
    with _lock:
        _write('pending.json', {'config':config, 'verifier':verifier,
                               'state':state, 'created_at':time.time()})
    return {'auth_url':url, 'redirect_uri':REDIRECT, 'expires_in':600}


def finish(return_url):
    if len(return_url) > 8192:
        raise ValueError('URL trả về quá dài.')
    try:
        url = urlsplit(return_url.strip())
        query = parse_qs(url.query, max_num_fields=30)
        valid = (url.scheme=='http' and url.hostname=='127.0.0.1' and url.port==8765
                 and url.path=='/' and not url.username and not url.password and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Dán toàn bộ URL http://127.0.0.1:8765/?... từ thanh địa chỉ, không chỉ mã code.')
    with _lock:
        pending = _read('pending.json')
        if not pending or time.time()-pending['created_at']>600:
            raise ValueError('Yêu cầu đăng nhập đã hết hạn. Bấm tạo link mới.')
        state = query.get('state', [])
        if len(state)!=1 or not hmac.compare_digest(state[0].encode(),pending['state'].encode()):
            raise ValueError('Phiên xác thực không khớp. Dùng URL của link Google vừa tạo.')
        if 'error' in query:
            (private_dir()/'pending.json').unlink(missing_ok=True)
            raise ValueError('Google chưa cấp quyền. Có thể thử kết nối lại hoặc tải về máy.')
        code = query.get('code', [])
        if len(code)!=1 or not code[0]:
            raise ValueError('URL chưa có authorization code.')
        flow = _flow(pending['config'], pending['verifier'])
        try:
            flow.fetch_token(code=code[0], timeout=60)
            credentials = flow.credentials
            if not credentials.has_scopes(SCOPES):
                raise ValueError('Thiếu quyền Drive cho các tệp do ứng dụng tạo.')
            _write('token.json', json.loads(credentials.to_json()))
        except Exception:
            raise ValueError('Không đổi được quyền Google. Kiểm tra Desktop OAuth client, test user và thử tạo link mới.') from None
        finally:
            (private_dir()/'pending.json').unlink(missing_ok=True)
    return status()


def disconnect():
    with _lock:
        for name in ('token.json','pending.json'):
            (private_dir()/name).unlink(missing_ok=True)
    return {'connected':False}


def _drive():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    import httplib2
    with _lock:
        info = _read('token.json')
        if not info:
            raise ValueError('Chưa kết nối Drive. Bấm Kết nối Drive trong Web.')
        info.setdefault('refresh_token', None)
        credentials = Credentials.from_authorized_user_info(info, scopes=SCOPES)
        if not credentials.valid:
            if not credentials.refresh_token:
                raise ValueError('Quyền Drive đã hết hạn. Hãy kết nối lại.')
            try:
                credentials.refresh(Request())
                _write('token.json', json.loads(credentials.to_json()))
            except Exception:
                raise ValueError('Không làm mới được quyền Drive. Hãy kết nối lại.') from None
    return build('drive','v3', http=AuthorizedHttp(credentials,http=httplib2.Http(timeout=90)),
                 cache_discovery=False)


def _folder(drive, name, parent=None):
    escaped = name.replace('\\','\\\\').replace("'","\\'")
    query = f"mimeType='application/vnd.google-apps.folder' and trashed=false and name='{escaped}'"
    query += f" and '{parent or 'root'}' in parents"
    files = drive.files().list(q=query,spaces='drive',fields='files(id)',pageSize=100).execute(num_retries=3).get('files',[])
    if files:
        return files[0]['id']
    return drive.files().create(body={'name':name,'mimeType':'application/vnd.google-apps.folder',
               'parents':[parent or 'root']},fields='id').execute(num_retries=3)['id']


def upload(file, book_folder, filename, progress=None):
    drive = _drive()
    try:
        with _lock:
            root = _folder(drive,'NovelReader_Exports')
            folder = _folder(drive,book_folder,root)
        result = _upload_file(drive, file, folder, filename, progress)
        return {'drive_path':f'NovelReader_Exports/{book_folder}/{filename}',
                'drive_url':result.get('webViewLink') or 'https://drive.google.com/file/d/'+result['id']+'/view'}
    except Exception:
        raise ValueError('Tải lên Drive thất bại. Kiểm tra Internet, quota Drive, bật Drive API và quyền OAuth; bản gốc vẫn được giữ.') from None
    finally:
        try:
            drive.close()
        except Exception:
            pass


def _upload_file(drive, file, parent, filename, progress=None):
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(file), resumable=True, chunksize=8*1024*1024)
    try:
        request = drive.files().create(body={'name':filename,'parents':[parent]},media_body=media,
                                      fields='id,name,webViewLink')
        result = None
        while result is None:
            chunk, result = request.next_chunk(num_retries=3)
            if chunk is not None and progress:
                progress(round(chunk.progress()*100))
        return result
    finally:
        media.stream().close()


def upload_audio(directory, book_folder, batch_name, progress=None):
    """Upload original audio filenames into a unique Drive folder, without ZIP."""
    directory = Path(directory)
    paths = sorted(p for p in directory.rglob('*') if p.is_file() and not p.is_symlink())
    if not paths:
        raise ValueError('Chưa có file audio nào để xuất')
    drive = _drive()
    try:
        with _lock:
            root = _folder(drive, 'NovelReader_Exports')
            book = _folder(drive, book_folder, root)
            audio = _folder(drive, 'audio', book)
            batch = _folder(drive, batch_name, audio)
        folders = {():batch}
        for index, file in enumerate(paths):
            rel = file.relative_to(directory)
            parent = batch
            for depth, name in enumerate(rel.parts[:-1],1):
                key = rel.parts[:depth]
                if key not in folders:
                    with _lock:
                        folders[key] = _folder(drive, name, parent)
                parent = folders[key]
            def on_chunk(percent):
                if progress:
                    progress(index,len(paths),str(rel),percent)
            _upload_file(drive, file, parent, file.name, on_chunk)
            if progress:
                progress(index+1,len(paths),str(rel),100)
        return {'drive_path':f'NovelReader_Exports/{book_folder}/audio/{batch_name}',
                'drive_url':'https://drive.google.com/drive/folders/'+batch,
                'uploaded_files':len(paths), 'total_files':len(paths)}
    except Exception:
        raise ValueError('Tải audio lên Drive chưa hoàn tất. Kiểm tra Internet, quota và quyền Drive; bản gốc vẫn giữ nguyên.') from None
    finally:
        try:
            drive.close()
        except Exception:
            pass
