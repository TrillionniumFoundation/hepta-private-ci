import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-after2268-20261112')
LAUNCH = Path('/tmp/hepta-36fa-final-nonrust-fmt-launch-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pins_and_skeleton(raw):
    tree = ast.parse(raw)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PINS' for target in node.targets)]
    assert len(assignments) == 1
    value = ast.literal_eval(assignments[0].value)
    assignments[0].value = ast.Constant(value=None)
    return value, ast.dump(tree, include_attributes=False)


def main():
    bootstrap = (LAUNCH / 'ACTUAL_BOOTSTRAP.py').read_bytes()
    template = Path('/tmp/hepta-36fa-final-nonrust-fmt-v1/BOOTSTRAP_TEMPLATE.HOLD.py').read_bytes()
    old_pins, old_skeleton = pins_and_skeleton(template)
    actual_pins, skeleton = pins_and_skeleton(bootstrap)
    assert skeleton == old_skeleton
    assert set(old_pins) == set(actual_pins) == {'driver.py', 'CAPTURE_NORMAL.original.json', 'NONRUST_PACKET.json', 'APPROVED_CONFIG.json'}
    for name in ('driver.py', 'CAPTURE_NORMAL.original.json'):
        assert old_pins[name] == actual_pins[name]
    assert old_pins['NONRUST_PACKET.json'] is None and old_pins['APPROVED_CONFIG.json'] is None
    cfg_raw = (ROOT / 'APPROVED_FINAL_NONRUST_FMT_V2_CONFIG.json').read_bytes()
    cfg = json.loads(cfg_raw)
    assert pin(cfg_raw)['git_blob'] == '6255bd067ebff2e4ca0cf890e791266645a38338'
    assert (LAUNCH / 'APPROVED_CONFIG.original.json').read_bytes() == cfg_raw
    assert cfg['status'] == 'ROOT_APPROVED_TO_EXECUTE' and cfg['root_execution_approved'] is True
    assert cfg['driver']['git_blob'] == '080753bf6fa5070c0f71096ace0cf199762ee42c'
    assert cfg['nonrust_packet']['git_blob'] == '5aa96020a8701f6e12b93c6a214964f61b69224f'
    assert cfg['expected_after_physical_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    assert (cfg['preflight_seconds'], cfg['fmt_seconds'], cfg['record_seconds'], cfg['outer_seconds']) == (600, 900, 300, 2100)
    assert cfg['fmt_argv'] == ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f']
    assert not any(cfg[key] for key in ('fix_authorized', 'test_commands_authorized', 'ref_updates_authorized'))
    request_raw = (LAUNCH / 'ACTUAL_PROCESS_INPUT.json').read_bytes()
    request = json.loads(request_raw)
    assert set(request) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
    assert request['host'] == 'desktop' and request['cwd'] == '/home/qian-qi'
    assert request['executable'] == '/usr/bin/python3' and request['args'] == ['-B', '-c', bootstrap.decode()]
    assert request['timeout_seconds'] == 2100 and request['idempotency_key'] == 'hepta-utility-36fa-final-nonrust-fmt-v1'
    stdin_raw = (LAUNCH / 'ACTUAL_STDIN.json').read_bytes()
    assert stdin_raw == request['stdin'].encode() and len(stdin_raw) <= 1048576
    payload = json.loads(stdin_raw)
    assert set(payload) == {'format', 'files'} and payload['format'] == 'hepta-final-nonrust-format-bootstrap-v1'
    assert set(payload['files']) == set(actual_pins)
    files = {}
    for name, value in payload['files'].items():
        raw = base64.b64decode(value, validate=True)
        if name == 'NONRUST_PACKET.json':
            raw = gzip.decompress(raw)
        assert pin(raw) == actual_pins[name]
        files[name] = raw
    assert files['APPROVED_CONFIG.json'] == cfg_raw
    assert files['driver.py'] == Path('/tmp/hepta-36fa-final-nonrust-fmt-v1/driver.HOLD.py').read_bytes()
    assert files['NONRUST_PACKET.json'] == Path('/tmp/hepta-36fa-reviewed-final-nonrust-v2/NONRUST_PACKET.json').read_bytes()
    assert pin(files['CAPTURE_NORMAL.original.json'])['git_blob'] == '8146d2ad99259a1965038f01dd3f8f186cd3e5a0'
    review = {
        'format': 'hepta-root-final-fmt-exact-launch-review-v1',
        'status': 'APPROVED_FOR_ONE_EXACT_NATIVE_LAUNCH',
        'root_input_review_blob': 'd80ce0a181264e2df6c7c0d6f11666797deef5e8',
        'peer_resolution_blob': '19ee2480b741a7866f1a348a81aeaf136d1397a6',
        'typed_request': pin(request_raw), 'stdin': pin(stdin_raw), 'bootstrap': pin(bootstrap),
        'original_bootstrap_template': pin(template), 'formal_config': pin(cfg_raw),
        'four_raw_inputs': actual_pins,
        'bootstrap_only_changes': 'Two absent PINS filled; complete remaining AST identical, including base path, input cap, create-only staging, bounded gzip read, four-file strict schema and exec argv.',
        'typed_field_count': 7, 'host': request['host'], 'cwd': request['cwd'],
        'idempotency_key': request['idempotency_key'], 'outer_seconds': request['timeout_seconds'],
        'original_fmt_seconds': 900, 'source_paths': cfg['allowed_paths'],
        'expected_after_physical_tree': cfg['expected_after_physical_tree'],
        'native_attempt_observed': False, 'qualification': False,
        'scope': 'Sole native executor may dispatch these exact seven fields once; retain original response and any partial effects. Reconcile only identical identity if transport is lost. No new fix/test/ref operation or relaxed deadlines.',
    }
    raw = (json.dumps(review, sort_keys=True, indent=2) + '\n').encode()
    (ROOT / 'ROOT_FINAL_FMT_EXACT_LAUNCH_REVIEW.json').write_bytes(raw)
    print(json.dumps({'review': pin(raw), 'typed_request': pin(request_raw), 'bootstrap': pin(bootstrap), 'stdin': pin(stdin_raw)}, indent=2))


if __name__ == '__main__':
    main()
