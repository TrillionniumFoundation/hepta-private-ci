#!/usr/bin/env python3
"""Local closed small records and literal binding only; full-log review remains pending."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
B = HERE.parent
D = B / 'native-validation-results/r31-closed-input'
P = 'native-workspace-r31'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def put(name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with (HERE / name).open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    return pin(data)


def main():
    declared = json.loads((D / 'R31-INPUT-PINS.json').read_bytes())
    available, absent = [], []
    for name, expected in declared.items():
        path = D / 'evidence' / name
        if not path.is_file():
            absent.append(name); continue
        actual = pin(path.read_bytes())
        assert actual['bytes'] == expected['bytes'] and actual['sha256'] == expected['sha256']
        available.append({'path': str(path.relative_to(B)), **actual})
    assert len(available) == 16 and set(absent) == {P + '-tests.log', P + '-test-results.json'}
    remote_only = []
    for suffix in ('tests.log', 'test-results.json'):
        path = D / 'transport' / (suffix + '-file-info-original.json')
        value = json.loads(path.read_bytes())
        assert value['size'] == declared[P + '-' + suffix]['bytes']
        assert value['sha256'] == declared[P + '-' + suffix]['sha256']
        remote_only.append({'original_info_path': str(path.relative_to(B)), **pin(path.read_bytes()),
                            'remote_file_info': value, 'full_bytes_read_independently': False})
    terminal_raw = (D / 'evidence' / (P + '-terminal-process-status.json')).read_bytes()
    terminal_pin = json.loads((D / 'TERMINAL-PIN.json').read_bytes())
    assert pin(terminal_raw) == terminal_pin
    terminal = json.loads(terminal_raw)
    assert terminal['job_id'] == '1a1b275ba33-fc05-7e17' and terminal['exit_code'] == 0 and terminal['state'] == 'succeeded'
    assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
    assert not any(terminal[k] for k in ('timed_out', 'cancelled', 'automatic_retry'))
    assert not any(terminal['log_truncated'].values()) and all(v is None for v in terminal['log_errors'].values())
    def doc(suffix):
        return json.loads((D / 'evidence' / (P + suffix)).read_bytes())
    raw, receipt = doc('-tests-raw-process-result.json'), doc('-tests-receipt.json')
    for key in ('phase', 'source_commit', 'source_tree', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
        assert raw[key] == receipt[key]
    assert raw['command'] == ['just', 'test', '--locked', '--retries', '0']
    assert raw['exit_code'] == receipt['effective_exit_code'] == terminal['exit_code'] == 0
    assert not receipt['issues'] and receipt['source_guards_pass']
    assert abs(receipt['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6
    resources = (D / 'evidence' / (P + '-tests-resources.txt')).read_bytes()
    assert pin(resources)['sha256'] == receipt['resources_sha256']
    assert re.findall(rb'^\s*Exit status: (\d+)\s*$', resources, re.M) == [b'0']
    for suffix in ('-source-pre-verification.json', '-metadata-source-post-verification.json',
                   '-tests-source-pre-verification.json', '-source-post-test-verification.json'):
        value = doc(suffix)
        assert value['pass'] and value['changed_file_count'] == 197
        assert value['source_commit'] == 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
        assert value['actual_tree'] == value['expected_tree'] == '440d4a8e09af4009e4d9ea067388826308da8803'
        assert value['native_head'] == 'bef6fa7645df9df12b69fda499e97eed25de6c75'
        assert not value['file_mismatches'] and not value['unstaged_paths'] and not value['untracked_paths']
        assert value['cargo_lock_sha256'] == '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
        assert value['bazel_lock_sha256'] == 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'
    controller_pins = json.loads((D / 'CONTROLLER-PINS.json').read_bytes())
    controls = {}
    for name, expected in controller_pins.items():
        local = D / 'controller' / name.removeprefix('r31-controller-closed-')
        data = local.read_bytes(); actual = pin(data)
        assert all(actual[key] == val for key, val in expected.items())
        controls[local.name] = json.loads(data)
    assert (D / 'controller/terminal-process-status.json').read_bytes() == terminal_raw
    streams = {}
    for stream in ('stdout', 'stderr'):
        chunks = []
        for name, value in controls.items():
            if not name.startswith('read-'):
                continue
            entry = value[stream]; data = bytes.fromhex(entry['bytes_hex'])
            assert len(data) == entry['next_offset'] - entry['offset'] and entry['size'] >= entry['next_offset']
            assert data == entry['text'].encode()
            chunks.append((entry['offset'], data))
        output = b''
        for offset, data in sorted(chunks, key=lambda row: row[0]):
            if data:
                assert offset == len(output); output += data
            else:
                assert offset <= len(output)
        assert output == (D / 'controller' / ('original-' + stream + '.log')).read_bytes()
        assert len(output) == terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored']
        streams[stream] = pin(output)
    events = [json.loads(line) for line in (D / 'controller/original-stdout.log').read_bytes().splitlines()]
    assert len(events) == 3 and events[0]['command'] == raw['command']
    assert events[1] == {**raw, 'event': 'workspace-raw-process-return'} and events[2] == receipt
    small = {'schema': 'hepta.source53-r31-independent-small-closure.v1',
             'scope': 'CLOSED_SMALL_ORIGINALS_AND_CONTROLLER_ONLY_FULL_LOG_PENDING',
             'available_producer_original_count': 16, 'available_originals': available,
             'terminal': terminal_pin, 'raw_exit': raw['exit_code'], 'effective_exit': receipt['effective_exit_code'],
             'outer_exit': terminal['exit_code'], 'wall_seconds': receipt['elapsed_seconds'],
             'native_recorded_source_guards_197_HEAD_dual_locks_pass': True,
             'controller_streams': streams, 'controller_raw_and_receipt_announcements_match': True,
             'remote_only_big_originals': remote_only,
             'independently_recomputed_test_counts': None, 'independently_recomputed_test_id_set': None,
             'native_review_not_used_as_full_log_substitute': True, 'full_197_source_bytes_review_pending': True,
             'no_runner_import_or_native_Rust_metadata_formatter_execution': True}
    small_pin = put('CLOSED-SMALL-READBACK.json', small)

    template_path = B / 'source53-r31-export-preparation/export-r31-closed-template.py'
    binding_dir = B / 'source53-r31-export-binding'
    bound_path = binding_dir / 'export-r31-closed-bound.py'
    final_path = binding_dir / 'export-r31-closed.py'
    if not final_path.exists():
        matches = [p for p in binding_dir.glob('*.py') if p != bound_path]
        assert len(matches) == 1
        final_path = matches[0]
    template, bound, final = [p.read_text() for p in (template_path, bound_path, final_path)]
    assert pin(template.encode())['sha256'] == '0a0b60ec209527b03cf54a7d7566409c9714aca13c4423fc8ef9dd0cc88be910'
    assert pin(bound.encode())['sha256'] == 'd3760bd68c2c0909b6dacfaeba071188a2a145e45b0ef08920a603b4d694fc07'
    assert pin(final.encode())['sha256'] == '1ceba4c592750c2254bc535e7d6aaa0240d8455b0a214873aad11f0ecf51a96c'
    def assignments(text):
        return {node.targets[0].id: node for node in ast.parse(text).body if isinstance(node, ast.Assign)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    nodes = assignments(bound)
    assert ast.literal_eval(nodes['FROZEN'].value) is False
    expected = {'TERMINAL_PIN': terminal_pin, 'CLOSED_ORIGINAL_PINS': declared, 'CONTROLLER_ORIGINAL_PINS': controller_pins}
    lines = bound.splitlines(keepends=True)
    for name, node in sorted(((name, nodes[name]) for name in expected), key=lambda item: item[1].lineno, reverse=True):
        assert ast.literal_eval(node.value) == expected[name]
        lines[node.lineno - 1:node.end_lineno] = [name + ' = None\n']
    assert ''.join(lines) == template
    assert bound.replace('FROZEN = False\n', 'FROZEN = True\n', 1) == final
    proof = {'schema': 'hepta.r31-export-independent-literal-binding.v1',
             'template': pin(template.encode()), 'bound': pin(bound.encode()), 'final': pin(final.encode()),
             'three_actual_literal_maps_exact': True, 'inverse_substitution_restores_entire_template': True,
             'only_final_activation_line_differs': True, 'AST_parse_only': True,
             'closed_small_readback': small_pin,
             'big_log_and_rows_pins_are_file_info_only_until_whole_archive_readback': True,
             'exporter_executed_or_imported_by_this_review': False, 'execution_authorized_by_this_review': False}
    binding_pin = put('EXPORTER-BINDING-READBACK.json', proof)
    print(json.dumps({'small': small_pin, 'binding': binding_pin, 'full_log_result': None}))


if __name__ == '__main__':
    main()
