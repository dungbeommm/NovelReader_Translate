"""Merge existing chapter audio; never translate or synthesize new audio."""
import json
import logging
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from .audio_service import get_chapter_audio_path
log = logging.getLogger(__name__)

def merge_audio_files(input_files: list[Path], output_file: Path, fmt: str = "mp3", bitrate: str = "96k") -> Path:
    """Gộp danh sách các file audio thành 1 file lớn duy nhất."""
    if not input_files:
        raise ValueError("Danh sách file cần gộp rỗng.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = (fmt or "mp3").lower().strip()
    with tempfile.TemporaryDirectory() as tmp_dir:
        concat_txt = Path(tmp_dir) / "concat_list.txt"
        lines = [f"file '{str(f.resolve()).replace(chr(92), '/')}'" for f in input_files if f.is_file()]
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        temp_out = Path(tmp_dir) / f"merged.{fmt}"
        if fmt == "mp3":
            codec_args = ["-c:a", "libmp3lame", "-b:a", bitrate]
        elif fmt in ("m4b", "m4a", "aac"):
            codec_args = ["-c:a", "aac", "-b:a", bitrate]
        elif fmt in ("opus", "ogg"):
            codec_args = ["-c:a", "libopus", "-b:a", bitrate]
        elif fmt == "wav":
            codec_args = ["-c:a", "pcm_s16le"]
        else:
            codec_args = ["-c:a", "libmp3lame", "-b:a", bitrate]

        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_txt),
            *codec_args,
            str(temp_out)
        ]
        subprocess.run(cmd, check=True, timeout=1200)
        shutil.move(str(temp_out), str(output_file))

    return output_file


def merge_chapter_range(
    store,
    start_pos: int,
    end_pos: int,
    fmt: str = "mp3",
    bitrate: str = "96k"
) -> dict:
    """Gộp audio các chương từ chương start_pos đến end_pos thành 1 file duy nhất."""
    if start_pos > end_pos:
        start_pos, end_pos = end_pos, start_pos

    chapters = store.list()
    range_chapters = [c for c in chapters if start_pos <= c.get("position", 0) <= end_pos]
    if not range_chapters:
        raise ValueError(f"Không tìm thấy chương nào trong khoảng từ chương {start_pos} đến {end_pos}.")

    range_chapters.sort(key=lambda c: c.get("position", 0))

    audio_files: list[Path] = []
    missing_positions: list[int] = []

    for c in range_chapters:
        p = get_chapter_audio_path(store.audio_dir, c["id"], c.get("position"))
        if p:
            audio_files.append(p)
        else:
            missing_positions.append(c.get("position"))

    if not audio_files:
        raise ValueError(
            f"Không tìm thấy file audio nào trong khoảng từ chương {start_pos} đến {end_pos}. "
            "Vui lòng tạo audio cho các chương này trước khi gộp."
        )

    merged_dir = store.audio_dir / "audio_gop"
    merged_dir.mkdir(parents=True, exist_ok=True)

    out_filename = f"chuong_{start_pos:04d}_{end_pos:04d}.{fmt}"
    target_path = merged_dir / out_filename

    merge_audio_files(audio_files, target_path, fmt=fmt, bitrate=bitrate)

    size_mb = round(target_path.stat().st_size / (1024 * 1024), 2)
    log.info("Đã gộp %d/%d file audio dải [%d - %d]: %s (%s MB)",
             len(audio_files), len(range_chapters), start_pos, end_pos, out_filename, size_mb)

    return {
        "ok": True,
        "filename": out_filename,
        "start_pos": start_pos,
        "end_pos": end_pos,
        "total_chapters": len(range_chapters),
        "merged_audio_count": len(audio_files),
        "missing_count": len(missing_positions),
        "missing_positions": missing_positions[:10],
        "size_mb": size_mb,
        "url": f"/api/audio/merged/{out_filename}",
        "download_url": f"/api/audio/merged/{out_filename}"
    }


