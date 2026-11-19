"""Download only source-locked original E15/E16 human train-only owner artifacts.

POST-SEAL scoring job ONLY; this must not run in the label-blind learner.
The artifacts originate in previously completed GitHub Actions on immutable
research source HEADs. They are NOT signatures from an independent human owner.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import os
from pathlib import Path
from urllib.request import Request, urlopen
from e23_original_owner_question_gate import E15_OWNERS, E16_OWNERS

REPO='TrillionniumFoundation/hepta-private-ci'


def spec():
    rows=tuple((f'HEPTA_E23_E15_OWNER_{i}',id,digest)
        for i,(id,digest) in enumerate(E15_OWNERS)) + tuple(
        (f'HEPTA_E23_E16_OWNER_{i}',id,digest) for i,(id,digest) in enumerate(E16_OWNERS))
    if len(rows)!=8 or len({id for _,id,_ in rows})!=8:
        raise ValueError('incomplete original label-owner census')
    return rows


def fetch(out, envfile, token):
    if type(token) is not str or not 1<len(token)<8192:
        raise ValueError('read-only GitHub token required in post-seal job')
    dest=Path(out)
    if dest.exists():
        raise ValueError('human owner output directory must be new')
    dest.mkdir(parents=True)
    fields=[]
    for key,id,digest in spec():
        request=Request(f'https://api.github.com/repos/{REPO}/actions/artifacts/{id}/zip',
          headers={'Authorization':f'Bearer {token}','X-GitHub-Api-Version':'2022-11-28',
                   'Accept':'application/vnd.github+json'})
        with urlopen(request,timeout=150) as stream:
            data=stream.read(25_001)
        if not 0<len(data)<25000 or sha256(data).hexdigest()!=digest:
            raise ValueError('original training label owner archive changed')
        p=dest/f'{id}.zip'
        with p.open('xb') as f:f.write(data)
        fields.append((key,str(p.resolve())))
    if envfile:
        with Path(envfile).open('a',encoding='utf8') as f:
            for key,path in fields:
                if '\n' in path or '\r' in path:raise ValueError('invalid export path')
                f.write(f'{key}={path}\n')
    return {'downloaded_archive_count':len(fields),'authority':'DENY_ALL',
            'held_labels_not_cryptographically_secret':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True)
    p.add_argument('--github-env',required=True)
    x=p.parse_args()
    result=fetch(x.out,x.github_env,os.environ.get('GH_TOKEN',''))
    print(f"Downloaded {result['downloaded_archive_count']} pinned post-seal original owner ZIPs; DENY_ALL")

if __name__ == '__main__':main()
