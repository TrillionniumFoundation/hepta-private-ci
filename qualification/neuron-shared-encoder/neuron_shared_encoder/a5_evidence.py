"""Fail-closed A5 *offline research schema* review; no source authenticity.

A list of five model names is not five real model executions. This checker
audits the exact output schema from run_real_encoder_matrix(..., five_arm=True).
Self-authored JSON may satisfy the schema but cannot prove training, source
signatures, prelabel chronology, NDU causality, or production FinalUse.
"""
from __future__ import annotations

import math
from typing import Any

from .validation_v3 import (
    BUDGETS, ENCODERS, FIVE_ARM_CANDIDATES, KINDS, is_commit_ref, is_digest,
)


def _finite_number(x: Any, *, positive: bool = False) -> bool:
    return (type(x) in (int, float) and math.isfinite(x)
            and (x > 0 if positive else x >= 0))


def _score_fields_good(score: Any) -> bool:
    if not isinstance(score, dict) or type(score.get('n')) is not int or score['n'] < 1:
        return False
    for name in ('accuracy', 'brier', 'ece_15', 'nll'):
        if not _finite_number(score.get(name)):
            return False
    return (0 <= score['accuracy'] <= 1 and
            0 <= score['ece_15'] <= 1 and
            0 <= score['brier'] <= 2)


