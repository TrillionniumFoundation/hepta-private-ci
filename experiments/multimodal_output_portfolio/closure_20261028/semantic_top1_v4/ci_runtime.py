"""Read visible Linux memory limits; missing or ambiguous nonroot data blocks work."""
from pathlib import Path, PurePosixPath
import re


def canonical_absolute(value):
    path = PurePosixPath(value)
    if (not path.is_absolute() or value.startswith('//') or '..' in path.parts
            or '.' in value.split('/') or str(path) != value):
        raise ValueError('Noncanonical cgroup path')
    return path


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def nonnegative_integer(value):
    if not value or any(character not in '0123456789' for character in value):
        raise ValueError('Invalid memory interface value')
    return int(value)


def observe(meminfo, cgroup, mountinfo, process_status, read_text):
    """Inject text readers for small fixtures; real observation uses proc and cgroupfs."""
    result = {'effective_headroom_bytes': 0, 'observation_status': 'unavailable',
              'invisible_ancestor_limits_known': False,
              'observation_is_future_memory_guarantee': False,
              'scope': 'Host MemAvailable and observable current/ancestor cgroup-v2 limits only. Unobservable ancestor restrictions and concurrent allocation changes are not inferred.'}
    try:
        values = {}
        for line in meminfo.splitlines():
            if line.startswith(('MemAvailable:', 'MemTotal:')):
                key, raw = line.split(':', 1)
                fields = raw.split()
                if key in values or len(fields) != 2 or fields[1] != 'kB':
                    raise ValueError('Ambiguous host memory observation')
                values[key] = nonnegative_integer(fields[0]) * 1024
        if set(values) != {'MemAvailable', 'MemTotal'} or values['MemAvailable'] > values['MemTotal']:
            raise ValueError('Missing or inconsistent host memory observation')
        result.update(host_available_bytes=values['MemAvailable'], host_total_bytes=values['MemTotal'])
        membership = []
        for line in cgroup.splitlines():
            fields = line.split(':', 2)
            if len(fields) == 3 and fields[:2] == ['0', '']:
                membership.append(canonical_absolute(fields[2]))
        if len(membership) != 1:
            raise ValueError('Expected one visible cgroup-v2 membership')
        member = membership[0]
        mappings = []
        for line in mountinfo.splitlines():
            fields = line.split(' - ')
            if len(fields) != 2 or fields[1].split()[0] != 'cgroup2':
                continue
            left = fields[0].split()
            if len(left) < 6:
                raise ValueError('Invalid cgroup mount record')
            root = canonical_absolute(unescape_mount(left[3]))
            point = canonical_absolute(unescape_mount(left[4]))
            if member.is_relative_to(root):
                current = point / member.relative_to(root)
                kind = 'membership_relative_to_mount_root'
            elif member == PurePosixPath('/'):
                current, kind = point, 'namespace_root_maps_to_visible_mount_root'
            else:
                continue
            if not current.is_relative_to(point):
                raise ValueError('Cgroup mapping escapes its visible mount')
            mappings.append((root, point, current, kind))
        if len(mappings) != 1:
            raise ValueError('Cgroup-v2 mount mapping is missing or ambiguous')
        root, point, current, kind = mappings[0]
        result.update(cgroup_membership=str(member), cgroup_mount_root=str(root),
                      cgroup_mountpoint=str(point), current_cgroup_path=str(current), mapping_kind=kind)
        observations = []
        finite_headroom = []
        path = current
        while True:
            raw = {}
            for name in ('memory.current', 'memory.max'):
                try:
                    raw[name] = read_text(str(path / name)).strip()
                except FileNotFoundError:
                    raw[name] = None
            if raw['memory.current'] is None or raw['memory.max'] is None:
                if (path != point or root != PurePosixPath('/')
                        or any(value is not None for value in raw.values())):
                    raise ValueError('Nonroot or partial memory-interface observation is unavailable')
                observations.append({'path': str(path), 'visible_hierarchy_root': True,
                                     'memory_interface': 'both_files_absent_at_visible_root',
                                     'interpretation': 'Use host observation plus other visible limits; absence is not proof of unlimited memory or absent invisible ancestors.'})
            else:
                used = nonnegative_integer(raw['memory.current'])
                limit = None if raw['memory.max'] == 'max' else nonnegative_integer(raw['memory.max'])
                row = {'path': str(path), 'visible_hierarchy_root': path == point,
                       'memory_current_raw': raw['memory.current'], 'memory_max_raw': raw['memory.max'],
                       'current_bytes': used, 'limit_bytes': limit}
                if limit is not None:
                    row['remaining_bytes'] = max(0, limit - used)
                    finite_headroom.append(row['remaining_bytes'])
                observations.append(row)
            if path == point:
                break
            path = path.parent
        result['cgroup_ancestor_observations'] = observations
        result['cgroup_current_bytes'] = observations[0].get('current_bytes')
        result['cgroup_limit_bytes'] = observations[0].get('limit_bytes')
        result['effective_headroom_bytes'] = min([values['MemAvailable'], *finite_headroom])
        result['observation_status'] = 'observed_visible_limits' if finite_headroom else 'host_observation_without_finite_visible_cap'
        for line in process_status.splitlines():
            if line.startswith(('VmRSS:', 'VmHWM:')):
                key, raw = line.split(':', 1)
                fields = raw.split()
                if len(fields) != 2 or fields[1] != 'kB':
                    raise ValueError('Invalid process memory observation')
                result[key + '_bytes'] = nonnegative_integer(fields[0]) * 1024
    except (OSError, ValueError, IndexError) as error:
        result.update(effective_headroom_bytes=0, observation_status='unavailable_fail_closed',
                      observation_error=type(error).__name__ + ': ' + str(error))
    return result


def resources():
    try:
        return observe(Path('/proc/meminfo').read_text(), Path('/proc/self/cgroup').read_text(),
                       Path('/proc/self/mountinfo').read_text(), Path('/proc/self/status').read_text(),
                       lambda path: Path(path).read_text())
    except OSError as error:
        return {'effective_headroom_bytes': 0, 'observation_status': 'unavailable_fail_closed',
                'observation_error': type(error).__name__ + ': ' + str(error),
                'invisible_ancestor_limits_known': False, 'observation_is_future_memory_guarantee': False}
