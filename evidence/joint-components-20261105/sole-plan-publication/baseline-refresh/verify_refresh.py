#!/usr/bin/env python3
"""Verify retained GitHub source reads without creating a ref or running CI."""
from pathlib import Path
import base64
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'pq_recovery/chain-sole-plan-trigger-review'
BASE = '0e1c25d42fff22bec6ec2a08c4fbdff240229858'
HEAD = 'd6b9835fa91a2a4b58c77cc60daf809b5e771d56'
TREE = '5943e8a1fb6c1a99cb24c7e06bd016f02c962ab1'
BRANCH = 'fix/chain-six-axis-performance-20261103'
DOC = 'docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md'


def load(path):
    return json.loads(path.read_bytes())


def rpc(name):
    result = load(OUT / name)
    assert result.get('isError') is not True
    return result['structuredContent']


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    first, last = rpc('pr688-current.raw.json'), rpc('pr688-after-review.raw.json')
    for pr in (first, last):
        assert pr['head_sha'] == HEAD and pr['head'] == BRANCH
        assert pr['state'] == 'open' and pr['draft'] is True and pr['merged'] is False
    commit = json.loads(rpc('commit.raw.json')['content'])
    assert commit['sha'] == HEAD and commit['tree']['sha'] == TREE
    assert [parent['sha'] for parent in commit['parents']] == [BASE]
    compare = json.loads(rpc('compare-full.raw.json')['content'])
    assert compare['status'] == 'ahead' and compare['ahead_by'] == compare['total_commits'] == 1
    assert compare['behind_by'] == 0 and len(compare['commits']) == 1
    assert compare['commits'][0]['sha'] == HEAD
    assert compare['base_commit']['sha'] == compare['merge_base_commit']['sha'] == BASE
    files = compare['files']
    assert len(files) == 9 and all('patch' in item for item in files)
    changed = {item['filename'] for item in files}
    assert DOC not in changed
    assert len([p for p in changed if p.startswith('evidence/growth-receipt-stream-20261105/')]) == 5
    assert len([p for p in changed if p.startswith('trillionnium/')]) == 4

    catalogs = ['workflow-inventory.json', 'entry-source-inventory.json',
                'model-control-source-inventory.json', 'unit-source-inventory.json']
    old_rows = {}
    for name in catalogs:
        for row in load(PRIOR / name):
            if not row.get('git_blob'):
                continue  # Preserve the historical guessed-path 404; it is not a verified input.
            path = PRIOR / 'source' / row['path']
            actual = identity(path)
            assert (actual['bytes'], actual['sha256'], actual['git_blob']) == (row['bytes'], row['sha256'], row['git_blob'])
            assert row['path'] not in old_rows
            old_rows[row['path']] = row
    assert len(old_rows) == 49 and not (changed & set(old_rows))

    listing = json.loads(rpc('workflows.raw.json')['content'])
    assert len(listing) == 19 and all(item['type'] == 'file' for item in listing)
    old_workflows = load(PRIOR / 'workflow-inventory.json')
    assert {item['path'] for item in listing} == {item['path'] for item in old_workflows}
    for item in listing:
        row = old_rows[item['path']]
        assert (item['sha'], item['size']) == (row['git_blob'], row['bytes'])

    encoded = rpc('sole_plan.raw.json')
    assert encoded['encoding'] == 'base64'
    raw = base64.b64decode(''.join(encoded['content'].splitlines()), validate=True)
    doc = OUT / 'source' / DOC
    assert doc.read_bytes() == raw
    doc_identity = identity(doc)
    assert doc_identity['git_blob'] == encoded['sha'] == '3787d8321ee9f4eb5a0fe5794dcad3f997afecb1'
    assert doc_identity['bytes'] == 552675
    assert doc_identity['sha256'] == '063df6d6047e08addb40d92c01bf85c2ff1386788369bfd7ba1d22e0a421198b'
    old_doc = ROOT / 'w1/sole-plan-current-draft/base' / DOC
    assert old_doc.read_bytes() == raw

    workflow_names = [
        'codeql-analysis-export.yml', 'pon-original-large-state-cpu.yml',
        'pon-original-workspace-large-state-cpu.yml', 'pon-priority-acceptance.yml',
        'trnm-required-baseline.yml']
    inputs = [OUT / name for name in [
        'pr688-current.raw.json', 'pr688-after-review.raw.json', 'commit.raw.json',
        'compare.raw.json', 'compare-full.raw.json', 'workflows.raw.json',
        'sole_plan.raw.json', 'observation-times.json']]
    inputs += [PRIOR / name for name in catalogs] + [PRIOR / 'review.json', PRIOR / 'delivery-manifest.json', doc]
    report = {
        'schema': 'chain-sole-plan-pr688-baseline-refresh-v1',
        'source': {'repository': 'TrillionniumFoundation/Trillionnium-Chain', 'pr': 688,
                   'head_ref': BRANCH, 'commit': HEAD, 'tree': TREE, 'parent': BASE,
                   'observed_initial_and_final_head_equal': True,
                   'observed_times': load(OUT / 'observation-times.json'),
                   'pr_base': first['base'], 'pr_base_sha': first['base_sha'],
                   'pr_actual_merge_sha': first['merge_commit_sha'],
                   'merge_scope': 'Existing PR688 prospective merge only; not a proposed docs PR identity or a qualification source.'},
        'delta': {'commits': 1, 'files': 9,
                  'paths': [{'path': item['filename'], 'status': item['status'], 'git_blob': item['sha'],
                             'additions': item['additions'], 'deletions': item['deletions']} for item in files],
                  'reviewed_changed_code_scope': 'Four Node migration/growth files replace block-ID copies with fixed-width reads and stream an authenticated receipt copy with fixed-size chunks. The patches add three file/SQLite controls; no workflow, command entry, model trainer invocation, or trial-ledger path is added.',
                  'native_or_performance_credit': False},
        'prior_trigger_audit_continuity': {
            'prior_head': BASE, 'workflow_count': 19, 'workflow_blob_and_size_equal_count': 19,
            'verified_entry_and_model_control_count': 30,
            'all_prior_verified_source_paths_unchanged': 49,
            'entry_comparison_method': 'The exact direct-parent one-commit comparison returns all nine changed paths, none in the 49 verified catalog paths; fresh current workflow listing also binds all 19 workflow Git blobs and sizes. Prior retained bytes were rehashed locally.',
            'trigger_reaudit_required': False,
            'unfiltered_pull_request_workflows_remain_eligible': workflow_names,
            'learning_boundary': 'Existing deterministic model-mechanism fixtures can still execute in unfiltered CI. The specifically scoped hosted SmolLM owner workflow has no pull_request trigger and still requires its exact push branch plus intent JSON path; a strict fresh stacked docs-only change does not match. No claim of zero CI/model logic or arbitrary external-webhook safety.',
            'source_update_note': 'Unfiltered original Rust CI may execute the newly inherited migration tests. No test outcome from C4, earlier source, or this read-only review qualifies the new head.'},
        'sole_plan_exact': doc_identity,
        'sole_plan_equal_to_prior_retained_base_bytes': True,
        'publication_conditions': {
            'required_base_ref': BRANCH, 'do_not_target': 'main',
            'only_permitted_total_compare_path': DOC,
            'edit_scope': 'Append to the current exact sole-plan bytes, retaining prior content.',
            'refresh_required_before_publication': True,
            'head_lease_required': HEAD,
            'if_head_advances': 'Refresh current source and workflow/entry delta, then rebase the document append without overwriting concurrent changes; do not assume a docs-only last commit means a docs-only PR.',
            'no_new_trial_or_ledger_reset_authorized': True},
        'actions': {'created_commit': False, 'created_or_updated_pr': False, 'workflow_dispatch': False,
                    'native_or_cargo_run': False, 'learning_ledger_mutation': False, 'desktop_bulk_read': False},
        'encoding_note': 'The contents API base64 value contains line wrapping. Decoding only removes those base64 newlines; the resulting bytes exactly match the advertised Git blob and the old raw source. An initial strict decode before handling wrapping raised an error, not a source or test failure.',
        'input_inventory': [identity(path) for path in inputs]}
    output = OUT / 'review.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'review': identity(output), 'latest_head': HEAD, 'unchanged_workflows': 19,
                      'unchanged_prior_verified_paths': 49, 'sole_plan': doc_identity}))


if __name__ == '__main__':
    main()
