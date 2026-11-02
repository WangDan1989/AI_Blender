from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def load_config(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def expand_candidate(candidate: str) -> str:
    return os.path.expandvars(candidate.replace("%USERPROFILE%", os.environ.get("USERPROFILE", "")))


def find_binary(candidates: list[str], env_var: str | None = None) -> str | None:
    if env_var and os.environ.get(env_var):
        env_path = os.environ[env_var]
        if Path(env_path).exists():
            return env_path
    for candidate in candidates:
        expanded = expand_candidate(candidate)
        if expanded and Path(expanded).exists():
            return expanded
    for candidate in candidates:
        leaf = Path(candidate).name
        if not leaf:
            continue
        resolved = shutil.which(leaf)
        if resolved:
            return resolved
    return None


def check_system_tool(name: str, payload: dict[str, Any]) -> CheckResult:
    binary = find_binary(payload.get("binary_candidates", []), payload.get("env_var"))
    if binary:
        return CheckResult(name=name, ok=True, detail=binary)
    installer = payload.get("installer", {})
    installer_hint = f"{installer.get('type', 'manual')}:{installer.get('id', 'unknown')}"
    return CheckResult(name=name, ok=False, detail=f"missing, install via {installer_hint}")


def check_model_tool(name: str, payload: dict[str, Any], config: dict[str, Any]) -> CheckResult:
    env_value = os.environ.get(payload["env_var"], "")
    env_root = Path(config["paths"]["envs_root"]) / payload["env_name"]
    repo_root = Path(config["paths"]["third_party_root"]) / name
    parts = []
    if env_root.exists():
        parts.append(f"env={env_root}")
    else:
        parts.append(f"env missing: {env_root}")
    if repo_root.exists():
        parts.append(f"repo={repo_root}")
    else:
        parts.append(f"repo missing: {repo_root}")
    if env_value:
        parts.append("cmd_template=present")
    else:
        parts.append("cmd_template=missing")
    ok = env_root.exists() and repo_root.exists() and bool(env_value)
    return CheckResult(name=name, ok=ok, detail=", ".join(parts))


def run_checks(config: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    tools = config["tools"]
    for name in ("ffmpeg", "ffprobe", "blender", "git", "micromamba"):
        results.append(check_system_tool(name, tools[name]))
    for name in ("cosyvoice", "whisperx", "hunyuan3d"):
        results.append(check_model_tool(name, tools[name], config))
    unreal = os.environ.get("AI_ANIME_UNREAL_CMD_TEMPLATE")
    results.append(
        CheckResult(
            name="ue5",
            ok=bool(unreal),
            detail="manual setup required" if not unreal else "cmd_template=present",
        )
    )
    return results


def render_text(results: list[CheckResult]) -> str:
    lines = []
    for item in results:
        status = "OK" if item.ok else "MISSING"
        lines.append(f"{status:7} {item.name:12} {item.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local AI anime pipeline environment")
    parser.add_argument("--config", default="/workspace/config/tools.json")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    results = run_checks(config)
    if args.json_output:
        print(
            json.dumps(
                [asdict(item) for item in results],
                ensure_ascii=True,
                indent=2,
            )
        )
    else:
        print(render_text(results))
    return 0 if all(item.ok or item.name == "ue5" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
