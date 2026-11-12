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

root = Path('/workspace/scratch/ce434f960ee9/retained-version-review')
evidence = Path('/workspace/scratch/ce434f960ee9/version-evidence')
mode = sys.argv[1]
phase = evidence / sys.argv[2]
phase.mkdir(exist_ok=False)
specification = json.loads((evidence / 'guard-patch-result.json').read_text())
started = time.time()
with (phase / 'raw.log').open('w') as raw, contextlib.redirect_stdout(raw), contextlib.redirect_stderr(raw):
    if mode == 'scoped':
        spec = importlib.util.spec_from_file_location('version_review', root / 'scripts/verify_hepta_callers.py')
        proof = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = proof
        spec.loader.exec_module(proof)
        manifest = tomllib.loads((root / 'CALLERS.toml').read_text())
        previous = tomllib.loads(subprocess.check_output(['git', 'show', 'HEAD:CALLERS.toml'], cwd=root).decode())
        old_rows = {row['path']: row for row in previous['protected_file']}
        rows = [row for row in manifest['protected_file'] if old_rows.get(row['path']) != row]
        identifiers = specification['updated_boundary_ids'] + specification['new_boundary_ids']
        boundaries = {row.identifier: row for row in proof._boundary_rows(manifest)}
        paths = {path for identifier in identifiers for path in (boundaries[identifier].definition_path, *boundaries[identifier].product_callers)}
        sources = {path: proof._strip_cfg_test_items(proof._strip_rust_non_code((root / path).read_text())) for path in paths}
        failures = []
        for row in rows:
            try:
                proof._verify_protected_files(root, {'protected_file': [row]})
                print('PASS protected', row['path'])
            except Exception as error:
                failures.append('protected ' + row['path'])
                print('FAIL protected', row['path'], str(error))
        for identifier in identifiers:
            try:
                proof._verify_boundary(root, boundaries[identifier], sources, ())
                print('PASS boundary', identifier)
            except Exception as error:
                failures.append('boundary ' + identifier)
                print('FAIL boundary', identifier, str(error))
        result = {'protected': len(rows), 'boundaries': len(identifiers), 'failures': failures}
        success = not failures
    else:
        suite = unittest.TestSuite()
        for path in specification['modified_qa']:
            spec = importlib.util.spec_from_file_location(Path(path).stem, root / path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
        ran = unittest.TextTestRunner(stream=raw, verbosity=2).run(suite)
        result = {'tests': ran.testsRun, 'failures': len(ran.failures), 'errors': len(ran.errors), 'skips': len(ran.skipped), 'failed_names': [str(test) for test, _ in ran.failures + ran.errors]}
        success = ran.wasSuccessful() and not ran.skipped
data = (phase / 'raw.log').read_bytes()
result.update({'mode': mode, 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip(), 'working_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'], cwd=root)).hexdigest(), 'seconds': time.time() - started, 'exit_code': 0 if success else 1, 'raw_bytes': len(data), 'raw_sha256': hashlib.sha256(data).hexdigest()})
(phase / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
sys.exit(result['exit_code'])
