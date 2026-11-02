export AI_ANIME_BLENDER_BIN="blender"
export AI_ANIME_FFMPEG_BIN="ffmpeg"
export AI_ANIME_FFPROBE_BIN="ffprobe"

export AI_ANIME_HUNYUAN3D_CMD_TEMPLATE="python /workspace/scripts/mock_hunyuan3d.py --prompt {prompt} --output {output} --ref-image {ref_image} --negative-prompt {negative_prompt} --seed {seed}"
export AI_ANIME_COSYVOICE_CMD_TEMPLATE="python /workspace/scripts/mock_cosyvoice.py --text {text} --ref-audio {ref_audio} --ref-text {ref_text} --output {output}"
export AI_ANIME_WHISPERX_CMD_TEMPLATE="python /workspace/scripts/mock_whisperx.py --audio {audio} --text {text} --output {output}"
export AI_ANIME_UNREAL_CMD_TEMPLATE="python /workspace/scripts/mock_unreal_render.py --shot-id {shot_id} --shot-manifest {shot_manifest} --project-manifest {project_manifest} --output-dir {output_dir} --done-file {done_file} --total-frames {total_frames} --warmup-frames {warmup_frames}"
