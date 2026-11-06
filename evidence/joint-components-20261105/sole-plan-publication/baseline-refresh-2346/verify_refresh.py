"""Verify this exact read-only ref/source refresh; no Git writes or CI runs."""
from pathlib import Path
import hashlib
import json

W = Path('/workspace/scratch/93bfcfe29fc8')
R = Path(__file__).resolve().parent
PRIOR = W / 'pq_recovery/chain-sole-plan-trigger-review'
BASE = 'd6b9835fa91a2a4b58c77cc60daf809b5e771d56'
HEAD = 'a5b5127883393da33c8619cc5f2b8e333a2dcf1b'
BRANCH = 'fix/chain-six-axis-performance-20261103'
DOC = 'docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md'
WORKFLOW = '.github/workflows/pon-branch-encoding-acceptance.yml'


def load(path):
    return json.loads(path.read_bytes())


def payload(name, parse=True):
    response = load(R / name)
    assert response.get('isError') is False
    value = response['structuredContent']['content']
    return json.loads(value) if parse else value


def desc(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(W)), 'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


for name in ['ref-before.raw.json', 'ref-after.raw.json']:
    ref = payload(name)
    assert ref['ref'] == 'refs/heads/' + BRANCH
    assert ref['object']['type'] == 'commit' and ref['object']['sha'] == HEAD
commit = payload('commit.raw.json')
assert commit['sha'] == HEAD
compare = payload('compare.raw.json')
assert compare['base_commit']['sha'] == compare['merge_base_commit']['sha'] == BASE
assert compare['status'] == 'ahead' and compare['behind_by'] == 0
assert compare['ahead_by'] == compare['total_commits'] == len(compare['commits']) == 3
assert compare['commits'][-1]['sha'] == HEAD
files = compare['files']
assert len(files) == 23 < 300
changed = {row['filename'] for row in files}
assert DOC not in changed

catalogs = ['workflow-inventory.json', 'entry-source-inventory.json',
            'model-control-source-inventory.json', 'unit-source-inventory.json']
old_rows = {}
for name in catalogs:
    for row in load(PRIOR / name):
        if not row.get('git_blob'):
            continue
        actual = desc(PRIOR / 'source' / row['path'])
        assert all(actual[key] == row[key] for key in ('bytes', 'sha256', 'git_blob'))
        assert row['path'] not in old_rows
        old_rows[row['path']] = row
assert len(old_rows) == 49 and changed & set(old_rows) == {WORKFLOW}
listing = payload('workflows.raw.json')
old_workflows = load(PRIOR / 'workflow-inventory.json')
assert len(listing) == len(old_workflows) == 19
assert {row['path'] for row in listing} == {row['path'] for row in old_workflows}
for row in listing:
    assert row['type'] == 'file'
    if row['path'] != WORKFLOW:
        prior = old_rows[row['path']]
        assert (row['sha'], row['size']) == (prior['git_blob'], prior['bytes'])

new_workflow = payload('changed-workflow.raw.json', False).encode()
old_workflow = (PRIOR / 'source' / WORKFLOW).read_bytes()
old_pin = b'06828d9204db6418e3da7f50ced582540bd6132d'
new_pin = b'ddc4e1d317ce962e453a1f08db7f608e43a8e152'
assert old_workflow.count(old_pin) == 1
assert new_workflow == old_workflow.replace(old_pin, new_pin, 1)
assert next(row for row in files if row['filename'].endswith('/native_store.rs'))['sha'] == new_pin.decode()
workflow_path = R / 'source' / WORKFLOW
workflow_path.parent.mkdir(parents=True, exist_ok=True)
workflow_path.write_bytes(new_workflow)
workflow_id = desc(workflow_path)
fresh_workflow = next(row for row in listing if row['path'] == WORKFLOW)
assert (workflow_id['git_blob'], workflow_id['bytes']) == (fresh_workflow['sha'], fresh_workflow['size'])
assert workflow_id['git_blob'] == 'ef548bd61a94d33162436731975fb71493362af6'
assert DOC not in new_workflow.decode().split('permissions:', 1)[0]

doc = payload('sole-plan.raw.json', False).encode()
doc_path = R / 'source' / DOC
doc_path.parent.mkdir(parents=True, exist_ok=True)
doc_path.write_bytes(doc)
doc_id = desc(doc_path)
assert doc == (W / 'pq_recovery/chain-sole-plan-refresh-20261105/source' / DOC).read_bytes()
assert doc_id['bytes'] == 552675
assert doc_id['sha256'] == '063df6d6047e08addb40d92c01bf85c2ff1386788369bfd7ba1d22e0a421198b'
assert doc_id['git_blob'] == '3787d8321ee9f4eb5a0fe5794dcad3f997afecb1'

