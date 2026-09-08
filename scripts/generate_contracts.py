from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from src.contracts.recipe_v1 import SCHEMA_VERSION, recipe_draft_json_schema

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"
SCHEMA_NAME = "recipe-draft.v1.schema.json"
MANIFEST_NAME = "recipe-draft.v1.manifest.json"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_files() -> dict[Path, str]:
    schema = recipe_draft_json_schema()
    schema_text = canonical_json(schema)

    fixture_paths = sorted((CONTRACTS_DIR / "fixtures").glob("*.json"))
    fixture_hashes = {
        path.relative_to(CONTRACTS_DIR).as_posix(): sha256(path)
        for path in fixture_paths
    }
    schema_hash = hashlib.sha256(schema_text.encode()).hexdigest()
    manifest = {
        "contract": "recipe-draft",
        "schema_file": SCHEMA_NAME,
        "schema_sha256": schema_hash,
        "schema_version": SCHEMA_VERSION,
        "fixtures": fixture_hashes,
    }
    return {
        CONTRACTS_DIR / SCHEMA_NAME: schema_text,
        CONTRACTS_DIR / MANIFEST_NAME: canonical_json(manifest),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and sync Foodiefy v1 contracts")
    parser.add_argument("--check", action="store_true", help="fail when generated files drift")
    parser.add_argument("--sync-flutter", type=Path, help="copy the snapshot to Flutter")
    args = parser.parse_args()

    files = generated_files()
    if args.check:
        drift = [path for path, text in files.items() if not path.exists() or path.read_text() != text]
        if drift:
            for path in drift:
                print(f"contract drift: {path.relative_to(ROOT)}")
            return 1
    else:
        CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
        for path, text in files.items():
            path.write_text(text)

    if args.sync_flutter:
        target = args.sync_flutter.resolve()
        target.mkdir(parents=True, exist_ok=True)
        (target / "fixtures").mkdir(exist_ok=True)
        for path in files:
            shutil.copy2(path, target / path.name)
        for fixture in sorted((CONTRACTS_DIR / "fixtures").glob("*.json")):
            shutil.copy2(fixture, target / "fixtures" / fixture.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
