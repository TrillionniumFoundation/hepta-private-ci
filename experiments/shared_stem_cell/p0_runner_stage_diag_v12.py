#!/usr/bin/env python3
"""Bounded original GitHub Actions per-model stage diagnosis; never authority.

The runner describes its own steps with GitHub Actions outcome values. This
record is NOT an external log attestation or proof that a foundation model
executed. A later distinct job matches the exact model, run and source head,
checks the source-blind producer artifact shape, and refuses any contradiction.
No raw exceptions, environment, secrets, checkpoints, or held labels are read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat

from p0_multirc_semantic_material import Invalid, canonical, read, save
from p0_partial_pretrained_diagnostic_v8 import MODELS
from p0_parallel_model_collector_v10 import ATTEMPT_SCHEMA

SCHEMA = 'hepta.p0.github-original-model-step-outcomes.v12'
AUDIT_SCHEMA = 'hepta.p0.cross-runner-step-observation.v12'
STEPS = ('compact_checkout','gemma_checkout','source_lock','runtime','source_preflight','original_attempt')
OUTCOMES = frozenset({'success','failure','cancelled','skipped','not_run'})
RUN_ID = re.compile(r'[0-9]{1,20}\Z')
SHA40 = re.compile(r'[0-9a-f]{40}\Z')
MAX_BYTES = 8192


def _regular(path, limit=MAX_BYTES):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise Invalid('missing/symlinked stage or original attempt source')
    st=path.stat()
    if not stat.S_ISREG(st.st_mode) or not 2 <= st.st_size <= limit:
        raise Invalid('missing, empty, or oversized stage/attempt source')
    return path


def _strict_read(path):
    raw=_regular(path).read_bytes()
    def pairs(entries):
        out={}
        for key,value in entries:
            if key in out:raise Invalid('duplicate stage/attempt receipt JSON key')
            out[key]=value
        return out
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('invalid numeric JSON')))
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise Invalid('unparseable stage/attempt JSON') from exc


def _identity(model,run_id,source_sha):
    if model not in MODELS or type(run_id) is not str or RUN_ID.fullmatch(run_id) is None:
        raise Invalid('unknown model or noncanonical run identity')
    if type(source_sha) is not str or SHA40.fullmatch(source_sha) is None:
        raise Invalid('noncanonical source-HEAD commit')


def _attempt(folder,model):
    original=_strict_read(Path(folder)/f'attempt-{model}.json')
    if (type(original) is not dict or set(original)!={'schema','model','outcome','authority',
        'production_promotion_permitted','held_test_labels_accessed'} or
        original['schema']!=ATTEMPT_SCHEMA or original['model']!=model or
        original['outcome'] not in ('model_report_written','failed_or_incomplete') or
        original['authority']!='DENY_ALL' or original['production_promotion_permitted'] is not False or
        original['held_test_labels_accessed'] is not False):
        raise Invalid('original matrix attempt receipt identity/authority mismatch')
    root=Path(folder)
    complete=(root/f'{model}.json').is_file()
    failed=(root/f'{model}.failed.txt').is_file()
    replay=(root/f'{model}.replay').is_dir()
    if ((root/f'{model}.json').is_symlink() or (root/f'{model}.failed.txt').is_symlink()
            or (root/f'{model}.replay').is_symlink()):
        raise Invalid('unsafe original model result/failure/replay')
    if original['outcome']=='model_report_written':
        if not complete or failed or replay!=(model!='laya421_nochange'):
            raise Invalid('original success has contradictory or missing outputs')
    elif not failed or complete or replay:
        raise Invalid('original failure contradicted by model result')
    return original


def create_stage(folder,model,run_id,source_sha,steps):
    """Called once on a model Runner, AFTER existing original attempt was written."""
    _identity(model,run_id,source_sha)
    if type(steps) is not dict or set(steps)!=set(STEPS) or any(
            type(v) is not str or v not in OUTCOMES for v in steps.values()):
        raise Invalid('unrecognized or incomplete GitHub step outcomes')
    attempt=_attempt(folder,model)
    required=('source_lock','runtime','source_preflight','original_attempt')
    if model!='laya421_nochange': required+=('compact_checkout',)
    if model=='embeddinggemma_2_text': required+=('gemma_checkout',)
    if attempt['outcome']=='model_report_written' and any(steps[s]!='success' for s in required):
        raise Invalid('original model success claimed despite failed/skipped preparation')
    if model=='laya421_nochange' and any(steps[s]!='skipped' for s in ('compact_checkout','gemma_checkout')):
        raise Invalid('Laya did not use the expected no-Encoder-source checkout policy')
    if model!='embeddinggemma_2_text' and steps['gemma_checkout']!='skipped':
        raise Invalid('foreign Gemma loader ran for unrelated research model')
    # The runner may catch model-loading failure and still return a successful
    # shell step, so a green step MUST NOT erase the original failed slot.
    failed_steps=[s for s in STEPS if steps[s] in ('failure','cancelled','not_run')
                  or (steps[s]=='skipped' and s in required)]
    first=failed_steps[0] if failed_steps else (
        'caught_inside_successful_step' if attempt['outcome']!='model_report_written' else None)
    receipt={
        'schema':SCHEMA,'model':model,'github_run_id':run_id,
        'exact_source_head_sha':source_sha,'original_attempt_outcome':attempt['outcome'],
        'github_step_outcomes':steps,'first_non_success_required_stage':first,
        'stages_are_original_runner_self_report_not_independent_attestation':True,
        'human_held_labels_read':False,'all_four_model_qualification':False,
        'production_promotion_permitted':False,'authority':'DENY_ALL'}
    save(Path(folder)/f'{model}.stage-v12.json',receipt)
    return receipt


def verify_stage(folder,model,run_id,expected_sha=None):
    _identity(model,run_id,expected_sha if expected_sha is not None else '0'*40)
    record=_strict_read(Path(folder)/f'{model}.stage-v12.json')
    if type(record) is not dict or set(record)!={
        'schema','model','github_run_id','exact_source_head_sha','original_attempt_outcome',
        'github_step_outcomes','first_non_success_required_stage',
        'stages_are_original_runner_self_report_not_independent_attestation',
        'human_held_labels_read','all_four_model_qualification',
        'production_promotion_permitted','authority'}:
        raise Invalid('incomplete or forged original stage receipt shape')
    if (record['schema']!=SCHEMA or record['model']!=model or record['github_run_id']!=run_id
        or type(record['exact_source_head_sha']) is not str
        or SHA40.fullmatch(record['exact_source_head_sha']) is None
        or (expected_sha is not None and record['exact_source_head_sha']!=expected_sha)
        or record['stages_are_original_runner_self_report_not_independent_attestation'] is not True
        or record['human_held_labels_read'] is not False
        or record['all_four_model_qualification'] is not False
        or record['production_promotion_permitted'] is not False
        or record['authority']!='DENY_ALL'):
        raise Invalid('stage receipt false identity or authority')
    steps=record['github_step_outcomes']
    if type(steps) is not dict or set(steps)!=set(STEPS) or any(type(x) is not str or x not in OUTCOMES for x in steps.values()):
        raise Invalid('altered or unknown runner step outcome')
    # Reconstruct the complete expected receipt with an in-memory write
    # contract, not by accepting an uploaded stage object at face value.
    original=_attempt(folder,model)
    required=('source_lock','runtime','source_preflight','original_attempt')
    if model!='laya421_nochange':required+=('compact_checkout',)
    if model=='embeddinggemma_2_text':required+=('gemma_checkout',)
    if original['outcome']=='model_report_written' and any(steps[s]!='success' for s in required):
        raise Invalid('model report claimed despite unsuccessful actual runner stage')
    if model=='laya421_nochange' and any(steps[s]!='skipped' for s in ('compact_checkout','gemma_checkout')):
        raise Invalid('unexpected native Laya source checkout')
    if model!='embeddinggemma_2_text' and steps['gemma_checkout']!='skipped':
        raise Invalid('Gemma source loaded for an unrelated model')
    failed_steps=[s for s in STEPS if steps[s] in ('failure','cancelled','not_run')
                  or (steps[s]=='skipped' and s in required)]
    expected_first=failed_steps[0] if failed_steps else (
        'caught_inside_successful_step' if original['outcome']!='model_report_written' else None)
    if record['original_attempt_outcome']!=original['outcome'] or record['first_non_success_required_stage']!=expected_first:
        raise Invalid('stage file concealed real original failed/successful evidence')
    return record


def audit_stage_root(root,run_id,source_sha):
    _identity(MODELS[0],run_id,source_sha)
    folder=Path(root)
    if folder.is_symlink() or not folder.is_dir():raise Invalid('unsafe model artifacts staging root')
    allowed={f'hepta-human-original-arm-{m}-{run_id}':m for m in MODELS}
    observed={}
    for child in folder.iterdir():
        if child.name not in allowed:raise Invalid('unregistered original model upload directory')
    for name,model in allowed.items():
        sub=folder/name
        if not sub.exists() and not sub.is_symlink():
            observed[model]={'status':'artifact_not_uploaded','stage':None}
            continue
        if sub.is_symlink() or not sub.is_dir():raise Invalid('unsafe model upload directory')
        record=verify_stage(sub,model,run_id,source_sha)
        observed[model]={'status':record['original_attempt_outcome'],
                         'stage':record['first_non_success_required_stage']}
    return {'schema':AUDIT_SCHEMA,'github_run_id':run_id,'exact_source_head_sha':source_sha,
            'original_stage_census':observed,'runner_outputs_external_authentication':False,
            'all_four_scientifically_accepted':False,'human_held_labels_seen':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    e=sub.add_parser('emit')
    e.add_argument('--arm-root',required=True,type=Path)
    e.add_argument('--model',required=True,choices=MODELS)
    e.add_argument('--run-id',required=True)
    e.add_argument('--source-sha',required=True)
    for s in STEPS:
        e.add_argument('--'+s.replace('_','-'),required=True,choices=sorted(OUTCOMES))
    a=sub.add_parser('audit')
    a.add_argument('--attempts-root',required=True,type=Path)
    a.add_argument('--run-id',required=True)
    a.add_argument('--source-sha',required=True)
    a.add_argument('--output',required=True,type=Path)
    z=p.parse_args()
    if z.command=='emit':
        result=create_stage(z.arm_root,z.model,z.run_id,z.source_sha,{s:getattr(z,s) for s in STEPS})
    else:
        result=audit_stage_root(z.attempts_root,z.run_id,z.source_sha)
        save(z.output,result)
    print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
