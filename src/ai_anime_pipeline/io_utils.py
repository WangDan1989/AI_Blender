from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import time
import wave
from pathlib import Path, PurePosixPath
from typing import Any


GPU_QUERY_CMD = [
    "nvidia-smi",
    "-i",
    "0",
    "--query-gpu=memory.used",
    "--format=csv,noheader,nounits",
]

STAGE_STATES = {"pending", "running", "passed", "failed"}


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json_atomic(path: Path | str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, target)


def compute_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_posix_relative(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    posix = PurePosixPath(path_value)
    if posix.is_absolute():
        raise ValueError(f"path must be relative to project_root: {path_value}")
    normalized = posix.as_posix()
    if normalized.startswith("../") or normalized == "..":
        raise ValueError(f"path escapes project_root: {path_value}")
    return normalized


def resolve_project_path(project_root: Path | str, relative_path: str) -> Path:
    normalized = ensure_posix_relative(relative_path)
    assert normalized is not None
    return Path(project_root).resolve() / Path(normalized)


def ensure_project_directories(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for rel in (
        "Outputs/Shots",
        "Outputs/Cleaned",
        "Outputs/Audio",
        "Outputs/Align",
        "Outputs/Renders",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)


def stage_stub() -> dict[str, Any]:
    return {"state": "pending", "retry": 0, "last_error": None}


def run_logged_command(
    command: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )


def require_command_from_env(env_name: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {env_name}")
    return value


def ffmpeg_pcm_codec(bit_depth: int) -> str:
    mapping = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}
    if bit_depth not in mapping:
        raise ValueError(f"unsupported PCM bit depth: {bit_depth}")
    return mapping[bit_depth]


def ffprobe_duration_seconds(path: Path | str, ffprobe_bin: str = "ffprobe") -> float:
    result = run_logged_command(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return float(result.stdout.strip())


def clear_directory(path: Path | str) -> None:
    target = Path(path)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def read_wav_pcm_metrics(path: Path | str) -> dict[str, float]:
    wav_path = Path(path)
    with wave.open(str(wav_path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        raw = handle.readframes(frame_count)

    if frame_count == 0:
        raise RuntimeError(f"empty wav file: {wav_path}")

    samples = decode_pcm_bytes(raw, sample_width)
    if channels > 1:
        merged = []
        for idx in range(0, len(samples), channels):
            chunk = samples[idx : idx + channels]
            merged.append(sum(chunk) / len(chunk))
        mono_samples = merged
    else:
        mono_samples = samples

    full_scale = float(2 ** (sample_width * 8 - 1))
    normalized = [max(min(sample / full_scale, 1.0), -1.0) for sample in mono_samples]
    squared = [sample * sample for sample in normalized]
    mean_square = sum(squared) / len(squared)
    rms = math.sqrt(mean_square)
    rms_db = -120.0 if rms <= 0 else 20.0 * math.log10(rms)

    window_size = max(int(sample_rate * 0.1), 1)
    silent_windows = 0
    total_windows = 0
    silence_threshold = 0.01
    for offset in range(0, len(normalized), window_size):
        window = normalized[offset : offset + window_size]
        if not window:
            continue
        total_windows += 1
        window_mean = sum(sample * sample for sample in window) / len(window)
        if math.sqrt(window_mean) < silence_threshold:
            silent_windows += 1

    silence_ratio = silent_windows / total_windows if total_windows else 0.0
    duration_sec = frame_count / sample_rate
    return {
        "rms_db": rms_db,
        "silence_ratio": silence_ratio,
        "duration_sec": duration_sec,
        "channels": float(channels),
        "sample_rate": float(sample_rate),
        "sample_width": float(sample_width),
    }


def decode_pcm_bytes(raw: bytes, sample_width: int) -> list[int]:
    if sample_width == 1:
        return [byte - 128 for byte in raw]
    if sample_width == 2:
        return list(struct.unpack("<" + "h" * (len(raw) // 2), raw))
    if sample_width == 3:
        values: list[int] = []
        for idx in range(0, len(raw), 3):
            chunk = raw[idx : idx + 3]
            sign_byte = b"\xff" if chunk[2] & 0x80 else b"\x00"
            values.append(struct.unpack("<i", chunk + sign_byte)[0])
        return values
    if sample_width == 4:
        return list(struct.unpack("<" + "i" * (len(raw) // 4), raw))
    raise ValueError(f"unsupported wav sample width: {sample_width}")


class GpuSentinel:
    def __init__(self, baseline_mb: int) -> None:
        self.baseline_mb = baseline_mb

    @classmethod
    def capture_baseline(cls) -> "GpuSentinel":
        return cls(query_gpu_memory_mb())

    def wait_for_release(self, *, threshold_mb: int = 600, timeout_sec: int = 30) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            current = query_gpu_memory_mb()
            if abs(current - self.baseline_mb) <= threshold_mb:
                return
            time.sleep(1.0)
        current = query_gpu_memory_mb()
        raise RuntimeError(
            "gpu memory did not return to baseline within timeout: "
            f"baseline={self.baseline_mb}MB current={current}MB threshold={threshold_mb}MB"
        )


def query_gpu_memory_mb() -> int:
    result = run_logged_command(GPU_QUERY_CMD)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    value = result.stdout.strip().splitlines()[0]
    return int(value)
