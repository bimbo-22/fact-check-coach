# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# App code + fixtures (fixtures power MOCK mode, so the container works offline).
COPY app ./app
COPY bot ./bot
COPY scripts ./scripts
COPY web ./web
COPY tests ./tests
RUN useradd --create-home --uid 10001 coach && chown -R coach /app
USER coach

# `docker build --target test .` runs the full test suite in mock mode.
FROM base AS test
USER root
COPY requirements-dev.txt pytest.ini ./
RUN pip install -r requirements-dev.txt
USER coach
ENV LLM_PROVIDER=mock SEARCH_PROVIDER=mock
RUN python -m pytest -q -p no:warnings

FROM base AS runtime
ENV LLM_PROVIDER=mock SEARCH_PROVIDER=mock
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
