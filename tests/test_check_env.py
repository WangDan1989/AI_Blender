from __future__ import annotations

import json
import os

from ai_anime_pipeline.io_utils import save_json_atomic


def test_check_env_json_output(tmp_path):
    config = {
        "paths": {
            "envs_root": str(tmp_path / "envs"),
            "third_party_root": str(tmp_path / "third_party"),
        },
        "tools": {
            "ffmpeg": {
                "binary_candidates": [],
                "env_var": "AI_ANIME_FFMPEG_BIN",
                "installer": {"type": "winget", "id": "x"},
            },
            "ffprobe": {
                "binary_candidates": [],
                "env_var": "AI_ANIME_FFPROBE_BIN",
            },
            "blender": {
                "binary_candidates": [],
                "env_var": "AI_ANIME_BLENDER_BIN",
                "installer": {"type": "winget", "id": "x"},
            },
            "git": {
                "binary_candidates": [],
                "env_var": "GIT_BIN",
                "installer": {"type": "winget", "id": "x"},
            },
            "micromamba": {
                "binary_candidates": [],
                "env_var": "MICROMAMBA_BIN",
                "installer": {"type": "winget", "id": "x"},
            },
            "cosyvoice": {
                "env_name": "cosy",
                "env_var": "AI_ANIME_COSYVOICE_CMD_TEMPLATE",
            },
            "whisperx": {
                "env_name": "whisperx",
                "env_var": "AI_ANIME_WHISPERX_CMD_TEMPLATE",
            },
            "hunyuan3d": {
                "env_name": "hunyuan3d",
                "env_var": "AI_ANIME_HUNYUAN3D_CMD_TEMPLATE",
            },
        },
    }
    (tmp_path / "envs" / "cosy").mkdir(parents=True)
    (tmp_path / "third_party" / "cosyvoice").mkdir(parents=True)
    os.environ["AI_ANIME_COSYVOICE_CMD_TEMPLATE"] = "present"
    config_path = tmp_path / "tools.json"
    save_json_atomic(config_path, config)

    import sys
    from pathlib import Path
    import subprocess

    result = subprocess.run(
        [sys.executable, "/workspace/scripts/check_env.py", "--config", str(config_path), "--json"],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )

    payload = json.loads(result.stdout)
    assert any(item["name"] == "cosyvoice" for item in payload)
