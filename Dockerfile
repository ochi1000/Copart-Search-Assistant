FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown appuser:appuser /app

COPY --chown=appuser:appuser backend ./backend

USER appuser

CMD ["python", "-m", "backend.main"]
