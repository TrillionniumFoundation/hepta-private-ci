"""Immutable original ScienceQA V25 outcome + V30 physical cost evidence gate.

Research-only. Two separately executed archived receipts, NO newly trained model,
no per-case joined prediction proof, and no ability to grant FinalUse/Stem choice.
Historical feature cost and original public labels cannot attest NDU utility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import zipfile

import v30_independent_feature_cost_review as cost

SCHEMA = 'hepta.stem.v31.original-same-source-cost-utility-gate.v1'
V25_ARTIFACT = 12081452577
V30_ARTIFACT = 12101143188
V25_ZIP_SHA = '0e623ec89014d7e0fa5cc0391d368443ac952599f353dc631597458cc9f434b0'
V30_ZIP_SHA = '90b5ef1d7e95609a1439ce0c948b47cb96827d560b82c4ef7078a068e218446f'
V25_NAME = 'v25-public-label-historical-review.json'
V25_MEMBER_SHA = 'b78b6d1175f5f2775265bf7fb2cadd2dbf9736dba2de314d573827369193e829'
V25_HOLD_NAME = 'v25-historical-missing-label-HOLD.json'
V25_HOLD_SHA = 'd71034f10050a7a6e855eca2fe1f7efb0fbee6ade529af1237f802b557c17240'
V30_NAME = 'v30-physical-descriptive-HOLD.json'
V30_MEMBER_SHA = '668499d3b714e83a2005e951de1ffe7919cc4f88ecee9bc9e754cfb28ca35b7f'
ORIGINAL_SOURCE = cost.ORIGINAL_SOURCE_SHA
ORIGINAL_PREDICTIONS = 'c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4'
V25_SOURCE_REV = 'b9984af01798586705cee1fbdfa80a6dcbef04f1'
ARM_NAMES = frozenset({'text_only', 'bridge_image_only', 'image_masked',
                       'calibrated_fusion', 'bridge_equal_fusion',
                       'rotated_equal_fusion', 'unaligned_equal_fusion', 'train_gate'})
MAX_ZIP_BYTES = 512 * 1024
MAX_MEMBER_BYTES = 96 * 1024


class Rejected(ValueError):
    pass


def require(value, msg):
    if not value:
        raise Rejected(msg)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_source_json(raw: bytes) -> dict:
    def unique(kvs):
        out = {}
        for key, val in kvs:
            require(key not in out, 'duplicate numerical evidence field')
            out[key] = val
        return out
    def bad_constant(_):
        raise Rejected('nonfinite numerical evidence')
    try:
        obj = json.loads(raw, object_pairs_hook=unique, parse_constant=bad_constant)
    except (ValueError, TypeError, OverflowError) as exc:
        raise Rejected('malformed numerical evidence') from exc
    require(type(obj) is dict, 'original reviewer must be object')
    try:
        cost.canonical(obj)  # nested 1e999 parses as Infinity in stock JSON.
    except (ValueError, TypeError, OverflowError) as exc:
        raise Rejected('nested nonfinite original evidence') from exc
    return obj


def exact_artifact(path: Path, outer_sha: str, expected: dict[str,str]) -> dict[str,bytes]:
    """Bounded entire ZIP SHA and exact member SHA, not mere artifact label."""
    require(isinstance(path, Path) and not path.is_symlink() and path.is_file(),
            'original Actions artifact file absent or unsafe')
    require(0 < path.stat().st_size <= MAX_ZIP_BYTES, 'original ZIP size exceeded')
    data = path.read_bytes()
    require(sha(data) == outer_sha, 'original Actions artifact complete-byte SHA changed')
    try:
        with zipfile.ZipFile(path) as z:
            entries = z.infolist()
            require(len(entries) == len(expected) and
                    {e.filename for e in entries} == set(expected) and
                    all(not e.is_dir() and not e.flag_bits & 1 and
                        e.file_size <= MAX_MEMBER_BYTES and
                        e.compress_size <= MAX_ZIP_BYTES and
                        re.fullmatch(r'[A-Za-z0-9._-]+', e.filename) for e in entries),
                    'original ZIP member roster, encryption or size changed')
            items = {}
            for entry in entries:
                content = z.read(entry)
                require(len(content) == entry.file_size and sha(content) == expected[entry.filename],
                        'original ZIP member SHA mismatch')
                items[entry.filename] = content
            return items
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError) as exc:
        raise Rejected('unreadable original archive') from exc


def finite_number(x):
    require(type(x) in (int,float) and math.isfinite(x), 'unverified numerical value')
    return float(x)


def exact_int(x, minimum=0, maximum=64):
    require(type(x) is int and minimum <= x <= maximum, 'unverified count')
    return x


def exact_p(r:int,h:int) -> float:
    n=r+h
    if not n:return 1.0
    return min(1.0, 2*sum(math.comb(n,k) for k in range(min(r,h)+1))/2**n)


def validate_historical(published: dict):
    """V25's ORIGINAL postseal publisher label replay, never forecast success."""
    require(published.get('schema') == 'hepta.stem.v25.original-publisher-historical-rejudge.v1'
            and published.get('decision') == 'HISTORICAL_PUBLISHER_LABEL_RECOUNT_ONLY_NO_PROMOTION'
            and published.get('authority_posture') == 'DENY_ALL',
            'untrusted historical outcome disposition')
    require(published.get('original_historical_archive_sha256') == cost.ORIGINAL_ARCHIVE_SHA
            and published.get('original_source_sha256') == ORIGINAL_SOURCE
            and published.get('original_prediction_sha256') == ORIGINAL_PREDICTIONS
            and published.get('publisher_revision') == V25_SOURCE_REV
            and published.get('original_publisher_dataset') == 'lmms-lab/ScienceQA-IMG',
            'historical source/prediction cohort mismatch')
    require(published.get('original_publisher_labels_independently_rescored') is True
            and published.get('original_test_label_file_sha256_original_matched') is True
            and published.get('source_file_sha256_original_matched') is True,
            'original label bytes were not independently reread')
    require(published.get('original_model_recomputed_in_this_run') is False
            and published.get('original_source_custody_independent_from_upstream_release') is False
            and published.get('future_independent_source_windows') == 0
            and type(published.get('future_independent_source_windows')) is int
            and published.get('new_encoder_forwards') == 0
            and type(published.get('new_encoder_forwards')) is int
            and published.get('new_training_updates') == 0
            and type(published.get('new_training_updates')) is int,
            'false independent future/training/original model provenance claim')
    require(published.get('scientific_promotion_authorized') is False
            and published.get('stem_winner_verified') is False
            and published.get('production_authorized') is False
            and published.get('external_independent_human_visual_necessity_annotated') is False,
            'historical result contains forged promotion or adjudication')
    arms = published.get('all_original_arms')
    require(type(arms) is dict and set(arms)==ARM_NAMES, 'missing original research controls')
    baseline=exact_int(arms['text_only']['original_historical_correct'])
    require(baseline == 17, 'text no-change score does not match frozen original source')
    for name,item in arms.items():
        require(type(item) is dict, 'missing per-arm labels')
        correct=exact_int(item.get('original_historical_correct'))
        rescues=exact_int(item.get('paired_rescues_vs_text'))
        harms=exact_int(item.get('paired_harms_vs_text'))
        require(correct-baseline == rescues-harms,
                'published per-arm confusion tally inconsistent with baseline')
        actual=finite_number(item.get('paired_exact_mcnemar_p'))
        require(abs(actual-exact_p(rescues,harms)) <= 1e-12,
                'published paired exact McNemar cannot be recounted')
        for measure in ('original_historical_brier_4class','original_historical_nll'):
            require(0 <= finite_number(item.get(measure)) <= 20,
                    'out-of-bounds original task score')
    require(arms['image_masked']['original_historical_correct'] == baseline
            and arms['calibrated_fusion']['original_historical_correct'] == baseline,
            'original negative/masked controls changed')
    route=published.get('precommitted_v24_label_blind_route')
    require(type(route) is dict, 'missing frozen conditional visual route')
    require(exact_int(route.get('historical_correct')) == baseline
            and finite_number(route.get('historical_accuracy')) == baseline/64
            and exact_int(route.get('historical_rescues_vs_text')) == 5
            and exact_int(route.get('historical_harms_vs_text')) == 5
            and finite_number(route.get('historical_exact_mcnemar_p')) == 1.0,
            'historical conditional route utility not independently verified')
    require(finite_number(route.get('threshold')) == .005
            and exact_int(route.get('conditional_image_calls_planned')) == 21
            and exact_int(route.get('changed_top1_vs_text')) == 19
            and route.get('archived_vision_features_were_computed_for_all_64') is True
            and route.get('actual_conditional_encoder_forward_count') is None
            and route.get('actual_conditional_cpu_or_energy_cost') is None
            and route.get('actual_conditional_service_latency_ms') is None,
            'historical route was not a physical selective execution')
    return {'baseline_correct':baseline,'conditional_correct':route['historical_correct'],
            'rescues':5,'harms':5,'mcnemar_exact_p':1.0,
            'original_train_gate_correct':arms['train_gate']['original_historical_correct']}


