"""Generate the API-owned shopping contract and reproducible Flutter snapshot."""

import argparse
import hashlib
import json
from pathlib import Path

from src.contracts.shopping_v1 import ShoppingOperation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--sync-flutter", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "contracts"
    schema = (
        json.dumps(ShoppingOperation.model_json_schema(), indent=2, sort_keys=True)
        + "\n"
    )
    fixtures = (root / "shopping.v1.fixtures.json").read_text()
    manifest = (
        json.dumps(
            {
                "version": "1.0",
                "fixtures_sha256": hashlib.sha256(fixtures.encode()).hexdigest(),
                "schema_sha256": hashlib.sha256(schema.encode()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    for name, data in [
        ("shopping.v1.schema.json", schema),
        ("shopping.v1.fixtures.json", fixtures),
        ("shopping.v1.manifest.json", manifest),
    ]:
        for directory in [root] + ([args.sync_flutter] if args.sync_flutter else []):
            path = directory / name
            if args.check:
                assert path.read_text() == data, f"Contract drift: {path}"
            else:
                path.write_text(data)


if __name__ == "__main__":
    main()
