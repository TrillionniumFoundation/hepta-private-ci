"""Pure byte freeze; does not execute Rust, format source or invoke H."""
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path('/tmp/hepta-36fa-root-generation-custody-cold-v2')
SRC = 'codex-rs/hepta-agentd/src/'
PRODUCTION_PARENT = SRC + 'neuron_generation_initial_root_custody.rs'
TEST_PARENT = SRC + 'neuron_generation_initial_root_custody_support_tests.rs'
PRODUCTION = SRC + 'neuron_generation_initial_root_cold.rs'
TESTS = SRC + 'neuron_generation_initial_root_cold_tests.rs'
MOUNTS = {
 PRODUCTION_PARENT: ('76142e204c9e10b5544e5586e08ea197ed2e1059', b'\n#[path = "neuron_generation_initial_root_cold.rs"]\nmod cold;\n'),
 TEST_PARENT: ('cdcd7949e8d620463ddd9abdfdc3dd413cc3e6d9', b'\n#[path = "neuron_generation_initial_root_cold_tests.rs"]\nmod cold_tests;\n'),
}

def pin(raw):
 return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
         'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def save(name, value):
 raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
 p = ROOT / name
 if p.exists():
  assert p.read_bytes() == raw, f'frozen file differs: {name}'
 else:
  p.write_bytes(raw)
 return pin(raw)

proof = []
for path, (sha, mount) in MOUNTS.items():
 before = (ROOT / 'before' / path).read_bytes()
 after = (ROOT / 'after' / path).read_bytes()
 assert pin(before)['git_blob'] == sha
 assert after == before + mount
 proof.append({'path': path, 'before': pin(before), 'after': pin(after),
               'exact_prefix_preserved': True, 'added_mount': mount.decode()})

originals = Path('/tmp/hepta-36fa-root-generation-custody-coordinator-v1/inputs/source')
refs = {
 'neuron_generation_current.rs': '36d3ae716003a4a6c499e005438ef176daab0826',
 'neuron_generation_current_initial.rs': '07092ccebbb5642fc42121187f57e842a9073b2a',
 'neuron_generation_initial.rs': '50cfc7f4db648a63e7085522d1bc96c31d16066d',
 'neuron_generation_initial_bootstrap.rs': 'c808361ee7a476fe8304fefb6f4f16e7af379043',
 'neuron_generation_update_live.rs': '3f83777f4f4a04ffc800d2be4eb5c8b4618bdc75',
}
reference_rows = []
for name, sha in refs.items():
 raw = (originals / SRC / name).read_bytes()
 assert pin(raw)['git_blob'] == sha
 reference_rows.append({'path': SRC + name, **pin(raw)})
save('SOURCE_REFERENCES.json', reference_rows)

changes = []
diff = []
for path in sorted([PRODUCTION_PARENT, TEST_PARENT, PRODUCTION, TESTS]):
 before_path = ROOT / 'before' / path
 before = before_path.read_bytes() if before_path.exists() else None
 after = (ROOT / 'after' / path).read_bytes()
 changes.append({'path': path, 'mode': '100644', 'before': pin(before) if before is not None else None,
                 'before_text': before.decode() if before is not None else None,
                 'after': pin(after), 'after_text': after.decode()})
 diff.extend(difflib.unified_diff((before or b'').decode().splitlines(True), after.decode().splitlines(True),
             fromfile='a/' + path if before is not None else '/dev/null', tofile='b/' + path))
diff_raw = ''.join(diff).encode()
diff_path = ROOT / 'SOURCE_DELTA.patch'
if diff_path.exists():
 assert diff_path.read_bytes() == diff_raw
else:
 diff_path.write_bytes(diff_raw)

