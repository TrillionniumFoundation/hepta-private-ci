#!/usr/bin/env python3
"""Bounded offline source-mechanism check; not a full caller gate or Rust test."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import tempfile
import tomllib

sys.dont_write_bytecode = True
BASE = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/source-before')
OWN = Path('/tmp/hepta-36fa-training-readonly-custody-peer-v1')
EXTRA = OWN / 'source-pins'
INVENTORY = Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_CLEAN_INVENTORY.expected.json')
PATHS = tuple('codex-rs/hepta-agentd/src/' + name for name in (
    'cell_q24_training_command_readback.rs',
    'cell_q24_training_command_readback_service.rs',
    'cell_q24_training_bootstrap_readback.rs',
))
DEFINITION = 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs'
TARGET = 'OriginalCellQ24TrainingBootstrapOwnerV1'
METHOD = 'recover_original_custody'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def source_path(relative):
    first = BASE / relative
    return first if first.is_file() else EXTRA / relative

def main():
    inventory_raw = INVENTORY.read_bytes()
    assert pin(inventory_raw)['git_blob'] == '663373f936c2ff130aec96ad34654cc9811773c2'
    inventory = json.loads(inventory_raw)
    expected = {row['path']: row for row in inventory['files']}
    references = ['CALLERS.toml', 'scripts/verify_hepta_callers.py',
                  'scripts/hepta_typed_callers.py',
                  'qa/b4-no-bypass/test_original_training_readback_source_closure.py',
                  DEFINITION,
                  'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs',
                  'qa/b4-no-bypass/test_original_training_bootstrap_source_closure.py',
                  'codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs', *PATHS]
    raw_sources = {path: source_path(path).read_bytes() for path in references}
    pins = {path: pin(raw) for path, raw in raw_sources.items()}
    for path, actual in pins.items():
        row = expected[path]
        assert actual['bytes'] == row['bytes']
        assert actual['sha256'] == row['sha256']
        assert actual['git_blob'] == row['working_blob'] == row['index_blob']
    spec = importlib.util.spec_from_file_location('custody_actual_246d_proof', BASE / 'scripts/verify_hepta_callers.py')
    proof = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = proof
    spec.loader.exec_module(proof)
    manifest = tomllib.loads(raw_sources['CALLERS.toml'].decode())
    boundary = next(row for row in proof._boundary_rows(manifest)
                    if row.identifier == 'learning_original_training_bootstrap_recover')
    assert boundary.symbol == TARGET + '::' + METHOD
    assert boundary.receiver_type == TARGET
    assert boundary.product_callers == ()
    source_index = {path: proof._strip_cfg_test_items(proof._strip_rust_non_code(raw_sources[path].decode()))
                    for path in (DEFINITION, *PATHS)}
    cases = {
        'actual_type_qualified': '\nfn injected_readback_authority() { let _ = ' + TARGET + '::' + METHOD + '(custody, config, dataset, cancellation); }\n',
        'declared_host_alias_qualified': '\nuse crate::' + TARGET + ' as Host;\nfn injected_readback_authority() { let _ = Host::' + METHOD + '(custody, config, dataset, cancellation); }\n',
        'explicit_typed_receiver_lexical': '\nfn injected_readback_authority(owner: &' + TARGET + ') { owner.' + METHOD + '(); }\n',
    }
    observations = []
    with tempfile.TemporaryDirectory(prefix='isolated-boundary-', dir=OWN) as tmp:
        isolated = Path(tmp)
        for path in source_index:
            target = isolated / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw_sources[path])
        baseline = proof._verify_boundary(isolated, boundary, source_index, (), fields_by_receiver_type={})
        for path in PATHS:
            for name, injected in cases.items():
                candidate = dict(source_index)
                candidate[path] = proof._strip_cfg_test_items(proof._strip_rust_non_code(raw_sources[path].decode() + injected))
                try:
                    proof._verify_boundary(isolated, boundary, candidate, (), fields_by_receiver_type={})
                except proof.VerificationFailure as error:
                    detail = str(error)
                    expected_error = ('caller set mismatch; missing=[], unexpected=[' + repr(path) + ']')
                    assert expected_error in detail, detail
                    observations.append({'path': path, 'case': name, 'injected_source': injected,
                                         'status': 'rejected_by_original_boundary', 'error': detail})
                else:
                    raise AssertionError((path, name, 'unexpected acceptance'))
    for path, raw in raw_sources.items():
        assert source_path(path).read_bytes() == raw
    result = {
        'format': 'hepta-training-readonly-custody-scoped-boundary-mechanism-v1',
        'source_commit': '246d8cb614770252ee42029a5c014f2a4904176a',
        'source_tree': 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087',
        'scope': 'Original boundary function over four pinned files; not the complete source collector or a full gate.',
        'inventory_pin': pin(inventory_raw), 'source_pins': pins,
        'original_verifier_unchanged': True, 'source_index_paths': sorted(source_index),
        'baseline_local_only': baseline, 'cases': observations,
        'rejected_cases': len(observations), 'input_bytes_unchanged': True,
        'rust_compilation_or_execution': False,
        'explicit_typed_receiver_caveat': 'The recovery function is associated, not a Rust instance method. This case probes the conservative lexical detector only. All snippets are uncompiled source mutations.',
        'full_gate_status': 'not_run_by_this_review',
        'does_not_test_candidate_protected_row_fix': True,
    }
    encoded = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode()
    output = OWN / 'BOUNDARY_MECHANISM.original.json'
    with output.open('xb') as handle:
        handle.write(encoded)
    print(json.dumps({'path': str(output), **pin(encoded), 'cases_rejected': len(observations),
                      'full_gate_status': result['full_gate_status']}))

if __name__ == '__main__':
    main()
