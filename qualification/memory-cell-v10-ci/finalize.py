"""Authenticate exact successful verification, then scoped fix and final format only."""

import base64
import os
import subprocess

from common import BASELINE, PACKAGE_NAMES, PACKAGES, ROOT, actual_command, git, git_text, identity, ordinary_command, require, save, source_inventory
from github_gate import authenticate
from verify import REQUIRED


def gate(runner, receipt):
    proof = receipt["request"]["verification"]
    verified, sources, index = authenticate(proof, runner.output)
    require(verified.get("schema") == "hepta.memory.v10.ci-receipt.v1" and verified.get("passed") is True
            and verified.get("mode") == "verify" and verified.get("source_commit") == proof["commit"]
            and verified.get("source_tree") == proof["tree"] and verified.get("initial_tracked_changes") == ""
            and verified.get("final_tracked_changes") == "" and verified.get("tests_executed") is True
            and verified.get("tests_before_final_fix_and_format") is True
            and verified.get("final_fix_executed") is False and verified.get("formatter_executed") is False
            and verified.get("ordinary_scoped_tests_passed") is True
            and verified.get("actual_trained_owner_lifecycle_passed") is True
            and verified.get("missing_required_receipts") == [] and verified.get("old_holdout_run") is False,
            "authenticated receipt is not completed clean V10 verification")
    for field in ("baseline_commit", "source_manifest_sha256", "protocol_sha256"):
        require(verified["request"][field] == receipt["request"][field], "verified research source identity differs")
    for field, value in (("GITHUB_RUN_ID", proof["run_id"]), ("GITHUB_RUN_ATTEMPT", proof["run_attempt"]),
                         ("GITHUB_SHA", proof["commit"])):
        require(verified["github"].get(field) == str(value), "verify receipt CI identity differs")
    executions = verified.get("executions")
    require(isinstance(executions, list) and executions and all(row.get("exit_code") == 0 for row in executions),
            "verification contains failed or incomplete commands")
    tests = [row["command"] for row in executions if row.get("command", [])[:2] == ["just", "test"]]
    require(tests == [ordinary_command(), actual_command()], "verification did not run both exact required test commands")
    require(verified.get("source_inventory") == index["files"].get("memory-v10-ci-output/SOURCE_FILES.json"),
            "verified source inventory receipt differs from authenticated archive")
    require(verified.get("required_native_artifacts") is not None
            and set(verified["required_native_artifacts"]) == set(REQUIRED), "native evidence inventory differs")
    for name in REQUIRED:
        require(verified["required_native_artifacts"][name] == index["files"].get("memory-v10-ci-output/native-actual/" + name),
                "required native artifact is absent from authenticated archive: " + name)
    current = source_inventory()
    require(current == sources, "protected source bytes/modes/inventory changed since successful verification")
    save(runner.output / "SOURCE_FILES.json", current)
    receipt.update(tested_source_gate_passed=True, tested_commit=proof["commit"], tested_tree=proof["tree"],
                   source_inventory=identity(runner.output / "SOURCE_FILES.json"), research_quality_pass_asserted=False)
    return current


def tracked_tree(output):
    index = output / "temporary.index"
    environment = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        subprocess.check_call(["git", "read-tree", "HEAD"], cwd=ROOT, env=environment)
        subprocess.check_call(["git", "add", "-u", "--", "."], cwd=ROOT, env=environment)
        return subprocess.check_output(["git", "write-tree"], cwd=ROOT, env=environment, text=True).strip()
    finally:
        index.unlink(missing_ok=True)


def stage(runner, receipt, name, before):
    tree = tracked_tree(runner.output)
    path = runner.output / (name + ".patch")
    path.write_bytes(git("diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-renames", before, "--"))
    row = {"name": name, "before_tree": before, "after_tree": tree, "patch": {"path": path.name, **identity(path)}}
    receipt.setdefault("stages", []).append(row)
    save(runner.output / (name + ".json"), row)
    return tree


def unchanged_inputs(before):
    after = source_inventory()
    require(set(after) == set(before), "finalization changed the protected source inventory")
    allowed = tuple("codex-rs/hepta-" + name + "/" for name in PACKAGE_NAMES)
    changed = [name for name in before if after[name] != before[name]]
    require(all(name.startswith(allowed) and name.endswith(".rs") for name in changed),
            "fix/format modified frozen Python, workflow, fixture or an unscoped source")
    return {name: after[name] for name in changed}


def run(runner, receipt):
    before = gate(runner, receipt)
    save(runner.output / "receipt.json", receipt)
    # The checkout remains depth one. Only this exact immutable baseline object
    # is fetched for the existing scoped formatter. Credentials are step-local,
    # supplied through Git configuration in the child environment, never argv.
    if subprocess.run(["git", "cat-file", "-e", BASELINE + "^{commit}"], cwd=ROOT, capture_output=True).returncode:
        origin = git_text("remote", "get-url", "origin")
        require(origin.rstrip("/").removesuffix(".git") == "https://github.com/TrillionniumFoundation/hepta-private-ci",
                "unexpected origin for fixed baseline fetch")
        environment = dict(os.environ)
        count = int(environment.get("GIT_CONFIG_COUNT", "0"))
        require(0 <= count <= 16 and bool(environment.get("GH_TOKEN")), "invalid Git read credential configuration")
        encoded = base64.b64encode(("x-access-token:" + environment["GH_TOKEN"]).encode()).decode()
        environment.update({"GIT_CONFIG_COUNT": str(count + 1),
                            f"GIT_CONFIG_KEY_{count}": "http.https://github.com/.extraheader",
                            f"GIT_CONFIG_VALUE_{count}": "AUTHORIZATION: basic " + encoded})
        runner.execute("fetch-fixed-format-base", ["git", "fetch", "--no-tags", "--depth=1", "origin", BASELINE], env=environment)
    target = os.environ.get("CARGO_TARGET_DIR", "")
    require(os.path.isabs(target), "absolute Cargo target directory required")
    receipt["tests_executed"] = False
    receipt["clippy_compiles_test_targets"] = True
    command = ["just", "fix", "--locked", *[arg for package in PACKAGES for arg in ("-p", package)]]
    receipt["final_fix_executed"] = True
    save(runner.output / "receipt.json", receipt)
    try:
        runner.execute("scoped-final-fix", command)
    finally:
        after_fix = stage(runner, receipt, "after-fix", receipt["source_tree"])
    unchanged_inputs(before)
    receipt["formatter_executed"] = True
    save(runner.output / "receipt.json", receipt)
    try:
        runner.execute("final-format", ["just", "fmt", "--base", BASELINE])
    finally:
        receipt["after_tracked_tree"] = stage(runner, receipt, "after-format", after_fix)
    save(runner.output / "AFTER_FILES.json", unchanged_inputs(before))
    receipt.update(passed=True, tests_executed_after_fix_or_format=False,
                   frozen_non_rust_inputs_unchanged=True, automatic_commit=False, automatic_push=False)
