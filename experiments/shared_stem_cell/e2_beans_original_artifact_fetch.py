"""Fetch exact original Beans GitHub Action ZIPs by run, ID, and SHA-256.

No arbitrary URL inputs, no producer training, and no redirect credential leak.
Returns immutable original ZIP bytes for two-process label-blind/withheld replay.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib import request, error, parse

REPO='TrillionniumFoundation/hepta-private-ci'
SOURCE_HEAD='927bf53b184c3947db17a129834046c5f03add04'
ORIGINAL={
 'source':'hepta-e2-beans-source-original-label-blind',
 'withheld':'hepta-e2-beans-withheld-test-targets',
 'producer':'hepta-e2-beans-original-dual-encoder-sealed-no-weights',
 'independent':'hepta-e2-beans-original-retrospective-independent-results',
}
BASE=f'https://api.github.com/repos/{REPO}'
ALLOWED_REDIRECT_SUFFIXES=('.githubusercontent.com','.blob.core.windows.net')
MAX_ARCHIVE_BYTES=70_000_000

class FetchError(ValueError):pass

def require(ok,message):
    if not ok: raise FetchError(message)

def digest(raw):return hashlib.sha256(raw).hexdigest()

def _hex_sha(s):
    require(type(s) is str and len(s)==64 and not set(s).difference('0123456789abcdef'),
            'literal lowercase SHA-256 required')
    return s

def _api_get_json(path,token):
    req=request.Request(BASE+path,headers={'Authorization':'Bearer '+token,
                  'Accept':'application/vnd.github+json',
                  'X-GitHub-Api-Version':'2022-11-28'},method='GET')
    with request.urlopen(req,timeout=40) as response:
        require(response.status==200,'GitHub API request failed')
        raw=response.read(4_000_000)
    return json.loads(raw)

class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def _download_exact_artifact(artifact_id,token,expected_digest):
    req=request.Request(BASE+f'/actions/artifacts/{artifact_id}/zip',headers={
         'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
         'X-GitHub-Api-Version':'2022-11-28'},method='GET')
    try:
        with request.build_opener(_NoRedirect()).open(req,timeout=40) as resp:
            status=resp.status; location=resp.headers.get('Location')
    except error.HTTPError as exc:
        if exc.code not in (301,302,303,307,308):raise
        status=exc.code;location=exc.headers.get('Location')
    require(status in (301,302,303,307,308) and isinstance(location,str),
            'expected short-lived archive redirect')
    url=parse.urlsplit(location)
    host=(url.hostname or '').lower()
    require(url.scheme=='https' and not url.username and not url.password and
            any(host.endswith(s) and host!=s[1:] for s in ALLOWED_REDIRECT_SUFFIXES),
            'unexpected GitHub storage redirect domain')
    # NEVER forward GitHub Authorization headers to storage-host redirects.
    req2=request.Request(location,method='GET',headers={'Accept':'application/zip'})
    with request.urlopen(req2,timeout=120) as res:
        require(res.status==200,'artifact storage retrieval failed')
        data=res.read(MAX_ARCHIVE_BYTES+1)
    require(0<len(data)<=MAX_ARCHIVE_BYTES and digest(data)==expected_digest,
            'original artifact size or SHA-256 mismatch')
    return data


def validate_run_and_inventory(run,artifacts,run_id,ids):
    require(type(run) is dict and run.get('id')==run_id and
            run.get('head_sha')==SOURCE_HEAD and run.get('status')=='completed' and
            run.get('conclusion')=='success',
            'original Beans run is not completed success at pinned source SHA')
    items=artifacts.get('artifacts')
    require(type(items) is list and items,'original run has no artifacts')
    require(set(ids)==set(ORIGINAL) and len(set(ids.values()))==4 and
            all(type(n) is int and n>0 for n in ids.values()),
            'exact four distinct artifact IDs mandatory')
    byid={}
    for a in items:
        if not isinstance(a,dict):continue
        if a.get('id') in byid:raise FetchError('duplicate artifact ID in response')
        byid[a.get('id')]=a
    for role,id in ids.items():
        a=byid.get(id)
        require(type(a) is dict and a.get('name')==ORIGINAL[role] and
                a.get('expired') is False and
                (a.get('workflow_run') or {}).get('id')==run_id,
                'artifact ID, name, expiry, or run association not authenticated')
    return True


def download_verified(run_id,ids,pins,destination,token,roles=None):
    require(type(run_id) is int and run_id>0 and type(token) is str and bool(token),
            'missing literal run or token')
    require(set(pins)==set(ORIGINAL),'original ZIP role pins missing')
    for sha in pins.values():_hex_sha(sha)
    if roles is None: roles=set(ORIGINAL)
    require(type(roles) is set and bool(roles) and roles <= set(ORIGINAL),
            'unknown requested ZIP roles')
    run=_api_get_json(f'/actions/runs/{run_id}',token)
    artifacts=_api_get_json(f'/actions/runs/{run_id}/artifacts?per_page=100',token)
    validate_run_and_inventory(run,artifacts,run_id,ids)
    dest=Path(destination)
    require(dest.parent.is_dir() and not dest.parent.is_symlink() and
            not dest.exists() and not dest.is_symlink(),
            'output directory must be new and non-linked')
    dest.mkdir()
    result={}
    for role in ORIGINAL:
        if role not in roles:continue
        data=_download_exact_artifact(ids[role],token,pins[role])
        p=dest/(role+'.zip')
        with p.open('xb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        result[role]={'artifact_id':ids[role],'sha256':pins[role],
                      'size_bytes':len(data)}
    return {'schema':'hepta.e2.original-beans-archive-fetch.v1',
            'original_run_id':run_id,'original_source_sha':SOURCE_HEAD,
            'archives':result,'production_accepted':False,'authority':'DENY_ALL'}


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id',type=int,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--roles',default='source,withheld,producer,independent',
                   help='comma-separated subset of original ZIPs physically downloaded')
    for k in ORIGINAL:
        p.add_argument('--'+k+'-id',type=int,required=True)
        p.add_argument('--'+k+'-sha256',required=True)
    a=p.parse_args()
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    values={k:getattr(a,k+'_id') for k in ORIGINAL}
    pins={k:getattr(a,k+'_sha256') for k in ORIGINAL}
    roles=set(a.roles.split(','))
    require(all(a.roles.split(',').count(r)==1 for r in roles),'duplicate role selector')
    outcome=download_verified(a.run_id,values,pins,a.output_dir,token,roles=roles)
    print(json.dumps(outcome,sort_keys=True))

if __name__=='__main__':cli()
