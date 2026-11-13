"""Pure byte composition of frozen review layers; no project code execution."""
import difflib
import hashlib
import json
from pathlib import Path

BASE = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
PREV = Path('/tmp/hepta-36fa-root-product-composition-v2')
OUT = Path('/tmp/hepta-36fa-root-product-composition-v3')
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
assert pin(previous_raw)['git_blob'] == '6685e7b5fe7ff2c52f50e9ce936967702838b195'
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
               E2 / 'ipc-layer-v1', E3 / 'root-service-layer-v1']:
    for e in read(folder / 'SOURCE_PACKET.json')['entries']:
        assert pin(e['after_utf8'].encode()) == e['after']
        known.setdefault(e['path'], set()).add(e['after']['git_blob'])

def replace_sequence(value, operations):
    original = value
    inverse = []
    for before, after in operations:
        assert before and value.count(before) == 1, ('nonunique replacement', before[:100])
        at = value.index(before)
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

def mapped_line_splices(before, value, operations):
    if before == value:
        lines = value.splitlines(keepends=True)
        for op in reversed(operations):
            a, b = op['before_lines']
            assert ''.join(lines[a:b]) == op['old_utf8']
            lines[a:b] = op['new_utf8'].splitlines(keepends=True)
        return ''.join(lines)
    left = before.splitlines(keepends=True)
    right = value.splitlines(keepends=True)
    equal = [op for op in difflib.SequenceMatcher(a=left, b=right, autojunk=False).get_opcodes() if op[0] == 'equal']
    edits = []
    for op in operations:
        a, b = op['before_lines']
        candidates = {(c + a - x, c + b - x) for _, x, y, c, d in equal if x <= a <= b <= y}
        assert len(candidates) == 1, ('ambiguous or overlapping original-line splice', a, b, sorted(candidates))
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
    (E2 / 'ipc-purpose-increment-v1', '69d6d5eda401ff59f7e89b1e659f77a431274248', 'purpose'),
    (E3 / 'late-enrollment-layer-v1', '388bfb3f3ab70e5f39d847c26d2d48daa2c7ead1', 'lines'),
    (E3 / 'explicit-callers-increment-v1', 'f1306c1243c83a758385cb592710e4fd30010a78', 'explicit'),
    (E2 / 'ordinary-handoff-layer-v1', '65e62f807885cd890d8fa9944c58e232dc55ae01', 'ordinary'),
]
layers = []
for folder, expected, mode in specs:
    raw = (folder / 'SOURCE_PACKET.json').read_bytes()
    assert pin(raw)['git_blob'] == expected
    packet = json.loads(raw)
    ledger_name = 'EXACT_REPLACEMENTS.json' if mode == 'purpose' else 'EXACT_SOURCE_SPLICES.json'
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
                result = mapped_line_splices(before, value, operations)
            else:
                if mode == 'purpose':
                    assert len(rows) == 1
                    operations = [(op['before'], op['after']) for op in rows[0]['replacements']]
                elif mode == 'explicit':
                    operations = [(op['before_text'], op['after_text']) for op in rows]
                else:
                    operations = [(op['before'], op['after']) for op in rows]
                assert replace_sequence(before, operations) == after
                result = replace_sequence(value, operations)
            merged = value != before
        sources[path] = result.encode()
        current[path] = pin(sources[path])
        known.setdefault(path, set()).update([e['after']['git_blob'], current[path]['git_blob']])
        changed.append({'path': path, 'original_before': e['before'], 'layer_after': e['after'],
                        'composed_after': current[path], 'preserved_other_layer_splices': merged})
    layers.append({'layer': folder.name, 'packet': pin(raw), 'exact_splices': pin(ledger_raw),
                   'paths': len(changed), 'files': changed})

new = sorted(set(current) - set(base))
modified = sorted(path for path in base if current[path] != base[path])
assert not set(base) - set(current)
assert set(sources) == set(new + modified)
report = {'format': 'hepta-root-partial-product-composition-v3',
          'source_base': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
          'previous_composition': pin(previous_raw), 'layers': layers,
          'files_before': len(base), 'files_after': len(current), 'changed_paths': len(sources),
          'new_files': len(new), 'modified_original_files': len(modified),
          'original_files_unchanged': len(base) - len(modified),
          'all_before_images_match_exact_known_layer_or_base': True,
          'all_original_splices_forward_and_inverse_equal': True,
          'all_composed_splices_preserve_unrelated_prior_bytes': True,
          'files': [{'path': p, 'before': base.get(p), 'after': current[p]} for p in sorted(sources)],
          'remaining': ['Root ordinary CLI typed loader', 'non-Root Material readonly Source loan',
                        'necessary mechanism tests', 'complete caller/protection/test registration',
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
