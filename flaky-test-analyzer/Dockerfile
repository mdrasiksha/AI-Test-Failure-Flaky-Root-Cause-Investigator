FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY --chown=app:app backend backend
COPY --chown=app:app frontend frontend
COPY --chown=app:app sample_data sample_data

USER app
EXPOSE 8000

CMD ["python", "-m", "backend.production"]
