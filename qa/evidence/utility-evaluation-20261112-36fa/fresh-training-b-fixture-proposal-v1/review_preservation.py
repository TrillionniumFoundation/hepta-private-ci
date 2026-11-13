#!/usr/bin/env python3
"""Pure source-body review. Does not execute Rust, Cargo, source gates or verifier main."""
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = 'codex-rs/hepta-agentd/src/'
INVENTORY = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
VERIFIER = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/source-before/scripts/verify_hepta_callers.py')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(side, name):
    return (ROOT / side / PREFIX / name).read_text()

def mask_function():
    raw = VERIFIER.read_bytes()
    inventory = json.loads(INVENTORY.read_bytes())
    pin = next(row for row in inventory['files'] if row['path'] == 'scripts/verify_hepta_callers.py')
    assert identity(raw) == {'bytes': pin['bytes'], 'sha256': pin['sha256'], 'git_blob': pin['working_blob']}
    parsed = ast.parse(raw)
    selected = [n for n in parsed.body if isinstance(n, ast.FunctionDef)
                and n.name in ('_strip_rust_non_code', '_looks_like_char_literal')]
    assert len(selected) == 2
    namespace = {'RAW_STRING_START': re.compile(r'r(#{0,255})"')}
    # Only the original two pure lexical definitions are loaded; no main,
    # imports, manifest collection or verification assertion is run.
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<two-original-lexical-definitions>', 'exec'), namespace)
    return namespace['_strip_rust_non_code'], identity(raw)

