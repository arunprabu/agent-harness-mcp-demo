# The MCP server as a container image, to run in AWS ECS Fargate.
# Every line is explained in ../guides/04_DEPLOYMENT_GUIDE.md.

# A small official Python image, the same version as .python-version.
FROM python:3.13-slim

# Copy the uv tool from uv's official image. A fixed version means the same build every time.
COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /bin/uv

WORKDIR /app

# Install the dependencies exactly as locked in uv.lock. Docker caches this step,
# so when only server.py changes, the next build skips the install.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache

# Then copy the code. Only server.py: .env and every other file stay out of the image.
COPY server.py ./

# PATH: use the packages uv just installed in /app/.venv.
# HOST=0.0.0.0: accept connections from outside the container (127.0.0.1 would refuse them).
# PYTHONUNBUFFERED=1: print() lines reach the logs right away, not in batches.
ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

# Don't run as root. If someone ever broke in through the server, they'd get fewer rights.
RUN useradd --system app
USER app

EXPOSE 9001
CMD ["python", "server.py"]
