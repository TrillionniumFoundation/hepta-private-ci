from pathlib import Path
import importlib.util
import json
import re
import sys
import tomllib

ROOT = Path("/workspace/scratch/ce434f960ee9/learn-current-v3")
spec = importlib.util.spec_from_file_location('root_format_guard', ROOT / 'scripts/verify_hepta_callers.py')
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)


OWNED_PATHS = set(["codex-rs/hepta-agentd/src/cell_q24_training_command_support_tests.rs","codex-rs/hepta-agentd/src/circuit_learning_retained_publication_support_tests.rs","codex-rs/hepta-agentd/src/circuit_retained_version_client.rs","codex-rs/hepta-agentd/src/circuit_retained_version_effect.rs","codex-rs/hepta-agentd/src/circuit_retained_version_host.rs","codex-rs/hepta-agentd/src/circuit_retained_version_issuer.rs","codex-rs/hepta-agentd/src/circuit_retained_version_issuer_host_tests.rs","codex-rs/hepta-agentd/src/circuit_retained_version_issuer_metadata_tests.rs","codex-rs/hepta-agentd/src/circuit_retained_version_issuer_support_tests.rs","codex-rs/hepta-agentd/src/circuit_retained_version_issuer_tests.rs","codex-rs/hepta-agentd/src/circuit_retained_version_material_support_tests.rs","codex-rs/hepta-agentd/src/circuit_retained_version_service.rs","codex-rs/hepta-agentd/src/circuit_retained_version_task_support_tests.rs","codex-rs/hepta-agentd/src/learning_iteration_evidence_client.rs","codex-rs/hepta-agentd/src/neuron_generation_update_initial_test_support.rs","codex-rs/hepta-agentd/src/root_issuer_client.rs","codex-rs/hepta-agentd/src/root_retained_version_issuer.rs"])

def owned(path):
    return path in OWNED_PATHS


def normalized(text):
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    positions = [i for rank, i in enumerate(positions) if not (
        text[i] == ',' and rank + 1 < len(positions) and text[positions[rank + 1]] in ')]}'
    )]
    return ''.join(text[i] for i in positions), positions


REVIEWED_ARM = ("RetainedVersionOriginV1::Recovered => RetainedVersionFinalUseOutcomeV1::Published as u8", "RetainedVersionOriginV1::Recovered => {\n                    RetainedVersionFinalUseOutcomeV1::Published as u8\n                }")

def equivalent(old, new):
    return (old, new) == REVIEWED_ARM or normalized(old)[0] == normalized(new)[0]

def actual_marker(source, marker, function=None, after=None, ordered=False):
    code = proof._strip_cfg_test_items(proof._strip_rust_non_code(source))
    start, end = 0, len(source)
    if function:
        start = code.index(function)
        end = proof._rust_item_end(code, start) + 1
    start = max(start, after or 0)
    body = source[start:end]
    if marker == REVIEWED_ARM[0]:
        updated = REVIEWED_ARM[1]
        assert function == 'fn new(' and updated in body
        return updated, start + body.index(updated) + len(updated)
    if not ordered and marker in body:
        return marker, start + body.index(marker) + len(marker)
    compact, positions = normalized(body)
    search, _ = normalized(marker)
    locations = [m.start() for m in re.finditer(re.escape(search), compact)]
    if ordered and locations:
        at = locations[0]
        result = body[positions[at]:positions[at + len(search) - 1] + 1]
        assert equivalent(marker, result)
        return result, start + positions[at + len(search) - 1] + 1
    candidates = {body[positions[at]:positions[at + len(search) - 1] + 1] for at in locations}
    if len(candidates) != 1:
        raise ValueError((function, marker, 'expected one exact replacement for all matching spans', sorted(candidates)))
    result = next(iter(candidates))
    assert equivalent(marker, result)
    at = locations[0]
    return result, start + positions[at + len(search) - 1] + 1


path = ROOT / 'CALLERS.toml'
text = path.read_text()
before = tomllib.loads(text)
blocks = list(re.finditer(r'(?ms)^\[\[protected_file\]\]\n.*?(?=^\[\[(?!protected_file\.)|\Z)', text))
changes = []
replacements = []
for block in blocks:
    raw = block[0]
    row = tomllib.loads(raw)['protected_file'][0]
    if not owned(row['path']):
        continue
    source = (ROOT / row['path']).read_text()
    assert not any(line.lstrip().startswith('#') for line in raw.splitlines()), row['path']
    updated_row = json.loads(json.dumps(row))
    groups = [(None, updated_row['required'], False)]
    groups.extend((None, sequence, True) for sequence in updated_row.get('required_order', []))
    for order in updated_row.get('required_function_order', []):
        groups.extend((order['function'], order[kind], kind == 'sequence') for kind in ('sequence', 'top_level', 'literal_calls') if kind in order)
    for function, markers, ordered in groups:
        cursor = None
        for index, marker in enumerate(markers):
            updated, end = actual_marker(source, marker, function, cursor, ordered)
            if ordered:
                cursor = end
            if marker != updated:
                changes.append({'path': row['path'], 'function': function, 'before': marker, 'after': updated})
                markers[index] = updated
    lines = ['[[protected_file]]']
    for key, value in updated_row.items():
        if key != 'required_function_order':
            lines.append(key + ' = ' + json.dumps(value, ensure_ascii=False))
    for order in updated_row.get('required_function_order', []):
        lines.extend(['', '[[protected_file.required_function_order]]'])
        lines.extend(key + ' = ' + json.dumps(value, ensure_ascii=False) for key, value in order.items())
    raw = '\n'.join(lines) + '\n\n'
    replacements.append((block.start(), block.end(), raw))
for start, end, raw in reversed(replacements):
    text = text[:start] + raw + text[end:]
after = tomllib.loads(text)
assert before.keys() == after.keys()
assert len(after['boundary']) == 483
assert len(after['protected_file']) == 373
for key in before:
    if key != 'protected_file':
        assert before[key] == after[key], key
assert len(before['protected_file']) == len(after['protected_file'])
for a, b in zip(before['protected_file'], after['protected_file']):
    assert a.keys() == b.keys()
    if not owned(a['path']):
        assert a == b
        continue
    for key in a:
        if key not in ('required', 'required_order', 'required_function_order'):
            assert a[key] == b[key]
    assert len(a['required']) == len(b['required'])
    pairs = list(zip(a['required'], b['required']))
    assert len(a.get('required_order', [])) == len(b.get('required_order', []))
    for old, new in zip(a.get('required_order', []), b.get('required_order', [])):
        assert len(old) == len(new)
        pairs.extend(zip(old, new))
    assert len(a.get('required_function_order', [])) == len(b.get('required_function_order', []))
    for old, new in zip(a.get('required_function_order', []), b.get('required_function_order', [])):
        assert old.keys() == new.keys()
        assert old['function'] == new['function']
        for key in old:
            if key != 'function':
                assert len(old[key]) == len(new[key])
                pairs.extend(zip(old[key], new[key]))
    for old, new in pairs:
        assert equivalent(old, new), (a['path'], old, new)
path.write_text(text)
Path('/workspace/scratch/ce434f960ee9/issuer-24057-guard-markers.json').write_text(json.dumps(changes, indent=2) + '\n')
errors = []
for row in after['protected_file']:
    if owned(row['path']):
        try:
            proof._verify_protected_files(ROOT, {'protected_file': [row]})
        except Exception as error:
            errors.append({'path': row['path'], 'error': str(error)})
print(json.dumps({'owned_rows': len(replacements), 'changed_markers': len(changes), 'errors': errors}, indent=2))
if errors:
    raise SystemExit(1)
