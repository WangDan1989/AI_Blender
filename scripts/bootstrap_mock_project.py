from __future__ import annotations

import argparse
import json
import math
import struct
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap mock project assets")
    parser.add_argument("--source", required=True, help="Path to examples/qwen_structured_output.json")
    args = parser.parse_args()

    source = json.loads(Path(args.source).read_text(encoding="utf-8"))
    project_root = Path(source["pipeline_spec"]["project_root"]).resolve()

    write_minimal_glb(project_root / "Assets/Characters/Hero_Master.glb")
    write_tone_wav(project_root / "Assets/Audio/VoiceBank/hero_ref.wav", 1.2, 240.0, 24000)
    write_tone_wav(project_root / "Assets/Audio/BGM/ep01_theme.wav", 8.0, 180.0, 48000, gain=0.12)
    write_tone_wav(project_root / "Assets/Audio/Ambience/room_hum.wav", 8.0, 60.0, 48000, gain=0.04)
    write_tone_wav(project_root / "Assets/Audio/SFX/door_open.wav", 0.8, 420.0, 48000, gain=0.2)
    return 0


def write_tone_wav(
    path: Path,
    duration_sec: float,
    frequency: float,
    sample_rate: int,
    *,
    gain: float = 0.2,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for i in range(total_frames):
            t = i / sample_rate
            value = int(32767 * gain * math.sin(2.0 * math.pi * frequency * t))
            frames.extend(value.to_bytes(2, "little", signed=True))
        handle.writeframes(bytes(frames))


def write_minimal_glb(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    indices = struct.pack("<3H", 0, 1, 2)
    indices_padded = indices + b"\x00\x00"
    positions = struct.pack(
        "<9f",
        -0.5,
        0.0,
        0.0,
        0.5,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
    )
    binary_chunk = indices_padded + positions
    json_dict = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0, "mode": 4}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5123,
                "count": 3,
                "type": "SCALAR",
                "max": [2],
                "min": [0],
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "max": [0.5, 1.0, 0.0],
                "min": [-0.5, 0.0, 0.0],
            },
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(indices), "target": 34963},
            {
                "buffer": 0,
                "byteOffset": len(indices_padded),
                "byteLength": len(positions),
                "target": 34962,
            },
        ],
        "buffers": [{"byteLength": len(binary_chunk)}],
    }
    json_chunk = json.dumps(json_dict, separators=(",", ":")).encode("utf-8")
    json_padding = (4 - len(json_chunk) % 4) % 4
    json_chunk += b" " * json_padding
    bin_padding = (4 - len(binary_chunk) % 4) % 4
    binary_chunk += b"\x00" * bin_padding

    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    glb = bytearray()
    glb.extend(struct.pack("<4sII", b"glTF", 2, total_length))
    glb.extend(struct.pack("<I4s", len(json_chunk), b"JSON"))
    glb.extend(json_chunk)
    glb.extend(struct.pack("<I4s", len(binary_chunk), b"BIN\x00"))
    glb.extend(binary_chunk)
    path.write_bytes(bytes(glb))


if __name__ == "__main__":
    raise SystemExit(main())
