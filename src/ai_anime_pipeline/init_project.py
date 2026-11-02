from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .io_utils import (
    ensure_posix_relative,
    ensure_project_directories,
    save_json_atomic,
    stage_stub,
)


def init_project(source_path: Path | str) -> dict[str, Any]:
    source = _load_source(source_path)
    pipeline_spec = deepcopy(source["pipeline_spec"])
    project_root = Path(pipeline_spec["project_root"]).resolve()
    ensure_project_directories(project_root)

    project_manifest = {
        "pipeline_spec": pipeline_spec,
        "project_meta": deepcopy(source.get("project_meta", {})),
        "shot_order": list(source["shot_order"]),
        "transitions": deepcopy(source.get("transitions", [])),
        "global_audio": deepcopy(source.get("global_audio", {})),
        "role_voicebank": deepcopy(source.get("role_voicebank", {})),
    }

    project_manifest_path = project_root / "project_manifest.json"
    save_json_atomic(project_manifest_path, project_manifest)

    transition_lookup = _build_transition_lookup(project_manifest)
    shots_by_id = {shot["shot_id"]: shot for shot in source["shots"]}

    for shot_id in project_manifest["shot_order"]:
        shot_source = shots_by_id[shot_id]
        shot_manifest = build_initial_shot_manifest(
            shot_source=shot_source,
            pipeline_spec=pipeline_spec,
            shot_order=project_manifest["shot_order"],
            transition_lookup=transition_lookup,
        )
        save_json_atomic(project_root / "Outputs/Shots" / f"{shot_id}.json", shot_manifest)

    return project_manifest


def build_initial_shot_manifest(
    *,
    shot_source: dict[str, Any],
    pipeline_spec: dict[str, Any],
    shot_order: list[str],
    transition_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    default_camera = pipeline_spec.get(
        "default_camera", {"warmup_frames": 24, "tail_frames": 0}
    )
    src_camera = shot_source.get("camera", {})
    camera = {
        "type": src_camera.get("type", "medium_close"),
        "warmup_frames": src_camera.get("warmup_frames", default_camera["warmup_frames"]),
        "tail_frames": src_camera.get("tail_frames", default_camera["tail_frames"]),
    }

    shot_id = shot_source["shot_id"]
    is_last_shot = shot_id == shot_order[-1]
    transition_out = None if is_last_shot else deepcopy(transition_lookup[shot_id])

    return {
        "shot_id": shot_id,
        "stage_status": {
            "assets": stage_stub(),
            "clean": stage_stub(),
            "audio": stage_stub(),
            "align": stage_stub(),
            "lock": stage_stub(),
            "render": stage_stub(),
        },
        "frames_locked": False,
        "camera": camera,
        "assets": [_normalize_asset(asset) for asset in shot_source.get("assets", [])],
        "dialogue": [
            {
                "role": item["role"],
                "text": item["text"],
                "start_offset": item.get("start_offset", 0.0),
                "audio_path": None,
                "audio_sha256": None,
                "audio_duration": None,
                "audio_status": "pending",
                "alignment_path": None,
                "alignment_sha256": None,
            }
            for item in shot_source.get("dialogue", [])
        ],
        "sfx": [
            {
                "path": ensure_posix_relative(item["path"]),
                "start_offset": item.get("start_offset", 0.0),
                "duration": item.get("duration", 0.0),
                "gain_db": item.get("gain_db", 0.0),
            }
            for item in shot_source.get("sfx", [])
        ],
        "render_spec": {
            "transition_out": transition_out,
            "total_render_frames": None,
        },
    }


def _normalize_asset(asset: dict[str, Any]) -> dict[str, Any]:
    asset_type = asset["type"]
    master_info = asset.get("master", {})
    if asset_type not in {"master", "generate"}:
        raise ValueError(f"unsupported asset type: {asset_type}")
    if asset_type == "generate":
        master = {"path": None, "sha256": None}
    else:
        master = {
            "path": ensure_posix_relative(master_info.get("path")),
            "sha256": master_info.get("sha256"),
        }
    payload = {
        "name": asset["name"],
        "type": asset_type,
        "master": master,
        "cleaned": {"path": None, "sha256": None, "remeshed": False},
        "target_tris": asset.get("target_tris", 15000),
    }
    if asset_type == "generate":
        payload["generation"] = {
            "prompt": asset.get("generation", {}).get("prompt", asset.get("prompt")),
            "negative_prompt": asset.get("generation", {}).get(
                "negative_prompt", asset.get("negative_prompt")
            ),
            "reference_image": ensure_posix_relative(
                asset.get("generation", {}).get("reference_image", asset.get("reference_image"))
            ),
            "seed": asset.get("generation", {}).get("seed", asset.get("seed")),
        }
    return payload


def _build_transition_lookup(project_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    default_type = project_manifest["pipeline_spec"].get("default_transition", "cut")
    default_animation = project_manifest["pipeline_spec"].get(
        "default_transition_animation", "hold"
    )
    transitions = {
        item["from"]: {
            "type": item["type"],
            "frames": item["duration_frames"],
            "animation": item.get("animation", default_animation),
        }
        for item in project_manifest.get("transitions", [])
    }
    lookup: dict[str, dict[str, Any]] = {}
    shot_order = project_manifest["shot_order"]
    for shot_id in shot_order[:-1]:
        lookup[shot_id] = transitions.get(
            shot_id,
            {"type": default_type, "frames": 0, "animation": default_animation},
        )
    return lookup


def _load_source(source_path: Path | str) -> dict[str, Any]:
    from .io_utils import load_json

    source = load_json(source_path)
    if "shots" not in source:
        raise ValueError("source payload must include 'shots'")
    return source
