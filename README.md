# NovelReader

NovelReader imports Chinese novels, translates them to Vietnamese with the Hachimi core, and can create speech with Piper or VieNeu. The Web interface and FastAPI service continue to run from the Molab marimo notebook.

## Run on Molab

Open `NovelReader_Molab.py`, select the translation model, TTS engine, and voice, then start the server. The default translation model is `HachimiMT-60-QT`; choose `HachimiMT-60` for modern settings. The notebook checks the GPU and runs translation/TTS inference before it reports GPU readiness. CPU mode remains available when no GPU is attached.

The initial translation batch is estimated from available VRAM. If translation runs out of memory, the worker lowers the batch and retries the same work. Audio begins with one worker. GPU throughput and end-to-end speed have not been benchmarked on Molab hardware in this workspace.

Molab sessions are limited in duration. NovelReader sets a 690-minute processing budget to leave time for a checkpoint, but the notebook cannot guarantee the runtime itself will stay available for 12 hours. At the next session, start the app, connect a Hugging Face write token, and restore the latest checkpoint before continuing. Keep the Molab page open while the current web service is in use; this version does not create a background VPS worker or restart sessions automatically.

## Hugging Face Bucket

The default destination is `hf://buckets/uri410/NovelReader_Cloud_Audio`. The bucket is public, so uploaded source text, translations, configuration, and checkpoints may be read by other people. Only upload stories you are comfortable making public.

In **Settings → Backup & Restore**, enter a Hugging Face write token. The token is held in the running Web process memory and is not written into logs, checkpoints, or bucket objects. Alternatively set `HF_TOKEN` or `HUGGINGFACE_HUB_TOKEN` in the runtime environment. After a restart, enter the token again unless supplied through the environment.

Completed chapter text and audio are queued for upload. A bounded background worker retries failures with backoff and persists its local upload queue. When automatic checkpointing is enabled, NovelReader writes a SQLite-consistent checkpoint periodically and after a job. The archive is uploaded before its checksum manifest and latest pointer; restore validates the checksum before applying the checkpoint. Audio can be included in a checkpoint, or fetched later with **Nạp audio đã lưu** after restoring the story.

Use **Save checkpoint** for a manual save and **Restore** to load a listed story. Restore replaces the active story, so save any current work first. A local ZIP checkpoint and legacy Pixeldrain restore remain available for migration.

## Translation and audio

The model selector uses the models defined in the Hachimi registry. Translation uses the core public `translate_text` API, which owns token-aware chunking and layout restoration. NovelReader preserves paragraph boundaries, glossary terms, and model-specific decoding settings. Blank source paragraphs remain blank. Missing output lines are treated as errors rather than silently dropped.

Translation and audio progress are stored in local SQLite while the runtime is alive. Continue processes missing or failed work; changing only the voice requires regenerating audio. The Bucket checkpoint is the durable copy across runtime resets. Models and voice weights are not included in checkpoints.

## Local development

Install `requirements.txt`, then run:

```powershell
python main.py
```

Run focused tests with:

```powershell
python -m pytest tests/test_translation_pipeline.py tests/test_text.py tests/test_glossary.py tests/test_jobs.py tests/test_api.py
```

GPU, model quality, Piper/VieNeu speed, and long-session behavior require measurements on the target Molab runtime. This workspace has not performed a live Bucket upload or a real Molab benchmark.
