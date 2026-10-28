"""Supervise a fresh Linux child and retain bounded, sampled resource evidence.

The samples cover the command tree and monitor itself. Integrals are estimates,
not exact residency histories; shared pages count in each process RSS. PSS is
also retained. Exit rusage is the kernel's directly waited child accounting:
https://docs.python.org/3.12/library/os.html#os.wait4
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


sys.path.insert(0, str(Path(__file__).resolve().parent))
from resource_samples import process_inventory, process_stat, storage_snapshot, validate_roots, visible_pid
from resource_cleanup import cleanup_tree, reap_child


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def identity(path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as handle:
        while block := handle.read(1048576):
            digest.update(block)
            size += len(block)
    return {'bytes': size, 'sha256': digest.hexdigest()}


def usage(value):
    return {name: getattr(value, name) for name in (
        'ru_utime', 'ru_stime', 'ru_maxrss', 'ru_minflt', 'ru_majflt',
        'ru_inblock', 'ru_oublock', 'ru_nvcsw', 'ru_nivcsw')}


def integrate(previous, current, totals):
    duration = current['monotonic_ns'] - previous['monotonic_ns']
    for name in totals:
        left, right = previous['metrics'][name], current['metrics'][name]
        item = totals[name]
        if left is None or right is None:
            item['unobserved_interval_ns'] += duration
        else:
            item['trapezoid_numerator_byte_ns'] += (left + right) * duration
            item['observed_interval_ns'] += duration


def observe(root_pid, known, roots, began):
    started = time.monotonic_ns()
    processes, process_errors = process_inventory(root_pid, known)
    storage = storage_snapshot(roots)
    ended = time.monotonic_ns()
    valid = not process_errors
    return {'elapsed_ns': ended - began, 'monotonic_ns': ended, 'sample_started_ns': started,
            'sample_duration_ns': ended - started, 'processes': processes, 'process_errors': process_errors,
            'storage': storage, 'metrics': {
                'tree_rss_bytes': sum(item['rss_bytes'] for item in processes) if valid else None,
                'tree_pss_bytes': sum(item['pss_bytes'] for item in processes) if valid else None,
                'storage_logical_bytes': storage['logical_bytes'],
                'storage_allocated_bytes': storage['allocated_bytes']}}


def run(args):
    if not sys.platform.startswith('linux') or not hasattr(os, 'wait4'):
        raise ValueError('this resource accounting profile requires Linux /proc and wait4')
    if not 5 <= args.interval_ms <= 1000 or not 1 <= args.timeout_seconds <= 3600:
        raise ValueError('sampling or child lifecycle bound is invalid')
    roots = validate_roots(args.root)
    outputs = [Path(value) for value in (args.output, args.samples, args.stdout, args.stderr)]
    if len(set(outputs)) != 4:
        raise ValueError('monitor output paths must be distinct')
    for path in outputs:
        if not path.is_absolute() or any(value.is_symlink() for value in (path, *path.parents)) or path.exists():
            raise ValueError('monitor outputs must be new absolute nonsymlink files')
        path.parent.mkdir(parents=True, exist_ok=True)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not Path(command[0]).is_absolute():
        raise ValueError('an absolute executable and explicit argument vector are required')
    output, sample_path, stdout_path, stderr_path = outputs
    began = time.monotonic_ns()
    monitor_visible_pid = visible_pid(os.getpid())
    known = {monitor_visible_pid: process_stat(monitor_visible_pid)['start_ticks']}
    metrics = ('tree_rss_bytes', 'tree_pss_bytes', 'storage_logical_bytes', 'storage_allocated_bytes')
    totals = {name: {'trapezoid_numerator_byte_ns': 0, 'observed_interval_ns': 0,
                     'unobserved_interval_ns': 0} for name in metrics}
    peaks = {name: None for name in metrics}
    previous, first_sample_at, samples, child_usage, exited, timed_out = None, None, 0, None, False, False
    root_pid, root_visible_pid, status, sample_hash = 0, None, None, hashlib.sha256()
    sample_bytes, sample_errors, max_gap, spawned_at, exited_at = 0, 0, 0, None, None
    monitor_error, launch_error, process = None, None, None
    cleanup = {'requested': False, 'signals': [], 'residual_live': [], 'residual_identity_errors': [],
               'observed_tree_stopped': True}
    with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr, sample_path.open('xb') as sample_log:
        try:
            # The fresh session and unreaped direct child anchor group cleanup.
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            root_pid = process.pid
            spawned_at = time.monotonic_ns()
            root_visible_pid = visible_pid(root_pid)
            known[root_visible_pid] = process_stat(root_visible_pid)['start_ticks']
            while True:
                current = observe(root_visible_pid, known, roots, began)
                if first_sample_at is None:
                    first_sample_at = current['monotonic_ns']
                if previous is not None:
                    max_gap = max(max_gap, current['monotonic_ns'] - previous['monotonic_ns'])
                    integrate(previous, current, totals)
                for name in metrics:
                    value = current['metrics'][name]
                    if value is not None:
                        peaks[name] = value if peaks[name] is None else max(value, peaks[name])
                data = encoded(current)
                sample_log.write(data)
                sample_log.flush()
                sample_hash.update(data)
                sample_bytes += len(data)
                samples += 1
                sample_errors += len(current['process_errors']) + current['storage']['error_count']
                previous = current
                if not exited:
                    waited, raw_status, resources = os.wait4(root_pid, os.WNOHANG)
                    if waited:
                        exited, status, child_usage = True, os.waitstatus_to_exitcode(raw_status), usage(resources)
                        exited_at = time.monotonic_ns()
                        process.returncode = status
                live = [item for item in current['processes'] if item['pid'] != monitor_visible_pid and item['state'] != 'Z']
                if exited and not live:
                    break
                elapsed = time.monotonic_ns() - began
                if (elapsed > int(args.timeout_seconds * 1e9) or sample_bytes > 64 * 1024 * 1024
                        or stdout_path.stat().st_size + stderr_path.stat().st_size > 64 * 1024 * 1024):
                    timed_out = True
                    break
                time.sleep(args.interval_ms / 1000)
        except BaseException as error:
            monitor_error = f'{type(error).__name__}: {error}'
            if process is None:
                launch_error = monitor_error
        finally:
            if process is not None:
                if monitor_error is not None or timed_out or not exited:
                    cleanup = cleanup_tree(root_pid, root_visible_pid, exited, known, monitor_visible_pid)
                if not exited:
                    waited, raw_status, resources = reap_child(root_pid)
                    if waited:
                        exited, status, child_usage = True, os.waitstatus_to_exitcode(raw_status), usage(resources)
                        exited_at = time.monotonic_ns()
                        process.returncode = status
                    else:
                        monitor_error = monitor_error or 'direct child did not exit within bounded cleanup'
        os.fsync(sample_log.fileno())
    observation_ended = time.monotonic_ns()
    pre_gap = (first_sample_at if first_sample_at is not None else observation_ended) - began
    post_gap = observation_ended - previous['monotonic_ns'] if previous is not None else 0
    for value in totals.values():
        value['unobserved_interval_ns'] += pre_gap + post_gap
        value['sampled_byte_ns_estimate'] = (value['trapezoid_numerator_byte_ns'] // 2
                                           if value['observed_interval_ns'] > 0 else None)
        value['estimate_scope'] = 'observed inter-sample intervals only; unknown intervals excluded'
        value['exact_continuous_integral'] = False
    receipt = {'schema': 'hepta.memory.v9.sampled-lifecycle.v1', 'command': command,
        'monitor_pid': os.getpid(), 'child_pid': root_pid,
        'monitor_proc_visible_pid': monitor_visible_pid, 'child_proc_visible_pid': root_visible_pid,
        'exit_code': status, 'timed_out_or_sample_cap': timed_out,
        'started_monotonic_ns': began, 'child_spawned_monotonic_ns': spawned_at,
        'child_reaped_monotonic_ns': exited_at, 'observations_ended_monotonic_ns': observation_ended,
        'wall_ns_through_observation_close': observation_ended - began,
        'sampling_gaps': {'before_first_sample_ns': pre_gap, 'after_last_sample_ns': post_gap,
                          'included_in_unobserved_intervals': True},
        'child_exit_rusage': child_usage, 'monitor_rusage_before_final_receipt': usage(resource.getrusage(resource.RUSAGE_SELF)),
        'ru_maxrss_unit': 'KiB on this Linux profile',
        'rusage_scope': 'Kernel wait4 accounting for the directly waited command; not a per-descendant sum.',
        'roots': [str(root) for root in roots], 'observed_process_identities': [
            {'pid': pid, 'start_ticks': start} for pid, start in sorted(known.items())],
        'sample_count': samples, 'requested_interval_ms': args.interval_ms, 'maximum_observed_gap_ns': max_gap,
        'sample_error_count': sample_errors, 'peaks_of_sequential_sample_sums': peaks, 'integrals': totals,
        'samples': {'path': str(sample_path), 'bytes': sample_bytes, 'sha256': sample_hash.hexdigest()},
        'stdout': {'path': str(stdout_path), **identity(stdout_path)},
        'stderr': {'path': str(stderr_path), **identity(stderr_path)},
        'coverage_gaps': [
            'No atomic whole-tree snapshot; per-process smaps reads and filesystem scans are sequential.',
            'Short-lived or detached descendants never observed cannot be reconstructed from samples.',
            'Memory/file changes between samples and before the first sample are not exact integrals.',
            'RSS sums count shared pages per process; PSS is retained separately.',
            'Only registered regular file data stocks are measured; filesystem metadata and remote storage are not.',
            'Final receipt serialization/fsync and monitor exit follow the last sample; parent must measure that tail.',
        ], 'full_cost_exact': False,
        'monitor_error': monitor_error, 'launch_error': launch_error, 'cleanup': cleanup,
        'all_sample_points_complete': monitor_error is None and samples > 0 and sample_errors == 0,
        'passed': monitor_error is None and exited and status == 0 and not timed_out and samples > 0
                  and child_usage is not None and cleanup['observed_tree_stopped']}
    with output.open('xb') as handle:
        handle.write(encoded(receipt))
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({'receipt': str(output), 'passed': receipt['passed'], 'samples': samples,
                      'exit_code': status, 'full_cost_exact': False}, sort_keys=True), flush=True)
    return 0 if receipt['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'samples', 'stdout', 'stderr'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--root', action='append', required=True)
    parser.add_argument('--interval-ms', type=int, default=20)
    parser.add_argument('--timeout-seconds', type=int, default=1200)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
