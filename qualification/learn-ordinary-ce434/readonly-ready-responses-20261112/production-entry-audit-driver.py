import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import tomllib

ROOT = Path('/workspace/scratch/ce434f960ee9/learn-readonly-ready-v4')
OUT = ROOT.parent / 'readonly-ready-v4'
STARTED = time.monotonic()
EXPECTED = '57ffff832355d75937045f240fed2c2d48783029'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def emit(item):
    print(json.dumps(item, sort_keys=True), flush=True)


assert git('rev-parse', 'HEAD') == EXPECTED
assert git('status', '--porcelain') == ''
spec = importlib.util.spec_from_file_location('readonly_production_audit', ROOT / 'scripts/verify_hepta_callers.py')
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())
boundaries = {row.identifier: row for row in proof._boundary_rows(manifest)}
paths = git('ls-files', '*.rs').splitlines()
emit({'phase': 'indexing', 'source': EXPECTED, 'tree': git('rev-parse', 'HEAD^{tree}'),
      'tracked_rust_files': len(paths), 'registered_source_roots': manifest['source_roots'],
      'ignored_path_fragments': manifest['ignored_path_fragments']})
source_index = {}
fingerprint = hashlib.sha256()
for path in paths:
    raw = (ROOT / path).read_bytes()
    fingerprint.update(path.encode() + b'\0' + hashlib.sha256(raw).digest())
    source_index[path] = proof._strip_cfg_test_items(proof._strip_rust_non_code(raw.decode()))
identifiers = [
    'learning_original_training_bootstrap_create',
    'learning_original_training_bootstrap_recover',
    'learning_original_candidate_stage_create',
    'learning_original_candidate_stage_recover',
    'learning_original_no_update_stage_create',
    'learning_original_no_update_stage_recover',
    'learning_retained_version_host_create',
    'learning_retained_version_host_recover',
    'learning_original_selector_readonly_host',
    'learning_original_observer_readonly_host',
    'learning_original_training_readonly_first_ready',
    'learning_original_selection_readonly_first_ready',
]
fields = {}
results = []
for identifier in identifiers:
    row = boundaries[identifier]
    try:
        result = proof._verify_boundary(ROOT, row, source_index,
                                        tuple(manifest['ignored_path_fragments']),
                                        fields_by_receiver_type=fields)
        result['definition_path'] = row.definition_path
        result['status'] = 'matched_explicit_caller_set'
    except Exception as error:
        result = {'id': identifier, 'symbol': row.symbol, 'definition_path': row.definition_path,
                  'status': 'mismatch', 'error': str(error)}
    results.append(result)
    emit(result)
result = {
    'source': EXPECTED, 'tree': git('rev-parse', 'HEAD^{tree}'),
    'clean_before_and_after': git('status', '--porcelain') == '',
    'tracked_rust_files': len(paths), 'source_index_digest_sha256': fingerprint.hexdigest(),
    'roots': sorted({Path(path).parts[0] for path in paths}),
    'excluded_product_paths': manifest['ignored_path_fragments'],
    'masking': 'repository _strip_rust_non_code then _strip_cfg_test_items; typed receiver caller verifier',
    'elapsed_seconds': time.monotonic() - STARTED,
    'boundaries': results,
    'scope': '12 selected bootstrap/initial handoff/readonly boundaries; not the full caller proof',
    'ordinary_adoption': 0, 'ordinary_no_update_or_fallback': 0, 'actual_daemon_root_cold_restart': 0,
}
assert git('rev-parse', 'HEAD') == EXPECTED
(OUT / 'production-entry-audit-v1.json').write_text(json.dumps(result, indent=2) + '\n')
emit({'phase': 'complete', 'elapsed_seconds': result['elapsed_seconds'],
      'matched': sum(item['status'] == 'matched_explicit_caller_set' for item in results),
      'clean': result['clean_before_and_after']})
