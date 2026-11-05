"""Install the reviewed external collector bundle and exec it exactly once.

This launcher creates only its own external tools directory. The coordinator
owns full source validation and every original gate. Launch with the original
durable 5400-second cap after the final source and CPU window are authorized.
"""
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import sys

EXPECTED = {'run_h2_native_pipeline.py': '700c8a3df4997f0d3348bbab6df4ad8b23865cb935e231a51f5171cd34e6a350', 'test_elf_capture.py': '64489779d88a399040e20f939fe878f8d20fa86a60b435a2d7896186dc64d87a', 'test_executed_binary_capture.py': '6045805d6ea6c988a071839ee24806f7b3bb9593fc8e755df9d7d0d097041969', 'nextest_fd_runner.py': '903c622365c9cf863f1ae4b5eca2d4a0501c9f86862538c48f94f126a82ba62b', 'test_nextest_fd_runner.py': '29a77665a8e255dbd29286709ccab06a4e9f81bf76f6f89ed489613a68ede61a', 'fd_gate_evidence.py': 'b582bbc5759f5dbadff6416f7aa804f67e6136d18553c7b6486bd8a7786435c6', 'h2-native-plan.json': '5f79297d78b0b1b2aa13022c4eed26bee8cff788a2eafd4086e9f3261c7e0288', 'h2-selected-tests-guard.py': 'db0d00120c1c1efda2bf2f2830ae4011e419cc03438b605e3f5b21ca51df8d7f', 'h2-extra-controls.json': '08d884ff93090767084059d1b40802fd3269c2b939b0f5534472c3ea663d908c'}
assert len(sys.argv) == 4
commit, tree, name = sys.argv[1:]
assert re.fullmatch(r'[0-9a-f]{40}', commit)
assert re.fullmatch(r'[0-9a-f]{40}', tree)
assert re.fullmatch(r'joint-h2-native-attempt-[0-9]+', name)
payload = json.load(sys.stdin)
assert set(payload) == set(EXPECTED)
verified = {}
for filename, expected in EXPECTED.items():
    raw = base64.b64decode(payload[filename], validate=True)
    assert hashlib.sha256(raw).hexdigest() == expected
    verified[filename] = raw
root = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf')
destination = root / 'tools' / name
destination.mkdir(mode=0o700)
for filename, raw in verified.items():
    with (destination / filename).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert hashlib.sha256((destination / filename).read_bytes()).hexdigest() == EXPECTED[filename]
directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
print(json.dumps({'phase': 'immutable-reviewed-bundle-installed', 'source': commit,
                  'tree': tree, 'destination': str(destination), 'files': EXPECTED}), flush=True)
os.execv(sys.executable, [sys.executable, '-B', str(destination / 'run_h2_native_pipeline.py'),
                         '--commit', commit, '--tree', tree, '--evidence-name', name])
