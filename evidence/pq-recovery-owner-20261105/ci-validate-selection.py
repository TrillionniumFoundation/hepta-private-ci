#!/usr/bin/env python3
"""Exercise the workflow's actual audit with fixtures; no native or CI credit.

Requires Python 3 and PyYAML. Outputs a new, create-only source-audit receipt.
The retained baseline is the exact upstream workflow blob, not a reconstruction
of a complete upstream checkout. Rust names and fixture logs are source checks.
"""

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

import yaml


BASELINE_BLOB = "c07b903bc589096f5927ee224abd10684d9a3c82"
REFERENCE_VALIDATOR_BLOB = "f54bb28e39e648b15fbb6051d4139ba5e55006c2"
RELATIVE = ".github/workflows/hepta-pq-policy-renewal.yml"
AUDIT = "Require every selected test by name with no selected skip"
OLD_SIGNED_STEP = "Run the two signed recovery frontier controls"
SIGNED_STEP = "Run the nine PQ recovery frontier controls"
PRODUCT_STEP = "Run the four real Agentd evidence recovery process controls"
OLD_DEPENDENCY_STEP = "Fetch the unchanged locked dependency graph"
DEPENDENCY_STEP = "Fetch the locked current dependency graph"
FIX_STEP = "Run the original scoped linter and retain any source mutation as failure"
COUNTS = {"dispatcher": 14, "product": 3, "recovery-owner": 7,
          "recovery-signed": 9, "recovery-product": 4}
PRESERVED = {"dispatcher", "product", "recovery-owner"}
EXACT_STEPS = {
    "recovery-owner": ("Run the seven recovery snapshot and ACK provenance controls", "600", "--lib"),
    "recovery-signed": (SIGNED_STEP, "600", "--lib"),
    "recovery-product": (PRODUCT_STEP, "1800", "kernel_evidence_product"),
}
MODULES = {
    "authbus_dispatch::tests": "codex-rs/hepta-agentd/src/authbus_dispatch_tests.rs",
    "authbus_dispatch::tests::pq": "codex-rs/hepta-agentd/src/authbus_pq_dispatch_tests.rs",
    "authbus_dispatch::tests::lease_delay": "codex-rs/hepta-agentd/src/authbus_lease_delay_tests.rs",
    "authbus_dispatch::tests::policy_rollback": "codex-rs/hepta-agentd/src/authbus_policy_rollback_tests.rs",
    "authbus_dispatch::tests::checkpoint_sync": "codex-rs/hepta-agentd/src/authbus_checkpoint_sync_tests.rs",
    "recovery_effect_frontier_tests": "codex-rs/hepta-evidence/src/recovery_effect_frontier_tests.rs",
    "provider_effect_recovery_provenance_tests": "codex-rs/hepta-evidence/src/provider_effect_recovery_provenance_tests.rs",
    "evidence_frontier::tests": "codex-rs/hepta-agentd/src/evidence_frontier_tests.rs",
}
PRODUCT_SOURCES = {
    "product": "codex-rs/hepta-agentd/tests/authbus_text_product.rs",
    "recovery-product": "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
}


def blob_id(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def audit_code(document):
    step = next(item for item in document["jobs"]["policy-renewal"]["steps"]
                if item.get("name") == AUDIT)
    return step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0] + "\n"


def expected_cases(code):
    nodes = [node for node in ast.parse(code).body
             if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id in {"prefix", "expected"}
                     for target in node.targets)]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<actual-audit-selection>", "exec"), namespace)
    return namespace["expected"]


def normalized_audit(code):
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "expected" for target in node.targets
        ):
            pairs = [(key, value) for key, value in zip(node.value.keys, node.value.values)
                     if key.value in PRESERVED]
            node.value.keys = [key for key, _ in pairs]
            node.value.values = [value for _, value in pairs]
    return ast.dump(tree, include_attributes=False)


def trigger_paths(document):
    # PyYAML's YAML 1.1 loader represents the GitHub key `on` as True.
    return document.get("on", document.get(True))["pull_request"]["paths"]


