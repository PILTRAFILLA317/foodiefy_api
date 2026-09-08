import argparse
import hashlib

from scripts.generate_contracts import CONTRACTS_DIR, canonical_json
from src.acquisition.models import EvidenceBundle


def generated_files():
    schema = canonical_json(EvidenceBundle.model_json_schema())
    name = "evidence-bundle.v1.schema.json"
    return {CONTRACTS_DIR / name: schema,
            CONTRACTS_DIR / "evidence-bundle.v1.manifest.json": canonical_json({
                "contract": "evidence-bundle", "schema_version": "1.0", "schema_file": name,
                "schema_sha256": hashlib.sha256(schema.encode()).hexdigest()})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in generated_files().items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                print("evidence contract drift:", path.name)
                return 1
        else:
            path.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
