import argparse
import hashlib
import json
import shutil
from pathlib import Path

from src.imports.models import ImportRequest, JobAccepted, JobPage, JobView

ROOT=Path(__file__).resolve().parents[1]


def files():
    document={'contract':'imports','schema_version':'1.0','delivery':'at_least_once',
              'endpoints':{'create':{'method':'POST','path':'/v1/imports','status':202,'required_header':'Idempotency-Key'},
                           'get':{'method':'GET','path':'/v1/imports/{job_id}'},
                           'list':{'method':'GET','path':'/v1/imports','query':['limit','cursor']},
                           'cancel':{'method':'POST','path':'/v1/imports/{job_id}/cancel'}},
              'schemas':{cls.__name__:cls.model_json_schema() for cls in [ImportRequest,JobAccepted,JobView,JobPage]},
              'progress':'stage_only_no_percentage'}
    text=json.dumps(document,sort_keys=True,ensure_ascii=False,indent=2)+'\n'
    manifest=json.dumps({'contract':'imports','schema_version':'1.0','schema_file':'imports.v1.schema.json',
                         'schema_sha256':hashlib.sha256(text.encode()).hexdigest()},sort_keys=True,indent=2)+'\n'
    return {'imports.v1.schema.json':text,'imports.v1.manifest.json':manifest}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--sync-flutter',type=Path)
    args=parser.parse_args()
    for name,text in files().items():
        path=ROOT/'contracts'/name
        if args.check:
            if not path.is_file() or path.read_text()!=text:
                raise SystemExit('imports contract drift')
        else:
            path.write_text(text)
        if args.sync_flutter:
            args.sync_flutter.mkdir(exist_ok=True,parents=True)
            shutil.copy2(path,args.sync_flutter/name)


if __name__=='__main__':
    main()
