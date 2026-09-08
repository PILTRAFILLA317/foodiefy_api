"""Pinned security gates. Reports only rule/package IDs and paths, never secrets."""

import argparse
import hashlib
import io
import json
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen


def download(url):
    with urlopen(url, timeout=60) as response:
        return response.read()


def install(directory, tool):
    os_name = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = "arm64" if platform.machine() in {"arm64", "aarch64"} else "amd64"
    if tool == "gitleaks":
        base = "https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/"
        name = f"gitleaks_8.28.0_{os_name}_{'x64' if arch == 'amd64' else arch}.tar.gz"
        sums = "gitleaks_8.28.0_checksums.txt"
    else:
        base = "https://github.com/google/osv-scanner/releases/download/v2.2.2/"
        name = f"osv-scanner_{os_name}_{arch}"
        sums = "osv-scanner_SHA256SUMS"
    data = download(base + name)
    checks = download(base + sums).decode()
    expected = next(
        line.split()[0] for line in checks.splitlines() if line.endswith(name)
    )
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("scanner_checksum_failed")
    if tool == "gitleaks":
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            data = archive.extractfile("gitleaks").read()
    binary = directory / tool
    binary.write_bytes(data)
    binary.chmod(0o700)
    return str(binary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["secrets", "dependencies"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="foodiefy-security-") as temp:
        temp = Path(temp)
        if args.mode == "secrets":
            binary = install(temp, "gitleaks")
            source = temp / "source"
            source.mkdir()
            files = subprocess.run(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=root,
                capture_output=True,
                check=True,
            ).stdout.split(b"\0")
            for raw in set(files):
                if not raw:
                    continue
                relative = Path(raw.decode())
                path = root / relative
                if not path.is_file() or path.is_symlink():
                    continue
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            report = temp / "report.json"
            result = subprocess.run(
                [
                    binary,
                    "dir",
                    str(source),
                    "--redact=100",
                    "--no-banner",
                    "--report-format=json",
                    f"--report-path={report}",
                ],
                capture_output=True,
            )
            findings = json.loads(report.read_text()) if report.exists() else []
            for finding in findings:
                path = finding["File"].removeprefix(str(source) + "/")
                print(
                    f"SECRET_REVIEW {path}:{finding['StartLine']} rule={finding['RuleID']}"
                )
            if result.returncode not in {0, 1}:
                raise RuntimeError("secret_scan_unavailable")
            print(f"Gitleaks 8.28.0: {len(findings)} findings (content redacted)")
            return result.returncode
        binary = install(temp, "osv-scanner")
        # OSV parses requirements.txt; input is the existing fully pinned lock.
        if (root / "requirements.lock").exists():
            lock = temp / "requirements.txt"
            shutil.copyfile(root / "requirements.lock", lock)
            locks = [lock, root / ".railway/package-lock.json"]
        else:
            locks = [root / "pubspec.lock"]
        report = temp / "osv.json"
        command = [
            binary,
            "scan",
            "source",
            "--format=json",
            f"--output={report}",
            "--no-resolve",
        ]
        for lock in locks:
            command.extend(["--lockfile", str(lock)])
        result = subprocess.run(command, cwd=temp, capture_output=True)
        if result.returncode not in {0, 1} or not report.exists():
            raise RuntimeError("dependency_scan_unavailable")
        data = json.loads(report.read_text())
        count = 0
        for group in data.get("results", []):
            for entry in group.get("packages", []):
                package = entry.get("package", {})
                for vuln in entry.get("vulnerabilities", []):
                    count += 1
                    fixed = sorted(
                        {
                            e["fixed"]
                            for a in vuln.get("affected", [])
                            for r in a.get("ranges", [])
                            for e in r.get("events", [])
                            if "fixed" in e
                        }
                    )
                    print(
                        f"DEPENDENCY_REVIEW {package.get('name')}@{package.get('version')} {vuln['id']} fixed={','.join(fixed) or 'review-advisory'}"
                    )
        print(f"OSV Scanner 2.2.2: {count} advisories")
        return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(
            "Security gate unavailable; no PASS claimed. Retry with scanner registry/OSV access."
        ) from None
