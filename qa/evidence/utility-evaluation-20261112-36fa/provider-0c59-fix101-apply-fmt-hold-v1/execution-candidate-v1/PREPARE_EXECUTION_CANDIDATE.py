#!/usr/bin/env python3
"""Pure cloud preparation; never execute the generated bootstrap or driver."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')
OUT = HERE / 'execution-candidate-v1'
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1/SOURCE_PACKET.json')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-fix101-apply-fmt-v1'
KEY = 'hepta-utility-36fa-provider-0c59-fix101-apply-fmt-v1'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def put(name, raw):
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == raw, ('existing prepared artifact differs', name)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'name': name, 'path': str(path), **pin(raw)}


def full_node(raw, name):
    text = raw.decode()
    node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ''.join(text.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])


def leaf_changes(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        assert set(before) == set(after)
        result = []
        for name in sorted(before):
            result += leaf_changes(before[name], after[name], prefix + '/' + name)
        return result
    return [] if before == after else [{'path': prefix, 'before': before, 'after': after}]


def main():
    OUT.mkdir(exist_ok=True)
    original_request_raw = (HERE / 'ORIGINAL_9101_PROCESS_INPUT.json').read_bytes()
    assert pin(original_request_raw)['git_blob'] == '60e6b8d8b12523318410b8f60d7626a7fdc1643e'
    original_request = json.loads(original_request_raw)
    old_bootstrap = original_request['args'][-1]
    assert old_bootstrap.encode() == (HERE / 'ORIGINAL_9101_BOOTSTRAP.py').read_bytes()
    assert pin(old_bootstrap.encode())['git_blob'] == '9ca752893983b582f2394c054e92a0adc265cb8f'

    driver = (HERE / 'driver-apply-fmt.HOLD.py').read_bytes()
    assert pin(driver)['git_blob'] == '0938761e369ddfa215da98b70423cfd5d48ac819'
    old_config_raw = (HERE / 'WAITING_CONFIG.json').read_bytes()
    old_config = json.loads(old_config_raw)
    config = dict(old_config)
    config['status'] = 'ROOT_APPROVED_TO_EXECUTE'
    config['root_execution_approved'] = True
    config_raw = jbytes(config)
    changes = leaf_changes(old_config, config)
    assert {x['path'] for x in changes} == {'/status', '/root_execution_approved'}
    inverse_config = dict(config)
    inverse_config['status'] = 'HOLD_ROOT_EXACT_REVIEW_REQUIRED'
    inverse_config['root_execution_approved'] = False
    assert jbytes(inverse_config) == old_config_raw
    assert config['driver'] == pin(driver)

    normal = (RUNTIME / 'MAIN_STATUS_06.original.json').read_bytes()
    proposal = REPAIR.read_bytes()
    assert pin(normal)['git_blob'] == '5980149603c1ab8f2a4a7aa7f21e9822c28c4c51'
    assert pin(proposal) == config['repair_proposal']
    files = {'driver.py': driver,
             'FAILED_MAINTENANCE_SUPERVISOR.original.json': normal,
             'REPAIR_PROPOSAL.original.json': proposal,
             'APPROVED_CONFIG.json': config_raw}
    pins = {name: pin(raw) for name, raw in files.items()}
    old_pin_line = next(line for line in old_bootstrap.splitlines() if line.startswith('PINS = '))
    new_pin_line = 'PINS = ' + repr(pins)
    replacements = [
        ("BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/source-repair-246d-fmt-control-v1')",
         'BASE = pathlib.Path(' + repr(CONTROL) + ')'),
        (old_pin_line, new_pin_line),
        ("if name == 'NONRUST_PACKET.json':", "if name == 'REPAIR_PROPOSAL.original.json':"),
        ('hepta-final-nonrust-format-bootstrap-v1', 'hepta-fix101-repair-format-bootstrap-v1'),
        ('hepta-final-nonrust-format-bootstrap-readback-v1', 'hepta-fix101-repair-format-bootstrap-readback-v1'),
        ('fixed_final_nonrust_format_bootstrap_verified', 'fixed_fix101_repair_format_bootstrap_verified'),
    ]
    bootstrap = old_bootstrap
    for before, after in replacements:
        assert bootstrap.count(before) == 1, before
        bootstrap = bootstrap.replace(before, after)
    inverse = bootstrap
    for before, after in reversed(replacements):
        assert inverse.count(after) == 1, after
        inverse = inverse.replace(after, before)
    assert inverse == old_bootstrap
    for name in ('check', 'identity', 'real_parents', 'retain'):
        assert full_node(bootstrap.encode(), name) == full_node(old_bootstrap.encode(), name)
    assert 'flock' not in bootstrap and 'fcntl' not in bootstrap
    assert 'SOURCE_COORDINATION.lock' not in bootstrap
    compile(bootstrap, '<prepared-bootstrap-only>', 'exec')

    compressed = gzip.compress(proposal, compresslevel=9, mtime=0)
    encoded = {name: base64.b64encode(compressed if name == 'REPAIR_PROPOSAL.original.json' else raw).decode('ascii')
               for name, raw in files.items()}
    payload_raw = jbytes({'format': 'hepta-fix101-repair-format-bootstrap-v1', 'files': encoded})
    payload = json.loads(payload_raw)
    for name, value in payload['files'].items():
        raw = base64.b64decode(value, validate=True)
        if name == 'REPAIR_PROPOSAL.original.json':
            raw = gzip.decompress(raw)
        assert raw == files[name] and pin(raw) == pins[name]

    request = dict(original_request)
    request['args'] = ['-B', '-c', bootstrap]
    request['stdin'] = payload_raw.decode()
    request['idempotency_key'] = KEY
    assert set(request) == {'host', 'executable', 'args', 'cwd', 'stdin', 'timeout_seconds', 'idempotency_key'}
    assert request['timeout_seconds'] == 2100 and request['host'] == 'desktop'
    assert request['cwd'] == '/home/qian-qi' and request['executable'] == '/usr/bin/python3'
    assert len(payload_raw) <= 1048576
    request_raw = jbytes(request)
    assert len(request_raw) <= 1048576

    driver_old = (HERE / 'ORIGINAL_9101_DRIVER.py').read_bytes()
    assert full_node(driver, 'main') == full_node(driver_old, 'main')
    original_helpers = {name: pin(full_node(old_bootstrap.encode(), name).encode())
                        for name in ('check', 'identity', 'real_parents', 'retain')}
    rows = [put('APPROVED_CONFIG.candidate.json', config_raw),
            put('ACTUAL_BOOTSTRAP.candidate.py', bootstrap.encode()),
            put('ACTUAL_STDIN.candidate.json', payload_raw),
            put('ACTUAL_PROCESS_INPUT.candidate.json', request_raw),
            put('CONFIG_FROM_HOLD.diff', ''.join(difflib.unified_diff(old_config_raw.decode().splitlines(keepends=True),
                  config_raw.decode().splitlines(keepends=True), fromfile='WAITING_CONFIG.json', tofile='APPROVED_CONFIG.candidate.json')).encode()),
            put('BOOTSTRAP_FROM_ORIGINAL_9101.diff', ''.join(difflib.unified_diff(old_bootstrap.splitlines(keepends=True),
                  bootstrap.splitlines(keepends=True), fromfile='ORIGINAL_9101_BOOTSTRAP.py', tofile='ACTUAL_BOOTSTRAP.candidate.py')).encode())]
    review = {
        'format': 'hepta-fix101-apply-fmt-exact-launch-static-review-v1',
        'state': 'PREPARED_FOR_ROOT_EXACT_REVIEW_NOT_DISPATCH_AUTHORIZED',
        'runtime_execution': False,
        'original_request': pin(original_request_raw), 'original_bootstrap': pin(old_bootstrap.encode()),
        'new_request': pin(request_raw), 'new_bootstrap': pin(bootstrap.encode()), 'new_stdin': pin(payload_raw),
        'driver': pin(driver), 'config': pin(config_raw), 'config_leaf_changes': changes,
        'config_full_inverse_equal': True, 'bootstrap_full_inverse_equal': True,
        'bootstrap_literal_replacement_count': len(replacements), 'unchanged_helpers': original_helpers,
        'decoded_inputs': pins, 'compressed_repair_transport': pin(compressed),
        'all_decoded_inputs_full_bytes_equal': True,
        'request_fields': sorted(request), 'environment_override_absent': True,
        'idempotency_key': KEY, 'outer_timeout_seconds': 2100,
        'control_directory': CONTROL,
        'budget': {'preflight_and_apply': 600, 'original_fmt': 900, 'shared_recording': 300, 'outer': 2100},
        'sequence': ['four fixed inputs validated in memory', 'fresh private control directory created',
                     'bootstrap/argv/payload and four fixed inputs written create-only and fully read back',
                     'unchanged execv tail enters the thin driver', 'thin main alone obtains LOCK_EX|LOCK_NB',
                     'actual failed-fix baseline and complete current environment/source/Git/input checks',
                     'four exact reviewed manual repairs', 'one original fmt with 900-second budget',
                     'complete actual source/Git/input/lock audits and retained terminal, then lock close'],
        'lock': {'bootstrap_opens_lock': False, 'bootstrap_inherits_additional_lock_fd': False,
                 'only_holder': 'the unchanged original 9101 thin main',
                 'thin_main_full_function_bytes_equal': True,
                 'scope': 'Cooperative writers only; complete before/after source and Git checks remain required.'},
        'historical_fix': {'job': '1a1d3eccd3a-392-231', 'returncode': 101, 'consumed': True,
                           'reclassified': False, 'second_fix_authorized': False},
        'source_ref_updates': False, 'tests_authorized': False, 'qualification': False,
        'actual_new_job': None, 'actual_new_result': None, 'actual_new_supervisor': None,
        'actual_postformat_inventory': None,
    }
    rows.append(put('EXACT_LAUNCH_STATIC_REVIEW.json', jbytes(review)))
    rows.append(put('PREPARE_EXECUTION_CANDIDATE.py', Path(__file__).read_bytes()))
    manifest = {'format': 'hepta-fix101-apply-fmt-execution-candidate-manifest-v1',
                'status': 'HOLD_ROOT_EXACT_REQUEST_APPROVAL_REQUIRED', 'dispatch_authorized': False,
                'entries': rows, 'decoded_fixed_inputs': pins,
                'exact_request': pin(request_raw), 'actual_execution': None}
    rows.append(put('MANIFEST.json', jbytes(manifest)))
    print(json.dumps(rows))


if __name__ == '__main__':
    main()
