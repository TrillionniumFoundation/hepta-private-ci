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

EXPECTED = {'run_h4_native_pipeline.py': '5bd64b700c9974582e0b70c3a97117982b8d6f470f8d308b99accc42bba1714a', 'test_elf_capture.py': '2cb676bff1657866dc39b3e35ff45644d1ce75981ec9ed3f8798509287ab5ebe', 'test_executed_binary_capture.py': 'debcc32b403d169a07cbdb4ae04319c9a12e674f0c3bfa412c809bb6ea78a838', 'nextest_fd_runner.py': '9679cc6e11762c29b4c0ee92dd7715d3fce0555a6f8e0e10ed9d0b007951381a', 'test_nextest_fd_runner.py': '29a77665a8e255dbd29286709ccab06a4e9f81bf76f6f89ed489613a68ede61a', 'test_fd_gate_targets.py': '642ec3f16702f1f9c9bedd205e8a268841a07c19884d711041504b59c76cbb06', 'fd_gate_evidence.py': '0fb050f795f982ad718938eba25c06d5e6831ce5c213a57dd166405039ba056d', 'live_fd_correspondence.py': 'fc8fc5cfc7c084a3a5884449cd683f94fbd6ee377455ba5a0df6033a6ceed0a4', 'test_live_fd_correspondence.py': '0e308e80ea2b802f2711c9939b90e1d6989cd062f6170eddd4069db487e251b4', 'h4-native-plan.json': 'c596e0f5a74ee878a20b68d545cefa9aff1d38773f388eb1dae91080acf9b51e', 'h4-selected-tests-guard.py': 'e273e7f5c17704bfb699e90a5d15c8389d349c6c17e271ee26c031e6b3a65d48', 'h4-extra-controls.json': '08d884ff93090767084059d1b40802fd3269c2b939b0f5534472c3ea663d908c'}
assert len(sys.argv) == 4
commit, tree, name = sys.argv[1:]
assert re.fullmatch(r'[0-9a-f]{40}', commit)
assert re.fullmatch(r'[0-9a-f]{40}', tree)
assert re.fullmatch(r'joint-h4-native-attempt-[0-9]+', name)
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
os.execv(sys.executable, [sys.executable, '-B', str(destination / 'run_h4_native_pipeline.py'),
                         '--commit', commit, '--tree', tree, '--evidence-name', name])
