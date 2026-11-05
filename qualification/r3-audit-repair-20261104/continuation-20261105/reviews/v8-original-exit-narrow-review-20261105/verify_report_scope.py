#!/usr/bin/env python3
"""Verify the frozen report transition; does not run native or product tests."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'ci-audit/v8-deliverables-narrow-review-20261105'
CURRENT = ROOT / 'hepta-audit-fifth/v8-deliverables'
PREVIOUS = ROOT / 'hepta-audit-fifth/v7-deliverables/continuation-blocker-progress-v5.json'
ORIGINAL = ROOT / 'hepta-audit-fourth/deliverables/current-blockers.json'
DOCS = [
    'CONTINUATION_PROGRESS_V7.zh-CN.md',
    'LATEST.zh-CN.md',
    'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md',
    'continuation-blocker-progress-v6.json',
]


def identity(path, raw=None):
    raw = path.read_bytes() if raw is None else raw
    return {
        'path': str(path.relative_to(ROOT)),
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'computed_git_blob': hashlib.sha1(
            b'blob ' + str(len(raw)).encode() + b'\0' + raw
        ).hexdigest(),
    }


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), identity(path, raw)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = OUT / 'frozen-inputs'
    frozen.mkdir(exist_ok=True)
    bodies = {name: (CURRENT / name).read_bytes() for name in DOCS}
    for name, raw in bodies.items():
        path = frozen / name
        if path.exists():
            assert path.read_bytes() == raw, f'frozen input changed: {name}'
        else:
            path.write_bytes(raw)

    old, old_pin = load(PREVIOUS)
    original, original_pin = load(ORIGINAL)
    new = json.loads(bodies['continuation-blocker-progress-v6.json'])
    ids = [f'B{i:02d}' for i in range(1, 24)]
    for obj in (old, original, new):
        assert [row['id'] for row in obj['items']] == ids
    changes = []
    exit_digest_rows = []
    for before, baseline, after in zip(old['items'], original['items'], new['items']):
        exit_text = after['original_exit_condition_zh']
        assert exit_text == before['original_exit_condition_zh']
        assert exit_text == baseline['original_exit_condition_zh']
        exit_digest_rows.append({
            'id': after['id'],
            'original_exit_utf8_sha256': hashlib.sha256(exit_text.encode()).hexdigest(),
        })
        delta = {key: {'before': before[key], 'after': after[key]}
                 for key in ('status', 'closure_class') if before[key] != after[key]}
        if delta:
            changes.append({'id': after['id'], 'fields': delta})
    assert len(changes) == 1 and changes[0]['id'] == 'B08'
    assert changes[0]['fields']['closure_class'] == {
        'before': 'OPEN', 'after': 'CLOSED_SCOPED'
    }
    assert Counter(row['closure_class'] for row in new['items']) == new['counts']
    assert new['counts'] == {'CLOSED_SCOPED': 11, 'OPEN': 11, 'SCIENTIFIC_HOLD': 1}
    assert new['whole_candidate_qualified'] is False
    assert new['all_blockers_closed'] is False
    assert new['original_23_ids_and_exit_conditions_unchanged'] is True

    plan = bodies['PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md'].decode()
    rows = [line for line in plan.splitlines() if re.match(r'^\| B\d\d \|', line)]
    assert len(rows) == 23
    for line, item in zip(rows, new['items']):
        fields = [field.strip() for field in line.split('|')[1:-1]]
        assert fields[0] == item['id']
        assert fields[1].split(' / ', 1)[0] == item['closure_class']
        assert fields[-1] == item['original_exit_condition_zh']

    item = {row['id']: row for row in new['items']}
    assert item['B15']['closure_class'] == 'OPEN'
    assert item['B18']['closure_class'] == 'SCIENTIFIC_HOLD'
    assert item['B11']['closure_class'] == 'OPEN'
    assert new['recorded_utc'] == '2026-11-05T17:53:52Z'
    assert new['v8_fixed_cut_not_rewritten'] == new['recorded_utc']
    assert new['postcut_appended_v8_utc'] > new['recorded_utc']
    assert len(new['closure_transitions_v8']) == 1
    transition = new['closure_transitions_v8'][0]
    assert transition['id'] == 'B08'
    assert transition['original_exit_unchanged'] is True
    assert transition['not_an_eed_GNU_or_full_workspace_pass'] is True

    b08_root, b08_root_pin = load(ROOT / 'hepta-audit-fifth/inputs/b08-original-contract-root-closure-v1.json')
    independent, independent_pin = load(ROOT / 'ci-audit/published-eed4d6-ci-20261105/b08-source-review-v1/review-v1/independent-review.json')
    snapshot, snapshot_pin = load(ROOT / 'ci-audit/published-eed4d6-ci-20261105/snapshot-0003/registry.actual-v1.json')
    assert b08_root_pin['computed_git_blob'] == '652e5013c96b62c5fd3e0dc27b49e02af89afb00'
    assert independent_pin['computed_git_blob'] == '98e9642f7ecfcd8baa71f97baa3db4f8cee051e4'
    assert snapshot_pin['computed_git_blob'] == 'aaefec8db8c5f7874129f4143af71a96ac78b124'

    progress = bodies['CONTINUATION_PROGRESS_V7.zh-CN.md'].decode()
    for literal in (
        'pending条数上限与溢出、exact replay及compaction清理',
        '512次真实记录与附加、32KiB保留上限及omission统计',
        'escaped输入原序列化字节上限',
        'first-party OpenAI',
        '3962通过、5失败、exit100',
        '没有执行eed的GNU全范围',
        '没有将四例的通过升级成B15通过',
        '17:54–17:58后续增量',
    ):
        assert literal in progress, literal

    receipt = {
        'schema': 'v8-report-original-exit-and-scope-narrow-review-v1',
        'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'decision': 'ACCEPTED_FOR_REVIEWED_REPORT_BYTES',
        'review_role': 'Independent report/source-evidence scope review; not a native or product-test execution.',
        'current_documents': [identity(CURRENT / name, bodies[name]) for name in DOCS],
        'previous_ledger': old_pin,
        'original_exit_ledger': original_pin,
        'verified_ids_in_order': ids,
        'all_23_original_exit_conditions_utf8_equal': True,
        'plan_table_all_23_ids_classes_and_exit_text_equal_to_ledger': True,
        'classification_changes': changes,
        'counts_before': old['counts'],
        'counts_after': new['counts'],
        'all_blockers_closed': False,
        'whole_candidate_qualified': False,
        'b08_evidence_pins': {'root_closure': b08_root_pin, 'independent_review': independent_pin},
        'b08_accepted_scope': {
            'original_gnu_cases': 4,
            'tested_working_tree': 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2',
            'ordinary_head_remains': 'cabc (the original full SHA is retained in the source receipts)',
            'related_complete_sources': 15,
            'source_bridge': 'All 15 relevant leaves are identical through fixed 5b/e78/eed; the original persistence contract is unchanged.',
            'owning_scope_result_not_relabelled': '3962 PASS / 5 FAIL / exit100',
            'windows_supplement': 'Three original unit cases retain their own fixed-source observations; the namespaced integration case is Unix-only.',
            'no_eed_gnu_or_workspace_qualification_inferred': True,
            'wire_precision': 'ChatGPT Codex and nonstandard endpoints strip local metadata; first-party OpenAI keeps its permitted metadata, independent of friendly provider name.',
            'q02_collection_plan_not_an_added_original_exit': True,
            'new_mutation_negative_or_test_not_invented': True,
        },
        'reviewer_attribution_correction': {
            'resolved_in_reviewed_documents': True,
            'pending_recorder': 'Pending-count bounds/overflow, None/Some, exact replay and compaction cleanup.',
            'retained_recorder': '512 actual record/attach operations, 32KiB retained bound and omission statistics.',
            'namespaced_case': 'The escaped-input serialized-byte bound belongs to this case, alongside actual request/output and rollout replay checks.',
            'qualification_effect': 'Corrects per-row explanation only; does not add a case, change evidence, or widen B08 closure.',
        },
        'postcut_boundary': {
            'fixed_cut': new['recorded_utc'],
            'explicit_addendum_recorded_utc': new['postcut_appended_v8_utc'],
            'snapshot_registry': snapshot_pin,
            'snapshot_scope': '19 workflows / 53 jobs; 18 success, 31 queued, 1 running, 2 skipped, 1 cancelled, 0 failure. The new success is API-only.',
            'b11_native6_and_followup': 'The document explicitly distinguishes 147 PASS / 7 FAIL / 2 ignored from the later counterfactual publication, whose result is not claimed.',
            'b11_originals_limit': 'This narrow report review checks that attribution and OPEN classification; it does not independently rerun or reverify the separate native6 ZIP.',
        },
        'retained_open_boundaries': {
            'B15': 'Latest candidate required workflows, original platform scope, base/merge/source identity and full-workspace acceptance remain OPEN.',
            'B11': 'The whole target remains failed; positive controls or a counterfactual publication do not close the strict permission contract.',
            'B18': 'SCIENTIFIC_HOLD remains unchanged.',
            'early_returns': 'The original full-workspace 25 observed early returns are retained; B08 does not convert them to executed behavior.',
            'native_resources': 'RESOURCE_PENDING and unchanged capacity floors remain; no resource recovery is inferred from the new CI API success.',
            'driver': 'The unrelated B16 driver remains UNKNOWN.',
        },
        'exit_condition_digests': exit_digest_rows,
        'actions': {
            'cloud_readonly_report_comparison': True,
            'native_commands': 0,
            'product_test_runs': 0,
            'ci_polls_or_mutations': 0,
            'source_or_git_ref_changes': 0,
        },
    }
    for name, raw in bodies.items():
        assert (CURRENT / name).read_bytes() == raw, f'input changed during review: {name}'
    output = OUT / 'independent-review.json'
    assert not output.exists(), 'do not overwrite a frozen review'
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(identity(output), ensure_ascii=False))


if __name__ == '__main__':
    main()