def merge_selected_chapters(
    store,
    chapter_ids: list[int],
    fmt: str = "mp3",
    bitrate: str = "96k"
) -> dict:
    """Gộp audio của các chương được chọn thành 1 file duy nhất."""
    if not chapter_ids:
        raise ValueError("Chưa chọn chương nào để gộp audio.")

    id_set = set(chapter_ids)
    chapters = [c for c in store.list() if c.get("id") in id_set]
    if not chapters:
        raise ValueError("Không tìm thấy các chương đã chọn.")

    chapters.sort(key=lambda c: c.get("position", 0))

    audio_files: list[Path] = []
    missing_positions: list[int] = []

    for c in chapters:
        p = get_chapter_audio_path(store.audio_dir, c["id"], c.get("position"))
        if p:
            audio_files.append(p)
        else:
            missing_positions.append(c.get("position"))

    if not audio_files:
        raise ValueError("Không tìm thấy file audio nào trong các chương đã chọn.")

    start_num = chapters[0]["position"]
    end_num = chapters[-1]["position"]

    merged_dir = store.audio_dir / "audio_gop"
    merged_dir.mkdir(parents=True, exist_ok=True)

    out_filename = f"chuong_{start_num:04d}_{end_num:04d}.{fmt}"
    target_path = merged_dir / out_filename

    merge_audio_files(audio_files, target_path, fmt=fmt, bitrate=bitrate)

    size_mb = round(target_path.stat().st_size / (1024 * 1024), 2)
    log.info("Đã gộp %d/%d file audio các chương đã chọn [%d - %d]: %s (%s MB)",
             len(audio_files), len(chapters), start_num, end_num, out_filename, size_mb)

    return {
        "ok": True,
        "filename": out_filename,
        "start_pos": start_num,
        "end_pos": end_num,
        "total_chapters": len(chapters),
        "merged_audio_count": len(audio_files),
        "missing_count": len(missing_positions),
        "missing_positions": missing_positions[:10],
        "size_mb": size_mb,
        "url": f"/api/audio/merged/{out_filename}",
        "download_url": f"/api/audio/merged/{out_filename}"
    }


_group_merge_lock = threading.Lock()


