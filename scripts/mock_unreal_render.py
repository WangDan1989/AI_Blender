from __future__ import annotations

import argparse
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_anime_pipeline.render_done import write_render_done


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wnqf2sAAAAASUVORK5CYII="
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock Unreal render worker")
    parser.add_argument("--shot-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--done-file", required=True)
    parser.add_argument("--total-frames", required=True, type=int)
    parser.add_argument("--warmup-frames", required=True, type=int)
    parser.add_argument("--shot-manifest", required=True)
    parser.add_argument("--project-manifest", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for frame in range(1, args.total_frames + 1):
        (output_dir / f"{args.shot_id}.{frame:04d}.png").write_bytes(PNG_1X1)
    write_render_done(output_dir, args.done_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
