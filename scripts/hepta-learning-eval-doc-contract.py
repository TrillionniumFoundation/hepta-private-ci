#!/usr/bin/env python3
"""Fail-closed documentation and source-contract checks for learning.eval.

This verifier checks references and scoped claims. It does not execute Rust code,
authenticate a target host, or issue acceptance/release authority.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/modules/learning.eval"
EVAL = ROOT / "codex-rs/hepta-intelligence-eval"

EXTERNAL_FALSE = (
    "targetHostQualified",
    "independentAcceptance",
    "independentAcceptanceIssued",
    "activation",
    "activationAuthorized",
    "release",
    "releaseAuthorized",
)
REQUIRED_FILTERS = (
    "signed_qualification_e2e",
    "evaluated_shadow",
    "plasticity_product",
    "signed_candidate_passes_only_with_bound_owner_run_context_and_root_trust",
    "multi_outcome_consumer_rejects_context_owner_and_signature_substitution",
    "cold_process_recovery_uses_only_persisted_inputs_and_current_trust",
)
REQUIRED_SYMBOLS = {
    "codex-rs/hepta-intelligence-eval/src/lib.rs": ("pub mod product;",),
    "codex-rs/hepta-intelligence-eval/src/product.rs": (
        "Canonical, authority-free product qualification facade",
        "RecordedProductEvaluationRunnerV1",
    ),
    "codex-rs/hepta-intelligence-eval/src/recorded_runner.rs": (
        "RecordedProductEvaluationRunnerV1",
        "failure::product_evaluation_failure_digest_v2",
    ),
    "codex-rs/hepta-intelligence-eval/src/recorded_failure.rs": (
        "hepta.learning-eval.product-evaluation-failure.v2",
        "product_evaluation_failure_digest_v2",
    ),
    "codex-rs/hepta-intelligence-eval/src/attempt_journal.rs": (
        "ProductEvaluationAttemptPhaseV1",
        "IntentPersisted",
        "PublicationPending",
    ),
    "codex-rs/hepta-intelligence-eval/src/signed_admission.rs": (
        "admit_signed_eligibility_v2",
        "consumer_binding_digest",
    ),
    "codex-rs/hepta-intelligence-eval/src/reconciled_sink.rs": (
        "ReconciledProductQualificationSinkV1",
    ),
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def walk_items(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            yield path, child
            yield from walk_items(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_items(child, f"{prefix}[{index}]")


def reject_bare_verified(value: dict[str, Any]) -> None:
    offenders = [
        path for path, _ in walk_items(value) if path.rsplit(".", 1)[-1] == "verified"
    ]
    if offenders:
        raise ValueError("bare verified claim is prohibited: " + ", ".join(offenders))


def require_external_false(value: dict[str, Any], label: str) -> None:
    for path, child in walk_items(value):
        key = path.rsplit(".", 1)[-1]
        if key in EXTERNAL_FALSE and child is not False:
            raise ValueError(f"{label} externally self-issues {path}={child!r}")


def source_inventory() -> str:
    roots = [
        ROOT / "codex-rs/hepta-intelligence-eval",
        ROOT / "codex-rs/hepta-intelligence",
        ROOT / "codex-rs/hepta-agentd",
    ]
    parts: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.rs")):
            parts.append(path.read_text(encoding="utf-8", errors="strict"))
    return "\n".join(parts)


def validate_trusted_reporter_call_chain(workflow: str, entry: str) -> None:
    """Check the trusted wrapper path without importing or executing its code."""
    if re.search(r"(?m)^[ \t]+with:[ \t]*\{", workflow):
        raise ValueError("trusted reporter step inputs must use block mappings")
    refs = re.findall(r"(?m)^[ \t]+ref:[ \t]*(.*?)[ \t]*$", workflow)
    if [value.strip("\"'") for value in refs] != [
        "${{ github.event.repository.default_branch }}"
    ]:
        raise ValueError("trusted reporter must checkout only the default branch")

    run_blocks: list[list[str]] = []
    run_indent: int | None = None
    for line in workflow.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if run_indent is not None and line.strip() and indent <= run_indent:
            run_indent = None
        if re.fullmatch(r"(?:- )?run: \|[-+]?", line.strip()):
            run_indent = indent
            run_blocks.append([])
        elif run_indent is not None:
            command = re.match(
                r"python3[ \t]+(?:\./)?scripts/(hepta-learning-eval-[a-z-]+\.py)(?:[ \t]|$)",
                line.strip(),
            )
            if command:
                run_blocks[-1].append(command.group(1))
    commands = [command for block in run_blocks for command in block]
    wrapper = "hepta-learning-eval-trusted-entry.py"
    if commands.count(wrapper) != 1:
        raise ValueError(
            "trusted reporter workflow must invoke the hardened entry exactly once"
        )
    if "hepta-learning-eval-trusted-report.py" in commands:
        raise ValueError("trusted reporter workflow bypasses the hardened entry")
    block = next(block for block in run_blocks if wrapper in block)
    identity = "hepta-learning-eval-control-plane-identity.py"
    if identity not in block[: block.index(wrapper)]:
        raise ValueError(
            "trusted reporter must verify control-plane identity before entry"
        )

    tree = ast.parse(entry)
    bindings: dict[str, list[ast.expr]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(node.value)
    script_dirs = bindings.get("SCRIPT_DIR", [])
    expected_dir = ast.parse("Path(__file__).resolve().parent", mode="eval").body
    if len(script_dirs) != 1 or ast.dump(script_dirs[0]) != ast.dump(expected_dir):
        raise ValueError(
            "trusted entry reporter directory must be its own trusted script directory"
        )
    inventories = bindings.get("TRUSTED_CONTROL_PLANE_PATHS", [])
    if len(inventories) != 1:
        raise ValueError("trusted entry byte-identity inventory is ambiguous")
    paths = ast.literal_eval(inventories[0])
    if not isinstance(paths, tuple) or not {
        "scripts/hepta-learning-eval-trusted-entry.py",
        "scripts/hepta-learning-eval-trusted-report.py",
    }.issubset(paths):
        raise ValueError(
            "trusted entry and reporter must both be bound by byte identity"
        )
    reporters = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "reporter"
    ]
    imports = [
        node
        for function in reporters
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_module"
    ]
    expected_import = ast.parse(
        'load_module("hepta_learning_eval_trusted_report", '
        'SCRIPT_DIR / "hepta-learning-eval-trusted-report.py")',
        mode="eval",
    ).body
    if len(imports) != 1 or ast.dump(imports[0]) != ast.dump(expected_import):
        raise ValueError(
            "trusted entry must load the reporter from its fixed trusted path"
        )


def check(root: Path = ROOT) -> None:
    if root != ROOT:
        raise ValueError("alternate roots are not supported by the production verifier")
    required_docs = (
        "DEVELOPER_GUIDE.md",
        "AUDIT_INDEX.md",
        "QUALIFICATION_MATRIX.json",
        "TECHNICAL.md",
        "CURRENT_STATUS.json",
        "IMPLEMENTATION_MAP.json",
    )
    for name in required_docs:
        if not (DOCS / name).is_file():
            raise ValueError(f"missing learning.eval document: {name}")

    guide = (DOCS / "DEVELOPER_GUIDE.md").read_text(encoding="utf-8")
    for index, title in enumerate(
        (
            "Mission and non-goals",
            "Authority model",
            "Product call path",
            "State machine",
            "Persistence and recovery",
            "Statistical contract",
            "Failure taxonomy",
            "Deployment topology",
            "Qualification checklist",
            "Known gaps",
        ),
        start=1,
    ):
        if f"## {index}. {title}" not in guide:
            raise ValueError(f"developer guide is missing section {index}: {title}")
    if guide.count("```mermaid") < 3:
        raise ValueError("developer guide must contain three normative diagrams")
    if "trusted default-branch" not in guide:
        raise ValueError(
            "developer guide does not explain the privileged reporting boundary"
        )

    audit = (DOCS / "AUDIT_INDEX.md").read_text(encoding="utf-8")
    for name in required_docs:
        if name not in audit and name != "AUDIT_INDEX.md":
            raise ValueError(f"audit index does not reference {name}")
    if "workflow_run" not in audit or "untrusted data" not in audit:
        raise ValueError("audit index does not document trusted PR reporting semantics")

    current = load_json(DOCS / "CURRENT_STATUS.json")
    matrix = load_json(DOCS / "QUALIFICATION_MATRIX.json")
    implementation = load_json(DOCS / "IMPLEMENTATION_MAP.json")
    reject_bare_verified(current)
    reject_bare_verified(matrix)
    reject_bare_verified(implementation)
    require_external_false(current, "CURRENT_STATUS.json")
    require_external_false(matrix, "QUALIFICATION_MATRIX.json")
    require_external_false(implementation, "IMPLEMENTATION_MAP.json")
    if matrix.get("authority") != "DENY_ALL" or matrix.get("releasePosture") != "NO_GO":
        raise ValueError("qualification matrix must remain authority-free NO_GO")
    source_facts = matrix.get("sourceFacts")
    if not isinstance(source_facts, dict):
        raise ValueError("qualification matrix source facts are missing")
    for fact in (
        "candidateExecutionReadOnlyWorkflowSourcePresent",
        "mainOnlyAttestationIsolationSourcePresent",
        "stalePrHeadReportRejectionSourcePresent",
        "trustedDefaultBranchWorkflowRunReporterSourcePresent",
        "untrustedArtifactValidationSourcePresent",
    ):
        if source_facts.get(fact) is not True:
            raise ValueError(
                f"qualification matrix is missing scoped source fact: {fact}"
            )

    inventory = source_inventory()
    for required in REQUIRED_FILTERS:
        if required not in inventory:
            raise ValueError(
                f"required nextest filter does not name a Rust test/symbol: {required}"
            )
    if "signed_candidate_passes_only_on_bound_current_owner_and_context" in (
        ROOT / "scripts/hepta-learning-eval-exact-entry.py"
    ).read_text(encoding="utf-8"):
        raise ValueError("stale Agentd qualification filter remains in exact entry")

    for relative, symbols in REQUIRED_SYMBOLS.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for symbol in symbols:
            if symbol not in text:
                raise ValueError(f"{relative} is missing required symbol/text {symbol}")
    runner = (EVAL / "src/recorded_runner.rs").read_text(encoding="utf-8")
    if 'format!("{error:?}")' in runner:
        raise ValueError("durable failure identity still hashes Rust Debug output")

    facade_test = EVAL / "tests/product_facade_compile.rs"
    if not facade_test.is_file():
        raise ValueError("canonical product facade compile test is missing")

    fixture = EVAL / "fixtures/trusted-inprocess"
    if (
        not (fixture / "Cargo.toml.in").is_file()
        or not (fixture / "tests/operator_claim.rs").is_file()
    ):
        raise ValueError("isolated trusted compatibility fixture is incomplete")
    wrapper = (EVAL / "tests/operator_claim.rs").read_text(encoding="utf-8")
    if "fixtures/trusted-inprocess/tests/operator_claim.rs" not in wrapper:
        raise ValueError(
            "historical operator_claim target is not a thin fixture wrapper"
        )

    exact_entry = (ROOT / "scripts/hepta-learning-eval-exact-entry.py").read_text(
        encoding="utf-8"
    )
    for required in REQUIRED_FILTERS:
        if required not in exact_entry:
            raise ValueError(f"exact entry does not guard filter {required}")
    for script in (
        "hepta-nextest-require.py",
        "hepta-learning-eval-compat-fixture.py",
        "hepta-learning-eval-aggregate.py",
        "hepta-learning-eval-exact-summary.py",
        "hepta-learning-eval-pr-status.py",
        "hepta-learning-eval-trusted-entry.py",
        "hepta-learning-eval-trusted-report.py",
        "test_hepta_learning_eval_trusted_report.py",
    ):
        if not (ROOT / "scripts" / script).is_file():
            raise ValueError(f"missing qualification script: {script}")

    convergence = (
        ROOT / ".github/workflows/hepta-learning-eval-convergence.yml"
    ).read_text(encoding="utf-8")
    exact = (ROOT / ".github/workflows/hepta-learning-eval-exact.yml").read_text(
        encoding="utf-8"
    )
    reporter = (
        ROOT / ".github/workflows/hepta-learning-eval-trusted-report.yml"
    ).read_text(encoding="utf-8")
    for needle in (
        "hepta-learning-eval-aggregate.py",
        "hepta-learning-eval-compat-fixture.py",
        "hepta-learning-eval-doc-contract.py",
        "test_hepta_learning_eval_trusted_report.py",
    ):
        if needle not in convergence:
            raise ValueError(f"convergence workflow is missing {needle}")
    for needle in (
        "hepta-learning-eval-exact-entry.py",
        "hepta-learning-eval-exact-summary.py",
        "test_hepta_learning_eval_trusted_report.py",
    ):
        if needle not in exact:
            raise ValueError(f"exact workflow is missing {needle}")
    for label, workflow in (("convergence", convergence), ("exact", exact)):
        if "pull-requests: write" in workflow:
            raise ValueError(
                f"{label} candidate-execution workflow has write permission"
            )
        if "hepta-learning-eval-pr-status.py" in workflow:
            raise ValueError(
                f"{label} candidate-execution workflow performs privileged PR updates"
            )
        if "needs.identity-recorder.outputs.tested_sha" in workflow:
            raise ValueError(f"{label} workflow checks out a job-output-derived ref")
        if (
            workflow.count("id-token: write") != 1
            or workflow.count("attestations: write") != 1
        ):
            raise ValueError(
                f"{label} must contain exactly one isolated attestation permission block"
            )
        attestation_job = workflow.find("\n  attest-")
        if attestation_job < 0:
            raise ValueError(f"{label} main-only attestation job is missing")
        privileged = min(
            workflow.find("id-token: write"), workflow.find("attestations: write")
        )
        if privileged < attestation_job:
            raise ValueError(
                f"{label} grants attestation authority before the isolated job"
            )
    for needle in (
        "workflow_run:",
        "Hepta learning.eval convergence",
        "Hepta learning.eval exact trees",
        "pull-requests: write",
        "github.event.repository.default_branch",
        "actions/download-artifact@",
        "hepta-learning-eval-trusted-entry.py",
    ):
        if needle not in reporter:
            raise ValueError(f"trusted reporter workflow is missing {needle}")
    if "ref: ${{ github.event.workflow_run.head_sha }}" in reporter:
        raise ValueError("trusted reporter must not checkout candidate source")
    validate_trusted_reporter_call_chain(
        reporter,
        (ROOT / "scripts/hepta-learning-eval-trusted-entry.py").read_text(
            encoding="utf-8"
        ),
    )
    for workflow in (convergence, exact):
        if "github.ref == 'refs/heads/main'" not in workflow:
            raise ValueError(
                "attestation permission is not isolated to a main-only job"
            )

    operations = implementation.get("operations")
    if not isinstance(operations, list) or not any(
        isinstance(operation, dict)
        and operation.get("nativeSymbol") == "product_evaluation_failure_digest_v2"
        and operation.get("sourcePath")
        == "codex-rs/hepta-intelligence-eval/src/recorded_failure.rs"
        for operation in operations
    ):
        raise ValueError("implementation map does not bind typed failure encoding V2")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        check(args.root.resolve())
        print("learning.eval documentation/source contract: PASS")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
