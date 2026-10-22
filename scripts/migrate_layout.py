"""Copy an old layout without deleting its files. Preview by default; --apply writes.

Use --flat-output only if root-level old output belongs to the active SQLite book.
"""
import argparse
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage.store import _safe_filename


def fingerprint(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.digest()


def same_content(left, right):
    if left.suffix == right.suffix == '.sqlite3':
        def database_hash(path):
            digest = hashlib.sha256()
            with sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True) as conn:
                for statement in conn.iterdump():
                    digest.update(statement.encode('utf-8'))
            return digest.digest()
        return database_hash(left) == database_hash(right)
    return fingerprint(left) == fingerprint(right)


def build_plan(source, destination, flat_output=False):
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError('Thư mục nguồn và đích phải khác nhau.')
    mappings = [('translator/models', 'models/translation'), ('tts/voice', 'models/voices'),
                ('translator/data', 'data')]
    plan = []
    for old, new in mappings:
        for f in sorted((source / old).rglob('*')):
            if f.is_symlink():
                raise ValueError(f'Không tự di chuyển symlink: {f}')
            if f.is_file() and f.suffix != '.log' and not f.name.endswith(('-wal', '-shm')):
                plan.append((f, destination / new / f.relative_to(source / old)))
    db = source / 'translator/data/novel.sqlite3'
    title = None
    if db.is_file() and db.stat().st_size:
        with sqlite3.connect(f'{db.as_uri()}?mode=ro', uri=True) as conn:
            row = conn.execute('SELECT title FROM book LIMIT 1').fetchone()
            title = _safe_filename(row[0]) if row else None
    for kind in ('output_text', 'output_audio'):
        base = source / kind
        for f in sorted(base.rglob('*')):
            if f.is_symlink():
                raise ValueError(f'Không tự di chuyển symlink: {f}')
            if not f.is_file():
                continue
            rel = f.relative_to(base)
            is_legacy = len(rel.parts) == 1 or rel.parts[0] in ('groups', 'merged')
            if is_legacy:
                if not flat_output or not title:
                    continue
                name = f.name
                if kind == 'output_audio':
                    if name.startswith('chapter_') or name.endswith('.sources.json'):
                        continue
                    is_group = len(rel.parts) > 1 or name.count('_') >= 2
                    rel = Path(title) / ('audio_gop' if is_group else '') / name
                else:
                    if name.endswith('_full.txt'):
                        name = 'toan_bo_truyen.txt'
                    rel = Path(title) / name
            plan.append((f, destination / kind / rel))
    return plan


def migrate(source, destination, apply=False, flat_output=False):
    plan = build_plan(source, destination, flat_output)
    targets = {}
    for old, new in plan:
        if not new.resolve().is_relative_to(destination.resolve()):
            raise ValueError(f'Đích nằm ngoài thư mục cài đặt: {new}')
        if new in targets and not same_content(old, targets[new]):
            raise ValueError(f'Hai nguồn khác nhau trùng đích: {new}')
        targets[new] = old
        if new.exists() and (not new.is_file() or not same_content(old, new)):
            raise ValueError(f'Đích đã có dữ liệu khác; không ghi đè: {new}')
    for new, old in targets.items():
        print(f'{old} -> {new}')
        if apply and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            if old.suffix == '.sqlite3':
                with sqlite3.connect(f'{old.as_uri()}?mode=ro', uri=True) as src:
                    with sqlite3.connect(new) as dst:
                        src.backup(dst)
            else:
                shutil.copy2(old, new)
    print(f'{"Đã sao chép" if apply else "Xem trước"}: {len(targets)} file. Nguồn không bị xóa.')
    return len(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--flat-output', action='store_true', help='Gán output phẳng cũ cho truyện hiện tại; chỉ bật khi chắc chắn không trộn truyện.')
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error('Không tìm thấy thư mục nguồn.')
    migrate(args.source, args.destination, args.apply, args.flat_output)

if __name__ == '__main__':
    main()
