FROM ghcr.io/astral-sh/uv:0.13.5 AS uv-bin

FROM python:3.13.7-slim

WORKDIR /app

COPY --from=uv-bin /uv /uvx /bin/

ARG APP_VERSION=1.1.0

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    APP_VERSION=${APP_VERSION} \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project && \
    rm -rf /root/.cache

COPY src/enphase_client.py src/full_backup.py src/self_consumption.py src/ai_optimization.py src/status.py src/web.py /app/

EXPOSE 8080

CMD ["python3", "/app/web.py"]
