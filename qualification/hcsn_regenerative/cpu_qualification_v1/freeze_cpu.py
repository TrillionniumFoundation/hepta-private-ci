"""Freeze a distinct CPU study only from complete actual two-producer evidence."""

import argparse
import copy
from pathlib import Path
import tempfile

from qualification.hcsn_regenerative.mechanism_contract import (
    ARMS, STATE_COUNT, EXPECTED_PARAMETERS, digest as object_digest, load_contract,
    ordered_roster, utc_now, validate_execution_environment, validate_plan, write_json)
from qualification.hcsn_regenerative.resource_migration_v4.freeze_v4 import verify_case_roster
from .evidence_guard import (ENV_KEYS, SLOTS, STUDY_ID, compare_scientific_parent,
                             digest, parse, preflight, require)


def validate_records(verified):
    records, pins, reg = verified["records"], verified["source_pins"], verified["registration"]
    bundle_sha, metadata_sha = reg["bundle_sha256"], reg["bundle_metadata_sha256"]

    def sources(actual):
        require(actual and all(path in pins and pins[path] == value for path, value in actual.items()),
                "A numerical receipt has an unregistered source identity")

    unit = records["unit"]
    require(unit.get("schema") == "hcsn-mechanism-unit-result-v1" and unit.get("status") == "pass"
            and unit.get("methods_run") == 13 and all(unit.get(k) == 0 for k in ("failures", "errors", "skipped")),
            "Actual no-skip13-method Torch unit evidence is required")
    sources(unit["source_pins"])
    for name, schema in (("graph_cpu", "hcsn-mechanism-graph-qualification-v1"),
                         ("sequence_cpu", "hcsn-mechanism-sequence-qualification-v1")):
        record = records[name]
        require(record.get("schema") == schema and record.get("status") == "pass" and record.get("device") == "cpu"
                and record.get("bundle_sha256") == bundle_sha and record.get("bundle_metadata_sha256") == metadata_sha
                and record.get("checks") and all(row.get("passed") is True for row in record["checks"]),
                "Actual CPU graph/sequence qualification failed")
        sources(record["source_pins"])
        verify_case_roster(record, sequence=name == "sequence_cpu")
        if name == "sequence_cpu":
            require(record["recovery"].get("passed") is True, "Actual independent-episode recovery did not pass")
    environment = records["graph_cpu"]["environment"]
    require({k: environment[k] for k in ENV_KEYS} == reg["cpu_execution_environment"], "Fresh graph and external budget CPU environment differ")
    resolution = records["resolution"]
    require(resolution.get("status") == "complete" and resolution.get("source_unchanged") is True
            and resolution.get("task_dataset_reads") == resolution.get("task_optimizer_updates") == 0
            and resolution.get("thresholds") == dict(common_bin_state_l1=.02, cumulative_hit_relative=.03, reference_crosscheck_abs=2e-8)
            and len(resolution.get("reference_crosscheck", [])) == 4
            and {row.get("horizon") for row in resolution["reference_crosscheck"]} == {.08, .1, .32, .7}
            and all(row.get("pass_") is True for row in resolution["reference_crosscheck"]),
            "Fixed resolution reference crosschecks or original thresholds differ")
    rows = resolution.get("rows", [])
    expected = {(n, p, dtype, schedule) for n, p in ((16, 8), (64, 16), (128, 32))
                for dtype in ("torch.float32", "torch.float64") for schedule in ("unequal", "equal")}
    require(len(rows) == 12 and {(x.get("active_cells"), x.get("phase_cells"), x.get("dtype"), x.get("schedule")) for x in rows} == expected,
            "Missing, duplicated or changed resolution row")
    eligible = []
    for n, p in ((16, 8), (64, 16), (128, 32)):
        cases = [x for x in rows if x["active_cells"] == n and x["phase_cells"] == p]
        if all(x["passes_configuration"] and x["state_l1_error"] <= .02 and x["hit_relative_error"] <= .03 for x in cases):
            eligible.append((n, p))
    selected = resolution.get("smallest_eligible_configuration", {})
    require(eligible and eligible[0] == (64, 16) and selected.get("active_cells") == 64
            and selected.get("phase_cells") == 16 and selected.get("eligible") is True
            and any(not x["passes_configuration"] for x in rows if x["active_cells"] == 16),
            "S81 is fixed; failed coarse S25 results must remain visible")
    require(object_digest(resolution["sources"]) == resolution["source_set_sha256"], "Resolution source digest differs")
    sources(resolution["sources"])
    fixed = records["fixed_renewal"]
    require(fixed.get("status") == "BOUNDED_FP64_CONSTRUCTION_CHECKS_PASS" and fixed.get("source_unchanged") is True
            and fixed.get("unit_methods_run") == 6 and fixed.get("unit_failures") == fixed.get("unit_errors") == 0,
            "Independent bounded zero-delay construction audit is required")
    sources(fixed["source_files_sha256"])
    sources(records["budget"]["source_pins"])
    qualification = verified["sources"]["qualification"]
    capability = parse(qualification["members"]["evidence/capability.json"])
    require(capability.get("schema") == "hcsn-kaggle-cpu-qualification-capability-v1"
            and capability.get("request_id") == qualification["manifest"]["request_id"]
            and capability.get("status") == "pass" and capability.get("matrix_identity_pass") is True
            and {k: capability["environment"][k] for k in ENV_KEYS} == reg["cpu_execution_environment"]
            and capability.get("optimizer_updates") == capability.get("formal_training_fits") == capability.get("task_dataset_reads") == 0,
            "Actual CPU capability is incomplete or from another request")
    fv = parse(qualification["members"]["evidence/fv-audit-cpu.json"])
    require(fv.get("status") == "pass" and fv.get("device") == "cpu" and len(fv.get("checks", [])) == 12
            and all(row.get("pass_") is True for row in fv["checks"]), "Actual CPU FV audit incomplete")
    stages = {row["name"]: row for row in qualification["execution"]["stages"]}
    for name, count in (("fv-unit", 8), ("mechanism-unit", 13)):
        observed = stages[name]["unit_observation"]
        require(observed["methods_run"] == count and all(observed[k] == 0 for k in ("failures", "errors", "skipped")),
                "Actual unit observation is incomplete")
    return environment, selected


