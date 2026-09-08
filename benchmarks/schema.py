"""Reproducible public manifest/reference schema snapshots; no source fixtures."""
import argparse
import json
from pathlib import Path

from .contracts import Manifest, Reference


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, model in [('manifest', Manifest), ('reference', Reference)]:
        path = Path(__file__).with_name(name + '.v1.schema.json')
        text = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + '\n'
        if args.check:
            if not path.is_file() or path.read_text() != text:
                raise SystemExit('benchmark schema drift')
        else:
            path.write_text(text)


if __name__ == '__main__':
    main()
