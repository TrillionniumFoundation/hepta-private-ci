"""Full tracked source bytes/types; Windows Git modes are not POSIX chmod evidence."""
import hashlib
import os

from a32_sshsig_format_boundaries import blob, boundary, inventory, snapshot


def windows_raw_snapshot(root, entries):
    """Bind actual bytes/link type, while Git index/tree separately binds executable modes."""
    result = {}
    for path, entry in entries.items():
        current = root / path
        if any(parent.is_symlink() for parent in current.parents if parent != root and root in parent.parents):
            raise RuntimeError('symlink ancestor in source: ' + path)
        mode = entry['mode']
        if mode == '120000':
            if not current.is_symlink():
                raise RuntimeError('HOLD: Windows checkout did not materialize real tracked symlink: ' + path)
            data = os.fsencode(os.readlink(current))
        else:
            if mode not in ('100644', '100755') or not current.is_file() or current.is_symlink():
                raise RuntimeError('nonregular source file: ' + path)
            data = current.read_bytes()
        result[path] = {'mode': mode, 'blob': blob(data), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    return result


def check_full_bytes(root, commit, tree, exclude=()):
    if not __debug__:
        raise RuntimeError('reviewed source boundary assertions require non-optimized Python')
    entries = inventory(root, commit, tree)
    observed = windows_raw_snapshot(root, entries) if os.name == 'nt' else snapshot(root, entries)
    for path, expected in entries.items():
        if observed[path]['mode'] != expected['mode'] or (path not in exclude and observed[path]['blob'] != expected['blob']):
            raise RuntimeError('worktree bytes/mode differ from committed blob: ' + path)
    try:
        boundary(root, commit, tree, entries)
    except AssertionError as error:
        raise RuntimeError('source changes: staged/index/full boundary: ' + str(error)) from error
    return {'tracked_files': len(entries), 'raw_bytes_and_types_checked': True,
            'git_index_modes_exact': True, 'physical_posix_executable_bits_checked': os.name != 'nt',
            'tracked_symlinks_must_be_real': True}
