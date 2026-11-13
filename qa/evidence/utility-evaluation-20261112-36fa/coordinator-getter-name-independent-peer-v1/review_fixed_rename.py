"""Pure byte review of two new getter names; does not invoke repo code."""
import base64
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1/SOURCE_PACKET.json')
PACKET = Path('/tmp/hepta-36fa-coordinator-original-metadata-getters-v1/SOURCE_PACKET.json')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    parent_raw, packet_raw = PARENT.read_bytes(), PACKET.read_bytes()
    assert pin(parent_raw)['git_blob'] == '773d67128190fd2e1c3271c372f72e2a5537d1e8'
    assert pin(packet_raw)['git_blob'] == '5279a43b99aa7031343578a21dba895f5eac3188'
    parent, packet = json.loads(parent_raw), json.loads(packet_raw)
    parents = {r['path']: r for r in parent['source_changes']}
    root = 'codex-rs/hepta-agentd/src/'
    replacements = {
        root + 'neuron_generation_initial_root_custody.rs': [
            ('pub fn final_use_binding(', 'pub fn original_final_use_binding(', 1),
            ('pub fn intent_digest(', 'pub fn original_intent_digest(', 1)],
        root + 'neuron_generation_initial_root_custody_support_tests.rs': [
            ('custody.final_use_binding()', 'custody.original_final_use_binding()', 1)],
        root + 'neuron_generation_initial_root_cold_tests.rs': [
            ('old.intent_digest()', 'old.original_intent_digest()', 4),
            ('old.final_use_binding()', 'old.original_final_use_binding()', 1),
            ('recovered.final_use_binding()', 'recovered.original_final_use_binding()', 1)]}
    assert {r['path'] for r in packet['source_changes']} == set(replacements)
    rows = []
    for change in packet['source_changes']:
        path = change['path']
        before, after = (base64.b64decode(change[k + '_base64'], validate=True) for k in ['before', 'after'])
        assert pin(before) == change['before'] and pin(after) == change['after']
        assert change['mode'] == parents[path]['mode']
        assert before == base64.b64decode(parents[path]['after_base64'], validate=True)
        forward = before.decode()
        details = []
        for old, new, count in replacements[path]:
            assert forward.count(old) == count and forward.count(new) == 0
            forward = forward.replace(old, new)
            details.append({'before': old, 'after': new, 'occurrences': count})
        assert forward.encode() == after
        reverse = after.decode()
        for old, new, count in replacements[path]:
            assert reverse.count(new) == count
            reverse = reverse.replace(new, old)
        assert reverse.encode() == before
        rows.append({'path': path, 'before': pin(before), 'after': pin(after),
                     'full_preimage_matches_773d': True, 'exact_forward_and_inverse': True,
                     'replacements': details})
    core = next(r for r in packet['source_changes'] if r['path'].endswith('root_custody.rs'))
    core_text = base64.b64decode(core['after_base64'], validate=True).decode()
    exact_methods = [
        'pub fn original_final_use_binding(&self) -> &FinalUseBinding {\n        &self.operation.binding\n    }',
        'pub fn original_intent_digest(&self) -> Digest32 {\n        self.operation.recovery.intent_digest\n    }']
    assert all(core_text.count(method) == 1 for method in exact_methods)
    unaffected = [
        {'path': path, 'after': row['after']}
        for path, row in parents.items() if path not in replacements]
    assert len(unaffected) == 6
    output = {
        'format': 'hepta-coordinator-new-getter-name-byte-review-v1',
        'parent_packet': pin(parent_raw), 'new_packet': pin(packet_raw),
        'rows': rows, 'definition_name_changes': 2, 'mechanism_call_site_changes': 7,
        'all_other_bytes_unchanged_in_three_files': True,
        'unchanged_other_six_rebased_paths': unaffected,
        'read_only_method_bodies': exact_methods,
        'scope': 'Only the packet layer was examined. No QA, verifier, collector, compiler, formatter, H job, source write, ref update or getter call was executed.',
        'semantic_boundaries': [
            'The first accessor still borrows the same protected operation FinalUseBinding and the second still returns the same intent Digest32. Neither constructs, signs, dispatches, publishes or recovers authority.',
            'All Prepared consumption, original operation binding/readback, Ready transition, same-Arc task installation/drain, cleanup and deadline code is byte-identical after inverse name substitution.',
            'The original initial production module and the new cold-recovery production module are absent from this delta. This selected layer does not apply the alternative UFCS edits.',
            'The new names still require exact boundary/caller registration. A local name disambiguation does not establish a complete repository caller scan or compilation.',
            'Prior lifecycle limits remain: a five-second cleanup timeout is terminal Unknown and Drop cancellation is not join evidence; reopened protected Current/journal tests are not a real process cold-restart observation.'
        ]}
    raw = (json.dumps(output, sort_keys=True, indent=2) + '\n').encode()
    with (HERE / 'FROZEN_RENAME_PROOF.json').open('xb') as f:
        f.write(raw)
    print(json.dumps({'report': pin(raw), 'source_paths': len(rows),
                      'definition_names': 2, 'fixture_call_sites': 7}))


if __name__ == '__main__':
    main()
