"""Isolated smoke probes of the NDU v2 guard rules; not a repo-source CI run."""
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_INPUT_BYTES = 16 * 1024 * 1024


def bound_manifest_read(path):
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NONBLOCK', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError('cohort manifest must be a regular file')
        if metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError('cohort manifest byte limit exceeded')
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('cohort manifest byte limit exceeded')
    return raw


def check_join_keys(*splits):
    seen = set()
    for task_id in splits:
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise ValueError('missing or noncanonical task_id')
        if task_id in seen:
            raise ValueError('duplicate task_id across source splits')
        seen.add(task_id)


def test_guards():
    check_join_keys('train:001', 'dev:001', 'test:001')
    for args in [('x','x'), ('train:001','dev:001','train:001')]:
        try: check_join_keys(*args)
        except ValueError as e: assert 'duplicate' in str(e)
        else: raise AssertionError('duplicate accepted')
    for bad in ('', ' leading', 'x/y', 'a\nb', 'z'*129):
        try: check_join_keys('a',bad)
        except ValueError as e: assert 'noncanonical' in str(e)
        else: raise AssertionError('bad ID accepted')
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        regular = root/'valid.json'; regular.write_text('{"safe":true}')
        assert bound_manifest_read(regular)==b'{"safe":true}'
        oversized=root/'oversized.json'
        with oversized.open('wb') as f: f.truncate(MAX_INPUT_BYTES + 1)
        try: bound_manifest_read(oversized)
        except ValueError as e: assert 'limit' in str(e)
        else: raise AssertionError('oversized accepted')
        if hasattr(os,'mkfifo') and hasattr(os,'O_NONBLOCK'):
            fifo=root/'fifo'; os.mkfifo(fifo)
            try: bound_manifest_read(fifo)
            except ValueError as e: assert 'regular' in str(e)
            else: raise AssertionError('FIFO accepted')
        if hasattr(os,'O_NOFOLLOW'):
            symlink=root/'alias'; symlink.symlink_to(regular)
            try: bound_manifest_read(symlink)
            except OSError: pass
            else: raise AssertionError('symlink accepted')
    print('Isolated NDU v2 guard smoke: PASS (6 classes; not exact repo unit tests)')

if __name__=='__main__': test_guards()
