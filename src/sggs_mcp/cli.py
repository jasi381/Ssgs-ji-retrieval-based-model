"""Command line entry points for running and maintaining SGGS MCP."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from . import __version__
from .config import DATA_ENV_VAR, chroma_dir, data_dir, database_path, missing_data_files


def _ensure_archive_target(root: Path, target: Path, name: str) -> None:
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Unsafe archive path: {name}") from exc


def run_server() -> int:
    from .server import mcp

    mcp.run(transport="stdio")
    return 0


def run_server_http(host: str = "0.0.0.0", port: int = 8000) -> int:
    from .server import mcp

    mcp.run(transport="streamable-http", host=host, port=port)
    return 0


def doctor() -> int:
    print(f"sggs-mcp {__version__}")
    print(f"Data directory: {data_dir()}")
    print(f"Chroma directory: {chroma_dir()}")
    print(f"Database path: {database_path()}")

    ok = True
    missing = missing_data_files()
    if missing:
        ok = False
        print("\nMissing data files:")
        for path in missing:
            print(f"  - {path}")
    else:
        print("\nData files: OK")

    if chroma_dir().exists():
        print("Semantic index: OK")
    else:
        ok = False
        print("Semantic index: missing. Run `sggs-mcp build-index` after data extraction.")

    for package in ("mcp", "sentence_transformers", "chromadb"):
        if importlib.util.find_spec(package) is None:
            ok = False
            print(f"Dependency missing: {package}")

    if not ok:
        print(f"\nSet {DATA_ENV_VAR}=/path/to/output if your data is outside the repo.")
        return 1

    print("\nDoctor check passed.")
    return 0


def build_index() -> int:
    from .build_index import main as build_index_main

    build_index_main()
    return 0


def extract_multilingual() -> int:
    from .extract_multilingual import main as extract_main

    extract_main()
    return 0


def download_data(url: str | None, destination: str | None) -> int:
    if not url:
        print(
            "No public SGGS MCP data bundle URL is configured yet.\n"
            "After licensing review, run this command with --url pointing to an approved "
            "zip or tar data release.\n\n"
            "Example:\n"
            "  sggs-mcp download-data --url https://example.org/sggs-mcp-data.zip\n"
        )
        return 2

    dest = Path(destination).expanduser().resolve() if destination else data_dir()
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / Path(url).name
    print(f"Downloading {url}")
    print(f"Destination: {dest}")
    urllib.request.urlretrieve(url, archive)

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                target = (dest / member.filename).resolve()
                _ensure_archive_target(dest, target, member.filename)
            zf.extractall(dest)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                target = (dest / member.name).resolve()
                _ensure_archive_target(dest, target, member.name)
            tf.extractall(dest)
    else:
        print(f"Downloaded {archive}; not an archive, leaving it in place.")

    print("Data download complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sggs-mcp")
    parser.add_argument("--version", action="version", version=f"sggs-mcp {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="Run the MCP server over stdio.")
    http_parser = subparsers.add_parser("serve-http", help="Run the MCP server over HTTP (streamable-http transport).")
    http_parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0).")
    http_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000).")
    subparsers.add_parser("doctor", help="Check dependencies, data files, and index state.")
    subparsers.add_parser("build-index", help="Build the Chroma semantic index.")
    subparsers.add_parser("extract-multilingual", help="Enrich data from BaniDB database.sqlite.")

    download_parser = subparsers.add_parser("download-data", help="Download an approved data bundle.")
    download_parser.add_argument("--url", help="Approved zip/tar data bundle URL.")
    download_parser.add_argument("--destination", help=f"Destination directory. Defaults to {DATA_ENV_VAR} or ./output.")

    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "serve":
        return run_server()
    if command == "serve-http":
        return run_server_http(host=args.host, port=args.port)
    if command == "doctor":
        return doctor()
    if command == "build-index":
        return build_index()
    if command == "extract-multilingual":
        return extract_multilingual()
    if command == "download-data":
        return download_data(args.url, args.destination)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
