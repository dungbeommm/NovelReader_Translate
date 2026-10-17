"""Private Telegram frontend. Fail closed unless ALLOWED_USER_IDS is configured."""
import asyncio
import contextlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from state import State

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = Path(__file__).resolve().parent
DATA = Path(os.getenv('BOT_DATA', str(ROOT / 'data/telegram'))).resolve()
state = State(DATA)
ALLOWED = {int(x.strip()) for x in os.getenv('ALLOWED_USER_IDS','').split(',') if x.strip()}
LIMIT = 19 * 1024**2
process = None
log = logging.getLogger(__name__)

HELP = '''📚 Dịch truyện Trung → Việt và audio Ngọc Huyền
/full — dịch + audio (mặc định)
/dich — chỉ dịch, nhận TXT + EPUB
/audio — chỉ đọc truyện tiếng Việt
Sau khi chọn, gửi file TXT hoặc EPUB (tối đa 19 MB).
/status — xem tiến độ và mã tác vụ
/cancel <mã> — hủy tác vụ
/retry <mã> — tiếp tục tác vụ lỗi/đã hủy
/xoa <mã> — xóa dữ liệu tác vụ đã dừng
Chỉ dùng file bạn có quyền xử lý. Không đăng công khai.
Nội dung được gửi qua Telegram và lưu trên máy chủ cho đến khi /xoa.'''

async def permitted(u):
    if not u.effective_user or not u.effective_chat or u.effective_chat.type != 'private':
        return False
    if u.effective_user.id not in ALLOWED:
        await u.effective_message.reply_text('Bot riêng tư. Tài khoản chưa được cấp quyền.')
        return False
    return True

async def start(u, c):
    if await permitted(u):
        await u.message.reply_text(HELP)

async def mode(u, c):
    if not await permitted(u): return
    cmd = u.message.text.split()[0].split('@')[0]
    value = {'/full':'full', '/dich':'translate', '/audio':'audio'}[cmd]
    state.mode(u.effective_user.id, value)
    await u.message.reply_text('Đã chọn: ' + {'full':'dịch + audio','translate':'chỉ dịch','audio':'chỉ audio tiếng Việt'}[value] + '. Gửi TXT/EPUB để bắt đầu.')

async def document(u, c):
    if not await permitted(u): return
    doc = u.message.document
    suffix = Path(doc.file_name or '').suffix.lower()
    if suffix not in ('.txt','.epub'):
        await u.message.reply_text('Bản này chỉ nhận TXT hoặc EPUB.'); return
    if doc.file_size is None or doc.file_size > LIMIT:
        await u.message.reply_text('File phải nhỏ hơn 19 MB. Hãy chia tập.'); return
    if shutil.disk_usage(DATA).free < 3*1024**3:
        await u.message.reply_text('Máy chủ còn dưới 3 GB trống; cần dọn dữ liệu.'); return
    try:
        file = await doc.get_file()
        data = bytes(await file.download_as_bytearray())
        if len(data) > LIMIT: raise ValueError('File quá lớn.')
        jid = state.create(u.effective_user.id, u.effective_chat.id, state.mode(u.effective_user.id), suffix, data)
        await u.message.reply_text(f'Đã xếp hàng: {jid}\nXem bằng /status. Hủy bằng /cancel {jid}')
    except Exception:
        log.exception('Receive failed')
        await u.message.reply_text('Chưa nhận được truyện: có thể hàng đợi đầy (tối đa 2 truyện/người, 10 toàn bot) hoặc Telegram lỗi. Thử lại sau.')

async def status(u,c):
    if not await permitted(u): return
    lines=[]
    for row in state.list(u.effective_user.id):
        detail=''
        path=DATA/row['id']/'progress.json'
        if path.exists():
            with contextlib.suppress(Exception):
                p=json.loads(path.read_text()); detail=f" | {p.get('stage','')} {p.get('done',0)}/{p.get('total',0)}"
        lines.append(f"{row['id']}: {row['status']}{detail}")
    await u.message.reply_text('\n'.join(lines) or 'Chưa có tác vụ.')

async def action(u,c):
    if not await permitted(u): return
    row=state.get(c.args[0],u.effective_user.id) if len(c.args)==1 else None
    if not row:
        await u.message.reply_text('Cần mã tác vụ của bạn. Xem /status.'); return
    jid=row['id']; cmd=u.message.text.split()[0].split('@')[0]
    if cmd=='/cancel':
        if row['status'] not in ('queued','running','delivering'):
            await u.message.reply_text('Tác vụ đã dừng.'); return
        state.set(jid,'cancelled')
        await u.message.reply_text('Đã yêu cầu hủy. Checkpoint được giữ; audio đang tạo trên dịch vụ nội bộ có thể cần thêm thời gian để dừng.')
    elif cmd=='/retry':
        if c.application.bot_data.get('active')==jid:
            await u.message.reply_text('Tác vụ đang dừng; đợi vài giây rồi /retry lại.'); return
        if row['status'] not in ('failed','cancelled'):
            await u.message.reply_text('Chỉ tiếp tục tác vụ lỗi/đã hủy.'); return
        # The worker is serial; requeued work waits for the previous process to stop.
        try:
            state.requeue(jid,u.effective_user.id)
        except ValueError as exc:
            await u.message.reply_text(str(exc)); return
        await u.message.reply_text('Đã xếp hàng tiếp tục từ checkpoint.')
    else:
        if row['status'] in ('queued','running','delivering') or c.application.bot_data.get('active')==jid:
            await u.message.reply_text('Hãy /cancel rồi đợi tác vụ dừng trước khi xóa.'); return
        shutil.rmtree(DATA/jid, ignore_errors=True)
        state.set(jid,'deleted')
        await u.message.reply_text('Đã xóa file và checkpoint trên máy chủ. Tin nhắn/file đã gửi trên Telegram không bị xóa.')

