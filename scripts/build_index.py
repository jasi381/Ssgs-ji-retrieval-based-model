"""Backward-compatible wrapper for `sggs-mcp build-index`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sggs_mcp.build_index import main


if __name__ == "__main__":
    main()
