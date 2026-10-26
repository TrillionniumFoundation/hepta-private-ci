"""Recover only JSON serialization after a fully executed immutable census.

This does not rerun a model, change a gate, refit a calibrator or change the
frozen analysis. The original nonzero process exit and stderr remain intact.
"""

import argparse
import json
from pathlib import Path
import time

from .analysis import qualification, confirmation
from .common import AREA, sha, write


def scalar(value):
    if type(value).__module__.startswith('numpy') and hasattr(value, 'item'):
        return value.item()
    raise TypeError('Unsupported report value: ' + type(value).__name__)


def recover(args):
    protocol = json.loads(args.protocol.read_text())
    analysis = AREA / 'analysis.py'
    if protocol['frozen_candidate_sha256'].get(str(analysis)) != sha(analysis):
        raise ValueError('Frozen analysis changed; serialization recovery is not permitted')
    rows = json.loads((args.run / 'ROWS.json').read_text())
    missing = json.loads((args.run / 'MISSING_ROWS.json').read_text())
    process = json.loads(args.process.read_text())
    if args.phase == 'qualification':
        summary = {p: qualification(rows, missing, p) for p in ('dynamic', 'fixed_late')}
    else:
        summary = confirmation(rows, protocol['bootstrap_seed'], protocol['bootstrap_replicates'])
    report = {'schema': 'hepta.advance.native-evaluation.v1', 'phase': args.phase, 'summary': summary,
        'policy_episodes': len(rows), 'all_missing_physical_requests': len(missing),
        'protocol_sha256': sha(args.protocol), 'wall_ns_whole_original_process': process['wall_ns'],
        'peak_rss_bytes_whole_original_process': process['child_peak_rss_bytes'],
        'new_weight_training_steps': 0, 'authority': 'deny_all', 'daemon_deployment': False,
        'report_serialization_recovered': True, 'original_process_returncode': process['returncode'],
        'original_process_receipt_sha256': sha(args.process)}
    # NumPy's scalar booleans are converted without changing values or analysis.
    converted = json.loads(json.dumps(report, default=scalar, allow_nan=False))
    write(args.run / 'RECOVERED_REPORT.json', converted)
    write(args.run / 'REPORT_RECOVERY.json', {'schema': 'hepta.advance.report-serialization-recovery.v1',
        'recovered_unix_ns': time.time_ns(), 'reason': 'Frozen analysis returned NumPy scalar booleans unsupported by the strict standard JSON encoder',
        'analysis_sha256_unchanged': sha(analysis), 'source_records_sha256': sha(args.run / 'ROWS.json'),
        'missing_records_sha256': sha(args.run / 'MISSING_ROWS.json'), 'report_sha256': sha(args.run / 'RECOVERED_REPORT.json'),
        'helper_sha256': sha(__file__), 'model_executions_added': 0, 'source_samples_added': 0,
        'thresholds_changed': False, 'original_failure_preserved': True})
    print(json.dumps(converted, sort_keys=True))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=('qualification', 'confirmation'), required=True)
    for name in ('run', 'protocol', 'process'):
        p.add_argument('--' + name, type=Path, required=True)
    recover(p.parse_args())
