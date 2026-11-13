#!/usr/bin/env python3
"""Pure content checks for this scoped memo; no project code or gates execute."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-section6-functional-completion-matrix-v1')
SOURCE_PATHS = {
    'closure.rs': 'codex-rs/hepta-intelligence-eval/src/closure.rs',
    'metric_roles.rs': 'codex-rs/hepta-intelligence-eval/src/metric_roles.rs',
    'ndu_well_posedness.rs': 'codex-rs/hepta-intelligence-eval/src/ndu_well_posedness.rs',
    'ope.rs': 'codex-rs/hepta-intelligence-eval/src/ope.rs',
    'eval_lib.rs': 'codex-rs/hepta-intelligence-eval/src/lib.rs',
    'product_material_commitments.rs': 'codex-rs/hepta-intelligence-eval/src/product_material_commitments.rs',
    'signed_evidence.rs': 'codex-rs/hepta-learning-ledger/src/signed_evidence.rs',
    'causal_v2.rs': 'codex-rs/hepta-learning-ledger/src/causal_v2.rs',
    'learning_iteration_types.rs': 'codex-rs/hepta-learning-artifacts/src/learning_iteration_types.rs',
    'cell_task_cost.rs': 'codex-rs/hepta-neuron/src/cell_task_cost.rs',
    'initial_root_custody.rs': 'codex-rs/hepta-agentd/src/neuron_generation_initial_root_custody.rs',
    'initial_root_cold.rs': 'codex-rs/hepta-agentd/src/neuron_generation_initial_root_cold.rs',
    'fresh_B_inputs.rs': 'codex-rs/hepta-agentd/src/circuit_original_evaluation_fresh_training_support_tests.rs',
    'objective_error.rs': 'codex-rs/hepta-objective/src/error.rs',
    'objective_model.rs': 'codex-rs/hepta-objective/src/model.rs',
    'objective_function_v1.rs': 'codex-rs/hepta-objective/src/objective_function_v1.rs',
    'run_start.rs': 'codex-rs/hepta-learning-ledger/src/run_start.rs',
    'initial_root_custody_tests.rs': 'codex-rs/hepta-agentd/src/neuron_generation_initial_root_custody_tests.rs',
    'initial_root_cold_tests.rs': 'codex-rs/hepta-agentd/src/neuron_generation_initial_root_cold_tests.rs',
    'closure_incomplete_evidence_tests.rs': 'codex-rs/hepta-intelligence-eval/src/closure_incomplete_evidence_tests.rs',
}

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def main():
    index_raw = (ROOT / 'INPUTS.full_get.json').read_bytes()
    index = json.loads(index_raw)
    inventory_raw = Path(index['inventory_file']).read_bytes()
    assert pin(inventory_raw) == index['inventory_pin']
    inventory = json.loads(inventory_raw)
    assert inventory['source']['head'] == index['source_commit']
    assert inventory['source']['tree'] == index['source_tree']
    assert inventory['source']['status'] == ''
    files = {row['path']: row for row in inventory['files']}
    assert len(files) == len(inventory['files']) == 15243
    observations = []
    for row in index['entries']:
        raw = Path(row['path']).read_bytes()
        measured = pin(raw)
        assert measured == {key: row[key] for key in measured}, row['name']
        assert row['full_Git_GET'] is True
        observation = {'name': row['name'], **measured,
                       'full_Git_GET_preserved_in_input_index': True}
        if row['name'] in SOURCE_PATHS:
            source_path = SOURCE_PATHS[row['name']]
            source = files[source_path]
            assert source['working_blob'] == measured['git_blob'], source_path
            assert source['bytes'] == measured['bytes'], source_path
            assert source['sha256'] == measured['sha256'], source_path
            observation.update(repository_path=source_path,
                               matches_actual_final_inventory=True)
        else:
            observation.update(kind='previous_frozen_source_audit',
                               matches_actual_final_inventory=None)
        observations.append(observation)
    assert len(observations) == 25
    assert sum('repository_path' in row for row in observations) == 20

    test_methods = []
    for name in ['initial_root_custody_tests.rs', 'initial_root_cold_tests.rs']:
        raw = (ROOT / 'inputs' / name).read_text()
        methods = re.findall(r'^async fn (root_initial_[a-z0-9_]+)\(', raw, re.M)
        ignored = raw.count('#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]')
        assert len(methods) == ignored
        test_methods.extend({'file': SOURCE_PATHS[name], 'method': method,
                             'direct_ignored_root_mechanism': True,
                             'executed_by_this_review': False} for method in methods)
    assert len(test_methods) == 9
    negative = (ROOT / 'inputs' / 'closure_incomplete_evidence_tests.rs').read_text()
    negative_methods = re.findall(r'^fn ([a-z0-9_]+)\(', negative, re.M)
    assert len(negative_methods) == 3
    result = {
        'schema': 'hepta-section6-pure-source-binding-review-v1',
        'outcome': 'EXACT_SCOPED_BYTES_AND_SOURCE_IDENTITIES',
        'source_commit': index['source_commit'], 'source_tree': index['source_tree'],
        'input_index': pin(index_raw), 'actual_inventory': pin(inventory_raw),
        'source_rows_checked': 20, 'prior_audits_checked': 5,
        'scope_note': 'Only the listed 20 source blobs were compared. No repository-wide absence claim, project code, collector, QA, Rust, H or runtime admission was executed.',
        'inputs': observations,
        'nine_root_mechanism_methods': test_methods,
        'incomplete_evidence_negative_methods': negative_methods,
        'qualification_results': None,
        'real_authorized_task_chain_successes_supported': 0,
        'full_daemon_and_root_process_cold_recovery_supported': False,
    }
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
    (ROOT / 'PURE_SOURCE_BINDING_REVIEW.json').write_bytes(raw)
    print(json.dumps({'review': pin(raw), 'sources': 20, 'prior_audits': 5,
                      'root_methods': 9, 'execution': False}, sort_keys=True))

if __name__ == '__main__':
    main()
