#!/usr/bin/env python3
"""Isolated GitHub Actions matrix artifact intake, without model/label authority.

Never use download-artifact merge-multiple for the four model attempts: GitHub
specifies *last writer wins* for duplicate relative names. A different Runner
materializes named per-arm artifacts. This code verifies the complete allowed
file inventory per arm BEFORE copying to the existing label-blind collector
workspace. The original V8 numeric and V10 all-four gate remain unchanged.

Missing uploaded artifacts are an observable missing arm, never a success. An
unexpected artifact, cross-arm file, invalid attempt or corrupted replay shape
is an ingestion FAILURE, never a missing/low-quality model. The original model
weights and human HELD labels are forbidden in this workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from p0_multirc_semantic_material import Invalid, canonical
from p0_parallel_model_collector_v10 import ATTEMPT_SCHEMA
from p0_partial_pretrained_diagnostic_v8 import MODELS

SCHEMA = 'hepta.p0.isolated-parallel-artifact-intake.v11'
MAX_TOTAL = 80 * 1024 * 1024
MAX_EACH = {
    '.json': 8 * 1024 * 1024,
    '.txt': 256 * 1024,
    '.safetensors': 16 * 1024 * 1024,
}
REPLAY_NAMES = frozenset({'COMMITTED.json', 'features.safetensors', 'heads.safetensors'})
META_NAMES = frozenset({'fit.json','blind.json'})
HEX_ID = re.compile(r'[0-9]{1,20}\Z')


def _normal_file(path: Path, *, max_size: int) -> int:
    if path.is_symlink():
        raise Invalid('symlink in original model artifact cannot be copied')
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or not 1 <= st.st_size <= max_size:
        raise Invalid('missing/unbounded/nonregular model artifact')
    return st.st_size


def _normal_dir(path: Path) -> None:
    if path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode):
        raise Invalid('unsafe/non-directory original source slot')


def _read_attempt(path: Path, model: str):
    _normal_file(path,max_size=4096)
    raw=path.read_bytes()
    def pairs(kv):
        out={}
        for key,value in kv:
            if key in out:
                raise Invalid('duplicate attempt receipt key')
            out[key]=value
        return out
    attempt=json.loads(raw,object_pairs_hook=pairs,
                       parse_constant=lambda x: (_ for _ in ()).throw(Invalid('bad float in attempt')))
    if (type(attempt) is not dict or set(attempt) !=
        {'schema','model','outcome','authority','production_promotion_permitted','held_test_labels_accessed'}
        or attempt['schema']!=ATTEMPT_SCHEMA or attempt['model']!=model or
        attempt['outcome'] not in ('model_report_written','failed_or_incomplete') or
        attempt['authority']!='DENY_ALL' or
        attempt['production_promotion_permitted'] is not False or
        attempt['held_test_labels_accessed'] is not False):
        raise Invalid('wrong arm identity or false authority in upload')
    return attempt


def _inventory_arm(folder: Path, model: str):
    """Return (attempt, source leaf paths) with *every* file individually checked."""
    _normal_dir(folder)
    files=[]
    replay=f'{model}.replay'
    allowed = {f'attempt-{model}.json',f'{model}.json',f'{model}.failed.txt',
               f'{model}.runtime.txt'}
    if model in ('granite_97m_r2','mmbert_small'):
        allowed.add(f'{model}.preflight-v9.json')
    if model=='embeddinggemma_2_text':
        allowed.add('gemma-source-receipt.json')
    # Original commit contains at most three declared tensor archive leaves.
    seen=set()
    total=0
    for child in folder.iterdir():
        if child.name not in allowed and child.name!=replay:
            raise Invalid('undeclared cross-model or human-label artifact path')
        if child.name in seen:
            raise Invalid('duplicate original root child')
        seen.add(child.name)
        if child.name==replay:
            if model=='laya421_nochange':
                raise Invalid('native Laya cannot forge a trained small-Head tensor archive')
            _normal_dir(child)
            names={p.name for p in child.iterdir()}
            if names!=REPLAY_NAMES:
                raise Invalid('incomplete/unregistered original tensor archive')
            for leaf in child.iterdir():
                suffix=leaf.suffix
                size=_normal_file(leaf,max_size=MAX_EACH[suffix])
                total+=size
                files.append((f'{replay}/{leaf.name}',leaf))
        else:
            suffix=child.suffix
            size=_normal_file(child,max_size=MAX_EACH[suffix])
            total+=size
            files.append((child.name,child))
        if total>MAX_TOTAL:
            raise Invalid('model artifact cumulative size exceeded')
    if f'attempt-{model}.json' not in seen:
        raise Invalid('original model artifact lacks fixed attempt receipt')
    attempt=_read_attempt(folder/f'attempt-{model}.json',model)
    got_model=f'{model}.json' in seen
    got_failed=f'{model}.failed.txt' in seen
    got_replay=replay in seen
    if attempt['outcome']=='model_report_written':
        if not got_model or got_failed or got_replay != (model!='laya421_nochange'):
            raise Invalid('successful attempt lacks its exact original model report/replay')
    else:
        if not got_failed or got_model or got_replay:
            raise Invalid('failed attempt contains contradictory successful model evidence')
    return attempt,files,total


def isolated_intake(attempts_root: Path, collected_root: Path, run_id: str):
    if type(run_id) is not str or HEX_ID.fullmatch(run_id) is None:
        raise Invalid('invalid exact GitHub run identity')
    root=Path(attempts_root);out=Path(collected_root)
    _normal_dir(root);_normal_dir(out)
    allowed={f'hepta-human-original-arm-{m}-{run_id}':m for m in MODELS}
    members=list(root.iterdir())
    if any(p.name not in allowed for p in members):
        raise Invalid('unexpected additional matrix artifact folder')
    if any(p.name in META_NAMES for p in out.iterdir() if p.is_symlink()):
        raise Invalid('unsafe input material path')
    if {x.name for x in out.iterdir()} != META_NAMES:
        raise Invalid('collector workspace must contain only original fit and blind')
    for p in out.iterdir():
        _normal_file(p,max_size=16 * 1024 * 1024)
    staged=[];statuses={};total=0
    # Never inspect ground-truth held labels and never accept raw model weight snapshots.
    for model in MODELS:
        path=root/f'hepta-human-original-arm-{model}-{run_id}'
        if not path.exists() and not path.is_symlink():
            statuses[model]={'status':'artifact_not_uploaded','files':0}
            continue
        attempt,files,bytes_count=_inventory_arm(path,model)
        staged.extend((rel,src,model) for rel,src in files)
        total+=bytes_count
        statuses[model]={'status':attempt['outcome'],'files':len(files),
                         'bytes':bytes_count}
        if total>4*MAX_TOTAL:
            raise Invalid('aggregate original artifacts oversized')
    allpaths=[rel for rel,_,_ in staged]
    if len(allpaths)!=len(set(allpaths)):
        raise Invalid('cross-runner path collision, would overwrite evidence')
    # Exactly one immutable per-arm tree is consumed; no merge-multiple overwrite.
    digests={}
    for rel,src,model in staged:
        destination=out/rel
        if '/' in rel:
            directory=destination.parent
            if directory.exists() or directory.is_symlink():
                # A replay tree is created once before adding its other leaves.
                if directory.is_symlink() or not directory.is_dir():
                    raise Invalid('unsafe already staged tensor tree')
            else:
                directory.mkdir(mode=0o700)
        h=hashlib.sha256()
        with src.open('rb') as reader, destination.open('xb') as writer:
            while True:
                chunk=reader.read(1024 * 1024)
                if not chunk: break
                writer.write(chunk);h.update(chunk)
            writer.flush();os.fsync(writer.fileno())
        digests[rel]=h.hexdigest()
    report={'schema':SCHEMA,'github_run_id':run_id,
            'original_attempt_upload_statuses':statuses,
            'intake_file_sha256':digests,
            'entire_four_model_population_verified':False,
            'independently_confirmed_pretrained_execution':False,
            'human_held_labels_seen':False,
            'production_promotion_permitted':False,
            'authority':'DENY_ALL'}
    # Write the receipt LAST, so torn copies cannot impersonate complete intake.
    with (out/'artifact-intake-v11.json').open('xb') as h:
        h.write(canonical(report)+b'\n');h.flush();os.fsync(h.fileno())
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--attempts-root',type=Path,required=True)
    p.add_argument('--collected-root',type=Path,required=True)
    p.add_argument('--run-id',required=True)
    a=p.parse_args()
    print(json.dumps(isolated_intake(a.attempts_root,a.collected_root,a.run_id),sort_keys=True))


if __name__=='__main__':main()
