#!/usr/bin/env python3
"""One-shot, fail-closed materializer for learning.operator convergence.

The shared branch moves frequently. Every edit accepts only a known pre-state
or the exact desired state; unknown concurrent changes abort without a commit.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FEATURE = "qualification-legacy-learning-write"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def ensure_text(path: str, old: str, new: str) -> None:
    text = read(path)
    old_count, new_count = text.count(old), text.count(new)
    if old_count == 1 and new_count == 0:
        write(path, text.replace(old, new, 1))
    elif not (old_count == 0 and new_count == 1):
        raise SystemExit(
            f"{path}: unknown state for exact edit; old={old_count}, new={new_count}"
        )


def remove_exact_line_if_present(path: str, line: str) -> None:
    text = read(path)
    count = text.count(line)
    if count > 1:
        raise SystemExit(f"{path}: duplicate exact line: {line!r}")
    if count == 1:
        write(path, text.replace(line, "", 1))


def remove_cfg_use_pairs(path: str) -> None:
    text = read(path)
    pattern = rf'#\[cfg\(feature = "{re.escape(LEGACY_FEATURE)}"\)\]\nuse [^\n]+;\n'
    write(path, re.sub(pattern, "", text))


def remove_feature_test_if_present(path: str, function_name: str) -> None:
    text = read(path)
    if f"async fn {function_name}()" not in text:
        return
    pattern = (
        rf'\n#\[cfg\(feature = "{re.escape(LEGACY_FEATURE)}"\)\]\n'
        rf'#\[tokio::test[^\n]*\]\nasync fn {re.escape(function_name)}\(\) \{{.*?'
        rf'(?=\n(?:#\[cfg|#\[tokio::test|#\[test)|\Z)'
    )
    updated, count = re.subn(pattern, "\n", text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{path}: unknown shape for legacy test {function_name}")
    write(path, updated)


# Lane E closed world: six current OP cases and all current native operations.
lane = "scripts/hepta-lane-e-closure.py"
lane_text = read(lane)
case_pattern = r'\*\(f"OP-\{index:02d\}" for index in range\(1,\s*(\d+)\)\),'
match = re.search(case_pattern, lane_text)
if match is None:
    raise SystemExit(f"{lane}: OP case range not found")
upper = int(match.group(1))
if upper == 5:
    lane_text = (
        lane_text[: match.start()]
        + '*(f"OP-{index:02d}" for index in range(1, 7)),'
        + lane_text[match.end() :]
    )
elif upper != 7:
    raise SystemExit(f"{lane}: unexpected OP case upper bound {upper}")

desired_operations = [
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
]
operator_pattern = r'    "learning\.operator": \{\n(?P<body>.*?)\n    \},\n    "learning\.eval": \{'
operator_match = re.search(operator_pattern, lane_text, flags=re.S)
if operator_match is None:
    raise SystemExit(f"{lane}: learning.operator operation set not found")
current_operations = re.findall(r'        "([^"]+)",', operator_match.group("body"))
unknown = set(current_operations) - set(desired_operations)
if unknown:
    raise SystemExit(f"{lane}: unknown concurrent operator operations: {sorted(unknown)}")
desired_body = "\n".join(f'        "{name}",' for name in desired_operations)
lane_text = (
    lane_text[: operator_match.start("body")]
    + desired_body
    + lane_text[operator_match.end("body") :]
)
write(lane, lane_text)

matrix = json.loads(read("docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"))
operator = next(row for row in matrix["modules"] if row["module"] == "learning.operator")
matrix_operations = {row["operation"] for row in operator["operations"]}
if matrix_operations != set(desired_operations):
    raise SystemExit(
        "Lane E operator matrix drift: "
        f"missing={sorted(set(desired_operations) - matrix_operations)}, "
        f"extra={sorted(matrix_operations - set(desired_operations))}"
    )

# Direct signed decision helper is crate-internal; ProductEvaluationRunner is ingress.
ensure_text(
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "pub use signed_evaluation::decide_with_signed_evidence_v2;",
    "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
)

# Delete obsolete raw V1 product append compatibility. Canonical product writes
# are owned by LedgerWriter; Agentd must not retain a second durable journal API.
product = "codex-rs/hepta-agentd/src/intelligence_product.rs"
remove_cfg_use_pairs(product)
for line in [
    "use codex_hepta_learning_ledger::DurableLedgerError;\n",
    "use codex_hepta_learning_ledger::LedgerEvent;\n",
]:
    remove_exact_line_if_present(product, line)
product_text = read(product)
old_comment = "proposal digest or append the exact Decision/Outcome event.\n"
new_comment = (
    "proposal digest. Learning facts are written only through the canonical "
    "LedgerWriter owner.\n"
)
if old_comment in product_text:
    product_text = product_text.replace(old_comment, new_comment, 1)
elif new_comment not in product_text:
    raise SystemExit(f"{product}: product ownership comment has unknown state")
if "pub struct PendingIntelligenceLedgerAppendV1" in product_text:
    pattern = (
        r'\n#\[derive\(Clone, Debug, Eq, PartialEq\)\]\n'
        r'pub struct PendingIntelligenceLedgerAppendV1 \{.*?\n'
        r'impl StdError for AgentdIntelligenceLedgerError \{\}\n'
    )
    product_text, count = re.subn(pattern, "\n", product_text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{product}: legacy append types have unknown shape")
write(product, product_text)

runner = "codex-rs/hepta-agentd/src/intelligence_product_runner.rs"
runner_text = read(runner)
if "pub fn append_decision(" in runner_text:
    pattern = (
        rf'\n    #\[cfg\(feature = "{re.escape(LEGACY_FEATURE)}"\)\]\n'
        r'    pub fn append_decision\(.*?\n    \}\n\}\n\Z'
    )
    runner_text, count = re.subn(pattern, "\n}\n", runner_text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{runner}: legacy append methods have unknown shape")
write(runner, runner_text)

tests = "codex-rs/hepta-agentd/src/intelligence_product_tests.rs"
remove_cfg_use_pairs(tests)
remove_feature_test_if_present(tests, "real_owner_product_path_records_decision_outcome_and_reopens")
remove_feature_test_if_present(tests, "final_use_revocation_race_fails_before_decision_publication")

lib_path = "codex-rs/hepta-agentd/src/lib.rs"
lib_text = read(lib_path)
write(
    lib_path,
    "".join(
        line
        for line in lib_text.splitlines(keepends=True)
        if "AgentdIntelligenceLedgerError" not in line
        and "PendingIntelligenceLedgerAppendV1" not in line
    ),
)

for path in [product, runner, tests, lib_path]:
    text = read(path)
    forbidden = [
        token
        for token in [
            "PendingIntelligenceLedgerAppendV1",
            "AgentdIntelligenceLedgerError",
            "pub fn append_decision(",
            "pub fn append_outcome(",
        ]
        if token in text
    ]
    if forbidden:
        raise SystemExit(f"{path}: legacy product writer surface remains: {forbidden}")

# Topology gate must execute actual topology_v2 tests, never a zero-test filter.
for path in [
    ".github/workflows/hepta-architecture-convergence.yml",
    "scripts/hepta_ci_scope.py",
    "scripts/tests/test_hepta_ci_scope.py",
]:
    text = read(path)
    if "topology_v3" in text:
        write(path, text.replace("topology_v3", "topology_v2"))
    elif "topology_v2" not in text:
        raise SystemExit(f"{path}: no recognized topology test token")

# Keep the existing ObjectiveRuntimeHost/DurableRunStartJournal as sole owner.
for stale in [
    "codex-rs/hepta-agentd/src/objective_ingress.rs",
    "codex-rs/hepta-agentd/src/objective_dispatch.rs",
]:
    path = ROOT / stale
    if path.exists():
        path.unlink()

subprocess.run(
    ["python3", "scripts/hepta-implementation-maps.py", "sync-plasticity-status"],
    cwd=ROOT,
    check=True,
)
print("learning.operator convergence materialization complete")
