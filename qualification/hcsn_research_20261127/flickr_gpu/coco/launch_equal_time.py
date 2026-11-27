"""Run the preregistered one-minute physical/SDPA/SSM controls on ai395."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
source_archive = root / 'coco_timed_sources.json'
expected = 'f422816efc148972f61f0b3f072e9ad3c35f04624fbd8ad1c77a86d39f81392e'
assert hashlib.sha256(source_archive.read_bytes()).hexdigest() == expected
work = root / 'coco_timed'
work.mkdir(exist_ok=True)
lock = (work / 'worker.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
for name, value in json.loads(source_archive.read_text()).items():
    assert name in {'PROTOCOL.md', 'panel.py', 'run.py', 'controls.py'}
    dest = work / name
    if dest.exists():
        assert dest.read_text() == value
    else:
        dest.write_text(value)
repo = root / 'coco1536' / 'repo'
end = time.monotonic() + 20000
while not (root / 'coco_restored' / 'verification.json').exists() or not (root / 'coco1536' / 'summary.json').exists():
    if time.monotonic() > end:
        raise TimeoutError('The canonical cohort and prior single-CPU panel must complete first')
    time.sleep(20)
inputs = root / 'coco_restored' / 'inputs'
environment = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PYTHONUNBUFFERED='1')
command = [sys.executable, str(work/'run.py'), '--repo', str(repo), '--upstream', str(repo/'qualification/hcsn_research_20261127/root'), '--inputs', str(inputs), '--out', str(work/'results')]
record = {'started': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'archive_sha256': expected, 'torch_interpreter': sys.executable, 'source': 'cf5aa0c954e92fbecd3a53494ccefaa37a2bb7d0', 'cpu_single_thread': True, 'flickr_gpu_shared_host': True}
(work/'launch.json').write_text(json.dumps(record, indent=2))
with (work/'worker.log').open('a') as log:
    subprocess.run(command, cwd=work, env=environment, check=True, stdout=log, stderr=subprocess.STDOUT)
assert (work/'results/summary.json').is_file()
