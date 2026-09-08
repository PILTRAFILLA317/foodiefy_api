"""Internal bounded subprocess. Never print source content or exception details."""
import base64
import json
import resource
import socket
import sys
from pathlib import Path

from .models import AcquisitionError, Limits


def main():
    action, directory, max_bytes, cpu = sys.argv[1:]
    resource.setrlimit(resource.RLIMIT_CPU, (int(cpu), int(cpu)))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max(int(max_bytes), 16 * 1024**2),) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    job = Path(directory)
    if action == "social":
        from .social import worker_extract
        worker_extract(job)
        return
    payload = json.loads(sys.stdin.buffer.read(131072))
    try:
        if action == "fetch":
            from .network import fetch_pinned
            result = fetch_pinned(payload["url"], Limits(**payload["limits"]), payload["max_bytes"],
                                  method=payload["method"], headers=payload["headers"],
                                  data=base64.b64decode(payload["data"]) if payload["data"] else None)
            (job / "body.bin").write_bytes(result.body)
            output = {"url": result.url, "headers": result.headers, "status": result.status, "wire_bytes": result.wire_bytes}
        elif action == "media":
            from .media import worker_audio
            output = worker_audio(payload, job)
        elif action == "parse_html":
            from .models import EvidenceBundle
            from .parsing import parse_html
            bundle = EvidenceBundle(**payload["bundle"])
            parse_html((job / "html.bin").read_bytes(), bundle)
            output = bundle.model_dump(mode="json")
        elif action == "visual":
            from .media import worker_visual
            output = worker_visual(payload, job)
        elif action == "probe_visual":
            from .media import worker_probe_visual
            output = worker_probe_visual(job)
        elif action == "sandbox_probe":
            try:
                socket.socket().connect(("127.0.0.1", payload["port"]))
            except PermissionError:
                output = {"network_denied": True}
            else:
                output = {"network_denied": False}
        else:
            raise AcquisitionError("unknown_worker")
    except AcquisitionError as exc:
        output = {"error": exc.code}
    except (TimeoutError, socket.timeout):
        output = {"error": "stage_timeout"}
    except Exception:
        output = {"error": "acquisition_failed"}
    (job / "result.json").write_text(json.dumps(output))


if __name__ == "__main__":
    main()
