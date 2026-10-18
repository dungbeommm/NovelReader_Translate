from urllib.parse import urlsplit
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from web import runtime
from web.access import has_access

router = APIRouter()

@router.websocket('/ws/progress')
async def progress(ws:WebSocket):
    if not has_access(ws.headers, ws.cookies):
        await ws.close(code=1008);return
    origin=ws.headers.get('origin');host=ws.headers.get('host')
    if origin and urlsplit(origin).netloc != host:
        await ws.close(code=1008);return
    await ws.accept();runtime.job.clients.add(ws)
    try:
        await ws.send_json({'type':'snapshot','progress':runtime.job.summary()})
        while True:await ws.receive_text()
    except (WebSocketDisconnect,RuntimeError):pass
    finally:runtime.job.clients.discard(ws)

