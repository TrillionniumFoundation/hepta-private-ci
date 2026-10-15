#!/usr/bin/env python3
"""No-token-forward SHA-pinned download of original completed GitHub Actions ZIP.

The GitHub API request carries a read-only GH_TOKEN, but the redirect request
is made with NO authorization header. No redirects are followed implicitly.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request, urlopen

REPO='TrillionniumFoundation/hepta-private-ci'
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def download(artifact_id: int, original_sha: str, destination: str, token: str):
    if type(artifact_id) is not int or artifact_id<1 or type(token) is not str or not 1<len(token)<8192:
        raise ValueError('original artifact identity and read-only token are required')
    if type(original_sha) is not str or len(original_sha)!=64 or any(c not in '0123456789abcdef' for c in original_sha):
        raise ValueError('invalid pinned original full ZIP SHA')
    out=Path(destination)
    if out.exists() or out.is_symlink():raise FileExistsError('create-only original ZIP required')
    api=f'https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip'
    req=Request(api,headers={'Authorization':f'Bearer {token}',
         'X-GitHub-Api-Version':'2022-11-28', 'Accept':'application/vnd.github+json'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=90):
            raise ValueError('expected signed GitHub artifact redirect')
    except HTTPError as err:
        if err.code not in (302, 307): raise
        redirect=err.headers.get('Location','')
    uri=urlsplit(redirect)
    if uri.scheme!='https' or not uri.netloc or uri.username or uri.password:
        raise ValueError('invalid original artifact HTTPS redirect')
    # Deliberately create a fresh request WITHOUT the GitHub API bearer token.
    with urlopen(Request(redirect,headers={'Accept':'application/zip'}),timeout=180) as stream:
        data=stream.read(2_000_001)
    if not 0<len(data)<2_000_000 or sha256(data).hexdigest()!=original_sha:
        raise ValueError('missing, oversized or forged original artifact ZIP')
    with out.open('xb') as f:f.write(data)
    return {'original_artifact_id':artifact_id,'original_zip_sha256':original_sha,
            'zip_size_bytes':len(data),'authority_posture':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id',type=int,required=True)
    p.add_argument('--sha',required=True)
    p.add_argument('--out',required=True)
    c=p.parse_args()
    record=download(c.id,c.sha,c.out,os.environ.get('GH_TOKEN',''))
    print('PINNED_ORIGINAL_ARTIFACT_BYTES_VERIFIED / DENY_ALL',record['original_artifact_id'])
if __name__=='__main__':main()