def join(published: dict, physical_raw: bytes, *, v25_zip_sha=V25_ZIP_SHA,
         v30_zip_sha=V30_ZIP_SHA) -> dict:
    historical=validate_historical(published)
    # Inherit the independently implemented original CPU phase-clock verifier.
    observed=cost.review(physical_raw)
    require(observed['authority'] == 'DENY_ALL', 'independent reviewer authority drift')
    require(observed['source_schema'] == cost.SOURCE_SCHEMA
            and observed['historical_archive_sha256'] == published['original_historical_archive_sha256']
            and observed['frozen_route_sha256'] == cost.MINIMAL_ROUTE_SHA
            and observed['cases'] == 64 and observed['selective_vision_cases']==21
            and observed['vision_batched_forwards_by_arm'] == [8,3,3,8]
            and observed['text_batched_forwards_by_arm'] == [20,20,20,20],
            'cost and historical source route are incompatible')
    fraction=observed['combined_total_feature_cpu_reduction_fraction_descriptive']
    require(type(fraction) is float and math.isfinite(fraction) and fraction < 1.0,
            'invalid phase-clock cost arithmetic')
    return {'schema':SCHEMA,'decision':'NO_GO_RESOURCE_ONLY_NO_UTILITY_UPLIFT',
            'authority':'DENY_ALL','scientific_promotion_authorized':False,
            'production_authorized':False,'stem_winner_verified':False,
            'source_sha256':ORIGINAL_SOURCE,
            'historical_public_label_artifact_id':V25_ARTIFACT,
            'physical_two_encoder_artifact_id':V30_ARTIFACT,
            'historical_public_label_artifact_sha256':v25_zip_sha,
            'physical_two_encoder_artifact_sha256':v30_zip_sha,
            'physical_producer_report_sha256':observed['producer_report_sha256'],
            'history_and_physical_source_sha_identical':True,
            'case_level_joint_prediction_replay_authenticated':False,
            'original_historical_labels_independently_reread':True,
            'historical_no_change_correct':historical['baseline_correct'],
            'historical_conditional_correct':historical['conditional_correct'],
            'historical_rescues':historical['rescues'],
            'historical_harms':historical['harms'],
            'historical_paired_exact_mcnemar_p':historical['mcnemar_exact_p'],
            'historical_frozen_train_gate_correct':historical['original_train_gate_correct'],
            'original_test_cases':64,'selected_vision_cases':21,
            'same_loaded_models_balanced_abba':True,
            'full_cpu_ns_by_arm':observed['full_feature_cpu_ns_by_arm'],
            'text_cpu_ns_by_arm':observed['text_cpu_ns_by_arm'],
            'vision_cpu_ns_by_arm':observed['vision_cpu_ns_by_arm'],
            'paired_cpu_savings_ns':observed['paired_total_feature_cpu_deltas_ns'],
            'observed_two_encoder_feature_cpu_reduction_fraction':fraction,
            'feature_only_resource_gain_descriptive':fraction>0,
            'independent_future_windows':0,
            'ndu_net_utility_improvement_verified':False,
            'ndu_net_benefit':None,
            'retention_and_negative_transfer_qualified':False,
            'actual_model_training_or_forward_this_join':False,
            'whole_product_lifecycle_cost_qualified':False,
            'cpu_claim_scoped_to_frozen_original_source_and_feature_phase':True,
            'no_change_baseline_production_trace_witnessed':False,
            'source_independent_human_modal_necessity_adjudicated':False,
            'independent_hardware_attestation':False,
            'resource_break_even_with_head_and_recovery':None,
            'physical_abba_host_peak_rss_kib_not_delta':observed['observed_high_water_rss_kib_not_arm_delta']}