def main():
    mask, verifier_pin = mask_function()
    def functions(text):
        stripped = mask(text)
        result = {}
        for match in re.finditer(r'\bfn\s+([A-Za-z_]\w*)\b', stripped):
            name = match[1]
            start = stripped.index('{', match.end())
            depth = 1
            end = start + 1
            while depth:
                if stripped[end] == '{': depth += 1
                elif stripped[end] == '}': depth -= 1
                end += 1
            assert name not in result, name
            result[name] = text[start:end]
        return result
    full = json.loads(INVENTORY.read_bytes())
    assert full['source']['head'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
    assert full['source']['tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    index = {r['path']: r for r in full['files']}
    before_files = sorted((ROOT / 'before' / PREFIX).glob('*.rs'))
    after_files = sorted((ROOT / 'after' / PREFIX).glob('*.rs'))
    assert len(before_files) == 7 and len(after_files) == 8
    checked = []
    for path in before_files:
        raw = path.read_bytes()
        pin = index[PREFIX + path.name]
        assert identity(raw) == {'bytes': pin['bytes'], 'sha256': pin['sha256'], 'git_blob': pin['working_blob']}
        checked.append({'path': PREFIX + path.name, 'before': identity(raw)})
    appended = []
    for name in ('cell_q24_training_bootstrap_original_ports_tests.rs',
                 'cell_q24_training_command_connection_support_tests.rs',
                 'cell_q24_training_readback_support_tests.rs',
                 'circuit_model_selection_owner_support_tests.rs',
                 'circuit_original_evaluation_provider_tests.rs'):
        old, new = read('before', name), read('after', name)
        assert new.startswith(old)
        appended.append({'path': PREFIX + name, 'entire_old_file_is_exact_prefix': True,
                         'added_bytes': len(new.encode()) - len(old.encode())})

    source_name = 'circuit_original_evaluation_source_support_tests.rs'
    source_before = functions(read('before', source_name))
    source_after = functions(read('after', source_name))
    expected_changes = {'populate_with_decision_binding', 'execute', 'config'}
    unchanged = [n for n in source_before if source_before[n] == source_after[n]]
    assert {n for n in source_before if source_before[n] != source_after[n]} == expected_changes
    old = source_before['populate_with_decision_binding']
    prefix = ('\n        let baseline = original.config.decision.request.selected_bundle.digest()?;'
              '\n        let candidate = original.candidate.digest()?;')
    assert old.count(prefix) == 1
    remaining = old.replace(prefix, '', 1)
    assert remaining.count('original,') == 3
    assert remaining.replace('original,', 'previous,') == source_after['populate_from_original_training']
    new = source_after['execute']
    assert new.count('previous.original_record()') == 1
    assert new.replace('previous.original_record()', 'original.previous.original_record()') == source_before['execute']
    new = source_after['config_from_original_training']
    replacements = [
        ('verifier.trust_digest()', 'original.config.verifier.trust_digest()'),
        ('            training,', '            training: Self::training(original)?,'),
        ('scope: scope.clone()', 'scope: original.config.scope.clone()'),
        ('training_evidence: training_evidence.clone()', 'training_evidence: original.config.training_evidence.clone()'),
        ('verifier: verifier.clone()', 'verifier: original.config.verifier.clone()'),
    ]
    for old_fragment, replacement in replacements:
        assert new.count(old_fragment) == 1, old_fragment
        new = new.replace(old_fragment, replacement, 1)
    assert new == source_before['config']

    member_name = 'circuit_original_evaluation_panel_member_support_tests.rs'
    member_before = functions(read('before', member_name))
    member_after = functions(read('after', member_name))
    member_unchanged = [n for n in member_before if member_before[n] == member_after[n]]
    assert {n for n in member_before if member_before[n] != member_after[n]} == {'complete'}
    common = member_after['complete_with_trainer']
    start = common.index('        let (trainer, thread) = match original_trainer {')
    end = common.index('        // Do not inline the original Qualification', start)
    old_body = member_before['complete']
    old_start = old_body.index('        let (trainer, thread) = fixture_original_receipt_client_until_close(')
    old_end = old_body.index('        // Do not inline the original Qualification', old_start)
    replacement = old_body[old_start:old_end]
    common = common[:start] + replacement + common[end:]
    assert common.count('\n            thread,\n') == 1
    common = common.replace('\n            thread,\n', '\n            thread: Some(thread),\n', 1)
    assert common == old_body
    assert 'None,' in member_after['complete'] and 'Some(trainer),' in member_after['complete_from_original_trainer']
    fixture = read('after', 'circuit_original_evaluation_fresh_training_support_tests.rs')
    assert 'PositiveFixture::' not in fixture and 'fixture_original_receipt_client_until_close(' not in fixture
    assert 'AuthorityPosture::DENY_ALL' in fixture
    assert 'IndependentEvaluationDispositionV1::Ineligible' in read('after', member_name)
    result = {
        'format': 'fresh-training-b-source-preservation-review-v1',
        'source_head': full['source']['head'], 'source_tree': full['source']['tree'],
        'before_files_exact_canonical': checked,
        'after_files': [{'path': PREFIX + p.name, **identity(p.read_bytes())} for p in after_files],
        'append_only_old_files': appended,
        'source_fixture_refactor': {
            'old_functions': len(source_before), 'old_unchanged_body_functions': unchanged,
            'delegated_old_functions': sorted(expected_changes),
            'populate_common_body_exact_after_three_actual_publication_parameter_substitutions': True,
            'execute_body_exact_after_original_publication_parameter_substitution': True,
            'config_common_body_exact_after_explicit_argument_substitutions': True,
            'old_wrapper_pure_training_snapshot_construction_now_precedes_config_body': True,
            'old_statements_or_assertions_removed': False},
        'panel_member_refactor': {
            'old_functions': len(member_before), 'old_unchanged_body_functions': member_unchanged,
            'complete_common_body_exact_after_only_trainer_injection_and_option_storage': True,
            'old_complete_passes_none_new_original_complete_passes_some': True,
            'all_original_qualification_and_ineligible_assertions_retained': True},
        'lexical_helper': verifier_pin,
        'only_pure_lexical_functions_loaded': ['_strip_rust_non_code', '_looks_like_char_literal'],
        'rust_parser_or_typecheck': False, 'rust_execution': False, 'cargo': False,
        'source_gate_or_verifier_main': False, 'new_test_methods_executed': 0,
        'external_dependency': 'ordinary_path supplies circuit_resident_candidate_provider_material_support_tests.rs for the new parent mount; this eight-file packet is a component, not a standalone compilable repository.'
    }
    raw = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    with (ROOT / 'STATIC_PRESERVATION_REVIEW.json').open('xb') as stream:
        stream.write(raw)
    print(json.dumps(identity(raw), sort_keys=True))

if __name__ == '__main__':
    main()
