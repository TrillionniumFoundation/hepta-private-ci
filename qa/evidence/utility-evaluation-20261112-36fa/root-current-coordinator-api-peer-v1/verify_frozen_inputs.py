"""Pure byte/pin verification for the CURRENT coordinator API review.

Reads fixed cloud source copies and the already matched 0c59 inventory.
Does not import candidate code, run Rust, Git, H, a gate, or a production main.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INVENTORY = Path('/tmp/hepta-36fa-new-source-materializer-hold-v1/EXPECTED_CANDIDATE.complete.inventory.json')
OLD_INDEX = Path('/tmp/hepta-36fa-root-current-cross-uid-peer-v1/SOURCE_INPUTS.json')
AUTHOR_INPUTS = Path('/tmp/hepta-36fa-root-generation-custody-coordinator-v1/inputs/source/codex-rs/hepta-agentd/src')
OLD_FEATURE = Path('/tmp/hepta-36fa-root-current-cross-uid-interface-proposal-v1/inputs/circuit_feature_current.rs')
NAMES = [
    'neuron_generation_current.rs',
    'neuron_generation_current_initial.rs',
    'neuron_generation_current_types.rs',
    'neuron_generation_current_initial_types.rs',
    'neuron_generation_current_store.rs',
    'neuron_generation_initial.rs',
    'neuron_generation_initial_bootstrap.rs',
    'neuron_generation_update.rs',
    'neuron_generation_update_bootstrap.rs',
    'neuron_generation_update_cold.rs',
    'neuron_generation_update_live.rs',
    'neuron_generation_update_selection.rs',
    'circuit_feature_current.rs',
    'circuit_feature_current_owner.rs',
    'circuit_feature_current_retirement.rs',
    'circuit_feature_current_control.rs',
    'circuit_feature_current_recovery.rs',
    'circuit_q24_task_profile.rs',
    'config_q24_circuit_task.rs',
]

def identity(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }

def main():
    inventory_raw = INVENTORY.read_bytes()
    assert identity(inventory_raw) == {
        'bytes': 5629701,
        'sha256': 'affce692432a4fa61521561e6717a84984f679f3535190b6b88c92cb0f725f44',
        'git_blob': 'a596ae68859e3263a9ee58e2b5d7334ac9314c34',
    }
    inventory = json.loads(inventory_raw)
    assert len(inventory['files']) == 15237
    by_path = {row['path']: row for row in inventory['files']}
    old_rows = json.loads(OLD_INDEX.read_text())['rows']
    old_by_name = {Path(row['path']).name: row for row in old_rows}
    rows = []
    for name in NAMES:
        repository_path = 'codex-rs/hepta-agentd/src/' + name
        canonical = by_path[repository_path]
        candidates = [ROOT / 'inputs' / name, AUTHOR_INPUTS / name]
        if name in old_by_name:
            candidates.append(Path(old_by_name[name]['local_path']))
        found = []
        for path in candidates:
            if path.exists():
                raw = path.read_bytes()
                pin = identity(raw)
                if pin['git_blob'] == canonical['working_blob']:
                    assert pin['bytes'] == canonical['bytes']
                    assert pin['sha256'] == canonical['sha256']
                    found.append((path, pin))
        assert found, (name, 'no exact canonical source bytes')
        path, pin = found[0]
        rows.append({'path': repository_path, 'local_path': str(path), **pin,
                     'canonical_inventory_match': True,
                     'observation': 'Exact frozen local bytes; not a new native read'})

    old = OLD_FEATURE.read_bytes()
    new = (ROOT / 'inputs' / 'circuit_feature_current.rs').read_bytes()
    assert identity(old)['git_blob'] == '542e4e532443ac2082bd0b8fa7649fcdb25deca9'
    assert identity(new)['git_blob'] == 'ea8581b8ad99b4fbc31e9fb2710c37b9a7b172a7'
    removals = [
        b'pub use learning_read::OriginalCircuitPublishedLocalReadV1;\n',
        b'pub use retained_publication::version::OriginalCircuitPublishedEvidenceReadbackV1;\n',
    ]
    inverse = new
    for line in removals:
        assert inverse.count(line) == 1
        inverse = inverse.replace(line, b'', 1)
    assert inverse == old

    get_rows = []
    for name in ['circuit_feature_current.rs', 'circuit_q24_task_profile.rs', 'config_q24_circuit_task.rs']:
        raw = (ROOT / 'inputs' / name).read_bytes()
        envelope_path = ROOT / 'inputs' / (name + '.GITHUB_GET.original.json')
        envelope = json.loads(envelope_path.read_bytes())
        assert envelope.get('isError') is not True
        content = envelope['structuredContent']['content']
        assert content.encode() == raw
        get_rows.append({'path': name, **identity(raw), 'full_get_equal': True,
                         'original_get_envelope': str(envelope_path)})
    result = {
        'schema': 'hepta-root-current-coordinator-api-peer-byte-verification-v1',
        'scope': 'Pure frozen-source byte verification; no candidate or runtime execution',
        'canonical_source': '0c59aaca0b4932507f068c723f73da2f96729b3d',
        'canonical_tree': '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09',
        'inventory': {'path': str(INVENTORY), **identity(inventory_raw),
                      'prior_native_match': 'Parent supplied already verified actual materialization; no second native scan'},
        'source_rows': rows,
        'source_count': len(rows),
        'new_actual_full_gets': get_rows,
        'accepted_old_feature_current_to_actual_0c59': {
            'before': identity(old), 'after': identity(new),
            'only_added_exports': [line.decode().strip() for line in removals],
            'inverse_full_bytes_equal': True,
        },
        'rust_formatter_qa_h_or_candidate_main_executed': False,
    }
    data = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
    output = ROOT / 'FROZEN_SOURCE_VERIFICATION.json'
    if output.exists():
        assert output.read_bytes() == data
    else:
        with output.open('xb') as stream:
            stream.write(data)
    print(json.dumps({'output': str(output), **identity(data), 'source_count': len(rows)}))

if __name__ == '__main__':
    main()
