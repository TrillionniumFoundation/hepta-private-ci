"""Strict offline replay of paired media truth flips from PR #1774.

This verifies *internal consistency* of prediction bytes, separately supplied
labels and aggregated scores. It DOES NOT authenticate the source media,
model weights, observer, timestamp of truth collection, NDU, or authority.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from typing import Any

PAIR_FIELDS = frozenset({
    'pair_id', 'source_group', 'split', 'modality', 'contrast_kind',
    'prompt_sha256', 'original_source_sha256', 'changed_source_sha256',
    'original_probabilities', 'changed_probabilities',
    'original_timestamps_us', 'changed_timestamps_us',
    'original_frames', 'changed_frames',
    'pair_wall_ns', 'pair_formula_flops',
})
PREDICTION_FIELDS = frozenset({
    'schema', 'scope', 'model_sha256', 'preprocessor_sha256',
    'source_sha256', 'classes', 'pairs',
})
TRUTH_FIELDS = frozenset({
    'schema', 'prediction_sha256', 'observer_receipt_sha256', 'labels',
})
MAX_PAIRS = 2048


class MediaReplayError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaReplayError(message)


def _digest(value: Any) -> str:
    try:
        data = json.dumps(value, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError) as exc:
        raise MediaReplayError('invalid canonical paired-media JSON') from exc
    return hashlib.sha256(data).hexdigest()


def _sha(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(
        char in '0123456789abcdef' for char in value)


def _identifier(value: Any) -> bool:
    return type(value) is str and 1 <= len(value) <= 128


def _probabilities(prob: Any, classes: int) -> None:
    _require(type(prob) is list and len(prob) == classes,
             'paired probability vector has wrong width')
    _require(all(type(v) in (float, int) and math.isfinite(v)
                 and 0 <= v <= 1 for v in prob),
             'paired probabilities must be finite and bounded')
    _require(abs(math.fsum(prob) - 1) <= 1e-6,
             'paired probabilities must sum to one')


def _timeline(times: Any) -> None:
    _require(type(times) is list and 2 <= len(times) <= 16
             and all(type(v) is int and 0 <= v < 2**63 for v in times)
             and all(b > a for a, b in zip(times, times[1:])),
             'video requires monotone bounded frame timestamps')


def replay_paired_media_truth(
    predictions: dict, labels: dict, report: dict,
) -> dict:
    """Reconstruct every PR #1774 score from exact paired predictions+truth.

    The caller MUST independently bind the same source/model/preprocessor
    and authorized principal/scope to C's final multimodal execution.
    """
    _require(type(predictions) is dict and set(predictions) == PREDICTION_FIELDS
             and predictions.get('schema') == 'hepta.stem.paired-modality-predictions.v1',
             'exact versioned paired-media predictions required')
    _require(_identifier(predictions['scope']) and all(_sha(predictions[key])
             for key in ('model_sha256', 'preprocessor_sha256', 'source_sha256')),
             'unbound paired-media scope/model/source')
    classes = predictions['classes']
    _require(type(classes) is int and 2 <= classes <= 16,
             'registered output class width invalid')
    pairs = predictions['pairs']
    _require(type(pairs) is list and 1 <= len(pairs) <= MAX_PAIRS,
             'unbounded or missing media prediction cohort')
    pair_digest = _digest(predictions)

    _require(type(labels) is dict and set(labels) == TRUTH_FIELDS
             and labels.get('schema') == 'hepta.stem.paired-modality-labels.v1',
             'external versioned paired-media truth manifest required')
    _require(labels['prediction_sha256'] == pair_digest
             and _sha(labels['observer_receipt_sha256']),
             'external truth does not bind exact paired prediction bytes')
    label_rows = labels['labels']
    _require(type(label_rows) is list and len(label_rows) == len(pairs),
             'paired truth must cover all prediction pairs')

    _require(type(report) is dict
             and report.get('schema') == 'hepta.stem.paired-modality-audit.v1'
             and report.get('prediction_sha256') == pair_digest
             and report.get('observer_receipt_sha256') == labels['observer_receipt_sha256'],
             'scored audit does not match source predictions/observer reference')

    by_id: dict[str, dict] = {}
    group_splits: dict[str, str] = {}
    for item in pairs:
        _require(type(item) is dict and set(item) == PAIR_FIELDS,
                 'incomplete or extra fields in paired media record')
        ident, family = item['pair_id'], item['source_group']
        _require(_identifier(ident) and _identifier(family) and ident not in by_id,
                 'missing/duplicate paired identity or source group')
        split, modality, contrast = item['split'], item['modality'], item['contrast_kind']
        _require(split in ('holdout', 'retention')
                 and modality in ('image', 'audio', 'video')
                 and contrast in ('media_substitution', 'temporal_reordering'),
                 'unregistered split/modality/contrast type')
        _require(family not in group_splits or group_splits[family] == split,
                 'source family crosses holdout and retention')
        group_splits[family] = split
        _require(all(_sha(item[k]) for k in
                     ('prompt_sha256', 'original_source_sha256', 'changed_source_sha256'))
                 and item['original_source_sha256'] != item['changed_source_sha256'],
                 'counterfactual does not change content-bound media')
        _probabilities(item['original_probabilities'], classes)
        _probabilities(item['changed_probabilities'], classes)
        if modality == 'video':
            _timeline(item['original_timestamps_us'])
            _timeline(item['changed_timestamps_us'])
        else:
            _require(item['original_timestamps_us'] is None
                     and item['changed_timestamps_us'] is None,
                     'nonvideo record cannot have video timestamps')
        if contrast == 'temporal_reordering':
            _require(modality == 'video'
                     and type(item['original_frames']) is list
                     and type(item['changed_frames']) is list,
                     'only video can declare frame-order counterfactual')
            original, changed = item['original_frames'], item['changed_frames']
            _require(len(original) == len(item['original_timestamps_us'])
                     and len(changed) == len(item['changed_timestamps_us'])
                     and all(_sha(x) for x in original + changed)
                     and sorted(original) == sorted(changed) and original != changed,
                     'temporal change must reorder identical actual frame inventory')
        else:
            _require(item['original_frames'] is None and item['changed_frames'] is None,
                     'unsupported frame metadata on non-reordering contrast')
        _require(type(item['pair_wall_ns']) is int and item['pair_wall_ns'] >= 0,
                 'measured per-pair duration must be nonnegative integer')
        flops = item['pair_formula_flops']
        _require(flops is None or (type(flops) is int and flops >= 0),
                 'formula FLOPs must be measured or explicitly null')
        by_id[ident] = item

    gold: dict[str, tuple[int, int]] = {}
    for item in label_rows:
        _require(type(item) is dict and set(item) ==
                 {'pair_id', 'original_label', 'changed_label'},
                 'external paired truth fields malformed')
        ident, original, changed = (item['pair_id'], item['original_label'],
                                    item['changed_label'])
        _require(ident in by_id and ident not in gold,
                 'extra or repeated external truth identity')
        _require(type(original) is int and type(changed) is int
                 and 0 <= original < classes and 0 <= changed < classes
                 and original != changed,
                 'independent contrast must change the correct answer')
        gold[ident] = (original, changed)
    _require(len(gold) == len(by_id), 'missing independently labeled media pairs')

    sums = defaultdict(lambda: {
        'pairs': 0, 'original_correct': 0, 'changed_correct': 0,
        'both_correct': 0, 'prediction_changed': 0,
        'unresponsive_to_truth_flip': 0, 'pair_wall_ns': 0,
        'known_flops': 0, 'all_flops_present': True, 'source_groups': set(),
    })
    for ident, item in by_id.items():
        original, changed = gold[ident]
        first = max(range(classes), key=item['original_probabilities'].__getitem__)
        second = max(range(classes), key=item['changed_probabilities'].__getitem__)
        key = '/'.join((item['split'], item['modality'], item['contrast_kind']))
        group = sums[key]
        group['pairs'] += 1
        group['original_correct'] += int(first == original)
        group['changed_correct'] += int(second == changed)
        group['both_correct'] += int(first == original and second == changed)
        group['prediction_changed'] += int(first != second)
        group['unresponsive_to_truth_flip'] += int(first == second)
        group['source_groups'].add(item['source_group'])
        group['pair_wall_ns'] += item['pair_wall_ns']
        if item['pair_formula_flops'] is None:
            group['all_flops_present'] = False
        else:
            group['known_flops'] += item['pair_formula_flops']

    scored = report.get('groups')
    _require(type(scored) is dict and set(scored) == set(sums),
             'scored media groups differ from actual prediction/label groups')
    metrics = (
        'pairs', 'original_correct', 'changed_correct', 'both_correct',
        'prediction_changed', 'unresponsive_to_truth_flip', 'pair_wall_ns',
        'distinct_source_groups', 'flop_coverage_complete', 'pair_formula_flops',
    )
    for name, expected in sums.items():
        aggregate = scored[name]
        _require(type(aggregate) is dict and set(aggregate) == set(metrics),
                 f'{name}: scored summary lacks exact measured metrics')
        computed = {
            key: value for key, value in expected.items()
            if key not in ('known_flops', 'all_flops_present', 'source_groups')
        }
        computed['distinct_source_groups'] = len(expected['source_groups'])
        computed['flop_coverage_complete'] = expected['all_flops_present']
        computed['pair_formula_flops'] = (
            expected['known_flops'] if expected['all_flops_present'] else None)
        for metric in metrics:
            value = aggregate[metric]
            _require(type(value) is type(computed[metric])
                     and value == computed[metric],
                     f'{name}: reported {metric} contradicts per-pair evidence')
    return {
        'pair_count': len(pairs),
        'group_count': len(sums),
        'label_payload_sha256': _digest(labels),
        'prediction_payload_sha256': pair_digest,
        'evidence_class': 'SELF_REPORTED_OFFLINE_REPLAY_ONLY',
        'independent_truth_verified': False,
        'production_admission': 'BLOCKED',
    }
