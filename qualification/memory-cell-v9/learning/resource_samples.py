"""Linux process and logical-file observations, with missing data explicit.

Kernel semantics: https://docs.kernel.org/filesystems/proc.html
smaps_rollup avoids the approximate RSS counters in /proc/PID/stat/statm.
Process samples are sequential observations, never an atomic whole-tree peak.
"""

import os
from pathlib import Path
import stat


MAX_PROCESSES = 4096
MAX_FILES = 100000


def visible_pid(namespace_pid):
    """Resolve this process or its direct child in the mounted /proc PID view."""
    own = int(Path('/proc/self/stat').read_text().split(' ', 1)[0])
    if namespace_pid == os.getpid():
        return own
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            value = process_stat(int(path.name))
            if value['ppid'] != own:
                continue
            fields = {line.split(':', 1)[0]: line.split(':', 1)[1].split()
                      for line in (path / 'status').read_text().splitlines() if ':' in line}
            if int(fields['NSpid'][-1]) == namespace_pid:
                return int(path.name)
        except (OSError, ValueError, KeyError, IndexError):
            continue
    raise ValueError('launched child is not identifiable in mounted /proc')


def process_stat(pid):
    raw = (Path('/proc') / str(pid) / 'stat').read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    return {'pid': pid, 'ppid': int(fields[1]), 'session': int(fields[3]),
            'start_ticks': int(fields[19]), 'state': fields[0]}


def process_inventory(root_pid, known):
    inventory, errors = {}, []
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            value = process_stat(int(path.name))
            inventory[value['pid']] = value
        except (OSError, ValueError, IndexError):
            continue  # Unrelated or already exited process; relevant losses are checked below.
    root_reused = (root_pid in known and root_pid in inventory
                   and known[root_pid] != inventory[root_pid]['start_ticks'])
    selected = {pid for pid, value in inventory.items()
                if (not root_reused and (pid == root_pid or value['session'] == root_pid))
                or known.get(pid) == value['start_ticks']}
    for pid, started in known.items():
        if pid not in inventory and (Path('/proc') / str(pid)).exists():
            errors.append({'pid': pid, 'start_ticks': started, 'error': 'bound_process_stat_unreadable'})
    for _ in range(MAX_PROCESSES):
        added = {pid for pid, value in inventory.items() if value['ppid'] in selected} - selected
        if not added:
            break
        selected.update(added)
    if len(selected) > MAX_PROCESSES:
        raise ValueError('monitored process tree exceeds bound')
    observed = []
    for pid in sorted(selected):
        value = inventory[pid]
        before = value['start_ticks']
        known[pid] = before
        try:
            if value['state'] == 'Z':
                rss, pss = 0, 0  # Observed zombie state: its userspace address space is released.
            else:
                fields = {}
                for line in (Path('/proc') / str(pid) / 'smaps_rollup').read_text().splitlines():
                    parts = line.split()
                    if len(parts) == 3 and parts[0] in ('Rss:', 'Pss:') and parts[2] == 'kB':
                        fields[parts[0]] = int(parts[1]) * 1024
                rss, pss = fields['Rss:'], fields['Pss:']
            if process_stat(pid)['start_ticks'] != before:
                raise ValueError('PID reused during observation')
            observed.append({**value, 'rss_bytes': rss, 'pss_bytes': pss})
        except (OSError, ValueError, KeyError, IndexError) as error:
            errors.append({'pid': pid, 'start_ticks': before, 'error': type(error).__name__})
            observed.append({**value, 'rss_bytes': None, 'pss_bytes': None})
    return observed, errors


def validate_roots(values):
    roots = [Path(value) for value in values]
    if not roots or len(roots) > 32 or len(set(roots)) != len(roots):
        raise ValueError('one to 32 distinct accounting roots required')
    for root in roots:
        if not root.is_absolute() or '..' in root.parts or any(path.is_symlink() for path in (root, *root.parents)):
            raise ValueError('accounting roots must be absolute and nonsymlinked')
    if any(a != b and a in b.parents for a in roots for b in roots):
        raise ValueError('overlapping accounting roots would double count')
    return roots


def storage_snapshot(roots):
    logical, allocated, unique_logical, count, nodes = 0, 0, 0, 0, set()
    errors, missing = [], []
    for root in roots:
        pending = [root]
        while pending:
            path = pending.pop()
            try:
                value = path.lstat()
                if stat.S_ISLNK(value.st_mode):
                    raise ValueError('symlink excluded from registered storage')
                if stat.S_ISDIR(value.st_mode):
                    pending.extend(path.iterdir())
                elif stat.S_ISREG(value.st_mode):
                    count += 1
                    if count > MAX_FILES:
                        raise ValueError('registered storage exceeds file bound')
                    logical += value.st_size
                    node = (value.st_dev, value.st_ino)
                    if node not in nodes:
                        nodes.add(node)
                        allocated += value.st_blocks * 512
                        unique_logical += value.st_size
                else:
                    # Unix sockets and FIFOs have no file-data stock; retain their count separately.
                    missing.append({'path': str(path), 'kind': 'non_regular_no_logical_file_data'})
            except FileNotFoundError:
                if path == root:
                    missing.append({'path': str(path), 'kind': 'root_not_yet_created'})
                else:
                    errors.append({'path': str(path), 'error': 'disappeared_during_scan'})
            except (OSError, ValueError) as error:
                errors.append({'path': str(path), 'error': str(error)})
                if count > MAX_FILES:
                    pending.clear()
    return {'logical_bytes': logical if not errors else None,
            'unique_inode_logical_bytes': unique_logical if not errors else None,
            'allocated_bytes': allocated if not errors else None,
            'observed_known_logical_bytes': logical, 'regular_files': count,
            'errors': errors[:32], 'error_count': len(errors),
            'non_file_or_absent': missing[:32], 'non_file_or_absent_count': len(missing)}
