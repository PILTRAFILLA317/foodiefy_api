import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .models import AcquisitionError, Limits

ROOT = Path(__file__).resolve().parents[2]


def minimal_env(job: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(job),
            "TMPDIR": str(job), "LANG": "C.UTF-8", "PYTHONPATH": str(ROOT)}


@contextmanager
def job_directory(root: Path | None = None):
    base = root or Path(tempfile.gettempdir()) / "foodiefy-acquisition"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != os.getuid():
        raise AcquisitionError("unsafe_temp_root")
    base.chmod(0o700)
    collect_expired(base)
    path = Path(tempfile.mkdtemp(prefix="job-", dir=base))
    (path / "lease").write_text(str(os.getpid()))
    try:
        yield path
    finally:
        shutil.rmtree(path)


def collect_expired(root: Path, ttl_seconds: int = 3600) -> int:
    removed = 0
    for path in root.glob("job-*"):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            if time.time() - path.stat().st_mtime <= ttl_seconds:
                continue
            try:
                pid = int((path / "lease").read_text())
                os.kill(pid, 0)
                continue  # Never collect a live job, even after TTL.
            except (FileNotFoundError, ProcessLookupError, ValueError):
                pass
            shutil.rmtree(path)
            removed += 1
        except (OSError, PermissionError):
            continue
    return removed


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def run_worker(action: str, payload: dict, job: Path, limits: Limits,
               *, sandbox: bool = False) -> None:
    command = [sys.executable, "-m", "src.acquisition.worker", action,
               str(job), str(limits.media_bytes), str(int(limits.stage_seconds) + 1)]
    if sandbox:
        command = sandbox_command(command)
    with subprocess.Popen(command, cwd=ROOT, env=minimal_env(job), stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=True) as process:
        try:
            process.communicate(json.dumps(payload).encode(), timeout=limits.stage_seconds)
        except subprocess.TimeoutExpired:
            stop_process(process)
            raise AcquisitionError("stage_timeout") from None
        finally:
            stop_process(process)
        if process.returncode:
            raise AcquisitionError("worker_failed")


def sandbox_command(command: list[str]) -> list[str]:
    # No opt-in can bypass this gate on Linux/Windows. Add a tested OS boundary first.
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise AcquisitionError("extractor_network_isolation_unavailable")
    return ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)", *command]
