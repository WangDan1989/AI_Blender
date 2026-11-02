from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_anime_pipeline.render_done import write_render_done


def main() -> int:
    parser = argparse.ArgumentParser(description="Write Unreal render .done sentinel")
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--done-file", required=True)
    args = parser.parse_args()
    payload = write_render_done(args.render_dir, args.done_file)
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
