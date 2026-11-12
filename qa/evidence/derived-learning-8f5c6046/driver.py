import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path('/workspace/scratch/ff41dfc0f7bf/hepta-historical-read-cloud')
OUT = Path('/workspace/scratch/ff41dfc0f7bf/local-validation/derived-learning-8f5c6046')
HEAD = '8f5c6046c65969fc011ae7aad673681e787c4e88'
TREE = 'a9038760ae66cb39d54c39a23b40dd45c2bfc673'
OUT.mkdir(parents=True, exist_ok=True)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args]).decode()


def snapshot():
    paths = git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split('\0')
    selected = sorted(set(p for p in paths if p and (
        p.endswith(('.rs', '.py')) or p in (
            'CALLERS.toml', '.github/blob-size-allowlist.txt',
            '.github/workflows/hepta-daemon-learning-native.yml'))))
    digest = hashlib.sha256()
    for relative in selected:
        data = (ROOT / relative).read_bytes()
        digest.update(relative.encode() + b'\0' + hashlib.sha256(data).digest())
    return {'head': git('rev-parse', 'HEAD').strip(),
            'tree': git('rev-parse', 'HEAD^{tree}').strip(),
            'status': git('status', '--porcelain'), 'source_files': len(selected),
            'sha256': digest.hexdigest()}


def emit(name, receipt, log):
    data = log.read_bytes()
    receipt.update(log_bytes=len(data), log_sha256=hashlib.sha256(data).hexdigest(),
                   native_executed=False)
    (OUT / (name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'name': name, 'receipt': receipt, 'raw_log_path': str(log)}), flush=True)


before = snapshot()
assert before['head'] == HEAD and before['tree'] == TREE and not before['status']
command = ['python3', '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass',
           '-p', '*source_closure.py', '-v']
start = time.time()
log = OUT / 'source-qa.log'
with log.open('wb') as output:
    completed = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
after = snapshot()
raw = log.read_text()
count = re.search(r'Ran (\d+) tests in ', raw)
receipt = {'schema': 'hepta.derived-learning.source-qa.v1', 'command': command,
           'start_unix': start, 'end_unix': time.time(), 'exit_code': completed.returncode,
           'before': before, 'after': after, 'source_unchanged': before == after,
           'tests': int(count.group(1)) if count else None,
           'does_not_inherit_prior_source_or_native_qualification': True}
emit('source-qa', receipt, log)
if completed.returncode or before != after:
    raise SystemExit(1)

start = time.time()
before = snapshot()
log = OUT / 'focused-callers.log'
errors = []
reports = []
counts = {}
with log.open('w') as output:
    try:
        spec = importlib.util.spec_from_file_location('run_start_focused_proof',
                                                     ROOT / 'scripts/verify_hepta_callers.py')
        proof = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = proof
        spec.loader.exec_module(proof)
        manifest = proof._load_manifest(ROOT / 'CALLERS.toml')
        boundaries = proof._boundary_rows(manifest)
        proof._verify_privileged_inventory(manifest, boundaries)
        proof._verify_protected_files(ROOT, manifest)
        counts = {'protected_rows': len(manifest['protected_file']),
                  'inventory_rows': len(boundaries)}
        print(json.dumps(counts), file=output, flush=True)
        ignored = proof._string_tuple(manifest, 'ignored_path_fragments')
        paths = proof._source_files(ROOT, proof._string_tuple(manifest, 'source_roots'))
        sources = {}
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            sources[relative] = proof._strip_cfg_test_items(
                proof._strip_rust_non_code(path.read_text()))
        selected = {row.identifier for row in boundaries if row.identifier.startswith((
            'root_historical_task_read_', 'original_task_data_',
            'cell_q24_historical_dataset_task', 'root_historical_task_publication_',
            'root_original_complete_task_'))}
        selected.update((
            'ordinary_historical_task_read_take', 'root_original_private_sealed_bytes',
            'root_learning_live_profile_action', 'root_original_publication_stream_until',
            'root_initial_run_start_fixed_files'))
        selected.update(('root_learning_derived_checkpoint', 'root_learning_original_store_core',
                         'root_q24_factory_reserve_same_service', 'root_q24_factory_explicit_reserve',
                         'root_q24_factory_open_original', 'root_q24_factory_capture_original',
                         'root_learning_original_store_registration', 'root_learning_original_store_reopen'))
        assert len(selected) == 50, sorted(selected)
        assert selected <= {row.identifier for row in boundaries}
        fields = {}
        for row in boundaries:
            if row.identifier not in selected:
                continue
            try:
                result = proof._verify_boundary(ROOT, row, sources, ignored,
                                                fields_by_receiver_type=fields)
                reports.append(result)
                print(json.dumps({'pass': row.identifier, 'result': result}), file=output, flush=True)
            except Exception as error:
                errors.append({'boundary': row.identifier, 'error': str(error)})
                print(json.dumps(errors[-1]), file=output, flush=True)
        counts.update(selected_rows=len(selected), source_files=len(sources))
    except Exception as error:
        errors.append({'stage_error': str(error)})
        traceback.print_exc(file=output)
after = snapshot()
receipt = {'schema': 'hepta.derived-learning.focused-callers.v1', 'start_unix': start,
           'end_unix': time.time(), 'before': before, 'after': after,
           'source_unchanged': before == after, 'full_caller_checker_run': False,
           'results': reports, 'errors': errors, **counts}
receipt['exit_code'] = 0 if not errors and before == after else 1
emit('focused-callers', receipt, log)
raise SystemExit(receipt['exit_code'])
