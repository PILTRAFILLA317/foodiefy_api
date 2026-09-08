import json
from fractions import Fraction

from src.acquisition.jobs import job_directory, run_worker
from src.acquisition.models import Limits

from .models import PipelineError


def jpeg_size(raw):
    if raw[:2] != b"\xff\xd8":
        raise PipelineError("invalid_visual_mime")
    cursor = 2
    while cursor + 8 < len(raw):
        if raw[cursor] != 0xff:
            break
        marker = raw[cursor + 1]
        length = int.from_bytes(raw[cursor + 2:cursor + 4], "big")
        if length < 2 or cursor + length + 2 > len(raw):
            break
        if marker in {0xc0, 0xc1, 0xc2}:
            return int.from_bytes(raw[cursor + 7:cursor + 9], "big"), int.from_bytes(raw[cursor + 5:cursor + 7], "big")
        cursor += length + 2
    raise PipelineError("invalid_visual_mime")


def validate_visual(evidence):
    if not evidence.paths or sum(p.stat().st_size for p in evidence.paths) > 12_000_000:
        raise PipelineError("visual_inline_size_limit")
    if evidence.variant == "frames":
        if len(evidence.timestamps) != len(evidence.paths) or any(not 0 <= t < evidence.duration_seconds for t in evidence.timestamps):
            raise PipelineError("invalid_frame_timestamps")
        for path in evidence.paths:
            width, height = jpeg_size(path.read_bytes())
            if not 0 < width <= 512 or not 0 < height <= 512:
                raise PipelineError("visual_resolution_limit")
        return evidence.duration_seconds
    with job_directory() as job:
        (job / "input.bin").write_bytes(evidence.paths[0].read_bytes())
        run_worker("probe_visual", {}, job, Limits(), sandbox=True)
        info = json.loads((job / "result.json").read_text())
    if "error" in info:
        raise PipelineError(info["error"])
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    if len(video) != 1 or any(s.get("codec_type") == "audio" for s in streams):
        raise PipelineError("visual_video_must_be_silent")
    stream = video[0]
    duration = float(info.get("format", {}).get("duration", 0))
    if not 0 < duration <= 300 or not 0 < stream.get("width", 0) <= 512 or not 0 < stream.get("height", 0) <= 512:
        raise PipelineError("visual_resolution_or_duration_limit")
    if not 0 < Fraction(stream.get("r_frame_rate", "0")) <= 1:
        raise PipelineError("visual_frame_rate_limit")
    return duration
