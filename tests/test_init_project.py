from __future__ import annotations

import json

from ai_anime_pipeline.init_project import init_project


def test_init_project_creates_manifests_and_derives_transition(tmp_path):
    project_root = tmp_path / "AI_Anime_Project"
    source = {
        "pipeline_spec": {
            "project_root": str(project_root),
            "fps": 30,
            "resolution": [1920, 1080],
            "audio_sample_rate": 48000,
            "audio_channels": 2,
            "audio_bit_depth": 24,
            "color_space": "sRGB",
            "default_transition": "cut",
            "default_transition_animation": "hold",
            "default_camera": {"warmup_frames": 24, "tail_frames": 0},
            "camera_presets": {},
            "audio_qc": {
                "rms_db_range": [-24, -12],
                "max_silence_ratio": 0.4,
                "duration_per_char_range": [0.15, 0.45],
            },
            "ducking_params": {
                "threshold": 0.05,
                "ratio": 8,
                "attack": 20,
                "release": 300,
                "knee": 2.8,
            },
        },
        "project_meta": {"title": "Episode 01", "shots_dir": "Outputs/Shots/"},
        "shot_order": ["shot_001", "shot_002"],
        "transitions": [
            {
                "from": "shot_001",
                "to": "shot_002",
                "type": "cross_dissolve",
                "duration_frames": 15,
            }
        ],
        "global_audio": {},
        "role_voicebank": {},
        "shots": [
            {
                "shot_id": "shot_001",
                "camera": {"type": "medium_close"},
                "assets": [
                    {
                        "name": "Hero",
                        "type": "master",
                        "master": {"path": "Assets/Characters/Hero_Master.glb", "sha256": "abc"},
                        "target_tris": 15000,
                    }
                ],
                "dialogue": [{"role": "Hero", "text": "系统已就绪。", "start_offset": 0.0}],
                "sfx": [],
            },
            {
                "shot_id": "shot_002",
                "camera": {"type": "medium_close", "warmup_frames": 12},
                "assets": [],
                "dialogue": [],
                "sfx": [],
            },
        ],
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    init_project(source_path)

    project_manifest = json.loads((project_root / "project_manifest.json").read_text(encoding="utf-8"))
    shot_001 = json.loads((project_root / "Outputs/Shots/shot_001.json").read_text(encoding="utf-8"))
    shot_002 = json.loads((project_root / "Outputs/Shots/shot_002.json").read_text(encoding="utf-8"))

    assert project_manifest["shot_order"] == ["shot_001", "shot_002"]
    assert (project_root / "Outputs/Cleaned").exists()
    assert shot_001["camera"]["warmup_frames"] == 24
    assert shot_002["camera"]["warmup_frames"] == 12
    assert shot_001["render_spec"]["transition_out"] == {
        "type": "cross_dissolve",
        "frames": 15,
        "animation": "hold",
    }
    assert shot_002["render_spec"]["transition_out"] is None
    assert shot_001["stage_status"]["clean"]["state"] == "pending"
    assert shot_001["dialogue"][0]["audio_path"] is None
    assert shot_001["assets"][0]["cleaned"]["sha256"] is None
