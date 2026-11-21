"""Verify the registered dispatch bridge without running numerical code."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).parent
REPOSITORY = HERE.parents[1]
WORKFLOW = REPOSITORY / ".github/workflows/openbao-compatibility.yml"
ORIGINAL = REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted"
SOURCE_FILES = {
    "README.md": HERE / "README.md",
    "NO_RUN_CHAIN.json": HERE / "NO_RUN_CHAIN.json",
    "REQUEST.json": HERE / "REQUEST.json",
    "__init__.py": HERE / "__init__.py",
    "test_bridge.py": HERE / "test_bridge.py",
    "verify_source.py": HERE / "verify_source.py",
    "registered_workflow": WORKFLOW,
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
    require(request["identity"] == freeze["identity"], "identity")
    require(request["base_commit"] == observed["sources"][1]["head"], "base observation")
    require(request["original_launcher_request_sha256"] == digest(ORIGINAL / "REQUEST.json"), "original request")
    require(request["original_launcher_sha256"] == digest(ORIGINAL / "launcher.py"), "original launcher")
    require(request["original_source_freeze_sha256"] == digest(ORIGINAL / "SOURCE_FREEZE.json"), "original freeze")
    require(request["prior_dedicated_run_count"] == request["prior_numerical_attempt_count"] == 0, "prior attempt")
    require(request["maximum_numerical_attempts"] == request["manual_dispatch_limit"] == 1, "attempt budget")
    require(observed["cumulative_numerical_attempts"] == 0, "no-run chain")
    require(all(item["dedicated_run_id"] is None for item in observed["sources"]), "run claim")
    workflow = WORKFLOW.read_text()
    require("default: false" in workflow, "default opt-out")
    require("if: ${{ !inputs.hcsn_n256_one_shot }}" in workflow, "OpenBao default")
    require(request["exact_head_branch"] in workflow, "branch guard")
    require(workflow.count("dense_oracle_hosted.launcher") == 1, "launcher count")
    require("if: always()" in workflow, "RED custody")
    require(freeze["request_sha256"] == digest(HERE / "REQUEST.json"), "request freeze")
    require(freeze["source_sha256"] == {name: digest(path) for name, path in SOURCE_FILES.items()}, "source freeze")
    require(freeze["source_execution_counts"] == {
        "n256_input_reads": 0, "n256_serializer_calls": 0, "dynamic_steps": 0,
        "dense_expm_actions": 0, "torch_calls": 0, "optimizer_steps": 0,
    }, "source counts")
    require(freeze["all_closed"] is False, "all closed")
    print(json.dumps({
        "identity": request["identity"], "status": "REGISTERED_DISPATCH_BRIDGE_SOURCE_FROZEN",
        "prior_numerical_attempts": 0, "source_dynamic_steps": 0,
        "source_dense_expm_actions": 0, "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
