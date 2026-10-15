"""Pure model-input directory re-snapshot, independent of original producer code."""
import hashlib
import os
import stat
from pathlib import Path

class ChangedDuringAudit(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stable_again(root, initial):
    """Second bounded read of all originally admitted paths; detect late additions."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ChangedDuringAudit('root changed')
    if len(initial) != 196 or len({p for p, d in initial}) != 196:
        raise ChangedDuringAudit('bad initial census')
    found = []
    total = 0
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        parent = Path(base)
        for name in dirs:
            path = parent / name
            if path.is_symlink() or not path.is_dir() or path.relative_to(root).as_posix() not in {'inputs', 'images'}:
                raise ChangedDuringAudit('unregistered directory')
        for name in files:
            path = parent / name
            rel = path.relative_to(root).as_posix()
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ChangedDuringAudit('changed path kind')
            size_limit = 8*1024*1024 if rel.startswith('images/') else 32*1024*1024
            if not 0 < st.st_size <= size_limit:
                raise ChangedDuringAudit('changed file size')
            data = path.read_bytes()
            if len(data) != st.st_size:
                raise ChangedDuringAudit('unstable file size')
            total += len(data)
            if total > 512*1024*1024:
                raise ChangedDuringAudit('total bound')
            found.append((rel, sha(data)))
    if sorted(found) != sorted((p, d) for p, d in initial):
        raise ChangedDuringAudit('model source mutated after initial scan')
    return True
