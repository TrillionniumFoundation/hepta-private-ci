from pathlib import Path
import ast
import io
import json
import tokenize

root = Path('/workspace/scratch/ce434f960ee9/learn-current-v2')
changes = json.loads(Path('/workspace/scratch/ce434f960ee9/root-guard-514-markers.json').read_text())
mapping = {}
for change in changes:
    mapping.setdefault(change['before'], set()).add(change['after'])
paths = [root / 'qa/b4-no-bypass' / name for name in (
    'test_original_next_use_command_source_closure.py',
    'test_original_selector_command_source_closure.py',
    'test_training_no_update_source_closure.py',
    'test_original_no_update_stage_source_closure.py',
)]
applied = []
ambiguous = []
for path in paths:
    source = path.read_text()
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    replacements = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.STRING:
            continue
        try:
            value = ast.literal_eval(token.string)
        except (SyntaxError, ValueError):
            continue
        if not isinstance(value, str) or value not in mapping:
            continue
        choices = mapping[value]
        if len(choices) != 1:
            ambiguous.append({'path': str(path.relative_to(root)), 'line': token.start[0], 'old': value, 'choices': sorted(choices)})
            continue
        updated = next(iter(choices))
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        replacements.append((start, end, json.dumps(updated)))
        applied.append({'path': str(path.relative_to(root)), 'line': token.start[0], 'old': value, 'new': updated})
    for start, end, value in reversed(replacements):
        source = source[:start] + value + source[end:]
    ast.parse(source)
    path.write_text(source)
Path('/workspace/scratch/ce434f960ee9/root-guard-514-qa-marker-map.json').write_text(json.dumps({'applied': applied, 'ambiguous': ambiguous}, indent=2) + '\n')
print(json.dumps({'applied': len(applied), 'ambiguous': ambiguous}, indent=2))
