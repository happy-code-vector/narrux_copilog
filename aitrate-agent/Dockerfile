FROM python:3.11-slim

# libpq-dev no longer needed — Qdrant embedded doesn't require PostgreSQL client

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

RUN useradd -m -u 1000 narrux && chown -R narrux:narrux /app
USER narrux

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
