"""Bounded cleanup of only the monitor's explicitly launched, observed tree.

An unreaped direct child anchors the newly created process group. Once reaped,
only observed start-tick identities may be signalled, through PID descriptors.
No mounted-/proc PID is passed directly to a caller-namespace signal syscall.
"""

import os
import signal
import time

from resource_samples import callable_pid, process_inventory, process_stat


def signal_identity(pid, started):
    record = {'proc_visible_pid': pid, 'start_ticks': started, 'signal': 'SIGKILL'}
    descriptor = None
    try:
        current = process_stat(pid)
        if current['start_ticks'] != started:
            return {**record, 'result': 'identity_changed_not_signalled'}
        if current['state'] == 'Z':
            return {**record, 'result': 'zombie_no_userspace'}
        api_pid = callable_pid(pid, started)
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            return {**record, 'result': 'unavailable', 'error': 'identity-bound pidfd signalling unsupported'}
        descriptor = os.pidfd_open(api_pid, 0)
        # An intervening exit/reuse cannot redirect a signal after this second
        # identity check: the opened descriptor pins that process incarnation.
        if process_stat(pid)['start_ticks'] != started:
            return {**record, 'result': 'identity_changed_not_signalled'}
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        return {**record, 'namespace_pid': api_pid, 'result': 'signalled_pidfd'}
    except ProcessLookupError:
        return {**record, 'result': 'already_exited'}
    except FileNotFoundError:
        return {**record, 'result': 'already_exited'}
    except (OSError, ValueError, KeyError, IndexError) as error:
        return {**record, 'result': 'unresolved', 'error': f'{type(error).__name__}: {error}'}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def remaining(known, monitor_pid):
    live, zombies, errors = [], [], []
    for pid, started in sorted(known.items()):
        if pid == monitor_pid:
            continue
        try:
            current = process_stat(pid)
            if current['start_ticks'] == started:
                (zombies if current['state'] == 'Z' else live).append(current)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError) as error:
            errors.append({'proc_visible_pid': pid, 'start_ticks': started, 'error': str(error)})
    return live, zombies, errors


def cleanup_tree(root_api_pid, root_visible_pid, root_reaped, known, monitor_pid):
    began = time.monotonic_ns()
    record = {'requested': True, 'signals': [], 'discovery_errors': [], 'group_signal': None}
    if root_visible_pid is not None:
        try:
            _, errors = process_inventory(root_visible_pid, known)
            record['discovery_errors'].extend(errors)
        except (OSError, ValueError) as error:
            record['discovery_errors'].append({'error': str(error)})
    # Popen(start_new_session=True) created this exact group, and the direct
    # child has not been reaped. Its PID cannot yet name a different group.
    if not root_reaped:
        try:
            os.killpg(root_api_pid, signal.SIGKILL)
            record['group_signal'] = {'namespace_pgid': root_api_pid, 'result': 'signalled_owned_unreaped_group'}
        except ProcessLookupError:
            record['group_signal'] = {'namespace_pgid': root_api_pid, 'result': 'already_exited'}
        except OSError as error:
            record['group_signal'] = {'namespace_pgid': root_api_pid, 'result': 'unresolved', 'error': str(error)}
    for pid, started in sorted(known.items()):
        if pid != monitor_pid:
            record['signals'].append(signal_identity(pid, started))
    deadline = time.monotonic() + 2
    while True:
        live, zombies, errors = remaining(known, monitor_pid)
        if not live or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    record.update({'residual_live': live, 'observed_zombies': zombies, 'residual_identity_errors': errors,
                   'observed_tree_stopped': not live and not errors, 'cleanup_ns': time.monotonic_ns() - began})
    return record


def reap_child(pid):
    """Bound wait4 after cleanup; an uninterruptible child remains explicit."""
    deadline = time.monotonic() + 5
    while True:
        result = os.wait4(pid, os.WNOHANG)
        if result[0] or time.monotonic() >= deadline:
            return result
        time.sleep(0.01)
