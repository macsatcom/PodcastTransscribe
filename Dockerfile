FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --user --no-cache-dir .
COPY . .
RUN pip install --user --no-cache-dir --no-deps -e .

FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq ffmpeg && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos "" appuser
WORKDIR /app
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
RUN mkdir -p /app/portal_images && chown appuser:appuser /app/portal_images
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
