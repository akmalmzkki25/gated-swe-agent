# Linux runner for every step: both agents and the SWE-bench harness.
#
# Why: on Windows, swebench 5.0.2 writes eval.sh and patch.diff with Path.write_text, which
# turns \n into \r\n. Inside the Linux task container that breaks `conda activate testbed\r`
# and every gold patch fails (docs/phase0.md). Running from Linux fixes it without touching
# harness code, and gives anyone reproducing the runs the same environment on any OS.
#
# The runner talks to the host Docker engine through the mounted socket; task containers are
# siblings, not nested. Neither mini-swe-agent nor the harness bind-mounts host paths into
# task containers (they use `docker exec` and tar copies), so this works on Docker Desktop.

FROM docker:28.0.4-cli AS dockercli
FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUTF8=1 \
    MSWEA_CONFIGURED=true \
    PATH=/opt/venv/bin:$PATH

WORKDIR /work
# Dependencies only; the project itself is mounted at /work at run time and installed editable.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-install-project
COPY src ./src
RUN uv sync --frozen
