"""yt-dlp metadata in a network-denied process; every HTTP request is brokered."""
import base64
import html
import io
import json
import os
import re
import selectors
import socket
import subprocess
import sys
import time
from pathlib import Path

from .jobs import (
    ROOT,
    job_directory,
    minimal_env,
    run_worker,
    sandbox_command,
    stop_process,
)
from .models import AcquisitionError, EvidenceBundle, Limits
from .network import SafeFetcher, public_url
from .parsing import fragment, string


def verify_sandbox(job, limits):
    # A listening socket distinguishes an enforced deny from connection refusal.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        run_worker("sandbox_probe", {"port": listener.getsockname()[1]}, job, limits, sandbox=True)
    if json.loads((job / "result.json").read_text()) != {"network_denied": True}:
        raise AcquisitionError("extractor_network_isolation_unavailable")


def extract_metadata(url: str, limits: Limits, *, environment="production", allow_local=False, media_kind=None):
    if environment != "local" or not allow_local:
        raise AcquisitionError("social_extractor_disabled")
    with job_directory() as job:
        verify_sandbox(job, limits)
        command = sandbox_command([sys.executable, "-m", "src.acquisition.worker", "social", str(job),
                                   str(limits.media_bytes), str(int(limits.stage_seconds) + 1)])
        (job / "request.json").write_text(json.dumps({"url": url, "timeout": limits.stage_seconds, "media_kind": media_kind}))
        deadline = time.monotonic() + limits.stage_seconds
        with subprocess.Popen(command, cwd=ROOT, env=minimal_env(job), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True) as process:
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    buffer = b""
                    requests = 0
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise AcquisitionError("stage_timeout")
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise AcquisitionError("social_extraction_failed")
                        buffer += chunk
                        if len(buffer) > 131072:
                            raise AcquisitionError("extractor_request_too_large")
                        if b"\n" not in buffer:
                            continue
                        line, buffer = buffer.split(b"\n", 1)
                        message = json.loads(line)
                        if message.get("event") == "done":
                            process.wait(timeout=max(.01, deadline - time.monotonic()))
                            if process.returncode:
                                raise AcquisitionError("social_extraction_failed")
                            result = json.loads((job / "metadata.json").read_text())
                            if "error" in result:
                                raise AcquisitionError(result["error"])
                            return result
                        requests += 1
                        if message.get("event") != "fetch" or requests > 30:
                            raise AcquisitionError("extractor_request_limit")
                        try:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise AcquisitionError("stage_timeout")
                            fetcher = SafeFetcher(limits.model_copy(update={"stage_seconds": remaining}))
                            result = fetcher.fetch(message["url"], method=message["method"], headers=message["headers"],
                                                   data=base64.b64decode(message["data"]) if message["data"] else None)
                            (job / "reply.bin").write_bytes(result.body)
                            reply = {"url": result.url, "headers": result.headers, "status": result.status}
                        except AcquisitionError as exc:
                            reply = {"error": exc.code}
                        (job / "reply.json").write_text(json.dumps(reply))
                        process.stdin.write(b"ready\n")
                        process.stdin.flush()
            except subprocess.TimeoutExpired:
                raise AcquisitionError("stage_timeout") from None
            finally:
                stop_process(process)


def worker_extract(job: Path):
    # Imported only in the sandboxed worker, never on FastAPI startup.
    from yt_dlp import YoutubeDL
    from yt_dlp.networking.common import RequestHandler, Response
    from yt_dlp.networking.exceptions import HTTPError, TransportError

    class BrokerRH(RequestHandler):
        _SUPPORTED_URL_SCHEMES = ("http", "https")
        _SUPPORTED_PROXY_SCHEMES = ()

        def _send(self, request):
            data = request.data
            if data is not None and not isinstance(data, bytes):
                raise TransportError("request_not_allowed")
            message = {"event": "fetch", "url": request.url, "method": request.method,
                       "headers": dict(self.headers) | dict(request.headers),
                       "data": base64.b64encode(data).decode() if data else None}
            print(json.dumps(message), flush=True)
            if sys.stdin.readline() != "ready\n":
                raise TransportError("broker_unavailable")
            result = json.loads((job / "reply.json").read_text())
            if "error" in result:
                raise TransportError(result["error"])
            response = Response(io.BytesIO((job / "reply.bin").read_bytes()), **result)
            if response.status >= 400:
                raise HTTPError(response)
            return response

    class BrokerDL(YoutubeDL):
        def build_request_director(self, handlers, preferences=None):
            return super().build_request_director([BrokerRH])

    class QuietLogger:
        def debug(self, *args): pass
        def warning(self, *args): pass
        def error(self, *args): pass

    request = json.loads((job / "request.json").read_text())
    options = {"skip_download": True, "noplaylist": True, "quiet": True, "no_warnings": True,
               "logger": QuietLogger(), "cachedir": False, "socket_timeout": request["timeout"],
               "retries": 0, "extractor_retries": 0, "writesubtitles": False,
               "writeautomaticsub": False, "nocheckcertificate": False, "proxy": "",
               "js_runtimes": {}, "remote_components": set()}
    try:
        with BrokerDL(options) as ydl:
            info = ydl.extract_info(request["url"], download=False)
            if not info or info.get("_type") in {"playlist", "multi_video"}:
                raise AcquisitionError("single_video_required")
            # Normal resolve exports no playback URL. Explicit media selection is private IPC only.
            keys = ("id", "title", "description", "uploader", "channel", "thumbnail", "duration", "language", "subtitles", "automatic_captions")
            result = {key: info.get(key) for key in keys}
            if request.get("media_kind"):
                result["selected_media_url"] = select_direct_media(info.get("formats", []), request["media_kind"])
    except AcquisitionError as exc:
        result = {"error": exc.code}
    except Exception:
        result = {"error": "social_extraction_failed"}
    (job / "metadata.json").write_text(json.dumps(result))
    print('{"event":"done"}', flush=True)


