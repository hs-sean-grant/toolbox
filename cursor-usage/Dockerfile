FROM python:3.12-slim

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app

WORKDIR /app
COPY app.py index.html ./
RUN mkdir -p /data && chown -R app:app /app /data

ENV PORT=8799 \
    USAGE_INTERVAL=600 \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 8799
VOLUME ["/data"]

USER app
ENTRYPOINT ["python", "app.py"]
