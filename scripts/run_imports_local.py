"""Launch against the already running local Supabase; never print its credentials."""
import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('target',choices=['api','worker'])
    args=parser.parse_args()
    try:
        data=json.loads(subprocess.run(['supabase','status','--output','json'],capture_output=True,text=True,check=True).stdout)
    except Exception:
        raise SystemExit('Local Supabase is unavailable') from None
    if urlsplit(data['API_URL']).hostname not in {'127.0.0.1','localhost','::1'} or urlsplit(data['DB_URL']).hostname not in {'127.0.0.1','localhost','::1'}:
        raise SystemExit('Only local loopback Supabase is allowed')
    env=dict(os.environ)
    env.update(APP_ENV='local',IMPORT_DATABASE_URL=data['DB_URL'],SUPABASE_URL=data['API_URL'],
               SUPABASE_JWT_SECRET=data['JWT_SECRET'],IMPORT_ALLOW_PAID='false')
    command=([sys.executable,'-m','uvicorn','src.fastapi_app:app','--host','127.0.0.1','--port','8000','--no-access-log']
             if args.target=='api' else [sys.executable,'-m','src.imports.worker'])
    os.execvpe(command[0],command,env)


if __name__=='__main__':
    main()