def check_preserved_workflow(old, new):
    before, after = copy.deepcopy(old), copy.deepcopy(new)
    for path in ("codex-rs/hepta-infer-worker-host/**",
                 "evidence/pq-recovery-owner-20261105/ci-*"):
        assert trigger_paths(after).count(path) == 1, path
        trigger_paths(after).remove(path)
    before["jobs"]["policy-renewal"]["steps"] = [
        step for step in before["jobs"]["policy-renewal"]["steps"]
        if step.get("name") not in {AUDIT, OLD_SIGNED_STEP}
    ]
    after["jobs"]["policy-renewal"]["steps"] = [
        step for step in after["jobs"]["policy-renewal"]["steps"]
        if step.get("name") not in {AUDIT, SIGNED_STEP, PRODUCT_STEP}
    ]
    for step in after["jobs"]["policy-renewal"]["steps"]:
        if step.get("name") == DEPENDENCY_STEP:
            step["name"] = OLD_DEPENDENCY_STEP
        if step.get("name") == FIX_STEP:
            suffix = " -p codex-hepta-infer-worker-host"
            assert step["run"].endswith(suffix)
            step["run"] = step["run"][:-len(suffix)]
    # Budgets, matrix, lanes, environment, action pins and all old 24 controls
    # survive exactly, apart from the explicit changes normalized above.
    assert before == after, "an unrelated workflow field or original gate changed"


