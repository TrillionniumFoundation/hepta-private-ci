#!/usr/bin/env python3
"""Acquire ONLY registered original Actions ZIPs, using separate bearer/HTTPS-blob requests.

No automatic redirect forwards the GitHub token to the signed object store.
Original hashes are code-pinned; any absent/corrupt artifact is NO-GO.
"""
import argparse, hashlib, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path

REPO='TrillionniumFoundation/hepta-private-ci'
SOURCE={
 'historic':(11946621518,'1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'),
 'public':(11991113170,'b8ea439e3d3300d4c09e5fe1c568bcaa6403d0bda2a86dd42fd28c05e9c761b1'),
 'model':(12010699818,'d1ff527ddb9ee32f3e258c9cdb206449f242ac5f9b7b21e6d4f163b6c88706d1'),
 'fold0':(11949081037,'cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d'),
 'fold1':(11948881417,'8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e'),
 'fold2':(11948806536,'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5'),
 'fold3':(11948681555,'8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2'),
 'owner':(11991387730,'89fce74a76a5abe4a43ea9c28ea120b9b81b76cb63e3ade198a80077f8035b35'),
 'score':(12018967923,'469bb6ef89c70f9329564e794cad2dff4b4fe603e5255971078aaf9500eb6eb8'),
}
BLIND=frozenset(('historic','public','model','fold0','fold1','fold2','fold3'))
REVIEW=frozenset(SOURCE)
MAX=200_000

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,request,file,code,msg,headers,newurl):return None

def signed_endpoint(url):
 if not isinstance(url,str) or any(c in url for c in ('\r','\n','\x00')):raise ValueError('unsafe original signed URL')
 p=urllib.parse.urlsplit(url);host=(p.hostname or '').lower()
 if (p.scheme!='https' or (not host.endswith('.blob.core.windows.net') and not host.endswith('.actions.githubusercontent.com') and host!='actions.githubusercontent.com')
     or p.username is not None or p.password is not None or p.port not in (None,443) or not p.path or not p.query or p.fragment):
  raise ValueError('unapproved signed-original-archive domain')
 return url

def download(scope,identity,token,output,opener=None):
 if scope not in ('blind','review') or identity not in SOURCE or identity not in (BLIND if scope=='blind' else REVIEW):
  raise ValueError('E25 held-owner access denied by blind material role')
 if not isinstance(token,str) or not token or '\r' in token or '\n' in token:raise ValueError('missing trusted Actions bearer')
 output=Path(output)
 if output.exists() or output.is_symlink():raise FileExistsError('create-only immutable material')
 artifact,expect=SOURCE[identity]
 open0=opener or urllib.request.build_opener(NoRedirect)
 url=f'https://api.github.com/repos/{REPO}/actions/artifacts/{artifact}/zip'
 request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
 try:
  with open0.open(request,timeout=100):raise ValueError('source API did not return signed response')
 except urllib.error.HTTPError as exc:
  if exc.code!=302:raise ValueError('original GitHub Actions ZIP unavailable') from exc
  redirect=signed_endpoint(exc.headers.get('Location'))
  exc.close()
 bare=urllib.request.Request(redirect,method='GET')
 with open0.open(bare,timeout=100) as response:
  if urllib.parse.urlsplit(response.geturl()).hostname!=urllib.parse.urlsplit(redirect).hostname:raise ValueError('signed blob redirected again')
  data=response.read(MAX+1)
 if not 200<len(data)<MAX or hashlib.sha256(data).hexdigest()!=expect:raise ValueError('original SHA-pinned Actions ZIP mismatch')
 output.parent.mkdir(parents=True,exist_ok=True)
 with output.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 return {'role':scope,'artifact_id':artifact,'sha256':expect,'bytes':len(data),'authority':'DENY_ALL'}

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--role',choices=('blind','review'),required=True);p.add_argument('--name',choices=tuple(SOURCE),required=True);p.add_argument('--output',required=True)
 a=p.parse_args();print(download(a.role,a.name,os.environ.get('GH_TOKEN',''),a.output))
if __name__=='__main__':main()
