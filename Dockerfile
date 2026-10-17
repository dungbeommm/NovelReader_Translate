FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    NOVEL_DATA=/app/data BOT_DATA=/botdata \
    NOVEL_MODELS=/app/models/translation HACHIMIMT_MODELS_DIR=/app/models/translation \
    TTS_VOICE_DIR=/app/models/voices HF_HOME=/cache/huggingface \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 espeak-ng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY telegram/requirements.txt /app/telegram/requirements.txt
RUN pip install --no-cache-dir -r telegram/requirements.txt
COPY . /app
RUN useradd -u 10001 -m appuser \
    && mkdir -p /botdata /app/data/logs /app/models/translation /app/models/voices /app/output_text /app/output_audio /cache/huggingface \
    && chown -R appuser:appuser /app /botdata /cache
USER appuser
CMD ["python", "telegram/bot.py"]
