"""Read-only, exact-run research audit of a GitHub-hosted ModernBERT result ZIP.

Only archived public research provenance / numerical claims are checked. The
archive does not include the original text or the model's hidden states, so
this audit NEVER substitutes for a fresh model forward or an NDU evaluator.
No network, path extraction, Pickle, Torch, signature, authority or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import struct
from zipfile import ZipFile, BadZipFile

SCHEMA = 'hepta.neuron.actual-hosted-token-archive-review.shadow.v1'
ARTIFACT_SHA256 = '8c2a5bb4b9d2cbc0b298829d90fe7bee17c6bd9e20eebd68bb5ceb1c875b38f5'
ORIGINAL_SOURCE_SHA256 = '1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2'
MODEL_REVISION = 'fa3113d09d6dacfe5528708803dd92a62240237a'
MODEL_ID = 'answerdotai/ModernBERT-base'
GITHUB_HEAD = 'b68d1c2937510eebb02a436d7c1096c0087b5edb'
RUN_ID = 38590216816
ARTIFACT_ID = 11923659430
SEEDS = (11, 23, 47)
KINDS = ('pooled_cached', 'token_query_prepared')
SPLITS = ('calibration', 'holdout')
EXPECTED_TENSORS = {
    'query': [768], 'down.weight': [8, 768], 'up.weight': [768, 8],
    'classifier.weight': [4, 768], 'classifier.bias': [4],
}
META_FILES = {
    'hepta-modernbert-acquisition.json', 'hepta-token-budget-preflight.json',
    'hepta-token-independent-review.json', 'hepta-real-token-pair/report.json',
}
HEADS = {(s, c, k): f'hepta-real-token-pair/seed-{s}-cell-{c}-{k}/'
         for s in SEEDS for c in (0, 1) for k in KINDS}
EXPECTED_FILES = META_FILES | {root + ending for root in HEADS.values()
                               for ending in ('manifest.json', 'head.safetensors')}
MAX_ARCHIVE = 2_000_000
MAX_TOTAL_UNCOMPRESSED = 3_000_000


def fail(message: str) -> None:
    raise ValueError('hosted token evidence rejected: ' + message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            fail('duplicate JSON key')
        result[key] = value
    return result


def _json(raw: bytes) -> dict:
    try:
        obj = json.loads(raw, object_pairs_hook=_pairs,
                         parse_constant=lambda _: fail('nonfinite JSON number'))
    except (ValueError, UnicodeError) as exc:
        fail('noncanonical JSON: ' + str(exc)[:120])
    if not isinstance(obj, dict):
        fail('JSON object required')
    canon = (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                        allow_nan=False, separators=(',', ':')) + '\n').encode()
    if raw != canon:
        fail('noncanonical JSON encoding')
    return obj


def _blocked(obj: dict, label: str) -> None:
    if obj.get('production_admission') != 'BLOCKED':
        fail(label + ' production-admission state')
    if obj.get('selection_authorized', False) is not False:
        fail(label + ' promotion flag')


def _safe_tensor_layout(raw: bytes) -> None:
    """Check safetensors header/offsets only; never deserialize or execute weights."""
    if not 64 <= len(raw) <= 130_000:
        fail('bounded safe Head bytes required')
    n = struct.unpack('<Q', raw[:8])[0]
    if not 0 < n <= 4096 or 8 + n >= len(raw):
        fail('invalid safetensors header length')
    try:
        hdr = json.loads(raw[8:8+n], object_pairs_hook=_pairs)
    except ValueError:
        fail('invalid safetensors header')
    if not isinstance(hdr, dict) or set(hdr) != set(EXPECTED_TENSORS):
        fail('unexpected checkpoint tensor names')
    ranges = []
    for name, shape in EXPECTED_TENSORS.items():
        item = hdr[name]
        if (not isinstance(item, dict) or set(item) != {'dtype', 'shape', 'data_offsets'}
                or item['dtype'] != 'F32' or item['shape'] != shape
                or not isinstance(item['data_offsets'], list)
                or len(item['data_offsets']) != 2
                or any(type(v) is not int for v in item['data_offsets'])):
            fail('unexpected safe Head tensor schema')
        start, stop = item['data_offsets']
        expected_n = 4 * math.prod(shape)
        if start < 0 or stop - start != expected_n:
            fail('safe Head tensor span/parameter count')
        ranges.append((start, stop))
    ranges.sort()
    if ranges[0][0] != 0 or ranges[-1][1] != len(raw) - (8+n) or any(
            left[1] != right[0] for left, right in zip(ranges, ranges[1:])):
        fail('overlapping or missing safetensors bytes')


def audit_blob(raw: bytes, expected_sha256: str) -> dict:
    """Independent byte audit. The expected digest must be externally pinned."""
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(
            c not in '0123456789abcdef' for c in expected_sha256):
        fail('explicit exact artifact digest required')
    if not isinstance(raw, bytes) or not 128 <= len(raw) <= MAX_ARCHIVE:
        fail('bounded ZIP bytes required')
    if sha(raw) != expected_sha256:
        fail('external Actions ZIP digest mismatch')
    try:
        archive = ZipFile(io.BytesIO(raw))
    except (BadZipFile, OSError):
        fail('invalid Actions ZIP format')
    with archive:
        infos = archive.infolist()
        if len(infos) != len(EXPECTED_FILES):
            fail('missing, extra or duplicate ZIP entries')
        paths = [x.filename for x in infos]
        if set(paths) != EXPECTED_FILES or len(set(paths)) != len(paths):
            fail('unexpected ZIP payload member or duplicate')
        total = 0
        for info in infos:
            name = info.filename
            p = PurePosixPath(name)
            if (p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name
                    or name.endswith('/') or info.is_dir() or info.flag_bits & 1
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                fail('unsafe ZIP path, link or encryption')
            limit = 131_072 if name.endswith('.safetensors') else 131_072
            if info.file_size < 1 or info.file_size > limit:
                fail('oversized or zero-byte ZIP member')
            if info.compress_size < 1 or info.file_size / info.compress_size > 250:
                fail('ZIP decompression ratio limit')
            total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            fail('aggregate decompressed ZIP budget exceeded')
        def get(name: str) -> bytes:
            return archive.read(name)
        acquire = _json(get('hepta-modernbert-acquisition.json'))
        pre = _json(get('hepta-token-budget-preflight.json'))
        reviewer = _json(get('hepta-token-independent-review.json'))
        report_raw = get('hepta-real-token-pair/report.json')
        producer = _json(report_raw)
        for label, obj in [('acquisition', acquire), ('preflight', pre),
                           ('reviewer', reviewer), ('producer', producer)]:
            _blocked(obj, label)
        if (acquire.get('model_id') != MODEL_ID
                or acquire.get('revision') != MODEL_REVISION
                or acquire.get('historical_source_zip_sha256') != ORIGINAL_SOURCE_SHA256
                or acquire.get('source_license_independently_granted') is not False
                or acquire.get('independent_signature_verified') is not False
                or acquire.get('publisher_files', {}).get('model.safetensors')
                != '340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9'):
            fail('source/model identity or use-entitlement drift')
        bundle = acquire.get('bundle_sha256')
        if not isinstance(bundle, str) or len(bundle) != 64:
            fail('missing physical Encoder bundle identity')
        if (pre.get('model_id') != MODEL_ID or pre.get('model_revision') != MODEL_REVISION
                or pre.get('source_zip_sha256') != ORIGINAL_SOURCE_SHA256
                or pre.get('capture_max_length') != 168 or pre.get('capture_batch') != 8
                or pre.get('full_joint_untruncated_row_count') != 128
                or pre.get('model_weights_downloaded_by_this_step') is not False
                or pre.get('pretrained_encoder_forward_verified') is not False):
            fail('original tokenizer-only preflight mismatch')
        originals = pre.get('per_cell')
        if not isinstance(originals, list) or len(originals) != 2:
            fail('complete ordered preflight Cells required')
        if (producer.get('schema') != 'hepta.neuron.real-token-paired-retrospective.v1'
                or producer.get('model_id') != MODEL_ID
                or producer.get('model_revision') != MODEL_REVISION
                or producer.get('source_zip_sha256') != ORIGINAL_SOURCE_SHA256
                or producer.get('real_model_encoder_forward_observed') is not True
                or producer.get('distinct_holdout_cases') != 32
                or producer.get('head_train_steps_per_candidate') != 20
                or producer.get('no_independent_future_or_ood_window_verified') is not True
                or producer.get('real_deployed_no_change_baseline_verified') is not False
                or producer.get('negative_transfer_and_NDU_verified') is not False):
            fail('Producer physical/scope/learning claims differ')
        observed = producer.get('encoder_observation', {})
        if observed.get('capture_profile') != {'max_length': 168, 'batch': 8}:
            fail('real Encoder preprocessing drift')
        if observed.get('pinned_tokenizer_preflight_sha256') != sha(get('hepta-token-budget-preflight.json')):
            fail('actual Encoder not bound to preserved tokenizer preflight')
        observed_cells = observed.get('cells')
        if not isinstance(observed_cells, list) or len(observed_cells) != 2:
            fail('two observed real Encoder Cell forwards required')
        model_times = []
        for cell in (0, 1):
            src, actual = originals[cell], observed_cells[cell]
            meter = actual.get('model_forward_observation', {})
            if (type(src.get('cell')) is not int or src['cell'] != cell
                    or type(actual.get('cell')) is not int or actual['cell'] != cell
                    or src.get('input_rows') != 64
                    or src.get('maximum_untruncated_tokens', 999) > 168
                    or src.get('ordered_active_token_ids_sha256') != actual.get('ordered_active_token_ids_sha256')
                    or src.get('total_active_token_slots') != actual.get('observed_masked_tokens')
                    or actual.get('total_encoder_batches') != 8
                    or actual.get('padded_token_slots') != 64 * 168
                    or meter.get('module_forward_attempts') != 8
                    or meter.get('module_forward_completions') != 8
                    or meter.get('module_forward_failures_or_incomplete') != 0
                    or meter.get('rows_attempted') != 64 or meter.get('rows_completed') != 64
                    or meter.get('production_worker_execution_verified') is not False):
                fail('observed physical tokens/forward counters drift')
            model_times.append(actual.get('observed_model_forward_wall_seconds'))
        if not all(type(x) in (float, int) and 0 < x < 600 for x in model_times):
            fail('nonphysical observed model wall-time fields')
        if (reviewer.get('schema') != 'hepta.neuron.token-pair-independent-numerical-review.v1'
                or reviewer.get('source_zip_sha256') != ORIGINAL_SOURCE_SHA256
                or reviewer.get('model_id') != MODEL_ID or reviewer.get('model_revision') != MODEL_REVISION
                or reviewer.get('research_producer_report_sha256') != sha(report_raw)
                or reviewer.get('training_seeds') != list(SEEDS)
                or reviewer.get('checked_head_checkpoints') != 12
                or reviewer.get('checked_holdout_cases_per_seed') != 32
                or reviewer.get('independent_numeric_replay_all_metrics_passed') is not True
                or reviewer.get('real_pretrained_encoder_forward_reobserved') is not True
                or reviewer.get('original_observer_independently_signed') is not False
                or reviewer.get('verified_prospective_future_NDU') is not False
                or reviewer.get('deployed_no_change_compared') is not False):
            fail('independent re-encode/replay evidence mismatch')
        runs = producer.get('runs')
        if not isinstance(runs, list) or len(runs) != 3 or [r.get('seed') for r in runs] != list(SEEDS):
            fail('three registered seed trajectories required')
        means = {kind: {m: [] for m in ('accuracy', 'brier', 'nll')} for kind in KINDS}
        for run in runs:
            seed = run['seed']
            if (run.get('all_32_holdout_rows_for_both_arms_verified') is not True
                    or len(run.get('candidate_heads', [])) != 4
                    or len(run.get('observations', [])) != 4):
                fail('incomplete sealed Head grid')
            candidates = {(a.get('cell'), a.get('kind')): a for a in run['candidate_heads']}
            if len(candidates) != 4 or set(candidates) != {(c,k) for c in (0,1) for k in KINDS}:
                fail('duplicate or missing Cell Head checkpoint')
            for cell in (0, 1):
                pair = [candidates[(cell,kind)] for kind in KINDS]
                if pair[0].get('training_sample_sha256') != pair[1].get('training_sample_sha256'):
                    fail('Head training sample lineage mismatch')
                for kind in KINDS:
                    candidate = candidates[(cell,kind)]
                    root = HEADS[(seed,cell,kind)]
                    manifest_raw = get(root+'manifest.json')
                    manifest = _json(manifest_raw)
                    weight_raw = get(root+'head.safetensors')
                    _safe_tensor_layout(weight_raw)
                    if (candidate.get('head_manifest_sha256') != sha(manifest_raw)
                            or candidate.get('parameter_count') != 16132
                            or manifest.get('schema') != 'hepta.neuron.trained-packed-head.shadow.v1'
                            or manifest.get('kind') != kind
                            or manifest.get('scope') != {'principal':'public-ag-news-research',
                                'purpose':'ag-news-retrospective-token-pair',
                                'organ_id':'ag-news','cell_id':f'cell-{cell}'}
                            or manifest.get('dimensions') != [768,8,4]
                            or manifest.get('weights_file') != 'head.safetensors'
                            or manifest.get('weights_bytes') != len(weight_raw)
                            or manifest.get('weights_sha256') != sha(weight_raw)
                            or manifest.get('pins', {}).get('encoder_sha256') != bundle
                            or manifest.get('pins', {}).get('tokenizer_sha256')
                            != pre.get('tokenizer_json_sha256')
                            or manifest.get('training', {}).get('seed') != seed + cell * 104729
                            or manifest.get('training', {}).get('steps') != 20
                            or manifest.get('training', {}).get('sample_sha256')
                            != candidate.get('training_sample_sha256')
                            or manifest.get('production_admission') != 'BLOCKED'
                            or manifest.get('selection_authorized') is not False
                            or manifest.get('independent_signature_verified') is not False):
                        fail('physical Head checkpoint/source/authority drift')
            observed_metrics = {(o.get('cell'), o.get('split')): o for o in run['observations']}
            if (len(observed_metrics) != 4 or set(observed_metrics)
                    != {(c,s) for c in (0,1) for s in SPLITS}):
                fail('duplicate or incomplete per-split Head metrics')
            for cell in (0, 1):
                item = observed_metrics[(cell, 'holdout')]
                if item.get('unique_cases') != 16:
                    fail('original source cohort size drift')
                for kind in KINDS:
                    m = item.get(kind)
                    if not isinstance(m, dict):
                        fail('missing physical Head holdout quality')
                    if m.get('head_manifest_sha256') != candidates[(cell,kind)]['head_manifest_sha256']:
                        fail('wrong quality/checkpoint association')
                    for key in ('accuracy', 'brier', 'nll'):
                        value = m.get(key)
                        if type(value) not in (float, int) or not math.isfinite(value):
                            fail('nonfinite quality metric')
                        if key == 'accuracy' and not 0 <= value <= 1:
                            fail('impossible accuracy')
                        if key != 'accuracy' and value < 0:
                            fail('negative proper score')
                        means[kind][key].append(value)
        if (panel := reviewer.get('paired_original_case_descriptive_effect')) is None:
            fail('missing original-case paired effect review')
        if (panel.get('original_holdout_cases') != 32
                or panel.get('original_holdout_cases_per_cell') != 16
                or panel.get('repeated_train_seeds') != list(SEEDS)
                or panel.get('number_of_actual_case_seed_comparisons') != 96
                or panel.get('case_source_independence_verified') is not False
                or panel.get('prospective_future_outcome_verified') is not False
                or panel.get('real_deployed_nochange_verified') is not False
                or panel.get('model_winner_selected') is not False
                or panel.get('independent_signed_NDU_verified') is not False
                or panel.get('production_admission') != 'BLOCKED'
                or panel.get('selection_authorized') is not False):
            fail('non-authorizing retrospective paired panel required')
        arm_means = {kind: {key: math.fsum(values)/len(values) for key, values in metrics.items()}
                     for kind, metrics in means.items()}
        delta = {metric: arm_means[KINDS[1]][metric] - arm_means[KINDS[0]][metric]
                 for metric in ('accuracy','brier','nll')}
        panel_measures = panel.get('paired_token_minus_pooled', {})
        for metric, v in delta.items():
            item = panel_measures.get(metric)
            if (not isinstance(item, dict)
                    or type(item.get('point_estimate')) not in (float,int)
                    or abs(item['point_estimate'] - v) > 2e-5
                    or not isinstance(item.get('original_case_stratified_bootstrap_95_descriptive'), list)
                    or len(item['original_case_stratified_bootstrap_95_descriptive']) != 2
                    or not all(type(x) in (int,float) and math.isfinite(x) for x in item['original_case_stratified_bootstrap_95_descriptive'])):
                fail('actual descriptive metric mean disagrees with independent reviewer')
        if (panel.get('repeated_seed_newly_correct_count') != 0
                or panel.get('repeated_seed_newly_incorrect_count') != 1):
            fail('changed-case actual replay count drift')
        return {
            'schema': SCHEMA,
            'artifact_zip_sha256': sha(raw),
            'source_github_run_id': RUN_ID,
            'source_github_artifact_id': ARTIFACT_ID,
            'source_pr_head_sha': GITHUB_HEAD,
            'model_id': MODEL_ID,
            'model_revision': MODEL_REVISION,
            'model_weights_sha256': acquire['publisher_files']['model.safetensors'],
            'original_dataset_artifact_sha256': ORIGINAL_SOURCE_SHA256,
            'tokenizer_preflight_sha256': sha(get('hepta-token-budget-preflight.json')),
            'producer_report_sha256': sha(report_raw),
            'independent_reviewer_sha256': sha(get('hepta-token-independent-review.json')),
            'actual_head_checkpoint_count': len(HEADS),
            'actual_original_holdout_cases': 32,
            'repeated_training_seeds': list(SEEDS),
            'mean_holdout_by_arm': arm_means,
            'paired_token_minus_pooled': panel_measures,
            'max_original_input_tokens': max(row['maximum_untruncated_tokens'] for row in originals),
            'observed_model_forward_wall_seconds_by_cell': model_times,
            'immutable_actual_run_byte_integrity_checked': True,
            'independent_reencoding_job_receipt_present': True,
            'external_observer_independently_signed': False,
            'source_use_licence_independently_granted': False,
            'original_source_family_independence_verified': False,
            'case_level_bootstrap_recomputed_from_original_predictions': False,
            'actual_future_outcomes_evaluated': False,
            'deployed_no_change_compared': False,
            'signed_NDU_verified': False,
            'target_host_4096_cell_qualified': False,
            'selection_authorized': False,
            'production_admission': 'BLOCKED',
            'warning': ('Read-only actual GitHub artifact integrity and descriptive metric '
                        'cross-check, not independently authenticated model execution, '
                        'case-level bootstrap replay, prospective NDU or deployment authority.'),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.archive.read_bytes()
    result = audit_blob(raw, ARTIFACT_SHA256)
    dst = args.output
    if dst.exists() or dst.is_symlink():
        fail('create-only output path already exists')
    payload = (json.dumps(result, sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(',', ':')) + '\n').encode()
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