def review_artifacts(v25_path: Path, v30_path: Path) -> dict:
    v25=exact_artifact(v25_path,V25_ZIP_SHA,{V25_NAME:V25_MEMBER_SHA,V25_HOLD_NAME:V25_HOLD_SHA})
    v30=exact_artifact(v30_path,V30_ZIP_SHA,{V30_NAME:V30_MEMBER_SHA})
    published=strict_source_json(v25[V25_NAME])
    # Force the historical *absence-of-labels* negative control too.
    negative=strict_source_json(v25[V25_HOLD_NAME])
    require(negative.get('decision')=='HOLD_ORIGINAL_PUBLIC_SOURCE_AND_LABEL_BYTES_NOT_REOPENED'
            and negative.get('original_publisher_labels_independently_rescored') is False
            and negative.get('v24_conditional_route_historical_accuracy') is None,
            'historical unadmitted-label negative control missing')
    return join(published,v30[V30_NAME])


def safe_write(path:Path,doc:dict):
    require(not path.is_symlink() and not path.exists(), 'must create new output')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as handle:
        handle.write(cost.canonical(doc)); handle.flush();os.fsync(handle.fileno())


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--historical-zip',type=Path,required=True)
    ap.add_argument('--physical-zip',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=review_artifacts(args.historical_zip,args.physical_zip)
    safe_write(args.output,result)
    print(json.dumps({'decision':result['decision'],'cases':result['original_test_cases'],
                      'observed_two_encoder_feature_cpu_reduction_fraction':result['observed_two_encoder_feature_cpu_reduction_fraction'],
                      'independent_future_windows':0,'production_authorized':False},sort_keys=True))

if __name__=='__main__':main()
