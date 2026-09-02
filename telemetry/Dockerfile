# Kart telemetry coaching pipeline, self-contained with a sample session.
#
#   docker build -t racecraft .
#   docker run --rm -p 8800:8800 racecraft
#
# Runs Stage A (recording -> dataset) and Stage B (analytics, coaching, dashboards),
# prints the coaching debrief, then serves the dashboards on http://localhost:8800.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ingestion/requirements.txt ingestion/requirements.txt
RUN pip install --no-cache-dir -r ingestion/requirements.txt

COPY ingestion/ ingestion/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENV VENUE=gateway-kartplex
EXPOSE 8800
ENTRYPOINT ["/app/docker-entrypoint.sh"]
