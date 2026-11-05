#!/usr/bin/env python3
"""Exercise the workflow's real audit with fixtures, never native test credit."""

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


BASE = "d206c3c787f6b67c771b67a8e1d46c8261810042"
RELATIVE = ".github/workflows/hepta-pq-policy-renewal.yml"
AUDIT = "Require every selected test by name with no selected skip"
NEW_STEPS = {
    "recovery-owner": "Run the seven recovery snapshot and ACK provenance controls",
    "recovery-signed": "Run the two signed recovery frontier controls",
}
MODULES = {
    "recovery_effect_frontier_tests": "codex-rs/hepta-evidence/src/recovery_effect_frontier_tests.rs",
    "provider_effect_recovery_provenance_tests": "codex-rs/hepta-evidence/src/provider_effect_recovery_provenance_tests.rs",
    "evidence_frontier::tests": "codex-rs/hepta-agentd/src/evidence_frontier_tests.rs",
}


def audit_code(document):
    step = next(x for x in document["jobs"]["policy-renewal"]["steps"] if x.get("name") == AUDIT)
    return step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0] + "\n"


def expected_cases(code):
    nodes = [
        node for node in ast.parse(code).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in {"prefix", "expected"} for target in node.targets)
    ]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<audit-selection>", "exec"), namespace)
    return namespace["expected"]


def normalized_audit(code):
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets):
            pairs = [(key, value) for key, value in zip(node.value.keys, node.value.values) if key.value not in NEW_STEPS]
            node.value.keys = [key for key, _ in pairs]
            node.value.values = [value for _, value in pairs]
    return ast.dump(tree, include_attributes=False)


