FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg gosu tesseract-ocr tesseract-ocr-eng libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SOURCEWISE_DATA=/app/data HF_HOME=/app/data/huggingface
WORKDIR /app
COPY requirements.txt requirements-media.txt ./
RUN pip install --no-cache-dir -r requirements-media.txt \
    && useradd --create-home --uid 10001 sourcewise \
    && install -d -m 700 -o sourcewise -g sourcewise /app/data
COPY --chown=sourcewise:sourcewise sourcewise ./sourcewise
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/sourcewise-entrypoint
USER sourcewise

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=15s CMD ["python", "-c", "import os; from urllib.request import urlopen; urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/health', timeout=3).close()"]
ENTRYPOINT ["/usr/local/bin/sourcewise-entrypoint"]
CMD ["serve"]
