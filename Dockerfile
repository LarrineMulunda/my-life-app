FROM python:3.12-slim

# Install gcsfuse for mounting Cloud Storage as a filesystem
RUN apt-get update && apt-get install -y \
    curl gnupg lsb-release fuse \
    && gcsFuseRepo=gcsfuse-`lsb_release -c -s` \
    && echo "deb https://packages.cloud.google.com/apt $gcsFuseRepo main" \
    | tee /etc/apt/sources.list.d/gcsfuse.list \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add - \
    && apt-get update && apt-get install -y gcsfuse \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /data

ENV DATABASE_PATH=/data/life.db
ENV PORT=8080

EXPOSE 8080

CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app