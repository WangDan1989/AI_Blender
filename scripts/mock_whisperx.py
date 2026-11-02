from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock WhisperX word alignment")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    audio_path = Path(args.audio)
    with wave.open(str(audio_path), "rb") as handle:
        duration = handle.getnframes() / handle.getframerate()

    words = [word for word in args.text.replace("。", " ").replace("，", " ").split() if word]
    if not words:
        words = list(args.text.strip()) or ["..."]

    step = duration / len(words)
    payload = {
        "segments": [
            {
                "start": 0.0,
                "end": duration,
                "text": args.text,
                "words": [
                    {
                        "word": word,
                        "start": round(index * step, 4),
                        "end": round((index + 1) * step, 4),
                        "score": 0.99,
                    }
                    for index, word in enumerate(words)
                ],
            }
        ]
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
