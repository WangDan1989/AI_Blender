from __future__ import annotations

import argparse
import json
from pathlib import Path

import unreal

from ue_write_done_callback import write_render_done_from_output_dir


class RenderCompletionProxy(unreal.MoviePipelinePythonHostExecutor):
    def __init__(self) -> None:
        super().__init__()
        self._done_file = ""
        self._output_dir = ""

    @unreal.ufunction(override=True)
    def execute_delayed(self, in_pipeline_queue):  # type: ignore[override]
        self.on_executor_finished_delegate.add_callable_unique(self._on_complete)
        self.execute(in_pipeline_queue)

    def configure_paths(self, output_dir: str, done_file: str) -> None:
        self._output_dir = output_dir
        self._done_file = done_file

    def _on_complete(self, _executor, _success: bool) -> None:
        write_render_done_from_output_dir(self._output_dir, self._done_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="UE5 MRQ render helper")
    parser.add_argument("--shot-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--done-file", required=True)
    parser.add_argument("--total-frames", required=True, type=int)
    parser.add_argument("--warmup-frames", required=True, type=int)
    parser.add_argument("--queue-asset", required=True)
    parser.add_argument("--level-sequence", required=True)
    args = parser.parse_args()

    shot = json.loads(Path(args.shot_manifest).read_text(encoding="utf-8"))
    subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = subsystem.get_queue()
    queue.delete_all_jobs()
    queue_asset = unreal.load_asset(args.queue_asset)
    preset_job = queue.copy_from(queue_asset)[0]
    preset_job.sequence = unreal.SoftObjectPath(args.level_sequence)
    preset_job.job_name = shot["shot_id"]
    preset_job.get_configuration().find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    ).output_directory = unreal.DirectoryPath(args.output_dir)
    output_setting = preset_job.get_configuration().find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    )
    output_setting.use_custom_playback_range = True
    output_setting.custom_start_frame = 1
    output_setting.custom_end_frame = args.total_frames
    output_setting.handle_frame_count = 0
    output_setting.zero_pad_frame_numbers = 4
    output_setting.output_frame_rate = unreal.FrameRate(numerator=30, denominator=1)
    output_setting.flush_disk_writes_per_shot = True

    anti_aliasing = preset_job.get_configuration().find_or_add_setting_by_class(
        unreal.MoviePipelineAntiAliasingSetting
    )
    anti_aliasing.render_warm_up_count = args.warmup_frames
    anti_aliasing.engine_warm_up_count = args.warmup_frames

    executor = RenderCompletionProxy()
    executor.configure_paths(args.output_dir, args.done_file)
    subsystem.render_queue_with_executor_instance(executor)


if __name__ == "__main__":
    main()
