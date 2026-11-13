"""Verify the complete native request without staging or executing it."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-source-repair-root-inputs-v1')
LAUNCH = Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')
CONTROL = Path('/tmp/hepta-36fa-source-repair-finalfmt-246d-v1')
PROPOSAL = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def literal_assignment(raw, name):
    matches = [node for node in ast.parse(raw).body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    assert len(matches) == 1
    return ast.literal_eval(matches[0].value)


def main():
    typed_raw = (LAUNCH / 'ACTUAL_PROCESS_INPUT.json').read_bytes()
    typed = json.loads(typed_raw)
    bootstrap = (LAUNCH / 'ACTUAL_BOOTSTRAP.py').read_bytes()
    stdin = (LAUNCH / 'ACTUAL_STDIN.json').read_bytes()
    assert pin(typed_raw) == {'bytes': 622334, 'sha256': '533af37aa8b89e19dbd6bf40a1c99bf50c56e3256904b2e74faca4d39e72c666',
                              'git_blob': '60e6b8d8b12523318410b8f60d7626a7fdc1643e'}
    assert set(typed) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
    assert typed['host'] == 'desktop' and typed['cwd'] == '/home/qian-qi'
    assert typed['executable'] == '/usr/bin/python3' and typed['args'] == ['-B', '-c', bootstrap.decode()]
    assert typed['timeout_seconds'] == 2100
    assert typed['idempotency_key'] == 'hepta-utility-36fa-source-repair-246d-final-fmt-v1'
    assert typed['stdin'].encode() == stdin and len(stdin) == 616256 and len(stdin) < 1048576
    pins = literal_assignment(bootstrap, 'PINS')
    template = (CONTROL / 'BOOTSTRAP_TEMPLATE.HOLD.py').read_bytes()
    old_pins = literal_assignment(template, 'PINS')
    assert old_pins['NONRUST_PACKET.json'] is None and old_pins['APPROVED_CONFIG.json'] is None
    expected_text = template.decode().replace("'NONRUST_PACKET.json': None", "'NONRUST_PACKET.json': " + repr(pins['NONRUST_PACKET.json']))
    expected_text = expected_text.replace("'APPROVED_CONFIG.json': None", "'APPROVED_CONFIG.json': " + repr(pins['APPROVED_CONFIG.json']))
    assert expected_text.encode() == bootstrap
    assert old_pins['driver.py'] == pins['driver.py'] and old_pins['SOURCE_GATES_NORMAL.original.json'] == pins['SOURCE_GATES_NORMAL.original.json']
    payload = json.loads(stdin)
    assert set(payload) == {'format', 'files'} and payload['format'] == 'hepta-final-nonrust-format-bootstrap-v1'
    assert set(payload['files']) == set(pins) == {'driver.py', 'SOURCE_GATES_NORMAL.original.json', 'NONRUST_PACKET.json', 'APPROVED_CONFIG.json'}
    expected_files = {'driver.py': CONTROL / 'driver.HOLD.py',
                      'SOURCE_GATES_NORMAL.original.json': Path('/tmp/hepta-36fa-final-source-qualification-launch-v1/SOURCE_STATUS_05.original.json'),
                      'NONRUST_PACKET.json': PROPOSAL / 'NONRUST_APPLY_PACKET.json',
                      'APPROVED_CONFIG.json': ROOT / 'APPROVED_CONFIG.json'}
    decoded = {}
    for name, value in payload['files'].items():
        raw = base64.b64decode(value, validate=True)
        if name == 'NONRUST_PACKET.json':
            assert raw == (PROPOSAL / 'NONRUST_APPLY_PACKET.json.gz').read_bytes()
            raw = gzip.decompress(raw)
        assert pin(raw) == pins[name] and raw == expected_files[name].read_bytes()
        decoded[name] = raw
    cfg = json.loads(decoded['APPROVED_CONFIG.json'])
    packet = json.loads(decoded['NONRUST_PACKET.json'])
    assert cfg['driver'] == pins['driver.py'] and cfg['nonrust_packet'] == pins['NONRUST_PACKET.json']
    assert cfg['status'] == 'ROOT_APPROVED_TO_EXECUTE' and cfg['root_execution_approved'] is True
    assert cfg['root_input_review_blob'] == pin((ROOT / 'ROOT_INPUT_REVIEW.json').read_bytes())['git_blob']
    assert cfg['peer_semantic_review_blob'] == 'c108a5c9f20bf057c404e3f01416ba2e5b78dac7'
    assert cfg['head'] == packet['source_identity']['head'] == '246d8cb614770252ee42029a5c014f2a4904176a'
    assert packet['source_identity']['status'] == ''
    assert cfg['head_tree'] == packet['source_identity']['tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    assert cfg['allowed_paths'] == [row['path'] for row in packet['changes']] and len(cfg['allowed_paths']) == 5
    assert cfg['expected_after_physical_tree'] == packet['expected_after_physical_tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    assert cfg['expected_after_leaf_count'] == packet['expected_after_leaf_count'] == 15188
    assert cfg['baseline_inventory'] == packet['base_inventory']
    assert (cfg['preflight_seconds'], cfg['fmt_seconds'], cfg['record_seconds'], cfg['outer_seconds']) == (600, 900, 300, 2100)
    assert cfg['fix_authorized'] is cfg['test_commands_authorized'] is cfg['ref_updates_authorized'] is False
    assert cfg['fmt_argv'] == ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f']
    manifest_raw = (LAUNCH / 'EXACT_LAUNCH_MANIFEST.json').read_bytes()
    manifest = json.loads(manifest_raw)
    for row in manifest['files']:
        assert {key: row[key] for key in ('bytes', 'sha256', 'git_blob')} == pin((LAUNCH / row['name']).read_bytes())
    assert manifest['raw_inputs'] == pins and manifest['idempotency_key'] == typed['idempotency_key']
    result = {'format': 'hepta-root-exact-source-repair-final-format-launch-approval-v1',
              'decision': 'APPROVE_EXACT_ONE_NATIVE_REQUEST', 'actual_process_input': pin(typed_raw),
              'actual_bootstrap': pin(bootstrap), 'actual_stdin': pin(stdin), 'launch_manifest': pin(manifest_raw),
              'four_raw_inputs': pins, 'seven_request_fields_only': True, 'stdin_below_original_one_mib_limit': True,
              'template_only_two_none_pins_replaced': True, 'all_bootstrap_helpers_and_control_bytes_unchanged': True,
              'host': typed['host'], 'cwd': typed['cwd'], 'executable': typed['executable'],
              'idempotency_key': typed['idempotency_key'], 'outer_seconds': 2100,
              'root_input_review': pin((ROOT / 'ROOT_INPUT_REVIEW.json').read_bytes()),
              'source_precondition': packet['source_identity'], 'baseline_inventory': cfg['baseline_inventory'],
              'approved_paths': cfg['allowed_paths'], 'approved_physical_tree_after_apply': cfg['expected_after_physical_tree'],
              'fmt_argv': cfg['fmt_argv'], 'budgets': {'preflight_apply': 600, 'fmt': 900, 'evidence': 300, 'outer': 2100},
              'original_EX_global_build_guard_environment_and_complete_audits_preserved': True,
              'failed_source_result_reclassified': False, 'tests_or_fix_or_ref_updates_authorized': False,
              'retry_or_rollback_authorized': False, 'native_execution_dispatched_by_this_review': False,
              'qualification': False, 'real_qualified_task_chains': 0,
              'execution_conditions': ['native_ci_audit alone dispatches these exact seven-field request bytes once',
                  'retain admission, normal terminal, original complete result, all actual postimages and full source/Git/input audits',
                  'if admission or state is uncertain reconcile the same idempotency/job; do not launch a second main',
                  'any changed request, source baseline or partial result requires a new concrete review; no budget or assertion relaxation']}
    (ROOT / 'ROOT_EXACT_LAUNCH_APPROVAL.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
