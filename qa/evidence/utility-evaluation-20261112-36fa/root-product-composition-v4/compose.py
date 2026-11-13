"""Pure byte composition of frozen review layers; no project code execution."""
import difflib
import hashlib
import json
from pathlib import Path

BASE = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
PREV = Path('/tmp/hepta-36fa-root-product-composition-v3')
OUT = Path('/tmp/hepta-36fa-root-product-composition-v4')
E1 = Path('/tmp/hepta-36fa-e1-source-candidate-v1')
E2 = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
E3 = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1')
KEYS = ('bytes', 'sha256', 'git_blob')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(path):
    return json.loads(path.read_bytes())

graph_raw = (BASE / 'PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(graph_raw)['git_blob'] == '7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base = {e['path']: {k: e[k] for k in KEYS} for e in json.loads(graph_raw)['files']}
current = base.copy()
known = {path: {p['git_blob']} for path, p in base.items()}
sources = {}
previous_raw = (PREV / 'PREQUALIFICATION_COMPOSITION_REVIEW.json').read_bytes()
assert pin(previous_raw)['git_blob'] == '0f4c064a865c44a648e8e8b6c3f6e0b5741ae744'
previous = json.loads(previous_raw)
for e in previous['files']:
    assert e['before'] == base.get(e['path'])
    raw = (PREV / 'after' / e['path']).read_bytes()
    assert pin(raw) == e['after']
    current[e['path']] = e['after']
    sources[e['path']] = raw
    known.setdefault(e['path'], set()).add(e['after']['git_blob'])
for e in read(E1 / 'MANIFEST.json')['files']:
    known.setdefault(e['path'], set()).add(e['after']['git_blob'])
for folder in [E2 / 'factory-split-layer-v1', E2 / 'factory-test-refusal-increment-v1',
               E2 / 'ipc-layer-v1', E2 / 'ipc-purpose-increment-v1',
               E2 / 'ordinary-handoff-layer-v1', E3 / 'root-service-layer-v1',
               E3 / 'late-enrollment-layer-v1', E3 / 'explicit-callers-increment-v1']:
    for e in read(folder / 'SOURCE_PACKET.json')['entries']:
        assert pin(e['after_utf8'].encode()) == e['after']
        known.setdefault(e['path'], set()).add(e['after']['git_blob'])

def replace_sequence(value, operations):
    original = value
    inverse = []
    for before, after in operations:
        assert before
        positions = [i for i in range(len(value)) if value.startswith(before, i)]
        if len(positions) != 1:
            positions = [i for i in positions if (i == 0 or value[i - 1] == '\n')
                         and (i + len(before) == len(value) or value[i + len(before)] == '\n')]
        assert len(positions) == 1, ('nonunique exact-line replacement', before[:100])
        at = positions[0]
        inverse.append((at, before, after))
        value = value[:at] + after + value[at + len(before):]
    undone = value
    for at, before, after in reversed(inverse):
        assert undone[at:at + len(after)] == after
        undone = undone[:at] + before + undone[at + len(after):]
    assert undone == original
    return value

def original_line_splices(before, after, operations):
    lines = before.splitlines(keepends=True)
    output = lines.copy()
    for op in reversed(operations):
        a, b = op['before_lines']
        assert ''.join(lines[a:b]) == op['old_utf8']
        output[a:b] = op['new_utf8'].splitlines(keepends=True)
    assert ''.join(output) == after
    reversed_lines = after.splitlines(keepends=True)
    for op in reversed(operations):
        a, b = op['after_lines']
        assert ''.join(reversed_lines[a:b]) == op['new_utf8']
        reversed_lines[a:b] = op['old_utf8'].splitlines(keepends=True)
    assert ''.join(reversed_lines) == before

coincident_insertions = []
explicit_integration_merges = []

def mapped_line_splices(before, value, operations, path):
    if before == value:
        lines = value.splitlines(keepends=True)
        for op in reversed(operations):
            a, b = op['before_lines']
            assert ''.join(lines[a:b]) == op['old_utf8']
            lines[a:b] = op['new_utf8'].splitlines(keepends=True)
        return ''.join(lines)
    left = before.splitlines(keepends=True)
    right = value.splitlines(keepends=True)
    mapping = difflib.SequenceMatcher(a=left, b=right, autojunk=False).get_opcodes()
    equal = [op for op in mapping if op[0] == 'equal']
    edits = []
    for op in operations:
        a, b = op['before_lines']
        candidates = {(c + a - x, c + b - x) for _, x, y, c, d in equal if x <= a <= b <= y}
        if a == b and len(candidates) == 2:
            prior = [(c, d) for kind, x, y, c, d in mapping if kind == 'insert' and x == y == a]
            assert len(prior) == 1 and candidates == {(prior[0][0], prior[0][0]), (prior[0][1], prior[0][1])}
            start = end = prior[0][1]
            coincident_insertions.append({'path': path, 'original_line_boundary': a,
                                          'order': 'prior layer insertion then later layer insertion',
                                          'prior_text': ''.join(right[prior[0][0]:prior[0][1]]),
                                          'later_text': op['new_utf8']})
        elif not candidates and path == 'codex-rs/hepta-agentd/src/production_launcher_inputs.rs' and op['old_utf8'] == 'const FLAGS: [&str; 19] = [\n' and op['new_utf8'] == 'const FLAGS: [&str; 20] = [\n':
            matches = [i for i, line in enumerate(right) if line == 'const FLAGS: [&str; 20] = [\n']
            assert len(matches) == 1
            start, end = matches[0], matches[0] + 1
            op = {**op, 'old_utf8': right[start], 'new_utf8': 'const FLAGS: [&str; 21] = [\n'}
            explicit_integration_merges.append({'path': path, 'base': 19, 'E3_after': 20, 'E2_after': 20,
                                               'combined': 21, 'reason': 'Two distinct inherited handoff flags are retained.'})
        else:
            assert len(candidates) == 1, ('ambiguous or overlapping original-line splice', path, a, b, sorted(candidates))
            start, end = candidates.pop()
        assert ''.join(right[start:end]) == op['old_utf8']
        edits.append((sum(map(len, right[:start])), sum(map(len, right[:end])), op))
    result = value
    inverse = []
    for start, end, op in sorted(edits, key=lambda x: x[0], reverse=True):
        assert result[start:end] == op['old_utf8']
        inverse.append((start, op['old_utf8'], op['new_utf8']))
        result = result[:start] + op['new_utf8'] + result[end:]
    undone = result
    for at, old, new in reversed(inverse):
        assert undone[at:at + len(new)] == new
        undone = undone[:at] + old + undone[at + len(new):]
    assert undone == value
    return result

specs = [
    (E2 / 'material-source-loan-layer-v1', '911e41dbd5bb0dbe2098fe84e50728a73c5b3757', 'group'),
    (E2 / 'bootstrap-receipt-tests-layer-v1', '3ce8abde6fd4ddb09d1b020d0be1eb004cabbc54', 'append'),
]

layers = []
for folder, expected, mode in specs:
    raw = (folder / 'SOURCE_PACKET.json').read_bytes()
    assert pin(raw)['git_blob'] == expected
    packet = json.loads(raw)
    ledger_name = 'EXACT_REPLACEMENTS.json' if mode == 'purpose' else 'EXACT_SOURCE_SPLICES.json'
    if mode == 'append':
        ledger = []
        for row in packet['entries']:
            if row['before'] is not None:
                assert row['after_utf8'].startswith(row['before_utf8'])
                assert row['after']['bytes'] - row['before']['bytes'] == 116
                ledger.append({'path': row['path'], 'before': row['before_utf8'], 'after': row['after_utf8']})
        ledger_raw = (json.dumps(ledger, sort_keys=True) + '\n').encode()
    else:
        ledger_raw = (folder / ledger_name).read_bytes()
        ledger = json.loads(ledger_raw)
    changed = []
    for e in packet['entries']:
        path = e['path']
        after = e['after_utf8']
        assert pin(after.encode()) == e['after']
        if e['before'] is None:
            assert path not in current and e.get('before_utf8') is None
            result = after
            merged = False
        else:
            before = e['before_utf8']
            assert pin(before.encode()) == e['before']
            assert e['before']['git_blob'] in known.get(path, set()), ('unknown ancestor', folder.name, path)
            value = sources.get(path, before.encode()).decode()
            assert pin(value.encode()) == current[path]
            rows = [row for row in ledger if row['path'] == path]
            assert rows, ('missing original splice', folder.name, path)
            if mode == 'lines':
                assert len(rows) == 1
                operations = rows[0]['operations']
                original_line_splices(before, after, operations)
                result = mapped_line_splices(before, value, operations, path)
            else:
                if mode in ('purpose', 'group'):
                    assert len(rows) == 1
                    operations = [(op['before'], op['after']) for op in rows[0]['replacements']]
                elif mode == 'explicit':
                    operations = [(op['before_text'], op['after_text']) for op in rows]
                else:
                    operations = [(op['before'], op['after']) for op in rows]
                assert replace_sequence(before, operations) == after
                left, right = before.splitlines(keepends=True), after.splitlines(keepends=True)
                minimal = [{'before_lines': [a, b], 'after_lines': [c, d],
                            'old_utf8': ''.join(left[a:b]), 'new_utf8': ''.join(right[c:d])}
                           for kind, a, b, c, d in difflib.SequenceMatcher(a=left, b=right, autojunk=False).get_opcodes()
                           if kind != 'equal']
                original_line_splices(before, after, minimal)
                result = mapped_line_splices(before, value, minimal, path)
            merged = value != before
        sources[path] = result.encode()
        current[path] = pin(sources[path])
        known.setdefault(path, set()).update([e['after']['git_blob'], current[path]['git_blob']])
        changed.append({'path': path, 'original_before': e['before'], 'layer_after': e['after'],
                        'composed_after': current[path], 'preserved_other_layer_splices': merged})
    layers.append({'layer': folder.name, 'packet': pin(raw), 'exact_splices': pin(ledger_raw),
                   'paths': len(changed), 'files': changed})

flag_source = sources['codex-rs/hepta-agentd/src/production_launcher_inputs.rs'].decode()
assert flag_source.count('const FLAGS: [&str; 21] = [\n') == 1
flag_body = flag_source.split('const FLAGS: [&str; 21] = [\n', 1)[1].split('];', 1)[0]
flag_names = [line.strip().rstrip(',') for line in flag_body.splitlines() if line.strip()]
assert len(flag_names) == len(set(flag_names)) == 21
assert '"--root-resident-learning-handoff-fd"' in flag_names
assert '"--root-original-task-handoff-fd"' in flag_names
assert len(explicit_integration_merges) == 0
new = sorted(set(current) - set(base))
modified = sorted(path for path in base if current[path] != base[path])
assert not set(base) - set(current)
assert set(sources) == set(new + modified)
report = {'format': 'hepta-root-partial-product-composition-v4',
          'source_base': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
          'previous_composition': pin(previous_raw), 'layers': layers,
          'files_before': len(base), 'files_after': len(current), 'changed_paths': len(sources),
          'new_files': len(new), 'modified_original_files': len(modified),
          'original_files_unchanged': len(base) - len(modified),
          'all_before_images_match_exact_known_layer_or_base': True,
          'all_original_splices_forward_and_inverse_equal': True,
          'all_composed_splices_preserve_unrelated_prior_bytes': True,
          'coincident_insertions_in_declared_layer_order': coincident_insertions,
          'explicit_integration_merges': explicit_integration_merges,
          'actual_distinct_launcher_flags': flag_names,
          'files': [{'path': p, 'before': base.get(p), 'after': current[p]} for p in sorted(sources)],
          'remaining': ['Root ordinary CLI typed loader and same-session Task/Material/V3 orchestration',
                        'Material process hookup and necessary mechanism tests', 'complete caller/protection/test registration',
                        'original formatting, compilation and qualification gates',
                        'real authorized A-independent B-C and actual daemon/Root process cold recovery'],
          'H_calls': 0, 'project_code_executed': False, 'source_Git_mutation': False,
          'qualification': False, 'real_qualified_chains': 0}
for path, raw in sources.items():
    output = OUT / 'after' / path
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(raw)
raw = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
with (OUT / 'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'review': pin(raw), 'paths': len(sources), 'new': len(new),
                  'modified': len(modified), 'files_after': len(current), 'qualification': False}))
