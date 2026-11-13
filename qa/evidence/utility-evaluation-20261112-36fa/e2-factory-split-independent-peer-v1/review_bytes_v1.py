#!/usr/bin/env python3
"""Read fixed UTF-8/JSON bytes only; no project import, Rust, QA or live I/O."""
from pathlib import Path
import difflib
import hashlib
import json
import re

D = Path('/tmp/hepta-36fa-e2-factory-split-independent-peer-v1')
A = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/factory-split-layer-v1')
T = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/factory-test-refusal-increment-v1')
E = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
I = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
PREFIX = 'codex-rs/hepta-agentd/src/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read_json(path):
    return json.loads(path.read_bytes())

def check(value, label):
    if not value:
        raise AssertionError(label)

def store_new(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        check(path.read_bytes() == body, 'existing review artifact changed: ' + str(path))
    else:
        with path.open('xb') as f:
            f.write(body)

def expected_pin(path, expected):
    raw = path.read_bytes()
    check(pin(raw) == expected, 'full pin: ' + str(path))
    return raw

def diff(before, after, path):
    return ''.join(difflib.unified_diff((before or '').splitlines(True), after.splitlines(True),
        fromfile='a/' + path if before is not None else '/dev/null', tofile='b/' + path))

def original_ref(path, native_path):
    raw = path.read_bytes()
    actual = pin(raw)
    row = inventory[native_path]
    check(actual == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']},
          'actual inventory reference: ' + native_path)
    store_new(D / 'inputs' / ('ORIGINAL_' + Path(native_path).name), raw)
    return {'path': native_path, 'pin': actual, 'local_source': str(path),
            'baseline_identity_match': True, 'basis': 'captured actual b608 inventory; no new native read'}

def block(text, start, end):
    a = text.index(start)
    b = text.index(end, a) + len(end)
    return text[a:b]

inventory_raw = I.read_bytes()
check(pin(inventory_raw)['git_blob'] == '457adb9bf9ba3a844e9dfa149be49460bb306998', 'actual inventory identity')
inventory = {x['path']: x for x in json.loads(inventory_raw)['files']}
check(len(inventory) == 15243, 'actual inventory count')
m = read_json(A / 'MANIFEST.json')
packet_raw = expected_pin(A / 'SOURCE_PACKET.json', m['source_packet'])
check(m['source_packet']['git_blob'] == '62ad5a5363ca91c335f2d599128f763c355b33bf', 'fixed packet')
packet = json.loads(packet_raw)
for name, key in [('SOURCE_DELTA.patch', 'patch'), ('REVIEW.json', 'review'), ('INSERTION_INVERSE.json', 'inverse')]:
    expected_pin(A / name, m[key])
check(pin((A / 'MANIFEST.json').read_bytes())['git_blob'] == '7e8a5be256d8376cf1185f892c291af2718e4ed7', 'fixed manifest')

e1_raw = (E / 'assembled-source-v1/SOURCE_PACKET.json').read_bytes()
import_raw = (E / 'request-type-import-increment-v1/SOURCE_PACKET.json').read_bytes()
check(pin(e1_raw)['git_blob'] == '1ca7a06948fcae69bf7c8e4c7823627a872c0c62', 'E1 assembled pin')
check(pin(import_raw)['git_blob'] == '36cd9a693ce75070e1225a978575ca6dea5f72c2', 'E1 import pin')
previous = {x['path']: x['after'] for x in json.loads(e1_raw)['images']}
for image in json.loads(import_raw)['images']:
    check(previous[image['path']] == image['before'], 'E1 import exact predecessor')
    previous[image['path']] = image['after']

manifest_rows = {x['path']: x for x in m['entries']}
check(len(manifest_rows) == 10 and len(packet['entries']) == 10, '10 unique E2 images')
entries = {x['path']: x for x in packet['entries']}
proof_rows = []
insertion_rows = []
patch = ''
for row in packet['entries']:
    path = row['path']
    mr = manifest_rows[path]
    check(row['mode'] == mr['mode'] == '100644', 'mode')
    check(row['after'] == mr['after'] == pin(row['after_utf8'].encode()), 'after pin: ' + path)
    check(row['before'] == mr['before'], 'before manifest: ' + path)
    before = row['before_utf8']
    if before is None:
        check(row['before'] is None and path not in previous and path not in inventory, 'new path: ' + path)
        basis = 'new path absent from captured b608 and E1 predecessor'
    else:
        check(pin(before.encode()) == row['before'], 'before pin: ' + path)
        if path in previous:
            check(before == previous[path], 'E1 exact predecessor: ' + path)
            basis = 'E1 assembled + explicit 70-byte import increment'
        else:
            original = E / 'references' / path
            check(before.encode() == original.read_bytes(), 'original local full predecessor: ' + path)
            ir = inventory[path]
            check(row['before'] == {'bytes': ir['bytes'], 'sha256': ir['sha256'], 'git_blob': ir['working_blob']}, 'original actual pin')
            basis = 'captured actual b608 image'
        lines_a = before.splitlines(True)
        lines_b = row['after_utf8'].splitlines(True)
        ops = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False).get_opcodes()
        insertions = []
        reverse = lines_b[:]
        for tag, i, j, k, l in reversed(ops):
            if tag == 'equal':
                continue
            check(tag == 'insert' and i == j, 'old bytes changed: ' + path)
            added = ''.join(lines_b[k:l])
            insertions.insert(0, {'before_line': i + 1, 'after_line': k + 1,
                                  'bytes': len(added.encode()), 'text': added})
            del reverse[k:l]
        check(''.join(reverse) == before, 'full insertion inverse: ' + path)
        insertion_rows.append({'path': path, 'insertions': insertions, 'full_inverse_equal': True})
    patch += diff(before, row['after_utf8'], path)
    proof_rows.append({'path': path, 'mode': row['mode'], 'before': row['before'], 'after': row['after'], 'preimage_basis': basis})
    store_new(D / 'reviewed-source' / 'after' / path, row['after_utf8'].encode())
    if before is not None:
        store_new(D / 'reviewed-source' / 'before' / path, before.encode())
