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
OUT = Path('/workspace/scratch/ff41dfc0f7bf/local-validation/post-a-integrated-7a8cc3c8')
HEAD = '7a8cc3c8c473b623a12667f49750c2ee5a46ea14'
TREE = 'c39ccb2167f7f8c1f3b2899ebaa073fd61a3bac1'
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
receipt = {'schema': 'hepta.post-a-installation.source-qa.v1', 'command': command,
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
        selected = set(['cell_original_physical_witness_codec', 'ledger_canonical_read_data_decode', 'ledger_canonical_read_data_encode', 'ledger_snapshot_dataset_records', 'original_task_data_validate', 'q24_dataset_pure_freeze_execution_key', 'q24_dataset_pure_original_projection', 'q24_dataset_pure_preparation_identity', 'q24_historical_dataset_original_clock', 'q24_historical_freeze_key_admission', 'q24_historical_freeze_signing_config', 'q24_original_freeze_phase_clock', 'q24_original_historical_dataset_batch', 'q24_original_historical_dataset_ledger', 'q24_original_historical_dataset_read', 'q24_original_historical_preparation', 'q24_preparation_into_live_writer', 'q24_preparation_live_writer', 'q24_prepared_historical_dataset', 'root_generation_publication_original_registration', 'root_generation_publication_original_serve', 'root_historical_current_trust_capsule', 'root_historical_current_trust_clock', 'root_historical_current_trust_read', 'root_historical_current_trust_receipt', 'root_historical_fixed_client_exchange', 'root_historical_fixed_operation', 'root_historical_ledger_snapshot_data', 'root_historical_recipient_trust_activation', 'root_historical_recipient_trust_files', 'root_historical_recipient_trust_payload', 'root_historical_recipient_trust_reply', 'root_historical_task_publication_data', 'root_historical_task_read_cold_source', 'root_historical_task_read_profile', 'root_historical_task_read_serve', 'root_initial_learning_trust_activation', 'root_initial_run_start_fixed_files', 'root_late_generation_publication_core', 'root_late_generation_publication_listener_until', 'root_late_generation_publication_until', 'root_late_learning_checkpoint_core', 'root_late_learning_checkpoint_until', 'root_late_learning_listener_until', 'root_late_q24_model_factory_core', 'root_late_q24_model_factory_until', 'root_late_q24_model_listener_until', 'root_learning_derived_checkpoint', 'root_learning_live_profile_action', 'root_learning_original_purpose_send', 'root_learning_original_scope_capture', 'root_learning_same_service_serve', 'root_learning_scoped_profile_constructor', 'root_original_complete_task_context', 'root_original_complete_task_digest', 'root_original_complete_task_ledger_data', 'root_original_complete_task_observation', 'root_original_complete_task_target', 'root_original_learning_checkpoint_exchange', 'root_original_learning_time', 'root_original_owner_absolute_end', 'root_original_peer_absolute_end', 'root_post_a_baseline_files_open', 'root_post_a_baseline_files_read', 'root_post_a_bound_learning', 'root_post_a_derive_profile', 'root_post_a_enable', 'root_post_a_fixed_plan', 'root_post_a_freeze_completion', 'root_post_a_freeze_files_open', 'root_post_a_install_provider', 'root_post_a_installation_prepare', 'root_post_a_installation_run', 'root_post_a_installation_serve', 'root_post_a_installation_submit', 'root_post_a_learning_install_original', 'root_post_a_learning_scope_ack', 'root_post_a_learning_strict_reply', 'root_post_a_original_file_identity', 'root_post_a_original_file_open', 'root_post_a_original_file_read', 'root_post_a_prepare_installation', 'root_q24_factory_capture_original', 'root_q24_factory_open_original', 'root_q24_factory_purpose_send', 'root_q24_factory_reserve_same_service', 'root_q24_factory_serve_original', 'root_registered_learning_checkpoint_writer'])
        assert len(selected) == 88
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
receipt = {'schema': 'hepta.post-a-installation.focused-callers.v1', 'start_unix': start,
           'end_unix': time.time(), 'before': before, 'after': after,
           'source_unchanged': before == after, 'full_caller_checker_run': False,
           'results': reports, 'errors': errors, **counts}
receipt['exit_code'] = 0 if not errors and before == after else 1
emit('focused-callers', receipt, log)
raise SystemExit(receipt['exit_code'])
