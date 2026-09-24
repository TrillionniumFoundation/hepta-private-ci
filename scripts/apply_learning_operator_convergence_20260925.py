#!/usr/bin/env python3
"""One-shot, fail-closed materializer for the learning.operator convergence candidate.

This script is executed by a temporary branch workflow and deleted in the same
materialization commit.  Every replacement is exact so source drift fails rather
than silently weakening a gate.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FEATURE = 'qualification-legacy-learning-write'


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly one replacement, found {count}: {old!r}')
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly one regex replacement, found {count}: {pattern!r}')
    write(path, updated)


def remove_cfg_use_pairs(path: str) -> None:
    text = read(path)
    pattern = rf'#\[cfg\(feature = "{re.escape(LEGACY_FEATURE)}"\)\]\nuse [^\n]+;\n'
    updated, count = re.subn(pattern, '', text)
    if count == 0:
        raise SystemExit(f'{path}: no legacy cfg/use pairs found')
    write(path, updated)


def remove_feature_test(path: str, function_name: str) -> None:
    text = read(path)
    pattern = (
        rf'\n#\[cfg\(feature = "{re.escape(LEGACY_FEATURE)}"\)\]\n'
        rf'#\[tokio::test[^\n]*\]\nasync fn {re.escape(function_name)}\(\) \{{.*?'
        rf'(?=\n(?:#\[cfg|#\[tokio::test|#\[test)|\Z)'
    )
    updated, count = re.subn(pattern, '\n', text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f'{path}: could not remove legacy test {function_name}')
    write(path, updated)


# 1. Lane E closed world follows the actual reviewed operator surface and tests.
lane = 'scripts/hepta-lane-e-closure.py'
replace_once(
    lane,
    '*(f"OP-{index:02d}" for index in range(1, 5)),',
    '*(f"OP-{index:02d}" for index in range(1, 7)),',
)
old_operator_set = '''    "learning.operator": {
        "build_targets",
        "validate_applicability_certificate",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "admit_operator_regularity",
        "fit_transition_model",
        "predict_transition",
    },'''
new_operator_set = '''    "learning.operator": {
        "build_targets",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "validate_applicability_certificate",
        "validate_applicability_with_signed_evidence_v2",
        "fit_tabular_operator",
        "fit_tabular_operator_strict_v2",
        "verify_tabular_operator_plan_v2",
        "fit_tabular_operator_verified_v2",
        "predict_tabular_operator",
        "encode_tabular_payload_v1",
        "load_pinned_tabular_operator_v1",
        "admit_operator_regularity",
        "admit_operator_regularity_with_signed_evidence_v2",
        "fit_transition_model",
        "verify_world_model_dataset_v2",
        "fit_transition_model_verified_v2",
        "predict_transition",
        "freeze_terminal_cell_from_owner_v1",
        "fit_terminal_cell_from_owner_v1",
    },'''
replace_once(lane, old_operator_set, new_operator_set)

matrix = json.loads(read('docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json'))
operator = next(row for row in matrix['modules'] if row['module'] == 'learning.operator')
matrix_ops = {row['operation'] for row in operator['operations']}
expected_ops = {
    line.strip().strip('",')
    for line in new_operator_set.splitlines()
    if line.lstrip().startswith('"') and 'learning.operator' not in line
}
if matrix_ops != expected_ops:
    raise SystemExit(
        'Lane E operator matrix drift: '
        f'missing={sorted(matrix_ops - expected_ops)}, extra={sorted(expected_ops - matrix_ops)}'
    )

# 2. The direct signed decision helper is crate-internal; ProductEvaluationRunner is ingress.
replace_once(
    'codex-rs/hepta-intelligence-eval/src/lib.rs',
    'pub use signed_evaluation::decide_with_signed_evidence_v2;',
    'pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;',
)

# 3. Remove obsolete raw V1 product append compatibility from the Agentd product source.
product = 'codex-rs/hepta-agentd/src/intelligence_product.rs'
remove_cfg_use_pairs(product)
text = read(product)
for line in [
    'use codex_hepta_learning_ledger::DurableLedgerError;\n',
    'use codex_hepta_learning_ledger::LedgerEvent;\n',
]:
    if line not in text:
        raise SystemExit(f'{product}: missing expected legacy import {line!r}')
    text = text.replace(line, '', 1)
text = text.replace(
    'proposal digest or append the exact Decision/Outcome event.\n',
    'proposal digest. Learning facts are written only through the canonical LedgerWriter owner.\n',
    1,
)
legacy_types = r'''\n#\[derive\(Clone, Debug, Eq, PartialEq\)\]\npub struct PendingIntelligenceLedgerAppendV1 \{.*?\nimpl StdError for AgentdIntelligenceLedgerError \{\}\n'''
text, count = re.subn(legacy_types, '\n', text, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f'{product}: legacy append types were not found exactly once')
write(product, text)

runner = 'codex-rs/hepta-agentd/src/intelligence_product_runner.rs'
regex_once(
    runner,
    rf'''\n    #\[cfg\(feature = "{re.escape(LEGACY_FEATURE)}"\)\]\n    pub fn append_decision\(.*?\n    \}}\n\}}\n\Z''',
    '\n}\n',
)

tests = 'codex-rs/hepta-agentd/src/intelligence_product_tests.rs'
remove_cfg_use_pairs(tests)
remove_feature_test(tests, 'real_owner_product_path_records_decision_outcome_and_reopens')
remove_feature_test(tests, 'final_use_revocation_race_fails_before_decision_publication')

# Remove stale public reexports if present; no product or qualification caller remains.
lib_path = 'codex-rs/hepta-agentd/src/lib.rs'
lib_text = read(lib_path)
lib_lines = [
    line for line in lib_text.splitlines(keepends=True)
    if 'AgentdIntelligenceLedgerError' not in line
    and 'PendingIntelligenceLedgerAppendV1' not in line
]
write(lib_path, ''.join(lib_lines))

# 4. The topology gate must execute real topology_v2 tests, never a zero-test filter.
for path in [
    '.github/workflows/hepta-architecture-convergence.yml',
    'scripts/hepta_ci_scope.py',
    'scripts/tests/test_hepta_ci_scope.py',
]:
    text = read(path)
    count = text.count('topology_v3')
    if count == 0:
        raise SystemExit(f'{path}: missing stale topology_v3 token')
    write(path, text.replace('topology_v3', 'topology_v2'))

# Orphan Objective ingress/dispatch files were never declared by lib.rs.  Keep the
# single existing ObjectiveRuntimeHost/DurableRunStartJournal product owner.
for stale in [
    'codex-rs/hepta-agentd/src/objective_ingress.rs',
    'codex-rs/hepta-agentd/src/objective_dispatch.rs',
]:
    path = ROOT / stale
    if path.exists():
        path.unlink()

# Regenerate the existing plasticity status projection instead of hand-editing it.
subprocess.run(
    ['python3', 'scripts/hepta-implementation-maps.py', 'sync-plasticity-status'],
    cwd=ROOT,
    check=True,
)

print('learning.operator convergence materialization complete')
