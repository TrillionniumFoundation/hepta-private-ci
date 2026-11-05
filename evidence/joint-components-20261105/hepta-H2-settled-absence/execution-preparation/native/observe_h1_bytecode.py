"""Retain a scoped post-run observation; never load or delete the bytecode."""
from pathlib import Path
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time

root = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf')
source = root / 'source'
destination = root / 'evidence/joint-h1-native-attempt-1/post-terminal-bytecode-observation'
destination.mkdir(mode=0o700)
env = dict(os.environ, GIT_NO_LAZY_FETCH='1', PYTHONDONTWRITEBYTECODE='1')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, env=env, timeout=20).decode().strip()
assert head == '9f785cb201ba12ab0ae0f0d341c0f7912cc65efc'
records = []
for path in sorted((source / 'scripts/__pycache__').glob('hepta_ci_candidate*.pyc')):
    before = path.stat(follow_symlinks=False)
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    sha = hashlib.sha256(raw).hexdigest()
    retained = destination / (sha + '.pyc')
    retained.write_bytes(raw)
    corresponding_source = Path(importlib.util.source_from_cache(str(path)))
    records.append({'path':str(path), 'sha256':sha, 'bytes':len(raw),
                    'mtime_ns':before.st_mtime_ns, 'ctime_ns':before.st_ctime_ns,
                    'retained_copy':str(retained), 'bytes_base64':base64.b64encode(raw).decode(),
                    'corresponding_source':str(corresponding_source),
                    'corresponding_source_sha256':hashlib.sha256(corresponding_source.read_bytes()).hexdigest()})
result = {'scope':'post-H1 observation only of scripts/__pycache__/hepta_ci_candidate*.pyc; not a per-import trace, not the complete ignored runtime closure',
          'source_commit':head, 'observed_unix':time.time(), 'records':records,
          'observer_interpreter':sys.executable, 'observer_interpreter_version':sys.version,
          'observer_interpreter_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
          'h1_environment_record':'../native-environment.json', 'original_source_and_bytecode_unmodified':True}
(destination / 'observation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'records':len(records), 'path':str(destination / 'observation.json')}), flush=True)
