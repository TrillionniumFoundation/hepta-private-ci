"""Collect immutable terminal artifacts, with no imports of model or oracle code."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import time
import traceback
import zipfile

from metadata_summary import (NAMES, PLAN_SHA, PROGRAM_MANIFEST_SHA, expected_tasks,
                              inspect_stage, read, sha, sum_observed_cost)


BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
AUDIT = Path('/home/qian-qi/hepta-hcsn-final-numerics-20261110-c385-v1')
PROGRAM = Path('/home/qian-qi/hepta-hcsn-final-numerics-program-20261110-c385-v1')
LAUNCH = BASE / 'numerics-final-audit-launch-v1'
BOOTSTRAP = BASE / 'numerics-final-audit-bootstrap-v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def require_isolated_output(out):
    candidate = Path(out).resolve()
    require(not candidate.exists(), 'new metadata output must be absent')
    for root in (AUDIT, PROGRAM, LAUNCH, BOOTSTRAP):
        protected = root.resolve()
        require(candidate != protected and protected not in candidate.parents,
                'metadata output cannot be inside original evidence')


def terminal_guard(launch, bootstrap):
    require(launch.get('schema') == 'terminal-HCSN-hard-deadline-launch-v1', 'unknown launcher receipt')
    require(launch.get('process_started') is True and launch.get('pid') == 1969758, 'different controller process')
    require(launch.get('hard_whole_wall_seconds') == 10800, 'changed audit ceiling')
    require(launch.get('status') in ('completed', 'failed', 'whole_budget_exhausted'), 'launcher is not terminal')
    require(type(launch.get('returncode')) is int, 'launcher return code missing')
    require(bootstrap.get('returncode') in (0, 1), 'bootstrap is not terminal')
    require(str(PROGRAM / 'run_audit.py') in launch.get('argv', []), 'different audit program')
    start = datetime.fromisoformat(launch['started_utc'])
    finish = datetime.fromisoformat(launch['finished_utc'])
    require(finish >= start, 'invalid terminal clock')
    if launch['status'] == 'whole_budget_exhausted':
        require(launch.get('returncode') == -9 and launch.get('stop_cause') == 'predeclared_hard10800_whole_process_group_limit', 'unknown hard-stop evidence')
    elif launch['status'] == 'completed':
        require(launch['returncode'] == 0, 'completed launcher has nonzero exit')
    else:
        require(launch['returncode'] != 0, 'failed launcher has zero exit')


def live_original_processes():
    exact = {str(PROGRAM / name) for name in ('stage.py', 'run_audit.py', 'launch_native.py')}
    rows, errors = [], []
    known_pids = {1969395, 1969757, 1969758}
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        pid = int(path.parent.name)
        try:
            raw = path.read_bytes()
            args = raw.decode('utf-8').split('\0')
            if not exact.intersection(args):
                continue
            status = (path.parent / 'status').read_text()
            state = next(line for line in status.splitlines() if line.startswith('State:'))
            rows.append({'pid': int(path.parent.name), 'state': state,
                         'cmdline_sha256': hashlib.sha256(raw).hexdigest(),
                         'executing': not state.split()[1].startswith('Z')})
        except FileNotFoundError:
            continue
        except (PermissionError, UnicodeDecodeError, StopIteration) as error:
            try:
                relevant = pid in known_pids or path.parent.stat().st_uid == os.geteuid()
            except FileNotFoundError:
                continue
            except PermissionError:
                relevant = True
            errors.append({'pid': pid, 'error': repr(error), 'possibly_relevant': relevant})
    return {'processes': rows, 'scan_errors': errors,
            'absence_established': not any(row['executing'] for row in rows)
                                   and not any(row['possibly_relevant'] for row in errors)}


def verify_closure():
    errors, checks, receipt_hashes = [], {}, {}
    def check(path, expected):
        key = str(path)
        if key in checks:
            require(checks[key]['expected_sha256'] == expected, 'conflicting expected hash: ' + key)
            return
        try:
            actual = sha(path)
            checks[key] = {'expected_sha256': expected, 'observed_sha256': actual, 'matches': actual == expected}
            if actual != expected:
                errors.append('changed: ' + key)
        except OSError as error:
            checks[key] = {'expected_sha256': expected, 'error': repr(error), 'matches': False}
            errors.append('unreadable: ' + key)
    check(PROGRAM / 'MANIFEST.json', PROGRAM_MANIFEST_SHA)
    check(PROGRAM / 'PLAN.json', PLAN_SHA)
    manifest = read(PROGRAM / 'MANIFEST.json')
    for name, identity in manifest['files'].items():
        require('..' not in Path(name).parts and not Path(name).is_absolute(), 'unsafe source manifest')
        check(PROGRAM / name, identity['sha256'])
    plan = read(PROGRAM / 'PLAN.json')
    require(list(plan['fit_roster']) == NAMES, 'plan roster differs')
    require(len(plan['finite_schedule_fixtures_per_primary_checkpoint']) == 9, 'plan fixture count differs')
    for name in NAMES:
        path = AUDIT / name / 'input-receipt.json'
        try:
            receipt = read(path)
            receipt_hashes[name] = sha(path)
            require(receipt['name'] == name, 'input receipt name differs')
            for filename, expected in receipt['bound_files'].items():
                check(Path(filename), expected)
            prepared = Path(receipt['prepared'])
            check(prepared / 'data-manifest.json', plan['data_manifest_sha256'])
            data = read(prepared / 'data-manifest.json')
            for fixed in plan['fixed_episodes']:
                row = next(row for row in data['episodes'] if row['id'] == fixed['id'])
                require(row['sha256'] == fixed['sha256'], 'episode declaration differs')
                check(prepared / row['path'], fixed['sha256'])
        except (OSError, ValueError, TypeError, KeyError, StopIteration) as error:
            errors.append(name + ': ' + repr(error))
    return {'passed': not errors, 'errors': errors, 'checks': checks}, receipt_hashes


def stable_inventory():
    rows = []
    for prefix, root in [('audit', AUDIT), ('launch', LAUNCH), ('bootstrap', BOOTSTRAP), ('program', PROGRAM)]:
        for path in sorted(root.rglob('*')):
            require(not path.is_symlink(), 'symlink in original output: ' + str(path))
            if path.is_file():
                rows.append({'path': str(path), 'member': prefix + '/' + str(path.relative_to(root)),
                             'bytes': path.stat().st_size, 'sha256': sha(path)})
    require(sum(row['bytes'] for row in rows) <= 1073741824, 'metadata archive byte ceiling exceeded')
    return rows


def collect(out):
    require_isolated_output(out)
    launch, bootstrap = read(LAUNCH / 'receipt.json'), read(BOOTSTRAP / 'receipt.json')
    terminal_guard(launch, bootstrap)
    processes = live_original_processes()
    require(processes['absence_established'], 'original process absence is not established: ' + repr(processes))
    out.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.monotonic(), time.process_time()
    collector_sources = {path.name: sha(path) for path in Path(__file__).parent.glob('*.py')}
    report = {'schema': 'terminal-numerics-read-only-postmortem-v1',
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'no_model_or_oracle_execution': True, 'numeric_retry_count': 0,
              'scientific_admission': 'HOLD', 'whole_training_domain_admission': 'HOLD',
              'training_adequacy_established': False, 'post_terminal_process_observations': processes,
              'collector_sources_before': collector_sources,
              'original_launcher_receipt': launch, 'original_bootstrap_receipt': bootstrap,
              'archived_summary_finality': 'PROVISIONAL_UNTIL_EXTERNAL_COLLECTION_RECEIPT_COMPLETED_AND_ARCHIVE_SHA256_MATCHES',
              'external_final_receipt_path': str(out / 'COLLECTION-RECEIPT.json'),
              'whole_attempt_CPU_completeness': 'incomplete_waited_processes_only_lower_bound' if launch['status'] == 'whole_budget_exhausted' else 'original_waited_process_receipts_only',
              'possible_unreaped_killed_stage_CPU_not_measured': launch['status'] == 'whole_budget_exhausted',
              'metadata_only_stricter_outer_check': 'Named finite pass additionally requires observed outer wall <= granted wall and all recorded RSS peaks <= fixed2GiB; raw original results remain unchanged.',
              'timing_scope': 'This separate metadata/hash/archive collection is after the original audit. '
                              'Original bootstrap, launcher, controller and stage timers overlap; do not sum them.'}
    try:
        inventory = stable_inventory()
        closure, input_hashes = verify_closure()
        rows = [inspect_stage(AUDIT, name, stage, input_hashes.get(name), closure['passed'])
                for name, stage in expected_tasks()]
        report.update(original_identity_closure=closure, stages=rows,
                      original_identity_closure_passed=closure['passed'],
                      original_controller_aggregate_present=(AUDIT / 'RESULT.json').exists(),
                      original_controller_archive_receipt_present=(AUDIT / 'ARCHIVE.json').exists(),
                      expected_stages=96, expected_finite_fixtures=60,
                      finite_qualified_named_fixture_count=sum(row.get('qualified_named_finite_fixture', False) for row in rows),
                      observed_stage_cost=sum_observed_cost(rows),
                      status='collected_original_terminal_artifacts')
        for path in Path(__file__).parent.glob('*.py'):
            (out / path.name).write_bytes(path.read_bytes())
        save(out / 'ORIGINAL-MANIFEST.json', inventory)
        save(out / 'RESULT.json', report)
        summary = {key: value for key, value in report.items() if key not in ('stages', 'original_identity_closure')}
        summary['original_identity_closure_passed'] = closure['passed']
        summary['original_identity_closure_errors'] = closure['errors']
        summary['stage_status_counts'] = {status: sum(row['observation_status'] == status for row in rows)
                                          for status in sorted({row['observation_status'] for row in rows})}
        summary['finite_rows'] = [{key: row.get(key) for key in ('name', 'stage', 'observation_status',
                                    'qualified_named_finite_fixture', 'raw_numerical_status', 'raw_finite_fields')}
                                  for row in rows if row['stage'].startswith('finite-')]
        summary['logrisk_rows'] = [row for row in rows if row['stage'] == 'logrisk']
        summary['uncompleted_rows'] = [{'name': row['name'], 'stage': row['stage'], 'status': row['observation_status']}
                                       for row in rows if row['observation_status'] != 'completed_artifact_chain']
        save(out / 'SUMMARY.json', summary)
        archive = Path(str(out) + '.zip')
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for row in inventory:
                zipped.write(row['path'], row['member'])
            for path in sorted(out.iterdir()):
                if path.is_file():
                    zipped.write(path, 'postmortem/' + path.name)
        with zipfile.ZipFile(archive) as zipped:
            require(zipped.testzip() is None, 'archive CRC failure')
            for row in inventory:
                with zipped.open(row['member']) as handle:
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                        digest.update(chunk)
                        size += len(chunk)
                    require(size == row['bytes'] and digest.hexdigest() == row['sha256'], 'archived original differs')
        after = stable_inventory()
        require(after == inventory, 'original files changed during metadata collection')
        final_closure, final_hashes = verify_closure()
        require(final_closure == closure and final_hashes == input_hashes, 'bound originals changed during collection')
        require({path.name: sha(path) for path in Path(__file__).parent.glob('*.py')} == collector_sources,
                'metadata collector source changed during collection')
        report['archive'] = {'path': str(archive), 'bytes': archive.stat().st_size, 'sha256': sha(archive),
                             'CRC_and_original_members_verified': True, 'original_files_unchanged': True}
        report['metadata_collection_status'] = 'completed'
    except Exception:
        report['metadata_collection_status'] = 'failed'
        report['collection_error'] = traceback.format_exc()
    finally:
        report.update(collection_wall_sample_seconds=time.monotonic() - started,
                      collection_CPU_sample_seconds=time.process_time() - cpu_started,
                      collection_peak_RSS_sample_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        save(out / 'COLLECTION-RECEIPT.json', {key: value for key, value in report.items()
                                             if key not in ('stages', 'original_identity_closure')})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.output)
    print(json.dumps({'metadata_collection_status': result['metadata_collection_status'],
                      'archive': result.get('archive'), 'output': str(args.output)}), flush=True)
    return 0 if result['metadata_collection_status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
