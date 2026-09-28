# ---- Stage 1 : build du venv avec uv ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---- Stage 2 : runtime python + venv ----
FROM python:3.12-slim-bookworm

# tzdata est requis pour que la variable TZ (posée par docker compose) soit
# prise en compte par datetime.now() dans history.py / new_season.py.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 tarot

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY bot.py curves.py ./
COPY tarot_commands ./tarot_commands

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# Le bot lit/écrit ses fichiers d'état en chemins relatifs : /data est le
# répertoire de travail et doit être monté en volume.
WORKDIR /data
RUN chown tarot:tarot /data
USER tarot
VOLUME ["/data"]

CMD ["python", "/app/bot.py"]
