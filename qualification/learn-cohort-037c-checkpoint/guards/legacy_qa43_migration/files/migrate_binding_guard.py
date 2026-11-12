"""Carry the old readonly host prohibitions to the extracted private binding."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
OVER = ROOT / 'overlay'
path = 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_binding.rs'
host = 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs'
manifest_path = OVER / 'CALLERS.toml'
original = manifest_path.read_text()
manifest = tomllib.loads(original)
before = next(row for row in manifest['protected_file'] if row['path'] == path)
legacy = next(row for row in manifest['protected_file'] if row['path'] == host)
after = copy.deepcopy(before)
after['forbidden'] += [item for item in legacy['forbidden'] if item not in after['forbidden']]
assert len(after['forbidden']) > len(before['forbidden'])
spec = importlib.util.spec_from_file_location('legacy_binding_proof', OVER / 'scripts/verify_hepta_callers.py')
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
source = (OVER / path).read_text()
attacks = [
    'fn illicit_key_slot(_: &ed25519_dalek::SigningKey) {}',
    'fn execute() {}',
    'fn serve_execute() {}',
    'fn create_evaluated() {}',
    'fn recover_evaluated() {}',
    'pub fn from_original_receipt_owner() {}',
    'pub(crate) fn evidence_response() {}',
]
results = []
for attack in attacks:
    record = {'attack': attack}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / path
        target.parent.mkdir(parents=True)
        target.write_text(source + '\n' + attack + '\n')
        for label, row in [('before', before), ('after', after)]:
            try:
                proof._verify_protected_files(root, {'protected_file': [row]})
                record[label] = 'accepted by this protected row'
            except proof.VerificationFailure as error:
                record[label] = 'rejected'
                record[label + '_error'] = str(error)
    assert record['before'] == 'accepted by this protected row'
    assert record['after'] == 'rejected'
    results.append(record)

blocks = list(re.finditer(r'(?m)^\[\[protected_file\]\]\n', original))
hits = []
for index, block in enumerate(blocks):
    end = blocks[index + 1].start() if index + 1 < len(blocks) else len(original)
    text = original[block.start():end]
    if re.search(r'(?m)^path = ' + re.escape(json.dumps(path)) + r'$', text):
        replacement, count = re.subn(
            r'(?m)^forbidden = .*$',
            'forbidden = ' + json.dumps(after['forbidden']), text,
        )
        assert count == 1
        hits.append((block.start(), end, replacement))
assert len(hits) == 1
start, end, replacement = hits[0]
changed = original[:start] + replacement + original[end:]
parsed = tomllib.loads(changed)
expected = copy.deepcopy(manifest)
expected['protected_file'][expected['protected_file'].index(before)] = after
assert parsed == expected
manifest_path.write_text(changed)
proof._verify_protected_files(OVER, {'protected_file': [after]})
delta = {
    'input_callers_sha256': hashlib.sha256(original.encode()).hexdigest(),
    'output_callers_sha256': hashlib.sha256(changed.encode()).hexdigest(),
    'protected_changes': [{'path': path, 'before': before, 'after': after}],
    'added_forbidden': [item for item in after['forbidden'] if item not in before['forbidden']],
    'all_other_registry_data_identical': True,
    'counts': [len(parsed['boundary']), len(parsed['protected_file'])],
    'qualification': 'One isolated protected-row migration; not a complete caller/source gate',
}
(ROOT / 'BINDING_FORBIDDEN_DELTA.json').write_text(json.dumps(delta, indent=2) + '\n')
(ROOT / 'evidence' / 'binding-forbidden-before-after.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps({'before_accepted_after_rejected': len(results), 'added_forbidden': delta['added_forbidden'], 'all_other_registry_data_identical': True}, indent=2))
