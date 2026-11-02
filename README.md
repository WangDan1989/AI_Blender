# AI Anime Pipeline

本仓库实现了一个面向本地工作站的 AI 漫剧生产线骨架，覆盖：

- `init_project`：从 Qwen 结构化输出初始化项目级与镜头级 manifest
- `scheduler`：按 `assets -> clean -> audio -> align -> lock -> render` 串行执行
- `clean_asset.py`：Blender 后台清洗脚本
- `run_global_ffmpeg_assembly`：全局音视频拼接、对白总线、BGM ducking、xfade
- `render.done`：渲染产物完整性哨兵
- `mock_*`：本地无大模型时的 dry-run 适配脚本

## 目录

- `src/ai_anime_pipeline/`：主项目代码
- `scripts/clean_asset.py`：Blender 后台清洗脚本
- `scripts/ue_mrq_render_job.py`：UE5 Movie Render Queue 作业脚本
- `scripts/ue_write_done_callback.py`：UE5 `.done` 哨兵写入辅助
- `scripts/mock_*.py`：CosyVoice / WhisperX / Hunyuan3D / Unreal mock 适配
- `scripts/bootstrap_env.ps1`：Windows 环境自举脚本
- `scripts/check_env.py`：环境体检脚本
- `examples/qwen_structured_output.json`：初始化样例
- `examples/mock_env.sh`：mock 环境变量模板
- `config/tools.json`：本地工具与模型环境配置

## 安装

```bash
cd /workspace
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

## 初始化项目

```bash
python /workspace/scripts/bootstrap_mock_project.py --source /workspace/examples/qwen_structured_output.json
python -m ai_anime_pipeline.cli init --source /workspace/examples/qwen_structured_output.json
```

初始化后会在 `pipeline_spec.project_root` 下生成：

- `project_manifest.json`
- `Outputs/Shots/shot_001.json`
- `Outputs/Shots/shot_002.json`

## 真机运行前需要的环境变量

- `AI_ANIME_HUNYUAN3D_CMD_TEMPLATE`
- `AI_ANIME_COSYVOICE_CMD_TEMPLATE`
- `AI_ANIME_WHISPERX_CMD_TEMPLATE`
- `AI_ANIME_UNREAL_CMD_TEMPLATE`
- 可选：`AI_ANIME_BLENDER_BIN`、`AI_ANIME_FFMPEG_BIN`、`AI_ANIME_FFPROBE_BIN`

命令模板使用 Python `str.format()` 占位符。

### 资产生成模板

可用占位符：

- `{prompt}`
- `{negative_prompt}`
- `{ref_image}`
- `{output}`
- `{seed}`
- `{asset_name}`
- `{shot_id}`

### 音频生成模板

可用占位符：

- `{text}`
- `{ref_audio}`
- `{ref_text}`
- `{output}`
- `{role}`
- `{shot_id}`
- `{dialogue_index}`

### 对齐模板

可用占位符：

- `{audio}`
- `{output}`
- `{text}`
- `{role}`
- `{shot_id}`
- `{dialogue_index}`

### UE 渲染模板

可用占位符：

- `{shot_id}`
- `{shot_manifest}`
- `{project_manifest}`
- `{output_dir}`
- `{done_file}`
- `{total_frames}`
- `{warmup_frames}`

## 环境自举

除 UE5 外，仓库现在提供了脚本化环境配置入口：

- 配置文件：[tools.json](file:///workspace/config/tools.json)
- 模板文件：[.env.template](file:///workspace/.env.template)
- Windows 自举脚本：[bootstrap_env.ps1](file:///workspace/scripts/bootstrap_env.ps1)
- 环境体检脚本：[check_env.py](file:///workspace/scripts/check_env.py)

推荐流程：

```powershell
pwsh -File .\scripts\bootstrap_env.ps1
python .\scripts\check_env.py --config .\config\tools.json
```

说明：

- `ffmpeg`、`blender`、`git`、`micromamba` 走 `winget`。
- `CosyVoice`、`WhisperX`、`Hunyuan3D` 走 `git clone + micromamba env + .env 命令模板`。
- `UE5` 仍然保留手动安装，只做命令模板检测，不做登录安装。
- `config/tools.json` 里的 `repo_url` 需要替换成你实际使用的仓库地址。

## Mock Dry Run

`mock_*` 脚本用于在没有真实模型时打通 orchestration 层。它们不替代真实产线，只用于验证：

- 状态机
- 路径解析
- 原子写盘
- `.done` 哨兵
- FFmpeg filtergraph 组装

使用方式：

```bash
source /workspace/examples/mock_env.sh
python /workspace/scripts/bootstrap_mock_project.py --source /workspace/examples/qwen_structured_output.json
python -m ai_anime_pipeline.cli init --source /workspace/examples/qwen_structured_output.json
python -m ai_anime_pipeline.cli scheduler run-shot --project-manifest /workspace/examples/mock_project/project_manifest.json --shot-id shot_001
```

说明：

- `mock_hunyuan3d.py` 只生成占位 `.glb` 字节流，不能替代真实 Hunyuan3D 几何体。
- 若要完整跑 `clean` stage，仍需提供真实可导入的 `.glb` 资产和 Blender。

## UE5 接入说明

推荐将渲染命令模板指向 UE5 命令行，并在 UE 侧调用：

- `scripts/ue_mrq_render_job.py`
- `scripts/ue_write_done_callback.py`

这样可以保证：

- 每个 shot 独立进程渲染
- warm-up 帧不写输出
- 仅以 `.render.done` 作为渲染成功依据

## 测试

```bash
python -m pytest -q
python -m compileall src scripts
```
