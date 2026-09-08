"""Owner-run post-build container gate. No paid provider or remote download."""
import os
import platform
import shutil
import subprocess
from pathlib import Path

from src.acquisition.jobs import minimal_env, sandbox_command
from src.acquisition.models import AcquisitionError, Limits
from src.acquisition.social import extract_metadata


def main():
    assert platform.system() == "Linux", "Run inside the reviewed Linux image"
    assert os.getuid() != 0, "Non-root required"
    for executable in ["ffmpeg", "ffprobe"]:
        assert shutil.which(executable)
        subprocess.run([executable,"-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    assert set(minimal_env(Path("/tmp"))) == {"PATH","HOME","TMPDIR","LANG","PYTHONPATH"}
    try:
        sandbox_command(["true"])
    except AcquisitionError:
        pass
    else:
        raise AssertionError("Linux network isolation implementation needs a new egress proof")
    try:
        extract_metadata("https://www.youtube.com/watch?v=synthetic",Limits(),environment="staging",allow_local=True)
    except AcquisitionError:
        pass
    else:
        raise AssertionError("Social route must fail closed")
    from src.acquisition.network import validate_url
    for url in ["http://127.0.0.1", "http://169.254.169.254", "http://[::1]"]:
        try:
            validate_url(url)
        except AcquisitionError:
            continue
        raise AssertionError("SSRF address accepted")
    print("PASS: Linux non-root/tools/secret isolation/fail-closed social/SSRF gate; no social support certified")


if __name__ == "__main__":
    main()
