"""Verify the frozen one-shot source without importing numerical packages."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent import policy


HERE = Path(__file__).parent
REPOSITORY = HERE.parents[1]
WORKFLOW = REPOSITORY / ".github/workflows/hcsn-currentstate-n256-firststep-dense-oracle-hosted.yml"
ORACLE = REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/dense_oracle.py"
INTENT_REQUEST = REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_hosted_admission_intent/REQUEST.json"
SOURCE_FILES = {
    "README.md": HERE / "README.md", "REQUEST.json": HERE / "REQUEST.json",
    "__init__.py": HERE / "__init__.py", "child.py": HERE / "child.py",
    "launcher.py": HERE / "launcher.py", "requirements.txt": HERE / "requirements.txt",
    "test_launcher.py": HERE / "test_launcher.py", "verify_source.py": HERE / "verify_source.py",
    "workflow": WORKFLOW,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def imports(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    compile(tree, str(path), "exec")
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def main():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    require(request["identity"] == freeze["identity"], "identity")
    require(request["unique_execution_key"] == freeze["unique_execution_key"], "execution key")
    require(request["base_commit"] == "4fd5333e01b6e5e28f5fe7975db8279d0184c7ff", "base")
    require(request["oracle_source_sha256"] == digest(ORACLE) == policy.DENSE_ORACLE_SHA256, "oracle")
    require(request["input_bundle_sha256"] == policy.INPUT_BUNDLE_SHA256, "input")
    require(request["runtime_sha256"] == policy.RUNTIME_SHA256, "runtime")
    require(request["admission_policy_sha256"] == policy.canonical_policy_sha256(), "policy")
    require(request["admission_intent_request_sha256"] == digest(INTENT_REQUEST), "intent request")
    require(request["target"] == {
        "lane": "warm", "lane_order": 1, "time_fraction": [1, 1000],
        **policy.TARGET,
    }, "target")
    require(request["n256_numerical_execution_allowed"] is True, "execution permission")
    require(request["maximum_attempts"] == 1, "attempt budget")
    require(request["historical_negative_and_unknown_preserved"] is True, "history")
    for name in ("largegrid_qualification", "production_adoption", "all_closed"):
        require(request[name] is False, name)

    parent_imports = imports(HERE / "launcher.py")
    require(not ({name.split(".")[0] for name in parent_imports} & {"numpy", "scipy", "torch"}), "parent import")
    child_imports = imports(HERE / "child.py")
    require(any("dense_oracle_source" in name for name in child_imports), "child oracle")
    launcher = (HERE / "launcher.py").read_text()
    require("preexec_fn=_child_limit" in launcher, "preexec ordering")
    require("resource.setrlimit(resource.RLIMIT_AS" in launcher, "rlimit")
    require("None if child_started else 0" in launcher, "UNKNOWN accounting")

    workflow = WORKFLOW.read_text()
    require("workflow_dispatch" not in workflow, "manual duplicate path")
    require("cancel-in-progress: false" in workflow, "cancellation")
    require(workflow.count("dense_oracle_hosted.launcher") == 1, "launcher count")
    require("--only-binary=:all:" in workflow, "binary runtime")
    require("if: always()" in workflow, "RED artifact")
    require("retention-days: 30" in workflow, "retention")

    require(freeze["request_sha256"] == digest(HERE / "REQUEST.json"), "request freeze")
    require(freeze["source_sha256"] == {name: digest(path) for name, path in SOURCE_FILES.items()}, "source freeze")
    require(freeze["source_execution_counts"] == {
        "n256_input_reads": 0, "n256_serializer_calls": 0, "dynamic_steps": 0,
        "dense_expm_actions": 0, "torch_calls": 0, "optimizer_steps": 0,
    }, "source counts")
    require(freeze["all_closed"] is False, "all closed")
    print(json.dumps({
        "identity": request["identity"], "status": "SOURCE_FROZEN_ONE_ATTEMPT",
        "stdlib_controls": 4, "source_dynamic_steps": 0,
        "source_dense_expm_actions": 0, "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
