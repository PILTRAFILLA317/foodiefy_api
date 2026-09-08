import argparse
import hashlib

from scripts.generate_contracts import CONTRACTS_DIR, canonical_json
from src.analysis.evidence import output_schema
from src.analysis.models import AnalysisResult


def generated_files():
    schema = canonical_json(AnalysisResult.model_json_schema())
    wire = canonical_json(output_schema())
    return {CONTRACTS_DIR / "analysis-result.v1.schema.json": schema,
            CONTRACTS_DIR / "analysis-result.v1.provider-schema.json": wire,
            CONTRACTS_DIR / "analysis-result.v1.manifest.json": canonical_json({
                "schema_version": "1.0", "schema_sha256": hashlib.sha256(schema.encode()).hexdigest(),
                "provider_schema_sha256": hashlib.sha256(wire.encode()).hexdigest()})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in generated_files().items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                print("analysis contract drift:", path.name)
                return 1
        else:
            path.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
