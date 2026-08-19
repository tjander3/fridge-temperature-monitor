FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/fridge-monitor.db

WORKDIR /app

COPY app.py notifier.py ./
COPY sensors.example.json ./sensors.json
COPY static ./static

EXPOSE 8080 1514/udp

CMD ["python", "app.py"]
