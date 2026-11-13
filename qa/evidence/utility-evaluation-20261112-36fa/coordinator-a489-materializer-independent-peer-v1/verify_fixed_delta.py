#!/usr/bin/env python3
"""Only byte/AST/data checks; never imports or invokes materializer/bootstrap."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-coordinator-a489-materializer-independent-peer-v1')
AUTHOR = Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1')
INPUTS = ROOT / 'inputs'
PINS = {
    'driver': '2044db8282eb8db8d5627519a425a49f636377da',
    'packet': 'b05c78c478bbd55219fea7869b1c7871617509c7',
    'config': '42bd8a4df41c9b0bdfceab1487cce4b35da6c585',
    'bootstrap': 'b4b8ade499b3102ed450407fd9f05de44529cc39',
    'typed': 'a5a3f6b6bcc0bdbfb4c36261d4c2d31f6fb5cefa',
    'old_driver': '6d1537fcd58540da64c18916369f4f04d2a0dce1',
    'old_typed': 'a34c8779fca77cbf1dd7e26e5516efcfb654c191',
}

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def nodes(src, kind):
    return {n.name: n for n in ast.parse(src).body if isinstance(n, kind)}

def segment(src, node):
    return ast.get_source_segment(src, node)

def assignments(src):
    return {n.targets[0].id: n for n in ast.parse(src).body
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}

def literal_value(node):
    n = node.value
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'Path':
        return ast.literal_eval(n.args[0])
    return ast.literal_eval(n)

def decode_payload(typed):
    payload = json.loads(typed['stdin'])
    assert set(payload) == {'format', 'files'}
    assert payload['format'] == 'hepta-complete-candidate-materialization-bootstrap-v1'
    expected_names = {'driver.py', 'MATERIALIZATION_PACKET.json', 'DONOR_RESULT.original.json',
                      'DONOR_SUPERVISOR.original.json', 'APPROVED_CONFIG.json'}
    assert set(payload['files']) == expected_names
    out = {}
    for name, text in payload['files'].items():
        raw = base64.b64decode(text, validate=True)
        assert base64.b64encode(raw).decode() == text
        if name == 'MATERIALIZATION_PACKET.json':
            raw = gzip.decompress(raw)
        out[name] = raw
    return out

def main():
    raw = {k: (INPUTS / (k + '.original')).read_bytes() for k in PINS}
    ids = {k: identity(v) for k, v in raw.items()}
    assert all(ids[k]['git_blob'] == PINS[k] for k in PINS)
    new, old = raw['driver'].decode(), raw['old_driver'].decode()
    new_assign, old_assign = assignments(new), assignments(old)
    changed_globals = [k for k in old_assign if segment(old, old_assign[k]) != segment(new, new_assign[k])]
    assert set(changed_globals) == {'TARGET', 'CONTROL', 'STAGING_PREFIX', 'HEAD', 'TREE', 'LEAVES', 'PACKET_PIN'}
    replacements = [(segment(old, old_assign[k]), segment(new, new_assign[k])) for k in changed_globals]
    explicit = [
        ("check(len(covered) == packet['overlay']['covered_paths'] == 110 and added == packet['overlay']['new_paths'] == 49 and changed == packet['overlay']['modified_paths'] == 60 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 110-path overlay')",
         "check(len(covered) == packet['overlay']['covered_paths'] == 119 and added == packet['overlay']['new_paths'] == 55 and changed == packet['overlay']['modified_paths'] == 63 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 119-path overlay')"),
        ('candidate_provided = add_provided(candidate_input, 120)', 'candidate_provided = add_provided(candidate_input, 129)'),
        ("check(len(object_index) == packet['object_scope']['union_objects'] == 16652 and counts == packet['object_scope']['counts'] == {'blob': 14796, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')",
         "check(len(object_index) == packet['object_scope']['union_objects'] == 16661 and counts == packet['object_scope']['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')")
    ]
    replacements.extend(explicit)
    restored = new
    for before, after in replacements:
        assert old.count(before) == 1 and restored.count(after) == 1
        restored = restored.replace(after, before, 1)
    assert restored == old and len(replacements) == 10
    before_defs = nodes(old, (ast.FunctionDef, ast.ClassDef))
    after_defs = nodes(new, (ast.FunctionDef, ast.ClassDef))
    assert set(before_defs) == set(after_defs) and len(before_defs) == 56
    def_rows = []
    for name, before in before_defs.items():
        after = after_defs[name]
        byte_equal = segment(old, before) == segment(new, after)
        ast_equal = ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False)
        assert byte_equal == ast_equal
        def_rows.append({'name': name, 'kind': type(before).__name__, 'byte_equal': byte_equal,
            'ast_equal': ast_equal, 'before_sha256': hashlib.sha256(segment(old, before).encode()).hexdigest(),
            'after_sha256': hashlib.sha256(segment(new, after).encode()).hexdigest()})
    assert [r['name'] for r in def_rows if not r['byte_equal']] == ['derive_candidate_inventory', 'expected_graphs']
    constants = {k: literal_value(new_assign[k]) for k in ['SOURCE', 'TARGET', 'CONTROL', 'STAGING_PREFIX',
        'HEAD', 'TREE', 'PARENT', 'LEAVES', 'DONOR_HEAD', 'DONOR_TREE', 'DONOR_LEAVES', 'ACTION_SECONDS', 'RECORD_SECONDS']}
    assert constants['ACTION_SECONDS'] == 600 and constants['RECORD_SECONDS'] == 180
    assert constants['PARENT'] == constants['DONOR_HEAD'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
    assert constants['DONOR_LEAVES'] == 15188 and constants['LEAVES'] == 15243
    assert constants['HEAD'] == 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
    assert constants['TREE'] == 'a489b394666b8141840275128a780605b024cde0'
    assert literal_value(new_assign['PACKET_PIN']) == ids['packet']
    typed = json.loads(raw['typed']); old_typed = json.loads(raw['old_typed'])
    assert set(typed) == set(old_typed) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
    assert typed['host'] == old_typed['host'] == 'desktop'
    assert typed['cwd'] == old_typed['cwd'] == '/home/qian-qi'
    assert typed['executable'] == old_typed['executable'] == '/usr/bin/python3'
    assert typed['args'][:2] == ['-B', '-c'] and len(typed['args']) == 3
    assert typed['args'][2].encode() == raw['bootstrap']
    assert typed['timeout_seconds'] == old_typed['timeout_seconds'] == 900
    assert typed['idempotency_key'] == 'hepta-utility-36fa-provider-coordinator-a489-isolated-materialization-v1'
    assert len(raw['typed']) <= 1048576 and len(typed['stdin'].encode()) <= 1048576
    assert identity(typed['stdin'].encode()) == {'bytes': 121937, 'sha256': 'd033544bf068677ebda7bb8223cac618fb7eb68ebdeef531f3070d04bc7c0cdb', 'git_blob': 'e4e971cde74ede142a8ef044a516652e35fbacb2'}
    boot, old_boot = raw['bootstrap'].decode(), old_typed['args'][2]
    ba, oa = assignments(boot), assignments(old_boot)
    inverse_boot = boot
    for key in ['BASE', 'PINS']:
        before, after = segment(old_boot, oa[key]), segment(boot, ba[key])
        assert inverse_boot.count(after) == 1
        inverse_boot = inverse_boot.replace(after, before, 1)
    assert inverse_boot == old_boot
    boot_defs, old_boot_defs = nodes(boot, ast.FunctionDef), nodes(old_boot, ast.FunctionDef)
    assert set(boot_defs) == set(old_boot_defs) == {'check', 'identity', 'real_parents', 'retain'}
    assert all(segment(boot, boot_defs[k]) == segment(old_boot, old_boot_defs[k]) for k in boot_defs)
    bootstrap_pins = ast.literal_eval(ba['PINS'].value)
    files, old_files = decode_payload(typed), decode_payload(old_typed)
    assert {k: identity(v) for k, v in files.items()} == bootstrap_pins
    for label, filename in [('driver', 'driver.py'), ('packet', 'MATERIALIZATION_PACKET.json'), ('config', 'APPROVED_CONFIG.json')]:
        assert files[filename] == raw[label]
    assert files['DONOR_RESULT.original.json'] == old_files['DONOR_RESULT.original.json']
    assert files['DONOR_SUPERVISOR.original.json'] == old_files['DONOR_SUPERVISOR.original.json']
    packet, old_packet = json.loads(raw['packet']), json.loads(old_files['MATERIALIZATION_PACKET.json'])
    invariant_packet_keys = ['donor', 'donor_git', 'donor_proof', 'format', 'format_base', 'git_tool',
        'original_inventory', 'parent_snapshot', 'qualification', 'seed_raw_commits', 'source_repo']
    assert all(packet[k] == old_packet[k] for k in invariant_packet_keys)
    assert packet['current']['parents'] == old_packet['current']['parents'] == [constants['PARENT']]
    assert packet['object_scope']['reused_donor_objects'] == 16449
    assert packet['object_scope']['provided_base_objects'] == 83
    assert packet['object_scope']['provided_candidate_objects'] == 129
    assert packet['object_scope']['union_objects'] == 16661
    assert packet['object_scope']['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}
    assert packet['object_scope']['unmaterialized_parent_boundaries'] == old_packet['object_scope']['unmaterialized_parent_boundaries']
    assert packet['donor']['allowed_missing_paths'] == []
    cfg, waiting = json.loads(raw['config']), json.loads((AUTHOR / 'WAITING_CONFIG.json').read_bytes())
    delta = {k: {'before': waiting[k], 'after': cfg[k]} for k in cfg if cfg[k] != waiting[k]}
    assert set(cfg) == set(waiting) and set(delta) == {'status', 'root_execution_approved'}
    assert cfg['status'] == 'APPROVED_CANDIDATE_ISOLATED_MATERIALIZATION' and cfg['root_execution_approved'] is True
    assert cfg['driver'] == ids['driver'] and cfg['action_seconds'] == 600 and cfg['record_seconds'] == 180
    assert cfg['source_repo'] == constants['SOURCE'] and cfg['destination_repo'] == constants['TARGET'] and cfg['control'] == constants['CONTROL']
    assert cfg['qualification'] is False and cfg['automatic_retry'] is False
    stages = []
    for group, expected_count in [('base', 2), ('candidate', 3)]:
        provided = packet['provided_inputs'][group]
        assert len(provided['parts']) == expected_count and provided['maximum_decoded_part'] == 524288
        offset = 0
        for i, item in enumerate(provided['parts'], 1):
            path = constants['STAGING_PREFIX'] + '-' + group + '.json.gz.part-%03d' % i
            assert item['path'] == path and item['offset'] == offset and item['mode'] == 0o600 and 0 < item['bytes'] <= 524288
            name = 'STAGE_' + group.upper() + '_%03d.REQUEST.HOLD.json' % i
            request_raw = (AUTHOR / name).read_bytes(); request = json.loads(request_raw)
            assert set(request) == {'data_base64', 'expected_version', 'host', 'path'}
            assert request['host'] == 'desktop' and request['path'] == path and request['expected_version'] == 'absent'
            block = base64.b64decode(request['data_base64'], validate=True)
            assert identity(block) == {k: item[k] for k in ('bytes', 'sha256', 'git_blob')}
            assert len(request_raw) <= 1048576
            offset += len(block)
            stages.append({'name': name, 'request': identity(request_raw), 'decoded': identity(block),
                'path': path, 'expected_version': 'absent', 'required_mode_checked_by_driver': '0600'})
        assert offset == provided['gzip']['bytes']
    # Key invariants are checked in their byte-identical original definition.
    guards = {
        'preflight': ["cfg['action_seconds'] == 600 and cfg['record_seconds'] == 180", "not os.path.lexists(TARGET)",
            'fcntl.LOCK_EX | fcntl.LOCK_NB', "check_processes('before-preparation')", "check_processes('before-new-destination')"],
        'command': ["not mutation or (repo == TARGET and target_created)", "unknown_after_bounded_owned_cleanup", "process.communicate(timeout=5)"],
        'source_physical': ["packet['donor']['allowed_missing_paths'] == []", "physical_paths(SOURCE) == expected"],
        'create_destination': ['source_reader.get(key, expected)', 'len(donor_verified) == 16449', "pack_path.open('xb')"],
        'main': ["row = {'check': name, 'status': 'unknown_not_available'}", "len(audits) == 3 and all(row['status'] == 'verified' for row in audits)",
            "'retention_error' not in result", "'FAILED_CANDIDATE_MATERIALIZATION'", 'record_deadline - 10'],
    }
    for name, needles in guards.items():
        source = segment(new, after_defs[name]); assert segment(old, before_defs[name]) == source
        assert all(needle in source for needle in needles), name
    out = {'schema': 'hepta-a489-materializer-fixed-delta-independent-byte-review-v1',
        'status': 'PURE_CHECKS_COMPLETE_NO_CONTROL_EXECUTION', 'input_identities': ids,
        'inverse_full_driver_bytes_equal': True, 'replacement_count': 10, 'changed_globals': changed_globals,
        'definitions': def_rows, 'unchanged_definitions': 54, 'constants': constants,
        'bootstrap_inverse_full_bytes_equal': True, 'four_bootstrap_helpers_byte_equal': True,
        'request_fields': sorted(typed), 'request_environment_override': False,
        'timeout_seconds': 900, 'five_payload_identities': bootstrap_pins,
        'invariant_packet_keys': invariant_packet_keys, 'candidate_config_exact_delta': delta,
        'staging_path_pin_capacity_checks': stages, 'separate_parts': [2, 3],
        'all_original_guard_definitions_byte_equal': list(guards),
        'object_content_membership_peer_scope': 'Ordinary independently audits full 129 objects and union. This review checks exact algorithm preservation, declared bindings and bounded staging identities; it does not call expected_graphs or preflight.',
        'no_H_no_product_execution_no_source_mutation': True}
    encoded = (json.dumps(out, sort_keys=True, indent=2) + '\n').encode()
    target = ROOT / 'FROZEN_BYTE_AND_GUARD_REVIEW.json'
    if target.exists(): assert target.read_bytes() == encoded
    else:
        with target.open('xb') as f: f.write(encoded)
    print(json.dumps({'status': out['status'], 'definitions': len(def_rows), 'unchanged': 54,
        'replacements': 10, 'staging_requests': len(stages), **identity(encoded)}))

if __name__ == '__main__':
    main()
