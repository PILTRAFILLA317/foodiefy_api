"""Manual API client. Access token comes from environment, never argv/stdout."""
import argparse
import json
import os
from urllib.parse import urlsplit

import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['submit','get','list','cancel'])
    parser.add_argument('--api',default='http://127.0.0.1:8000')
    parser.add_argument('--url')
    parser.add_argument('--key')
    parser.add_argument('--job-id')
    parser.add_argument('--cursor')
    args=parser.parse_args()
    token=os.environ.get('FOODIEFY_ACCESS_TOKEN')
    host=urlsplit(args.api)
    if not token or host.username or host.password or not (host.scheme=='https' or host.scheme=='http' and host.hostname in {'localhost','127.0.0.1','::1'}):
        raise SystemExit('Access token and HTTPS API (or local loopback) required')
    if args.action=='submit' and (not args.url or not args.key):
        parser.error('submit requires --url and --key')
    if args.action in {'get','cancel'}:
        from uuid import UUID
        try:
            job=str(UUID(args.job_id))
        except (ValueError,TypeError):
            parser.error('valid --job-id required')
    else:
        job=None
    path='/v1/imports'+('/'+job if job else '')+('/cancel' if args.action=='cancel' else '')
    headers={'Authorization':'Bearer '+token}
    if args.key:
        headers['Idempotency-Key']=args.key
    try:
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=15) as client:
            response=client.request('POST' if args.action in {'submit','cancel'} else 'GET',args.api.rstrip('/')+path,
                                    headers=headers,json={'url':args.url} if args.action=='submit' else None,
                                    params={'cursor':args.cursor} if args.cursor else None)
        data=response.json()
        safe={k:data[k] for k in ['job_id','status','stage','error','next_cursor'] if k in data}
        if 'items' in data:
            safe['items']=[{k:item[k] for k in ['job_id','status','stage','error']} for item in data['items']]
        print(json.dumps({'http_status':response.status_code,**safe}))
        return 0 if response.is_success else 2
    except (httpx.HTTPError,ValueError):
        print('{"error":{"code":"service_unavailable"}}')
        return 2


if __name__=='__main__':
    raise SystemExit(main())
