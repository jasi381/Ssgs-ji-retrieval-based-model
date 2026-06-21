FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SGGS_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

VOLUME ["/data"]

ENTRYPOINT ["sggs-mcp"]
CMD ["serve"]
