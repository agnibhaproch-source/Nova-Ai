# Sandbox runner (docs/43 §2.3). Dev compose mounts the Docker socket; production runs on
# dedicated gVisor hosts (docs/24) — never mount the socket in staging/production.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY sandbox_runner sandbox_runner
RUN useradd -u 10001 -m runner
USER 10001
EXPOSE 8090
CMD ["/srv/.venv/bin/uvicorn", "sandbox_runner.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8090"]
