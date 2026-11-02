from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

from ai_anime_pipeline.io_utils import save_json_atomic
from ai_anime_pipeline.scheduler import (
    PipelineRuntime,
    apply_lock_stage,
    compute_shot_timeline_offsets,
    compute_total_frames,
    run_stage,
)


class DummySentinel:
    def wait_for_release(self, **_: object) -> None:
        return None


def test_run_stage_resets_stale_running_and_marks_passed(tmp_path):
    shot = {
        "shot_id": "shot_001",
        "stage_status": {"assets": {"state": "running", "retry": 0, "last_error": None}},
    }
    project = {"pipeline_spec": {"project_root": str(tmp_path)}}
    runtime = PipelineRuntime(project_root=tmp_path, workspace_root=tmp_path, gpu_sentinel=DummySentinel())

    def runner(shot_payload, _project, _runtime):
        shot_payload["value"] = 1
        return shot_payload

    updated = run_stage(shot, project, "assets", runner, runtime)

    assert updated["value"] == 1
    assert updated["stage_status"]["assets"]["state"] == "passed"
    assert updated["stage_status"]["assets"]["retry"] == 1
    assert updated["stage_status"]["assets"]["last_error"] is None


def test_apply_lock_stage_hash_checks_and_total_frames(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "Outputs/Audio").mkdir(parents=True)
    (project_root / "Outputs/Align").mkdir(parents=True)

    audio_path = project_root / "Outputs/Audio/shot_001__dlg_001.wav"
    write_silence_wav(audio_path, frames=48000, sample_rate=48000)
    align_path = project_root / "Outputs/Align/shot_001__dlg_001.json"
    save_json_atomic(
        align_path,
        [{"word": "系统", "abs_start": 0.0, "abs_end": 0.5, "score": 0.99}],
    )

    shot = {
        "shot_id": "shot_001",
        "stage_status": {
            "audio": {"state": "passed", "retry": 0, "last_error": None},
            "align": {"state": "passed", "retry": 0, "last_error": None},
            "lock": {"state": "pending", "retry": 0, "last_error": None},
        },
        "frames_locked": False,
        "camera": {"tail_frames": 5},
        "dialogue": [
            {
                "start_offset": 0.0,
                "audio_path": "Outputs/Audio/shot_001__dlg_001.wav",
                "audio_sha256": sha256(audio_path),
                "audio_duration": 1.0,
                "alignment_path": "Outputs/Align/shot_001__dlg_001.json",
                "alignment_sha256": sha256(align_path),
            }
        ],
        "sfx": [{"path": "Assets/Audio/SFX/hit.wav", "start_offset": 2.0, "duration": 0.8}],
        "render_spec": {"transition_out": {"frames": 15}},
    }
    project = {"pipeline_spec": {"project_root": str(project_root), "fps": 30}}
    runtime = PipelineRuntime(project_root=project_root, workspace_root=tmp_path, gpu_sentinel=DummySentinel())

    locked = apply_lock_stage(shot, project, runtime)

    assert locked["frames_locked"] is True
    assert locked["render_spec"]["total_render_frames"] == compute_total_frames(shot, 30)


def test_compute_shot_timeline_offsets_subtracts_transition_overlap():
    project = {"pipeline_spec": {"fps": 30}, "shot_order": ["shot_001", "shot_002", "shot_003"]}
    shots = {
        "shot_001": {"render_spec": {"total_render_frames": 90, "transition_out": {"frames": 15}}},
        "shot_002": {"render_spec": {"total_render_frames": 60, "transition_out": {"frames": 0}}},
        "shot_003": {"render_spec": {"total_render_frames": 45, "transition_out": None}},
    }

    offsets = compute_shot_timeline_offsets(project, shots)

    assert offsets == {"shot_001": 0.0, "shot_002": 2.5, "shot_003": 4.5}


def write_silence_wav(path: Path, *, frames: int, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00\x00\x00" * frames)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