production_text = (ROOT / 'after' / PRODUCTION).read_text()
test_text = (ROOT / 'after' / TESTS).read_text()
body = production_text[production_text.index('    pub fn recover_from_original_current('):]
assert len(re.findall(r'^    pub fn ', production_text, re.M)) == 1
assert body.count('recover_agentd_generation_initial_v1(') == 1
assert 'Arc::clone(&current)' in body and 'authorities.clone()' in body
assert 'operation.read_original()? != before' in body
assert not re.search(r'\b(?:prepare_agentd_generation_initial_v1|claim_final_use|initialize|publish|from_parts)\(', body)
names = re.findall(r'^async fn (root_initial_cold_entry_[a-z_]+)\(', test_text, re.M)
assert len(names) == 4 and len(set(names)) == 4
assert test_text.count('#[ignore = ') == 4 and test_text.count('#[tokio::test') == 4
assert not re.search(r'\bassert(?:_eq|_ne)?!', test_text)
assert 'RootAuthorityDirectory::open(fixture.root_directory.path())?' in test_text
assert 'NeuronGenerationCurrentOwnerV1::open(' in test_text
assert 'let cleanup = session.finish().await;\n    result.and(cleanup)' in test_text
assert 'CurrentStore::from_test_store' not in test_text
prefix = 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::cold_tests::'
save('TEST_INVENTORY.json', {'format': 'hepta-root-cold-entry-test-inventory-v2',
 'status': 'PREPARED_NOT_FORMATTED_COMPILED_OR_EXECUTED', 'test_count': 4,
 'test_fqns': [prefix + n for n in names], 'mechanism': 'Actual Current/journal reopen in the same process',
 'authority_scope': 'Existing original engineering Artifact/FinalUse fixture instances are retained',
 'process_restart_test': False, 'requires_explicit_root_ignored_selection': True})
packet = {'format': 'hepta-original-root-cold-custody-source-proposal-v2',
 'status': 'FROZEN_CANDIDATE_PENDING_INDEPENDENT_REVIEW',
 'base_commit': '0c59aaca0b4932507f068c723f73da2f96729b3d',
 'dependencies': {'production_v1': '3ffcac56096eb06214963ab1fdc5898e2b7eebb2',
                  'mechanism_tests_v1': 'ae05b4ca793a24a164d08e247a8faec62f690750'},
 'source_changes': changes, 'source_deletions': [], 'old_functions_or_tests_changed': 0,
 'new_public_associated_methods': ['OriginalRootInitialGenerationCustodyV1::recover_from_original_current'],
 'new_root_tests': 4, 'H_format_compile_Rust_QA_calls': 0,
 'source_ref_mutations': 0, 'real_useful_task_chain_completions': 0}
packet_pin = save('SOURCE_PACKET.json', packet)
save('STATIC_REVIEW.json', {'format': 'hepta-root-cold-custody-pure-byte-review-v2',
 'source_packet': packet_pin, 'parents': proof,
 'new_constructor': 'Direct original recovery; same Current/authority Arcs; complete protected readback before/after',
 'original_production_and_test_bodies_preserved': True,
 'new_test_names': names, 'mechanism_only': True,
 'Rust_or_QA_or_gate_execution': False, 'actual_cold_process_result': 'Unknown',
 'installation_recovery_scope': 'Same generation custody only; no automatic Source Create or Recover fallback'})
save('SOURCE_MAP.json', {r['path']: r['after']['git_blob'] for r in changes})
names = ['SOURCE_PACKET.json', 'SOURCE_DELTA.patch', 'SOURCE_REFERENCES.json', 'TEST_INVENTORY.json',
         'STATIC_REVIEW.json', 'SOURCE_MAP.json', 'REVIEW.md', 'freeze_cold_candidate.py']
names += ['after/' + r['path'] for r in changes]
rows = []
for name in names:
 raw = (ROOT / name).read_bytes()
 assert len(raw) <= 512000
 rows.append({'name': name, 'path': str(ROOT / name), **pin(raw), 'chars': len(raw.decode())})
save('ARCHIVE_INPUTS.json', rows)
print(json.dumps({'packet': packet_pin, 'changes': len(changes), 'new_Root_tests': packet['new_root_tests'],
                  'source_map': {r['path']: r['after']['git_blob'] for r in changes}}, indent=2))