def select_direct_media(formats, kind):
    candidates = [f for f in formats if f.get("protocol") in {"http", "https"} and f.get("url")
                  and (f.get("filesize") or f.get("filesize_approx") or 0) <= 50 * 1024**2]
    if kind == "audio":
        candidates = [f for f in candidates if f.get("acodec") not in {None, "none"}
                      and (f.get("vcodec") == "none" or 0 < (f.get("height") or 0) <= 720)]
        candidates.sort(key=lambda f: (f.get("vcodec") != "none", f.get("abr") or f.get("tbr") or 9999))
    elif kind == "video":
        candidates = [f for f in candidates if f.get("vcodec") not in {None, "none"} and 0 < (f.get("height") or 0) <= 720]
        candidates.sort(key=lambda f: (-(f.get("height") or 0), f.get("tbr") or 9999))
    else:
        raise AcquisitionError("unsupported_media_kind")
    if not candidates:
        raise AcquisitionError("direct_media_unavailable")
    return candidates[0]["url"]


def subtitle_fragment(body, extension, kind, language):
    raw = body.decode("utf-8-sig", errors="strict")
    if extension == "json3":
        data = json.loads(raw)
        lines = ["".join(s.get("utf8", "") for s in event.get("segs", [])) for event in data.get("events", [])]
    elif extension in {"vtt", "srt"}:
        if "-->" not in raw:
            raise AcquisitionError("invalid_subtitle_format")
        def strip_tags(line):
            # Bounded linear scan, including malformed captions with many '<' characters.
            parts = line.split("<")
            return html.unescape(parts[0] + "".join(part.split(">", 1)[1] if ">" in part else "<" + part
                                                   for part in parts[1:])).strip()
        lines = [strip_tags(line) for line in raw.splitlines()
                 if line.strip() and not re.search(r"-->|^WEBVTT|^Kind:|^Language:|^\d+$", line)]
    else:
        raise AcquisitionError("unsupported_subtitle_format")
    result = fragment(kind, "\n".join(lines), language)
    result.raw_text, result.format = raw, extension
    return result


def populate_social(bundle: EvidenceBundle, metadata: dict, fetcher: SafeFetcher, limits: Limits):
    bundle.source_id = string(metadata.get("id"))
    bundle.title = string(metadata.get("title"))
    description = metadata.get("description")
    bundle.description = fragment("description", description) if isinstance(description, str) else None
    if bundle.description is None:
        bundle.warnings.append("description_unavailable")
    bundle.author = string(metadata.get("uploader")) or string(metadata.get("channel"))
    bundle.thumbnail = public_url(metadata.get("thumbnail"))
    duration = metadata.get("duration")
    if isinstance(duration, (int, float)) and 0 <= duration < float("inf"):
        bundle.duration_seconds = duration
    bundle.language = string(metadata.get("language"))
    bundle.language_basis = "source" if bundle.language else None
    if bundle.duration_seconds and bundle.duration_seconds > limits.duration_seconds:
        bundle.status = "partial"
        bundle.warnings.append("duration_limit_subtitles_skipped")
        return
    for source, kind in (("subtitles", "manual_subtitles"), ("automatic_captions", "auto_subtitles")):
        start = time.monotonic()
        tracks = metadata.get(source) or {}
        if not isinstance(tracks, dict):
            bundle.warnings.append(kind + "_invalid")
            continue
        languages = sorted(tracks, key=lambda lang: (lang != bundle.language, lang))
        if not languages:
            bundle.warnings.append(kind + "_unavailable")
        if len(languages) > limits.subtitle_tracks:
            bundle.warnings.append(kind + "_track_limit")
            bundle.status = "partial"
        for language in languages[:limits.subtitle_tracks]:
            options = tracks[language]
            selected = next((entry for ext in ("vtt", "srt", "json3") for entry in options
                             if entry.get("ext") == ext and entry.get("url")), None)
            if not selected:
                bundle.warnings.append(kind + "_format_unavailable")
                bundle.status = "partial"
                continue
            try:
                if time.monotonic() - start >= limits.stage_seconds:
                    raise AcquisitionError("stage_timeout")
                result = fetcher.fetch(selected["url"], timeout_seconds=limits.stage_seconds - (time.monotonic() - start))
                if result.status != 200:
                    raise AcquisitionError("subtitle_http_error")
                part = subtitle_fragment(result.body, selected["ext"], kind, language)
                getattr(bundle, kind).append(part)
                if bundle.language is None and language != "und":
                    bundle.language, bundle.language_basis = language, "subtitles"
            except (AcquisitionError, ValueError, UnicodeError, TypeError):
                bundle.status = "partial"
                bundle.warnings.append(kind + "_acquisition_failed")
        bundle.timings_ms[kind] = round((time.monotonic() - start) * 1000, 3)
