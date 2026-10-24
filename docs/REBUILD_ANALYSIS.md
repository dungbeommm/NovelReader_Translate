# NovelReader MoLab — rebuild record

This document is the compatibility record for the rebuild. The existing
Vietnamese WebUI remains the client contract; the new runtime services add
explicit lifecycle, checkpoint and remote-storage boundaries around it.

## Source audit

| Area | Existing contract | Rebuild boundary | Verification |
|---|---|---|---|
| WebUI/API | `web/static/*`, `/api/upload`, chapters, translate, audio/export | Existing routers retained; system lifecycle endpoints added | `tests/test_api.py`, route smoke tests |
| SQLite | WAL database, one active book, chapter status and output paths | `Store` remains local; `CheckpointManager` uses SQLite backup API | `tests/test_layout_storage.py`, checkpoint unit tests |
| Chapter parsing | TXT/EPUB decoding and chapter extraction | `storage.files.parse_file` retained | `tests/test_files.py`, `tests/test_novel_suite.py` |
| Translation | CT2/PyTorch adapters, glossary, honorific and pronoun postprocess | Existing `translation` modules remain the engine implementation | translation and pipeline tests |
| TTS | Piper voices, chunking, WAV-to-output encoding | Existing audio service remains the real backend; no fake audio path | audio pipeline tests |
| Audio | merge/range/group exports with FFmpeg | Existing merge service retained | `tests/test_range_audio_workflow.py`, `tests/test_t4_pipeline.py` |
| Jobs | pause/resume/stop, retry, translation→TTS queue | `Job` keeps the worker contract and writes local checkpoints after chapters | `tests/test_jobs.py`, pipeline tests |
| Remote storage | No reliable bucket boundary in source | `storage.hf_bucket.HFBucketStorage` uses official bucket API only | offline adapter tests; live test requires HF secrets |
| Recovery | Partial legacy output state | `storage.checkpoints` records a SQLite snapshot, checksums, chapter/config metadata; `storage.bucket_service` publishes immutable manifest + latest pointer | checkpoint integrity tests |
| MoLab | Existing notebook mixed install, server and tunnel fallbacks | `NovelReader_Molab.py` is the lifecycle UI; Cloudflare is the only public tunnel | AST/import smoke test; live run requires MoLab |

## Explicit non-goals

GitHub Actions, VPS control, Android/Windows clients, Telegram, payments and a
new WebUI are not part of this rebuild. Google Drive and Pixeldrain adapters
remain available as legacy export integrations, but HF Storage Bucket is the
primary recovery store.

## Operational limits

- A Hugging Face bucket is mutable and non-transactional. Checkpoints therefore
  upload an immutable archive and manifest first, then move the book's `latest`
  pointer only after the upload succeeds.
- SQLite is never written directly to remote storage. The backup uses the
  SQLite backup API and an integrity check.
- GPU use is reported only when PyTorch confirms CUDA availability. CT2/Piper
  model providers are not treated as proof of successful GPU inference.
- Cloudflare Quick Tunnel requires a local `cloudflared` executable. The
  application does not silently switch to Pinggy or localhost.run.
- A live HF/cloudflared test needs credentials and network access, so offline
  CI verifies configuration, request construction and local checkpoint hashes.

