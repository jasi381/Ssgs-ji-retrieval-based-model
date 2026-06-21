FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SGGS_DATA_DIR=/data \
    ANONYMIZED_TELEMETRY=False \
    CHROMA_TELEMETRY=false

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY output/ /data/

# Rebuild the semantic index natively so HNSW binaries match the Linux runtime.
# Uses embedding_chunks.jsonl already copied above; model downloads once and is
# baked into the image. The broken macOS-built chroma/ is overwritten here.
RUN SGGS_DATA_DIR=/data sggs-mcp build-index

EXPOSE 8000

ENTRYPOINT ["sggs-mcp"]
CMD ["serve-http", "--host", "0.0.0.0", "--port", "8000"]
