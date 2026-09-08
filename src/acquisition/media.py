"""Explicit future-phase helper. SourceResolver never calls this module."""
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

from .jobs import job_directory, run_worker
from .models import AcquisitionError, Limits, MediaReference
from .network import SafeFetcher


@contextmanager
def acquire_audio(url: str, limits: Limits | None = None):
    """Caller owns this lifetime. References expire at context exit, including failures."""
    limits = limits or Limits()
    with job_directory() as job:
        # Verify the OS boundary before spending bandwidth; unsupported hosts fail closed.
        from .social import verify_sandbox
        verify_sandbox(job, limits)
        result = SafeFetcher(limits).fetch(url, max_bytes=limits.media_bytes)
        if result.status != 200:
            raise AcquisitionError("media_http_error")
        (job / "input.bin").write_bytes(result.body)
        run_worker("media", {"limits": limits.model_dump()}, job, limits, sandbox=True)
        output = json.loads((job / "result.json").read_text())
        if "error" in output:
            raise AcquisitionError(output["error"])
        yield job, [MediaReference(**reference) for reference in output["media"]]


def worker_audio(payload: dict, job: Path):
    limits = Limits(**payload["limits"])
    ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise AcquisitionError("ffmpeg_unavailable")
    restriction = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,mp3,wav,aac,ogg,matroska,webm"]
    result = subprocess.run([ffprobe, "-v", "error", *restriction, "-show_entries",
                             "format=duration,format_name:stream=codec_type", "-of", "json", str(job / "input.bin")],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=limits.stage_seconds, check=True)
    info = json.loads(result.stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    if not 0 < duration <= limits.duration_seconds:
        raise AcquisitionError("media_duration_limit_or_unknown")
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise AcquisitionError("media_has_no_audio")
    output = job / "audio.mp3"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", *restriction, "-i", str(job / "input.bin"),
                    "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-ac", "1", "-ar", "16000",
                    "-c:a", "libmp3lame", "-b:a", "64k", "-threads", "1", "-f", "mp3", str(output)],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=limits.stage_seconds, check=True)
    size = output.stat().st_size
    if not 0 < size <= limits.media_bytes or not output.read_bytes().startswith((b"ID3", b"\xff\xfb", b"\xff\xf3")):
        raise AcquisitionError("invalid_audio_output")
    return {"media": [{"source_kind": "audio", "filename": "audio.mp3", "mime_type": "audio/mpeg",
                       "size_bytes": size, "duration_seconds": duration}]}


@contextmanager
def acquire_visual(url: str, *, variant="frames", limits: Limits | None = None):
    limits = limits or Limits()
    with job_directory() as job:
        from .social import verify_sandbox
        verify_sandbox(job, limits)
        result = SafeFetcher(limits).fetch(url, max_bytes=limits.media_bytes)
        if result.status != 200:
            raise AcquisitionError("media_http_error")
        (job / "input.bin").write_bytes(result.body)
        run_worker("visual", {"limits": limits.model_dump(), "variant": variant}, job, limits, sandbox=True)
        output = json.loads((job / "result.json").read_text())
        if "error" in output:
            raise AcquisitionError(output["error"])
        yield job, output


def worker_visual(payload, job):
    limits = Limits(**payload["limits"])
    ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise AcquisitionError("ffmpeg_unavailable")
    restriction = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm"]
    raw = subprocess.run([ffprobe, "-v", "error", *restriction, "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", str(job / "input.bin")], capture_output=True, check=True, timeout=limits.stage_seconds)
    info = json.loads(raw.stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    if not 0 < duration <= limits.duration_seconds or not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        raise AcquisitionError("invalid_visual_duration_or_stream")
    base = [ffmpeg, "-nostdin", "-v", "error", *restriction]
    scale = "scale=512:512:force_original_aspect_ratio=decrease:force_divisible_by=2"
    timestamps, files = [], []
    if payload["variant"] == "frames":
        for i in range(6):
            timestamp = duration * i / 6
            filename = f"frame-{i}.jpg"
            subprocess.run([*base, "-ss", str(timestamp), "-i", str(job / "input.bin"), "-an", "-frames:v", "1",
                            "-vf", scale, "-q:v", "3", "-threads", "1", "-map_metadata", "-1", str(job / filename)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=limits.stage_seconds)
            files.append(filename)
            timestamps.append(timestamp)
    elif payload["variant"] == "video":
        files = ["visual.mp4"]
        subprocess.run([*base, "-i", str(job / "input.bin"), "-an", "-vf", "fps=1," + scale,
                        "-c:v", "libx264", "-crf", "32", "-preset", "fast", "-threads", "1",
                        "-map_metadata", "-1", "-movflags", "+faststart", str(job / files[0])],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=limits.stage_seconds)
    else:
        raise AcquisitionError("unsupported_visual_variant")
    if sum((job / name).stat().st_size for name in files) > 12_000_000:
        raise AcquisitionError("visual_inline_size_limit")
    return {"files": files, "timestamps": timestamps, "duration_seconds": duration}


def worker_probe_visual(job):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise AcquisitionError("ffmpeg_unavailable")
    raw = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov",
                          "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json",
                          str(job / "input.bin")], capture_output=True, check=True, timeout=30)
    return json.loads(raw.stdout)
