"""A/B/C independent-input research audits. Never grants model or effect authority.

This package can validate *self-reported* aligned artifacts but cannot verify
an issuer signature, no-change provenance, authentic pre-label publication,
actual model execution, NDU causality, worker resource attestation or FinalUse.
No implicit downloads, synthetic outcome imputation or production promotion.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
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
    # A changed Encoder, feature normalization, input formatting or runtime
    # can manufacture a "learning" lift even with identical Head weights.
    # Frozen and learned Head must bind the same exact frozen features.
    frozen = snapshots['frozen_head']
    learned = snapshots['learned_head']
    for field in ('encoder_bundle_sha256', 'feature_pipeline_sha256',
                  'runtime_profile_sha256', 'input_contract_sha256'):
        left, right = frozen.get(field), learned.get(field)
        if not is_digest(left) or not is_digest(right) or left != right:
            raise ValueError(f'Frozen/Learned feature-runtime mismatch: {field}')
    frozen_digest = frozen.get('head_digest')
    head_before = learned.get('head_digests_by_row')
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
    first_index = ordered[0]
    if not torch.allclose(
            tensors['frozen_head'][first_index],
            tensors['learned_head'][first_index], atol=1e-7, rtol=0):
        raise ValueError('first future matched Head prediction differs before any learning')
    records = journal.get('records')
    updates = bundle.get('postlabel_updates')
    if not isinstance(records, list) or len(records) != len(ordered):
        raise ValueError('one ordered, label-free precommit record per future row required')
    if not isinstance(updates, list) or len(updates) != len(ordered):
        raise ValueError('one separately recorded post-label update per future row required')
    expected_next_head = frozen_digest
    previous_update_time = None
    applied_updates = 0
    skipped_updates = 0
    for index, event, update in zip(ordered, records, updates):
        row = rows[index]
        required = {
            'row_id', 'future_window', 'frozen_head_digest',
            'learned_head_digest_before', 'input_digest',
            'prediction_digests', 'predicted_at',
        }
        if not isinstance(event, dict) or set(event) != required:
            raise ValueError('unknown/missing or label-bearing precommit fields')
        if event.get('row_id') != row['row_id'] or event.get('future_window') != row['future_window']:
            raise ValueError('out-of-order/missing future precommit')
        if (event.get('frozen_head_digest') != frozen_digest or
                event.get('learned_head_digest_before') != head_before[index]):
            raise ValueError('pre-label Head identity mismatch')
        if head_before[index] != expected_next_head:
            raise ValueError('learned Head digest chain fork/missing previous update')
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
        if predicted < _datetime(row['event_time']):
            raise ValueError('prediction timestamp precedes the event')
        if previous_update_time is not None and predicted < previous_update_time:
            raise ValueError('next prediction preceded previous Head update')
        # A separate post-label journal cannot be smuggled into the
        # label-free precommit object; its link is the exact prediction hash.
        update_fields = {
            'row_id', 'head_digest_before', 'head_digest_after',
            'prediction_record_digest', 'label_digest',
            'label_available_at', 'updated_at', 'update_kind',
        }
        if not isinstance(update, dict) or set(update) != update_fields:
            raise ValueError('missing, unknown or ambiguous post-label update fields')
        if update['row_id'] != row['row_id'] or update['head_digest_before'] != head_before[index]:
            raise ValueError('post-label update Head identity mismatch')
        if update['prediction_record_digest'] != canonical_digest(event):
            raise ValueError('post-label update does not bind the sealed prediction')
        if update['label_digest'] != canonical_digest({
                'row_id': row['row_id'], 'label': row['label']}):
            raise ValueError('post-label update label identity mismatch')
        # Actual label availability is observed only AFTER prediction
        # sealing, never inserted into a pre-label record retrospectively.
        revealed = _datetime(update['label_available_at'])
        if predicted >= revealed:
            raise ValueError('prediction was not chronologically pre-label')
        update_time = _datetime(update['updated_at'])
        if update_time <= revealed:
            raise ValueError('Head update occurred before label availability')
        if not is_digest(update['head_digest_after']):
            raise ValueError('post-label successor Head digest invalid')
        if update['update_kind'] == 'updated':
            if update['head_digest_after'] == head_before[index]:
                raise ValueError('claimed Head update without new weights')
            applied_updates += 1
        elif update['update_kind'] == 'no_update':
            if update['head_digest_after'] != head_before[index]:
                raise ValueError('no-update must retain identical Head weights')
            skipped_updates += 1
        else:
            raise ValueError('invalid post-label update disposition')
        expected_next_head = update['head_digest_after']
        previous_update_time = update_time
    if snapshots['learned_head'].get('final_head_digest') != expected_next_head:
        raise ValueError('learned final Head differs from committed successor chain')
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
        window_scores = {
            role: _scores(tensors[role][ids], labels[ids])
            for role in ROLES
        }
        for score in window_scores.values():
            # _scores returns unnormalized multiclass Brier; the paired
            # comparison below uses /width. Publish both unambiguously.
            score['brier_normalized'] = score['brier'] / width
        report = {
            'groups': len(groups), 'cases': len(ids),
            'scores': window_scores,
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
        'postlabel_head_update_chain_consistent': True,
        'postlabel_update_count': applied_updates,
        'postlabel_no_update_count': skipped_updates,
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
    for field in ('scope_id', 'principal_id'):
        value = manifest.get(field)
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            problems.append(f'missing exact C experiment scope: {field}')
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
    shared_text_stem = None
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
        candidate_stem = stage.get('shared_text_stem_sha256')
        if not is_digest(candidate_stem):
            problems.append(f'{name}: unpinned shared text Stem weights')
        elif shared_text_stem is not None and candidate_stem != shared_text_stem:
            problems.append(f'{name}: text Stem weights changed during modality differentiation')
        if shared_text_stem is None:
            shared_text_stem = candidate_stem
        modality_adapter = stage.get('modality_adapter_sha256')
        if (name == 'text' and modality_adapter is not None) or (
            name != 'text' and not is_digest(modality_adapter)
        ):
            problems.append(f'{name}: invalid or missing modality adapter version')
        if name != 'text' and not is_digest(stage.get('paired_media_dataset_sha256')):
            problems.append(f'{name}: source-bound paired media cohort missing')
        if name != 'text' and not is_digest(stage.get('media_preprocessor_sha256')):
            problems.append(f'{name}: source-bound multimodal preprocessing identity missing')
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
                    scale.get('scope_id') != manifest.get('scope_id') or
                    scale.get('principal_id') != manifest.get('principal_id') or
                    scale.get('paired_text_workload_sha256') != manifest.get('paired_text_workload_sha256')):
                problems.append(f'{name}/{cells}: unmatched host/source/text workload')
            if (scale.get('active_cell_count') != cells or
                    scale.get('actually_executed_cell_count') != cells or
                    not _finite(scale.get('requests'), positive=True) or scale['requests'] < cells):
                problems.append(f'{name}/{cells}: logical-only or missing Cell execution coverage')
            if not isinstance(scale.get('run_id'), str) or not scale['run_id']:
                problems.append(f'{name}/{cells}: exact observed run identity required')
            if not is_digest(scale.get('recovery_trace_sha256')):
                problems.append(f'{name}/{cells}: independent reviewable recovery trace required')
            for field in ('encoder_forward_rows', 'encoder_batch_calls', 'throughput_rps',
                          'cpu_seconds', 'rss_peak_bytes', 'request_p95_ms', 'request_p99_ms',
                          'batch_p95_ms', 'batch_p99_ms',
                          'active_modality_peak_bytes', 'head_resident_bytes',
                          'queue_peak_depth', 'wal_fsync_count',
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
            if (name != 'text' and not _finite(
                    scale.get('active_modality_peak_bytes'), positive=True)):
                problems.append(f'{name}/{cells}: active modality physical memory missing')
            if (not _finite(scale.get('head_resident_bytes'), positive=True)
                    or not _finite(scale.get('wal_fsync_count'), positive=True)):
                problems.append(f'{name}/{cells}: active Heads or durable WAL not observed')
            if (_finite(scale.get('queue_peak_depth'))
                    and _finite(scale.get('requests'))
                    and scale['queue_peak_depth'] > scale['requests']):
                problems.append(f'{name}/{cells}: queue depth exceeds request cohort')
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
                'additional_4096_active_modality_peak_bytes': (
                    cohort[-1]['active_modality_peak_bytes']
                    - prior['scales'][-1]['active_modality_peak_bytes']
                    if _finite(cohort[-1].get('active_modality_peak_bytes'))
                    and _finite(prior['scales'][-1].get('active_modality_peak_bytes'))
                    else None),
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
        'scope_id': manifest.get('scope_id'), 'principal_id': manifest.get('principal_id'),
        'protocol_sha256': manifest.get('protocol_sha256'),
        'final_multimodal_model_sha256': stages[-1].get('artifact_sha256') if stages else None,
        'final_media_source_sha256': stages[-1].get('paired_media_dataset_sha256') if stages else None,
        'final_media_preprocessor_sha256': stages[-1].get('media_preprocessor_sha256') if stages else None,
        'status': 'SCHEMA_COMPLETE_UNVERIFIED' if not problems else 'BLOCKED',
        'issues': problems, 'stage_deltas': deltas,
        'target_host_attested': False, 'independent_real_model_runs_verified': False,
        'ndu_verification_present': False,
        'production_admission': 'BLOCKED', 'selection': 'NOT_AUTHORIZED',
        'warning': 'A complete telemetry table cannot establish real hardware, worker signatures, unclean WAL recovery, or NDU.',
    }



MEDIA_SEMANTIC_REQUIRED = (
    'holdout/image/media_substitution',
    'holdout/audio/media_substitution',
    'holdout/video/temporal_reordering',
)


def paired_media_necessity_audit(
    report: dict, policy: dict, *, expected_protocol_sha256: str | None = None,
    raw_predictions: dict | None = None,
    raw_labels: dict | None = None,
    expected_model_sha256: str | None = None,
    expected_media_source_sha256: str | None = None,
    expected_preprocessor_sha256: str | None = None,
    expected_scope_id: str | None = None,
) -> dict:
    """Audit PR #1774's *self-reported* truth-flip output, never source authority.

    Require all image/audio/video counterfactuals, including exact video-frame
    temporal reordering. This prevents a C resource-only or retrieval-only
    benchmark from pretending to prove media-conditioned decisions.
    """
    issues = []
    if not isinstance(report, dict) or report.get('schema') != 'hepta.stem.paired-modality-audit.v1':
        issues.append('PR1774 paired-media scorer output is absent/invalid')
        report = {}
    if not isinstance(policy, dict) or policy.get('schema') != 'hepta.stem.media-review-policy.v1':
        issues.append('externally preregistered media policy is absent')
        policy = {}
    policy_digest = policy.get('protocol_sha256')
    if (not is_digest(policy_digest) or
            (expected_protocol_sha256 is not None and
             policy_digest != expected_protocol_sha256)):
        issues.append('media protocol does not match frozen A/B/C study')
    if not all(is_digest(report.get(k)) for k in
               ('prediction_sha256', 'observer_receipt_sha256')):
        issues.append('paired prediction or external observer reference is unpinned')
    if report.get('actual_independent_observer_verified') is True or report.get('production_accepted') is True:
        issues.append('self-asserted independent authority not accepted')
    # Bind the actual PR1774 input bytes by its canonical prediction digest,
    # then bind model/preprocessor/media source to the final C video stage.
    # Schema validation is intentionally not PR1774's full semantic oracle:
    # re-run that scorer to independently check the truth labels/groups.
    expected_keys = {
        'schema', 'scope', 'model_sha256', 'preprocessor_sha256',
        'source_sha256', 'classes', 'pairs',
    }
    observed_raw_groups = defaultdict(int)
    if not isinstance(raw_predictions, dict) or set(raw_predictions) != expected_keys:
        issues.append('missing exact raw paired-media prediction payload')
    elif raw_predictions.get('schema') != 'hepta.stem.paired-modality-predictions.v1':
        issues.append('unsupported raw paired-media payload version')
    else:
        for key, expected in (
            ('model_sha256', expected_model_sha256),
            ('preprocessor_sha256', expected_preprocessor_sha256),
            ('source_sha256', expected_media_source_sha256),
        ):
            actual = raw_predictions.get(key)
            if not is_digest(actual) or (expected is not None and actual != expected):
                issues.append('media prediction source mismatch: ' + key)
        if (not isinstance(raw_predictions.get('scope'), str)
                or not raw_predictions['scope']
                or type(raw_predictions.get('classes')) is not int
                or not 2 <= raw_predictions['classes'] <= 16):
            issues.append('invalid raw media inference scope/classes')
        if expected_scope_id is not None and raw_predictions.get('scope') != expected_scope_id:
            issues.append('media input scope does not match the C benchmark owner scope')
        pairs = raw_predictions.get('pairs')
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 2048:
            issues.append('invalid raw paired media cohort')
        else:
            for pair in pairs:
                if not isinstance(pair, dict):
                    issues.append('non-object raw media pair')
                    continue
                split, kind, contrast = (
                    pair.get('split'), pair.get('modality'), pair.get('contrast_kind'))
                if (split not in ('holdout', 'retention')
                        or kind not in ('image', 'audio', 'video')
                        or contrast not in ('media_substitution', 'temporal_reordering')):
                    issues.append('unsupported raw media pair grouping')
                    continue
                observed_raw_groups['/'.join((split, kind, contrast))] += 1
        try:
            actual_digest = hashlib.sha256(json.dumps(
                raw_predictions, sort_keys=True, ensure_ascii=True,
                separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        except (ValueError, TypeError):
            issues.append('raw paired-media JSON has invalid finite encoding')
        else:
            # Canonical PR1774 uses json.dumps default ASCII encoding, so
            # non-ASCII media metadata must retain exactly those bytes.
            if actual_digest != report.get('prediction_sha256'):
                issues.append('media report is not bound to actual raw prediction bytes')
    # The group-level PR1774 summary alone is not proof of the stated
    # correct answer. Replay every prediction against the separately
    # provided paired truth, then compare ALL scorer counters exactly.
    # This remains an untrusted offline consistency check; model/media
    # origin, signer and independent labels are not authenticated here.
    replay = None
    try:
        from .media_truth_replay import replay_paired_media_truth
        replay = replay_paired_media_truth(raw_predictions, raw_labels, report)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        issues.append('paired-media label/score replay failed: ' + str(exc))
    min_pairs = policy.get('minimum_pairs_per_group')
    min_groups = policy.get('minimum_distinct_source_groups_per_group')
    accuracy = policy.get('minimum_both_correct_fraction')
    unresponsive = policy.get('maximum_unresponsive_fraction')
    if (type(min_pairs) is not int or min_pairs < 1
            or type(min_groups) is not int or min_groups < 1
            or min_groups > min_pairs
            or type(accuracy) not in (int, float) or
            not math.isfinite(accuracy) or not 0 <= accuracy <= 1
            or type(unresponsive) not in (int, float)
            or not math.isfinite(unresponsive) or not 0 <= unresponsive <= 1):
        issues.append('valid precommitted pair/group/accuracy/abstention limits required')
        min_pairs, min_groups, accuracy, unresponsive = None, None, None, None
    groups = report.get('groups') if isinstance(report.get('groups'), dict) else {}
    summaries = {}
    for key in MEDIA_SEMANTIC_REQUIRED:
        entry = groups.get(key)
        if not isinstance(entry, dict):
            issues.append('missing actual modality truth-flip group: ' + key)
            continue
        names = ('pairs', 'both_correct', 'original_correct', 'changed_correct',
                 'prediction_changed', 'unresponsive_to_truth_flip',
                 'distinct_source_groups')
        counts = [entry.get(name) for name in names]
        if any(type(v) is not int or v < 0 for v in counts):
            issues.append(key + ': nonnegative integer cohort/response counts required')
            continue
        pair_count, both, original, changed, moved, ignored, families = counts
        if observed_raw_groups.get(key) != pair_count:
            issues.append(key + ': scored pair count differs from bound raw media payload')
        if (pair_count == 0 or families > pair_count or
                max(both, original, changed, moved, ignored) > pair_count or
                both > min(original, changed) or moved + ignored != pair_count):
            issues.append(key + ': internally inconsistent paired truth-flip counts')
            continue
        summaries[key] = {
            'pairs': pair_count, 'source_groups': families,
            'both_correct_fraction': both / pair_count,
            'unresponsive_to_truth_flip_fraction': ignored / pair_count,
        }
        if min_pairs is not None and (pair_count < min_pairs or
                families < min_groups or both / pair_count < accuracy or
                ignored / pair_count > unresponsive):
            issues.append(key + ': preregistered semantic necessity threshold missed')
    return {
        'experiment': 'C-media-semantic-necessity',
        'status': 'SCHEMA_COMPLETE_UNVERIFIED' if not issues else 'BLOCKED',
        'issues': issues,
        'media_groups': summaries,
        'per_pair_truth_replay': replay,
        'independent_media_truth_verified': False,
        'independent_observer_verified': False,
        'ndu_utility_verified': False, 'production_admission': 'BLOCKED',
        'warning': ('A paired-media result and operator-authored policy do not '
                    'authenticate the media bytes, independent truth, frozen '
                    'pre-registration, or source/model signatures.'),
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
    media = paired_media_necessity_audit(
        bundle.get('media_counterfactual'), bundle.get('media_policy'),
        raw_predictions=bundle.get('media_predictions'),
        raw_labels=bundle.get('media_labels'),
        expected_protocol_sha256=c.get('protocol_sha256') if isinstance(c, dict) else None,
        expected_model_sha256=c.get('final_multimodal_model_sha256') if isinstance(c, dict) else None,
        expected_media_source_sha256=c.get('final_media_source_sha256') if isinstance(c, dict) else None,
        expected_preprocessor_sha256=c.get('final_media_preprocessor_sha256') if isinstance(c, dict) else None,
        expected_scope_id=c.get('scope_id') if isinstance(c, dict) else None)
    if media['status'] != 'SCHEMA_COMPLETE_UNVERIFIED':
        issues.append('multimodal counterfactual semantic necessity not established')
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
        'issues': issues, 'media_necessity': media,
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
    def finite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise ValueError('nonfinite JSON float exponent forbidden')
        return value
    obj = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(
        ValueError('nonfinite JSON extension forbidden')),
        parse_float=finite_float, object_pairs_hook=_strict_pairs)
    if not isinstance(obj, dict):
        raise ValueError('top-level evidence must be JSON object')
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('b-threeway', 'c-stages', 'media-pairs', 'abc-joint'))
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
    elif args.command == 'media-pairs':
        result = paired_media_necessity_audit(
            bundle.get('report'), bundle.get('policy'),
            raw_predictions=bundle.get('raw_predictions'),
            raw_labels=bundle.get('raw_labels'))
    else:
        result = joint_abc_evidence_gate(bundle)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                      encoding='utf-8')
    print(f'{args.command}: {output} (no selection authority)')


if __name__ == '__main__':
    main()
