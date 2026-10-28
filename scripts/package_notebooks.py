"""Refresh standalone notebook sources without packaging runtime data or credentials."""
import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('audio', 'core', 'monitoring', 'notebook', 'scripts', 'server', 'storage', 'translation', 'tts', 'web', 'workflows', 'tests')
SOURCE_FILES = ('main.py', 'paths.py', 'requirements.txt', 'requirements-dev.txt',
                'requirements-vieneu.txt', 'README.md', 'LICENSE', 'Dockerfile',
                'compose.yaml', '.env.example', '.dockerignore')
RETIRED = ('gdrive/__init__.py', 'gdrive/api_drive.py', 'gdrive/colab_bridge.py',
           'gdrive/export_service.py', 'gdrive/gdrive_service.py',
           'storage/pixeldrain_service.py', 'web/routes/gdrive.py',
           'web/routes/drive_api.py', 'web/routes/drive_exports.py',
           'web/routes/pixeldrain_routes.py')


def source_archive():
    sources = [ROOT / name for name in SOURCE_FILES]
    for directory in SOURCE_DIRS:
        sources.extend(p for p in (ROOT / directory).rglob('*') if p.is_file()
                       and not p.is_symlink() and not any(part.startswith('.') or part == '__pycache__'
                                                       for part in p.relative_to(ROOT).parts))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(sources)):
            if path.is_file():
                member = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), (2026, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(member, path.read_bytes())
    return out.getvalue()


def update_source(source, payload, checksum):
    source, count = re.subn(r"(_overlay_payload = ')[^']*(')",
                            lambda m: m[1] + payload + m[2], source)
    if count != 1:
        raise ValueError('Expected one bundled source payload.')
    source, count = re.subn(r"(hexdigest\(\) != ')[a-f0-9]{64}(')",
                            lambda m: m[1] + checksum + m[2], source)
    if count != 1:
        raise ValueError('Expected one bundled source checksum.')
    # Older notebook workspaces may still contain retired modules after extraction.
    cleanup = ('for _retired in ' + repr(RETIRED) + ':\n'
               '    (repo_dir / _retired).unlink(missing_ok=True)\n')
    if '    del _overlay_payload' in source:
        cleanup = '\n'.join('    ' + line for line in cleanup.rstrip().splitlines()) + '\n'
    source = re.sub(r'(?m)^([ ]*)# BEGIN_RETIRED_STORAGE_CLEANUP\n.*?^\1# END_RETIRED_STORAGE_CLEANUP\n', '', source, flags=re.S)
    indent = '    ' if '    del _overlay_payload' in source else ''
    cleanup = indent + '# BEGIN_RETIRED_STORAGE_CLEANUP\n' + cleanup + indent + '# END_RETIRED_STORAGE_CLEANUP\n'
    return source.replace(indent + 'del _overlay_payload', cleanup + indent + 'del _overlay_payload')


def main():
    archive = source_archive()
    payload = base64.b64encode(archive).decode('ascii')
    checksum = hashlib.sha256(archive).hexdigest()
    molab = ROOT / 'NovelReader_Molab.py'
    molab_source = molab.read_text('utf-8')
    if '_overlay_payload = ' in molab_source:
        molab.write_text(update_source(molab_source, payload, checksum), encoding='utf-8')
    colab = ROOT / 'NovelReader_Colab.ipynb'
    notebook = json.loads(colab.read_text('utf-8'))
    for cell in notebook['cells']:
        source = ''.join(cell.get('source', []))
        if '_overlay_payload = ' in source:
            source = update_source(source, payload, checksum)
            # Colab uses an uppercase repository variable.
            source = source.replace('(repo_dir / _retired)', '(REPO_DIR / _retired)')
            cell['source'] = source.splitlines(keepends=True)
    colab.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (ROOT / 'NovelReader_GPU_notebook.zip').write_bytes(archive)
    print(f'Refreshed notebook sources: {len(archive)} bytes, SHA256 {checksum}')


if __name__ == '__main__':
    main()
