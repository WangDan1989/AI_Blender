from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_render_done_from_output_dir(output_dir: str, done_file: str) -> dict:
    directory = Path(output_dir)
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files:
        raise RuntimeError(f"render output is empty: {directory}")
    payload = {
        "frame_count": len(files),
        "first_frame_hash": sha256_file(files[0]),
        "last_frame_hash": sha256_file(files[-1]),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json_atomic(Path(done_file), payload)
    return payload
