"""Two-process archival replay: fit-only seal, then independent withheld scoring.

No hidden fallback, model load, future-label fit input, Stem selection, or
production authority. Every ZIP and seal object has an exact caller-supplied
SHA-256. Separate processes are required by the documented command sequence.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import os
from e2_beans_original_zip_review import Reject, require, canon, digest
from e2_beans_frozen_vision_linear_probe import seal, write_seal


def _pin(s):
    require(type(s) is str and len(s)==64 and all(c in '0123456789abcdef' for c in s),
            'SHA-256 must be exact lowercase hex')
    return s


def prepare(source,source_sha,producer,producer_sha,out):
    """Only two labels-free archive inputs; withheld ZIP is not accepted."""
    source_sha=_pin(source_sha);producer_sha=_pin(producer_sha)
    model,preds=seal(source,source_sha,producer,producer_sha)
    result=write_seal(Path(out),model,preds)
    return {'schema':'hepta.e2.beans-two-stage-replay-seal.v1',
            'source_zip_sha256':source_sha,'producer_zip_sha256':producer_sha,
            'seal':result, 'withheld_labels_opened':False,
            'production_accepted':False,'stem_selected':False,'authority':'DENY_ALL'}


def finish(paths,pins,model,model_sha,predictions,predictions_sha,output):
    from e2_beans_vision_probe_independent_score import read_pinned
    from e2_beans_independent_svd_oracle import independent_svd_parity
    expected={'source','producer','withheld','independent'}
    require(set(paths)==set(pins)==expected,'four original archives and pins mandatory')
    require(len({str(Path(p).resolve()) for p in paths.values()})==4,
            'same archive reused for two original roles')
    for k in paths:_pin(pins[k])
    model_sha=_pin(model_sha);predictions_sha=_pin(predictions_sha)
    m=read_pinned(model,model_sha);p=read_pinned(predictions,predictions_sha)
    # Distinct numerical implementation and all 24 original feature predictions
    # are checked before the independent label-bearing reviewer is imported.
    svd=independent_svd_parity(paths['source'],pins['source'],paths['producer'],pins['producer'],m,p)
    from e2_beans_vision_probe_independent_score import independent_score
    original=independent_score(paths,pins,m,model_sha,p)
    require(original.get('authority')=='DENY_ALL' and
            original.get('all_four_original_archives_independently_validated') is True,
            'original evidence audit failed')
    result={'schema':'hepta.e2.beans-two-approach-independent-evidence.v1',
            'source_zip_sha256':pins['source'],
            'producer_zip_sha256':pins['producer'],
            'withheld_zip_sha256':pins['withheld'],
            'independent_zip_sha256':pins['independent'],
            'svd_oracle':svd,'paired_original_outcomes':original,
            'natural_task_accepted':False,
            'natural_future_windows_verified':False,
            'independent_original_model_owner_attested':False,
            'production_accepted':False,'stem_selected':False,'authority':'DENY_ALL'}
    path=Path(output)
    require(path.parent.is_dir() and not path.is_symlink() and not path.exists(),
            'output must be create-only')
    data=canon(result)
    with path.open('xb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    return {'artifact_sha256':digest(data),'original_cases':original['cases'],
            'fitted_bridge_correct':original['original_fitted_bridge_correct'],
            'vision_ridge_correct':original['frozen_vision_ridge_correct'],
            'vision_prototype_correct':original['original_vision_prototype_correct'],
            'production_accepted':False,'authority':'DENY_ALL'}


def cli():
    a=argparse.ArgumentParser(description=__doc__)
    sub=a.add_subparsers(dest='command',required=True)
    fit=sub.add_parser('seal',help='train-only, only source and producer archives')
    for n in ('source','producer'):
        fit.add_argument('--'+n+'-zip',type=Path,required=True)
        fit.add_argument('--'+n+'-sha256',required=True)
    fit.add_argument('--output-dir',type=Path,required=True)
    score=sub.add_parser('score',help='independent process consumes all four original archives')
    for n in ('source','producer','withheld','independent'):
        score.add_argument('--'+n+'-zip',type=Path,required=True)
        score.add_argument('--'+n+'-sha256',required=True)
    score.add_argument('--model',required=True,type=Path)
    score.add_argument('--model-sha256',required=True)
    score.add_argument('--predictions',required=True,type=Path)
    score.add_argument('--predictions-sha256',required=True)
    score.add_argument('--output',required=True,type=Path)
    p=a.parse_args()
    if p.command=='seal':
        out=prepare(p.source_zip,p.source_sha256,p.producer_zip,p.producer_sha256,p.output_dir)
    else:
        keys=('source','producer','withheld','independent')
        out=finish({k:getattr(p,k+'_zip') for k in keys},
                   {k:getattr(p,k+'_sha256') for k in keys},
                   p.model,p.model_sha256,p.predictions,p.predictions_sha256,p.output)
    print(json.dumps(out,sort_keys=True))

if __name__=='__main__':cli()
