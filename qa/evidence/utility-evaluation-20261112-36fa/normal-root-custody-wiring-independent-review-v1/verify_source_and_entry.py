#!/usr/bin/env python3
"""Pure byte/entry-point audit. Does not import or execute project code."""
import hashlib
import json
from pathlib import Path
import tomllib

ROOT = Path('/tmp/hepta-36fa-normal-root-custody-wiring-audit-v1')
INVENTORY = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json')
CALLERS = Path('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1/after/CALLERS.toml')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def write_once(name, obj):
    raw = (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    target = ROOT / name
    if target.exists():
        assert target.read_bytes() == raw, ('existing audit differs', name)
    else:
        with target.open('xb') as stream:
            stream.write(raw)

def main():
    raw = INVENTORY.read_bytes()
    inv_id = identity(raw)
    assert inv_id == {'bytes': 5634549,
        'sha256': 'bc6b9d59143004236665bb9446e2c45d1ac77cd7aaba14ba7cee8f4ea76d003f',
        'git_blob': 'e1e48f35bb6cf5a3dd86c59472da77df87154b6a'}
    inv = json.loads(raw)
    rows = {r['path']: r for r in inv['files']}
    observations = json.loads((ROOT / 'SOURCE_FULL_GET_OBSERVATIONS.json').read_bytes())
    assert observations['source_count'] == len(observations['entries']) == 34
    inputs = []
    texts = {}
    for entry in observations['entries']:
        path = entry['path']
        body = (ROOT / 'source' / path).read_bytes()
        seen = identity(body)
        row = rows[path]
        assert seen == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
        assert seen['git_blob'] == entry['git_blob'] and entry['full_get_equal'] is True
        inputs.append({'path': path, **seen, 'scope': 'actual f905 inventory identity', 'actual_git_full_get_equal': True})
        texts[path] = body.decode()
    layers = [
        ('neuron_generation_initial_root_custody.rs', '/tmp/hepta-36fa-coordinator-original-metadata-getters-v1/after', '31ede1a405c6469508871d672c50a4f000342985'),
        ('neuron_generation_initial_root_task.rs', '/tmp/hepta-36fa-coordinator-f905-preparation-v1/after', '6cd8470ecba5b966f331fffdea86f0ffdf770c2f'),
        ('neuron_generation_initial_root_cold.rs', '/tmp/hepta-36fa-coordinator-f905-preparation-v1/after', '944a1927f2761000c206d018034b26d01a2ce0df'),
    ]
    for filename, base, expected in layers:
        path = 'codex-rs/hepta-agentd/src/' + filename
        body = (Path(base) / path).read_bytes()
        seen = identity(body)
        assert seen['git_blob'] == expected
        inputs.append({'path': path, **seen, 'scope': 'prepared 773d then 5279 layer, not actual f905 source'})
        texts[path] = body.decode()
    callers_raw = CALLERS.read_bytes()
    assert identity(callers_raw)['git_blob'] == '1f53a53349aa18d37a0c7299f2ab9fe94b0de244'
    callers = tomllib.loads(callers_raw.decode())
    new_rows = callers['boundary'][621:]
    assert len(new_rows) == 12
    assert all(r['product_callers'] == [] and r['caller_markers'] == [] for r in new_rows)
    entry_names = ['main.rs', 'bin/hepta-authority-host.rs', 'production_launcher.rs',
                   'production_launcher_inputs.rs', 'runtime.rs']
    names = ['OriginalRootInitialGenerationCustodyV1', 'OriginalRootCircuitTaskCustodyV1',
             'with_q24_circuit_task_profile', 'with_root_learning_stage_owners',
             'into_candidate_service', 'register_host_resident_learning_v3',
             'recover_host_resident_learning_v3']
    entry_observations = []
    for name in entry_names:
        path = 'codex-rs/hepta-agentd/src/' + name
        body = texts[path]
        matches = {needle: [i for i, line in enumerate(body.splitlines(), 1) if needle in line] for needle in names}
        entry_observations.append({'path': path, 'literal_occurrences': matches})
    assert all(not hits for row in entry_observations for hits in row['literal_occurrences'].values())
    required = {
        'production_launcher.rs': ['config.prepare_root_handoff(uid, gid)?.drop_to_owner()?',
            'config = config.with_root_learning_inputs(inputs)?;', 'config.require_root_learning_assembled()?;'],
        'config_root_handoff.rs': ['std::sync::Arc::strong_count(&self._writer_lock) != 1',
            'std::process::id() != self.process_id', 'descriptor.ino() != self.lock_inode'],
        'root_production_inputs.rs': ['if uid == 0', 'bundle.root.pid == std::process::id()',
            'metadata.uid() != uid', 'metadata.mode() & 0o7777 != 0o700'],
        'neuron_generation_update_live.rs': ['pub(crate) struct LiveGenerationCurrent',
            'artifacts: Arc<Mutex<LearningArtifactOwnerService>>', 'final_use: Arc<FinalUseAuthority>',
            'final_use.current_external_frontier().map_err(invalid)?;'],
        'circuit_feature_current.rs': ['pub struct PublishedCircuitFeatureTaskV1(Arc<PublishedTask>);',
            'current: Arc<LiveGenerationCurrent>'],
        'circuit_feature_current_retirement.rs': ['if !Arc::ptr_eq(&self.0, &cell.task.0)',
            'original.drain()?;', 'self.require_current()?;'],
        'neuron_generation_initial_root_custody.rs': ['libc::getuid() } != 0', 'libc::geteuid() } != 0'],
        'neuron_generation_initial_root_task.rs': ['require_root()?;',
            'let runtime = config.with_q24_circuit_task_profile(profile)?;',
            '.drain_completed_task(&self.cell, self.source.as_ref(), &self.identity)'],
    }
    anchors = []
    for name, needles in required.items():
        path = 'codex-rs/hepta-agentd/src/' + name
        body = texts[path]
        for needle in needles:
            hits = [i for i, line in enumerate(body.splitlines(), 1) if needle in line]
            assert hits, (path, needle)
            anchors.append({'path': path, 'exact_text': needle, 'lines': hits})
    result = {
        'schema': 'hepta-normal-root-custody-source-and-entry-review-v1',
        'status': 'PURE_BYTE_AND_BOUNDED_ENTRY_OBSERVATIONS_COMPLETE',
        'source_inventory': inv_id,
        'actual_source_inputs': 34,
        'prepared_coordinator_inputs': 3,
        'source_inputs': inputs,
        'prepared_callers': identity(callers_raw),
        'new_registered_boundary_rows': new_rows,
        'entry_literal_observations': entry_observations,
        'source_anchors': anchors,
        'limits': [
            'Literal absence is bounded to the five named shipping entry files; this is not a full repository collector run.',
            'All 34 original source bytes match the actual f905 inventory; the three coordinator sources remain a prepared layer.',
            'No project code, QA method, Rust compiler, gate, H operation or source mutation is executed.',
            'A source-level owner/custody mechanism is not proof of deployed host wiring or independent real task B.'
        ],
    }
    write_once('SOURCE_AND_ENTRY_PROOF.json', result)
    print(json.dumps({'actual_sources': 34, 'prepared_sources': 3,
        'registered_unwired_api_rows': 12, 'bounded_entry_files': 5,
        'output': 'SOURCE_AND_ENTRY_PROOF.json', **identity((ROOT / 'SOURCE_AND_ENTRY_PROOF.json').read_bytes())}))

if __name__ == '__main__':
    main()
