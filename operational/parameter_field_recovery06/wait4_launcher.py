"""Execution06 detached measured supervisor parent; never uploads or retries.

CONTEXT_RECONSTRUCTION. Full-entry-to-exit wait4 is preserved even if publishing
START fails after Popen returned. Historical execution04 A17 CPU is not added.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

BASE = Path('/workspace/scratch/178ced6a501f')
SOURCE = BASE / 'fullstudy_recovery06_git'
OPS = BASE / 'fullstudy_execution06_ops'
RAW = BASE / 'fullstudy_execution06_durable_raw'
EPISODE = 'execution06_detached_20261030'
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery04 import durable_archive as archive
from operational.parameter_field_recovery06.owned_children import proc_identity, run_controller


def supervisor_argv(config, config_desc):
    return [config['python'], '-B', config['descriptors']['own_supervisor']['path'],
            '--config', config_desc['path'], '--expected-config-sha256', config_desc['sha256'], '--execute']


def run_measured(config, config_desc, directory, *, detachment=None):
    """Measure one configured supervisor, retaining failed construction evidence."""
    measuring_identity = proc_identity(os.getpid())
    if config.get('schema') == 'hepta.fullstudy.execution06.configuration.1':
        archive.require(detachment is not None, 'Production launch requires the registered detached bootstrap')
    if detachment is not None:
        from operational.parameter_field_recovery06.daemon_bootstrap import verify_ready
        binding = {'execution_episode': EPISODE, 'pipeline_config': config_desc,
                   'daemon_bootstrap': config['descriptors']['daemon_bootstrap'],
                   'wait4_launcher': config['descriptors']['wait4_launcher']}
        ready = verify_ready(detachment, binding)
        archive.require(ready['measuring_parent_identity'] == measuring_identity,
                        'This is not the actual detached measuring parent')
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    argv = supervisor_argv(config, config_desc)
    archive.write_json(directory / 'INTENT.json', {
        'schema': 'hepta.execution06.outer-launch-intent.1', 'execution_episode': EPISODE,
        'config': config_desc, 'argv': argv, 'cwd': config['empty_cwd'], 'start_new_session': True,
        'detached_start': detachment, 'measuring_parent_identity': measuring_identity,
        'automatic_retry': False})
    core = SimpleNamespace(subprocess=subprocess)
    started, cpu = time.monotonic(), time.process_time()
    captured = {}

    def execute():
        with (directory / 'supervisor.stdout.log').open('xb') as out, (directory / 'supervisor.stderr.log').open('xb') as err:
            child = core.subprocess.Popen(argv, cwd=config['empty_cwd'], stdout=out, stderr=err,
                    env={**os.environ, 'PYTHONPATH': config['source_root'], 'PYTHONDONTWRITEBYTECODE': '1'},
                    start_new_session=True)
        captured['child'] = child
        observed = proc_identity(child.pid)
        archive.require(observed['pgid'] == child.pid == observed['sid'], 'Supervisor new session differs')
        captured['identity'] = observed
        archive.write_json(directory / 'START.json', {'config': config_desc, 'argv': argv,
                           'child_identity': observed, 'parent_identity': proc_identity(os.getpid()),
                           'started_unix': time.time(), 'detached_start': detachment})
        while child.poll() is None:
            current = proc_identity(os.getpid())
            archive.require(current == measuring_identity,
                'Measuring parent identity changed: ' + json.dumps({'expected': measuring_identity, 'observed': current}, sort_keys=True))
            time.sleep(0.05)
        archive.require(proc_identity(os.getpid()) == measuring_identity, 'Measuring parent changed at child exit')
        return child.wait4

    try:
        usage = run_controller(core, execute, directory / 'owned_supervisor',
                               binding={'execution_episode': EPISODE, 'pipeline_config': config_desc,
                                        'scientific_scope': 'Supervisor plus its waited descendants, excluding historical imported A17 execution.'},
                               term_grace_seconds=15.0, kill_wait_seconds=5.0)
    except BaseException as error:
        owner = directory / 'owned_supervisor/CLOSURE.json'
        failure = {'schema': 'hepta.execution06.outer-launch-failure.1', 'execution_episode': EPISODE,
                   'config': config_desc, 'error_type': type(error).__name__, 'message': str(error),
                   'automatic_retry': False, 'owned_child_closure': archive.descriptor(owner) if owner.is_file() else None,
                   'returned_supervisor_wait4': captured['child'].wait4 if 'child' in captured else None,
                   'construction_cost_unknown_unless_recorded_in_owned_closure': 'child' not in captured,
                   'launcher_cpu_seconds_separate_until_failure_record': time.process_time()-cpu,
                   'wall_seconds_until_failure_record': time.monotonic()-started}
        try:
            archive.write_json(directory / 'LAUNCH_FAILED.json', failure)
        except BaseException as receipt_error:
            error.add_note('Outer launch failure receipt also failed: ' + repr(receipt_error))
        raise
    child = captured['child']
    result = {'schema': 'hepta.fullstudy.execution06-outer-wait4.1', 'execution_episode': EPISODE,
              'config': config_desc, 'argv': argv, 'child_identity': captured['identity'], 'waited_pid': child.pid,
              'measuring_parent_identity': measuring_identity, 'detached_start': detachment,
              'exit_code': usage['exit_code'], 'wait_status': usage['wait_status'],
              'wall_seconds': time.monotonic()-started,
              'user_cpu_seconds': usage['user_cpu_seconds'], 'system_cpu_seconds': usage['system_cpu_seconds'],
              'total_cpu_seconds_inclusive': usage['cpu_seconds'], 'peak_rss_bytes': usage['peak_rss_bytes'],
              'launcher_cpu_seconds_separate': time.process_time()-cpu,
              'measurement_scope': 'Full supervisor entry-to-exit and descendants it waited for; excludes external root upload/readback and historical A17 execution.',
              'do_not_add_nested_science_driver_archive_or_supervisor_ledgers': True,
              'imported_A17_historical_scientific_cpu_not_added': True,
              'unwaited_orphan_costs_unknown_if_failure': child.returncode != 0,
              'owned_supervisor_closure': archive.descriptor(directory / 'owned_supervisor/CLOSURE.json'),
              'pending_root_durable_closure': True}
    if child.returncode == 0:
        primary = Path(config['ops_root']) / 'COMPLETE.json'
        try:
            complete = archive.read(primary)
            archive.require(complete.get('schema') == 'hepta.fullstudy.pipeline-completion.4'
                            and complete.get('complete') is True, 'Zero exit lacks primary completion')
            result['primary_complete'] = archive.descriptor(primary)
        except BaseException as error:
            try:
                archive.write_json(directory / 'WAIT4_PRIMARY_INVALID.json', {
                    **result, 'primary_completion_verified': False,
                    'primary_error_type': type(error).__name__, 'primary_error': str(error)})
            except BaseException as receipt_error:
                error.add_note('Invalid-primary wait4 receipt also failed: ' + repr(receipt_error))
            raise
    archive.write_json(directory / 'WAIT4_COMPLETE.json', result)
    return result


def load_config(path, expected_sha):
    config_desc = archive.descriptor(path)
    archive.require(config_desc['sha256'] == expected_sha, 'Config SHA differs')
    config = archive.read(path)
    archive.require(config.get('schema') == 'hepta.fullstudy.execution06.configuration.1'
                    and config.get('execution_episode') == EPISODE
                    and Path(config['source_root']).resolve() == SOURCE
                    and Path(config['ops_root']).resolve() == OPS
                    and Path(config['raw_root']).resolve() == RAW, 'Wrong measured execution')
    python = str(BASE / 'runtime_recovery_20261030/venv/bin/python')
    archive.require(config['python'] == python and sys.version_info[:3] == (3, 12, 14), 'Wrong verified interpreter')
    for name in ('own_supervisor', 'durable_archive', 'wait4_launcher', 'daemon_bootstrap', 'producer_config', 'producer_map', 'import_receipt'):
        archive.verify_descriptor(config['descriptors'][name])
    pinned = config['descriptors']['wait4_launcher']
    archive.require(pinned['path'] == str(Path(__file__).resolve()), 'Wrong measured launcher pin')
    archive.require(config['descriptors']['durable_archive']['path'] == str(Path(archive.__file__).resolve()),
                    'Wrong archive helper pin')
    archive.require(config['descriptors']['daemon_bootstrap']['path'] ==
                    str(Path(__file__).with_name('daemon_bootstrap.py').resolve()), 'Wrong daemon bootstrap pin')
    return config, config_desc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--expected-config-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    archive.require(not args.execute,
                    'Direct measuring-parent execution is forbidden; use the registered daemon_bootstrap.py --execute')
    config, config_desc = load_config(args.config, args.expected_config_sha256)
    print(json.dumps({'status': 'MEASURED_LAUNCH_PREPARED_ONLY',
                      'production_entrypoint': config['descriptors']['daemon_bootstrap'],
                      'argv': supervisor_argv(config, config_desc),
                      'workers_started': 0, 'uploads_started': 0}))


if __name__ == '__main__':
    main()
