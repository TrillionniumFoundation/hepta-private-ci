"""Fetch the exact original successful E3 Actions artifact without leaking API token.

A research-only operator manifest frozen in source. No model/label or deployment authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib import error, parse, request

REPO='TrillionniumFoundation/hepta-private-ci'
RUN_ID=38672941350
SOURCE_HEAD='b8b2f10fe38506972301e77e3836729a90200673'
ARTIFACT_ID=11945106672
ARTIFACT_NAME='hepta-e3-granite-dino-actual-or-failure-no-weights-no-media'
ARCHIVE_SHA='7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'
ENDPOINT=f'https://api.github.com/repos/{REPO}'
REDIRECT_DOMAINS=('.githubusercontent.com','.blob.core.windows.net')

class FetchReject(ValueError): pass

def check(test, message):
    if not test:raise FetchReject(message)

def api_json(path, token):
    req=request.Request(ENDPOINT+path,headers={'Authorization':'Bearer '+token,
      'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with request.urlopen(req,timeout=40) as res:
        check(res.status==200,'GitHub source API error')
        raw=res.read(100_000)
        check(len(raw)<100_000,'unbounded GitHub response')
    return json.loads(raw)

def validate(run, artifact):
    check(type(run) is dict and run.get('id')==RUN_ID and
          run.get('head_sha')==SOURCE_HEAD and
          run.get('status')=='completed' and run.get('conclusion')=='success',
          'original source run not pinned completed-success')
    check(type(artifact) is dict and artifact.get('id')==ARTIFACT_ID and
          artifact.get('name')==ARTIFACT_NAME and artifact.get('expired') is False and
          (artifact.get('workflow_run') or {}).get('id')==RUN_ID,
          'wrong original artifact identity/run/expiration')
    if artifact.get('digest') is not None:
        check(artifact['digest']=='sha256:'+ARCHIVE_SHA,'original artifact digest mismatch')
    check(type(artifact.get('size_in_bytes')) is int and
          0<artifact['size_in_bytes']<2_000_000,'invalid original archive transfer size')

def storage_host(location):
    parts=parse.urlsplit(location)
    host=(parts.hostname or '').lower()
    check(parts.scheme=='https' and bool(host) and
          parts.username is None and parts.password is None and
          any(host.endswith(s) and host!=s[1:] for s in REDIRECT_DOMAINS),
          'not an approved GitHub artifact storage redirect')
    return host

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def get_zip(token):
    check(isinstance(token,str) and len(token)>10,'GitHub read token required')
    run=api_json(f'/actions/runs/{RUN_ID}',token)
    art=api_json(f'/actions/artifacts/{ARTIFACT_ID}',token)
    validate(run,art)
    req=request.Request(ENDPOINT+f'/actions/artifacts/{ARTIFACT_ID}/zip',
         headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=40) as result:
            status=result.status;location=result.headers.get('Location')
    except error.HTTPError as exc:
        check(exc.code in (301,302,303,307,308),'original API artifact download refused')
        status=exc.code;location=exc.headers.get('Location')
    check(status in (301,302,303,307,308) and type(location) is str,
          'no direct GitHub storage redirect')
    storage_host(location)
    # GitHub bearer authorization MUST NOT be forwarded to storage.
    req2=request.Request(location,headers={'Accept':'application/zip'})
    with request.urlopen(req2,timeout=80) as response:
        check(response.status==200,'original archive storage GET failed')
        data=response.read(2_000_001)
    check(0<len(data)<2_000_000 and hashlib.sha256(data).hexdigest()==ARCHIVE_SHA,
          'original archive SHA-256 changed')
    return data

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    data=get_zip(token)
    p=args.output
    check(p.parent.is_dir() and not p.parent.is_symlink() and not p.exists() and
          not p.is_symlink(),'artifact file must be create-only')
    with p.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    print(json.dumps({'run':RUN_ID,'artifact_id':ARTIFACT_ID,'sha256':ARCHIVE_SHA,
          'size_bytes':len(data),'production_accepted':False,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()
