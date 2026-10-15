#!/usr/bin/env python3
"""Source-bound, label-BLIND partial P0 artifact diagnosis (research / DENY_ALL).

When one of four model invocations fails, the existing all-or-nothing physical
job intentionally fails and prevents V5/V6/V7 promotion. This independent job
still audits each actually present ORIGINAL model receipt and, for the three
Encoder/Head arms, checks that its saved safetensors features and trained Head
reproduce all sealed predictions. Missing/failed models remain unavailable.

This can diagnose partial ORIGINAL source/model output; it never attests that
weights were genuinely loaded, provides task labels, ranks a Stem, certifies
physical hardware, or overrides the original all-four-model admission path.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import resource
import stat
import time

from p0_multirc_semantic_material import Invalid, canonical, read, save, sha, validate
from p0_multirc_semantic_review import REVISIONS
from p0_physical_replay_v5 import MODEL_WIDTHS, independent_numeric_replay

SCHEMA = 'hepta.p0.partial-physical-artifact-diagnostic.v8'
MODELS = (*MODEL_WIDTHS, 'laya421_nochange')
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_FAILED_BYTES = 4096


def _regular(path: Path, *, max_bytes: int) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    st = path.stat()
    return stat.S_ISREG(st.st_mode) and 2 < st.st_size <= max_bytes


def _laya_identity(blind: dict, report: dict):
    """Only a typed original Laya prediction-census check; NO weight replay."""
    if (type(report) is not dict or report.get('model') != 'laya421_nochange'
            or report.get('model_revision') != REVISIONS['laya421_nochange']
            or report.get('head_mode') != 'pretrained_checkpoint_native_noul_nochange_not_equal_head'
            or report.get('training') is not None
            or report.get('feature_width') is not None
            or report.get('matched_question_only_control') is not None
            or report.get('control') is None or type(report['control']) is not dict
            or set(report['control']) != {'laya_native_nochange'}):
        raise Invalid('original native Laya declared an impossible learned Head or wrong policy')
    arm = report['control']['laya_native_nochange']
    if type(arm) is not dict or set(arm) != {'predictions'} or type(arm['predictions']) is not list:
        raise Invalid('no original native Laya prediction census')
    expected = {r['case_id']:r['view_sha256'] for r in blind['cases']}
    seen = set()
    measured = 0.0
    for p in arm['predictions']:
        if (type(p) is not dict or set(p) != {'case_id','view_sha256','positive_probability','full_request_ms'}
                or type(p['case_id']) is not str or p['case_id'] not in expected
                or p['case_id'] in seen or p['view_sha256'] != expected[p['case_id']]
                or type(p['positive_probability']) not in (float,int)
                or not math.isfinite(p['positive_probability'])
                or not 0 <= p['positive_probability'] <= 1
                or type(p['full_request_ms']) not in (float,int)
                or not math.isfinite(p['full_request_ms']) or p['full_request_ms'] <= 0):
            raise Invalid('changed, missing, or invented native Laya task/prediction')
        measured += p['full_request_ms']
        seen.add(p['case_id'])
    if seen != set(expected) or len(seen) != len(blind['cases']):
        raise Invalid('native Laya lacks a complete blind prediction population')
    for name in ('local_process_wall_ms','local_process_cpu_ms','local_peak_rss_bytes','model_load_ms'):
        value = report.get(name)
        if type(value) not in (float,int) or not math.isfinite(value) or value<=0:
            raise Invalid('missing original native Laya resource measurement')
    if (report['model_load_ms'] > report['local_process_wall_ms']+5
            or measured > report['local_process_wall_ms']+5):
        raise Invalid('native Laya recorded impossible full-work timing')
    return {'native_frozen_prediction_count':len(seen),
            'numeric_recomputed_from_laya_weights':False,
            'actual_weight_source_independently_authenticated':False}


def audit_partial(fit, blind, root: Path):
    """Report per-model availability WITHOUT ever issuing four-model acceptance."""
    validate(fit, blind)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise Invalid('invalid original prediction artifact root')
    fit_sha=sha(canonical(fit));blind_sha=sha(canonical(blind))
    output={};all_valid=True;valid_count=0;unavailable_count=0
    for model in MODELS:
        report_file=root/f'{model}.json'
        failure=root/f'{model}.failed.txt'
        replay=root/f'{model}.replay'
        t0=time.perf_counter_ns()
        observation={'model':model,'numeric_scope':'partial-diagnostic-only',
                     'production_promotion_permitted':False,'authority':'DENY_ALL'}
        # Every apparent failed slot is retained, never converted into a zero-
        # quality prediction or silently ignored if a contradictory success exists.
        failure_present=failure.exists() or failure.is_symlink()
        model_present=report_file.exists() or report_file.is_symlink()
        replay_present=replay.exists() or replay.is_symlink()
        try:
            if failure_present:
                if not _regular(failure,max_bytes=MAX_FAILED_BYTES):
                    raise Invalid('unbounded/symlinked failed-model slot')
                if model_present or replay_present:
                    raise Invalid('contradictory model success and explicit failure slot')
                observation['status']='unavailable'
                observation['reason']='producer_declared_failed_model'
                unavailable_count+=1
            elif not model_present and not replay_present:
                observation['status']='unavailable'
                observation['reason']='no_original_producer_output'
                unavailable_count+=1
            else:
                if not _regular(report_file,max_bytes=MAX_REPORT_BYTES):
                    raise Invalid('original model report missing/unsafe/incomplete')
                if replay_present and replay.is_symlink():
                    raise Invalid('original artifact replay path is a symlink')
                report=read(report_file)
                if (type(report) is not dict or
                        report.get('schema')!='hepta.p0.multirc-original-semantic-physical.v1' or
                        report.get('dataset_schema')!=fit['metadata']['schema'] or
                        report.get('model')!=model or
                        report.get('model_revision')!=REVISIONS[model] or
                        report.get('panel_id')!=fit['metadata']['panel_id'] or
                        report.get('fit_material_sha256')!=fit_sha or
                        report.get('blind_material_sha256')!=blind_sha or
                        report.get('eval_blind_rows')!=len(blind['cases']) or
                        report.get('actual_pretrained_local_weights_claimed') is not True or
                        report.get('physical_model_origin_independently_signed') is not False or
                        report.get('model_selection_permitted') is not False or
                        report.get('production_promotion_permitted') is not False or
                        report.get('authority')!='DENY_ALL'):
                    raise Invalid('untrusted original model/Scope/model-quality fields')
                if model in MODEL_WIDTHS:
                    if not replay_present or not replay.is_dir():
                        raise Invalid('claim of trained Encoder/Head without committed tensor replay')
                    verified=independent_numeric_replay(replay,fit,blind,report,model=model)
                    if (verified.get('authority')!='DENY_ALL' or
                            verified.get('production_promotion_permitted') is not False or
                            verified.get('independent_task_quality_proven') is not False):
                        raise Invalid('partial model numeric replay falsely granted capability')
                    observation.update({'status':'original_head_numeric_replay_consistent',
                        'report_sha256':sha(report_file.read_bytes()),
                        'replay_commit_sha256':sha((replay/'COMMITTED.json').read_bytes()),
                        'recomputed_held_predictions':verified['replayed_original_and_question_head_predictions'],
                        'max_probability_difference':verified['max_probability_disagreement'],
                        'encoder_source_cold_verified_by_this_job':False,
                        'original_human_labels_seen':False})
                else:
                    if replay_present:
                        raise Invalid('Laya no-change cannot impersonate a small-Head tensor replay')
                    observation.update({'status':'laya_native_identity_only',
                        'report_sha256':sha(report_file.read_bytes()),
                        **_laya_identity(blind,report), 'original_human_labels_seen':False})
                valid_count+=1
        except (Invalid,KeyError,TypeError,ValueError,IndexError,OSError) as err:
            # Audit faults remain faults, never get relabeled as simply missing.
            observation['status']='invalid'
            observation['reason']='source_or_numeric_replay_rejected'
            observation['internal_rejection_class']=type(err).__name__
            all_valid=False
        observation['independent_diagnostic_wall_ms']=(time.perf_counter_ns()-t0)/1e6
        output[model]=observation
    return {'schema':SCHEMA,'models':output,'original_model_reports_numeric_or_identity_consistent':valid_count,
            'unavailable_model_count':unavailable_count,
            'invalid_source_or_report_present':not all_valid,
            'whole_four_model_success':False,
            'independent_real_pretrained_weight_origin_verified':False,
            'human_evaluation_labels_accessed':False,
            'task_quality_or_stem_ranking_computed':False,
            'source_head_accepted_for_production':False,
            'production_promotion_permitted':False,
            'authority':'DENY_ALL'}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--fit',type=Path,required=True)
    cli.add_argument('--blind',type=Path,required=True)
    cli.add_argument('--artifacts-root',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    opt=cli.parse_args()
    if opt.output.exists():
        raise FileExistsError('diagnostic source report is create only')
    report=audit_partial(read(opt.fit),read(opt.blind),opt.artifacts_root)
    save(opt.output,report)
    # An INVALID present model is a hard non-zero diagnosis. Merely MISSING
    # models are an observed fact, not a CI pass for scientific P0 acceptance.
    if report['invalid_source_or_report_present']:
        raise SystemExit('present original model artifacts failed source-bound audit')


if __name__=='__main__':
    main()
