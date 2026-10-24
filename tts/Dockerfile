FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY tts/requirements.txt /app/tts/requirements.txt
RUN pip install --no-cache-dir -r tts/requirements.txt
COPY tts /app/tts
COPY paths.py /app/paths.py
COPY models/voices /app/models/voices
RUN useradd -u 10001 -m appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8010
CMD ["uvicorn", "tts.server:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1", "--no-access-log"]
