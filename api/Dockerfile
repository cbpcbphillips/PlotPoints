# The serving API. Build from the repo root (the root Dockerfile is Astro's, for Airflow):
#   just api-build        -> stages the newest snapshot into api/snapshot/, then docker build
#
# The snapshot is baked in, so the running container needs no database and no read credential, and
# every deploy serves exactly one known version of the data (see /meta). To ship new data, rebuild.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Pinned from uv.lock (api/requirements.txt is generated: `just api-reqs`).
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# Flat modules the API imports (scoring, snapshot, fetch_diary, paths) live in src/.
COPY src/scoring.py src/snapshot.py src/fetch_diary.py src/paths.py src/
COPY api/*.py api/
COPY api/snapshot /app/snapshot

ENV PYTHONPATH=/app:/app/src \
    PLOTPOINTS_SNAPSHOT_DIR=/app/snapshot \
    PLOTPOINTS_INBOX=local \
    PLOTPOINTS_DATA_DIR=/tmp/plotpoints

# A non-root user: the process only reads the snapshot and writes to the inbox sink.
RUN useradd --create-home app && mkdir -p /tmp/plotpoints && chown app /tmp/plotpoints
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')"
# $PORT is how Cloud Run and Render tell a container which port to listen on.
CMD ["sh", "-c", "exec uvicorn api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
