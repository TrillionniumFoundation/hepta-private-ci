"""Read-only V30 two-model *feature-cost* reviewer. Never runs/authorizes a model.

An isolated consumer of the exact source-run aggregate. It independently checks
all declared model/source/authority fields, rejects V30's former phase-clock
collision, and recomputes balanced ABBA cost differences. Counters in one
model-produced JSON are NOT independent physical hardware attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

SOURCE_SCHEMA = 'hepta.stem.v30.live-text-selective-vision-cost.v1'
REVIEW_SCHEMA = 'hepta.stem.v30.independent-feature-cost-review.v1'
ORIGINAL_SOURCE_SHA = 'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
ORIGINAL_ARCHIVE_SHA = '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'
MINIMAL_ROUTE_SHA = 'd8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6'
GRANITE = ('ibm-granite/granite-embedding-97m-multilingual-r2', '835ad14087e140460703cf0fae09f97d469d65c2')
DINO = ('facebook/dinov2-small', 'ed25f3a31f01632728cabb09d1542f84ab7b0056')
ARM_ORDER = ('all64', 'conditional21', 'conditional21', 'all64')
ARM_KEYS = frozenset(('arm','cpu_ns','wall_ns','text_items','text_batches',
    'text_cpu_ns','text_wall_ns','items','batches','media_bytes_read',
    'vision_cpu_ns','vision_wall_ns'))
TOP_KEYS = frozenset(('schema','authority','disposition','production_authorized',
    'stem_winner_verified','frozen_route_plan_sha256','historical_archive_sha256',
    'actual_live_text_route_from_model','cached_vision_predictions_used_for_route',
    'real_test_labels_opened','new_training_updates','real_original_source_case_count',
    'selected_vision_cases','real_text_model_repo','real_text_model_revision',
    'real_vision_model_repo','real_vision_model_revision',
    'text_model_manifest_sha256','vision_model_manifest_sha256',
    'actual_pretrained_text_and_vision_forwards','warmup_text_batches',
    'warmup_vision_batches','model_acquisition_and_load_wall_ns','arm_traces',
    'text_score_max_abs_drift','image_feature_max_abs_drift',
    'process_peak_rss_kib_not_incremental','energy_joules','gpu_peak_bytes',
    'independent_future_windows','full_product_end_to_end_savings_proven',
    'original_task_accuracy_recomputed_this_run','physical_cpu_execution_owner'))
MAX_REPORT_BYTES = 128 * 1024
MAX_OBSERVED_NS = 10**16

class Rejected(ValueError):
    """No partial readout and no permission fallback."""


def require(ok: bool, why: str):
    if not ok:
        raise Rejected(why)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha64(v: object) -> bool:
    return type(v) is str and len(v) == 64 and all(c in '0123456789abcdef' for c in v)


def integer(v: object, low=0, high=MAX_OBSERVED_NS) -> int:
    require(type(v) is int and low <= v <= high, 'missing/invalid physical integer')
    return v


def strict_json(raw: bytes):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_REPORT_BYTES and raw.endswith(b'\n'),
            'absent, oversized or partial physical receipt')
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, 'duplicate physical receipt field')
            result[key] = value
        return result
    def bad_constant(_):
        raise Rejected('nonfinite model observation')
    try:
        doc = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
        require(type(doc) is dict and raw == canonical(doc), 'noncanonical physical report bytes')
        return doc
    except (ValueError, TypeError, OverflowError) as exc:
        raise Rejected('invalid physical receipt JSON') from exc


def canonical(doc) -> bytes:
    return (json.dumps(doc, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False)+'\n').encode('utf-8')


def validate_immutable_identity(doc: dict):
    require(set(doc) == TOP_KEYS and doc['schema'] == SOURCE_SCHEMA,
            'unexpected model report contract or field inventory')
    require(doc['authority'] == 'DENY_ALL' and doc['disposition'] == 'HOLD_NO_CELL_OR_MODEL_SELECTION'
            and doc['production_authorized'] is False and doc['stem_winner_verified'] is False
            and doc['full_product_end_to_end_savings_proven'] is False,
            'model report promotes science or effect authority')
    require(doc['frozen_route_plan_sha256'] == MINIMAL_ROUTE_SHA
            and doc['historical_archive_sha256'] == ORIGINAL_ARCHIVE_SHA
            and doc['real_original_source_case_count'] == 64
            and doc['selected_vision_cases'] == 21,
            'original source/route/case identity mismatch')
    require(doc['real_text_model_repo'] == GRANITE[0] and doc['real_text_model_revision'] == GRANITE[1]
            and doc['real_vision_model_repo'] == DINO[0]
            and doc['real_vision_model_revision'] == DINO[1],
            'substituted pretrained model')
    require(sha64(doc['text_model_manifest_sha256']) and sha64(doc['vision_model_manifest_sha256'])
            and doc['text_model_manifest_sha256'] != doc['vision_model_manifest_sha256'],
            'missing/doubled model manifest identity')
    require(doc['actual_live_text_route_from_model'] is True
            and doc['cached_vision_predictions_used_for_route'] is False
            and doc['actual_pretrained_text_and_vision_forwards'] is True
            and doc['real_test_labels_opened'] is False
            and doc['new_training_updates'] == 0 and type(doc['new_training_updates']) is int
            and doc['independent_future_windows'] == 0 and type(doc['independent_future_windows']) is int
            and doc['original_task_accuracy_recomputed_this_run'] is False,
            'model-side score leakage, false training/forward or future claim')
    require(doc['warmup_text_batches'] == 1 and type(doc['warmup_text_batches']) is int
            and doc['warmup_vision_batches'] == 1 and type(doc['warmup_vision_batches']) is int
            and doc['physical_cpu_execution_owner'] == 'original-frozen-granite-and-dinov2',
            'unobserved model warmup/original owner drift')
    require(doc['energy_joules'] is None and doc['gpu_peak_bytes'] is None,
            'unqualified hardware telemetry asserted')
    integer(doc['model_acquisition_and_load_wall_ns'],1)
    integer(doc['process_peak_rss_kib_not_incremental'],1)
    for k in ('text_score_max_abs_drift','image_feature_max_abs_drift'):
        v = doc[k]
        require(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 1e-4,
                'missing or out-of-bound cross-arm real features')


def review(raw: bytes) -> dict:
    """Pure independent recomputation of costs; never calls an Encoder."""
    doc = strict_json(raw)
    validate_immutable_identity(doc)
    traces = doc['arm_traces']
    require(type(traces) is list and len(traces) == 4, 'expected four independent ABBA traces')
    for i,arm in enumerate(traces):
        require(type(arm) is dict and set(arm) == ARM_KEYS and arm['arm'] == ARM_ORDER[i],
                'arm order or clock field inventory changed')
        expected_items = 64 if i in (0,3) else 21
        expected_batches = 8 if i in (0,3) else 3
        require(integer(arm['text_items'],320,320)==320
                and integer(arm['text_batches'],20,20)==20
                and integer(arm['items'],expected_items,expected_items)==expected_items
                and integer(arm['batches'],expected_batches,expected_batches)==expected_batches,
                'missing or invented feature-forward counts')
        integer(arm['media_bytes_read'],1,512*1024*1024)
        for field in ('cpu_ns','wall_ns','text_wall_ns','text_cpu_ns','vision_wall_ns','vision_cpu_ns'):
            integer(arm[field],1)
        # Prior V30 code accidentally overwrote 'cpu_ns'/'wall_ns' with the
        # vision-only phase receipt. Checking sums detects this objectively.
        require(arm['cpu_ns'] >= arm['text_cpu_ns'] + arm['vision_cpu_ns']
                and arm['wall_ns'] >= arm['text_wall_ns'] + arm['vision_wall_ns'],
                'full feature-ingress clock does not include text AND vision')
        require(arm['cpu_ns'] >= arm['vision_cpu_ns']
                and arm['wall_ns'] >= arm['vision_wall_ns'],
                'incoherent end-to-end phase clock')
    require(traces[0]['media_bytes_read'] == traces[3]['media_bytes_read']
            and traces[1]['media_bytes_read'] == traces[2]['media_bytes_read']
            and traces[0]['media_bytes_read'] > traces[1]['media_bytes_read'],
            'model input media bytes are not the frozen source cohort')
    totals = [arm['cpu_ns'] for arm in traces]
    vision = [arm['vision_cpu_ns'] for arm in traces]
    text = [arm['text_cpu_ns'] for arm in traces]
    full_ns = totals[0] + totals[3]
    lazy_ns = totals[1] + totals[2]
    require(full_ns>0 and lazy_ns>0, 'missing paired physical CPU observations')
    # Two temporally adjacent ABBA differences, not a confidence interval.
    return {
        'schema': REVIEW_SCHEMA,
        'source_schema': SOURCE_SCHEMA,
        'producer_report_sha256': digest(raw),
        'historical_archive_sha256': ORIGINAL_ARCHIVE_SHA,
        'frozen_route_sha256': MINIMAL_ROUTE_SHA,
        'cases': 64,
        'selective_vision_cases': 21,
        'full_text_batches_in_each_arm': 20,
        'vision_batched_forwards_by_arm': [8,3,3,8],
        'text_batched_forwards_by_arm': [20]*4,
        'full_feature_cpu_ns_by_arm': totals,
        'text_cpu_ns_by_arm': text,
        'vision_cpu_ns_by_arm': vision,
        'paired_total_feature_cpu_deltas_ns': [totals[0]-totals[1], totals[3]-totals[2]],
        'combined_total_feature_cpu_reduction_fraction_descriptive': 1-lazy_ns/full_ns,
        'paired_vision_cpu_deltas_ns': [vision[0]-vision[1], vision[3]-vision[2]],
        'paired_text_cpu_deltas_ns': [text[0]-text[1], text[3]-text[2]],
        'observed_high_water_rss_kib_not_arm_delta':doc['process_peak_rss_kib_not_incremental'],
        'model_loading_cost_excluded_from_arm_comparison':True,
        'numerical_receipt_recounted':True,
        'producer_counters_independently_hardware_attested':False,
        'new_model_forward_performed_by_reviewer':False,
        'actual_accuracy_or_future_utility_verified':False,
        'full_product_end_to_end_savings_proven':False,
        'energy_joules':None,
        'gpu_peak_bytes':None,
        'production_authorized':False,
        'stem_winner_verified':False,
        'authority':'DENY_ALL',
        'decision':'HOLD_RESEARCH_FEATURE_CPU_ONLY_NO_PROMOTION',
    }


def write_create_only(path: Path, doc: dict):
    require(isinstance(path,Path) and not path.is_symlink()
            and not path.parent.is_symlink(), 'unsafe independent readout location')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'wb') as handle:
        handle.write(canonical(doc))
        handle.flush();os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--producer',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(not args.producer.is_symlink() and args.producer.is_file(),
            'missing/unsafe upstream physical artifact')
    require(0 < args.producer.stat().st_size <= MAX_REPORT_BYTES,
            'invalid upstream report length')
    result=review(args.producer.read_bytes())
    write_create_only(args.output,result)
    print(json.dumps({'producer_report_sha256':result['producer_report_sha256'],
         'disposition':result['decision'],'production_authorized':False},sort_keys=True))


if __name__=='__main__':main()
