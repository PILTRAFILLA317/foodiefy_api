"""Same image, explicit web entrypoint; no migrations or worker subprocess."""
import logging
import os

import uvicorn


def main():
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise SystemExit("invalid_port")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run("src.fastapi_app:create_app", factory=True, host="0.0.0.0", port=port, access_log=False)


if __name__ == "__main__":
    main()
