FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV DATABASE_PATH=/data/life.db
ENV PORT=8080

EXPOSE 8080

CMD python3 -c "from db import init_db; init_db(); print('DB tables ready')" && \
    exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app