def group_and_merge_chapters(store, group_size: int = 50, fmt: str = "mp3",
                             chapter_ids=None, bitrate: str = "96k") -> list[dict]:
    """Merge fixed ranges (1..N, N+1..2N) or remainder/scoped chapters < N using existing audio only.

    - If chapter_ids is provided and len(chapter_ids) <= group_size:
      Merges the selected chapters as one group when all have audio (Case 2).
    - If chapter_ids is provided and len(chapter_ids) > group_size:
      Merges full groups of N and the remainder group < N within scope (Case 1).
    - If chapter_ids is None (manual merge):
      Merges full groups of N, and any contiguous remainder < N at the tail of audio (Case 1).
    """
    if isinstance(group_size, bool) or not isinstance(group_size, int) or not 2 <= group_size <= 500:
        raise ValueError('Số chương mỗi nhóm phải từ 2 đến 500.')
    if fmt not in ('mp3', 'm4b', 'm4a', 'opus', 'wav'):
        raise ValueError('Định dạng audio không hợp lệ.')
    if bitrate not in ('64k', '96k', '128k', '192k'):
        raise ValueError('Bitrate không hợp lệ.')
    with _group_merge_lock:
        all_chapters = store.list()
        groups_dir = store.audio_dir / 'audio_gop'
        results = []

        def _merge_group(rows, group_num, start_n, end_n):
            audio_files = [get_chapter_audio_path(store.audio_dir, c['id'], c['position']) for c in rows]
            if any(p is None for p in audio_files):
                return None
            groups_dir.mkdir(parents=True, exist_ok=True)
            out_filename = f'chuong_{start_n:04d}_{end_n:04d}.{fmt}'
            target_path = groups_dir / out_filename
            manifest_path = target_path.with_suffix(target_path.suffix + '.sources.json')
            fingerprint = {
                'format': fmt,
                'bitrate': bitrate,
                'sources': [[str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns] for p in audio_files]
            }
            try:
                previous = json.loads(manifest_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                previous = None
            if not target_path.is_file() or target_path.stat().st_size == 0 or previous != fingerprint:
                merge_audio_files(audio_files, target_path, fmt=fmt, bitrate=bitrate)
                manifest_path.write_text(json.dumps(fingerprint, ensure_ascii=False), encoding='utf-8')
            return {
                'group': group_num,
                'title': f'Tập {group_num:02d}: Chương {start_n} - {end_n}',
                'filename': out_filename,
                'start_pos': start_n,
                'end_pos': end_n,
                'file_path': str(target_path),
                'size_mb': round(target_path.stat().st_size / (1024 * 1024), 2),
                'chapter_count': len(audio_files),
                'url': f'/api/audio/groups/{out_filename}',
                'download_url': f'/api/audio/groups/{out_filename}'
            }

        # Case 2: Scoped selection with count <= group_size
        if chapter_ids is not None:
            allowed = set(chapter_ids)
            scoped_chapters = [c for c in all_chapters if c['id'] in allowed and c.get('position', 0) > 0]
            scoped_chapters.sort(key=lambda c: c['position'])
            if not scoped_chapters:
                return []

            if len(scoped_chapters) <= group_size:
                start_num = scoped_chapters[0]['position']
                end_num = scoped_chapters[-1]['position']
                if [c['position'] for c in scoped_chapters] == list(range(start_num, end_num + 1)):
                    group_num = (start_num - 1) // group_size + 1
                    res = _merge_group(scoped_chapters, group_num, start_num, end_num)
                    if res:
                        results.append(res)
                return results

            # Scoped selection > group_size: split into groups of group_size, plus remainder
            buckets = {}
            for c in scoped_chapters:
                pos = c['position']
                buckets.setdefault((pos - 1) // group_size, []).append(c)

            max_bucket_idx = max(buckets.keys())
            for index, rows in sorted(buckets.items()):
                start_num = index * group_size + 1
                nominal_end = start_num + group_size - 1
                rows.sort(key=lambda c: c['position'])
                if len(rows) == group_size:
                    if [c['position'] for c in rows] == list(range(start_num, nominal_end + 1)):
                        res = _merge_group(rows, index + 1, start_num, nominal_end)
                        if res:
                            results.append(res)
                elif index == max_bucket_idx and len(rows) > 0:
                    end_num = rows[-1]['position']
                    if [c['position'] for c in rows] == list(range(start_num, end_num + 1)):
                        res = _merge_group(rows, index + 1, start_num, end_num)
                        if res:
                            results.append(res)
            return results

        # chapter_ids is None: Scan all existing audio in the book (Manual merge)
        buckets = {}
        for chapter in all_chapters:
            position = chapter.get('position', 0)
            if position > 0:
                buckets.setdefault((position - 1) // group_size, []).append(chapter)

        if not buckets:
            return []

        for index, rows in sorted(buckets.items()):
            start_num = index * group_size + 1
            nominal_end = start_num + group_size - 1
            rows.sort(key=lambda c: c['position'])

            if len(rows) == group_size:
                if [c['position'] for c in rows] == list(range(start_num, nominal_end + 1)):
                    res = _merge_group(rows, index + 1, start_num, nominal_end)
                    if res:
                        results.append(res)
            elif len(rows) > 0:
                actual_start = rows[0]['position']
                actual_end = rows[-1]['position']
                if [c['position'] for c in rows] == list(range(actual_start, actual_end + 1)):
                    res = _merge_group(rows, index + 1, actual_start, actual_end)
                    if res:
                        results.append(res)

        return results
