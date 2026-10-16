"""Secure original GitHub Actions artifact transport with bearer redirect separation.

GitHub token goes ONLY to api.github.com. Every signed object-store redirect
is downloaded in a separate unauthenticated request. Never log signed URLs.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

URL='https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/11586991191/zip'
ZIP_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
MAX_SIZE=420_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def accepted_location(value):
    if type(value) is not str or len(value)>8192 or any(c in value for c in ('\n','\r','\x00')):
        raise ValueError('no trustworthy signed-object location')
    parsed=urllib.parse.urlsplit(value)
    host=(parsed.hostname or '').lower()
    allowed=(host in ('objects.githubusercontent.com','release-assets.githubusercontent.com',
                      'pipelines.actions.githubusercontent.com') or
             host.endswith('.blob.core.windows.net') or
             host.endswith('.actions.githubusercontent.com') or
             host.endswith('.githubusercontent.com') or
             host.endswith('.s3.amazonaws.com'))
    if (parsed.scheme!='https' or not allowed or parsed.username is not None or
        parsed.password is not None or parsed.port not in (None,443) or
        not parsed.path.startswith('/') or not parsed.query):
        raise ValueError('redirect does not satisfy original GitHub artifact signed URL policy')
    return value


def download(dest,token,opener=None,object_open=None):
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:
        raise ValueError('missing GitHub Actions read token')
    p=Path(dest)
    if p.exists() or p.is_symlink() or not p.parent.is_dir():
        raise ValueError('create-only artifact output already exists')
    opener=opener or urllib.request.build_opener(NoRedirect())
    req=urllib.request.Request(URL,headers={
        'Authorization':'Bearer '+token,
        'Accept':'application/vnd.github+json',
        'User-Agent':'Hepta-V19-Research-Readonly'})
    try:
        response=opener.open(req,timeout=80)
        response.close()
        raise ValueError('original artifact API did not give a signed redirect')
    except urllib.error.HTTPError as e:
        if e.code not in (302,303,307,308):
            raise ValueError('GitHub artifact signed redirect unavailable') from None
        signed=accepted_location(e.headers.get('Location'))
        e.close()
    get=urllib.request.Request(signed,headers={'User-Agent':'Hepta-V19-Research-Readonly'})
    if any(k.casefold()=='authorization' for k in get.headers):
        raise ValueError('redirect request has an unexpected credential')
    target_open=object_open or urllib.request.urlopen
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):flags|=os.O_NOFOLLOW
    h=sha256();total=0
    try:
        with target_open(get,timeout=1200) as original,os.fdopen(os.open(p,flags,0o600),'wb') as f:
            while True:
                buf=original.read(1024*1024)
                if not buf:break
                total+=len(buf)
                if total>MAX_SIZE:raise ValueError('unbounded external archive')
                h.update(buf);f.write(buf)
            f.flush();os.fsync(f.fileno())
        if h.hexdigest()!=ZIP_SHA:
            raise ValueError('original GitHub archive SHA256 changed')
    except BaseException as exc:
        p.unlink(missing_ok=True)
        # urllib transport errors may embed the bearer-free but sensitive signed
        # query URL.  Never expose signed URLs in a hosted job log or receipt.
        if isinstance(exc, (urllib.error.URLError, OSError)):
            raise ValueError('signed object transfer failed; URL withheld') from None
        raise
    return {'archive_sha256':ZIP_SHA,'zip_bytes':total,
            'github_token_sent_to_object_store':False,
            'original_model_executed':False,'production_authorized':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True)
    a=p.parse_args()
    result=download(a.out,os.environ.get('GH_TOKEN'))
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
