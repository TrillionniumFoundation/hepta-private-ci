"""Static verifier for the unexecuted hosted admission intent."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent.policy import (
    DENSE_ORACLE_SHA256,
    IDENTITY,
    INPUT_BUNDLE_SHA256,
    POLICY,
    RUNTIME_SHA256,
    TARGET,
    canonical_policy_sha256,
)


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]
WORKFLOW = REPOSITORY / ".github/workflows/hcsn-currentstate-n256-firststep-hosted-admission-intent.yml"

BOUND_PATHS = {
    "development_red_sha256": ROOT / "DEVELOPMENT_RED.json",
    "dense_oracle_request_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/REQUEST.json",
    "dense_oracle_source_freeze_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/SOURCE_FREEZE.json",
    "dense_oracle_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/dense_oracle.py",
    "hosted_runtime_request_v2_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_hosted_runtime_snapshot/REQUEST_V2.json",
    "hosted_runtime_source_freeze_v2_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_hosted_runtime_snapshot/SOURCE_FREEZE_V2.json",
    "hosted_observation_attempt002_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_hosted_runtime_snapshot/evidence/attempt002/HOSTED_OBSERVATION.json",
    "hosted_observation_review_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_hosted_runtime_snapshot/evidence/attempt002/INDEPENDENT_REVIEW.json",
}

SOURCE_PATHS = {
    "DEVELOPMENT_RED.json": ROOT / "DEVELOPMENT_RED.json",
    "README.md": ROOT / "README.md",
    "REQUEST.json": ROOT / "REQUEST.json",
    "__init__.py": ROOT / "__init__.py",
    "policy.py": ROOT / "policy.py",
    "test_policy.py": ROOT / "test_policy.py",
    "verify_source.py": ROOT / "verify_source.py",
    "workflow": WORKFLOW,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _check_stdlib_only(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    compile(tree, str(path), "exec")
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    _require(not any(name.split(".")[0] in {"numpy", "scipy", "torch"} for name in imports), "numerical import")


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    _require(request["identity"] == freeze["identity"] == IDENTITY, "identity")
    _require(request["base_commit"] == "4f58ca6b956620fcea05d52e274aa9fc6ac3d29b", "base commit")
    _require(request["future_target"] == TARGET, "future target")
    _require(request["future_resource_policy"] == POLICY, "future resource policy")

    observed_bindings = {name: digest(path) for name, path in BOUND_PATHS.items()}
    observed_bindings.update({
        "runtime_sha256": RUNTIME_SHA256,
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "canonical_policy_sha256": canonical_policy_sha256(),
    })
    _require(request["bindings"] == observed_bindings, "parent bindings")
    _require(request["bindings"]["dense_oracle_sha256"] == DENSE_ORACLE_SHA256, "oracle identity")

    observation = json.loads(BOUND_PATHS["hosted_observation_attempt002_sha256"].read_text())
    observed = observation["observation"]
    _require(observed["runtime_sha256"] == RUNTIME_SHA256, "observed runtime")
    _require(observation["runtime_admitted"] is False, "observed runtime claim")
    _require(observation["resource_admitted"] is False, "observed resource claim")
    _require(observed["allocation_contract"] is None, "observed allocation claim")
    _require(observed["calendar_contract"] is None, "observed calendar claim")
    _require(observed["counts"] == {
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "n256_input_reads": 0,
        "n256_serializer_calls": 0,
        "optimizer_steps": 0,
        "torch_calls": 0,
    }, "observed zero counts")

    _require(set(request["required_future_originals"].values()) == {None}, "future originals claimed")
    for name in (
        "runtime_admitted", "resource_admitted", "n256_numerical_execution_allowed",
        "largegrid_qualification", "production_adoption", "all_closed",
    ):
        _require(request[name] is False, f"false claim: {name}")
    for name in (
        "n256_input_reads", "n256_serializer_calls", "dynamic_steps",
        "matrix_exponential_actions", "torch_calls", "optimizer_steps",
    ):
        _require(request[name] == 0, f"nonzero claim: {name}")
    _require(request["historical_negative_and_unknown_preserved"] is True, "history preservation")
    development_red = json.loads((ROOT / "DEVELOPMENT_RED.json").read_text())
    _require(development_red["preserved"] is True, "development RED preservation")
    for name in (
        "n256_input_reads", "n256_serializer_calls", "dynamic_steps",
        "matrix_exponential_actions", "torch_calls", "optimizer_steps",
    ):
        _require(development_red[name] == 0, f"development RED nonzero: {name}")

    for path in (ROOT / "policy.py", ROOT / "test_policy.py", ROOT / "verify_source.py"):
        _check_stdlib_only(path)
    workflow = WORKFLOW.read_text()
    _require("pip install" not in workflow, "workflow installs numerical dependencies")
    _require("dense_oracle" not in workflow, "workflow invokes dense oracle")
    _require("cancel-in-progress: false" in workflow, "workflow cancellation policy")

    source_sha256 = {name: digest(path) for name, path in SOURCE_PATHS.items()}
    _require(freeze["source_sha256"] == source_sha256, "source freeze")
    _require(freeze["request_sha256"] == digest(ROOT / "REQUEST.json"), "request freeze")
    _require(freeze["bindings"] == observed_bindings, "freeze bindings")
    for name in (
        "n256_input_reads", "n256_serializer_calls", "dynamic_steps",
        "matrix_exponential_actions", "torch_calls", "optimizer_steps",
    ):
        _require(freeze[name] == 0, f"freeze nonzero: {name}")
    _require(freeze["all_closed"] is False, "freeze all-closed claim")

    print(json.dumps({
        "identity": IDENTITY,
        "status": request["status"],
        "canonical_policy_sha256": canonical_policy_sha256(),
        "stdlib_controls": 7,
        "n256_numerical_execution_allowed": False,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
