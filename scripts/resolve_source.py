"""Explicit local acquisition probe. Summary on stdout; full evidence only in a private file."""
import argparse
import json
import os
from pathlib import Path

from src.acquisition.models import Limits
from src.acquisition.parsing import context_view
from src.acquisition.resolver import SourceResolver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-local-social", action="store_true", help="macOS only; requires verified OS network deny")
    parser.add_argument("--stage-seconds", type=float, default=30)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--context-chars", type=int, default=24000)
    args = parser.parse_args()
    limits = Limits(stage_seconds=args.stage_seconds, duration_seconds=args.duration_seconds, context_chars=args.context_chars)
    bundle = SourceResolver(limits, environment="local", allow_local_social=args.allow_local_social).resolve(args.url)
    result = {"evidence": bundle.model_dump(mode="json"), "context_data": context_view(bundle, limits.context_chars)}
    # Exclusive creation prevents overwriting an unrelated file/symlink; mode 0600 before any content.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": bundle.status, "platform": bundle.platform, "recipes": len(bundle.recipes),
                      "manual_tracks": len(bundle.manual_subtitles), "auto_tracks": len(bundle.auto_subtitles),
                      "media_count": len(bundle.media), "warnings": bundle.warnings, "timings_ms": bundle.timings_ms}))
    return 0 if bundle.status in {"ok", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
