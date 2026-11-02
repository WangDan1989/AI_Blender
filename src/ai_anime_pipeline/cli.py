from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from .init_project import init_project
from .scheduler import main as scheduler_main


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI anime pipeline tools")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="initialize project and shot manifests")
    init_cmd.add_argument("--source", required=True, help="Qwen structured JSON payload")

    scheduler_cmd = sub.add_parser("scheduler", help="delegate to the runtime scheduler")
    scheduler_cmd.add_argument("scheduler_args", nargs=argparse.REMAINDER)

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "init":
        init_project(Path(args.source))
        return 0
    return scheduler_main(args.scheduler_args)


if __name__ == "__main__":
    raise SystemExit(main())
