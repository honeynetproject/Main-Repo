# AI Core image (Phase 7: log follower + normalizer + session store).
# Build from the repository root:  docker compose --profile application build ai-core
#
# * Standard library only: nothing is downloaded at build time besides the base image.
# * Base image pinned by tag AND digest (python:3.14-slim-bookworm), matching the
#   Python version the test suite was run on (3.14).
# * Code is root-owned and read-only to the runtime user; the model, training data
#   and Cowrie logs are never copied in (see .dockerignore) - they arrive as volumes.
FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b

LABEL org.opencontainers.image.title="autonomous-deception ai-core" \
      org.opencontainers.image.description="Cowrie log follower, event normalizer and session store (Phase 7)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COWRIE_LOG_DIR=/data/cowrie/logs \
    DATABASE_DIR=/app/db \
    STATE_DIR=/app/state

WORKDIR /app
COPY ai_core/ /app/ai_core/

# Non-root. compose.yaml overrides this with AI_CORE_UID/AI_CORE_GID so the user
# matches the owner of ./data/app/db on the host.
USER 1000:1000

CMD ["python", "-m", "ai_core.ingest", "--follow"]
