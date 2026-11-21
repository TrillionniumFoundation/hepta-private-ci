"""Verify the zero-numerical Ubuntu 24.04 repair without numerical code."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).parent
REPOSITORY = HERE.parents[1]
WORKFLOW = REPOSITORY / ".github/workflows/hepta-contract-gate.yml"
OPENBAO = REPOSITORY / ".github/workflows/openbao-compatibility.yml"
HOSTED_WORKFLOW = REPOSITORY / ".github/workflows/hcsn-currentstate-n256-firststep-dense-oracle-hosted.yml"
FREEZE_WORKFLOW = REPOSITORY / ".github/workflows/hcsn-currentstate-n256-execution-freeze-protocol.yml"
ORIGINAL = REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted"
ORIGINAL_SOURCE_PATHS = {
    "README.md": ORIGINAL / "README.md",
    "REQUEST.json": ORIGINAL / "REQUEST.json",
    "__init__.py": ORIGINAL / "__init__.py",
    "child.py": ORIGINAL / "child.py",
    "launcher.py": ORIGINAL / "launcher.py",
    "requirements.txt": ORIGINAL / "requirements.txt",
    "test_launcher.py": ORIGINAL / "test_launcher.py",
    "verify_source.py": ORIGINAL / "verify_source.py",
}
SOURCE_FILES = {
    "README.md": HERE / "README.md",
    "DISPATCH_001_REJECTION.json": HERE / "DISPATCH_001_REJECTION.json",
    "DISPATCH_002_REJECTION.json": HERE / "DISPATCH_002_REJECTION.json",
    "DISPATCH_003_REJECTION.json": HERE / "DISPATCH_003_REJECTION.json",
    "PUSH_CONTRACT_REJECTION.json": HERE / "PUSH_CONTRACT_REJECTION.json",
    "PUSH_HOSTED_REJECTION.json": HERE / "PUSH_HOSTED_REJECTION.json",
    "PUSH_FREEZE_REJECTION.json": HERE / "PUSH_FREEZE_REJECTION.json",
    "PUSH_PYTHON_REJECTION.json": HERE / "PUSH_PYTHON_REJECTION.json",
    "PYTHON_RUNTIME_AVAILABILITY.json": HERE / "PYTHON_RUNTIME_AVAILABILITY.json",
    "NO_RUN_CHAIN.json": HERE / "NO_RUN_CHAIN.json",
    "REQUEST.json": HERE / "REQUEST.json",
    "__init__.py": HERE / "__init__.py",
    "test_bridge.py": HERE / "test_bridge.py",
    "verify_source.py": HERE / "verify_source.py",
    "registered_workflow": WORKFLOW,
    "hosted_workflow": HOSTED_WORKFLOW,
    "freeze_protocol_workflow": FREEZE_WORKFLOW,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    observed = json.loads((HERE / "NO_RUN_CHAIN.json").read_text())
    rejected = json.loads((HERE / "DISPATCH_001_REJECTION.json").read_text())
    rejected2 = json.loads((HERE / "DISPATCH_002_REJECTION.json").read_text())
    rejected3 = json.loads((HERE / "DISPATCH_003_REJECTION.json").read_text())
    original_freeze = json.loads((ORIGINAL / "SOURCE_FREEZE.json").read_text())
    push_rejections = [
        json.loads((HERE / name).read_text())
        for name in ("PUSH_CONTRACT_REJECTION.json", "PUSH_HOSTED_REJECTION.json", "PUSH_FREEZE_REJECTION.json")
    ]
    runtime_rejection = json.loads((HERE / "PUSH_PYTHON_REJECTION.json").read_text())
    runtime_availability = json.loads((HERE / "PYTHON_RUNTIME_AVAILABILITY.json").read_text())
    require(request["identity"] == freeze["identity"], "identity")
    require(request["base_commit"] == observed["sources"][1]["head"], "base observation")
    require(request["original_launcher_request_sha256"] == digest(ORIGINAL / "REQUEST.json"), "original request")
    require(request["original_launcher_sha256"] == digest(ORIGINAL / "launcher.py"), "original launcher")
    require(request["original_source_freeze_sha256"] == digest(ORIGINAL / "SOURCE_FREEZE.json"), "original freeze")
    require(all(original_freeze["source_sha256"][name] == digest(path) for name, path in ORIGINAL_SOURCE_PATHS.items()), "original numerical source")
    require(request["prior_dedicated_run_count"] == request["prior_numerical_attempt_count"] == 0, "prior attempt")
    require(request["maximum_numerical_attempts"] == 1 and request["manual_dispatch_limit"] == 0, "attempt budget")
    require(request["trigger_event"] == "push", "trigger event")
    require(request["trigger_parent"] == "57cce86bc0f31c5fdf0549a76db9a65f1c97c0ef", "trigger parent")
    require(request["prior_push_source_tree"] == "cbeb33a520677364fef04b7086a532d08d1fdacd", "prior tree")
    require(request["prior_dispatch_rejections"] == 3, "dispatch rejection count")
    require(request["prior_push_admission_rejections"] == 3, "push rejection count")
    require(request["prior_runtime_admission_rejections"] == 1, "runtime rejection count")
    require(request["registered_workflow_id"] == 356353926, "registered workflow")
    require(request["registered_dispatch_success_run_id"] == 40463001551, "dispatch proof")
    require(request["prior_actions_run_count"] == 4, "Actions run count")
    require(request["prior_actions_job_count"] == 1 and request["prior_artifact_count"] == 0, "job/artifact count")
    require(observed["cumulative_numerical_attempts"] == 0, "no-run chain")
    require(all(item["dedicated_run_id"] is None for item in observed["sources"]), "run claim")
    require(rejected["github_http_status"] == 422 and rejected["h_exit_code"] == 1, "dispatch RED")
    require(rejected["actions_run_id"] is rejected["actions_job_id"] is rejected["artifact_id"] is None, "dispatch no-run")
    require(rejected["dynamic_steps"] == rejected["dense_expm_actions"] == 0, "dispatch numerical count")
    require(rejected2["github_http_status"] == 422 and rejected2["h_exit_code"] == 1, "second dispatch RED")
    require(rejected2["actions_run_id"] is rejected2["actions_job_id"] is rejected2["artifact_id"] is None, "second no-run")
    require(rejected2["dynamic_steps"] == rejected2["dense_expm_actions"] == 0, "second numerical count")
    require(rejected3["github_http_status"] == 422 and rejected3["h_exit_code"] == 1, "third dispatch RED")
    require(rejected3["actions_run_id"] is rejected3["actions_job_id"] is rejected3["artifact_id"] is None, "third no-run")
    require(rejected3["dynamic_steps"] == rejected3["dense_expm_actions"] == 0, "third numerical count")
    expected_runs = {44846825298, 44846823906, 44846822585}
    expected_lines = {100, 36, 52}
    require({item["actions_run_id"] for item in push_rejections} == expected_runs, "push run identities")
    require({int(item["annotation"].rsplit("L", 1)[1]) for item in push_rejections} == expected_lines, "annotation lines")
    require(all(item["event"] == "push" and item["status"] == "completed" and item["conclusion"] == "failure" for item in push_rejections), "push RED")
    require(all(item["actions_job_count"] == item["artifact_count"] == 0 for item in push_rejections), "admission before job")
    require(all(item["dynamic_steps"] == item["dense_expm_actions"] == item["optimizer_steps"] == 0 for item in push_rejections), "push numerical count")
    require(runtime_rejection["source_head"] == request["trigger_parent"], "runtime rejection parent")
    require(runtime_rejection["source_tree"] == request["prior_push_source_tree"], "runtime rejection tree")
    require((runtime_rejection["actions_run_id"], runtime_rejection["actions_job_id"], runtime_rejection["check_suite_id"]) == (44847784583, 136671635724, 121386660926), "runtime RED identities")
    require(runtime_rejection["checkout_completed"] is True and runtime_rejection["setup_python_completed"] is False, "setup-python RED")
    require(all(runtime_rejection[name] is False for name in ("install_completed", "verifier_completed", "tests_completed", "launcher_completed")), "runtime admission boundary")
    require(runtime_rejection["artifact_count"] == 0, "runtime artifact count")
    require(all(runtime_rejection[name] == 0 for name in ("n256_input_reads", "n256_serializer_calls", "dynamic_steps", "dense_expm_actions", "torch_calls", "optimizer_steps")), "runtime numerical count")
    require(runtime_availability["manifest_blob_sha"] == request["python_versions_manifest_blob_sha"] == "8468b3406cb309a299b2ead4109d0a2b2467153b", "runtime manifest")
    require(runtime_availability["python_version"] == request["python_version"] == "3.12.3", "exact Python")
    require(runtime_availability["selected_runner"] == request["runner_label"] == "ubuntu-24.04", "explicit runner")
    require(runtime_availability["selected_file"] == request["python_versions_manifest_file"] == "python-3.12.3-linux-24.04-x64.tar.gz", "runtime archive")
    require(runtime_availability["selected_file_available"] is True and runtime_availability["rejected_matching_file_available"] is False, "runtime availability")
    require(runtime_availability["runtime_execution"] is False, "availability is read-only")
    workflow = WORKFLOW.read_text()
    require("hcsn_n256_one_shot" not in workflow, "no branch-only input")
    require("github.event_name == 'push'" in workflow, "push trigger")
    require("if: ${{ github.ref_name != 'research/hcsn-n256-firststep-dense-oracle-ubuntu24-repair-20261120-c06d' }}" in workflow, "contract default")
    require(request["exact_head_branch"] in workflow, "branch guard")
    require(workflow.count("runs-on: ubuntu-24.04") == 2 and "runs-on: ubuntu-latest" not in workflow, "explicit supported runner")
    require("python-version: 3.12.3" in workflow, "exact Python request")
    require(workflow.count("dense_oracle_hosted.launcher") == 1, "launcher count")
    require("if: always()" in workflow, "RED custody")
    invalid_plain = "run: python -m pip install --only-binary=:all: -r"
    for candidate in (workflow, HOSTED_WORKFLOW.read_text(), FREEZE_WORKFLOW.read_text()):
        require(invalid_plain not in candidate, "invalid plain run scalar")
        require("run: >-" in candidate and "python -m pip install --only-binary=:all: -r" in candidate, "folded install scalar")
    require("hcsn-n256-one-shot" not in OPENBAO.read_text(), "OpenBao restoration")
    require(freeze["request_sha256"] == digest(HERE / "REQUEST.json"), "request freeze")
    require(freeze["source_sha256"] == {name: digest(path) for name, path in SOURCE_FILES.items()}, "source freeze")
    require(freeze["source_execution_counts"] == {
        "n256_input_reads": 0, "n256_serializer_calls": 0, "dynamic_steps": 0,
        "dense_expm_actions": 0, "torch_calls": 0, "optimizer_steps": 0,
    }, "source counts")
    require(freeze["all_closed"] is False, "all closed")
    print(json.dumps({
        "identity": request["identity"], "status": "UBUNTU24_REPAIR_REFROZEN_AFTER_ZERO_NUMERICAL_RUNTIME_RED",
        "prior_numerical_attempts": 0, "source_dynamic_steps": 0,
        "source_dense_expm_actions": 0, "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