def review_a5_execution(report: dict) -> dict:
    """Conservative structural review, never an independent execution attestation."""
    problems: list[str] = []
    if not isinstance(report, dict):
        report = {}
    if (report.get('experiment') != 'A5'
            or report.get('evidence_class') != 'REAL_MODEL_LOCAL_SHADOW'
            or report.get('production_admission') != 'BLOCKED'
            or report.get('independent_artifact_signatures_verified') is not False):
        problems.append('A5 real-offline, DENY_ALL source contract missing')
    if not is_digest(report.get('dataset_sha256')):
        problems.append('A5 dataset byte SHA-256 missing')
    dim = report.get('same_projected_width')
    if type(dim) is not int or not 1 <= dim <= 512:
        problems.append('A5 shared feature width invalid')
    common = report.get('same_training')
    if (not isinstance(common, dict)
            or type(common.get('seed')) is not int
            or type(common.get('steps')) is not int or common['steps'] < 1
            or type(common.get('batch')) is not int or common['batch'] < 1
            or not isinstance(common.get('optimizer'), str)
            or common['optimizer'].lower() != 'adamw'
            or not _finite_number(common.get('learning_rate'), positive=True)):
        problems.append('A5 common pinned optimizer/seed/update budget missing')
        common = {}
    records = report.get('encoders')
    expected_names = {name for name, _, _, _ in FIVE_ARM_CANDIDATES}
    if not isinstance(records, dict) or set(records) != expected_names:
        problems.append('A5 requires the exact five real Encoder result arms')
        records = records if isinstance(records, dict) else {}
    rows_reference = None
    labels_reference = None
    weight_ids = set()
    bundle_ids = set()
    completed = 0
    full_grid = {(kind, budget) for kind in KINDS for budget in BUDGETS}

    for name, backend, repository, expected_hidden in FIVE_ARM_CANDIDATES:
        entry = records.get(name)
        if not isinstance(entry, dict):
            problems.append(f'{name}: missing actual model execution result')
            continue
        if entry.get('backend_kind') != backend:
            problems.append(f'{name}: wrong frozen backend')
        upstream_repo = entry.get('upstream_repository')
        if (upstream_repo != repository if repository else
                not isinstance(upstream_repo, str) or not upstream_repo):
            problems.append(f'{name}: wrong upstream repository identity')
        revision = entry.get('upstream_revision')
        if not is_commit_ref(revision) or len(revision) != 40:
            problems.append(f'{name}: exact 40-character upstream revision required')
        for field in ('weights_sha256', 'checkpoint_bundle_sha256',
                      'tokenizer_sha256_claimed'):
            if not is_digest(entry.get(field)):
                problems.append(f'{name}: missing actual {field}')
        if is_digest(entry.get('weights_sha256')):
            if entry['weights_sha256'] in weight_ids:
                problems.append(f'{name}: reused other candidate model weight digest')
            weight_ids.add(entry['weights_sha256'])
        if is_digest(entry.get('checkpoint_bundle_sha256')):
            if entry['checkpoint_bundle_sha256'] in bundle_ids:
                problems.append(f'{name}: reused other candidate checkpoint bundle')
            bundle_ids.add(entry['checkpoint_bundle_sha256'])
        hidden = entry.get('hidden_size')
        if (type(hidden) is not int or not 1 <= hidden <= 4096 or
                (expected_hidden is not None and hidden != expected_hidden)):
            problems.append(f'{name}: actual model hidden width mismatch')
        if type(dim) is int and entry.get('projected_width') != dim:
            problems.append(f'{name}: inconsistent feature projection width')
        n = entry.get('input_rows')
        if type(n) is not int or n < 1 or (
                rows_reference is not None and n != rows_reference):
            problems.append(f'{name}: unequal actual input row count')
        elif rows_reference is None:
            rows_reference = n
        if not _finite_number(entry.get('encoder_seconds'), positive=True):
            problems.append(f'{name}: missing physical Encoder elapsed time')
        matrix = entry.get('trained_head_matrix')
        if not isinstance(matrix, dict) or (
                matrix.get('experiment') != 'E2'
                or matrix.get('production_admission') != 'BLOCKED'
                or matrix.get('evidence_class') != 'TRAINED_SHADOW'):
            problems.append(f'{name}: missing actual equal-budget Head training matrix')
            continue
        if common and (
                matrix.get('same_train_steps') != common.get('steps')
                or matrix.get('same_train_batch') != common.get('batch')
                or matrix.get('same_train_lr') != common.get('learning_rate')):
            problems.append(f'{name}: Head optimizer conditions mismatch')
        options = matrix.get('frozen_output_class_count')
        if type(options) is not int or not 2 <= options <= 16 or (
                labels_reference is not None and options != labels_reference):
            problems.append(f'{name}: frozen output option count mismatch')
        elif labels_reference is None:
            labels_reference = options
        if matrix.get('class_count_source') != 'frozen_registered_option_width':
            problems.append(f'{name}: Head class count not frozen from options')
        runs = matrix.get('candidates')
        if not isinstance(runs, list):
            problems.append(f'{name}: no Head experiment receipts')
            continue
        seen: set[tuple[str, int]] = set()
        trained = 0
        for arm in runs:
            if not isinstance(arm, dict):
                problems.append(f'{name}: non-object Head trial')
                continue
            kind, budget = arm.get('kind'), arm.get('budget')
            if (kind, budget) not in full_grid or (kind, budget) in seen:
                problems.append(f'{name}: duplicate/missing/unregistered Head budget arm')
                continue
            seen.add((kind, budget))
            if arm.get('status') == 'OVER_BUDGET':
                continue
            if arm.get('status') != 'EVALUATED_SHADOW':
                problems.append(f'{name}: Head trial lacks actual execution status')
                continue
            count = arm.get('parameters')
            if (type(count) is not int or not 1 <= count <= budget
                    or arm.get('parameter_bytes_fp32') != count * 4
                    or type(arm.get('optimizer_state_bytes')) is not int
                    or arm['optimizer_state_bytes'] < 0
                    or not _finite_number(arm.get('train_seconds'))):
                problems.append(f'{name}: fabricated/incomplete trained parameter cost')
                continue
            if not all(_score_fields_good(arm.get(split))
                       for split in ('validation', 'future')):
                problems.append(f'{name}: missing held-out/future decision metrics')
                continue
            auroc = arm.get('ood_auroc_msp')
            if not _finite_number(auroc) or auroc > 1:
                problems.append(f'{name}: missing OOD detection metric')
                continue
            trained += 1
        if seen != full_grid:
            problems.append(f'{name}: incomplete full 8-Head x 4-budget matrix')
        if trained < 1:
            problems.append(f'{name}: zero actually trained eligible Heads')
        else:
            completed += 1
        if backend == 'laya-joint':
            orig = entry.get('original_laya_system_one')
            if not isinstance(orig, dict) or not all(
                    _score_fields_good(orig.get(s)) for s in ('validation', 'future', 'ood')):
                problems.append('Laya: missing original full-System-One teacher policy')
            elif not _finite_number(orig.get('ood_auroc_msp')) or orig['ood_auroc_msp'] > 1:
                problems.append('Laya: missing original full-policy OOD result')
    return {
        'experiment': 'A5-execution-integrity',
        'status': 'SCHEMA_COMPLETE_UNVERIFIED' if not problems else 'BLOCKED',
        'issues': problems,
        'five_expected_models': len(FIVE_ARM_CANDIDATES),
        'arms_with_training_receipts': completed,
        'independent_model_load_verified': False,
        'independent_data_use_verified': False,
        'production_admission': 'BLOCKED',
        'warning': ('Self-authored weight digests and metrics are neither signed '
                    'model-load attestations nor proof of equal real hardware, '
                    'frozen data, genuine future predictions or NDU benefit.'),
    }