async def deliver(app,row):
    folder=DATA/row['id']; marker=folder/'sent.json'
    sent=set(json.loads(marker.read_text())) if marker.exists() else set()
    for path in sorted((folder/'output').iterdir()):
        if state.get(row['id'])['status']=='cancelled': return
        if path.name in sent or not path.is_file():continue
        if path.stat().st_size>48*1024**2:
            raise ValueError('File xuất quá 48 MB; lấy trên máy chủ hoặc chia tập.')
        with path.open('rb') as f:
            if path.suffix=='.mp3':
                await app.bot.send_audio(row['chat'], audio=f, filename=path.name, title=path.stem, read_timeout=120, write_timeout=120)
            else:
                await app.bot.send_document(row['chat'], document=f, filename=path.name, read_timeout=120, write_timeout=120)
        sent.add(path.name)
        temp=marker.with_suffix('.tmp');temp.write_text(json.dumps(sorted(sent)));temp.replace(marker)
        await asyncio.sleep(1.1)
    if state.get(row['id'])['status']!='cancelled':
        state.set(row['id'],'done')
        with contextlib.suppress(Exception):
            await app.bot.send_message(row['chat'], f"Hoàn tất {row['id']}. Dọn dữ liệu bằng /xoa {row['id']}.")

async def worker(app):
    global process
    state.recover()
    while True:
        row=state.next()
        if not row:
            await asyncio.sleep(2); continue
        jid=row['id'];folder=DATA/jid
        app.bot_data['active']=jid
        try:
            with contextlib.suppress(Exception):
                await app.bot.send_message(row['chat'],f'Bắt đầu {jid}. Xem tiến độ bằng /status.')
            with (folder/'runner.log').open('ab') as logfile:
                process=await asyncio.create_subprocess_exec(sys.executable,str(BOT_DIR/'runner.py'),str(folder),stdout=logfile,stderr=logfile)
                began=asyncio.get_running_loop().time()
                while process.returncode is None:
                    current=state.get(jid)['status']
                    if current not in ('running',) or asyncio.get_running_loop().time()-began>86400:
                        if current=='running':state.set(jid,'failed','Timeout 24 giờ; có thể /retry.')
                        process.terminate()
                        try: await asyncio.wait_for(process.wait(),10)
                        except asyncio.TimeoutError:
                            process.kill();await process.wait()
                        break
                    try: await asyncio.wait_for(process.wait(),2)
                    except asyncio.TimeoutError:pass
                if state.get(jid)['status']!='running': continue
                if process.returncode: raise RuntimeError('Xử lý lỗi; xem runner.log trên máy chủ.')
            state.set(jid,'delivering')
            await deliver(app,row)
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.terminate()
                with contextlib.suppress(Exception):await asyncio.wait_for(process.wait(),10)
                if process.returncode is None:process.kill();await process.wait()
            raise
        except Exception:
            log.exception('Job %s failed',jid)
            if state.get(jid)['status'] not in ('cancelled','queued'):
                state.set(jid,'failed','Xử lý/gửi kết quả lỗi; xem runner.log và docker compose logs bot.')
                with contextlib.suppress(Exception):
                    await app.bot.send_message(row['chat'],f'Tác vụ {jid} lỗi. /retry {jid} để tiếp tục. Chi tiết nằm trong log máy chủ; không gửi token lên chat.')
        finally:
            process=None
            app.bot_data['active']=None

async def init(app):app.bot_data['worker']=asyncio.create_task(worker(app))
async def shutdown(app):
    task=app.bot_data.get('worker')
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):await task

def main():
    if not ALLOWED:raise SystemExit('Phải đặt ALLOWED_USER_IDS; bot từ chối chạy công khai.')
    token=os.environ.get('TELEGRAM_BOT_TOKEN','')
    if not token or token.startswith('YOUR_'):raise SystemExit('Thiếu TELEGRAM_BOT_TOKEN.')
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    app=Application.builder().token(token).post_init(init).post_stop(shutdown).build()
    app.add_handler(CommandHandler(['start','help'],start))
    app.add_handler(CommandHandler(['full','dich','audio'],mode))
    app.add_handler(CommandHandler('status',status))
    app.add_handler(CommandHandler(['cancel','retry','xoa'],action))
    app.add_handler(MessageHandler(filters.Document.ALL,document))
    app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=False)

if __name__=='__main__':main()
