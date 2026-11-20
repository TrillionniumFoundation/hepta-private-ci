#!/usr/bin/env python3
"""Offline DATA equality only; no database, signature verification or authority call."""
from pathlib import Path
import hashlib
import json
import struct
import time

ROOT = Path('/workspace/scratch/e9e051ab0825')
OUT = ROOT / 'e6_noupdate12_finaluse_attribution_review_1'
SOURCE = 'dbd6a00992b60f4b33e8f10c2defda031d123bcb'
MAP = ROOT / 'e6_diagnostic_host_archive_readback_1/verification-1/PHYSICAL_RESTORE_MAP.json'
rows = json.loads(MAP.read_bytes())
by_name = {Path(r['workspace_relative_path']).name: r for r in rows}
consumed = []


def digest(data):
    return hashlib.sha256(data).hexdigest()


def gitblob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def write(name, data):
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('xb') as handle:
        handle.write(data)
    assert p.read_bytes() == data


def output(name, value):
    write(name, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def read(name):
    row = by_name[name]
    p = ROOT / row['workspace_relative_path']
    data = p.read_bytes()
    assert len(data) == row['bytes'] and digest(data) == row['sha256']
    assert '/final-use/' in row['original_path'] or '/authority/frontier-v1-' in row['original_path']
    write('primary/' + name, data)
    consumed.append({**row, 'copy': 'primary/' + name, 'git_blob': gitblob(data)})
    return data


def value(name):
    return json.loads(read(name))


def h(value):
    assert isinstance(value, list) and len(value) == 32
    return bytes(value).hex()


def main():
    started = time.monotonic()
    original_peer_manifest = ROOT / 'e6_noupdate12_training_business_physical_review_1/READOUT_MANIFEST.json'
    prior_sha = digest(original_peer_manifest.read_bytes())
    assert prior_sha == 'd21f91f9668243dbed3e367dd69cc3b1e0cefe6486f576bac41ce324f58c3bd4'
    a = value('0013__frontier-v1-0c65b63160e9e170f019c5408390d14a135edcb311c5fda0429484a7793f66c6.json')
    c_refusal = value('0023__frontier-v1-7cd1fffbd7092c2f4cd52c8e418a49275a9840cad53172f858e64c9643f6e1bd.json')
    c_grant = value('0041__frontier-v1-ddef6ff81d081320feb423a68e48f5465c29b336c205a3fc71bc5312dde16075.json')
    c = value('0043__frontier-v1-e44ed9a89da52dddab39f7ece2106db8a2851717c37ca6dfd2f113a6539467be.json')
    claim_bytes = read('0159__authority.claims')
    device = value('0160__authority.json')
    notes_bytes = read('0162__authority.claims')
    notes = value('0163__authority.json')
    assert len(claim_bytes) == 80 and len(notes_bytes) == 0
    claims = [{'offset': i, 'authority_epoch': struct.unpack('>Q', claim_bytes[i:i+8])[0], 'nonce': claim_bytes[i+8:i+40].hex()} for i in range(0, len(claim_bytes), 40)]
    assert len({r['nonce'] for r in claims}) == 2
    af = a['frontier']
    ar = af['observed']['current']['initial']['record']
    cf = c['frontier']
    cr = cf['published']
    initial = ar['signed']['grant']
    subsequent = cr['signed']['grant']
    assert [r['nonce'] for r in claims] == [h(initial['nonce']), h(subsequent['nonce'])]
    assert [r['authority_epoch'] for r in claims] == [initial['authority_epoch'], subsequent['authority_epoch']] == [1, 1]
    assert device == notes
    assert device['signer_id'] == initial['signer_id'] == subsequent['signer_id'] == 'ordinary-original-root'
    assert device['head']['authority_epoch'] == 1
    assert device['head']['revision'] == 1 and device['head']['revoked_grant_ids'] == []
    assert af['phase'] == 'finalized'
    assert af['original']['target'] == af['observed']['current']['current'] == ar['intent']['target']
    assert ar['intent']['target']['scope']['run_id'] == 'ordinary-original-a'
    assert ar['intent']['operation_id'] == 'ordinary-original-a-initial'
    assert initial['binding']['destination_id'] == 'agentd.cell-generation.initialize'
    assert cr['intent']['previous'] == ar['intent']['target']
    assert cr['intent']['target'] == cf['current']
    assert cr['intent']['target']['scope']['run_id'] == 'ordinary-original-c'
    assert cr['intent']['completion'] == 'owner_drained_same_model'
    assert subsequent['binding']['destination_id'] == 'agentd.cell-generation.next-task-same-model'
    assert c_grant['frontier']['state']['phase'] == 'issued'
    assert c_grant['frontier']['state']['signed'] == cr['signed']
    assert c_grant['frontier']['original']['original']['intent'] == cr['intent']
    assert c_refusal['frontier']['phase'] == 'ready'
    assert c_refusal['frontier']['publication']['current'] == cf
    assert c_refusal['frontier']['original']['original'] == c_grant['frontier']['original']['original']
    assert c_refusal['frontier']['publication']['accepted_revocations'] == device['head']
    extracted = []
    for claim, rec, grant, label in [(claims[0], ar, initial, 'A initialization'), (claims[1], cr, subsequent, 'A to C retained-model publication')]:
        witness = rec['witness']
        authority = witness['authority_ref']['authority']
        assert witness['authority_ref']['authority_family'] == 'final_use'
        assert authority['grant_id'] == grant['grant_id']
        assert authority['signer_id'] == grant['signer_id']
        assert authority['revocation_revision'] == device['head']['revision']
        assert witness['authority_epoch'] == grant['authority_epoch']
        assert witness['boundary'] == 'dispatch_entry'
        assert grant['binding']['subject_id'] == rec['intent']['target']['scope']['agent_id']
        assert grant['not_before_unix_ms'] <= witness['verified_at_unix_ms'] <= grant['expires_at_unix_ms']
        extracted.append({
            **claim, 'attribution': label, 'grant_id': grant['grant_id'], 'signer_id': grant['signer_id'],
            'destination_id': grant['binding']['destination_id'], 'operation_id': rec['intent']['operation_id'],
            'previous_run_id': rec['intent'].get('previous', {}).get('scope', {}).get('run_id'),
            'target_run_id': rec['intent']['target']['scope']['run_id'],
            'subject_id': grant['binding']['subject_id'],
            'request_sha256': h(grant['binding']['request_sha256']),
            'scope_sha256': h(grant['binding']['scope_sha256']),
            'payload_sha256': h(grant['binding']['payload_sha256']),
            'signed_grant_digest_retained': h(rec['signed_grant_digest']),
            'witness_binding_sha256_retained': h(authority['binding_sha256']),
            'not_before_unix_ms': grant['not_before_unix_ms'], 'expires_at_unix_ms': grant['expires_at_unix_ms'],
            'witness_verified_at_unix_ms': witness['verified_at_unix_ms'], 'witness_boundary': witness['boundary'],
        })
    source_root = ROOT / 'e6_noupdate12_training_business_physical_review_1'
    source_pins = json.loads((source_root / 'ADDITIONAL_SOURCE_PINS.json').read_bytes())
    pin = next(p for p in source_pins if p['repo_path'].endswith('/final_use_store.rs'))
    source_bytes = (source_root / 'source' / pin['repo_path']).read_bytes()
    assert digest(source_bytes) == pin['sha256'] and len(source_bytes) == pin['bytes'] and pin['actual_inventory_equal']
    assert b'const CLAIM_FRAME_BYTES: usize = 8 + 32;' in source_bytes
    assert b'file.write_all(&authority_epoch.to_be_bytes())' in source_bytes
    assert b'let epoch = u64::from_be_bytes(epoch_bytes);' in source_bytes
    write('source/final_use_store.rs', source_bytes)
    output('SOURCE_PIN.json', {'actual_source': SOURCE, **pin, 'copied_exact': True, 'scope': '40B claim layout only; no fresh signature or authority verifier'})
    output('ATTRIBUTION_READOUT.json', {
        'scope': 'Retained finite DATA attribution, not live FinalUse qualification',
        'actual_source': SOURCE, 'mapping_sha256': digest(MAP.read_bytes()),
        'device_claims_bytes': len(claim_bytes), 'notes_claims_bytes': len(notes_bytes),
        'claim_frames': extracted,
        'equality_checks': {
            'claim_epoch_nonce_matches_full_retained_grant': True,
            'A_initial_intent_target_matches_original_and_observed_current': True,
            'C_intent_previous_equals_A_target': True,
            'C_intent_target_equals_retained_current': True,
            'C_prepared_signed_grant_equals_published_signed_grant': True,
            'C_issued_prepared_intent_equals_published_intent': True,
            'C_accepted_publication_current_equals_owner_current': True,
            'grant_ids_signer_epoch_match_witness_and_device_head': True,
        },
        'C_publication_evidence': {'grant_phase': c_grant['frontier']['state']['phase'], 'refusal_phase': c_refusal['frontier']['phase'], 'refusal_attempt': c_refusal['frontier']['attempt'], 'publication_verified_at_unix_ms': c_refusal['frontier']['publication']['verified_at_unix_ms'], 'completion_label': cr['intent']['completion'], 'completion_label_applies_to_previous_A_owner': True, 'is_not_C_drain_completion': True},
        'limits': [
            'Epoch/nonce claim frames contain no task identity; attribution requires the separately retained signed-grant/intents and frontiers.',
            'Claims are durable nonce burns, not by themselves proof that a downstream effect completed.',
            'No fresh signature, live trust/revocation/currentness, grant verification or Rust observer was executed.',
            'Retained digest fields are cross-compared, not independently recalculated from signing/domain algorithms by this reader.',
            'No database, WAL or SHM was opened; the captured originals remain unchanged.',
            'No D/cold/Adopt/final-post-retirement acceptance or complete FinalUse qualification follows.',
            'Original NoUpdate12 remains FAIL at C Generation is_drained=false.',
        ],
        'consumed_inputs': consumed,
    })
    assert digest(original_peer_manifest.read_bytes()) == prior_sha
    for row in consumed:
        raw = (ROOT / row['workspace_relative_path']).read_bytes()
        assert len(raw) == row['bytes'] and digest(raw) == row['sha256']
    output('RESULT.json', {'status': 'RETAINED_DATA_ATTRIBUTION_PASS', 'successful': True, 'read_seconds': time.monotonic() - started, 'physical_inputs': len(consumed), 'physical_input_bytes': sum(r['bytes'] for r in consumed), 'claim_count': 2, 'attributed': ['A initialization', 'A to C retained-model publication'], 'new_native_model_host_signature_or_database_operations': 0, 'old_training_readout_manifest_unchanged': True, 'original_parent': 'FAIL', 'cold_D_Adopt_FinalUse_or_settlement_qualified': False})
    print(json.dumps({'status': 'RETAINED_DATA_ATTRIBUTION_PASS', 'claims': [{'run': r['target_run_id'], 'grant': r['grant_id'], 'destination': r['destination_id']} for r in extracted], 'physical_inputs': len(consumed)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
