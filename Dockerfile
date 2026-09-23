# Backend image for the LOCAL compose stack (docker-compose.yml). Production
# does not use this image.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source is bind-mounted by compose for hot reload; this copy makes the image
# usable on its own too.
COPY backend ./backend
COPY scripts ./scripts

EXPOSE 8000
CMD ["sh", "-c", "python -m scripts.migrate && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"]
