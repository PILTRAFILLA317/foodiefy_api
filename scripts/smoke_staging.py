"""Owner-run read-only hosting smoke; never queues work or calls paid providers."""
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    url = os.environ.get("STAGING_API_URL", "").rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SystemExit("Set the reviewed HTTPS STAGING_API_URL without credentials")
    checks = [("/health/live", 200), ("/health/ready", 200), ("/v1/imports", 401)]
    for path, expected in checks:
        request = Request(url+path, headers={"Authorization":"Bearer deliberately-invalid"} if path=="/v1/imports" else {})
        try:
            with urlopen(request, timeout=15) as response:
                status=response.status
        except HTTPError as error:
            status=error.code
        if status != expected:
            raise SystemExit(f"FAIL {path}: HTTP {status}, expected {expected}")
        print(f"PASS {path}: HTTP {status}")


if __name__ == "__main__":
    main()
