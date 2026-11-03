FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY VERSION alembic.ini ./
COPY migrations migrations
COPY scripts scripts
COPY app app

RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/api/health', timeout=2).status == 200 else 1)"

# One worker on purpose: rate limiting is in-process (see README) so more workers multiply the limits.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