check(patch.encode() == (A / 'SOURCE_DELTA.patch').read_bytes(), 'complete patch regeneration')
check(len(insertion_rows) == 7, 'seven old insertion-only images')
check(sum(1 for x in packet['entries'] if x['before'] is None) == 3, 'two new production and one test')

refs = []
for name in ['neuron_generation_initial_root_task.rs', 'neuron_generation_initial_root_custody.rs',
             'neuron_generation_initial_bootstrap.rs', 'circuit_feature_current.rs',
             'circuit_feature_current_retirement.rs', 'circuit_task_source.rs']:
    refs.append(original_ref(E / 'references' / PREFIX / name, PREFIX + name))
refs.append(original_ref(Path('/tmp/hepta-36fa-e2-custody-transport-interface-review-v1/inputs/circuit_q24_task_profile.rs'), PREFIX + 'circuit_q24_task_profile.rs'))
for name in ['circuit_task_runtime.rs', 'circuit_task_source_journal.rs', 'circuit_task.rs']:
    refs.append(original_ref(D / 'inputs' / name, PREFIX + name))

old_factory = entries[PREFIX + 'neuron_generation_initial_root_task.rs']['before_utf8']
new_factory = entries[PREFIX + 'neuron_generation_initial_root_task_channel.rs']['after_utf8']
new_host = entries[PREFIX + 'authority_host_session_generation_root_task.rs']['after_utf8']
profile_old = block(old_factory, 'let profile = CircuitQ24TaskProfileV1 {', '            };')
profile_new = block(new_factory, 'let profile = CircuitQ24TaskProfileV1 {', '            };')
check(profile_old == profile_new, 'all original profile fields exact')
ready_lines = 'let task = (*ready).into_circuit_feature_task(inputs.definition, inputs.source)?;\n            let retirement = task.clone();'
check(ready_lines in old_factory and ready_lines in new_factory, 'original Ready and same-task clone exact')
check(new_factory.count('let runtime = circuit_q24_task_channel_v1(identity, profile)?;') == 1, 'single original factory call')
check('cell: runtime.cell(),\n                    source: runtime.source(),' in new_factory, 'actual factory outputs')
check('Err(error) => Err(OriginalRootInitialInstallationErrorV1 { operation, error })' in new_factory, 'original readback-only error')
apis = []
for name, text in [('neuron_generation_initial_root_task_channel.rs', new_factory), ('authority_host_session_generation_root_task.rs', new_host)]:
    for visibility, method in re.findall(r'\b(pub(?:\(crate\))?)\s+fn\s+(\w+)\s*(?:<|\()', text):
        apis.append({'path': PREFIX + name, 'visibility': visibility, 'name': method})
check(len(apis) == 5, 'five new methods')
check('pub(crate) fn into_original_root_task_channel' in new_factory, 'private concrete channel constructor')
check('pub struct PreparedRootHostCircuitTaskV1' in new_host and '#[derive(Clone' not in new_host, 'non-Clone holder')
struct_body = block(new_host, 'pub struct PreparedRootHostCircuitTaskV1', '\n}')
check(not re.search(r'^\s*pub\s+\w+\s*:', struct_body, re.M), 'holder fields private')
code_without_line_comments = '\n'.join(x for x in (new_factory + '\n' + new_host).splitlines() if not x.lstrip().startswith('//'))
check(not re.search(r'\b(?:AgentdConfig|AgentdState|AutomationStore)\b', code_without_line_comments), 'no Config/State/Store implementation dependency')
check('self.runtime.bootstrap.handle().pending_count()' in new_host, 'original counter only')
check(new_host.count('OriginalRootCircuitTaskCustodyV1::drain_completed_task(&self.custody)?;') == 1, 'single original drain')

