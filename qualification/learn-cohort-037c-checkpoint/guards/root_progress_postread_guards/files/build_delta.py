"""Compose isolated Root progress/postread rows; never edit a central registry."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OVERLAY = HERE / 'overlay'
AGENT = 'codex-rs/hepta-agentd/src/'
BASE_TEXT = (HERE / 'base/CALLERS.toml').read_text()
BASE = tomllib.loads(BASE_TEXT)
AFTER = deepcopy(BASE)
spec = importlib.util.spec_from_file_location('root_progress_postread_guard', OVERLAY / 'scripts/verify_hepta_callers.py')
assert spec and spec.loader
PROOF = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = PROOF
spec.loader.exec_module(PROOF)
CHANGED = {}

def row(name):
    path = AGENT + name + '.rs'
    result = next(item for item in AFTER['protected_file'] if item['path'] == path)
    CHANGED[path] = result
    return result

def function(item, name):
    return next(entry for entry in item['required_function_order'] if entry['function'] == 'fn ' + name + '(')

def code(name):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((OVERLAY / AGENT / (name + '.rs')).read_text()))

def item_code(name, marker, start=0):
    text = code(name)
    point = text.index(marker, start)
    end = PROOF._rust_item_end(text, point)
    assert end is not None
    return text[point:end + 1]

def order(item, name, sequence, top=()):
    new = {'function': 'fn ' + name + '(', 'sequence': list(sequence), 'top_level': list(top)}
    item.setdefault('required_function_order', []).append(new)
    return new

EVALUATION_NAME = 'cell_q24_candidate_stage_evaluation'
MAIN_NAME = 'cell_q24_candidate_stage_retention'
S_NAME = 'cell_q24_candidate_stage_retention_selection'
evaluation = row(EVALUATION_NAME)
main = row(MAIN_NAME)
selection = row(S_NAME)

# All old Evaluation checks remain in their original sequence. Only projection
# of the private result changes; the actual I/O body is unchanged.
execute = function(evaluation, 'execute_original_evaluation')
assert execute['sequence'][-1] == 'Ok(original.receipt().clone())'
execute['sequence'][-1] = 'Ok(original.evaluation.receipt().clone())'
readback = function(evaluation, 'read_original_evaluation')
readback['sequence'] = ['snapshot: &LearningIterationSnapshotV1',
                       'Ok(self', '.read_original_evaluation_with_originals(snapshot)', '.await?', '.evaluation)']
readback['top_level'] = ['Ok(self']
order(evaluation, 'read_original_evaluation_with_originals',
      ['snapshot: &LearningIterationSnapshotV1', 'Result<PostEvaluationOriginals, Error>',
       'self.original_evaluation(snapshot, Action::Readback).await'],
      ['self.original_evaluation(snapshot, Action::Readback).await'])
order(evaluation, 'into_parts', ['self,', 'OriginalCellQ24MaterialCommandReceiptV1',
      'OriginalCellQ24TrainingCommandReceiptV1', 'OriginalCellEvaluationCommandReceiptV1',
      '(self.dataset, self.training, self.evaluation)'],
      ['(self.dataset, self.training, self.evaluation)'])
original = function(evaluation, 'original_evaluation')
at = original['sequence'].index('lane.retained = Some(original.clone())')
original['sequence'][at:at] = ['let post = PostEvaluationOriginals {',
    'dataset: common.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone()',
    'training: current_training.clone()', 'evaluation: original.clone()']
assert original['sequence'][-1] == 'Ok(original)'
original['sequence'][-1] = 'Ok(post)'
original['top_level'] = ['let started_at =', 'lane.failed = true',
    'auth::verify_prefix(&self.common.material, &training_cut, &common, fresh)?',
    'self.verify_original_evaluation(snapshot, &training_cut, &training, &original, fresh)?',
    'let post = PostEvaluationOriginals {', 'lane.retained = Some(original.clone())',
    'lane.failed = false', 'Ok(post)']
text = code(EVALUATION_NAME)
start = text.index('enum Action {')
end = PROOF._rust_item_end(text, text.index('pub(super) struct PostEvaluationOriginals {'))
evaluation.setdefault('required_order', []).append([text[start:end + 1], 'impl PostEvaluationOriginals {'])
evaluation['required_order'].append([item_code(EVALUATION_NAME, 'impl PostEvaluationOriginals {'),
                                     'impl OriginalCellQ24CandidateStageOwnersV1 {'])
evaluation['required_order'].append([item_code(EVALUATION_NAME, 'pub(super) struct EvaluationLane {'),
                                     'impl EvaluationLane {'])
evaluation['required_order'].append(['pub(super) async fn read_original_evaluation_with_originals(',
                                     'snapshot: &LearningIterationSnapshotV1',
                                     'Result<PostEvaluationOriginals, Error>'])
evaluation['forbidden'] += ['pub struct PostEvaluationOriginals', 'pub(crate) struct PostEvaluationOriginals',
    'impl Clone for PostEvaluationOriginals', 'impl Copy for PostEvaluationOriginals',
    'impl Default for PostEvaluationOriginals', 'Deserialize',
    'pub async fn read_original_evaluation_with_originals(',
    'pub(crate) async fn read_original_evaluation_with_originals(',
    'pub fn into_parts(', 'pub(crate) fn into_parts(',
    'Option<PostEvaluationOriginals>', 'Mutex<PostEvaluationOriginals>',
    'OnceLock', 'LazyLock', 'thread_local!', 'static '] 
for helper in ('new', 'evaluation_failure'):
    full = item_code(EVALUATION_NAME, 'fn ' + helper + '(')
    opening = full.index('{')
    parameter = ('initial: OriginalCellEvaluationCommandConnectionV1' if helper == 'new'
                 else 'error: OriginalCellEvaluationCommandErrorV1')
    order(evaluation, helper, [parameter, full[opening:]],
          ['Self {\n            initial: Some(initial),'] if helper == 'new' else ['match error'])

pred = function(main, 'evaluated_predecessors')
pred['sequence'] = ['let (dataset, training, evaluation) = self',
    '.read_original_evaluation_with_originals(four_cut)', '.await?', '.into_parts()',
    'self.training_prefix(four_cut)?', 'self.common.continuation.try_lock()',
    'common.original_dataset.as_ref() != Some(&dataset)',
    'common.original_training.as_ref() != Some(&training)', 'return Err(Error::CommitUncertain)',
    'evaluation.snapshot() != four_cut', 'evaluation.training_attestation() != training.attestation()',
    'common_auth::require_material(&self.common.material, self.common.initial_binding)?',
    'common_auth::verify_prefix(&self.common.material, &training_cut, &common, fresh)?',
    'self.verify_original_evaluation(four_cut, &training_cut, &training, &evaluation, fresh)?',
    'self.require_live_deadline()?', 'Ok(Predecessors {']
pred['top_level'] = ['let (dataset, training, evaluation) = self',
    'if common.original_dataset.as_ref() != Some(&dataset)', 'if evaluation.snapshot()',
    'common_auth::verify_prefix(', 'self.verify_original_evaluation(', 'Ok(Predecessors {']
main['forbidden'] += ['PostEvaluationOriginals {', 'Option<PostEvaluationOriginals>',
                      'Mutex<PostEvaluationOriginals>', 'pub fn evaluated_predecessors(',
                      'pub(crate) fn evaluated_predecessors(']

# Pin the entire real polling loop. Pending and Busy cannot reach publication;
# Available contains one complete read on the same channel and a final Root
# check. No nested closure can leave matching branches unexecuted.
prepare = function(selection, 'prepare_evaluated_version')
old_loop = prepare['sequence'].index('loop {')
prepare['sequence'] = prepare['sequence'][:old_loop]
loop = item_code(S_NAME, 'loop {', code(S_NAME).index('fn prepare_evaluated_version('))
prepare['sequence'].append(loop)
prepare_code = code(S_NAME)
prepare_start = prepare_code.index('fn prepare_evaluated_version(')
prepare_open = prepare_code.index('{', prepare_start)
loop_start = prepare_code.index('loop {', prepare_open)
# Contiguous live prefix + complete loop also preserve the post-Prepare gate
# inside its actual if. Repeated gate/take identifiers are not unique markers.
prepare['sequence'] = [prepare_code[prepare_open:loop_start], loop]
prepare['top_level'] = ['let gate =', 'let result =', 'let actual =', 'loop {']
selection['required'].append('use crate::OriginalCircuitEvaluatedVersionProgressV1;')
selection.setdefault('required_order', []).append([
    'const VERSION_READBACK_RESERVE: usize = 8;', 'impl Owners {',
])

new_boundary = {
    'id': 'learning_original_candidate_evaluation_postread',
    'symbol': 'OriginalCellQ24CandidateStageOwnersV1::read_original_evaluation_with_originals',
    'receiver_type': 'OriginalCellQ24CandidateStageOwnersV1',
    'definition_path': AGENT + EVALUATION_NAME + '.rs',
    'definition_markers': ['pub(super) async fn read_original_evaluation_with_originals('],
    'product_callers': [AGENT + MAIN_NAME + '.rs'],
    'caller_markers': [],
}
assert not any(r['id'] == new_boundary['id'] for r in AFTER['boundary'])
AFTER['boundary'].append(new_boundary)
AFTER['privileged_inventory']['required_boundary_ids'].append(new_boundary['id'])

alignments = []
for item in CHANGED.values():
    raw = (OVERLAY / item['path']).read_text()
    masked = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(raw))
    for entry in item.get('required_function_order', []):
        start = masked.index(entry['function']); end = PROOF._rust_item_end(masked, start) + 1
        body = masked[start:end]
        for key in ('sequence', 'top_level'):
            cursor = 0
            for index, marker in enumerate(entry.get(key, [])):
                begin = 0 if key == 'top_level' else cursor
                pattern = r'\s*'.join(re.escape(token) for token in re.findall(r'\w+|[^\w\s]', marker))
                found = re.search(pattern, body[begin:])
                if not found:
                    found = re.search(pattern.replace(r'\)', r'(?:,\s*)?\)'), body[begin:])
                assert found, (item['path'], entry['function'], key, marker)
                value = found.group()
                cursor = begin + found.end()
                def equivalent(s):
                    return re.sub(r',(?=\))', '', re.sub(r'\s+', '', s))
                assert equivalent(value) == equivalent(marker)
                entry[key][index] = value
                if value != marker:
                    alignments.append({'path': item['path'], 'function': entry['function'], 'field': key,
                                       'before': marker, 'after': value})

for path, item in CHANGED.items():
    old = next(row for row in BASE['protected_file'] if row['path'] == path)
    assert not (Counter(old['forbidden']) - Counter(item['forbidden']))

def value(v):
    if isinstance(v, str): return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool): return str(v).lower()
    if isinstance(v, list): return '[' + ', '.join(value(x) for x in v) + ']'
    if isinstance(v, dict): return '{ ' + ', '.join(k + ' = ' + value(x) for k, x in v.items()) + ' }'
    return str(v)

def table(kind, item):
    return '[[' + kind + ']]\n' + '\n'.join(k + ' = ' + value(v) for k, v in item.items()) + '\n\n'

def replace(match):
    item = tomllib.loads(match.group())['protected_file'][0]
    return table('protected_file', CHANGED[item['path']]) if item['path'] in CHANGED else match.group()

pattern = r'(?ms)^\[\[protected_file\]\]\n.*?(?=^\[\[(?:boundary|protected_file)\]\]|^\[(?:authority|privileged_inventory)\]|\Z)'
new_text = re.sub(pattern, replace, BASE_TEXT)
new_text = re.sub(r'(?m)^required_boundary_ids = .*?$',
    'required_boundary_ids = ' + value(AFTER['privileged_inventory']['required_boundary_ids']), new_text, count=1)
new_text += '\n# Same-call actual Evaluation originals; no reusable CURRENT authority.\n' + table('boundary', new_boundary)
assert tomllib.loads(new_text) == AFTER
(OVERLAY / 'CALLERS.toml').write_text(new_text)

delta = json.loads((HERE / 'base/CALLERS.delta.json').read_text())
for collection in ('protected_replacements', 'new_protected_files'):
    for entry in delta[collection]:
        item = entry['after'] if collection == 'protected_replacements' else entry
        if item['path'] in CHANGED:
            if collection == 'protected_replacements': entry['after'] = deepcopy(CHANGED[item['path']])
            else: entry.update(deepcopy(CHANGED[item['path']]))
a96 = tomllib.loads((ROOT / 'profile-evaluated-read-guards-4ab-v1/postimages/CALLERS.toml').read_text())
assert not any(entry['after']['path'] == AGENT + EVALUATION_NAME + '.rs' for entry in delta['protected_replacements'])
delta['protected_replacements'].append({
    'before': next(item for item in a96['protected_file'] if item['path'] == AGENT + EVALUATION_NAME + '.rs'),
    'after': deepcopy(evaluation),
})
delta['new_boundaries'].append(new_boundary)
delta['inventory_additions'].append(new_boundary['id'])
delta['external_progress_caller_only'] = {
    'owner': 'profile_audit',
    'id': 'learning_evaluated_version_publication_progress',
    'definition_path': AGENT + 'circuit_retained_version_client.rs',
    'symbol': 'OriginalCircuitRetainedVersionClientV1::publication_progress',
    'product_callers_add': [AGENT + S_NAME + '.rs'],
    'boundary_not_duplicated_here': True,
}
delta['input_status'] = 'Root12 actual + caller v2 actual + Root progress v3 prefmt + postread v1 prefmt'
(HERE / 'CALLERS.delta.json').write_text(json.dumps(delta, indent=2) + '\n')
(HERE / 'GUARD_ALIGNMENTS.json').write_text(json.dumps(alignments, indent=2) + '\n')
PROOF._verify_protected_files(OVERLAY, {'protected_file': list(CHANGED.values())})
print(json.dumps({'changed_existing_rows_since_old_root_guard': len(CHANGED),
                  'new_private_boundaries_since_old_root_guard': 1,
                  'old_forbidden_preserved': True,
                  'central_registry_modified': False,
                  'local_changed_row_verification': 'PASS'}))