report = {
    'schema': 'chain-sole-plan-exact-ref-refresh-2346-v1',
    'source': {'repository': 'TrillionniumFoundation/Trillionnium-Chain', 'head_ref': BRANCH,
        'commit': HEAD, 'tree': commit['tree']['sha'], 'parents': [p['sha'] for p in commit['parents']],
        'observed_initial_and_final_head_equal': True,
        'observed_times': load(R / 'observation-times.json')},
    'delta': {'base': BASE, 'commits': 3, 'files': 23,
        'paths': [{'path': row['filename'], 'status': row['status'], 'git_blob': row['sha'],
            'additions': row['additions'], 'deletions': row['deletions']} for row in files],
        'scope': 'Only trigger/input continuity reviewed. Repository delta also includes held-descriptor scanner/operator file changes and native apply test-only code with rusqlite trace dev feature; no outcome or performance credit is inferred.'},
    'prior_trigger_continuity': {
        'catalog_paths': 49, 'unchanged_paths': 48, 'unchanged_entry_and_model_control_paths': 30,
        'unchanged_workflows': 18, 'changed_workflows': [WORKFLOW],
        'changed_workflow': {'actual': workflow_id,
            'entire_byte_difference': 'Exactly one native_store Git blob pin replacement; all other bytes identical.',
            'old_pin': old_pin.decode(), 'new_pin': new_pin.decode(),
            'trigger_resources_budgets_commands_other_than_the_pin_unchanged': True,
            'canonical_doc_path_still_not_in_pull_request_paths': True},
        'unfiltered_original_pr_workflows_still_eligible': [
            'codeql-analysis-export.yml', 'pon-original-large-state-cpu.yml',
            'pon-original-workspace-large-state-cpu.yml', 'pon-priority-acceptance.yml',
            'trnm-required-baseline.yml'],
        'learning_boundary': 'The previous exact 49-path trigger/entry assessment continues for this source with the one rechecked pin-only workflow delta. Five original unfiltered CI workflows can run, including deterministic model-mechanism fixtures. The scoped hosted SmolLM owner remains push/exact-branch and intent-path gated; no zero-CI, zero-model-logic, external-webhook or new-learning qualification is inferred.',
        'no_full_trigger_reaudit': 'Fresh listing binds 19 workflow Git blobs; 18 unchanged. All 49 retained source files locally rehashed; exact full 23-file Git comparison shows only the one workflow intersects the catalog.'},
    'sole_plan_exact': doc_id, 'sole_plan_unchanged': True,
    'publication_conditions': {'base_ref': BRANCH, 'head_lease': HEAD,
        'required_entire_stacked_compare': [DOC], 'do_not_target_main': True,
        'append_to_exact_current_bytes': True, 'refresh_and_reconcile_if_head_advances': True},
    'read_only_actions': {'github_reads_only': True, 'created_commit': False, 'created_pr': False,
        'workflow_dispatch': False, 'native_run': False, 'learning_or_ledger_mutation': False,
        'desktop_or_bulk_reads': False},
    'prior_review': desc(W / 'pq_recovery/chain-sole-plan-refresh-20261105/review.json'),
    'prior_trigger_review': desc(PRIOR / 'review.json'),
    'source_encoding': 'Fresh GitHub fetch returned normalized UTF-8 source text; its encoded bytes were independently checked against the unchanged exact Git blob and prior retained raw source.',
}
(R / 'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
inputs = [desc(p) for p in sorted(R.rglob('*')) if p.is_file() and p != R / 'delivery-manifest.json']
manifest = {'schema': 'chain-sole-plan-read-only-refresh-delivery-v1', 'review': desc(R / 'review.json'),
    'files': inputs, 'file_count': len(inputs), 'total_bytes': sum(row['bytes'] for row in inputs),
    'git_writes': 0, 'native_runs': 0, 'desktop_bulk_reads': 0}
(R / 'delivery-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'review': desc(R / 'review.json'), 'manifest': desc(R / 'delivery-manifest.json'),
    'head': HEAD, 'tree': commit['tree']['sha'], 'unchanged_catalog': 48,
    'rechecked_pin_only_workflow': WORKFLOW, 'plan': doc_id}, ensure_ascii=False))
