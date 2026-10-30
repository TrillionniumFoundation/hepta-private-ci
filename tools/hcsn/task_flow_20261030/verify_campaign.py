"""Verify delivery identities without converting scientific failures into passes.

This is a receipt/source audit, not a replacement for each independent numerical
or task evaluation. It does not rerun training or regenerate heldout cohorts.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
HCSN = HERE.parent
REPOSITORY = HERE.parents[2]


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output=None):
    checks = []

    def identities(label, root, mapping):
        bad = [name for name, expected in mapping.items()
               if not (root / name).is_file() or digest(root / name) != expected]
        checks.append(dict(name=label, files=len(mapping), mismatches=bad, passed=not bad))

    baseline = read(HERE / "BASELINE_FILES.json")
    identities("historical_files_unchanged", REPOSITORY, baseline["files"])
    for attempt in ("attempt001", "attempt002"):
        folder = HERE / "flow" / "results" / attempt
        mapping = read(folder / "source_hashes.json")
        identities("flow_snapshot_" + attempt, folder / "source", mapping)
        if attempt == "attempt002":
            identities("flow_current_matches_final_audit", HERE / "flow", mapping)
    memory_freeze = read(HERE / "memory" / "freeze.json")
    identities("memory_scientific_freeze", HCSN, memory_freeze["source_sha256"])
    control_freeze = read(HERE / "control" / "freeze.json")
    identities("control_scientific_freeze", HERE / "control", control_freeze["source_sha256"])
    identities("control_inherited_content", HCSN, control_freeze["inherited_sha256"])
    v2_freeze = read(HERE / "control_v2" / "freeze.json")
    identities("control_v2_scientific_freeze", HERE / "control_v2", v2_freeze["source_sha256"])
    identities("control_v2_preserves_original_trial", HERE, v2_freeze["reused_v1_sha256"])
    identities("control_v2_inherited_content", HCSN, v2_freeze["inherited_hcsn_sha256"])
    package = read(HERE / "memory" / "PACKAGE_MANIFEST.json")
    identities("memory_delivery_manifest", HERE / "memory", {r["path"]: r["sha256"] for r in package["files"]})
    archive = read(HERE / "control" / "evidence_archives.json")
    identities("control_archive_bytes", HERE / "control", {r["path"]: r["sha256"] for r in archive["archives"]})
    v2_archives = read(HERE / "control_v2" / "evidence_archives.json")
    identities("control_v2_archive_bytes", HERE / "control_v2", {r["path"]: r["sha256"] for r in v2_archives["archives"]})
    v2_package = read(HERE / "control_v2" / "delivery_manifest.json")
    identities("control_v2_delivery_manifest", HERE / "control_v2", {name: r["sha256"] for name, r in v2_package["files"].items()})
    syntax_errors, future_imports, sources = [], [], list(HERE.rglob("*.py"))
    for source in sources:
        relative = str(source.relative_to(HERE))
        try:
            tree = ast.parse(source.read_text(), filename=relative)
        except SyntaxError as exc:
            syntax_errors.append(dict(path=relative, reason=str(exc)))
            continue
        if any(isinstance(node, ast.ImportFrom) and node.module == "__future__" for node in ast.walk(tree)):
            future_imports.append(relative)
    checks.append(dict(name="python_syntax_and_repository_import_rule", files=len(sources),
                       syntax_errors=syntax_errors, future_imports=future_imports,
                       passed=not syntax_errors and not future_imports))
    flow = read(HERE / "flow" / "results" / "attempt002" / "results.json")
    memory = read(HERE / "memory" / "results.json")
    replay = read(HERE / "memory" / "audit.json")
    summary = read(HERE / "memory" / "summary.json")
    control = read(HERE / "control" / "audit.json")
    v2 = read(HERE / "control_v2" / "confirmation.json")
    v2_audit = read(HERE / "control_v2" / "audit.json")
    checks.extend([
        dict(name="memory_completed_unique_matrix", passed=memory["complete"] and len(memory["runs"]) == 30),
        dict(name="memory_all_evidence_invariants", passed=all(replay["evidence"].values())),
        dict(name="memory_summary_bound_to_raw_audit", passed=summary["results_sha256"] == digest(HERE / "memory" / "results.json")
             and summary["audit_sha256"] == digest(HERE / "memory" / "audit.json")),
        dict(name="control_integrity_and_real_actions", passed=control["integrity_passed"] and control["causal"]["passed"]),
        dict(name="control_v2_original_integrity", passed=v2_audit["integrity_passed"]),
        dict(name="control_v2_independent_rewards_and_files", passed=read(HERE / "control_v2" / "delivery_audit.json")["passed"]),
        dict(name="all_raw_archives_restored", passed=read(HERE / "control" / "restoration_validation.json")["passed"]
             and read(HERE / "memory" / "archive_validation.json")["passed"]
             and read(HERE / "control_v2" / "restoration_validation.json")["passed"]),
    ])
    receipts = ["control/audit.json", "control/restoration_validation.json",
                "memory/audit.json", "memory/archive_validation.json", "memory/replay_diagnosis.json",
                "control_v2/audit.json", "control_v2/delivery_audit.json",
                "control_v2/restoration_validation.json"]
    result = dict(recorded_utc=datetime.now(timezone.utc).isoformat(), baseline_commit=baseline["commit"],
                  integrity_passed=all(c["passed"] for c in checks), checks=checks,
                  receipt_sha256={name: digest(HERE / name) for name in receipts},
                  numerical_and_scientific_verdicts=dict(
                      flow_fp64_finite_model_passed=flow["passed"], flow_checks=len(flow["checks"]),
                      memory_strict_replay_passed=replay["passed"],
                      memory_strict_replay_conditions=len(replay["checks"]),
                      memory_strict_replay_failed=sum(not c["passed"] for c in replay["checks"]),
                      memory_joint_quality_passed=summary["quality_gate"]["passed"],
                      financial_shape_positive_gates=summary["positive_shape_gates"],
                      control_v1_benefit_passed=control["primary_scientific_gate_passed"],
                      control_v2_development_passed=read(HERE / "control_v2" / "gate.json")["passed"],
                      control_v2_heldout_benefit_passed=v2["primary"]["benefit_passed"]),
                  formatter=dict(original_command="cd codex-rs && just fmt", original_status="unavailable_in_sparse_checkout",
                                 observed_exit=1, reason="codex-rs is absent; just and Rust are not on the task PATH; no Rust files changed"),
                  scope="Identity and delivery verification only. A successful receipt audit does not override any false numerical or scientific verdict.")
    text = json.dumps(result, indent=2) + "\n"
    if output:
        with Path(output).open("x") as handle:
            handle.write(text)
    print(text)
    return 0 if result["integrity_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="New receipt path; refuses to replace an existing receipt")
    raise SystemExit(main(parser.parse_args().output))
