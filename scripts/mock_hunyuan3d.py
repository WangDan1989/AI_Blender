from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock Hunyuan3D asset generator")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ref-image", default="")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--seed", default="")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Placeholder bytes for pipeline-stage testing. Replace with the real Hunyuan3D command in production.
    output.write_bytes(
        (
            "mock glb placeholder\n"
            f"prompt={args.prompt}\n"
            f"negative={args.negative_prompt}\n"
            f"ref_image={args.ref_image}\n"
            f"seed={args.seed}\n"
        ).encode("utf-8")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
