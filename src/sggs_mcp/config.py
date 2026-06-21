"""Runtime path configuration for SGGS MCP."""

from __future__ import annotations

import os
from pathlib import Path

DATA_ENV_VAR = "SGGS_DATA_DIR"
DB_ENV_VAR = "DB_PATH"

REQUIRED_DATA_FILES = (
    "sggs_lines.jsonl",
    "sggs_shabads.jsonl",
    "sggs_angs.jsonl",
    "sggs_concepts.jsonl",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    configured = os.environ.get(DATA_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / "output"


def chroma_dir() -> Path:
    return data_dir() / "chroma"


def database_path() -> Path:
    configured = os.environ.get(DB_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / "database.sqlite"


def missing_data_files(base: Path | None = None) -> list[Path]:
    root = base or data_dir()
    missing = [root / name for name in REQUIRED_DATA_FILES if not (root / name).exists()]
    if not (root / "embedding_chunks.jsonl").exists():
        missing.append(root / "embedding_chunks.jsonl")
    return missing
