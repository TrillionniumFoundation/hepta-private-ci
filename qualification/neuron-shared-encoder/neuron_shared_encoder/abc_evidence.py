"""A/B/C independent-input research audits. Never grants model or effect authority.

This package can validate *self-reported* aligned artifacts but cannot verify
an issuer signature, no-change provenance, authentic pre-label publication,
actual model execution, NDU causality, worker resource attestation or FinalUse.
No implicit downloads, synthetic outcome imputation or production promotion.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any

import torch
from torch.nn import functional as F

from .contracts import _datetime, load_dataset, sha256_file
from .validation_v3 import (
    _scores, _validated_snapshot, canonical_digest, is_commit_ref, is_digest,
)

ROLES = ('frozen_no_change', 'frozen_head', 'learned_head')
WINDOWS = ('future_1', 'future_2')
STAGES = ('text', 'vision', 'audio', 'video')
SCALES = (64, 256, 1024, 4096)
TASKS = {
    'text': ('text_decision',),
    'vision': ('text_decision', 'image_text_retrieval', 'visual_relations'),
    'audio': ('text_decision', 'image_text_retrieval', 'visual_relations', 'audio_events'),
    'video': ('text_decision', 'image_text_retrieval', 'visual_relations',
              'audio_events', 'temporal_order'),
}


def _finite(value: Any, *, positive: bool = False) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def _group_interval(values: list[float], *, bootstrap: int, seed: int) -> tuple[float, float]:
    if not values or not 100 <= bootstrap <= 10000:
        raise ValueError('invalid grouped bootstrap cohort/budget')
    rng = random.Random(seed)
    size = len(values)
    draws = sorted(sum(values[rng.randrange(size)] for _ in range(size)) / size
                   for _ in range(bootstrap))
    return draws[int(.025 * (bootstrap - 1))], draws[int(.975 * (bootstrap - 1))]


def _require_timeline(rows: list[dict]) -> tuple[list[int], dict[str, list[int]]]:
    future = [i for i, r in enumerate(rows) if r['split'] == 'future']
    if not future or any(rows[i].get('future_window') not in WINDOWS for i in future):
        raise ValueError('future events need explicit future_1/future_2 windows')
    windows = {name: [i for i in future if rows[i]['future_window'] == name]
               for name in WINDOWS}
    if any(not ids for ids in windows.values()):
        raise ValueError('both future windows are mandatory')
    first = max(_datetime(rows[i]['event_time']) for i in windows['future_1'])
    second = min(_datetime(rows[i]['event_time']) for i in windows['future_2'])
    if first >= second:
        raise ValueError('future_2 must start strictly after future_1')
    groups = {}
    for i in future:
        key = (rows[i]['principal'], rows[i]['source_group'])
        prev = groups.setdefault(key, rows[i]['future_window'])
        if prev != rows[i]['future_window']:
            raise ValueError('source-group leakage across future windows')
    ordered = sorted(future, key=lambda i: (_datetime(rows[i]['event_time']), rows[i]['row_id']))
    if len({rows[i]['row_id'] for i in future}) != len(future):
        raise ValueError('duplicate future row ID')
    return ordered, windows


def threeway_prequential_audit(
    rows: list[dict], dataset_sha256: str, bundle: dict, *,
    min_future_groups: int = 30, bootstrap: int = 2000, seed: int = 42,
) -> dict:
    """B: compare true no-change, immutable frozen and learned Head per event.

    Per-label precommit hash/time checks are necessary, not sufficient: a
    self-authored trace can be forged. No outcome is used to fit a model here.
    """
    if not is_digest(dataset_sha256) or not rows or type(min_future_groups) is not int or min_future_groups < 1:
        raise ValueError('approved dataset pin/cohort minimum required')
    if not 100 <= bootstrap <= 10000:
        raise ValueError('invalid bootstrap budget')
    if not isinstance(bundle, dict) or bundle.get('dataset_sha256') != dataset_sha256:
        raise ValueError('B snapshot bundle/dataset mismatch')
    snapshots = bundle.get('snapshots')
    journal = bundle.get('prelabel_journal')
    if not isinstance(snapshots, dict) or set(snapshots) != set(ROLES) or not isinstance(journal, dict):
        raise ValueError('all three exact snapshots and a pre-label journal required')
    tensors = {role: _validated_snapshot(snapshots[role], rows, dataset_sha256, role)
               for role in ROLES}
    artifacts = [snapshots[role]['artifact_digest'] for role in ROLES]
    if len(set(artifacts)) != 3:
        raise ValueError('no-change, frozen and learned artifacts must be distinct')
    frozen_digest = snapshots['frozen_head'].get('head_digest')
    head_before = snapshots['learned_head'].get('head_digests_by_row')
    if snapshots['learned_head'].get('initial_head_digest') != frozen_digest:
        raise ValueError('learned and frozen Heads lack identical initialization')
    if (not is_digest(frozen_digest) or
            not isinstance(head_before, list) or len(head_before) != len(rows) or
            any(not is_digest(d) for d in head_before)):
        raise ValueError('frozen Head and each per-event learned Head revision required')
    if journal.get('frozen_head_digest') != frozen_digest:
        raise ValueError('matched frozen Head identity drift')
    threshold = journal.get('acceptance_threshold')
    if not _finite(threshold, positive=True) or threshold >= 1:
        raise ValueError('precommitted acceptance threshold required')
    ordered, windows = _require_timeline(rows)
    if head_before[ordered[0]] != frozen_digest:
        raise ValueError('first future learned Head must equal frozen initialization')
    records = journal.get('records')
    if not isinstance(records, list) or len(records) != len(ordered):
        raise ValueError('one ordered, label-free precommit record per future row required')
    for index, event in zip(ordered, records):
        row = rows[index]
        required = {
            'row_id', 'future_window', 'frozen_head_digest',
            'learned_head_digest_before', 'input_digest',
            'prediction_digests', 'predicted_at', 'label_available_at',
        }
        if not isinstance(event, dict) or set(event) != required:
            raise ValueError('unknown/missing or label-bearing precommit fields')
        if event.get('row_id') != row['row_id'] or event.get('future_window') != row['future_window']:
            raise ValueError('out-of-order/missing future precommit')
        if (event.get('frozen_head_digest') != frozen_digest or
                event.get('learned_head_digest_before') != head_before[index]):
            raise ValueError('pre-label Head identity mismatch')
        expected_input = canonical_digest({
            'state': row['state'], 'question': row['question'], 'options': row['options'],
        })
        if event.get('input_digest') != expected_input:
            raise ValueError('pre-label input identity mismatch')
        for role in ROLES:
            pred_digest = canonical_digest({
                'row_id': row['row_id'], 'probabilities': snapshots[role]['probabilities'][index],
            })
            if not isinstance(event.get('prediction_digests'), dict) or event['prediction_digests'].get(role) != pred_digest:
                raise ValueError('prediction changed after pre-label seal')
        predicted = _datetime(event.get('predicted_at'))
        revealed = _datetime(event.get('label_available_at'))
        if predicted >= revealed or predicted < _datetime(row['event_time']):
            raise ValueError('prediction was not chronologically pre-label')
    labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
    width = tensors['learned_head'].shape[1]
    per_row = {role: ((values - F.one_hot(labels, width).float()).square().sum(1)
                      / width) for role, values in tensors.items()}
    window_reports = {}
    sufficient = True
    for widx, window in enumerate(WINDOWS):
        ids = windows[window]
        groups = defaultdict(list)
        for i in ids:
            groups[(rows[i]['principal'], rows[i]['source_group'])].append(i)
        report = {
            'groups': len(groups), 'cases': len(ids),
            'scores': {role: _scores(tensors[role][ids], labels[ids]) for role in ROLES},
            'paired_normalized_brier_improvement': {},
        }
        for r_index, comparator in enumerate(('frozen_no_change', 'frozen_head')):
            deltas = [float((per_row[comparator][indexes]
                             - per_row['learned_head'][indexes]).mean())
                      for indexes in groups.values()]
            lo, hi = _group_interval(deltas, bootstrap=bootstrap,
                                     seed=seed + 2 * widx + r_index)
            negative = sum(x < -1e-6 for x in deltas)
            report['paired_normalized_brier_improvement'][comparator] = {
                'group_mean': sum(deltas) / len(deltas),
                'bootstrap_95pct': [lo, hi],
                'negative_transfer_groups': negative,
                'negative_transfer_fraction': negative / len(deltas),
            }
            if len(groups) < min_future_groups or lo <= 0 or negative:
                sufficient = False
        report['abstention_fraction'] = {
            role: float((tensors[role][ids].max(1).values < threshold).float().mean())
            for role in ROLES
        }
        window_reports[window] = report
    ood_ids = [i for i, row in enumerate(rows) if row['split'] == 'ood']
    if not ood_ids:
        raise ValueError('OOD holdout missing')
    ood = {role: float((tensors[role][ood_ids].max(1).values >= threshold).float().mean())
           for role in ROLES}
    # OOD/retention limits MUST come from an independent, preregistered policy.
    # Report their values but never self-authorize a selection.
    return {
        'experiment': 'B-threeway', 'dataset_sha256': dataset_sha256,
        'status': 'PAIRED_SELF_REPORTED_SHADOW',
        'production_admission': 'BLOCKED', 'selection': 'NOT_AUTHORIZED',
        'self_reported_prelabel_timeline_consistent': True,
        'durable_external_prelabel_witness_verified': False,
        'independent_no_change_and_ndu_verified': False,
        'future_windows': window_reports,
        'retention_validation': {
            role: _scores(tensors[role][
                [i for i, r in enumerate(rows) if r['split'] == 'validation']],
                labels[[i for i, r in enumerate(rows) if r['split'] == 'validation']])
            for role in ROLES
        },
        'ood_false_acceptance_fraction': ood,
        'decision_threshold_calibration_independently_verified': False,
        'future_brier_precheck_positive': sufficient,
        'warning': 'Self-reported hashes and times cannot prove independent pre-label collection, NDU, or source signatures.',
    }


def multimodal_cost_audit(manifest: dict) -> dict:
    """C: enforce a staged full-active 64/256/1024/4096 paired host protocol."""
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return {'experiment': 'C-stages', 'status': 'BLOCKED',
                'issues': ['manifest must be an object'], 'production_admission': 'BLOCKED'}
    for name in ('dataset_sha256', 'protocol_sha256', 'paired_text_workload_sha256'):
        if not is_digest(manifest.get(name)):
            problems.append(f'missing study identity {name}')
    if not is_commit_ref(manifest.get('source_commit')) or not isinstance(manifest.get('host_id'), str) or not manifest['host_id']:
        problems.append('missing exact source commit or target host')
    allowed_drop = manifest.get('max_retained_task_score_drop')
    if not _finite(allowed_drop) or allowed_drop > 1:
        problems.append('preregistered retained-task regression limit required')
        allowed_drop = 0
    stages = manifest.get('stages')
    if not isinstance(stages, list) or [s.get('stage') if isinstance(s, dict) else None for s in stages] != list(STAGES):
        problems.append('exact text -> vision -> audio -> video stages required')
        stages = []
    deltas = []
    previous = None
    text_probe = None
    seen_tasks: dict[str, tuple[str, int, float]] = {}
    for stage in stages:
        name = stage['stage']
        if not is_digest(stage.get('artifact_sha256')) or not is_commit_ref(stage.get('model_revision')):
            problems.append(f'{name}: unpinned model/revision')
        probe = stage.get('frozen_text_probe_sha256')
        if not is_digest(probe):
            problems.append(f'{name}: missing frozen text probe')
        elif text_probe is not None and probe != text_probe:
            problems.append(f'{name}: original text embedding changed without migration')
        if text_probe is None:
            text_probe = probe
        for field in ('total_parameters', 'trainable_parameters', 'projection_parameters',
                      'resident_weights_bytes', 'peak_training_memory_bytes', 'training_seconds'):
            if not _finite(stage.get(field)):
                problems.append(f'{name}: invalid {field}')
        if (all(_finite(stage.get(k)) for k in
                ('total_parameters', 'trainable_parameters', 'projection_parameters'))
                and (stage['trainable_parameters'] > stage['total_parameters']
                     or stage['projection_parameters'] > stage['trainable_parameters'])):
            problems.append(f'{name}: impossible trainable/projector parameter counts')
        tasks = stage.get('tasks')
        if not isinstance(tasks, dict) or set(tasks) != set(TASKS[name]):
            problems.append(f'{name}: incomplete current and retained modality tasks')
            tasks = {}
        for task in TASKS[name]:
            value = tasks.get(task)
            if not isinstance(value, dict) or not is_digest(value.get('dataset_sha256')) or (
                type(value.get('cases')) is not int or value['cases'] < 1
            ) or not _finite(value.get('score')) or value['score'] > 1:
                problems.append(f'{name}: invalid {task} truth task cohort')
                continue
            if task in seen_tasks:
                old_pin, old_n, old_score = seen_tasks[task]
                if (old_pin, old_n) != (value['dataset_sha256'], value['cases']):
                    problems.append(f'{name}: changed previously frozen {task} cohort')
                if value['score'] < old_score - allowed_drop - 1e-9:
                    problems.append(f'{name}: negative transfer above registered limit for {task}')
            else:
                # Retain the FIRST stage's frozen task score, not the
                # immediately preceding score: repeated small regressions
                # must not conceal cumulative negative transfer.
                seen_tasks[task] = (value['dataset_sha256'], value['cases'], value['score'])
        cohort = stage.get('scales')
        if not isinstance(cohort, list) or [r.get('cell_count') if isinstance(r, dict) else None for r in cohort] != list(SCALES):
            problems.append(f'{name}: missing 64/256/1024/4096 ordered full-active trials')
            continue
        for scale in cohort:
            cells = scale['cell_count']
            if (scale.get('host_id') != manifest.get('host_id') or
                    scale.get('source_commit') != manifest.get('source_commit') or
                    scale.get('paired_text_workload_sha256') != manifest.get('paired_text_workload_sha256')):
                problems.append(f'{name}/{cells}: unmatched host/source/text workload')
            if (scale.get('active_cell_count') != cells or
                    scale.get('actually_executed_cell_count') != cells or
                    not _finite(scale.get('requests'), positive=True) or scale['requests'] < cells):
                problems.append(f'{name}/{cells}: logical-only or missing Cell execution coverage')
            for field in ('encoder_forward_rows', 'encoder_batch_calls', 'throughput_rps',
                          'cpu_seconds', 'rss_peak_bytes', 'request_p95_ms', 'request_p99_ms',
                          'batch_p95_ms', 'batch_p99_ms',
                          'wal_written_bytes', 'recovery_seconds', 'failed_replay_count',
                          'latency_cas_p99_ms', 'latency_signature_p99_ms', 'latency_cns_p99_ms'):
                if not _finite(scale.get(field)):
                    problems.append(f'{name}/{cells}: invalid {field}')
            if (not _finite(scale.get('encoder_batch_calls'), positive=True) or
                    not _finite(scale.get('encoder_forward_rows'), positive=True) or
                    scale['encoder_batch_calls'] > scale['encoder_forward_rows']):
                problems.append(f'{name}/{cells}: impossible Encoder batch counters')
            if (_finite(scale.get('request_p95_ms')) and _finite(scale.get('request_p99_ms'))
                    and scale['request_p99_ms'] < scale['request_p95_ms']):
                problems.append(f'{name}/{cells}: request p99 lower than p95')
            if (_finite(scale.get('batch_p95_ms')) and _finite(scale.get('batch_p99_ms'))
                    and scale['batch_p99_ms'] < scale['batch_p95_ms']):
                problems.append(f'{name}/{cells}: batch p99 lower than p95')
            if any(not _finite(scale.get(f), positive=True) for f in
                   ('throughput_rps', 'cpu_seconds', 'rss_peak_bytes',
                    'request_p95_ms', 'request_p99_ms', 'wal_written_bytes')):
                problems.append(f'{name}/{cells}: absent/nonpositive measured workload')
            if (scale.get('device') != 'cpu' and not _finite(scale.get('gpu_peak_bytes'))
                    or scale.get('unclean_crash_recovered') is not True):
                problems.append(f'{name}/{cells}: missing GPU/crash-recovery observation')
        if previous is not None and all(
            _finite(stage.get(k)) and _finite(previous.get(k))
            for k in ('total_parameters', 'resident_weights_bytes')
        ):
            prior = previous
            deltas.append({
                'transition': prior['stage'] + '_to_' + name,
                'additional_parameters': stage['total_parameters'] - prior['total_parameters'],
                'additional_resident_weights_bytes':
                    stage['resident_weights_bytes'] - prior['resident_weights_bytes'],
                'additional_4096_cell_peak_rss_bytes':
                    cohort[-1]['rss_peak_bytes'] - prior['scales'][-1]['rss_peak_bytes']
                    if _finite(cohort[-1].get('rss_peak_bytes')) and
                       _finite(prior['scales'][-1].get('rss_peak_bytes')) else None,
                'prior_task_score_deltas': {
                    task: tasks[task]['score'] - prior['tasks'][task]['score']
                    for task in TASKS[prior['stage']]
                    if isinstance(tasks.get(task), dict) and isinstance(prior.get('tasks', {}).get(task), dict)
                       and _finite(tasks[task].get('score')) and _finite(prior['tasks'][task].get('score'))
                },
            })
        previous = stage
    return {
        'experiment': 'C-stages', 'dataset_sha256': manifest.get('dataset_sha256'),
        'status': 'SCHEMA_COMPLETE_UNVERIFIED' if not problems else 'BLOCKED',
        'issues': problems, 'stage_deltas': deltas,
        'target_host_attested': False, 'independent_real_model_runs_verified': False,
        'ndu_verification_present': False,
        'production_admission': 'BLOCKED', 'selection': 'NOT_AUTHORIZED',
        'warning': 'A complete telemetry table cannot establish real hardware, worker signatures, unclean WAL recovery, or NDU.',
    }


def joint_abc_evidence_gate(bundle: dict) -> dict:
    """Cross-check the SAME dataset through A5/B/C, never pick a live model.

    A successful self-reported schema is a research review prerequisite only.
    A signature, causality, NDU and FinalUse can never be inferred here.
    """
    issues = []
    if not isinstance(bundle, dict):
        bundle = {}
    a, b, c = (bundle.get(k) for k in ('A', 'B', 'C'))
    if not all(isinstance(x, dict) for x in (a, b, c)):
        issues.append('need all A5, B-threeway, C-stages reports')
    else:
        from .validation_v3 import FIVE_ARM_CANDIDATES
        if a.get('experiment') != 'A5' or a.get('evidence_class') != 'REAL_MODEL_LOCAL_SHADOW':
            issues.append('five actual local model runs missing')
        elif set(a.get('encoders', {})) != {x[0] for x in FIVE_ARM_CANDIDATES}:
            issues.append('A5 model inventory incomplete')
        if b.get('experiment') != 'B-threeway' or not b.get('future_brier_precheck_positive'):
            issues.append('no paired learned-Head future advantage over BOTH controls')
        if c.get('experiment') != 'C-stages' or c.get('status') != 'SCHEMA_COMPLETE_UNVERIFIED':
            issues.append('all real-stage resource/multimodal rows missing')
        pins = [x.get('dataset_sha256') for x in (a, b, c)]
        if not all(is_digest(p) for p in pins) or len(set(pins)) != 1:
            issues.append('A/B/C dataset provenance is not identical')
    return {
        'experiment': 'ABC-joint',
        'status': 'RESEARCH_REVIEW_CANDIDATE_UNVERIFIED' if not issues else 'BLOCKED',
        'issues': issues,
        'candidate_stem_selected': None, 'production_admission': 'BLOCKED',
        'independent_ndu_and_final_use_verified': False,
        'warning': 'Even complete A/B/C files are self-reported. Only independent evaluator, selector and executor may authorize a production change.',
    }


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON object field')
        result[key] = value
    return result


def _pinned_json(path: str, expected: str) -> dict:
    if not is_digest(expected) or sha256_file(path) != expected:
        raise ValueError('pinned evidence bytes mismatch')
    raw = Path(path).read_text(encoding='utf-8')
    obj = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(
        ValueError('nonfinite JSON extension forbidden')), object_pairs_hook=_strict_pairs)
    if not isinstance(obj, dict):
        raise ValueError('top-level evidence must be JSON object')
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('b-threeway', 'c-stages', 'abc-joint'))
    parser.add_argument('--input-json', required=True)
    parser.add_argument('--input-sha256', required=True)
    parser.add_argument('--dataset')
    parser.add_argument('--dataset-sha256')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    bundle = _pinned_json(args.input_json, args.input_sha256)
    if args.command == 'b-threeway':
        if not args.dataset or not args.dataset_sha256:
            raise ValueError('B requires independently approved, pinned chronological dataset')
        rows, data = load_dataset(args.dataset, expected_sha256=args.dataset_sha256)
        result = threeway_prequential_audit(rows, data['dataset_sha256'], bundle)
    elif args.command == 'c-stages':
        result = multimodal_cost_audit(bundle)
    else:
        result = joint_abc_evidence_gate(bundle)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                      encoding='utf-8')
    print(f'{args.command}: {output} (no selection authority)')


if __name__ == '__main__':
    main()
