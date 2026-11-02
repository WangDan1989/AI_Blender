from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import compute_sha256, save_json_atomic


def collect_render_done_payload(render_dir: Path | str) -> dict[str, Any]:
    directory = Path(render_dir)
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files:
        raise RuntimeError(f"render directory is empty: {directory}")
    return {
        "frame_count": len(files),
        "first_frame_hash": compute_sha256(files[0]),
        "last_frame_hash": compute_sha256(files[-1]),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def write_render_done(render_dir: Path | str, done_path: Path | str) -> dict[str, Any]:
    payload = collect_render_done_payload(render_dir)
    save_json_atomic(done_path, payload)
    return payload