def freeze(args):
    output = Path(args.output)
    require(not output.exists(), "The CPU plan is immutable; do not overwrite an existing plan")
    verified = preflight(args)
    environment, selected = validate_records(verified)
    parent, reg = verified["parent"], verified["registration"]
    plan = copy.deepcopy(parent)
    receipts = {}
    for name, record in verified["records"].items():
        binding = verified["slot_pins"][name]
        receipts[name] = dict(filename=PureName(SLOTS[name]), sha256=binding["sha256"],
                              schema=record.get("schema"), status=record.get("status"),
                              source_id=binding["source_id"], member=binding["member"], bytes=binding["bytes"],
                              archive_sha256=verified["lineage"]["sources"][binding["source_id"]]["archive"]["sha256"])
    execution = {key: environment[key] for key in ENV_KEYS}
    execution["gpu_uuid_policy"] = "not_applicable"
    plan.update(status="FROZEN", study_id=STUDY_ID, frozen_at=utc_now(), source_pins=verified["source_pins"],
                qualification_receipts=receipts, numerical_resolution=selected, execution_environment=execution,
                runtime_feasibility_policy=dict(parent["runtime_feasibility_policy"], provider="kaggle", execution_gpu_index=None),
                resource_migration=verified["lineage"])
    require(plan["state_count"] == STATE_COUNT == 81 and plan["expected_parameter_count"] == EXPECTED_PARAMETERS == 2890
            and plan["arms"] == list(ARMS) and len(ordered_roster(plan)) == 160, "Original S81 study roster changed")
    require(object_digest(ordered_roster(plan)) == parent["ordered_fit_roster_sha256"], "Ordered160 fit identity changed")
    compare_scientific_parent(parent, plan)
    validate_plan(plan)
    members = verified["sources"]["qualification"]["members"]
    metadata = parse(members[reg["metadata_member"]])
    validate_execution_environment(plan, environment, metadata)
    validate_execution_environment(plan, verified["records"]["budget"]["environment"], metadata)
    # The original loader verifies all operator arrays and original sources; no Torch model is run.
    with tempfile.TemporaryDirectory(prefix="hcsn-cpu-freeze-verified-") as temporary:
        root = Path(temporary)
        bundle = root / "operators-s81.npz"
        bundle.write_bytes(members[reg["bundle_member"]])
        bundle.with_suffix(".json").write_bytes(members[reg["metadata_member"]])
        candidate = root / "candidate-plan.json"
        write_json(candidate, plan)
        load_contract(bundle, candidate)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, plan)
    return plan


def PureName(path):
    return path.rsplit("/", 1)[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent-plan", "qualification-manifest", "evidence-index", "artifact-root", "final-control-manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("qualification-manifest-sha256", "evidence-index-sha256", "final-control-manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    plan = freeze(args)
    print(plan["study_id"], digest(Path(args.output).read_bytes()), plan["ordered_fit_roster_sha256"])


if __name__ == "__main__":
    main()
