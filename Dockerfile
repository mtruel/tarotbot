# ---- Stage 1 : build du venv avec uv ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---- Stage 2 : telechargement de supercronic (verifie par SHA1) ----
FROM debian:bookworm-slim AS supercronic

ARG TARGETARCH=arm64
ARG SUPERCRONIC_VERSION=v0.2.49
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      arm64) SHA1=0b6c5bb743e0b0dafed1132198c81807927ac413 ;; \
      amd64) SHA1=e63c11a9726b775a6a11801e81af4f3fb926aa68 ;; \
      *) echo "Architecture non supportee : $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
         -o /supercronic \
    && echo "${SHA1}  /supercronic" | sha1sum -c - \
    && chmod +x /supercronic

# ---- Stage 3 : runtime python + venv ----
FROM python:3.12-slim-bookworm

# tzdata est requis pour que la variable TZ (posée par docker compose) soit
# prise en compte par datetime.now() dans history.py / new_season.py.
# rclone (acces Google Drive), restic (snapshots + rotation + copie vers Drive)
# et ca-certificates (HTTPS vers les API Google) sont les seuls outils externes
# necessaires : les archives zip sont produites par la stdlib Python du venv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata rclone restic ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 tarot

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY bot.py curves.py ./
COPY tarot_commands ./tarot_commands
COPY --from=supercronic /supercronic /usr/local/bin/supercronic
COPY backup/backup.sh backup/entrypoint.sh /usr/local/bin/
COPY backup/crontab /etc/tarotbot/crontab
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# Le bot lit/écrit ses fichiers d'état en chemins relatifs : /data est le
# répertoire de travail et doit être monté en volume.
WORKDIR /data
RUN chown tarot:tarot /data
USER tarot
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
