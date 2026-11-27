"""Linux wait4 and descendant observations; no model or resource-analysis imports."""
import base64
import ctypes
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback


def enable_subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'cannot enable child subreaper')
    value = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(value), 0, 0, 0) != 0 or value.value != 1:
        raise OSError(ctypes.get_errno(), 'child subreaper not confirmed')
    return True


def read_stat(pid):
    raw = Path(f'/proc/{pid}/stat').read_bytes()
    fields = raw[raw.rfind(b')') + 2:].split()
    return {'pid': pid, 'state': fields[0].decode('ascii'), 'ppid': int(fields[1]),
            'pgrp': int(fields[2]), 'session': int(fields[3]), 'start_ticks': int(fields[19]),
            'rss_bytes': max(0, int(fields[21])) * os.sysconf('SC_PAGE_SIZE'),
            'raw_stat_base64': base64.b64encode(raw).decode('ascii'),
            'raw_stat_sha256': hashlib.sha256(raw).hexdigest()}


class ProcessTree:
    def __init__(self):
        self.observer = os.getpid()
        self.core = None
        self.known = {}
        self.unreadable = []
        self.adopted_reaped = []
        self.peak = 0
        self.subreaper = enable_subreaper()
        self.before = self.scan()
        if self.before['scan_errors'] or self.before['adopted_children']:
            raise ValueError('observer must begin with readable /proc and no existing children')

    def scan(self):
        found, errors = {}, []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():
                continue
            pid = int(entry.name)
            try:
                if entry.stat().st_uid == os.getuid():
                    found[pid] = read_stat(pid)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except Exception as exc:
                errors.append({'pid': pid, 'error_type': type(exc).__name__, 'error': str(exc)})
        owned = {pid for pid, r in found.items()
                 if pid == self.core or self.core is not None and r['pgrp'] == self.core
                 or r['ppid'] == self.observer and pid != self.core}
        owned |= {pid for pid, old in self.known.items()
                  if pid in found and found[pid]['start_ticks'] == old['start_ticks']}
        while True:
            enlarged = owned | {pid for pid, r in found.items() if r['ppid'] in owned}
            if enlarged == owned:
                break
            owned = enlarged
        for pid in sorted(owned):
            row = found[pid]
            old = self.known.get(pid)
            if old is not None and old['start_ticks'] != row['start_ticks']:
                errors.append({'pid': pid, 'error_type': 'PIDReuse', 'error': 'start_ticks changed'})
                continue
            self.known.setdefault(pid, {**row, 'first_observed_monotonic': time.monotonic()})
            self.peak = max(self.peak, row['rss_bytes'])
        records = [found[self.observer]] if self.observer in found else []
        for pid in sorted(set(self.known) | ({self.core} if self.core else set())):
            if pid in found:
                records.append(found[pid])
                continue
            try:
                row = read_stat(pid)  # Explicit absence check, not a directory-list inference.
                errors.append({'pid': pid, 'error_type': 'InventoryRace', 'error': 'known PID appeared after inventory'})
                records.append(row)
            except (FileNotFoundError, ProcessLookupError):
                records.append({'pid': pid, 'observed_absent': True, 'checked_monotonic': time.monotonic()})
            except Exception as exc:
                errors.append({'pid': pid, 'error_type': type(exc).__name__, 'error': str(exc)})
        self.unreadable.extend(errors)
        return {'observer_pid': self.observer, 'core_pid': self.core, 'core_pgid': self.core,
                'observed_monotonic': time.monotonic(), 'records': records, 'scan_errors': errors,
                'same_group_pids': sorted(pid for pid, r in found.items() if self.core and r['pgrp'] == self.core),
                'tracked_live_descendants': sorted(pid for pid in self.known if pid != self.core and pid in found),
                'adopted_children': sorted(pid for pid, r in found.items()
                                           if r['ppid'] == self.observer and pid != self.core)}

    def kill_owned(self, direct_unreaped=False):
        errors = []
        if direct_unreaped and self.core is not None:
            # Our direct child cannot reuse its PID before our wait4, even when /proc is unreadable.
            try:
                os.kill(self.core, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:
                errors.append({'pid': self.core, 'error_type': type(exc).__name__, 'error': str(exc)})
        for pid, old in sorted(self.known.items()):
            if pid == self.core and direct_unreaped:
                continue
            try:
                current = read_stat(pid)
                if current['start_ticks'] != old['start_ticks']:
                    raise ValueError('refusing to signal a reused PID')
                os.kill(pid, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except Exception as exc:
                errors.append({'pid': pid, 'error_type': type(exc).__name__, 'error': str(exc)})
        self.unreadable.extend(errors)
        return errors

    def cleanup(self, deadline):
        reaped, errors = self.adopted_reaped, []
        while time.monotonic() < deadline:
            scan = self.scan()
            if not any(scan[k] for k in ('same_group_pids', 'tracked_live_descendants', 'adopted_children')):
                return scan, reaped, errors
            errors.extend(self.kill_owned())
            for pid in scan['adopted_children']:
                if pid not in self.known:
                    errors.append({'pid': pid, 'error_type': 'UntrackedChild', 'error': 'not signaled or reaped'})
                    continue
                try:
                    waited, status, usage = os.wait4(pid, os.WNOHANG)
                    if waited:
                        reaped.append({'pid': pid, 'returncode': os.waitstatus_to_exitcode(status),
                                       'CPU_seconds': usage.ru_utime + usage.ru_stime,
                                       'peak_RSS_bytes': usage.ru_maxrss * 1024})
                except ChildProcessError:
                    pass  # A tracked process may still have a living parent.
            time.sleep(.01)
        return self.scan(), reaped, errors


def observe(argv, directory, env, wall_limit, rss_limit, cleanup_seconds=3, launch_deadline=None):
    """Run once, including real Popen-to-wait4 time. Synthetic tests use small caps."""
    row = {'process_started': False, 'spawn_attempted': False, 'returncode': None,
           'timed_out': False, 'child_terminal_unknown': False, 'unreaped_descendants': False,
           'whole_child_wall_seconds': None, 'wait4_child_CPU_seconds': None,
           'wait4_peak_RSS_bytes': None, 'sampled_peak_RSS_bytes': 0, 'process_gate_passed': False}
    tree, process, start, reaped_at = None, None, None, None
    first, final, adopted, cleanup_errors = None, None, [], []
    try:
        tree = ProcessTree()
        with (directory / 'stdout').open('xb') as stdout, (directory / 'stderr').open('xb') as stderr:
            if launch_deadline is not None and time.monotonic() > launch_deadline:
                raise TimeoutError('startup allowance exhausted before Popen')
            row['spawn_attempted'] = True
            start = time.monotonic()
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       env=env, start_new_session=True)
            row.update(process_started=True, pid=process.pid, argv=argv)
            tree.core = process.pid
            killed = False
            while time.monotonic() < start + wall_limit + cleanup_seconds:
                scan = tree.scan()
                waited, status, usage = os.wait4(process.pid, os.WNOHANG)
                if waited:
                    reaped_at = time.monotonic()
                    process.returncode = os.waitstatus_to_exitcode(status)
                    row.update(returncode=process.returncode, whole_child_wall_seconds=reaped_at-start,
                               wait4_child_CPU_seconds=usage.ru_utime+usage.ru_stime,
                               wait4_peak_RSS_bytes=usage.ru_maxrss*1024)
                    break
                over_wall = time.monotonic() - start >= wall_limit
                if over_wall or tree.peak > rss_limit or scan['scan_errors']:
                    row['timed_out'] |= over_wall
                    if not killed:
                        cleanup_errors.extend(tree.kill_owned(direct_unreaped=True))
                        killed = True
                time.sleep(.01)
            if reaped_at is None:
                row['child_terminal_unknown'] = True
            first = tree.scan()
    except Exception:
        row['error'] = traceback.format_exc()
        if row['spawn_attempted'] and process is None:
            row['process_started'] = None  # Popen failed; no invented zero-cost terminal.
        if process is not None and reaped_at is None:
            row['child_terminal_unknown'] = True
    finally:
        try:
            if tree is not None:
                if process is not None and reaped_at is None:
                    cleanup_errors.extend(tree.kill_owned(direct_unreaped=True))
                    until = time.monotonic() + cleanup_seconds
                    while time.monotonic() < until:
                        try:
                            waited, status, usage = os.wait4(process.pid, os.WNOHANG)
                            if waited:
                                reaped_at = time.monotonic()
                                process.returncode = os.waitstatus_to_exitcode(status)
                                row.update(returncode=process.returncode, child_terminal_unknown=False,
                                           whole_child_wall_seconds=reaped_at-start,
                                           wait4_child_CPU_seconds=usage.ru_utime+usage.ru_stime,
                                           wait4_peak_RSS_bytes=usage.ru_maxrss*1024)
                                break
                        except ChildProcessError:
                            break
                        time.sleep(.01)
                try:
                    first = first or tree.scan()
                    final, adopted, more = tree.cleanup(time.monotonic() + cleanup_seconds)
                    cleanup_errors.extend(more)
                except Exception:
                    error = {'error_type': 'CleanupObservationFailed', 'error': traceback.format_exc()}
                    cleanup_errors.append(error)
                    tree.unreadable.append(error)
                    adopted = tree.adopted_reaped
                    row['descendant_terminal_unknown'] = True
                    final = {'observer_pid': tree.observer, 'core_pid': tree.core, 'core_pgid': tree.core,
                             'records': [], 'same_group_pids': [], 'tracked_live_descendants': [],
                             'adopted_children': [], 'scan_errors': [error], 'observed_monotonic': time.monotonic()}
                    first = first or final
                row.update(sampled_peak_RSS_bytes=tree.peak,
                           process_observations={'subreaper_enabled': tree.subreaper, 'before_start': tree.before,
                               'after_direct_wait4': first, 'after_cleanup': final,
                               'tracked_identities': [tree.known[p] for p in sorted(tree.known)],
                               'unreadable': tree.unreadable}, adopted_child_wait4=adopted,
                           cleanup_errors=cleanup_errors)
                row['unreaped_descendants'] = bool(row.get('descendant_terminal_unknown')) or any(final[k] for k in
                    ('same_group_pids', 'tracked_live_descendants', 'adopted_children'))
                empty = lambda s: not any(s[k] for k in
                    ('same_group_pids', 'tracked_live_descendants', 'adopted_children', 'scan_errors'))
                row['process_gate_passed'] = bool(reaped_at is not None and row['returncode'] == 0
                    and not row['timed_out'] and row['whole_child_wall_seconds'] <= wall_limit
                    and max(tree.peak, row['wait4_peak_RSS_bytes']) <= rss_limit
                    and not adopted and not tree.unreadable and not cleanup_errors and empty(first) and empty(final)
                    and tree.core in tree.known and 'error' not in row)
        except Exception:
            error = {'error_type': 'FinalCleanupFailed', 'error': traceback.format_exc()}
            cleanup_errors.append(error)
            row.update(process_gate_passed=False, descendant_terminal_unknown=True, unreaped_descendants=True,
                       cleanup_errors=cleanup_errors)
            if process is not None and reaped_at is None:
                row['child_terminal_unknown'] = True
            if tree is not None:
                tree.unreadable.append(error)
                adopted = tree.adopted_reaped
                row.update(sampled_peak_RSS_bytes=tree.peak, adopted_child_wait4=adopted,
                    process_observations={'subreaper_enabled': tree.subreaper, 'before_start': tree.before,
                        'after_direct_wait4': first, 'after_cleanup': final,
                        'tracked_identities': [tree.known[p] for p in sorted(tree.known)],
                        'unreadable': tree.unreadable})
        row.update(child_wall_lower_bound_seconds=time.monotonic()-start if start is not None and reaped_at is None else None,
                   popen_started_monotonic=start, wait4_completed_monotonic=reaped_at,
                   direct_child_CPU_complete=reaped_at is not None,
                   total_attempt_CPU_unknown_or_lower_bound=reaped_at is None or bool(adopted)
                       or row['unreaped_descendants'] or row['process_started'] is None
                       or bool(cleanup_errors) or bool(tree is not None and tree.unreadable),
                   CPU_scope='Direct wait4 includes descendants reaped by that child. Adopted wait4 rows are disjoint and separately recorded; no inference from a missing terminal.')
        if not row['direct_child_CPU_complete'] or row['total_attempt_CPU_unknown_or_lower_bound']:
            row['process_gate_passed'] = False
    return row, tree
