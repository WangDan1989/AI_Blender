from __future__ import annotations

import argparse
import math
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock CosyVoice synthesizer")
    parser.add_argument("--text", required=True)
    parser.add_argument("--ref-audio", required=True)
    parser.add_argument("--ref-text", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    text_len = max(len("".join(args.text.split())), 1)
    duration_sec = min(max(text_len * 0.22, 0.6), 6.0)
    sample_rate = 24000
    total_frames = int(duration_sec * sample_rate)
    amplitude = 9000
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for i in range(total_frames):
            t = i / sample_rate
            env = min(t / 0.05, 1.0) * min((duration_sec - t) / 0.05, 1.0)
            env = max(min(env, 1.0), 0.0)
            value = int(amplitude * env * math.sin(2.0 * math.pi * 220.0 * t))
            frames.extend(value.to_bytes(2, "little", signed=True))
        handle.writeframes(bytes(frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
