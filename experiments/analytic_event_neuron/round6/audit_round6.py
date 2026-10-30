"""Read-only independent numerical/transport audit with fresh native replay logs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import scipy

from .audit_replay import Replay
from .audit_training import audit_seed
from .audit_transport import Checks, file_sha
from .data import DOMAINS, SEEDS, SMOKE_SEED


def audit(run_dir, output, phase, expected_freeze=None, smoke=False):
    run_dir, output = Path(run_dir).resolve(), Path(output).resolve()
    if output.is_relative_to(run_dir) or output.exists():
        raise ValueError('A new review directory outside the immutable scientific run is required')
    output.mkdir(parents=True)
    started, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    child_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    sources = {p.name: file_sha(p) for p in Path(__file__).parent.glob('audit_*.py')}
    sources['reference.py'] = file_sha(Path(__file__).with_name('reference.py'))
    initial = {'schema': 'hepta.acquired-feedback.independent-review.v6', 'phase': phase,
               'run_dir': str(run_dir), 'namespace': 'smoke' if smoke else 'registered',
               'expected_freeze_sha256': expected_freeze, 'reviewer_sources_sha256': sources,
               'started_utc': datetime.now(timezone.utc).isoformat(),
               'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__,
               'scipy': scipy.__version__, 'platform': platform.platform(),
               'data_generation_or_primary_training_performed': False,
               'EM_and_GD_trajectories_reconstructed_for_verification': phase == 'preparation',
               'native_execution_is_new': True, 'native_build_is_new': False}
    (output / 'STARTED.json').write_text(json.dumps(initial, indent=2, sort_keys=True) + '\n')
    checks, scopes, replay, replay_summary, failure, statistical_review = Checks(), [], None, None, None, None
    try:
        if smoke:
            checks.require(expected_freeze is None and not (run_dir / 'FREEZE.json').exists(), 'development namespace only')
        elif phase == 'preparation':
            checks.require(expected_freeze is None and not (run_dir / 'FREEZE.json').exists()
                           and not (run_dir / 'confirmation').exists(), 'pre-freeze preparation audit')
            from .lifecycle import verify_prepared
            prepared = verify_prepared(run_dir)
            initial['sources_sha256'] = prepared['sources_sha256']
            initial['prepared_sha256'] = file_sha(run_dir / 'PREPARED.json')
        else:
            from .lifecycle import verify
            frozen = verify(run_dir, expected_freeze)
            initial['sources_sha256'] = frozen['sources_sha256']
            initial['prepared_sha256'] = frozen['prepared_sha256']
        replay = Replay(run_dir / 'native', output / 'replay', checks)
        seeds = (SMOKE_SEED,) if smoke else SEEDS
        if phase == 'preparation':
            for seed in seeds:
                scopes.append(audit_seed(run_dir / 'prepared' / f'seed_{seed}', replay, checks))
        else:
            from .audit_confirmation import audit_scope
            for seed in seeds:
                for domain in ('nominal',) if smoke else DOMAINS:
                    scopes.append(audit_scope(run_dir, seed, domain, replay, checks))
            if not smoke:
                from .audit_statistics import audit_statistics
                statistical_review = audit_statistics(run_dir, expected_freeze, checks)
        for name, expected in sources.items():
            checks.require(file_sha(Path(__file__).with_name(name)) == expected, 'review source stable throughout execution')
        if not smoke:
            if phase == 'preparation':
                verify_prepared(run_dir)
            else:
                verify(run_dir, expected_freeze)
    except Exception as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    finally:
        if replay is not None:
            replay_summary = replay.close()
        after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        report = {**initial, 'finished_utc': datetime.now(timezone.utc).isoformat(),
                  'passed': failure is None, 'failure': failure, 'checks': checks.count,
                  'maximum_errors': checks.maxima, 'scopes': scopes, 'replay': replay_summary,
                  'statistical_review': statistical_review,
                  'wall_ns': time.perf_counter_ns() - started,
                  'parent_cpu_ns': time.process_time_ns() - parent_cpu,
                  'children_user_seconds': after_cpu.ru_utime - child_cpu.ru_utime,
                  'children_system_seconds': after_cpu.ru_stime - child_cpu.ru_stime,
                  'timing_scope': 'review function, excludes interpreter/import startup and final receipt serialization',
                  'native_energy': None, 'financial_cost': None, 'production_promotion': False}
        native_log = output / 'replay' / 'NATIVE_REPLAY.jsonl.gz'
        if native_log.exists():
            report['native_replay_log_sha256'] = file_sha(native_log)
        (output / 'REVIEW.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        if failure is None and not smoke and phase == 'preparation':
            gate = run_dir / 'validation' / 'PREPARED_REVIEW.json'
            gate.parent.mkdir(parents=True, exist_ok=True)
            with gate.open('x') as stream:
                json.dump(report, stream, indent=2, sort_keys=True)
                stream.write('\n')
        print(json.dumps({'passed': failure is None, 'failure': failure, 'checks': checks.count,
                          'scopes_completed': len(scopes), 'review': str(output / 'REVIEW.json')}))
    if failure is not None:
        raise RuntimeError(failure)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--phase', choices=('preparation', 'confirmation'), required=True)
    parser.add_argument('--expected-freeze-sha256')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    audit(args.run_dir, args.output, args.phase, args.expected_freeze_sha256, args.smoke)


if __name__ == '__main__':
    main()