def main():
    repository, edited, output = map(Path, sys.argv[1:])
    old_text = subprocess.check_output(["git", "show", BASE + ":" + RELATIVE], cwd=repository, text=True)
    new_bytes = (edited / RELATIVE).read_bytes()
    old, new = yaml.safe_load(old_text), yaml.safe_load(new_bytes)
    old_code, new_code = audit_code(old), audit_code(new)
    expected = expected_cases(new_code)
    previous = expected_cases(old_code)
    assert {key: expected[key] for key in previous} == previous
    assert {key: len(names) for key, names in expected.items()} == {
        "dispatcher": 14, "product": 3, "recovery-owner": 7, "recovery-signed": 2,
    }
    assert normalized_audit(old_code) == normalized_audit(new_code)
    old_without_audit = copy.deepcopy(old)
    new_without_additions = copy.deepcopy(new)
    old_without_audit["jobs"]["policy-renewal"]["steps"] = [
        step for step in old_without_audit["jobs"]["policy-renewal"]["steps"] if step.get("name") != AUDIT
    ]
    new_without_additions["jobs"]["policy-renewal"]["steps"] = [
        step for step in new_without_additions["jobs"]["policy-renewal"]["steps"]
        if step.get("name") not in {AUDIT, *NEW_STEPS.values()}
    ]
    assert old_without_audit == new_without_additions
    spec = importlib.util.spec_from_file_location("repo_nextest_wrapper", repository / "scripts/run-nextest.py")
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    steps = {step.get("name"): step for step in new["jobs"]["policy-renewal"]["steps"]}
    selectors = {}
    for suite, step_name in NEW_STEPS.items():
        step = steps[step_name]
        argv = shlex.split(step["run"])
        expression = argv[argv.index("-E") + 1]
        selected = re.findall(r"test\(=([A-Za-z0-9_:]+)\)", expression)
        assert len(selected) == len(expected[suite]) and set(selected) == expected[suite]
        assert expression == " | ".join("test(=" + name + ")" for name in selected)
        assert wrapper.graph_free_filter(expression)
        assert argv[:2] == ["python3", "scripts/hepta_ci_exec.py"]
        assert argv[argv.index("--minimum-tests") + 1] == str(len(selected))
        assert argv[argv.index("--timeout-seconds") + 1] == "600"
        assert argv[argv.index("--") + 1 : argv.index("--") + 4] == ["just", "test", "--locked"]
        assert argv[argv.index("--retries") + 1] == "0"
        assert "--lib" in argv and "--no-capture" in argv and "--test-threads=1" in argv
        assert step["if"] == steps["Run all fourteen original and added dispatcher controls"]["if"]
        assert step["env"] == {"CARGO_NET_OFFLINE": "true"}
        for full_name in selected:
            module, name = full_name.rsplit("::", 1)
            source = (repository / MODULES[module]).read_text()
            assert re.search(r"^async fn " + re.escape(name) + r"\(", source, re.M), full_name
        selectors[suite] = {"filter": expression, "names": selected}
    fixtures = [("all_26_named_controls", None, None, None, True), ("only_original_17", None, None, "old_only", False)]
    for suite in NEW_STEPS:
        for name in sorted(expected[suite]):
            for mutation in ("missing", "ignored", "duplicate"):
                fixtures.append((suite + ":" + name + ":" + mutation, suite, name, mutation, False))
        for mutation in ("zero", "digest", "exit", "status", "count", "failed_summary", "extra"):
            fixtures.append((suite + ":" + mutation, suite, None, mutation, False))
    results = []
    for label, target, selected, mutation, should_pass in fixtures:
        with tempfile.TemporaryDirectory(prefix="recovery-ci-audit-") as directory:
            root = Path(directory)
            for suite, names in expected.items():
                if mutation == "old_only" and suite in NEW_STEPS:
                    continue
                cases = [(name, "ok") for name in sorted(names)]
                record = {"status": "passed", "command_exit_code": 0, "observed_passed_tests": len(names), "observed_failed_tests": 0, "log_file": suite + ".log"}
                if suite == target:
                    if mutation == "missing": cases = [(name, status) for name, status in cases if name != selected]
                    elif mutation == "ignored": cases = [(name, "ignored" if name == selected else status) for name, status in cases]
                    elif mutation == "duplicate": cases.append((selected, "ok"))
                    elif mutation == "zero": cases = []
                    elif mutation == "extra": cases.append(("unexpected_test", "ok"))
                    elif mutation == "exit": record["command_exit_code"] = 101
                    elif mutation == "status": record["status"] = "failed"
                    elif mutation == "count": record["observed_passed_tests"] -= 1
                    elif mutation == "failed_summary": record["observed_failed_tests"] = 1
                raw = "".join("test " + name + " ... " + status + "\n" for name, status in cases).encode()
                record["log_sha256"] = hashlib.sha256(raw).hexdigest()
                if suite == target and mutation == "digest": record["log_sha256"] = "0" * 64
                (root / record["log_file"]).write_bytes(raw)
                (root / (suite + ".json")).write_text(json.dumps(record))
            process = subprocess.run([sys.executable, "-c", new_code, str(root)], text=True, capture_output=True, check=False)
            observations = json.loads((root / "selected-tests.json").read_text())
            actual = process.returncode == 0
            assert actual == should_pass, (label, process.returncode, process.stdout, process.stderr)
            if actual: assert all(item["passed"] for item in observations.values())
            else: assert any(not item["passed"] for item in observations.values())
            results.append({"case": label, "audit_exit_code": process.returncode, "expected_acceptance": should_pass, "matched": True})
    receipt = {
        "kind": "CI_SOURCE_AND_SELECTION_AUDIT_FIXTURES_ONLY",
        "base_commit": BASE,
        "workflow_path": RELATIVE,
        "workflow_git_blob": hashlib.sha1(b"blob " + str(len(new_bytes)).encode() + b"\0" + new_bytes).hexdigest(),
        "workflow_sha256": hashlib.sha256(new_bytes).hexdigest(),
        "preserved_original_workflow_configuration_and_17_controls": True,
        "real_rust_source_names_checked": 9,
        "selectors": selectors,
        "audit_fixture_results": results,
        "fixture_cases_passed": len(results),
        "native_tests_executed": 0,
        "ci_triggered": False,
        "qualification": "HOLD_NO_GO",
    }
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"selectors", "audit_fixture_results"}}, indent=2))


if __name__ == "__main__":
    main()
