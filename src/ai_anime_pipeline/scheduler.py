from __future__ import annotations

import argparse
import math
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .io_utils import (
    GpuSentinel,
    clear_directory,
    compute_sha256,
    ensure_posix_relative,
    ffmpeg_pcm_codec,
    ffprobe_duration_seconds,
    load_json,
    read_wav_pcm_metrics,
    resolve_project_path,
    run_logged_command,
    save_json_atomic,
)


STAGES = ["assets", "clean", "audio", "align", "lock", "render"]


@dataclass(slots=True)
class PipelineRuntime:
    project_root: Path
    workspace_root: Path
    gpu_sentinel: GpuSentinel
    blender_bin: str = "blender"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    hunyuan3d_cmd_template: str | None = None
    cosyvoice_cmd_template: str | None = None
    whisperx_cmd_template: str | None = None
    unreal_cmd_template: str | None = None

    @classmethod
    def from_project(cls, project: dict[str, Any]) -> "PipelineRuntime":
        workspace_root = Path(__file__).resolve().parents[2]
        project_root = Path(project["pipeline_spec"]["project_root"]).resolve()
        return cls(
            project_root=project_root,
            workspace_root=workspace_root,
            gpu_sentinel=GpuSentinel.capture_baseline(),
            blender_bin=os.environ.get("AI_ANIME_BLENDER_BIN", "blender"),
            ffmpeg_bin=os.environ.get("AI_ANIME_FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=os.environ.get("AI_ANIME_FFPROBE_BIN", "ffprobe"),
            hunyuan3d_cmd_template=os.environ.get("AI_ANIME_HUNYUAN3D_CMD_TEMPLATE"),
            cosyvoice_cmd_template=os.environ.get("AI_ANIME_COSYVOICE_CMD_TEMPLATE"),
            whisperx_cmd_template=os.environ.get("AI_ANIME_WHISPERX_CMD_TEMPLATE"),
            unreal_cmd_template=os.environ.get("AI_ANIME_UNREAL_CMD_TEMPLATE"),
        )


def run_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    stage: str,
    runner,
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    st = shot["stage_status"][stage]
    if st["state"] == "passed":
        return shot
    if st["state"] == "running":
        st["state"] = "failed"
        st["retry"] += 1
        st["last_error"] = "stale running state detected from previous crash"
    if st["retry"] >= 3:
        raise RuntimeError(f"{shot['shot_id']}/{stage} retry exceeded")
    st["state"] = "running"
    st["last_error"] = None
    try:
        shot = runner(shot, project, runtime)
        st["state"] = "passed"
    except Exception as exc:  # noqa: BLE001
        st["state"] = "failed"
        st["retry"] += 1
        st["last_error"] = repr(exc)
    return shot


def run_shot_pipeline(
    shot_path: Path | str,
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    shot = load_json(shot_path)
    runners = {
        "assets": run_assets_stage,
        "clean": run_clean_stage,
        "audio": run_audio_stage,
        "align": run_align_stage,
        "lock": apply_lock_stage,
        "render": run_render_stage,
    }
    shot_file = Path(shot_path)
    for stage in STAGES:
        shot = run_stage(shot, project, stage, runners[stage], runtime)
        save_json_atomic(shot_file, shot)
        if shot["stage_status"][stage]["state"] != "passed":
            return shot
    return shot


def run_assets_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    for asset in shot.get("assets", []):
        master = asset["master"]
        if asset["type"] == "generate":
            generated = ensure_generated_asset(asset=asset, shot=shot, runtime=runtime)
            master["path"] = ensure_posix_relative(
                generated.relative_to(runtime.project_root).as_posix()
            )
            master["sha256"] = compute_sha256(generated)
            continue
        if not master.get("path"):
            raise RuntimeError(f"master asset missing path: {asset['name']}")
        source_abs = resolve_project_path(runtime.project_root, master["path"])
        if not source_abs.exists():
            raise FileNotFoundError(source_abs)
        actual_sha = compute_sha256(source_abs)
        if master.get("sha256") and master["sha256"] != actual_sha:
            raise RuntimeError(f"master hash mismatch for {asset['name']}")
        master["sha256"] = actual_sha
    return shot


def ensure_generated_asset(
    *,
    asset: dict[str, Any],
    shot: dict[str, Any],
    runtime: PipelineRuntime,
) -> Path:
    master = asset["master"]
    if master.get("path") and master.get("sha256"):
        existing_abs = resolve_project_path(runtime.project_root, master["path"])
        if existing_abs.exists() and compute_sha256(existing_abs) == master["sha256"]:
            return existing_abs

    if not runtime.hunyuan3d_cmd_template:
        raise RuntimeError("missing required environment variable: AI_ANIME_HUNYUAN3D_CMD_TEMPLATE")

    generation = asset.get("generation", {})
    prompt = generation.get("prompt")
    if not prompt:
        raise RuntimeError(f"generate asset missing generation.prompt: {asset['name']}")

    reference_image = generation.get("reference_image")
    reference_image_abs = (
        resolve_project_path(runtime.project_root, reference_image) if reference_image else None
    )
    output_rel = f"Assets/Generated/{shot['shot_id']}__{slugify(asset['name'])}.glb"
    output_abs = resolve_project_path(runtime.project_root, output_rel)
    output_abs.parent.mkdir(parents=True, exist_ok=True)
    command = format_template_command(
        runtime.hunyuan3d_cmd_template,
        prompt=prompt,
        negative_prompt=generation.get("negative_prompt") or "",
        ref_image=str(reference_image_abs) if reference_image_abs else "",
        output=str(output_abs),
        seed="" if generation.get("seed") is None else str(generation["seed"]),
        asset_name=asset["name"],
        shot_id=shot["shot_id"],
    )
    result = run_logged_command(command, cwd=runtime.project_root)
    if result.returncode != 0:
        raise RuntimeError(
            f"Hunyuan3D generation failed for {asset['name']}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    runtime.gpu_sentinel.wait_for_release()
    if not output_abs.exists():
        raise RuntimeError(f"Hunyuan3D output missing: {output_abs}")
    return output_abs


def run_clean_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    clean_script = runtime.workspace_root / "scripts" / "clean_asset.py"
    if not clean_script.exists():
        raise FileNotFoundError(clean_script)
    for asset in shot.get("assets", []):
        cleaned = asset["cleaned"]
        if cleaned.get("path") and cleaned.get("sha256"):
            existing_abs = resolve_project_path(runtime.project_root, cleaned["path"])
            if existing_abs.exists() and compute_sha256(existing_abs) == cleaned["sha256"]:
                continue

        source_rel = asset["master"]["path"]
        if not source_rel:
            raise RuntimeError(f"asset source path unavailable: {asset['name']}")
        source_abs = resolve_project_path(runtime.project_root, source_rel)
        output_rel = f"Outputs/Cleaned/{shot['shot_id']}__{slugify(asset['name'])}.glb"
        output_abs = resolve_project_path(runtime.project_root, output_rel)
        output_abs.parent.mkdir(parents=True, exist_ok=True)
        remove_doubles_dist = 5e-5 if asset.get("target_tris", 15000) >= 10000 else 1e-3
        command = [
            runtime.blender_bin,
            "-b",
            "--python",
            str(clean_script),
            "--",
            str(source_abs),
            str(output_abs),
            str(asset.get("target_tris", 15000)),
            str(remove_doubles_dist),
        ]
        result = run_logged_command(command, cwd=runtime.workspace_root)
        stdout = result.stdout or ""
        if result.returncode != 0 or "FAILED_MESH:" in stdout:
            raise RuntimeError(
                f"blender clean failed for {asset['name']}: "
                f"exit={result.returncode} stdout={stdout.strip()} stderr={result.stderr.strip()}"
            )
        if not output_abs.exists():
            raise RuntimeError(f"cleaned asset missing after blender export: {output_abs}")
        cleaned["path"] = ensure_posix_relative(output_rel)
        cleaned["sha256"] = compute_sha256(output_abs)
        cleaned["remeshed"] = "REMESHED:true" in stdout
    return shot


def run_audio_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    unlock_frames(shot)
    if not runtime.cosyvoice_cmd_template:
        raise RuntimeError(
            "missing required environment variable: AI_ANIME_COSYVOICE_CMD_TEMPLATE"
        )
    role_voicebank = project.get("role_voicebank", {})
    spec = project["pipeline_spec"]
    for index, dialogue in enumerate(shot.get("dialogue", []), start=1):
        if dialogue.get("audio_path") and dialogue.get("audio_sha256") and dialogue.get("audio_duration"):
            audio_abs = resolve_project_path(runtime.project_root, dialogue["audio_path"])
            if audio_abs.exists() and compute_sha256(audio_abs) == dialogue["audio_sha256"]:
                dialogue["audio_status"] = "accepted"
                continue

        voice_ref = role_voicebank.get(dialogue["role"])
        if not voice_ref:
            raise RuntimeError(f"missing voicebank for role: {dialogue['role']}")
        ref_audio_abs = resolve_project_path(runtime.project_root, voice_ref["ref_audio"])
        raw_output_rel = f"Outputs/Audio/{shot['shot_id']}__dlg_{index:03d}.synth.wav"
        raw_output_abs = resolve_project_path(runtime.project_root, raw_output_rel)
        final_output_rel = f"Outputs/Audio/{shot['shot_id']}__dlg_{index:03d}.wav"
        final_output_abs = resolve_project_path(runtime.project_root, final_output_rel)
        raw_output_abs.parent.mkdir(parents=True, exist_ok=True)

        synth_command = format_template_command(
            runtime.cosyvoice_cmd_template,
            text=dialogue["text"],
            ref_audio=str(ref_audio_abs),
            ref_text=voice_ref["ref_text"],
            output=str(raw_output_abs),
            role=dialogue["role"],
            shot_id=shot["shot_id"],
            dialogue_index=str(index),
        )
        synth_result = run_logged_command(synth_command, cwd=runtime.project_root)
        if synth_result.returncode != 0:
            raise RuntimeError(
                f"CosyVoice synthesis failed for {shot['shot_id']}#{index}: "
                f"{synth_result.stderr.strip() or synth_result.stdout.strip()}"
            )
        runtime.gpu_sentinel.wait_for_release()
        if not raw_output_abs.exists():
            raise RuntimeError(f"CosyVoice output missing: {raw_output_abs}")

        resample_wav(
            input_path=raw_output_abs,
            output_path=final_output_abs,
            spec=spec,
            ffmpeg_bin=runtime.ffmpeg_bin,
        )
        try:
            qc = validate_dialogue_audio(final_output_abs, dialogue["text"], spec["audio_qc"])
        except Exception:  # noqa: BLE001
            dialogue["audio_status"] = "rejected"
            raise
        dialogue["audio_status"] = "accepted"
        dialogue["audio_path"] = ensure_posix_relative(final_output_rel)
        dialogue["audio_sha256"] = compute_sha256(final_output_abs)
        dialogue["audio_duration"] = qc["duration_sec"]
        if raw_output_abs.exists():
            raw_output_abs.unlink()
    return shot


def run_align_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    unlock_frames(shot)
    if not runtime.whisperx_cmd_template:
        raise RuntimeError(
            "missing required environment variable: AI_ANIME_WHISPERX_CMD_TEMPLATE"
        )
    for index, dialogue in enumerate(shot.get("dialogue", []), start=1):
        if dialogue.get("audio_status") == "rejected":
            raise RuntimeError(f"rejected dialogue cannot enter align stage: {index}")
        audio_rel = dialogue.get("audio_path")
        audio_sha = dialogue.get("audio_sha256")
        if not audio_rel or not audio_sha:
            raise RuntimeError(f"dialogue audio missing for alignment: {index}")
        audio_abs = resolve_project_path(runtime.project_root, audio_rel)
        if compute_sha256(audio_abs) != audio_sha:
            raise RuntimeError(f"dialogue audio hash mismatch before align: {index}")

        if dialogue.get("alignment_path") and dialogue.get("alignment_sha256"):
            align_abs = resolve_project_path(runtime.project_root, dialogue["alignment_path"])
            if align_abs.exists() and compute_sha256(align_abs) == dialogue["alignment_sha256"]:
                continue

        relative_json_rel = f"Outputs/Align/{shot['shot_id']}__dlg_{index:03d}.relative.json"
        relative_json_abs = resolve_project_path(runtime.project_root, relative_json_rel)
        absolute_json_rel = f"Outputs/Align/{shot['shot_id']}__dlg_{index:03d}.json"
        absolute_json_abs = resolve_project_path(runtime.project_root, absolute_json_rel)
        relative_json_abs.parent.mkdir(parents=True, exist_ok=True)

        align_command = format_template_command(
            runtime.whisperx_cmd_template,
            audio=str(audio_abs),
            output=str(relative_json_abs),
            text=dialogue["text"],
            role=dialogue["role"],
            shot_id=shot["shot_id"],
            dialogue_index=str(index),
        )
        align_result = run_logged_command(align_command, cwd=runtime.project_root)
        if align_result.returncode != 0:
            raise RuntimeError(
                f"WhisperX alignment failed for {shot['shot_id']}#{index}: "
                f"{align_result.stderr.strip() or align_result.stdout.strip()}"
            )
        runtime.gpu_sentinel.wait_for_release()
        if not relative_json_abs.exists():
            raise RuntimeError(f"WhisperX output missing: {relative_json_abs}")

        relative_payload = load_json(relative_json_abs)
        absolute_words = to_absolute_alignment(relative_payload, dialogue["start_offset"])
        save_json_atomic(absolute_json_abs, absolute_words)
        dialogue["alignment_path"] = ensure_posix_relative(absolute_json_rel)
        dialogue["alignment_sha256"] = compute_sha256(absolute_json_abs)
        relative_json_abs.unlink(missing_ok=True)

    validate_and_update_sfx_durations(shot, runtime)
    return shot


def apply_lock_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    if shot["stage_status"]["audio"]["state"] != "passed":
        raise RuntimeError("audio stage must pass before lock")
    if shot["stage_status"]["align"]["state"] != "passed":
        raise RuntimeError("align stage must pass before lock")

    for dialogue in shot.get("dialogue", []):
        audio_rel = dialogue.get("audio_path")
        audio_sha = dialogue.get("audio_sha256")
        align_rel = dialogue.get("alignment_path")
        align_sha = dialogue.get("alignment_sha256")
        if not audio_rel or not audio_sha or not align_rel or not align_sha:
            raise RuntimeError("dialogue assets incomplete for lock stage")
        audio_abs = resolve_project_path(runtime.project_root, audio_rel)
        align_abs = resolve_project_path(runtime.project_root, align_rel)
        if compute_sha256(audio_abs) != audio_sha:
            mark_stage_for_rework(shot, "audio", "audio hash mismatch during lock")
            raise RuntimeError("audio hash mismatch during lock")
        if compute_sha256(align_abs) != align_sha:
            mark_stage_for_rework(shot, "align", "alignment hash mismatch during lock")
            raise RuntimeError("alignment hash mismatch during lock")

    shot["render_spec"]["total_render_frames"] = compute_total_frames(
        shot, project["pipeline_spec"]["fps"]
    )
    shot["frames_locked"] = True
    return shot


def run_render_stage(
    shot: dict[str, Any],
    project: dict[str, Any],
    runtime: PipelineRuntime,
) -> dict[str, Any]:
    if not shot.get("frames_locked"):
        raise RuntimeError("lock stage must pass before render")
    if not runtime.unreal_cmd_template:
        raise RuntimeError("missing required environment variable: AI_ANIME_UNREAL_CMD_TEMPLATE")

    total_frames = shot["render_spec"].get("total_render_frames")
    if not isinstance(total_frames, int) or total_frames <= 0:
        raise RuntimeError("invalid total_render_frames")

    output_rel = f"Outputs/Renders/{shot['shot_id']}"
    output_abs = resolve_project_path(runtime.project_root, output_rel)
    output_abs.mkdir(parents=True, exist_ok=True)
    done_path = runtime.project_root / "Outputs/Shots" / f"{shot['shot_id']}.render.done"

    if done_path.exists():
        done_payload = load_json(done_path)
        if done_payload.get("frame_count") == total_frames:
            return shot
        clear_directory(output_abs)
        done_path.unlink(missing_ok=True)
        raise RuntimeError(f"render done frame_count mismatch for {shot['shot_id']}")

    if any(output_abs.iterdir()):
        clear_directory(output_abs)

    command = format_template_command(
        runtime.unreal_cmd_template,
        shot_id=shot["shot_id"],
        shot_manifest=str(runtime.project_root / "Outputs/Shots" / f"{shot['shot_id']}.json"),
        project_manifest=str(runtime.project_root / "project_manifest.json"),
        output_dir=str(output_abs),
        done_file=str(done_path),
        total_frames=str(total_frames),
        warmup_frames=str(shot["camera"]["warmup_frames"]),
    )
    result = run_logged_command(command, cwd=runtime.project_root)
    if result.returncode != 0:
        clear_directory(output_abs)
        raise RuntimeError(
            f"Unreal render command failed for {shot['shot_id']}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    if not done_path.exists():
        clear_directory(output_abs)
        raise RuntimeError(f"missing render .done sentinel for {shot['shot_id']}")
    done_payload = load_json(done_path)
    if done_payload.get("frame_count") != total_frames:
        clear_directory(output_abs)
        done_path.unlink(missing_ok=True)
        raise RuntimeError(f"render done frame_count mismatch for {shot['shot_id']}")
    return shot


def assert_all_rendered(project: dict[str, Any], shots: dict[str, dict[str, Any]]) -> None:
    root = Path(project["pipeline_spec"]["project_root"]).resolve()
    for shot_id in project["shot_order"]:
        shot = shots[shot_id]
        if shot["stage_status"]["render"]["state"] != "passed":
            raise RuntimeError(f"shot not rendered: {shot_id}")
        done_path = root / "Outputs/Shots" / f"{shot_id}.render.done"
        if not done_path.exists():
            raise RuntimeError(f"render done missing: {shot_id}")
        done_payload = load_json(done_path)
        if done_payload.get("frame_count") != shot["render_spec"]["total_render_frames"]:
            raise RuntimeError(f"render done mismatch: {shot_id}")


def run_global_ffmpeg_assembly(
    project: dict[str, Any],
    shots: dict[str, dict[str, Any]],
    runtime: PipelineRuntime,
) -> Path:
    assert_all_rendered(project, shots)
    spec = project["pipeline_spec"]
    fps = spec["fps"]
    timeline_offsets = compute_shot_timeline_offsets(project, shots)

    dialogue_entries: list[dict[str, Any]] = []
    sfx_entries: list[dict[str, Any]] = []
    for shot_id in project["shot_order"]:
        shot = shots[shot_id]
        base_start = timeline_offsets[shot_id]
        for dialogue in shot.get("dialogue", []):
            dialogue_entries.append(
                {
                    "path": resolve_project_path(runtime.project_root, dialogue["audio_path"]),
                    "start_sec": base_start + dialogue["start_offset"],
                    "gain_db": 0.0,
                }
            )
        for sfx in shot.get("sfx", []):
            sfx_entries.append(
                {
                    "path": resolve_project_path(runtime.project_root, sfx["path"]),
                    "start_sec": base_start + sfx["start_offset"],
                    "gain_db": sfx.get("gain_db", 0.0),
                }
            )

    dialogue_bus = runtime.project_root / "Outputs/Audio/dialogue_bus.wav"
    build_audio_bus(dialogue_entries, dialogue_bus, spec, runtime.ffmpeg_bin)

    sfx_bus = runtime.project_root / "Outputs/Audio/sfx_bus.wav"
    if sfx_entries:
        build_audio_bus(sfx_entries, sfx_bus, spec, runtime.ffmpeg_bin)

    final_duration = compute_project_duration_seconds(project, shots)
    final_output = runtime.project_root / "Outputs" / "final_episode.mov"
    ffmpeg_work = runtime.project_root / "Outputs" / "ffmpeg"
    ffmpeg_work.mkdir(parents=True, exist_ok=True)
    filter_script = ffmpeg_work / "assembly_filtergraph.txt"

    video_inputs, video_filter, video_label = build_video_filter(
        project=project,
        shots=shots,
        runtime=runtime,
        timeline_offsets=timeline_offsets,
    )
    audio_inputs, audio_filter, audio_label = build_audio_mix_filter(
        project=project,
        runtime=runtime,
        dialogue_bus=dialogue_bus,
        sfx_bus=sfx_bus if sfx_entries else None,
        total_duration=final_duration,
    )
    filter_script.write_text(video_filter + "\n" + audio_filter + "\n", encoding="utf-8")

    command = (
        [runtime.ffmpeg_bin, "-y"]
        + video_inputs
        + audio_inputs
        + [
            "-filter_complex_script",
            str(filter_script),
            "-map",
            video_label,
            "-map",
            audio_label,
            "-r",
            str(fps),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            ffmpeg_pcm_codec(spec["audio_bit_depth"]),
            str(final_output),
        ]
    )
    result = run_logged_command(command, cwd=runtime.project_root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return final_output


def build_audio_bus(
    entries: list[dict[str, Any]],
    output_path: Path,
    spec: dict[str, Any],
    ffmpeg_bin: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not entries:
        raise RuntimeError("audio bus requires at least one entry")
    command = [ffmpeg_bin, "-y"]
    filter_parts: list[str] = []
    mix_labels: list[str] = []
    for index, entry in enumerate(entries):
        command.extend(["-i", str(entry["path"])])
        delay_ms = int(round(entry["start_sec"] * 1000))
        label = f"a{index}"
        gain_db = entry.get("gain_db", 0.0)
        filter_parts.append(
            f"[{index}:a]adelay={delay_ms}|{delay_ms},volume={db_to_volume(gain_db)}[{label}]"
        )
        mix_labels.append(f"[{label}]")
    filter_parts.append(
        "".join(mix_labels)
        + f"amix=inputs={len(entries)}:normalize=0,aresample={spec['audio_sample_rate']}[mixout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[mixout]",
            "-ar",
            str(spec["audio_sample_rate"]),
            "-ac",
            str(spec["audio_channels"]),
            "-c:a",
            ffmpeg_pcm_codec(spec["audio_bit_depth"]),
            str(output_path),
        ]
    )
    result = run_logged_command(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def build_video_filter(
    *,
    project: dict[str, Any],
    shots: dict[str, dict[str, Any]],
    runtime: PipelineRuntime,
    timeline_offsets: dict[str, float],
) -> tuple[list[str], str, str]:
    spec = project["pipeline_spec"]
    width, height = spec["resolution"]
    video_inputs: list[str] = []
    filter_parts: list[str] = []
    prepared_labels: list[str] = []
    for index, shot_id in enumerate(project["shot_order"]):
        pattern = detect_sequence_pattern(runtime.project_root / "Outputs/Renders" / shot_id)
        video_inputs.extend(["-framerate", str(spec["fps"]), "-start_number", "1", "-i", pattern])
        label = f"v{index}"
        filter_parts.append(
            f"[{index}:v]setpts=PTS-STARTPTS,scale={width}:{height},format=yuv420p[{label}]"
        )
        prepared_labels.append(label)

    if len(prepared_labels) == 1:
        return video_inputs, ";".join(filter_parts), f"[{prepared_labels[0]}]"

    current = prepared_labels[0]
    xfade_index = 1
    for shot_index, shot_id in enumerate(project["shot_order"][:-1], start=1):
        transition = shots[shot_id]["render_spec"]["transition_out"] or {
            "type": "fade",
            "frames": 0,
        }
        next_label = prepared_labels[shot_index]
        out_label = f"vx{xfade_index}"
        transition_type = "fade" if transition["type"] == "cut" else transition["type"]
        offset_sec = timeline_offsets[project["shot_order"][shot_index]]
        duration_sec = transition.get("frames", 0) / spec["fps"]
        if transition.get("frames", 0) <= 0:
            filter_parts.append(
                f"[{current}][{next_label}]concat=n=2:v=1:a=0[{out_label}]"
            )
        else:
            filter_parts.append(
                f"[{current}][{next_label}]xfade=transition={transition_type}:"
                f"duration={duration_sec}:offset={offset_sec}[{out_label}]"
            )
        current = out_label
        xfade_index += 1
    return video_inputs, ";".join(filter_parts), f"[{current}]"


def build_audio_mix_filter(
    *,
    project: dict[str, Any],
    runtime: PipelineRuntime,
    dialogue_bus: Path,
    sfx_bus: Path | None,
    total_duration: float,
) -> tuple[list[str], str, str]:
    spec = project["pipeline_spec"]
    inputs = ["-i", str(dialogue_bus)]
    filter_parts = ["[0:a]anull[dial]"]
    mix_labels = ["[dial]"]
    next_index = 1

    if sfx_bus and sfx_bus.exists():
        inputs.extend(["-i", str(sfx_bus)])
        filter_parts.append(f"[{next_index}:a]anull[sfx]")
        mix_labels.append("[sfx]")
        next_index += 1

    global_audio = project.get("global_audio", {})
    bgm = global_audio.get("bgm")
    if bgm and bgm.get("path"):
        bgm_index = next_index
        inputs.extend(["-stream_loop", "-1", "-i", str(resolve_project_path(runtime.project_root, bgm["path"]))])
        duck_threshold = spec["ducking_params"]["threshold"]
        duck_ratio = spec["ducking_params"]["ratio"]
        duck_attack = spec["ducking_params"]["attack"]
        duck_release = spec["ducking_params"]["release"]
        duck_knee = spec["ducking_params"]["knee"]
        fade_out_sec = bgm.get("fade_out_sec", 0.0)
        fade_out_start = max(total_duration - fade_out_sec, 0.0)
        filter_parts.append(
            f"[{bgm_index}:a]atrim=duration={total_duration},"
            f"volume={db_to_volume(bgm.get('gain_db', 0.0))},"
            f"afade=t=in:st=0:d={bgm.get('fade_in_sec', 0.0)},"
            f"afade=t=out:st={fade_out_start}:d={fade_out_sec}[bgmraw]"
        )
        if bgm.get("ducking", False):
            filter_parts.append(
                "[bgmraw][dial]sidechaincompress="
                f"threshold={duck_threshold}:ratio={duck_ratio}:attack={duck_attack}:"
                f"release={duck_release}:knee={duck_knee}[bgm]"
            )
        else:
            filter_parts.append("[bgmraw]anull[bgm]")
        mix_labels.append("[bgm]")
        next_index += 1

    ambience = global_audio.get("ambience")
    if ambience and ambience.get("path"):
        ambience_index = next_index
        inputs.extend(
            ["-stream_loop", "-1", "-i", str(resolve_project_path(runtime.project_root, ambience["path"]))]
        )
        filter_parts.append(
            f"[{ambience_index}:a]atrim=duration={total_duration},"
            f"volume={db_to_volume(ambience.get('gain_db', 0.0))}[amb]"
        )
        mix_labels.append("[amb]")

    filter_parts.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:normalize=0,aresample={spec['audio_sample_rate']}[aout]"
    )
    return inputs, ";".join(filter_parts), "[aout]"


def compute_total_frames(shot: dict[str, Any], fps: int) -> int:
    ends = [
        dialogue["start_offset"] + dialogue["audio_duration"]
        for dialogue in shot.get("dialogue", [])
        if dialogue.get("audio_duration") is not None
    ]
    ends += [sfx["start_offset"] + sfx["duration"] for sfx in shot.get("sfx", [])]
    max_end = max(ends) if ends else 0.0
    trans = shot["render_spec"]["transition_out"] or {}
    return (
        math.ceil(max_end * fps)
        + shot["camera"]["tail_frames"]
        + int(trans.get("frames", 0))
    )


def validate_dialogue_audio(
    audio_path: Path,
    text: str,
    qc_spec: dict[str, Any],
) -> dict[str, float]:
    metrics = read_wav_pcm_metrics(audio_path)
    rms_min, rms_max = qc_spec["rms_db_range"]
    if not (rms_min <= metrics["rms_db"] <= rms_max):
        raise_rejected_audio(
            f"RMS out of range: {metrics['rms_db']:.2f}dB not in [{rms_min}, {rms_max}]"
        )
    if metrics["silence_ratio"] > qc_spec["max_silence_ratio"]:
        raise_rejected_audio(
            f"silence ratio too high: {metrics['silence_ratio']:.3f} > {qc_spec['max_silence_ratio']}"
        )
    char_count = len("".join(text.split()))
    if char_count <= 0:
        raise_rejected_audio("dialogue text has no visible characters")
    ratio = metrics["duration_sec"] / char_count
    ratio_min, ratio_max = qc_spec["duration_per_char_range"]
    if not (ratio_min <= ratio <= ratio_max):
        raise_rejected_audio(
            f"duration per char out of range: {ratio:.3f} not in [{ratio_min}, {ratio_max}]"
        )
    return metrics


def validate_and_update_sfx_durations(shot: dict[str, Any], runtime: PipelineRuntime) -> None:
    for sfx in shot.get("sfx", []):
        sfx_abs = resolve_project_path(runtime.project_root, sfx["path"])
        actual_duration = ffprobe_duration_seconds(sfx_abs, ffprobe_bin=runtime.ffprobe_bin)
        if abs(actual_duration - sfx["duration"]) > 0.1:
            sfx["duration"] = actual_duration


def to_absolute_alignment(
    relative_payload: dict[str, Any],
    start_offset: float,
) -> list[dict[str, Any]]:
    words = extract_word_segments(relative_payload)
    absolute_words = []
    for word in words:
        absolute_words.append(
            {
                "word": word["word"],
                "abs_start": start_offset + float(word["start"]),
                "abs_end": start_offset + float(word["end"]),
                "score": float(word.get("score", 0.0)),
            }
        )
    return absolute_words


def extract_word_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "word_segments" in payload:
        return list(payload["word_segments"])
    words: list[dict[str, Any]] = []
    for segment in payload.get("segments", []):
        words.extend(segment.get("words", []))
    if not words:
        raise RuntimeError("WhisperX payload does not contain word-level alignment")
    return words


def mark_stage_for_rework(shot: dict[str, Any], stage: str, reason: str) -> None:
    st = shot["stage_status"][stage]
    st["state"] = "failed"
    st["retry"] += 1
    st["last_error"] = reason
    if st["retry"] >= 3:
        raise RuntimeError(f"{shot['shot_id']}/{stage} retry exceeded during lock validation")


def unlock_frames(shot: dict[str, Any]) -> None:
    if shot.get("frames_locked"):
        shot["frames_locked"] = False
        shot["render_spec"]["total_render_frames"] = None


def resample_wav(
    *,
    input_path: Path,
    output_path: Path,
    spec: dict[str, Any],
    ffmpeg_bin: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-ar",
        str(spec["audio_sample_rate"]),
        "-ac",
        str(spec["audio_channels"]),
        "-c:a",
        ffmpeg_pcm_codec(spec["audio_bit_depth"]),
        str(output_path),
    ]
    result = run_logged_command(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def format_template_command(template: str, **kwargs: str) -> list[str]:
    rendered = template.format(**{key: shlex.quote(value) for key, value in kwargs.items()})
    return shlex.split(rendered)


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_") or "asset"


def raise_rejected_audio(message: str) -> None:
    raise RuntimeError(f"audio_rejected: {message}")


def db_to_volume(gain_db: float) -> float:
    return 10 ** (gain_db / 20.0)


def compute_shot_timeline_offsets(
    project: dict[str, Any],
    shots: dict[str, dict[str, Any]],
) -> dict[str, float]:
    fps = project["pipeline_spec"]["fps"]
    offsets: dict[str, float] = {}
    current_frames = 0
    for index, shot_id in enumerate(project["shot_order"]):
        offsets[shot_id] = current_frames / fps
        if index == len(project["shot_order"]) - 1:
            continue
        transition_frames = int(
            (shots[shot_id]["render_spec"]["transition_out"] or {}).get("frames", 0)
        )
        current_frames += shots[shot_id]["render_spec"]["total_render_frames"] - transition_frames
    return offsets


def compute_project_duration_seconds(
    project: dict[str, Any],
    shots: dict[str, dict[str, Any]],
) -> float:
    offsets = compute_shot_timeline_offsets(project, shots)
    last_shot_id = project["shot_order"][-1]
    last_duration = shots[last_shot_id]["render_spec"]["total_render_frames"] / project["pipeline_spec"]["fps"]
    return offsets[last_shot_id] + last_duration


def detect_sequence_pattern(render_dir: Path) -> str:
    if not render_dir.exists():
        raise FileNotFoundError(render_dir)
    files = sorted(path for path in render_dir.iterdir() if path.is_file())
    if not files:
        raise RuntimeError(f"render directory is empty: {render_dir}")
    match = re.match(r"^(.*?)(\d+)(\.[^.]+)$", files[0].name)
    if not match:
        raise RuntimeError(f"cannot derive sequence pattern from {files[0].name}")
    prefix, digits, suffix = match.groups()
    return str(render_dir / f"{prefix}%0{len(digits)}d{suffix}")


def load_project(project_manifest_path: Path | str) -> dict[str, Any]:
    project = load_json(project_manifest_path)
    project["pipeline_spec"]["project_root"] = str(Path(project["pipeline_spec"]["project_root"]).resolve())
    return project


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI anime local pipeline scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("run", help="run the full scheduler")
    init_parser.add_argument("--project-manifest", required=True)
    init_parser.add_argument("--assemble-only", action="store_true")

    shot_parser = sub.add_parser("run-shot", help="run a single shot")
    shot_parser.add_argument("--project-manifest", required=True)
    shot_parser.add_argument("--shot-id", required=True)

    assembly_parser = sub.add_parser("assemble", help="assemble final episode with ffmpeg")
    assembly_parser.add_argument("--project-manifest", required=True)

    args = parser.parse_args(list(argv) if argv is not None else None)
    project = load_project(args.project_manifest)
    runtime = PipelineRuntime.from_project(project)

    if args.command == "run-shot":
        shot_path = runtime.project_root / "Outputs/Shots" / f"{args.shot_id}.json"
        run_shot_pipeline(shot_path, project, runtime)
        return 0

    if args.command == "assemble":
        shots = {
            sid: load_json(runtime.project_root / "Outputs/Shots" / f"{sid}.json")
            for sid in project["shot_order"]
        }
        run_global_ffmpeg_assembly(project, shots, runtime)
        return 0

    if not args.assemble_only:
        for shot_id in project["shot_order"]:
            run_shot_pipeline(runtime.project_root / "Outputs/Shots" / f"{shot_id}.json", project, runtime)
    shots = {
        sid: load_json(runtime.project_root / "Outputs/Shots" / f"{sid}.json")
        for sid in project["shot_order"]
    }
    assert_all_rendered(project, shots)
    run_global_ffmpeg_assembly(project, shots, runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
