#!/usr/bin/env python3
"""Independently check paired *redacted* Granite research artifacts.

Only audits public summaries and archive integrity. Does not verify model weights,
source-case predictions, trust custody, NDU decisions, future benefit or effects.
No dependency on GitHub, Torch, NumPy or network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from statistics import median, mean
from typing import Any

LIMIT = 256 * 1024
ARMS = (
    'frozen_stage1_no_second_phase_learning',
    'unsplit_continued_update',
    'fixed_router',
    'learned_router',
    'adaptive_split',
)
SEEDS = (41, 47, 53)
SOURCE = '2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4'
ENCODER = 'ibm-granite/granite-embedding-97m-multilingual-r2'
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


class Reject(ValueError):
    pass


def require(p: Any, why: str) -> None:
    if not p:
        raise Reject(why)


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        require(k not in out, f'duplicate JSON key {k!r}')
        out[k] = v
    return out


def read_receipt(path: Path) -> tuple[dict[str, Any], str]:
    require(path.is_file() and not path.is_symlink(), 'expected ordinary archive')
    require(path.stat().st_size <= LIMIT, 'archive too large for redacted data')
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        require(len(entries) == 1 and entries[0].filename == 'granite-redacted-receipt.json',
                'redacted ZIP must contain one safe receipt, never raw payloads')
        require(not entries[0].is_dir() and entries[0].file_size <= LIMIT,
                'oversized or invalid ZIP entry')
        raw = z.read(entries[0], pwd=None)
    try:
        doc = json.loads(raw, object_pairs_hook=no_duplicate_keys,
                         parse_constant=lambda val: (_ for _ in ()).throw(Reject(val)))
    except (ValueError, UnicodeDecodeError, RecursionError) as e:
        raise Reject('bad JSON') from e
    require(type(doc) is dict, 'nonobject root')
    return doc, hashlib.sha256(raw).hexdigest()


def check(doc: dict[str, Any]) -> dict[str, Any]:
    required = {
        'schema': 'hepta.cell-meta-granite-redacted-artifact.v1',
        'status': 'COMPLETE_DESCRIPTIVE_ONLY',
        'authority_posture': 'DENY_ALL',
        'production_admission': 'BLOCKED',
        'descriptive_only': True,
        'expected_source_cases': 224,
        'host_custody_authenticated': False,
        'independent_ndu_selection_authorized': False,
        'matched_lifecycle_compute': False,
        'ood_verified': False,
        'pretrained_origin_independently_authenticated': False,
        'prospective_future_windows_verified': False,
        'raw_payloads_published': False,
        'training_seeds_are_not_independent_datasets': True,
        'missing': [],
        'reason_codes': [],
    }
    for key, value in required.items():
        require(key in doc and type(doc[key]) is type(value) and doc[key] == value,
                'unqualified or inconsistent claim: ' + key)
    agg = doc.get('aggregate')
    require(type(agg) is dict and agg.get('original_public_panel_sha256') == SOURCE,
            'wrong pinned source panel')
    require(agg.get('registered_encoder') == ENCODER, 'wrong registered encoder')
    files = doc.get('files')
    require(type(files) is list and len(files) >= 20, 'incomplete digest-only source inventory')
    observed: dict[str, dict] = {}
    for f in files:
        require(type(f) is dict and set(f) == {'name', 'sha256', 'bytes'},
                'invalid source file inventory entry')
        name, sha, size = f['name'], f['sha256'], f['bytes']
        require(type(name) is str and len(name) <= 180 and name and '/' not in name and '\\' not in name,
                'unsafe filename in source inventory')
        require(name not in observed, 'duplicate source file inventory entry')
        require(type(sha) is str and bool(HEX64.fullmatch(sha)), 'invalid SHA256 receipt')
        require(type(size) is int and 0 < size <= 20 * 1024 * 1024,
                'invalid bounded file size')
        observed[name] = f
    for key in ('source-panel.json', 'model-files.json', 'granite-q24-features.json',
                '41-trial-panel.json', '47-trial-panel.json', '53-trial-panel.json'):
        require(key in observed, 'missing source identity ' + key)
    require(observed['source-panel.json']['sha256'] == SOURCE,
            'declared panel bytes inconsistent with precommitted SHA')
    items = agg.get('five_arm_retrospective_research')
    require(type(items) is list and len(items) == 15, 'wrong five-arm observation count')
    by: dict[tuple[int, str], dict] = {}
    for row in items:
        require(type(row) is dict and row.get('seed') in SEEDS and row.get('arm') in ARMS,
                'unregistered seed/arm')
        key = (row['seed'], row['arm'])
        require(key not in by, 'duplicate seed/arm')
        require(type(row.get('split_proposed')) is bool, 'invalid split flag')
        for k in ('test_1', 'test_2'):
            val = row.get(k)
            require(type(val) is dict and set(val) == {'accuracy', 'brier'}, 'wrong metric schema')
            for metric in ('accuracy', 'brier'):
                v = val[metric]
                require(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1,
                        'out of range metric')
        by[key] = row
    require(set(by) == {(s, a) for s in SEEDS for a in ARMS}, 'incomplete seed-arm grid')
    os = agg.get('five_arm_os_medians')
    require(type(os) is dict and os.get('exact_15_os_processes_declared') == 15,
            'missing 15 physical processes declaration')
    require(os.get('cost_includes_python_import_and_numeric_replay') is True and
            os.get('cpu_and_rss_are_untrusted_same_class_samples') is True,
            'inaccurate resource description')
    osarms = os.get('by_arm')
    require(type(osarms) is dict and set(osarms) == set(ARMS), 'incomplete five-arm CPU evidence')
    for a, value in osarms.items():
        require(type(value) is dict and set(value) == {
            'cpu_seconds_including_import_and_replay','peak_process_rss_bytes'},
            'wrong CPU/RSS observation structure')
        cpu = value['cpu_seconds_including_import_and_replay']
        rss = value['peak_process_rss_bytes']
        require(type(cpu) in (int, float) and math.isfinite(cpu) and cpu > 0 and
                type(rss) is int and rss > 0,
                'invalid physical resource observation')
    scores: dict[str, dict[str, float | int]] = {}
    for a in ARMS:
        per_seed = [by[(s, a)] for s in SEEDS]
        scores[a] = dict(
            mean_brier_1=round(mean(x['test_1']['brier'] for x in per_seed), 9),
            mean_brier_2=round(mean(x['test_2']['brier'] for x in per_seed), 9),
            mean_accuracy_1=round(mean(x['test_1']['accuracy'] for x in per_seed), 9),
            mean_accuracy_2=round(mean(x['test_2']['accuracy'] for x in per_seed), 9),
            split_count=sum(x['split_proposed'] for x in per_seed),
        )
    # Descriptive only, using repeated seeds on the SAME source panel.
    diffs = {
        control: {
            part: round(mean(by[(s, 'adaptive_split')][part]['brier'] - by[(s, control)][part]['brier']
                             for s in SEEDS), 9)
            for part in ('test_1','test_2')
        }
        for control in ARMS if control != 'adaptive_split'
    }
    return {
        'source_panel_sha256': SOURCE,
        'encoder': ENCODER,
        'three_training_seeds_one_dataset': True,
        'distinct_source_cases_claimed': 224,
        'stored_digest_inventory': observed,
        'five_arm_scores': scores,
        'adaptive_brier_minus_controls': diffs,
        'median_os_costs_descriptive': osarms,
        'authentic_origin_verified': False,
        'true_future_window_verified': False,
        'production_admission': 'BLOCKED',
        'authority_posture': 'DENY_ALL',
    }


def compare(first: dict, second: dict) -> dict[str, Any]:
    a, b = check(first), check(second)
    for key in ('source_panel_sha256', 'encoder', 'five_arm_scores',
                'adaptive_brier_minus_controls'):
        require(a[key] == b[key], 'paired completed-run discrepancy: '+key)
    for name in ('source-panel.json','model-files.json','41-trial-panel.json',
                 '47-trial-panel.json','53-trial-panel.json'):
        require(a['stored_digest_inventory'][name] == b['stored_digest_inventory'][name],
                'paired run file identity drift: '+name)
    # Whole Q24 JSON files contain timing/provenance fields. Their actual bytes
    # differed across completed runs; do NOT assume neural-vector equivalence.
    return {
        'study': 'paired_previous_source_SHA_runs_only',
        'source_shas': {
            'source_2331': 'd46b8ba39fed16a6715f12e0bb602aba1fb31cf5',
            'source_2344': 'a14141be69c60cb5af36dd5fc706960b3f2bfcf9',
        },
        'numerical_descriptive_outputs_equal': True,
        'encoder_json_bytes_equal': a['stored_digest_inventory']['granite-q24-features.json']['sha256']
                                     == b['stored_digest_inventory']['granite-q24-features.json']['sha256'],
        'raw_feature_vectors_independently_compared': False,
        'scores': a['five_arm_scores'],
        'adaptive_brier_minus_controls': a['adaptive_brier_minus_controls'],
        'os_medians_from_source_2344': b['median_os_costs_descriptive'],
        'classification_quality_and_longitudinal_gain_established': False,
        'host_signed_attestation_established': False,
        'production_admission': 'BLOCKED',
        'authority_posture': 'DENY_ALL',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--older-redacted-zip', required=True, type=Path)
    parser.add_argument('--newer-redacted-zip', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    opts = parser.parse_args(argv)
    try:
        older, hash1 = read_receipt(opts.older_redacted_zip)
        newer, hash2 = read_receipt(opts.newer_redacted_zip)
        report = compare(older, newer)
        report['source_artifact_receipt_sha256'] = {'older': hash1, 'newer': hash2}
        require(not opts.out.exists() and not opts.out.is_symlink(), 'refuse overwrite')
        opts.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print('DESCRIPTIVE EVIDENCE ONLY; no future NDU, no model selection')
        return 0
    except (Reject, OSError, zipfile.BadZipFile, RuntimeError) as e:
        print('REJECTED: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
