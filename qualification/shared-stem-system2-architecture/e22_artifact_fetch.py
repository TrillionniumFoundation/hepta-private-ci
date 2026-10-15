"""Exact SHA-bound E22 hosted artifact inputs; blind stage never fetches scores.

Read-only GitHub Actions ZIP fetch. No original human-label Parquet or model
weights are fetched here. The human scorer obtains the pinned parquet in a
SEPARATE job only after all blind prediction bytes are sealed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import os
from pathlib import Path
from urllib.request import Request, urlopen

from e21_whole_question import E15_FOLDS, E15_SCORES, SOURCE_SHA
from e22_e16_question_gate import E16_FOLDS
from e22_independent_human_score import E16_SCORES

REPO='TrillionniumFoundation/hepta-private-ci'
SOURCE_ARTIFACT=11946621518


def inventory(stage: str, with_e9: bool = False):
    if stage not in ('blind','full'):
        raise ValueError('only blind or full original artifact inventory admitted')
    items = []
    for n, (artifact_id, digest, _) in enumerate(E15_FOLDS):
        items.append((f'HEPTA_E22_E15_FOLD_{n}', artifact_id, digest))
    for n, (artifact_id, digest, _) in enumerate(E16_FOLDS):
        items.append((f'HEPTA_E22_E16_FOLD_{n}', artifact_id, digest))
    if stage=='full':
        for n,(artifact_id, digest, _) in enumerate(E15_SCORES):
            items.append((('HEPTA_E22_E15_SCORE_SOURCE','HEPTA_E22_E15_SCORE_MERGE')[n], artifact_id, digest))
        for n,(artifact_id,digest,_) in enumerate(E16_SCORES):
            items.append((('HEPTA_E22_E16_SCORE_SOURCE','HEPTA_E22_E16_SCORE_MERGE')[n],artifact_id,digest))
    if with_e9:
        if stage != 'full': raise ValueError('historical label archive forbidden before blind seal')
        items.extend([
            ('HEPTA_E9_PHYSICAL', 11908591037, 'd8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa'),
            ('HEPTA_E9_HISTORICAL', 11886761368, 'e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'),
        ])
    if len({id for _,id,_ in items})!=len(items) or len(items)!=(8 if stage=='blind' else (14 if with_e9 else 12)):
        raise ValueError('historical source artifact plan collision or missing receipt')
    return tuple(items)


def fetch(out: str, stage: str, *, source_archive: str | None = None,
          github_env: str | None = None, token: str | None = None, with_e9: bool = False):
    base=Path(out)
    if base.exists():
        raise ValueError('create-only source cache path must not exist')
    base.mkdir(parents=True)
    spec=[('HEPTA_E22_ARCHIVE',SOURCE_ARTIFACT,SOURCE_SHA)]+list(inventory(stage, with_e9=with_e9))
    exports={}
    for key,id,expected in spec:
        path=Path(source_archive) if key=='HEPTA_E22_ARCHIVE' and source_archive else base/f'{id}.zip'
        if not (key=='HEPTA_E22_ARCHIVE' and source_archive):
            if not token or len(token)>8192:
                raise ValueError('limited GitHub token required to fetch original evidence')
            url=f'https://api.github.com/repos/{REPO}/actions/artifacts/{id}/zip'
            req=Request(url,headers={'Authorization':f'Bearer {token}',
                                     'X-GitHub-Api-Version':'2022-11-28',
                                     'Accept':'application/vnd.github+json'})
            with urlopen(req,timeout=160) as response:
                data=response.read(2_000_001)
            if not 0<len(data)<=2_000_000:
                raise ValueError('missing or excessively large immutable research archive')
            if sha256(data).hexdigest()!=expected:
                raise ValueError('original GitHub artifact bytes changed')
            with path.open('xb') as f:f.write(data)
        if not path.is_file() or sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('source archive incorrect before use')
        exports[key]=str(path.resolve())
    # Compatibility names used by the original broad E6-E8 source discovery,
    # E20, E21 and E22. No tests are skipped, mocked or filtered.
    orig=exports['HEPTA_E22_ARCHIVE']
    for key in ('HEPTA_E14_ARCHIVE','HEPTA_E15_ARCHIVE','HEPTA_E16_ARCHIVE',
                'HEPTA_E17_REAL_ARCHIVE','HEPTA_E18_ORIGINAL_ARCHIVE',
                'HEPTA_E19_ORIGINAL_ARCHIVE','HEPTA_E20_ORIGINAL_MULTIRC_ARCHIVE',
                'HEPTA_E21_SOURCE'):
        exports[key]=orig
    for i in range(4):
        exports[f'HEPTA_E21_FOLD_{i}']=exports[f'HEPTA_E22_E15_FOLD_{i}']
    if stage=='full':
        exports['HEPTA_E21_SCORE_SOURCE']=exports['HEPTA_E22_E15_SCORE_SOURCE']
        exports['HEPTA_E21_SCORE_MERGE']=exports['HEPTA_E22_E15_SCORE_MERGE']
    if github_env:
        with Path(github_env).open('a',encoding='utf-8') as f:
            for k,v in sorted(exports.items()):
                if not k.startswith('HEPTA_') or '\n' in v or '\r' in v:
                    raise ValueError('bad exact historical source export')
                f.write(f'{k}={v}\n')
    return exports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True)
    p.add_argument('--stage',choices=('blind','full'),required=True)
    p.add_argument('--source-archive',default=None)
    p.add_argument('--github-env',default=None)
    p.add_argument('--with-e9',action='store_true')
    a=p.parse_args()
    result=fetch(a.out,a.stage,source_archive=a.source_archive,
                 github_env=a.github_env,token=os.environ.get('GH_TOKEN'),with_e9=a.with_e9)
    print(f'Validated {len(result)} source environment records; stage={a.stage}; DENY_ALL')

if __name__=='__main__':main()