def check_sources(repository, expected):
    inspected = {}
    for suite, names in expected.items():
        for full_name in names:
            if suite in PRODUCT_SOURCES:
                relative, name = PRODUCT_SOURCES[suite], full_name
            else:
                module, name = full_name.rsplit("::", 1)
                relative = MODULES[module]
            raw = (repository / relative).read_bytes()
            source = raw.decode("utf-8")
            match = re.search(r"((?:^#\[[^\]]+\]\s*)+)(?:async )?fn "
                              + re.escape(name) + r"\(", source, re.M)
            assert match is not None, (relative, full_name)
            assert re.search(r"#\[(?:tokio::)?test(?:\(|\])", match[1]), full_name
            assert "#[ignore" not in match[1], full_name
            inspected[relative] = {"git_blob": blob_id(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return inspected


def check_selectors(repository, document, expected):
    specification = importlib.util.spec_from_file_location(
        "repo_nextest_wrapper", repository / "scripts/run-nextest.py")
    wrapper = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(wrapper)
    steps = {step.get("name"): step for step in document["jobs"]["policy-renewal"]["steps"]}
    result = {}
    for suite, (name, timeout, target) in EXACT_STEPS.items():
        step = steps[name]
        arguments = shlex.split(step["run"])
        expression = arguments[arguments.index("-E") + 1]
        selected = re.findall(r"test\(=([A-Za-z0-9_:]+)\)", expression)
        assert len(selected) == len(expected[suite]) and set(selected) == expected[suite]
        assert expression == " | ".join("test(=" + item + ")" for item in selected)
        assert wrapper.graph_free_filter(expression)
        assert arguments[:2] == ["python3", "scripts/hepta_ci_exec.py"]
        assert arguments[arguments.index("--minimum-tests") + 1] == str(COUNTS[suite])
        assert arguments[arguments.index("--timeout-seconds") + 1] == timeout
        assert arguments[arguments.index("--output") + 1] == "$RUNNER_TEMP/pq-policy-renewal/" + suite + ".json"
        assert arguments[arguments.index("--") + 1:arguments.index("--") + 4] == ["just", "test", "--locked"]
        assert arguments[arguments.index("--retries") + 1] == "0"
        assert "--no-capture" in arguments and "--test-threads=1" in arguments
        if target == "--lib":
            assert target in arguments and "--test" not in arguments
        else:
            assert arguments[arguments.index("--test") + 1] == target and "--lib" not in arguments
        package = "codex-hepta-evidence" if suite == "recovery-owner" else "codex-hepta-agentd"
        assert arguments[arguments.index("-p") + 1] == package
        assert step["if"] == steps["Run all fourteen original and added dispatcher controls"]["if"]
        assert step["env"] == {"CARGO_NET_OFFLINE": "true"}
        result[suite] = {"filter": expression, "names": selected, "timeout_seconds": int(timeout)}
    return result


def exercise_actual_audit(code, expected):
    fixtures = [("all_37_named_controls", None, None, None, True),
                ("only_preserved_24_controls", None, None, "old_only", False),
                ("old_classical_v1_name", "recovery-signed",
                 "evidence_frontier::tests::recovery_frontier_refuses_valid_classical_v1_and_v2_signatures",
                 "stale_name", False)]
    for suite, names in expected.items():
        for name in sorted(names):
            for mutation in ("missing", "ignored", "duplicate"):
                fixtures.append((suite + ":" + name + ":" + mutation, suite, name, mutation, False))
        for mutation in ("absent_group", "zero", "digest", "exit", "status", "count", "failed_summary", "extra"):
            fixtures.append((suite + ":" + mutation, suite, None, mutation, False))
    results = []
    for label, target, selected, mutation, should_pass in fixtures:
        with tempfile.TemporaryDirectory(prefix="pq-recovery-ci-audit-") as directory:
            root = Path(directory)
            for suite, names in expected.items():
                if (mutation == "old_only" and suite not in PRESERVED
                        or mutation == "absent_group" and suite == target):
                    continue
                cases = [(name, "ok") for name in sorted(names)]
                record = {"status": "passed", "command_exit_code": 0,
                          "observed_passed_tests": len(names), "observed_failed_tests": 0,
                          "log_file": suite + ".log"}
                if suite == target:
                    if mutation == "missing":
                        cases = [(name, status) for name, status in cases if name != selected]
                    elif mutation == "ignored":
                        cases = [(name, "ignored" if name == selected else status) for name, status in cases]
                    elif mutation == "duplicate":
                        cases.append((selected, "ok"))
                    elif mutation == "stale_name":
                        cases = [("evidence_frontier::tests::recovery_frontier_refuses_a_valid_old_v1_signature"
                                  if name == selected else name, status) for name, status in cases]
                    elif mutation == "zero":
                        cases = []
                    elif mutation == "extra":
                        cases.append(("unexpected_test", "ok"))
                    elif mutation == "exit":
                        record["command_exit_code"] = 101
                    elif mutation == "status":
                        record["status"] = "failed"
                    elif mutation == "count":
                        record["observed_passed_tests"] -= 1
                    elif mutation == "failed_summary":
                        record["observed_failed_tests"] = 1
                raw = "".join("test " + name + " ... " + status + "\n" for name, status in cases).encode()
                record["log_sha256"] = hashlib.sha256(raw).hexdigest()
                if suite == target and mutation == "digest":
                    record["log_sha256"] = "0" * 64
                (root / record["log_file"]).write_bytes(raw)
                (root / (suite + ".json")).write_text(json.dumps(record))
            process = subprocess.run([sys.executable, "-c", code, str(root)],
                                     text=True, capture_output=True, check=False)
            observations = json.loads((root / "selected-tests.json").read_text())
            assert (process.returncode == 0) == should_pass, (label, process.stderr)
            assert all(item["passed"] for item in observations.values()) == should_pass
            results.append({"case": label, "audit_exit_code": process.returncode,
                            "expected_acceptance": should_pass, "matched": True})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new output file; refuses overwrite")
    arguments = parser.parse_args()
    repository = arguments.repository.resolve(strict=True)
    if arguments.output.exists() or arguments.output.is_symlink():
        parser.error("--output already exists; source receipts are create-only")
    baseline = Path(__file__).with_name("ci-baseline-workflow.yml").read_bytes()
    assert blob_id(baseline) == BASELINE_BLOB, "retained baseline differs from the upstream blob"
    new_bytes = (repository / RELATIVE).read_bytes()
    old, new = yaml.safe_load(baseline), yaml.safe_load(new_bytes)
    old_code, new_code = audit_code(old), audit_code(new)
    expected, previous = expected_cases(new_code), expected_cases(old_code)
    assert {suite: len(names) for suite, names in expected.items()} == COUNTS
    assert {suite: expected[suite] for suite in PRESERVED} == {suite: previous[suite] for suite in PRESERVED}
    assert normalized_audit(old_code) == normalized_audit(new_code), "audit logic changed beyond selected names"
    check_preserved_workflow(old, new)
    sources = check_sources(repository, expected)
    selectors = check_selectors(repository, new, expected)
    results = exercise_actual_audit(new_code, expected)
    receipt = {
        "kind": "CI_SOURCE_AND_SELECTION_AUDIT_FIXTURES_ONLY",
        "reference_validator_git_blob": REFERENCE_VALIDATOR_BLOB,
        "baseline_workflow_git_blob": BASELINE_BLOB,
        "inspected_checkout_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
        "workflow_path": RELATIVE,
        "workflow_git_blob": blob_id(new_bytes),
        "workflow_sha256": hashlib.sha256(new_bytes).hexdigest(),
        "validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "preserved_original_workflow_configuration_and_24_controls": True,
        "mandatory_audit_logic_unchanged_except_selected_names": True,
        "suite_counts": COUNTS,
        "real_rust_source_names_checked": sum(COUNTS.values()),
        "inspected_source_files": sources,
        "selectors": selectors,
        "audit_fixture_results": results,
        "fixture_cases_passed": len(results),
        "native_tests_executed": 0,
        "ci_triggered": False,
        "qualification": "HOLD_NO_GO",
    }
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in receipt.items()
                      if key not in {"inspected_source_files", "selectors", "audit_fixture_results"}}, indent=2))


if __name__ == "__main__":
    main()
