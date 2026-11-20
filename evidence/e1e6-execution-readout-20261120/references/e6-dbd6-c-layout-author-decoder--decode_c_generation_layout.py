"""Cloud-only layout interpretation of retained dbd6 NoUpdate12 originals.

This does not invoke a Rust observer, verify a signature, reconnect an owner,
repair a witness, or grant execution/publication qualification.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path('/workspace/scratch/e9e051ab0825')
HERE = Path(__file__).resolve().parent
PHYSICAL = HERE / 'c-physical'
SOURCE = 'dbd6a00992b60f4b33e8f10c2defda031d123bcb'
INDEX_FILE = ROOT / 'e6_owner_work/initial_observation_diagnostic_candidate/rev1/EXPECTED_SOURCE_INVENTORY_RECONSTRUCTED.json'
INDEX = {row['path']: row for row in json.loads(INDEX_FILE.read_bytes())}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def compact(value):
    # Original target uses the declaration order of Serialize-derived structs.
    # The actual 32-byte on-disk guarded header independently checks this encoding.
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def digest(domain, value):
    return hashlib.sha256(domain + compact(value)).digest()


source_rows = []
for name in ['cell_generation_current.rs', 'cell_generation_journal.rs',
             'cell_generation_state.rs', 'cell_generation_observer.rs',
             'cell_generation_observation.rs', 'cell_generation_types.rs']:
    relative = 'codex-rs/hepta-neuron/src/' + name
    path = ROOT / 'e6_noupdate12_c_drain_review/source' / relative
    raw = path.read_bytes()
    assert sha(raw) == INDEX[relative]['sha256']
    source_rows.append(dict(path=relative, sha256=sha(raw), bytes=len(raw)))
for relative, path in [
    ('codex-rs/hepta-neuron/src/witness.rs', ROOT / 'e6_delivery_peer_review/witness.rs'),
    ('codex-rs/hepta-types/src/digest.rs', ROOT / 'e6_noupdate9_parent_read_review/support-source/codex-rs/hepta-types/src/digest.rs'),
    ('codex-rs/hepta-agentd/src/ordinary_q24_post_a_completed_data_tests.rs',
     ROOT / 'e6_noupdate12_c_drain_review/source/codex-rs/hepta-agentd/src/ordinary_q24_post_a_completed_data_tests.rs'),
]:
    raw = path.read_bytes()
    assert sha(raw) == INDEX[relative]['sha256']
    source_rows.append(dict(path=relative, sha256=sha(raw), bytes=len(raw)))

capture = json.loads((PHYSICAL / 'CAPTURED_INPUTS.json').read_bytes())
for row in capture:
    raw = (PHYSICAL / Path(row['captured_path']).name).read_bytes()
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256']

target = json.loads((PHYSICAL / 'post-a-data__c-target.json').read_bytes())
material = json.loads((PHYSICAL / 'post-a-data__original-publication-material.json').read_bytes())
assert target == material['target']
configuration = target['generation']
initial = configuration['initial']
journal = (PHYSICAL / 'post-a-data__c-generation.journal').read_bytes()
witness = (PHYSICAL / 'post-a-witnesses__c-generation.witness').read_bytes()
configuration_digest = digest(b'hepta.cell.generation-owner.v2\0', [configuration, target['journal_records']])
assert journal == b'HPTACG03' + configuration_digest
assert len(journal) == 40
manifest_digest = digest(b'hepta.cell.backend.v2\0', configuration['manifest'])
assert manifest_digest == bytes(initial['manifest_digest'])
assert manifest_digest == bytes(material['selection']['compatibility_digest'])
expected_witness_prefix = (b'HPTNWA01' + bytes(target['witness_scope'])
                           + bytes(target['witness_objective'])
                           + target['witness_generation'].to_bytes(8, 'big'))
assert witness == expected_witness_prefix + hashlib.sha256(expected_witness_prefix).digest()
assert len(witness) == 112

# With zero frames, original GenerationState::new supplies the actual initial
# snapshot, draining=false, pending=None, outbox=None. No reducer events run.
fields = [
    dict(assertion='generation.owner_binding() == binding', value=True,
         evidence='Guarded header matches the complete target configuration and original journal_records; target equals publication-material target.'),
    dict(assertion='generation.is_drained()', value=False,
         evidence='Zero journal frames; GenerationState::new sets draining=false and no Drain event exists.'),
    dict(assertion='observed.manifest_digest() == selected.manifest.digest()', value=True,
         evidence='Recomputed manifest digest equals initial.manifest_digest and the retained signed-selection DATA compatibility_digest; signature is not re-verified here.'),
    dict(assertion='observed.snapshot().revision == 0', value=initial['revision'] == 0,
         observed=initial['revision']),
    dict(assertion='observed.snapshot().prefix.is_empty()', value=initial['prefix'] == [],
         observed=initial['prefix']),
    dict(assertion='!observed.snapshot().stopped', value=initial['stopped'] is False,
         observed=initial['stopped']),
    dict(assertion='observed.pending_request_digest().is_none()', value=True,
         observed=None, evidence='Initial reducer pending=None; no frames.'),
    dict(assertion='observed.pending_output().is_none()', value=True,
         observed=None, evidence='Initial reducer outbox=None; no frames.'),
]
assert [row['assertion'] for row in fields if not row['value']] == ['generation.is_drained()']
readout = dict(
    schema='hepta-e6-noupdate12-c-generation-layout-readout-v1',
    source=SOURCE,
    status='PHYSICAL_LAYOUT_MATCHES_UNDRAINED_GENESIS',
    qualification='Offline byte/layout interpretation only; original whole parent remains FAIL.',
    capture_result_sha256=sha((PHYSICAL / 'RESULT.json').read_bytes()),
    capture_manifest_sha256=sha((PHYSICAL / 'CAPTURED_INPUTS.json').read_bytes()),
    source_inventory_file_sha256=sha(INDEX_FILE.read_bytes()),
    source_files=source_rows,
    physical_files=[{key: row[key] for key in ['path', 'captured_path', 'bytes', 'sha256']} for row in capture],
    original_guard='ordinary_q24_post_a_completed_data_tests.rs:225-234',
    guarded_header_matches_target=True,
    configuration_digest=configuration_digest.hex(),
    journal_bytes=len(journal), journal_event_frames=0,
    witness_bytes=len(witness), witness_records=0,
    witness_checksum_and_target_context_match=True,
    manifest_digest=manifest_digest.hex(),
    target_equals_publication_material_target=True,
    target_generation=initial['generation'], target_writer_epoch=initial['writer_epoch'],
    generation_reducer=dict(draining=False, pending=None, outbox=None, revision=initial['revision'],
                            prefix=initial['prefix'], stopped=initial['stopped']),
    eight_field_interpretation=fields,
    limitations=[
        'No new Rust observer, current/trust/clock verification, source opening, signature verification, or live owner operation was executed.',
        'The original Rust observer already returned before the observed parent assertion; the original && expression short-circuits at is_drained, so later fields were not separately reported by that execution.',
        'The manifest/selected equality here uses retained selection DATA plus exact hashing; no independent authority or signature acceptance is inferred.',
        'Individual files were captured with original stat/SHA preservation; this is not a simultaneous global snapshot.',
        'No inference event, Drain event, or witness anchor is present in these two captured generation files. This does not on its own prove the reason the production caller omitted drain.',
    ],
    new_native_or_model_runs=0,
    host_requests=0,
)
output = HERE / 'C_LAYOUT_READOUT.json'
assert not output.exists()
output.write_text(json.dumps(readout, indent=2) + '\n')
print(json.dumps(dict(status=readout['status'], bytes=output.stat().st_size,
                      sha256=sha(output.read_bytes()), failed_fields=[row['assertion'] for row in fields if not row['value']]), indent=2))
