#!/usr/bin/env python3
"""Offline derivation and byte/AST review; no H, source activation or gate execution."""
from pathlib import Path
import ast
import base64
import copy
import gzip
import hashlib
import json
import re
import tomllib

ROOT = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
SOURCE = ROOT / 'source-before'
POST = ROOT / 'proposal-after'
BASE_INVENTORY = Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_CLEAN_INVENTORY.expected.json')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def create(name, raw):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return {'name': name, **pin(raw)}


def definitions(text):
    found = {}
    def descend(body, prefix=''):
        for node in body:
            if isinstance(node, ast.ClassDef):
                descend(node.body, prefix + node.name + '.')
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                assert name not in found
                found[name] = {'source': ast.get_source_segment(text, node),
                               'ast': ast.dump(node, include_attributes=False)}
    descend(ast.parse(text).body)
    return found


def main():
    prepared_raw = (ROOT / 'REPAIR_PACKET.json').read_bytes()
    prepared = json.loads(prepared_raw)
    initial_manifest_raw = (ROOT / 'REPAIR_MANIFEST.json').read_bytes()
    initial_manifest = json.loads(initial_manifest_raw)
    assert pin(prepared_raw)['git_blob'] == 'bade35cfabded0a0db3451d758e8316034cabec6'
    assert pin(initial_manifest_raw)['git_blob'] == '2c5ac17667053597ee9111445da45164afd849ae'
    inventory_raw = BASE_INVENTORY.read_bytes()
    assert pin(inventory_raw) == prepared['base_inventory'] == {
        'bytes': 5611184,
        'sha256': 'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e',
        'git_blob': '663373f936c2ff130aec96ad34654cc9811773c2',
    }
    inventory = json.loads(inventory_raw)
    assert inventory['source'] == {
        'head': '246d8cb614770252ee42029a5c014f2a4904176a',
        'tree': 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087', 'status': '',
    }
    index = {row['path']: row for row in inventory['files']}
    assert len(index) == 15188
    changed_paths = [entry['path'] for entry in prepared['changes']]
    assert changed_paths == sorted(changed_paths) and len(set(changed_paths)) == 5
    for entry in prepared['changes']:
        path = entry['path']
        before = (SOURCE / path).read_bytes()
        after = (POST / path).read_bytes()
        assert entry['mode'] == index[path]['index_mode'] == '100644'
        assert pin(before) == entry['before'] == {
            'bytes': index[path]['bytes'], 'sha256': index[path]['sha256'],
            'git_blob': index[path]['index_blob'],
        }
        assert pin(after) == entry['after']
        assert base64.b64decode(entry['after_base64'], validate=True) == after

    packet = {
        'format': 'hepta-reviewed-nonrust-source-apply-v1',
        'source_identity': inventory['source'],
        'base_inventory': prepared['base_inventory'],
        'base_physical_tree': prepared['base_tree'],
        'expected_after_physical_tree': prepared['expected_after_tree'],
        'expected_after_leaf_count': prepared['expected_after_leaf_count'],
        'changes': copy.deepcopy(prepared['changes']),
    }
    assert packet['changes'] == prepared['changes']
    assert packet['expected_after_physical_tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    assert packet['expected_after_leaf_count'] == 15188
    packet_raw = jbytes(packet)
    raw_record = create('NONRUST_APPLY_PACKET.json', packet_raw)
    compressed = gzip.compress(packet_raw, compresslevel=9, mtime=0)
    gzip_record = create('NONRUST_APPLY_PACKET.json.gz', compressed)
    part_records = []
    for number, offset in enumerate(range(0, len(compressed), 196608), 1):
        segment = compressed[offset:offset + 196608]
        encoded = base64.b64encode(segment) + b'\n'
        name = f'NONRUST_APPLY_PACKET.json.gz.part{number:03d}.b64'
        part_records.append({**create(name, encoded), 'decoded_offset': offset,
                             'decoded_bytes': len(segment), 'decoded_sha256': hashlib.sha256(segment).hexdigest()})
    assembled = b''.join(base64.b64decode((ROOT / row['name']).read_bytes(), validate=False)
                         for row in part_records)
    assert assembled == compressed and gzip.decompress(assembled) == packet_raw
    apply_manifest = {
        'format': 'hepta-246d-repair-native-schema-derivation-v1',
        'status': 'PREPARED_NOT_ACTIVATED_REQUIRES_ROOT_APPROVAL',
        'source_proposal': pin(prepared_raw),
        'original_preparation_manifest': pin(initial_manifest_raw),
        'transformation': 'Schema-only rename/rearrangement of top-level fields and explicit clean source identity from the exact original complete inventory. All five change objects, preimages, postimages, modes and base64 strings remain JSON-equal; no source content changed.',
        'source_identity': packet['source_identity'],
        'base_inventory': packet['base_inventory'],
        'base_physical_tree': packet['base_physical_tree'],
        'expected_after_physical_tree': packet['expected_after_physical_tree'],
        'expected_after_leaf_count': 15188,
        'packet': raw_record, 'gzip': gzip_record, 'parts': part_records,
        'reconstruction': 'In listed order remove the trailing LF from each ASCII base64 part, base64-decode each separately, concatenate the decoded bytes, verify the gzip identity, gunzip once, then verify raw JSON identity. No JSON reserialization is needed for reconstruction.',
        'qualification': False, 'native_or_H_execution': False,
    }
    create('NONRUST_APPLY_MANIFEST.json', jbytes(apply_manifest))

    old_callers_raw = (SOURCE / 'CALLERS.toml').read_bytes()
    new_callers_raw = (POST / 'CALLERS.toml').read_bytes()
    old_callers = tomllib.loads(old_callers_raw.decode())
    new_callers = tomllib.loads(new_callers_raw.decode())
    inverse = copy.deepcopy(new_callers)
    protected_delta = []
    for row_number in (386, 387, 388):
        old_row = old_callers['protected_file'][row_number]
        new_row = new_callers['protected_file'][row_number]
        assert new_row['forbidden'] == old_row['forbidden'] + ['recover_original_custody']
        inverse['protected_file'][row_number]['forbidden'].pop()
        protected_delta.append({'zero_based_row': row_number, 'path': old_row['path'],
                                'before_forbidden': old_row['forbidden'],
                                'after_forbidden': new_row['forbidden']})
    assert inverse == old_callers
    assert len(old_callers['boundary']) == len(new_callers['boundary']) == 569
    assert len(old_callers['protected_file']) == len(new_callers['protected_file']) == 422
    assert old_callers['boundary'] == new_callers['boundary']

    qa_reviews = []
    for path in [path for path in changed_paths if path.endswith('.py')]:
        old = (SOURCE / path).read_text()
        new = (POST / path).read_text()
        old_defs, new_defs = definitions(old), definitions(new)
        assert list(old_defs) == list(new_defs)
        changed = [name for name in old_defs if old_defs[name] != new_defs[name]]
        test_names = [name for name in old_defs if name.rsplit('.', 1)[-1].startswith('test_')]
        if path.endswith('test_original_circuit_observer_source_closure.py'):
            reverse = new.replace('        "fn into_command_owner(", "fn require_profile(",\n',
                                  '        "fn into_command_owner(",\n', 1)
            assert reverse == old and not changed
        elif path.endswith('test_resident_root_source_closure.py'):
            line = '    ' + json.dumps(initial_manifest['exact_new_root_issuer_case']) + ',\n'
            assert new.count(line) == 1
            reverse = new.replace(line, '', 1)
            assert reverse == old and not changed
        else:
            assert changed == ['OriginalSelectionReadbackClosureTests.test_wire_purpose_action_sequence_and_original_context_cannot_change']
            extra = '\n        self.mutate(\n            CLIENT, "fn operation(",\n            \'"runtime.learning.original-circuit-evaluated-selection.readback.v1"\',\n            \'"runtime.learning.original-circuit-evaluated-selection.readbacK.v1"\',\n        )'
            assert new.count(extra) == 1
            reverse = new.replace(extra, '', 1)
            reverse = reverse.replace('self.mutate(CLIENT, "fn operation(", "} else {\\n        OPERATION\\n    }")',
                                      'self.mutate(CLIENT, "fn operation(", "None => OPERATION")', 1)
            reverse = reverse.replace('self.mutate(CLIENT, "fn operation(", "context.evaluated.is_some()")',
                                      'self.mutate(CLIENT, "fn operation(", "Some(_)")', 1)
            assert reverse == old
        assert ast.dump(ast.parse(reverse), include_attributes=False) == ast.dump(ast.parse(old), include_attributes=False)
        qa_reviews.append({'path': path, 'before': pin(old.encode()), 'after': pin(new.encode()),
                           'test_method_count_before_and_after': len(test_names),
                           'all_definition_names_preserved': True,
                           'changed_function_definitions': changed,
                           'all_other_definition_source_and_AST_unchanged': True,
                           'exact_inverse_restores_entire_original_file_and_AST': True})

    training_path = 'qa/b4-no-bypass/test_original_training_readback_source_closure.py'
    training_raw = (SOURCE / training_path).read_bytes()
    assert training_path not in changed_paths
    assert (ROOT / 'targeted-proposal-source' / training_path).read_bytes() == training_raw
    assert pin(training_raw)['git_blob'] == index[training_path]['index_blob']
    allowance_before = (SOURCE / '.github/blob-size-allowlist.txt').read_bytes()
    allowance_after = (POST / '.github/blob-size-allowlist.txt').read_bytes()
    assert allowance_after.startswith(allowance_before)
    allowance_delta = allowance_after[len(allowance_before):].decode()
    assert allowance_delta == '\n# Original Trainer readonly adapters reject actual custody recovery; exact reviewed inventory.\nsha256:' + pin(new_callers_raw)['sha256'] + ' CALLERS.toml\n'
    diag_before = (ROOT / 'targeted-diagnostic-v1/INPUTS_BEFORE.json').read_bytes()
    diag_after = (ROOT / 'targeted-diagnostic-v1/INPUTS_AFTER.json').read_bytes()
    assert diag_before == diag_after
    source_rows = json.loads(diag_before)
    assert len(source_rows) == 32
    for row in source_rows:
        expected = next((change['after'] for change in prepared['changes'] if change['path'] == row['path']), None)
        if expected is None:
            original = index[row['path']]
            expected = {'bytes': original['bytes'], 'sha256': original['sha256'], 'git_blob': original['index_blob']}
        assert {key: row[key] for key in ('bytes', 'sha256', 'git_blob')} == expected
    result_raw = (ROOT / 'targeted-diagnostic-v1/RESULT.json').read_bytes()
    result = json.loads(result_raw)
    local_raw = (ROOT / 'targeted-diagnostic-v1/RAW.log').read_bytes()
    assert result['raw'] == pin(local_raw)
    assert result['returncode'] == 0 and result['timed_out'] is False and result['source_inputs_unchanged'] is True
    assert b'Ran 4 tests in 3.835s\n\nOK\n' in local_raw

    review = {
        'format': 'hepta-246d-five-file-repair-byte-AST-and-local-diagnostic-review-v1',
        'status': 'REVIEWED_PROPOSAL_WITH_SCOPED_FOUR_METHOD_PASS_NOT_QUALIFICATION',
        'base_source': inventory['source'], 'base_inventory': pin(inventory_raw),
        'original_preparation_manifest_unchanged': pin(initial_manifest_raw),
        'native_schema_packet': pin(packet_raw),
        'expected_after_tree': packet['expected_after_physical_tree'], 'expected_after_leaf_count': 15188,
        'files_changed': changed_paths,
        'callers': {'before': pin(old_callers_raw), 'after': pin(new_callers_raw),
                    'boundaries_before_after': 569, 'protected_rows_before_after': 422,
                    'only_three_additive_complete_identifiers': protected_delta,
                    'inverse_restores_entire_original_TOML': True,
                    'all_boundary_caller_authority_fields_unchanged': True,
                    'matcher_verifier_and_typed_helper_unchanged': True},
        'QA': qa_reviews,
        'training_QA': {'path': training_path, **pin(training_raw), 'bytes_unchanged': True,
                        'original_seven_mutations_for_each_three_readonly_paths_preserved': True},
        'allowlist': {'original_complete_bytes_are_prefix': True, 'delta': allowance_delta},
        'local_diagnostic': {'result': pin(result_raw), 'raw': pin(local_raw),
                             'input_count': 32, 'input_projection_before_after_equal': True,
                             'exact_original_inputs_with_only_five_approved_overlays': True,
                             'command': json.loads((ROOT / 'targeted-diagnostic-v1/INPUT.json').read_bytes())['command'],
                             'result_summary': result,
                             'scope': 'Only the four actual failing original methods, each with its unmodified class setup, against exact required files. This is a partial source fixture and is not a full-source collector or qualification run.'},
        'actual_original_source_gate': {
            'status': 'FAILED', 'runner_486_passed_6_failed_preserved': True,
            'raw_488_explicit_OK_4_failed_methods_6_failure_entries_492_total': True,
            'raw': pin((ROOT / 'raw.log').read_bytes()),
            'runner': pin((ROOT / 'source-closure.original.json').read_bytes())},
        'independent_training_peer': {
            'report_git_blob': 'edb5d3f56e224d95ab86f71ed0c2495aaa347993',
            'scoped_nine_typed_checks_git_blob': '86b27d8511396f485f605f71d13ea97c926e1cec',
            'limitation': 'The uncompiled Host no-argument injection is a static protection attack, not proof of runtime authority acquisition. The added complete identifier is an actual authority API and remains behind independent empty caller boundaries 353/354. No general recover-prefix detection claim.'},
        'not_performed': ['H/native/Cargo', 'complete source-closure', 'complete caller gate on repaired source',
                          'source activation', 'commit/ref/PR mutation'],
        'real_authorized_A_B_C_chains': 0,
    }
    review_record = create('REPAIR_REVIEW.json', jbytes(review))
    print(json.dumps({'apply_packet': raw_record, 'apply_gzip': gzip_record,
                      'apply_parts': part_records,
                      'apply_manifest': pin((ROOT / 'NONRUST_APPLY_MANIFEST.json').read_bytes()),
                      'review': review_record,
                      'qa_method_counts': {row['path']: row['test_method_count_before_and_after'] for row in qa_reviews}}, indent=2))


if __name__ == '__main__':
    main()
