#!/usr/bin/env python3
"""Seal only this local inert preparation; never execute/import the exporter."""
import ast
import hashlib
import json
import os
from pathlib import Path

D = Path(__file__).resolve().parent
B = D.parent


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def write_raw(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return pin(raw)


def write_json(name, value):
    return write_raw(D / name, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def main():
    template_raw = (D / 'export-r31-closed-template.py').read_bytes()
    expected_template = '0a0b60ec209527b03cf54a7d7566409c9714aca13c4423fc8ef9dd0cc88be910'
    assert pin(template_raw)['sha256'] == expected_template
    constants = {}
    for node in ast.parse(template_raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    assert constants['FROZEN'] is False
    future = ('TERMINAL_PIN', 'CLOSED_ORIGINAL_PINS', 'CONTROLLER_ORIGINAL_PINS')
    assert all(constants[name] is None for name in future)
    contract = json.loads((D / 'references/R31-PRODUCER-CONTRACT.json').read_bytes())
    mechanical = json.loads((D / 'MECHANICAL-READBACK.json').read_bytes())
    self_review = json.loads((D / 'STATIC-SELF-REVIEW.json').read_bytes())
    assert self_review['template'] == pin(template_raw)

    native_path = B / 'r31-export-native-independent-review/INDEPENDENT-REVIEW.json'
    native_raw = native_path.read_bytes()
    assert pin(native_raw)['sha256'] == '5107927d44919bd8ed3fdbd2419ec6a728c33bacad2cbffbc63093befab50de9'
    native = json.loads(native_raw)
    assert native['conclusion'] == 'STATIC_CLEAR_REMAINS_INERT'
    assert {key: native['exporter'][key] for key in pin(template_raw)} == pin(template_raw)
    write_raw(D / 'references/NATIVE-INDEPENDENT-REVIEW.json', native_raw)

    input_contract = {
        'schema': 'hepta.r31-export-input-contract.v1',
        'template': {'path': 'export-r31-closed-template.py', **pin(template_raw)},
        'producer_contract': {'path': 'references/R31-PRODUCER-CONTRACT.json',
                              **pin((D / 'references/R31-PRODUCER-CONTRACT.json').read_bytes())},
        'producer': mechanical['producer'],
        'source': {'source_commit': constants['COMMIT'], 'source_tree': constants['TREE'],
                   'native_HEAD': constants['HEAD'], 'changed_count': 197,
                   'manifest_name': constants['SOURCE_NAME'], 'manifest_pin': constants['SOURCE_PIN'],
                   'dual_locks': constants['LOCKS'], 'diagnostic_only': True, 'behavior_repair_claimed': False},
        'actual_original_gate': {'job_id': contract['job_id'], 'key': contract['key'],
                                'launch_executable': contract['launch_executable'],
                                'launch_args': contract['launch_args'], 'launch_env_keys': [],
                                'original_workspace_command': contract['workspace_command'],
                                'original_metadata_command': contract['metadata_command'],
                                'result_at_preparation': None},
        'future_binding_names': {name: None for name in future},
        'binding_rules': {
            'TERMINAL_PIN': 'Actual natural terminal original for this job; bytes, SHA256 and optional Git blob.',
            'CLOSED_ORIGINAL_PINS': 'Exact actually existing closed original basename to byte/hash pin map; no synthesized successful set on failure.',
            'CONTROLLER_ORIGINAL_PINS': 'Exact original flat r31-controller-closed-* launch, terminal and process-read records; byte ranges and totals are independently checked.',
            'FROZEN': 'Remains false until the actual three maps and final one-line activation receive root/native review and explicit authorization.'},
        'successful_originals': contract['successful_originals'],
        'successful_original_count_excluding_terminal': 18,
        'additional_actual_failure_names': contract['additional_actual_failure_names'],
        'terminal_name': contract['terminal_name'],
        'controller_rules': {'prefix': constants['CONTROLLER_PREFIX'],
                             'chunk_length': 'next_offset - offset', 'stream_size': 'size >= next_offset',
                             'text_equals_hex': True, 'nonempty_ranges_contiguous': True,
                             'terminal_seen_and_stored_equals_reconstructed_length': True,
                             'eof_is_not_terminal_status': True},
        'prerequisites': [
            {'name': 'r30_closed_gate_readback', 'source': 'source53', 'original_count': 19,
             'natural_outer_exit': 0, 'phases': ['strict', 'tests'],
             'exact_app_server_test_ids': 1345, 'role': 'Same-source original project gate; not the current workspace result.'},
            {'name': 'source52_r28_historical_project_gate', 'source': 'source52', 'original_count': 26,
             'natural_outer_exit': 0, 'phases': ['python-runner', 'strict', 'tests'],
             'python_count': 32, 'four_package_test_id_count': 1564,
             'role': 'Historical source52 evidence, never substituted for source53 R30 or R31.'},
            {'name': 'original_r29_workspace_baseline', 'source': 'source52', 'original_count': 4,
             'test_id_count': 20228, 'observed_counts': {'PASS': 20227, 'FAIL': 1, 'TIMEOUT': 0, 'reported_skip': 130},
             'original_gate_exit': 100, 'role': 'Failed historical full-workspace identity baseline, used after execution only.'}],
        'source_and_ancestry_preservation': [
            'All actual 197 source files are raw SHA256/Git blob/Git mode checked before and after export.',
            'Parent source52 195 unchanged rows and the two source53 Bedrock leaves are bound independently.',
            'Seven-member source53 apply input, source50 lock origin, source51/source52 ancestors, and original R24/R26/R29 failures remain separate.',
            'Source drift stops export; no reset, apply, test retry or formatting is permitted.'],
        'result_semantics': {
            'complete_success_requires': ['actual complete 18 originals', 'natural durable outer 0',
                                         'raw/effective/resource/source guards consistent',
                                         'complete original nextest log', 'exact 20228 baseline IDs all PASS'],
            'missing_or_partial_nextest_counts': None,
            'readback_errors': 'Retained separately without overwriting original nonzero exits or inventing missing originals.',
            'source53_diagnostic_only': True, 'behavior_repair_claimed': False,
            'archive_success_is_engineering_pass': False,
            'aggregate_counts_with_prior_gates': False},
        'proposed_output': {'archive': contract['archive_path_proposed'],
                            'derived_directory': contract['derived_path_proposed'],
                            'result': '/home/alex/work/hepta-cell-unified-20261106-a/evidence/checkpoint-r31-export.json',
                            'create_only': True, 'gzip_mtime': 0, 'member_raw_mode_and_whole_hash_readback': True},
        'forbidden_by_scope': ['native gate execution', 'cargo metadata execution', 'Rust execution',
                               'source apply/reset', 'fix/fmt', 'tool installation', 'active-log reads',
                               'mutating old frozen reports or historical outcome fields'],
        'archive_execution_authorized': False,
    }
    write_json('INPUT-CONTRACT.json', input_contract)
    # The literal stdout below is the actual result returned by the local
    # exec tool for verify_static.py. No exporter function was called.
    verification_stdout = json.dumps({
        'template': pin(template_raw),
        'static_readback': pin((D / 'STATIC-SELF-REVIEW.json').read_bytes()),
        'historical_command_rows': 5}) + '\n'
    write_json('LOCAL-STATIC-EXECUTION.json', {
        'schema': 'hepta.r31-export-local-static-execution.v1',
        'command': ['python3', 'source53-r31-export-preparation/verify_static.py'],
        'cwd': str(B), 'tool_chunk_id': 'c01886', 'exit_code': 0, 'wall_time_seconds': 0.126395591,
        'stdout': verification_stdout, 'stderr': '',
        'script': {'path': 'verify_static.py', **pin((D / 'verify_static.py').read_bytes())},
        'AST_and_closed_original_data_only': True, 'candidate_imported_or_executed': False,
        'native_Rust_metadata_formatter_or_git_command_executed': False})
    preparation = {
        'schema': 'hepta.r31-export-preparation.v1',
        'state': 'FROZEN_PREPARATION_STATIC_CLEAR_EXECUTION_DISABLED',
        'template': {'path': 'export-r31-closed-template.py', **pin(template_raw)},
        'FROZEN': False, 'future_closure_maps': {name: None for name in future},
        'actual_r31_terminal_result': None, 'actual_archive': None,
        'source_commit': contract['source_commit'], 'source_tree': contract['source_tree'], 'source_count': 197,
        'producer_contract': 'INPUT-CONTRACT.json', 'mechanical_readback': 'MECHANICAL-READBACK.json',
        'local_self_review': {'path': 'STATIC-SELF-REVIEW.json', **pin((D / 'STATIC-SELF-REVIEW.json').read_bytes())},
        'independent_review': {'original_path': str(native_path.relative_to(B)),
                               'exact_copy': 'references/NATIVE-INDEPENDENT-REVIEW.json', **pin(native_raw)},
        'initial_preparation_preserved': 'initial-build/',
        'single_comparison_correction': 'INITIAL-BUILD-CORRECTION.json',
        'actual_execution': {'exporter': False, 'runner': False, 'Rust': False, 'metadata': False,
                             'fix': False, 'fmt': False, 'upload': False},
        'active_r31_test_log_read': False,
        'next_steps': ['Wait for the actual natural R31 terminal and closed files.',
                      'Native binds only the three actual closure maps in a separate derived file.',
                      'Root reviews exact binding and one-line activation before any export launch.'],
        'claims': {'archive_success_is_gate_pass': False, 'science_qualification': False,
                   'diagnostic_only': True, 'behavior_repair_claimed': False}}
    write_json('PREPARATION.json', preparation)
    files = []
    for path in sorted(D.rglob('*')):
        if path.is_file():
            assert not path.is_symlink()
            raw = path.read_bytes()
            files.append({'path': str(path.relative_to(D)), **pin(raw)})
    handoff = {'schema': 'hepta.r31-export-preparation-handoff.v1',
        'result': 'STATIC_CLEAR_INERT', 'root': str(D),
        'listed_file_count': len(files), 'listed_bytes': sum(row['bytes'] for row in files),
        'files': files, 'template': preparation['template'],
        'FROZEN': False, 'future_closure_maps': {name: None for name in future},
        'actual_r31_terminal_result': None, 'exporter_executed': False,
        'scope': 'Local preparation and static review only; source53 diagnostic classification unchanged.',
        'binary_paths': []}
    handoff_pin = write_json('HANDOFF-MANIFEST.json', handoff)
    for row in files:
        assert pin((D / row['path']).read_bytes()) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    print(json.dumps({'handoff': handoff_pin, 'file_count_including_handoff': len(files) + 1,
                      'bytes_including_handoff': sum(row['bytes'] for row in files) + handoff_pin['bytes'],
                      'template': pin(template_raw), 'result': 'STATIC_CLEAR_INERT'}))


if __name__ == '__main__':
    main()
