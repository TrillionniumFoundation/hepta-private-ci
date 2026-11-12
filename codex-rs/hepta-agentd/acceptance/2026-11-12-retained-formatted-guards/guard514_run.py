import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import unittest

root = Path('/workspace/scratch/ce434f960ee9/retained-guard-514')
phase = Path('/workspace/scratch/ce434f960ee9/version-evidence') / sys.argv[1]
phase.mkdir(exist_ok=False)
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
assert head == '514fe5f53cfdc254477667f8862d652ea756c807'
start = time.monotonic()
paths = [
    'qa/b4-no-bypass/test_artifact_publication_readback_source_closure.py',
    'qa/b4-no-bypass/test_retained_publication_source_closure.py',
]
with (phase / 'raw.log').open('w') as raw, contextlib.redirect_stdout(raw), contextlib.redirect_stderr(raw):
    spec = importlib.util.spec_from_file_location('guard514_verify', root / 'scripts/verify_hepta_callers.py')
    proof = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = proof
    spec.loader.exec_module(proof)
    manifest = tomllib.loads((root / 'CALLERS.toml').read_text())
    rows = [r for r in manifest['protected_file'] if Path(r['path']).name in (
        'owner_host_readback.rs', 'owner_service_readback.rs'
    ) or Path(r['path']).name.startswith(('circuit_learning_retained_', 'circuit_retained_version'))]
    failures = []
    for row in rows:
        try:
            proof._verify_protected_files(root, {'protected_file': [row]})
            print('PASS owned protected', row['path'])
        except Exception as error:
            failures.append({'path': row['path'], 'error': str(error)})
            print('FAIL owned protected', row['path'], str(error))
    suite = unittest.TestSuite()
    for path in paths:
        spec = importlib.util.spec_from_file_location(Path(path).stem, root / path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    ran = unittest.TextTestRunner(stream=raw, verbosity=2).run(suite)
    result = {
        'protected_rows': len(rows), 'protected_failures': failures,
        'tests': ran.testsRun, 'failures': len(ran.failures), 'errors': len(ran.errors),
        'skips': len(ran.skipped), 'failed_names': [str(test) for test, _ in ran.failures + ran.errors],
    }
    success = not failures and ran.wasSuccessful() and not ran.skipped
data = (phase / 'raw.log').read_bytes()
result.update({
    'source_parent': head, 'scope': 'owned Artifact and retained/Version rows and two source QA modules only',
    'working_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'], cwd=root)).hexdigest(),
    'seconds': time.monotonic() - start, 'exit_code': 0 if success else 1,
    'raw_bytes': len(data), 'raw_sha256': hashlib.sha256(data).hexdigest(),
})
(phase / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
sys.exit(result['exit_code'])
