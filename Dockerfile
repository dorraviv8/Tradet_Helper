FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5173 \
    JOURNAL_DB_PATH=/data/trader_journal.sqlite3

WORKDIR /app

RUN useradd --create-home --uid 10001 trader \
    && mkdir -p /data \
    && chown trader:trader /data

COPY --chown=trader:trader app/ /app/

USER trader
VOLUME ["/data"]
EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:5173/health', timeout=3)" || exit 1

CMD ["python", "server.py"]
