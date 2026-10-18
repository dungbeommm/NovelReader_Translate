FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    NOVEL_DATA=/app/data NOVEL_MODELS=/app/models/translation \
    HACHIMIMT_MODELS_DIR=/app/models/translation TTS_VOICE_DIR=/app/models/voices \
    HF_HOME=/cache/huggingface OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 espeak-ng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN useradd -u 10001 -m appuser \
    && mkdir -p /app/data/logs /app/models/translation /app/models/voices /app/output_text /app/output_audio /cache/huggingface \
    && chown -R appuser:appuser /app /cache
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
