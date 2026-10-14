"""Validate real GNU time -v process resource receipts for shadow Stem/Laya.

The process profiling *includes* cold model load and Python framework set-up;
it excludes prior source/weight downloads.  It is not steady-state per-item
latency, FLOPs, GPU energy, signed host evidence, or equal lifecycle costing.
No receipt or observed improvement authorizes production model selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import shlex

MODEL_CODE_PATH = 'qualification/neuron-dynamic-learning/agnews_paired_shadow.py'
MAX_CAPTURE_BYTES = 16 * 1024
TIME_FIELDS = {
    'Command being timed': 'command',
    'User time (seconds)': 'user_cpu_seconds',
    'System time (seconds)': 'system_cpu_seconds',
    'Elapsed (wall clock) time (h:mm:ss or m:ss)': 'wall_seconds',
    'Maximum resident set size (kbytes)': 'peak_rss_kib',
    'Exit status': 'exit_status',
}


class ResourceEvidenceError(ValueError):
    """Missing, invalid or unbound physical host measurements."""


def digest(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _nonnegative_decimal(value: str) -> float:
    if not re.fullmatch(r'(?:0|[0-9]+)(?:\.[0-9]+)?', value):
        raise ResourceEvidenceError('nondecimal, negative or nonfinite GNU time reading')
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ResourceEvidenceError('nonfinite GNU time reading')
    return parsed


def _elapsed(value: str) -> float:
    fields = value.split(':')
    if len(fields) not in (2, 3):
        raise ResourceEvidenceError('elapsed must be m:ss or h:mm:ss')
    if not all(re.fullmatch(r'[0-9]+', item) for item in fields[:-1]):
        raise ResourceEvidenceError('noninteger elapsed minutes/hours')
    seconds = _nonnegative_decimal(fields[-1])
    minutes = int(fields[-2])
    if not 0 <= seconds < 60 or (len(fields) == 3 and minutes >= 60):
        raise ResourceEvidenceError('malformed elapsed minutes/seconds')
    return (int(fields[0]) * 3600 if len(fields) == 3 else 0) + minutes*60 + seconds


def read_gnu_time(path: Path, arm: str) -> dict:
    """Parse the *real child process* GNU time output, never fabricated microseconds."""
    if arm not in ('gemma', 'laya'):
        raise ResourceEvidenceError('unknown physical model arm')
    if not isinstance(path, Path) or not path.is_file() or path.is_symlink():
        raise ResourceEvidenceError('missing actual resource file')
    if not 0 < path.stat().st_size <= MAX_CAPTURE_BYTES:
        raise ResourceEvidenceError('unbounded/empty process resource file')
    source = path.read_bytes()
    try:
        body = source.decode('utf-8')
    except UnicodeError as exc:
        raise ResourceEvidenceError('invalid resource log encoding') from exc
    if '\x00' in body or '\r' in body:
        raise ResourceEvidenceError('unsafe resource log bytes')
    fields = {}
    for line in body.splitlines():
        if ':' not in line:
            continue
        # GNU time accepts both tabs and spaces; never infer fields from prose.
        label, value = line.strip().split(': ', 1) if ': ' in line else ('', '')
        if label in TIME_FIELDS:
            key = TIME_FIELDS[label]
            if key in fields:
                raise ResourceEvidenceError('duplicate measured field')
            fields[key] = value.strip()
    if set(fields) != set(TIME_FIELDS.values()):
        raise ResourceEvidenceError('missing mandatory GNU time measurements')
    line = fields['command']
    if len(line) < 3 or line[0] != '"' or line[-1] != '"':
        raise ResourceEvidenceError('command lacks unambiguous GNU time quotes')
    try:
        args = shlex.split(line[1:-1])
    except ValueError as exc:
        raise ResourceEvidenceError('invalid measured invocation') from exc
    if (len(args) < 5 or not args[0].endswith('/python')
            or args[1] != MODEL_CODE_PATH or '--mode' not in args
            or args.count('--mode') != 1
            or args.index('--mode') + 1 >= len(args)
            or args[args.index('--mode')+1] != arm
            or '--confirmatory-panel' not in args
            or '--confirmatory-output' not in args):
        raise ResourceEvidenceError('resource log came from wrong model command')
    exit_status = _nonnegative_decimal(fields['exit_status'])
    if exit_status != 0 or not fields['exit_status'].isdigit():
        raise ResourceEvidenceError('model invocation did not exit successfully')
    peak_kib = _nonnegative_decimal(fields['peak_rss_kib'])
    if not fields['peak_rss_kib'].isdigit() or peak_kib < 100_000:
        raise ResourceEvidenceError('implausible/not-real pretrained model RSS')
    wall = _elapsed(fields['wall_seconds'])
    if wall <= 0:
        raise ResourceEvidenceError('no measurable wall-clock execution')
    user = _nonnegative_decimal(fields['user_cpu_seconds'])
    system = _nonnegative_decimal(fields['system_cpu_seconds'])
    if user + system <= 0:
        raise ResourceEvidenceError('model process consumed no CPU time')
    return {
        'arm': arm,
        'measurement_tool': 'GNU time --verbose',
        'raw_time_log_sha256': digest(source),
        'command_includes_prelocked_val2': True,
        'wall_seconds_including_model_load': wall,
        'process_user_cpu_seconds': user,
        'process_system_cpu_seconds': system,
        'process_peak_rss_bytes': int(peak_kib) * 1024,
        'model_process_exit_status': 0,
        'process_metric_signature_verified': False,
    }


def audit(gemma_path: Path, laya_path: Path, gemma_reports: list,
          laya_report: dict) -> dict:
    if not isinstance(gemma_reports, list) or len(gemma_reports) != 2 or not isinstance(laya_report, dict):
        raise ResourceEvidenceError('missing actual paired arm output')
    by_id = {r.get('arm_id'):r for r in gemma_reports if isinstance(r, dict)}
    if set(by_id) != {'gemma2_frozen_head', 'gemma2_trained_head'} or len(by_id) != 2:
        raise ResourceEvidenceError('wrong complete frozen/trained Head bundle')
    if (laya_report.get('arm_id') != 'laya421_frozen'
            or any(r.get('production_promotion') != 'DENY_ALL'
                   for r in [*gemma_reports, laya_report])
            or any(r.get('real_model_execution_claim') is not True
                   for r in [*gemma_reports,laya_report])
            or any(r.get('model_execution_independently_attested') is not False
                   for r in [*gemma_reports,laya_report])):
        raise ResourceEvidenceError('unbound or overclaimed real model output')
    frozen = by_id['gemma2_frozen_head'].get('metadata')
    trained = by_id['gemma2_trained_head'].get('metadata')
    laya = laya_report.get('metadata')
    if not all(isinstance(x, dict) for x in (frozen, trained, laya)):
        raise ResourceEvidenceError('missing model metadata')
    if (frozen.get('backend') != 'google/embeddinggemma-2'
            or trained.get('backend') != 'google/embeddinggemma-2'
            or frozen.get('stem_digest') != trained.get('stem_digest')
            or laya.get('backend') != 'convaiinnovations/laya'
            or laya.get('trainable_parameters') != 0):
        raise ResourceEvidenceError('measured model identity not bound')
    gemma = read_gnu_time(gemma_path, 'gemma')
    laya_measured = read_gnu_time(laya_path, 'laya')
    return {
        'schema': 'hepta.stem.paired-real-process-resources.shadow.v1',
        'resource_scope': 'hosted_cpu_process_entire_model_load_and_val1_val2_execution',
        'excludes': ['pretraining','weight_source_download', 'training_dataset_download',
                     'energy_joules','external_signatures','steady_state_queue_and_p99'],
        'measurements': {'gemma': gemma, 'laya': laya_measured},
        'paired_model_reports_sha256': {
            'gemma_frozen_head': digest(canonical(by_id['gemma2_frozen_head'])),
            'gemma_trained_head': digest(canonical(by_id['gemma2_trained_head'])),
            'laya421_frozen': digest(canonical(laya_report)),
        },
        'gemma_phase_includes_sgd': True,
        'laya_phase_includes_sgd': False,
        'same_host_profile_independently_attested': False,
        'independent_final_use_authority': False,
        'model_lifetime_cost_equalization_proven': False,
        'production_promotion': 'DENY_ALL',
    }


def main():
    parser=argparse.ArgumentParser(description='Scope-bound process resource audit')
    for arg in ('gemma-time','laya-time','gemma-report','laya-report','out'):
        parser.add_argument('--'+arg, required=True, type=Path)
    args=parser.parse_args()
    result=audit(args.gemma_time,args.laya_time,
                 json.loads(args.gemma_report.read_text(encoding='utf-8')),
                 json.loads(args.laya_report.read_text(encoding='utf-8')))
    args.out.write_bytes(canonical(result))
    print(json.dumps({'report_sha256':digest(canonical(result)),
                      'peak_gemma_rss_bytes':result['measurements']['gemma']['process_peak_rss_bytes'],
                      'peak_laya_rss_bytes':result['measurements']['laya']['process_peak_rss_bytes'],
                      'production_promotion':'DENY_ALL'}, sort_keys=True))


if __name__=='__main__': main()
