# ColorPlate GUI + API — single image for container hosts (Render, Fly, Cloud Run).
FROM python:3.12-slim-bookworm

# System libs the wheels dlopen at runtime:
#   libcairo2          -> cairosvg (SVG rasterization)
#   libglib2.0-0/libgl1 -> opencv-python-headless
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY colorplate ./colorplate
RUN pip install ".[web]"

EXPOSE 8000
# $PORT is provided by the host (Render/Cloud Run); falls back to 8000 locally.
CMD ["sh", "-c", "colorplate-web --host 0.0.0.0 --port ${PORT:-8000} --no-browser"]
