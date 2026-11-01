# DevFlow AI backend (FastAPI + LangGraph)
FROM docker:27-cli AS dockercli

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_ROOT=/var/lib/devflow/workspaces

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI only (no daemon): the backend launches sandbox containers on the
# host daemon. Generated code runs in those sandboxes, never in this container.
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 devflow \
    && mkdir -p /var/lib/devflow/workspaces \
    && chown -R devflow:devflow /var/lib/devflow /app
USER devflow

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# Single worker: workflow execution threads and the checkpointer live in-process.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
