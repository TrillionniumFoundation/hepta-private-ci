"""120s/512MiB one-worker envelope; receipt, not exit0 alone, finalizes the archive."""
import time
START = time.monotonic()
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import traceback

from build_report import skeleton
from metadata_io import (Inputs, PROGRAM, RSS, WHOLE, VerifiedArchive, authorize,
                         identity, program_manifest, save)
from resource_arithmetic import nonnegative, require, roster


def verify_output(path, expected_source, peak, elapsed, inputs):
    require(type(peak) is int and 0 <= peak <= RSS and 0 <= elapsed <= WHOLE, 'whole RSS/wall envelope exceeded')
    archive_id = identity(path, inputs.budget)
    archive = VerifiedArchive(path, inputs, archive_id)
    result = archive.json('RESULT.json')
    require(result['execution_status'] in ('completed_metadata', 'completed_metadata_with_explicit_holds')
            and result['inputs_unchanged'] is True
            and result['program_manifest_before'] == result['program_manifest_after'] == expected_source,
            'result source/input/terminal state not admitted')
    require(len(result['candidates']) == 42 and {r['name'] for r in result['candidates']} == set(roster()), 'result lost candidates')
    require(result['confirmation_E_access'] is False and result['training_steps'] == result['forward_calls']
            == result['backward_calls'] == result['numerical_oracle_calls'] == 0, 'analysis execution scope differs')
    require(nonnegative(result['metadata_worker_wall_seconds'], 'worker wall') <= WHOLE
            and type(result['worker_self_peak_RSS_bytes']) is int
            and 0 <= result['worker_self_peak_RSS_bytes'] <= RSS, 'worker self envelope exceeded')
    for original, item in result['input_identities'].items():
        inputs.bind(original, item)
    require(program_manifest() == expected_source, 'analysis source changed after worker exit')
    return {'archive': archive_id, 'RESULT': archive.members['RESULT.json'], 'members': len(archive.members),
            'CRC_all_members_manifest_verified': True, 'result_status': result['execution_status'],
            'independently_adequate_selected_comparison': result.get('independently_adequate_selected_comparison', False)}


def run(args):
    launch = Path(args.launch_directory)
    launch.mkdir(exist_ok=False)
    process, usage = None, None
    row = {'schema': 'c2-resource-analysis-launch-v1', 'status': 'not_started', 'process_started': False, 'spawn_attempted': False,
           'whole_hard_wall_seconds': WHOLE, 'peak_RSS_limit_bytes': RSS, 'workers': 1, 'threads': 1,
           'started_utc': datetime.now(timezone.utc).isoformat(), 'archive_finalized': False,
           'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD',
           'confirmation_E_access': False, 'training_steps': 0, 'energy_joules': None,
           'all_42_candidate_roster': roster(), 'sampled_child_peak_RSS_bytes': 0}
    def budget():
        require(time.monotonic()-START <= WHOLE, 'whole analysis envelope exhausted')
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 <= RSS, 'launcher RSS over cap')
    inputs = Inputs(budget)
    try:
        auth, _, _ = authorize(args, inputs)
        require(not Path(args.output).exists() and not Path(str(args.output)+'.zip').exists(), 'output exists; automatic retry forbidden')
        worker = [sys.executable, '-B', str(PROGRAM/'analysis_worker.py'), '--output', args.output,
                  '--authorization', args.authorization, '--authorization-sha', args.authorization_sha,
                  '--binding', args.binding, '--binding-sha', args.binding_sha]
        # The extra virtual-address ceiling is a conservative implementation guard;
        # actual sampled and wait4 RSS still determine the declared 512MiB gate.
        wrapper = ('import os,resource,sys;resource.setrlimit(resource.RLIMIT_AS,('
                   +str(1024**3)+','+str(1024**3)+'));os.execv(sys.argv[1],sys.argv[1:])')
        argv = [sys.executable, '-B', '-c', wrapper, *worker]
        row.update(argv=argv, status='prepared', authorization=identity(args.authorization), binding=identity(args.binding))
        save(launch/'INTENT.json', row)
        env = dict(os.environ, HCSN_C2_RESOURCE_STARTED=str(START), OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                   MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1')
        with (launch/'stdout').open('xb') as stdout, (launch/'stderr').open('xb') as stderr:
            row['spawn_attempted'] = True
            process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            row.update(process_started=True, pid=process.pid, status='running')
            killed = False
            while True:
                pid, status, observed = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    usage = observed
                    process.returncode = os.waitstatus_to_exitcode(status)
                    row['returncode'] = process.returncode
                    if not killed:
                        row['status'] = 'completed' if process.returncode == 0 else 'worker_failed'
                    break
                try:
                    text = Path(f'/proc/{process.pid}/status').read_text()
                    rss = [int(r.split()[1])*1024 for r in text.splitlines() if r.startswith('VmRSS:')]
                    if rss:
                        row['sampled_child_peak_RSS_bytes'] = max(row['sampled_child_peak_RSS_bytes'], rss[0])
                except (FileNotFoundError, ProcessLookupError):
                    pass
                over_wall = time.monotonic()-START >= WHOLE
                over_rss = max(row['sampled_child_peak_RSS_bytes'], resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024) > RSS
                if (over_wall or over_rss) and not killed:
                    os.killpg(process.pid, signal.SIGKILL)
                    row.update(status='whole_wall_censored' if over_wall else 'RSS_censored')
                    killed = True
                time.sleep(.01)
        if row['status'] == 'completed':
            peak = max(row['sampled_child_peak_RSS_bytes'], usage.ru_maxrss*1024,
                       resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
            row.update(verify_output(Path(str(args.output)+'.zip'), auth['program_manifest_sha256'],
                                     peak, time.monotonic()-START, inputs))
            inputs.verify()
            budget()
            row['archive_finalized'] = True
    except Exception:
        row.update(status='launch_or_artifact_failed', archive_finalized=False, error=traceback.format_exc())
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                row['returncode'] = process.returncode
            except Exception:
                row.update(child_terminal_unknown=True, cleanup_error=traceback.format_exc())
        elif process is None and row['spawn_attempted']:
            row['process_started'] = None
    finally:
        wall = time.monotonic()-START
        own_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        if wall > WHOLE or own_peak > RSS or usage is not None and usage.ru_maxrss*1024 > RSS:
            row.update(archive_finalized=False, status='final_envelope_failed')
        row.update(whole_wall_seconds=wall, own_process_CPU_sample_seconds=time.process_time(),
                   exact_waited_child_CPU_seconds=usage.ru_utime+usage.ru_stime if usage else None,
                   exact_waited_child_peak_RSS_bytes=usage.ru_maxrss*1024 if usage else None,
                   own_peak_RSS_bytes=own_peak, child_CPU_complete=usage is not None,
                   CPU_unknown_or_lower_bound=usage is None,
                   finished_utc=datetime.now(timezone.utc).isoformat(),
                   cost_scope='Whole metadata envelope only. Worker cost is nested; neither is training cost.',
                   RSS_scope='Maximum per-process sampled and wait4 RSS; no claim of a concurrent-tree sum.')
        for name in ('stdout', 'stderr'):
            row[name] = identity(launch/name) if (launch/name).is_file() else None
        save(launch/'RECEIPT.json', row)
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('authorization', 'authorization-sha', 'binding', 'binding-sha', 'output', 'launch-directory'):
        parser.add_argument('--'+key, required=True)
    value = run(parser.parse_args())
    raise SystemExit(0 if value['status'] == 'completed' and value['archive_finalized'] else 2)
