FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SGGS_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY output/ /data/

EXPOSE 8000

ENTRYPOINT ["sggs-mcp"]
CMD ["serve-http", "--host", "0.0.0.0", "--port", "8000"]