tm = read_json(T / 'MANIFEST.json')
traw = expected_pin(T / 'SOURCE_PACKET.json', tm['packet'])
check(tm['packet']['git_blob'] == '12459a8255be0358c822a825d2445fa48828a7e1', 'fixed refusal increment')
expected_pin(T / 'SOURCE_DELTA.patch', tm['patch'])
tp = json.loads(traw)
if 'images' in tp:
    ti = tp['images'][0]
    tb, ta, test_path = ti['before'], ti['after'], ti['path']
else:
    ti = tp['entries'][0]
    tb, ta, test_path = ti['before_utf8'], ti['after_utf8'], ti['path']
check(tb == entries[test_path]['after_utf8'], 'test increment exact E2 predecessor')
check(pin(tb.encode()) == tm['entry']['before'] and pin(ta.encode()) == tm['entry']['after'], 'test increment full pins')
check(diff(tb, ta, test_path).encode() == (T / 'SOURCE_DELTA.patch').read_bytes(), 'test complete patch')
second = 'async fn root_host_task_factory_refusal_retains_only_the_same_operation()'
check(tb[tb.index(second):] == ta[ta.index(second):], 'second test unchanged')
check('Err(crate::AgentdError::Invalid(message)) if message == crate::CircuitTaskErrorV1::ReconciliationRequired.to_string()' in ta, 'exact original Source error')
check('unrelated error did not prove missing original Source completion' in ta, 'other errors reject')
check(ta.count('let cleanup = fixture.finish();\n    body?;\n    cleanup') == 2, 'both Result bodies attempt cleanup before propagation')
check(ta.count('#[tokio::test]') == 2 and ta.count('#[ignore = ') == 2, 'same two ignored mechanisms')
check(ta.count('read_original_root_task_generation(&task)? == published') == 2, 'actual generation read before and after refusal')
check('fixture.original.generation_bytes()? == journal' in ta, 'actual generation bytes after refusal')
store_new(D / 'reviewed-source' / 'test-increment' / test_path, ta.encode())

proof = {
    'format': 'hepta-e2-factory-split-independent-byte-proof-v1',
    'status': 'PURE_BYTE_CHECKS_COMPLETED_NO_PROJECT_EXECUTION',
    'publication': 'locally computed only; no Git write',
    'scope': {'rust_images': 10, 'old_insertion_only': 7, 'new_production': 2, 'new_tests': 1,
              'followup_test_images': 1, 'new_api_methods': 5, 'mechanism_test_methods': 2},
    'fixed_inputs': {'manifest': pin((A / 'MANIFEST.json').read_bytes()), 'packet': pin(packet_raw),
        'patch': pin((A / 'SOURCE_DELTA.patch').read_bytes()), 'E1': pin(e1_raw),
        'E1_import': pin(import_raw), 'test_followup': pin(traw), 'captured_actual_inventory': pin(inventory_raw)},
    'images': proof_rows, 'insertion_inverses': insertion_rows,
    'references': refs, 'new_methods': apis,
    'same_factory': {'original_ready_consumption_and_task_arc_clone_bytes_equal': True,
                     'entire_original_profile_literal_equal': True, 'profile_literal_pin': pin(profile_new.encode()),
                     'new_concrete_factory_calls': 1, 'runtime_cell_source_used': True},
    'test_finding': {'initial_test': entries[test_path]['after'], 'finding': 'any Err did not isolate missing Source request',
        'successor': tm['entry']['after'], 'successor_packet': tm['packet'], 'exact_original_error_and_post_refusal_reads': True,
        'second_test_body_unchanged': True, 'tests_executed': False},
    'execution': {'H': False, 'Rust': False, 'formatter': False, 'QA': False, 'collector': False,
                  'candidate_import': False, 'source_mutation': False, 'Git_write': False},
    'limitations': ['Text and full-byte checks are not a Rust type-check.',
                    'Original reference files are captured bytes, not new live native observations.',
                    'No IPC, AutomationStore loan, daemon startup, claim/ACK transport or useful task was executed.']
}
body = (json.dumps(proof, indent=2, ensure_ascii=False) + '\n').encode()
store_new(D / 'BYTE_PROOF.json', body)
print(json.dumps({'result': 'completed', 'proof': pin(body), 'scope': proof['scope']}, ensure_ascii=False))
