from __future__ import annotations

import sys
from pathlib import Path

from ai_anime_pipeline.render_done import write_render_done
from ai_anime_pipeline.scheduler import PipelineRuntime, run_assets_stage


class DummySentinel:
    def wait_for_release(self, **_: object) -> None:
        return None


def test_run_assets_stage_generates_asset_and_backfills_master(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = PipelineRuntime(
        project_root=project_root,
        workspace_root=Path("/workspace"),
        gpu_sentinel=DummySentinel(),
        hunyuan3d_cmd_template=(
            f"{sys.executable} /workspace/scripts/mock_hunyuan3d.py "
            "--prompt {prompt} --output {output} --ref-image {ref_image} "
            "--negative-prompt {negative_prompt} --seed {seed}"
        ),
    )
    shot = {
        "shot_id": "shot_001",
        "assets": [
            {
                "name": "Console",
                "type": "generate",
                "master": {"path": None, "sha256": None},
                "generation": {"prompt": "anime console prop", "seed": 7},
                "cleaned": {"path": None, "sha256": None, "remeshed": False},
                "target_tris": 8000,
            }
        ],
    }

    updated = run_assets_stage(shot, {"pipeline_spec": {"project_root": str(project_root)}}, runtime)

    master = updated["assets"][0]["master"]
    assert master["path"] == "Assets/Generated/shot_001__console.glb"
    assert master["sha256"]
    assert (project_root / master["path"]).exists()


def test_write_render_done_collects_frame_metadata(tmp_path):
    render_dir = tmp_path / "renders"
    render_dir.mkdir()
    (render_dir / "shot_001.0001.png").write_bytes(b"a")
    (render_dir / "shot_001.0002.png").write_bytes(b"b")
    done_path = tmp_path / "shot_001.render.done"

    payload = write_render_done(render_dir, done_path)

    assert payload["frame_count"] == 2
    assert payload["first_frame_hash"]
    assert payload["last_frame_hash"]
    assert done_path.exists()
