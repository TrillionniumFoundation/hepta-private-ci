"""Inspect pinned real-run inputs without granting execution or learning authority.

The existing native Cell journal must authenticate ownership, isolation and meters.
This module checks bytes, the complete design and public input projection. It does
not run incoming executables, certify a declared principal, or implement native
receipt verification. Even complete static inputs remain Inconclusive.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from ndu_portfolio.factorial import COSTS, RESEARCH, validate_protocol

from .materials import _read, _strict_json, check_file, load_public_case, validate_materials
from .state import exact_fields, sha256_value


SCHEMA = "hepta.text-image-execution-plan.v1"
FAMILY_MAP = {
    "text_sufficient": "text_sufficient",
    "text_image_complementary": "complementary",
    "selective_refinement": "asymmetric",
    "preparation_required": "prepare_then_gain",
    "continuation_not_worthwhile": "stop_worthwhile",
}
SPLIT_MAP = {"train": "train", "development": "validation", "confirmation": "test"}
PLAN_FIELDS = (
    "schema", "experiment_id", "stage", "material_manifest", "source_registry",
    "protocol", "providers", "evaluator", "objective", "meter", "cost_contract",
    "power_plan", "power_review", "native_owner",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    _require(isinstance(value, str) and 0 < len(value) <= 512 and "\x00" not in value,
             "expected bounded nonempty identity")
    return value


def _pinned_json(root, path, pin):
    sha256_value(pin, "external artifact pin")
    raw, digest, _ = _read(root, path, 8 * 1024 * 1024)
    _require(digest == pin, "artifact differs from external pin")
    return _strict_json(raw)


def _materials(root, manifest_path, registry_path, manifest_pin, registry_pin, stage):
    manifest = _pinned_json(root, manifest_path, manifest_pin)
    report = validate_materials(root, manifest_path, registry_path,
        expected_registry_sha256=registry_pin, stage=stage)
    _require(report["manifest_sha256"] == manifest_pin, "manifest changed during admission")
    return manifest, report


def actor_public_input(root, manifest_path, registry_path, *, expected_manifest_sha256,
                       expected_registry_sha256, case_id, split):
    """Trusted host projection for one registered case; not an OS sandbox.

    The host supplies the original split and external pins, never the actor.
    Only this return value may cross into the actor; do not share the material
    root, full manifest, reference files, or this privileged callable with it.
    Confirmation scheduling/lock enforcement belongs to the native owner.
    """
    _require(split in (*SPLIT_MAP, "retention"), "unknown original case split")
    manifest, _ = _materials(root, manifest_path, registry_path,
        expected_manifest_sha256, expected_registry_sha256,
        "confirmation" if split == "confirmation" else "development")
    matches = [case for case in manifest["cases"] if case["id"] == case_id]
    _require(len(matches) == 1 and matches[0]["split"] == split,
             "case absent or original split differs")
    case = matches[0]
    # Construct a closed input; never pass the full record to an actor/provider.
    public = load_public_case(root, {"text": case["text"], "image": case["image"]})
    # Immutable storage prevents a provider from re-enabling NumPy writes.
    pixels = public["image_rgb"]
    public["image_rgb"] = np.frombuffer(pixels.tobytes(), dtype=pixels.dtype).reshape(pixels.shape)
    return public


def inspect_execution(root, plan_path, *, expected_plan_sha256,
                      expected_manifest_sha256, expected_registry_sha256):
    """Return actionable missing/failed prerequisites, never an admission receipt.

    Missing files/null slots are Inconclusive. A performed integrity or contract
    check that fails is Failed. No callback or JSON real/verified flag can bypass
    the explicitly unimplemented native authentication boundary.
    """
    result = {
        "schema": "hepta.text-image-execution-readiness.v1",
        "outcome": "Inconclusive", "checks": {}, "blockers": [],
        "native_receipt_verification": "NOT_IMPLEMENTED",
        "evaluator_isolation_verification": "NOT_IMPLEMENTED",
        "execution_started": False, "execution_authorized": False,
        "scientific_admission": False, "adoption_authorized": False,
    }

    def block(code, scope, action):
        result["blockers"].append({"code": code, "scope": scope, "required_action": action})

    def check(scope, operation):
        try:
            value = operation()
        except FileNotFoundError:
            result["checks"][scope] = "MISSING"
            block("missing_artifact", scope, "Supply the original externally registered artifact.")
        except Exception as error:
            result["outcome"] = "Failed"
            result["checks"][scope] = "FAILED"
            block("verification_failed", scope,
                  f"Resolve {type(error).__name__}: {str(error)[:240]}")
        else:
            result["checks"][scope] = "VERIFIED"
            return value
        return None

    def artifact(binding, scope, *, expected=None, parse=False):
        if binding is None:
            result["checks"][scope] = "MISSING"
            block("missing_artifact", scope, "Supply a nonempty pinned artifact; null is unknown.")
            return None

        def verify():
            if expected is not None:
                sha256_value(expected, "external identity")
                _require(binding["sha256"] == expected, "binding differs from registered identity")
            _require(binding["bytes"] > 0, "empty artifact cannot establish an executable or contract")
            raw = check_file(root, binding, limit=8 * 1024 * 1024 if parse else 64 * 1024**3,
                             retain=parse)
            if parse:
                value = _strict_json(raw)
                _require(isinstance(value, dict), "expected a JSON object artifact")
                return value
            return True
        return check(scope, verify)

    for name, pin in (("plan_pin", expected_plan_sha256), ("manifest_pin", expected_manifest_sha256),
                      ("registry_pin", expected_registry_sha256)):
        if pin is None or pin == "":
            result["checks"][name] = "MISSING"
            block("missing_external_pin", name, "Obtain the pin from the independent registration record.")
    if result["blockers"]:
        return result

    plan = check("plan", lambda: _pinned_json(root, plan_path, expected_plan_sha256))
    if plan is None:
        return result

    def plan_shape():
        exact_fields(plan, PLAN_FIELDS, "execution plan")
        _require(plan["schema"] == SCHEMA, "unknown execution plan schema")
        _require(plan["stage"] in ("development", "confirmation"), "unknown study stage")
        _text(plan["experiment_id"])
        return True
    if check("plan_structure", plan_shape) is None:
        return result
    manifest = artifact(plan["material_manifest"], "material_manifest",
                        expected=expected_manifest_sha256, parse=True)
    registry = artifact(plan["source_registry"], "source_registry",
                        expected=expected_registry_sha256, parse=True)
    if manifest is not None and registry is not None:
        def admit_materials():
            current, report = _materials(root, plan["material_manifest"]["path"],
                plan["source_registry"]["path"], expected_manifest_sha256,
                expected_registry_sha256, plan["stage"])
            _require(current["experiment_id"] == plan["experiment_id"], "experiment identity differs")
            return report
        check("material_integrity", admit_materials)

    protocol = artifact(plan["protocol"], "protocol", parse=True)
    tasks = None
    if protocol is not None:
        validated = check("factorial_design", lambda: validate_protocol(protocol))
        if validated is not None:
            tasks, unknown = validated
            for field in unknown:
                block("unknown_research_cost", field, "Reconcile original training/search/evaluation usage.")
            if protocol["evidence_kind"] != "real":
                block("synthetic_protocol", "protocol", "Register a real study; do not relabel this fixture.")
        artifact(plan["objective"], "objective", expected=protocol.get("objective_digest"))
        artifact(plan["meter"], "meter", expected=protocol.get("measurement_digest"))

    if tasks is not None and manifest is not None:
        def task_mapping():
            _require(protocol["dataset_digest"] == expected_manifest_sha256,
                     "factorial dataset is not the externally pinned material manifest")
            cases = {case["id"]: case for case in manifest["cases"]}
            _require(set(tasks) == set(cases), "factorial tasks differ from registered material cases")
            for task_id, task in tasks.items():
                case = cases[task_id]
                _require(task["source_group"] == case["source_id"], "upstream source group was relabelled")
                _require(task["family"] == FAMILY_MAP[case["task_family"]], "task family mapping differs")
                if case["split"] == "retention":
                    _require(task["cohort"] == "retention" and task["split"] in ("validation", "test"),
                             "old capability lacks a frozen validation/test partition")
                else:
                    _require(task["cohort"] == "new" and task["split"] == SPLIT_MAP[case["split"]],
                             "material split differs from factorial split")
            return True
        check("task_mapping", task_mapping)

    actors = set()
    if tasks is not None:
        providers = {} if plan["providers"] is None else plan["providers"]
        if not isinstance(providers, dict) or set(providers) - set(protocol["profiles"]):
            check("provider_roster", lambda: _require(False, "unknown provider profile or invalid roster"))
        else:
            for key, profile in protocol["profiles"].items():
                provider = providers.get(key)
                if provider is None:
                    block("missing_provider", key, "Bind the actual executable, model, policy and initial content.")
                    continue

                def provider_shape():
                    exact_fields(provider, ("principal", "executable", "model", "policy", "initial_content"),
                                 "profile provider")
                    return _text(provider["principal"])
                principal = check(f"provider:{key}", provider_shape)
                if principal is None:
                    continue
                actors.add(principal)
                artifact(provider["executable"], f"provider:{key}:executable")
                for field in ("model", "policy", "initial_content"):
                    artifact(provider[field], f"provider:{key}:{field}", expected=profile[f"{field}_digest"])

    evaluator = plan["evaluator"]
    if evaluator is None:
        block("missing_evaluator", "evaluator", "Bind an independent evaluator and its rubric.")
    else:
        def evaluator_shape():
            exact_fields(evaluator, ("principal", "executable", "rubric", "isolation_evidence"), "evaluator")
            _require(_text(evaluator["principal"]) not in actors, "actor cannot be its own evaluator")
            return True
        if check("evaluator_identity", evaluator_shape):
            artifact(evaluator["executable"], "evaluator:executable",
                     expected=protocol.get("evaluator_digest") if protocol else None)
            artifact(evaluator["rubric"], "evaluator:rubric")
            artifact(evaluator["isolation_evidence"], "evaluator:isolation_evidence")

    cost = artifact(plan["cost_contract"], "cost_contract", parse=True)
    if cost is not None and tasks is not None:
        def cost_shape():
            exact_fields(cost, ("schema", "cost_unit", "cost_weight", "attribution", "research_categories",
                "physical_fields", "unknown_value", "attempt_scope", "conversion_evidence"), "cost contract")
            _require(cost["schema"] == "hepta.physical-cost-contract.v1", "unknown cost contract")
            _require(cost["cost_unit"] == protocol["cost_unit"] and
                cost["cost_weight"] == protocol["cost_weight"] and protocol["cost_weight"] > 0,
                "physical cost conversion must match the registered positive cost weight")
            exact_fields(cost["attribution"], COSTS, "disjoint attribution")
            for description in cost["attribution"].values():
                _text(description)
            _require(cost["research_categories"] == list(RESEARCH), "research ledger categories differ")
            _require(cost["physical_fields"] == ["wall_seconds", "peak_bytes", "energy_joules", "actual_charges"],
                     "physical observations must preserve time, memory, energy and charges")
            _require(cost["unknown_value"] is None and cost["attempt_scope"] == "all_started_attempts",
                     "unknowns or unsuccessful attempts cannot become zero/exclusions")
            return True
        if check("cost_contract_structure", cost_shape):
            artifact(cost["conversion_evidence"], "cost_conversion_evidence")
    artifact(plan["power_plan"], "power_plan")
    artifact(plan["power_review"], "power_review")
    owner = plan["native_owner"]
    if owner is None:
        block("missing_native_owner", "native_owner", "Integrate the existing Cell journal verifier and owner contract.")
    else:
        def owner_shape():
            exact_fields(owner, ("kind", "adapter", "contract", "receipt_inventory"), "native owner")
            _require(owner["kind"] == "hepta-cell-journal", "a new Python owner cannot replace the Cell journal")
            return True
        if check("native_owner_structure", owner_shape):
            for field in ("adapter", "contract", "receipt_inventory"):
                artifact(owner[field], f"native_owner:{field}")
    for code, action in (
        ("native_authentication_not_implemented", "Verify original Cell starts, attempt inventory and signed outcomes through the existing owner."),
        ("evaluator_isolation_unverified", "Authenticate distinct principals and prove the actor cannot read references or future observations."),
        ("provider_execution_unverified", "Execute every bound provider with measured active capacity, objective, runtime and output identities."),
        ("physical_cost_calibration_unverified", "Verify meter calibration, disjoint allocation and unknown/failed/retry/synchronization accounting."),
        ("power_review_unverified", "Validate the prospective independent-fit/source-cluster power analysis and its pre-result registration."),
        ("source_independence_unverified", "Independently verify upstream source clusters, exposure history and task-family validity."),
    ):
        block(code, "native_integration", action)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--registry-sha256", required=True)
    args = parser.parse_args()
    report = inspect_execution(args.root, args.plan, expected_plan_sha256=args.plan_sha256,
        expected_manifest_sha256=args.manifest_sha256, expected_registry_sha256=args.registry_sha256)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    raise SystemExit(2 if report["outcome"] == "Failed" else 3)
