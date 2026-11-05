"""Deploy and test only the external H2 fd-exec runner; no repository mutations."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf')
DEST = ROOT / 'h2-runner-preflight-attempt1'
EXPECTED = {
    'nextest_fd_runner.py': '903c622365c9cf863f1ae4b5eca2d4a0501c9f86862538c48f94f126a82ba62b',
    'test_nextest_fd_runner.py': '29a77665a8e255dbd29286709ccab06a4e9f81bf76f6f89ed489613a68ede61a',
}


def main():
    package = json.load(sys.stdin)
    assert set(package['files']) == set(EXPECTED)
    assert package['sha256'] == EXPECTED
    DEST.mkdir(mode=0o700)
    for name, content in package['files'].items():
        raw = content.encode()
        assert hashlib.sha256(raw).hexdigest() == EXPECTED[name]
        (DEST / name).write_bytes(raw)
    start = time.time()
    command = [sys.executable, str(DEST / 'test_nextest_fd_runner.py')]
    with (DEST / 'controls.log').open('xb') as log:
        proc = subprocess.run(command, cwd=DEST,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                              stdout=log, stderr=subprocess.STDOUT, timeout=20)
    result = {'scope': 'three synthetic utility controls only; no Rust product credit',
              'command': command, 'timeout_seconds': 20,
              'started_unix': start, 'finished_unix': time.time(),
              'exit_code': proc.returncode, 'source_sha256': EXPECTED,
              'log_sha256': hashlib.sha256((DEST / 'controls.log').read_bytes()).hexdigest(),
              'python': sys.version, 'python_executable': sys.executable,
              'python_sha256': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
              'pid': os.getpid(), 'proc_self': os.readlink('/proc/self')}
    (DEST / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    if proc.returncode:
        raise SystemExit(proc.returncode)


if __name__ == '__main__':
    main()
