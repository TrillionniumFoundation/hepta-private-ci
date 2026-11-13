"""Pure frozen bytes and layer comparisons. No Rust/QA/main/native execution."""
import base64
import difflib
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-root-generation-custody-coordinator-v1')
TEST = Path('/tmp/hepta-36fa-root-generation-custody-tests-v1')
COLD = Path('/tmp/hepta-36fa-root-generation-custody-cold-v2')
PREFIX = 'codex-rs/hepta-agentd/src/'

def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def body(row, side):
    if row[side] is None:
        assert row.get(side + '_text') is None and row.get(side + '_base64') is None
        return None
    if side + '_base64' in row:
        raw = base64.b64decode(row[side + '_base64'], validate=True)
    else:
        raw = row[side + '_text'].encode('utf-8')
    assert ident(raw) == row[side], (row['path'], side)
    return raw

def main():
    jobs = [('production', BASE, 'PRODUCTION_PACKET.json', '3ffcac56096eb06214963ab1fdc5898e2b7eebb2', 4),
            ('tests', TEST, 'SOURCE_PACKET.json', 'ae05b4ca793a24a164d08e247a8faec62f690750', 3),
            ('cold', COLD, 'SOURCE_PACKET.json', 'a7256a2eea8df3af2c927f728b2c38c9342cc830', 4)]
    current = {}
    rows = []
    modifications = []
    packets = []
    for label, root, name, expected, count in jobs:
        raw = (root / name).read_bytes()
        assert ident(raw)['git_blob'] == expected
        packet = json.loads(raw)
        assert packet['base_commit'] == '0c59aaca0b4932507f068c723f73da2f96729b3d'
        assert len(packet['source_changes']) == count
        packets.append({'layer': label, **ident(raw)})
        for row in packet['source_changes']:
            path = row['path']
            before, after = body(row, 'before'), body(row, 'after')
            assert after == (root / 'after' / path).read_bytes()
            if path in current:
                assert current[path] == before, ('layer preimage', label, path)
            elif before is not None:
                assert before == (BASE / 'inputs/source' / path).read_bytes(), ('original', path)
            current[path] = after
            if before is not None:
                # Every existing body is an exact subsequence; identify the sole
                # inserted hunk independently, and remove it to recover all bytes.
                a, b = before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True)
                ops = [o for o in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if o[0] != 'equal']
                assert len(ops) == 1 and ops[0][0] == 'insert', (label, path, ops)
                _, i0, i1, j0, j1 = ops[0]
                assert i0 == i1
                inserted = ''.join(b[j0:j1])
                assert (''.join(b[:j0]) + ''.join(b[j1:])).encode() == before
                modifications.append({'layer': label, 'path': path, 'inserted_text': inserted,
                                      'old_full_bytes_recovered_by_removal': True})
            rows.append({'layer': label, 'path': path, 'before': None if before is None else ident(before),
                         'after': ident(after), 'full_local_body_matches_packet': True})
    assert len(current) == 9 and len(rows) == 11 and len(modifications) == 5
    production_new = ['neuron_generation_initial_root_custody.rs', 'neuron_generation_initial_root_task.rs',
                      'neuron_generation_initial_root_cold.rs']
    tests_new = ['neuron_generation_initial_root_custody_support_tests.rs', 'neuron_generation_initial_root_custody_tests.rs',
                 'neuron_generation_initial_root_cold_tests.rs']
    for name in tests_new:
        assert name.endswith('_tests.rs')
    core = current[PREFIX + production_new[0]].decode()
    task = current[PREFIX + production_new[1]].decode()
    cold = current[PREFIX + production_new[2]].decode()
    # Literal facts used to support the manual semantic review, not a Rust parser
    # or execution verdict. All full production bodies were read independently.
    assert core.index('std::mem::replace(&mut self.phase, InitialPhase::ReadbackRequired)') < core.index('(*prepared).publish(signed)?')
    assert 'Prepared(Box::new(prepared))' in core and 'self.phase = InitialPhase::Prepared' not in core
    assert 'pub current:' not in core and '#[derive(Clone)]' not in core + task + cold
    assert 'pub published_task:' not in task
    assert 'let retirement = task.clone();' in task and 'published_task: task,' in task
    assert 'cell: runtime.cell,' in task and 'source: runtime.source,' in task
    assert '.drain_completed_task(&self.cell, self.source.as_ref(), &self.identity)' in task
    assert 'Err(error) => Err(OriginalRootInitialInstallationErrorV1 { operation, error })' in task
    assert 'prepare_agentd_generation_initial_v1(' not in cold
    assert '.publish(' not in cold and 'recover_agentd_generation_initial_v1(' in cold
    assert 'if operation.read_original()? != before' in cold
    methods = []
    for name in tests_new[1:]:
        text = current[PREFIX + name].decode()
        names = re.findall(r'#\[tokio::test\([^\n]*\)\]\n#\[ignore = [^\n]+\]\nasync fn ([A-Za-z0-9_]+)\(', text)
        expected = 5 if name.endswith('custody_tests.rs') else 4
        assert len(names) == expected
        methods += [{'path': PREFIX + name, 'method': n, 'ignored_root_mechanism': True, 'executed': False} for n in names]
    support = current[PREFIX + tests_new[0]].decode()
    assert 'RootAuthorityDirectory::open(root_directory.path())?' in support
    assert 'self.providers.current' not in support
    assert 'timeout(Duration::from_secs(5), worker).await???;' in support
    original_refs = []
    source_pins = {
        'neuron_generation_initial.rs': '50cfc7f4db648a63e7085522d1bc96c31d16066d',
        'neuron_generation_current.rs': '36d3ae716003a4a6c499e005438ef176daab0826',
        'neuron_generation_current_initial.rs': '07092ccebbb5642fc42121187f57e842a9073b2a',
        'neuron_generation_current_initial_types.rs': '58b9b01746fba32e2a9fedf94655121d6e1df45f',
        'neuron_generation_initial_bootstrap.rs': 'c808361ee7a476fe8304fefb6f4f16e7af379043',
        'neuron_generation_update_live.rs': '3f83777f4f4a04ffc800d2be4eb5c8b4618bdc75',
        'circuit_q24_task_profile.rs': '153381dda993d21b0821d59f6b52e1b971bef98a',
        'config_q24_circuit_task.rs': 'c969fac0cbae5b43d5aaca8fd5c71bd53d99e934',
        'circuit_feature_current.rs': 'ea8581b8ad99b4fbc31e9fb2710c37b9a7b172a7',
        'circuit_feature_current_retirement.rs': 'd100d803ff1e44d814c155f0ef29992fe658ae9f'}
    for name, expected in source_pins.items():
        path = BASE / 'inputs/source' / PREFIX / name
        raw = path.read_bytes()
        assert ident(raw)['git_blob'] == expected, (name, ident(raw))
        original_refs.append({'path': PREFIX + name, **ident(raw)})
    output = {
        'schema': 'hepta-root-initial-custody-independent-frozen-layer-review-v1',
        'packets': packets, 'operations': rows, 'final_coverage_paths': len(current),
        'existing_body_preservation': modifications, 'original_refs': original_refs,
        'tests': methods, 'old_body_changes_other_than_exact_mount_exports': False,
        'new_production_paths': [PREFIX + n for n in production_new],
        'new_test_paths': [PREFIX + n for n in tests_new],
        'live_root_factory_called_by_fixture_source': True,
        'fixture_unused_test_current_not_passed_to_coordinator': True,
        'cleanup_limit': 'Normal Result path awaits cancellation/join; timeout drops the moved JoinHandle and returns Err, Drop only cancels. No terminal guarantee is inferred for timeout or outer cancellation.',
        'scope': 'Full packet/raw hash comparisons, exact layer ancestry and insertion inverses only; small literal checks document manually read code. No Rust parser/compiler, formatter, QA, test, H, runtime or source mutation.'}
    raw = (json.dumps(output, sort_keys=True, indent=2) + '\n').encode()
    with (HERE / 'FROZEN_LAYER_REVIEW.json').open('xb') as f:
        f.write(raw)
    print(json.dumps({'path': str(HERE / 'FROZEN_LAYER_REVIEW.json'), **ident(raw)}))

if __name__ == '__main__':
    main()
