#!/usr/bin/env python3
"""Label-blind four-arm *physical artifact* census, not model selection.

Each model is attempted on a separate CI Runner. This collector runs even if a
matrix arm failed and preserves the original fail-closed four-way dependency:
V5/V6/V7/human-label evaluation must NOT start on a partial population.

An upstream attempt is a candidate self-report, not a signed model source.
Even a successful numeric V8 replay cannot prove actual full-weight execution.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import stat

from p0_multirc_semantic_material import Invalid, canonical, read, save, sha, validate
from p0_partial_pretrained_diagnostic_v8 import audit_partial, MODELS, _regular

SCHEMA = 'hepta.p0.parallel-four-original-physical-census.v10'
ATTEMPT_SCHEMA = 'hepta.p0.single-original-model-attempt.v10'
ACCEPTED = {
    'granite_97m_r2':'original_head_numeric_replay_consistent',
    'mmbert_small':'original_head_numeric_replay_consistent',
    'embeddinggemma_2_text':'original_head_numeric_replay_consistent',
    'laya421_nochange':'laya_native_identity_only',
}
MAX_ATTEMPT_BYTES = 4096


def original_four_census(fit, blind, artifacts_root):
    validate(fit, blind)
    root=Path(artifacts_root)
    if root.is_symlink() or not root.is_dir():
        raise Invalid('no safe physical model collection directory')
    # This runner may receive only fit/blind and original model output.
    # It must never receive owner-only human ground-truth material.
    if any((root / name).exists() or (root / name).is_symlink() for name in
           ('owner-only-human-labels.json','owner-only-candidate-labels.json','labels.json')):
        raise Invalid('original human held labels entered model-only collector')
    details={}
    for model in MODELS:
        receipt_path=root / f'attempt-{model}.json'
        if not _regular(receipt_path,max_bytes=MAX_ATTEMPT_BYTES):
            details[model]={'status':'missing_attempt_receipt'}
            continue
        try:
            attempt=read(receipt_path,limit=MAX_ATTEMPT_BYTES + 1)
            if (type(attempt) is not dict or set(attempt) !=
                    {'schema','model','outcome','authority','production_promotion_permitted',
                     'held_test_labels_accessed'} or attempt.get('schema')!=ATTEMPT_SCHEMA or
                    attempt.get('model')!=model or attempt.get('authority')!='DENY_ALL' or
                    attempt.get('production_promotion_permitted') is not False or
                    attempt.get('held_test_labels_accessed') is not False or
                    attempt.get('outcome') not in ('model_report_written','failed_or_incomplete')):
                raise Invalid('invalid single model attempt evidence')
            produced=(root/f'{model}.json').is_file()
            failed=(root/f'{model}.failed.txt').is_file()
            if attempt['outcome']=='model_report_written' and (not produced or failed):
                raise Invalid('attempt success disagrees with original result')
            if attempt['outcome']=='failed_or_incomplete' and (not failed or produced):
                raise Invalid('attempt failure disagrees with original result')
            details[model]={'status':attempt['outcome']}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            details[model]={'status':'invalid_attempt_receipt',
                            'reason_type':type(exc).__name__}
    # This pre-existing independent source-bound V8 audit checks that every
    # original candidate report/replay can numerically be re-evaluated WITHOUT
    # labels, and that failures stay failures rather than becoming zero scores.
    inspection=audit_partial(fit,blind,root)
    observed={m:inspection['models'][m]['status'] for m in MODELS}
    complete=(all(details[m]['status']=='model_report_written' for m in MODELS)
              and all(observed[m]==ACCEPTED[m] for m in MODELS)
              and inspection['invalid_source_or_report_present'] is False
              and inspection['unavailable_model_count']==0
              and inspection['original_model_reports_numeric_or_identity_consistent']==4)
    result={'schema':SCHEMA,'model_attempts':details,'independent_v8_original_statuses':observed,
            'registered_model_count':4,'entire_four_model_population_present_and_v8_consistent':complete,
            'missing_or_failed_model_count':sum(details[m]['status']!='model_report_written' for m in MODELS),
            'full_pretrained_model_execution_independently_authenticated':False,
            'new_quality_or_future_outcomes_proven':False,
            'held_human_test_labels_accessed':False,
            'model_winner_selected':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}
    return result


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--fit',type=Path,required=True)
    a.add_argument('--blind',type=Path,required=True)
    a.add_argument('--artifacts-root',type=Path,required=True)
    a.add_argument('--output',type=Path,required=True)
    args=a.parse_args()
    fit=read(args.fit);blind=read(args.blind)
    ret=original_four_census(fit,blind,args.artifacts_root)
    save(args.output,ret)
    if not ret['entire_four_model_population_present_and_v8_consistent']:
        raise SystemExit('DENY_ALL: incomplete or invalid original four-model physical results')
    print('Four complete original self-reported source-based physical model artifacts; no independent origin authentication or production permission')

if __name__=='__main__':main()
