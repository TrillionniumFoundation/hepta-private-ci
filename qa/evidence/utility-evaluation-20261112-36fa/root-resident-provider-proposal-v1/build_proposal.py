"""Deterministic source proposal inventory; does not import/execute Rust or gates."""
from pathlib import Path
import base64
import difflib
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
CALLERS = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/proposal-after/CALLERS.toml')
SOURCE = {'head': 'cc57c7198db6293ccca562253c42fffbe2a04633', 'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e', 'status': ''}


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def put(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
    (ROOT / name).write_bytes(raw)
    return identity(raw)


def tree_hash(entries):
    root = {}
    for path, (mode, sha) in entries.items():
        node = root
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (mode, sha)
    trees = {}
    def encode(node, prefix):
        rows = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, sha = '40000', encode(value, prefix + name + '/')
                order = (name + '/').encode()
            else:
                mode, sha = value
                order = name.encode()
            rows.append((order, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(row[1] for row in sorted(rows))
        sha = hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        trees[prefix.rstrip('/')] = sha
        return sha
    return encode(root, ''), trees


def main():
    raw = BASE.read_bytes()
    assert identity(raw) == {'bytes': 5611184, 'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9', 'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}
    inventory = json.loads(raw)
    assert inventory['source'] == SOURCE
    rows = {r['path']: r for r in inventory['files']}
    refs = []
    for path in sorted((ROOT / 'before').rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT / 'before').as_posix()
        data = path.read_bytes()
        pin = identity(data)
        expected = rows[relative]
        assert (pin['bytes'], pin['sha256'], pin['git_blob']) == (expected['bytes'], expected['sha256'], expected['working_blob']), relative
        refs.append({'path': relative, **pin, 'source': SOURCE['head'], 'source_url': f'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{SOURCE["head"]}/{relative}'})
    put('SOURCE_REFERENCES.json', {'source': SOURCE, 'base_inventory': identity(raw), 'references': refs})

    changes = []
    patch = []
    additions = deletions = 0
    for path in sorted((ROOT / 'after').rglob('*.rs')):
        relative = path.relative_to(ROOT / 'after').as_posix()
        before_path = ROOT / 'before' / relative
        before = before_path.read_bytes() if before_path.exists() else b''
        after = path.read_bytes()
        assert after.endswith(b'\n') and not after.endswith(b'\n\n'), relative
        if before:
            assert rows[relative]['working_blob'] == identity(before)['git_blob']
            assert rows[relative]['index_mode'] == '100644'
        else:
            assert relative not in rows
        delta = list(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                    fromfile='a/' + relative if before else '/dev/null', tofile='b/' + relative))
        patch.extend(delta)
        additions += sum(line.startswith('+') and not line.startswith('+++') for line in delta)
        deletions += sum(line.startswith('-') and not line.startswith('---') for line in delta)
        changes.append({'path': relative, 'mode': '100644',
                        'before': identity(before) if before else None,
                        'after': identity(after),
                        'before_base64': base64.b64encode(before).decode() if before else None,
                        'after_base64': base64.b64encode(after).decode(),
                        'lines_before': len(before.splitlines()), 'lines_after': len(after.splitlines())})
    assert len(changes) == 8 and sum(c['before'] is None for c in changes) == 4
    assert deletions == 0

    removed = {
        'authority_host_learning_resident.rs': ['#[path = "authority_host_learning_candidate_service.rs"]\nmod candidate_service;\npub use candidate_service::RootResidentCandidateInputsV1;\npub use candidate_service::RootResidentCandidateServiceV1;\npub use candidate_service::RootResidentLearningConsumerV3;\n'],
        'root_production_handoff.rs': ['\n#[path = "root_candidate_stage_handoff.rs"]\nmod candidate_stages;\npub use candidate_stages::RootCandidateStageHandoffV1;\npub use candidate_stages::receive_root_candidate_stage_handoff;\npub use candidate_stages::send_root_candidate_stage_handoff;\n'],
        'cell_q24_candidate_stage_owners.rs': ['\n    /// Narrow the original command path to the already elapsed handoff end.\n    /// This consumes the bundle before Root can install its effect gate.\n    pub(crate) fn restrict_original_handoff_deadline(mut self, end: Instant) -> Result<Self, Error> {\n        self.end = self.end.min(end);\n        self.common.end = self.common.end.min(self.end);\n        self.require_live_deadline()?;\n        Ok(self)\n    }\n'],
        'lib.rs': ['#[cfg(target_os = "linux")]\npub use authority_host_service::resident::RootResidentCandidateInputsV1;\n#[cfg(target_os = "linux")]\npub use authority_host_service::resident::RootResidentCandidateServiceV1;\n#[cfg(target_os = "linux")]\npub use authority_host_service::resident::RootResidentLearningConsumerV3;\n', '#[cfg(target_os = "linux")]\npub use root_production_handoff::RootCandidateStageHandoffV1;\n#[cfg(target_os = "linux")]\npub use root_production_handoff::receive_root_candidate_stage_handoff;\n#[cfg(target_os = "linux")]\npub use root_production_handoff::send_root_candidate_stage_handoff;\n']}
    inverse = []
    for name, blocks in removed.items():
        relative = 'codex-rs/hepta-agentd/src/' + name
        text = (ROOT / 'after' / relative).read_text()
        for block in blocks:
            assert text.count(block) == 1, name
            text = text.replace(block, '', 1)
        assert text.encode() == (ROOT / 'before' / relative).read_bytes(), name
        inverse.append({'path': relative, 'complete_inverse_bytes_equal': True, 'inserted_blocks': len(blocks)})

    old = {p: (r['index_mode'], r['index_blob']) for p, r in rows.items()}
    old_root, old_trees = tree_hash(old)
    assert old_root == SOURCE['tree'] and len(old) == 15188
    candidate = dict(old)
    for change in changes:
        candidate[change['path']] = (change['mode'], change['after']['git_blob'])
    candidate_root, new_trees = tree_hash(candidate)
    assert len(candidate) == 15192
    changed_trees = [{'path': key, 'before': old_trees.get(key), 'after': value}
                     for key, value in sorted(new_trees.items()) if value != old_trees.get(key)]

    import tomllib
    callers_bytes = CALLERS.read_bytes()
    assert identity(callers_bytes)['git_blob'] == rows['CALLERS.toml']['working_blob']
    callers = tomllib.loads(callers_bytes.decode())
    path = 'codex-rs/hepta-agentd/src/authority_host_learning_candidate_service.rs'
    edge_rows = []
    for position in (403, 404, 429, 430, 434):
        row = callers['boundary'][position]
        assert row['product_callers'] == []
        edge_rows.append({'zero_based_position': position, 'original_complete_row': row,
                         'proposed_real_product_callers': [path], 'change_implemented_in_callers': False})
    registration = {
        'status': 'PLANNED_ONLY_WAITING_ORIGINAL_FORMAT_AND_COMPLETE_COLLECTOR',
        'source': SOURCE, 'callers_original': identity(callers_bytes),
        'original_boundary_count': len(callers['boundary']), 'original_protected_count': len(callers['protected_file']),
        'existing_edges': edge_rows,
        'new_entries_requiring_fences': [
            'send_root_candidate_stage_handoff', 'receive_root_candidate_stage_handoff',
            'RootCandidateStageHandoffV1::into_original_streams',
            'OriginalCellQ24CandidateStageOwnersV1::restrict_original_handoff_deadline',
            'RootResidentLearningRegistrationV3::into_candidate_service',
            'RootResidentCandidateServiceV1::run'],
        'required_new_protection': [
            'separate purpose, fixed 21-right order, exact role names and distinct socket identity',
            'root_pair and actual sender pidfd plus actual recipient PID/boot/start binding',
            'trusted independent profile and typed materials; no wire origin or owner/grant constructors',
            'absolute monotonic end, remaining lifetime, timeout bounds and consuming min-only deadline cap',
            'registration Check before and after original role admission; private readonly fresh/recovery dispatch',
            'by-value registration/handoff/stages; no Clone/getter/reconnect or returned stage owner',
            'A EOF does not cancel Root; Root cancellation/finite end cancels and closes only owned work',
            'original four disposition semantics, old protocols, budgets, assertions and exact caller sets retained'],
        'no_final_literal_markers_before_actual_formatter': True,
        'full_original_source_collection_required': True,
        'authority_granted': False,
    }
    put('STRUCTURAL_REGISTRATION_PLAN.json', registration)
    patch_raw = ''.join(patch).encode()
    (ROOT / 'changes.patch').write_bytes(patch_raw)
    packet = {'format': 'hepta-original-root-provider-source-proposal-v1',
              'status': 'PREPARED_UNFORMATTED_NOT_COMPILED_NOT_RUN', 'source': SOURCE,
              'base_inventory': identity(raw), 'expected_candidate_tree': candidate_root,
              'expected_candidate_leaf_count': len(candidate), 'changes': changes}
    packet_raw = (json.dumps(packet, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
    (ROOT / 'SOURCE_PACKET.json').write_bytes(packet_raw)
    tests = re.findall(r'^fn (candidate_\w+)\(', (ROOT / 'after/codex-rs/hepta-agentd/src/root_candidate_stage_handoff_tests.rs').read_text(), re.M)
    assert len(tests) == 4
    static = {'format': 'hepta-original-root-provider-static-byte-review-v1', 'source': SOURCE,
              'before_reference_files_verified': len(refs), 'changed_files': len(changes),
              'new_files': 4, 'existing_files': 4, 'added_lines': additions, 'deleted_lines': deletions,
              'old_function_bodies_and_unrelated_file_bytes_preserved_by_exact_inverse': inverse,
              'old_base_merkle_recomputed': old_root, 'expected_preformat_candidate_tree': candidate_root,
              'candidate_leaf_count': len(candidate), 'changed_trees': changed_trees,
              'prepared_test_methods': tests, 'tests_executed': 0, 'rust_compile_executed': False,
              'formatter_executed': False, 'source_gate_executed': False, 'H_calls': 0,
              'real_task_chains': 0, 'source_or_ref_activated': False}
    put('STATIC_BYTE_REVIEW.json', static)
    artifacts = []
    for name in ('SOURCE_PACKET.json', 'changes.patch', 'SOURCE_REFERENCES.json', 'STATIC_BYTE_REVIEW.json', 'STRUCTURAL_REGISTRATION_PLAN.json', 'README.md', 'VALIDATION_DESIGN.md', 'build_proposal.py'):
        artifacts.append({'path': name, **identity((ROOT / name).read_bytes())})
    manifest = {'format': 'hepta-original-root-provider-proposal-manifest-v1',
                'status': 'HOLD_PENDING_PEER_FORMAT_COMPILE_INTEGRATION_AND_ORIGINAL_GATES',
                'source': SOURCE, 'expected_preformat_candidate_tree': candidate_root,
                'expected_candidate_leaf_count': len(candidate), 'source_changes': [
                    {k:v for k,v in change.items() if not k.endswith('_base64')} for change in changes],
                'artifacts': artifacts, 'runtime_or_qualification_claims': [],
                'mechanism_tests_executed': 0, 'real_task_chains': 0,
                'remaining_external_inputs': [
                    'actual completed A and original Root execution/readback intent with exact registered lease',
                    'ten distinct original Root-targeted stream/pidfd pairs and their real process metadata',
                    'independently trusted original material/protocol/loaded-model/verifier objects',
                    'actual A/successor Root client peer and legal late-enrollment host integration',
                    'independent B/retention outcomes, accessible licensed model material and full frozen cost ledger',
                    'actual new C consumption, daemon and Root cold-recovery observations'],
                'remaining_engineering': [
                    'independent source/authority peer review',
                    'original scoped formatter/compile and exact postformat CALLERS/protected/QA/allowlist integration',
                    'real original-owner service integration cases from VALIDATION_DESIGN, without canned role results',
                    'all unchanged original qualification gates on the new exact published source'],
                'storage': 'Git-backed repository proposal; no Library duplicate or active source write'}
    put('MANIFEST.json', manifest)
    print(json.dumps({'packet': identity(packet_raw), 'manifest': identity((ROOT/'MANIFEST.json').read_bytes()),
                      'candidate_tree':candidate_root,'lines_added':additions,'source_count':len(changes),
                      'new_source_count':4,'static_only':True}, sort_keys=True))


if __name__ == '__main__':
    main()
