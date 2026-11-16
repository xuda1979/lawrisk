"""Production launcher: serve API + SPA on a single port.

Usage:
    python -m lawrisk.serve [--host 0.0.0.0] [--port 8000]

Build the frontend first (`cd frontend && npm run build`) so the SPA is served
from the same process; the API otherwise serves /api/* with no UI.
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("LAWRISK_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAWRISK_PORT", "8000")))
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import uvicorn

    uvicorn.run("lawrisk.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
