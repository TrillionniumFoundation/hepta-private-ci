#!/usr/bin/env python3
"""Deterministic candidate output reconstruction, never native execution proof."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
HERE = Path('/tmp/hepta-36fa-postformat-nonrust-v1')
VIEW = HERE / 'source_view'
sys.path.insert(0, str(VIEW / 'scripts'))

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def main():
    extractor = module('proposal_reconstruction_f868', OUT / 'extractor-v2.py')
    proof = module('proposal_reconstruction_original_proof', VIEW / 'scripts/verify_hepta_callers.py')
    plan_raw = (OUT / 'FENCE_MATRIX_V2.json').read_bytes()
    assert identity(plan_raw)['git_blob_sha'] == extractor.PLAN_BLOB
    plan = json.loads(plan_raw)
    cfg = json.loads((HERE / 'EXTRACTOR_CONTRACT_V5_PENDING_ROOT_REVIEW.json').read_bytes())
    raw_inventory = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json').read_bytes()
    assert identity(raw_inventory) == cfg['complete_source_inventory']
    manifest_raw = (VIEW / 'CALLERS.toml').read_bytes()
    assert identity(manifest_raw) == {k: plan['structural_callers'][k] for k in identity(manifest_raw)}
    data = proof.tomllib.loads(manifest_raw.decode())
    assert len(proof._boundary_rows(data)) == 569 and len(data['protected_file']) == 412
    assert proof._string_tuple(data, 'source_roots') == ('codex-rs',)
    assert proof._string_tuple(data, 'ignored_path_fragments') == ('/tests/', '/examples/', '_tests.rs')
    sources, masked, source_pins = {}, {}, {}
    for path in sorted({row['path'] for row in plan['rows']}):
        raw = (VIEW / path).read_bytes()
        assert identity(raw) == {k: cfg['formatted_source_pins'][path][k] for k in identity(raw)}
        source = raw.decode()
        code = proof._strip_cfg_test_items(proof._strip_rust_non_code(source))
        assert len(code) == len(source)
        sources[path], masked[path], source_pins[path] = source, code, identity(raw)
    proposals = []
    for row in plan['rows']:
        path = row['path']
        code, raw = masked[path], sources[path]
        item = {'id': row['id'], 'path': path, 'source': source_pins[path],
                'semantic_obligations': row['semantic_obligations'], 'scopes': []}
        if row['id'].startswith('existing-'):
            original_row = data['protected_file'][row['index']]
            assert original_row['path'] == path
            item['original_row_unchanged'] = original_row
            item['preserve_forbidden_exactly'] = original_row.get('forbidden', [])
        else:
            item['new_proposed_forbidden'] = row['proposed_forbidden']
        for selector in row['selectors']:
            selected = extractor.select_scope(proof, code, selector)
            start, end = selected['start'], selected['end']
            item['scopes'].append({'selector': selector, 'actual_span': selected,
                'actual_raw': raw[start:end], 'actual_masked': code[start:end],
                'marker_proposal': extractor.original_compatible_proposal(code, selected),
                'limits': 'Proposal only; preserve old constraints and independently review every transfer.'})
        proposals.append(item)
    literals = [{'path': spec['path'], **extractor.literal_span(
        proof, masked[spec['path']], sources[spec['path']], spec)} for spec in plan['critical_literals']]
    mounts = [{'parent': spec['parent'], **extractor.mount_span(
        proof, masked[spec['parent']], sources[spec['parent']], spec)} for spec in plan['module_mounts']]
    proposal = {'schema': extractor.SCHEMA + '.proposal', 'status': 'unapplied_proposal_requires_review',
        'source_inventory': identity(raw_inventory), 'source_identity': cfg['source_identity'],
        'source_pins': source_pins, 'rows': proposals, 'literals': literals, 'mounts': mounts,
        'original_validator_run': False, 'boundary_membership_run': False, 'source_closure_run': False}
    raw = (json.dumps(proposal, indent=2, sort_keys=True) + '\n').encode()
    with (OUT / 'PROPOSALS.candidate-reconstruction.json').open('xb') as out:
        out.write(raw)
    meta = {'format': 'hepta-postformat-proposal-candidate-reconstruction-v1',
        'status': 'candidate_only_waiting_actual_native_result_identity',
        'candidate_output': identity(raw), 'source_pins_verified': len(source_pins),
        'root_and_source_inventory_executed': False, 'native_job_replayed': False,
        'extractor_main_called': False, 'source_gate_executed': False,
        'source': 'All 46 actual SH73 capture bytes independently checked against full actual 3f28 inventory; exact successor f868 functions (only two PLAN constants differ) and original pinned masks only.',
        'recognition_condition': 'Only actual native normal-zero RESULT and exact original proposal bytes/SHA256/Git identity equality can recognize this candidate as recovered original output.'}
    with (OUT / 'PROPOSAL_CANDIDATE_RECONSTRUCTION.json').open('xb') as out:
        out.write((json.dumps(meta, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps(meta, sort_keys=True))

if __name__ == '__main__':
    main()
