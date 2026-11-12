from pathlib import Path
import copy
import difflib
import hashlib
import json
import tomllib

ROOT = Path(__file__).resolve().parent
PREFMT = ROOT.parent / 'recovery-b-panel-training-proof-57b-v2'
A = 'codex-rs/hepta-agentd/src/'
CHANGES = [
    (A + 'neuron_cell_evaluation_qualification_sources.rs',
     'self.prepare_with_training(config, started_at, &mut OriginalPanelTrainingReadV1::Individual)',
     'self.prepare_with_training(\n            config,\n            started_at,\n            &mut OriginalPanelTrainingReadV1::Individual,\n        )'),
    (A + 'neuron_cell_evaluation_panel.rs',
     'OriginalCellEvaluationPanelMemberOwnersV1::read_original(owner, task, clock, training)\n                    .await?',
     'OriginalCellEvaluationPanelMemberOwnersV1::read_original(\n                    owner, task, clock, training,\n                )\n                .await?'),
    (A + 'neuron_cell_evaluation_host.rs',
     'OriginalPanelTrainingSourceV1::call(&self.training_source, self.panel.retention.len() + 1)?',
     'OriginalPanelTrainingSourceV1::call(\n            &self.training_source,\n            self.panel.retention.len() + 1,\n        )?'),
    (A + 'neuron_cell_evaluation_host.rs',
     '&mut self.panel, super::original::now, training,',
     '&mut self.panel,\n            super::original::now,\n            training,'),
    (A + 'neuron_cell_evaluation_training_read_proof.rs',
     'Self::Individual => OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config).await',
     'Self::Individual => {\n                OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config).await\n            }'),
    (A + 'neuron_cell_evaluation_training_read_proof.rs',
     'OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config).await?',
     'OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config)\n                        .await?'),
]


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def replace_exact(value, before, after):
    count = 0
    if isinstance(value, str):
        count = value.count(before)
        return value.replace(before, after), count
    if isinstance(value, list):
        result = []
        for item in value:
            changed, used = replace_exact(item, before, after)
            result.append(changed)
            count += used
        return result, count
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            changed, used = replace_exact(item, before, after)
            result[key] = changed
            count += used
        return result, count
    return value, count


def scalar(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join(scalar(item) for item in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(key + ' = ' + scalar(item) for key, item in value.items()) + '}'
    raise TypeError(type(value))


manifest = tomllib.loads((PREFMT / 'guard-mirror/CALLERS.toml').read_text())
before_manifest = copy.deepcopy(manifest)
plan = json.loads((PREFMT / 'CALLERS-DELTA.prefmt.json').read_text())
before_plan = copy.deepcopy(plan)
applied = []
for path, before, after in CHANGES:
    actual = (ROOT / 'postimages' / path).read_text()
    assert before not in actual and after in actual, (path, before)
    uses = 0
    for index, row in enumerate(manifest['protected_file']):
        if row['path'] == path:
            changed, count = replace_exact(row, before, after)
            assert changed['forbidden'] == row['forbidden']
            manifest['protected_file'][index] = changed
            uses += count
    assert uses == 1, (path, before, uses)
    plan_uses = 0
    for item in plan['protected_row_replacements']:
        if item['path'] == path:
            item['after'], count = replace_exact(item['after'], before, after)
            plan_uses += count
    for index, row in enumerate(plan['new_protected_rows']):
        if row['path'] == path:
            plan['new_protected_rows'][index], count = replace_exact(row, before, after)
            plan_uses += count
    assert plan_uses == 1, (path, before, plan_uses)
    applied.append({'path': path, 'before': before, 'after': after,
                    'manifest_uses': uses, 'delta_after_uses': plan_uses})

assert manifest['boundary'] == before_manifest['boundary']
assert manifest['privileged_inventory'] == before_manifest['privileged_inventory']
assert [r['forbidden'] for r in manifest['protected_file']] == [r['forbidden'] for r in before_manifest['protected_file']]
assert [r['before'] for r in plan['protected_row_replacements']] == [r['before'] for r in before_plan['protected_row_replacements']]
assert plan['new_boundaries'] == before_plan['new_boundaries']
assert plan['boundary_changes'] == before_plan['boundary_changes']

qa_path = 'qa/b4-no-bypass/test_original_panel_training_transaction_source_closure.py'
qa_before = (PREFMT / 'work' / qa_path).read_text()
before, after = CHANGES[-1][1:]
# Both values occur as Python string literals; keep the literal escape spelling.
needle = repr(before)
replacement = repr(after)
assert qa_before.count(needle) == 1
qa_after = qa_before.replace(needle, replacement)
for destination in [ROOT / 'work' / qa_path, ROOT / 'guard-mirror' / qa_path]:
    destination.write_text(qa_after)

plan['actual_format'] = True
plan['actual_format_manifest'] = meta((ROOT / 'manifest.json').read_bytes())
plan['format_marker_adaptations'] = applied
plan['native_tests_run'] = False
plan['scope_note'] = 'Exact 57b before rows; six marker spelling changes follow verified Rust 1.96 formatting only. Existing baseline caller-gap fixes are separate and must be preserved during central merge.'
(ROOT / 'CALLERS-DELTA.actual.json').write_text(json.dumps(plan, indent=2) + '\n')
(ROOT / 'guard-mirror/CALLERS.toml').write_text(''.join(key + ' = ' + scalar(value) + '\n' for key, value in manifest.items()))
(ROOT / 'qa-format-only.patch').write_text(''.join(difflib.unified_diff(qa_before.splitlines(True), qa_after.splitlines(True), fromfile='a/' + qa_path, tofile='b/' + qa_path)))
(ROOT / 'FORMAT-MARKER-ADAPTATIONS.json').write_text(json.dumps({
    'source': '57b27c81d0d5321b873ee751fd0e58e1d905b988',
    'rust_files_edited_after_format': False,
    'scanner_edited': False,
    'all_forbidden_preserved': True,
    'all_boundary_callers_preserved': True,
    'marker_changes': applied,
    'qa_before': meta(qa_before.encode()),
    'qa_after': meta(qa_after.encode()),
}, indent=2) + '\n')
print(json.dumps({'marker_changes': len(applied), 'qa_string_changes': 1,
                  'delta': meta((ROOT / 'CALLERS-DELTA.actual.json').read_bytes()),
                  'qa': meta(qa_after.encode())}))
