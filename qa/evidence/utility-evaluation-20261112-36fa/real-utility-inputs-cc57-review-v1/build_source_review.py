"""Pure local source identity/catalog review. Never imports or executes repo code."""
from pathlib import Path
import hashlib
import json
import re
import tomllib

BASE = Path('/tmp/hepta-36fa-real-utility-gap-review-cc57-v1')
NEW = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
OLD = Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_CLEAN_INVENTORY.expected.json')
CALLERS = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/proposal-after/CALLERS.toml')
SHA = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'


def pins(value):
    return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()}


def write(name, data):
    (BASE / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


new_raw = NEW.read_bytes()
old_raw = OLD.read_bytes()
assert pins(new_raw) == {
    'bytes': 5611184,
    'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
    'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537',
}
new, old = json.loads(new_raw), json.loads(old_raw)
assert new['source'] == {'head': SHA, 'tree': TREE, 'status': ''}
assert old['source']['head'] == '246d8cb614770252ee42029a5c014f2a4904176a'
n = {row['path']: row for row in new['files']}
o = {row['path']: row for row in old['files']}
assert len(n) == len(o) == 15188 and n.keys() == o.keys()
changed = [p for p in sorted(n) if (n[p]['working_blob'], n[p]['index_mode']) != (o[p]['working_blob'], o[p]['index_mode'])]
assert changed == [
    '.github/blob-size-allowlist.txt', 'CALLERS.toml',
    'qa/b4-no-bypass/test_original_circuit_observer_source_closure.py',
    'qa/b4-no-bypass/test_original_selection_readback_source_closure.py',
    'qa/b4-no-bypass/test_resident_root_source_closure.py',
]
sources = []
tests = []
for path in sorted((BASE / 'sources').rglob('*')):
    if not path.is_file():
        continue
    rel = path.relative_to(BASE / 'sources').as_posix()
    raw = path.read_bytes()
    actual = pins(raw)
    expected = {'bytes': n[rel]['bytes'], 'sha256': n[rel]['sha256'], 'git_blob': n[rel]['working_blob']}
    assert actual == expected
    source = {'path': rel, **actual,
              'url': 'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/' + SHA + '/' + rel}
    sources.append(source)
    if rel.endswith('_tests.rs'):
        text = raw.decode()
        methods = []
        for match in re.finditer(r'(?m)^(?:async )?fn ([A-Za-z_][A-Za-z_0-9]*)\(', text):
            prefix = text[max(0, match.start() - 240):match.start()]
            if not re.search(r'#\[(?:tokio::)?test(?:\(|\])', prefix):
                continue
            methods.append({'name': match.group(1), 'line': text.count('\n', 0, match.start()) + 1,
                            'nearby_ignore_attribute': '#[ignore' in prefix})
        tests.append({'path': rel, 'git_blob': actual['git_blob'], 'methods_lexically_located': methods,
                      'executed_by_this_audit': False})
assert len(sources) == 59, len(sources)
write('VERIFIED_SOURCE_ROWS.json', sources)

callers_raw = CALLERS.read_bytes()
assert pins(callers_raw) == {'bytes': n['CALLERS.toml']['bytes'], 'sha256': n['CALLERS.toml']['sha256'], 'git_blob': n['CALLERS.toml']['working_blob']}
manifest = tomllib.loads(callers_raw.decode())
assert len(manifest['boundary']) == 569 and len(manifest['protected_file']) == 422
selected_ids = {
    'root_learning_original_purpose_send', 'root_learning_original_purpose_receive',
    'root_learning_original_stage_assembly', 'root_learning_original_runtime_consume',
    'root_resident_registration_create', 'root_resident_registration_recover',
    'root_resident_original_register', 'root_resident_runtime_consume',
    'root_resident_candidate_runtime_consume', 'root_resident_late_enrollment_config',
    'root_resident_late_enrollment_submit', 'learning_original_candidate_stage_create',
    'learning_original_training_bootstrap_create', 'learning_original_training_bootstrap_recover',
    'learning_original_training_bootstrap_serve', 'learning_original_candidate_bootstrap_serve',
    'learning_original_material_command_custody',
    'learning_original_material_command_serve_experience_commands',
    'learning_original_material_command_serve_dataset_commands',
    'learning_retained_version_evaluated_host_create', 'learning_retained_version_ordinary_serve',
    'learning_original_model_command_host_create', 'learning_original_model_command_host_serve',
    'learning_original_selector_command_owner_serve', 'learning_original_next_use_command_owner_serve',
}
selected = [{k: r[k] for k in ('id', 'symbol', 'definition_path', 'product_callers')}
            for r in manifest['boundary'] if r['id'] in selected_ids]
assert {r['id'] for r in selected} == selected_ids, selected_ids - {r['id'] for r in selected}

references = []
for path in sorted((BASE / 'references').iterdir()):
    if path.suffix != '.md':
        continue
    raw = path.read_bytes()
    references.append({'file': path.name, **pins(raw),
                       'use': 'historical context only; source/qualification claims rechecked or not inherited'})

review = {
    'format': 'hepta-real-utility-original-owner-input-review-v1',
    'status': 'READ_ONLY_REVIEW_AND_UNIMPLEMENTED_ASSEMBLY_HOLD',
    'source': new['source'],
    'full_inventory': {'local_path': str(NEW), **pins(new_raw), 'files': len(n),
                       'provenance': 'previous expected projection independently matched actual canonical readback by Root; no new native read in this audit'},
    'previous_full_inventory': {'local_path': str(OLD), **pins(old_raw), 'source': old['source']},
    'exact_changed_paths_from_246d': changed,
    'rust_source_changes_from_246d': [],
    'audited_source_file_count': len(sources),
    'source_rows_file': 'VERIFIED_SOURCE_ROWS.json',
    'callers': {**pins(callers_raw), 'boundaries': len(manifest['boundary']),
                'protected_files': len(manifest['protected_file']), 'selected_original_rows': selected,
                'interpretation': 'actual declared product consumer edges; empty rows corroborate inspected startup/library paths, not permission to add dummy callers'},
    'mechanism_tests_static_catalog': tests,
    'historical_reference_files': references,
    'findings': [
        {'id': 'assembly-agentd', 'classification': 'UNIMPLEMENTED_PRODUCT_ASSEMBLY_REQUIRING_ORIGINAL_PROVIDER_CONTRACT',
         'evidence': ['production_launcher.rs::receive', 'production_launcher.rs::run', 'config_root_learning.rs::with_root_learning_stage_owners', 'root_production_learning_handoff.rs::receive_learning_packet'],
         'conclusion': 'Current ordinary handoff carries checkpoint+Root pidfd only; real stage-owner bundle is not a config field or existing startup variable.'},
        {'id': 'assembly-resident', 'classification': 'UNIMPLEMENTED_PRODUCT_ASSEMBLY_REQUIRING_ORIGINAL_PROVIDER_CONTRACT',
         'evidence': ['authority_host_learning_resident.rs::into_candidate_runtime', 'config_resident_learning.rs', 'resident_learning_delivery.rs', 'bin/hepta-authority-host.rs'],
         'conclusion': 'Root resident factory and actual A-outbox late enrollment exist, but no inspected product producer assembles/serves the required role bundle. Agentd/local and resident modes must not consume the same bundle twice.'},
        {'id': 'evaluated-noupdate', 'classification': 'MECHANISM_IMPLEMENTED_REAL_OUTCOME_UNKNOWN',
         'conclusion': 'Original four/five/six-cut evaluated-retention continuation is present; full prefix, original T/E/current/publication/S/C and once-only checks remain. Legacy three/four/five-cut and Candidate Adopt refusal remain distinct.'},
        {'id': 'real-inputs', 'classification': 'NOT_DEMONSTRATED_IN_REVIEWED_MATERIALS',
         'conclusion': 'No reviewed artifact supplies an executable nonfixture A/B/C instance plus original permissions, deployable model materials and independent observations. This is bounded absence, not a global search result.'},
        {'id': 'costs', 'classification': 'NARROW_EXISTING_SCOPE_FULL_COST_UNKNOWN',
         'conclusion': 'TaskLedgersBeforeFinalHoldout excludes later estimator/signature/publication overhead. Immutable failed/cancelled/unknown-preserving ledger mechanism exists, but full externally frozen metering/allocation/reward contract and observations are not supplied by reviewed artifacts.'},
    ],
    'real_authorized_complete_chains_demonstrated_in_reviewed_materials': 0,
    'runtime_authorization_artifacts_created': [],
    'production_source_changes': [],
    'executions': {'H': 0, 'Cargo': 0, 'source_gates': 0, 'real_tasks': 0, 'repository_code_import_or_main': 0},
    'scope_limits': [
        'Does not inherit any previous qualification or synthetic test PASS.',
        'Does not classify engineering failures or Unknown as Objective Fraud.',
        'No default framework, future receipt, fixture-based credential replacement, or dummy product caller was added.',
        'HOLD is a producer/consumer integration specification, not an implemented or compiled patch.',
    ],
}
write('SOURCE_REVIEW.json', review)
print(json.dumps({'source_files': len(sources), 'selected_boundaries': len(selected), 'static_test_files': len(tests), 'changed': changed, 'review': pins((BASE / 'SOURCE_REVIEW.json').read_bytes())}, ensure_ascii=False))
