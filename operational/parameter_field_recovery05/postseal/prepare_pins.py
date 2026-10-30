"""Execution05 primary/ACK metadata gate and exact postseal invocation pins.

Mechanical continuation of the recovered execution04 preparer. No old binary
readback payload path is reopened; original ACK/ACK_VERIFIED provenance remains.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery05.postseal import prepare_plan as layout
from operational.parameter_field_recovery05.producer_adapter import ProducerAdapter
from operational.parameter_field_recovery05.postseal.prepare_plan import BASE, OPS, RAW, WORK, PYTHON, EPISODE, SUPPLEMENT_SHA, need, descriptor, verify, read, bound, write

ORDER = ["A-17", "A-29", "A-43", "C", "B-17", "B-29", "B-43", "W",
         "R-17", "R-29", "R-43", "A_endpoint", "B_endpoint", "C_endpoint"]
LABELS = ORDER + ["controller", "analysis", "final_closure"]

def collect_primary(config, plan_desc):
    need(not (OPS / "FAILED.json").exists(), "Primary FAILED exists")
    cfg = bound(config)
    need(config["path"] == str(OPS / "registrations/initial/PIPELINE_CONFIG.json")
         and cfg.get("schema") == "hepta.fullstudy.execution05.configuration.1"
         and cfg.get("execution_episode") == EPISODE and cfg["raw_root"] == str(RAW)
         and cfg["ops_root"] == str(OPS) and cfg["source_root"] == str(SOURCE), "Wrong execution05 pipeline config")
    need(plan_desc in cfg["initial_metadata"], "Prospective plan is absent from initial metadata")
    plan = bound(plan_desc)
    producer = layout.validate_plan(plan, cfg["descriptors"]["producer_config"], cfg["source_commit"])
    adapter = ProducerAdapter(producer["producer_map"], producer["import_receipt"], producer["fresh_registration"])
    outer_desc = descriptor(OPS / "wait4_launcher/WAIT4_COMPLETE.json")
    outer = bound(outer_desc)
    need(outer["schema"] == "hepta.fullstudy.execution05-outer-wait4.1"
         and outer["exit_code"] == 0 and outer["config"] == config,
         "Successful matching outer wait4 is required")
    primary_desc = outer["primary_complete"]
    need(primary_desc["path"] == str(OPS / "COMPLETE.json"), "Wrong primary path")
    primary = bound(primary_desc)
    need(primary["schema"] == "hepta.fullstudy.pipeline-completion.4"
         and primary["complete"] is True and primary["execution_episode"] == EPISODE
         and primary["pipeline_config"] == config and primary["jobs"] == ORDER
         and primary["jobs_verified"] == 14 and primary["required_finalizer_seals_verified"] == 30,
         "Primary metadata is incomplete or belongs to another execution")
    need(primary.get("imported_jobs") == ["A-17"] and primary.get("scientific_jobs_executed_here") == ORDER[1:]
         and primary.get("import_receipt") == producer["import_receipt"]
         and primary.get("producer_map") == producer["producer_map"], "Primary imported/fresh producer population differs")
    need(outer.get("imported_A17_historical_scientific_cpu_not_added") is True
         and outer.get("do_not_add_nested_science_driver_archive_or_supervisor_ledgers") is True,
         "Execution05 outer cost scope differs")
    artifacts = primary["artifacts"]
    need(set(artifacts) == {"verified", "manifest", "aggregate_results", "finalizer_freeze"},
         "Primary artifact interface changed")
    for item in artifacts.values():
        verify(item)  # Hash aggregate RESULTS bytes; do not decode them here.
    literal = bound(artifacts["verified"])
    manifest = bound(artifacts["manifest"])
    finalizer = bound(artifacts["finalizer_freeze"])
    need(artifacts["verified"]["path"] == str(RAW/"evidence_v2/verification05/VERIFIED.json")
         and artifacts["manifest"]["path"] == str(RAW/"evidence_v2/verification05/MANIFEST.json")
         and finalizer.get("evidence_id") == "verification05"
         and finalizer.get("evidence_relative") == "evidence_v2/verification05", "Wrong finalizer destination")
    adapter.require_bound(finalizer)
    entries = manifest["logical_paths"]
    manifest_relative = {**artifacts["manifest"],
                         "path": str(Path(artifacts["manifest"]["path"]).relative_to(RAW))}
    need(literal["archive_verification_complete"] is True
         and literal["temporary_directory_removed_after_success"] is True
         and literal["manifest"] == manifest_relative
         and literal["binding"] == manifest["binding"]
         and literal["logical_files_restored"] == manifest["logical_artifact_count"] == len(entries)
         and literal["logical_bytes_restored"] == manifest["logical_artifact_bytes"]
             == sum(row["bytes"] for row in entries.values())
         and literal["logical_paths_verified"] == sorted(entries)
         and primary["logical_files_restored"] == len(entries)
         and primary["logical_bytes_restored"] == literal["logical_bytes_restored"],
         "Literal restore counts/binding differ")
    aggregate_freeze_desc = finalizer["actual_aggregate_source_freeze"]
    aggregate_freeze = bound(aggregate_freeze_desc)
    adapter.require_bound(aggregate_freeze)
    report_inputs_desc = aggregate_freeze["report_inputs"]
    verify(report_inputs_desc)
    analysis_id = aggregate_freeze["analysis_id"]
    output_relative = Path(aggregate_freeze["output_relative"])
    need(analysis_id == "analysis05backpressure"
         and not output_relative.is_absolute() and ".." not in output_relative.parts,
         "Unexpected analysis location")
    names = {"controller/EXECUTION.json"}
    for phase in ("A", "B", "C", "W", "R"):
        for seed in (17, 29, 43) if phase in ("A", "B", "R") else (None,):
            token = f"{phase}-seed-{seed}" if seed is not None else f"{phase}-all"
            names.add(f"operations/{token}.COMPLETE.json")
            names.add(f"stage_{phase}/seed-{seed}/COMPLETE.json"
                      if seed is not None else f"stage_{phase}/COMPLETE.json")
        if phase in ("A", "B", "C"):
            sub = "endpoint_evaluation" if phase == "C" else "endpoints"
            names.add(f"stage_{phase}/{sub}/ENDPOINTS.json")
    expected_26 = {str(RAW / name) for name in names}
    expected_30 = expected_26 | {
        str(RAW / f"analysis_operations/{analysis_id}/COMPLETE.json"),
        str(RAW / f"analysis_operations/{analysis_id}/WORKER_COMPLETE.json"),
        str(RAW / output_relative / "RESULTS.json"),
        str(RAW / output_relative / "REPORT.md")}
    analysis_seals = aggregate_freeze["required_scientific_seals"]
    final_seals = finalizer["required_scientific_seals"]
    need(len(expected_26) == len(analysis_seals) == 26 and set(analysis_seals) == expected_26
         and len(expected_30) == len(final_seals) == 30 and set(final_seals) == expected_30
         and all(final_seals[path] == digest for path, digest in analysis_seals.items()),
         "Declared 26/30 seal population differs")
    stages = primary["durable_stages"]
    need(len(stages) == 17, "Need exactly 17 primary durable stages")
    coverage, stage_rows, previous_ack = {}, [], None
    for index, (label, stored) in enumerate(zip(LABELS, stages, strict=True), 1):
        directory = OPS / "durable" / f"{index:02d}_{label}"
        checked_stage_desc = descriptor(directory / "ACK_VERIFIED.json")
        need(bound(checked_stage_desc) == stored, "Primary ACK_VERIFIED record changed")
        request = bound(stored["request"])
        ack = bound(stored["ack"])
        binding = request["binding"]
        need(binding["execution_episode"] == EPISODE and binding["sequence"] == index
             and binding["label"] == label and binding["pipeline_config"] == config
             and binding["completed_jobs"] == ORDER[:min(index, 14)]
             and binding["previous_ack"] == previous_ack and stored["binding"] == binding,
             "Durable stage ordering/binding changed")
        need(stored["request"]["path"] == str(directory / "REQUEST.json")
             and stored["ack"]["path"] == str(directory / "ACK.json")
             and ack["schema"] == request["required_ack_schema"]
             and ack["status"] == "VERIFIED_REMOTE_READBACK"
             and ack["unknown_upload_outcome"] is False
             and ack["request"] == stored["request"] and ack["binding"] == binding,
             "ACK is not the sealed successful root ACK")
        items = ack["items"]
        need(len(items) == len(request["items"]) == stored["items_verified"]
             and stored["readback_bytes_verified_here"] is True, "ACK population differs")
        remote_ids = []
        for expected, item in zip(request["items"], items, strict=True):
            need(item["local"] == expected and item["upload_item_success"] is True
                 and item["remote_readback_performed"] is True
                 and item["readback_remote_identity"] == item["remote_identity"]
                 and all(item["readback"][k] == expected[k] for k in ("bytes", "sha256")),
                 "ACK item has an incomplete or conflicting remote readback")
            remote_id = item["remote_identity"]["library_file_id"]
            need(isinstance(remote_id, str) and bool(remote_id), "Missing real Library identity")
            remote_ids.append(remote_id)
        need(len(set(remote_ids)) == len(items)
             and sorted(remote_ids) == stored["remote_library_file_ids"],
             "ACK remote identity population differs")
        archive_manifest = bound(request["manifest"])
        archive_verified = bound(request["archive_verification"])
        need(archive_manifest["binding"] == binding and archive_verified["binding"] == binding
             and archive_verified["verification_complete"] is True
             and archive_verified["manifest"] == request["manifest"],
             "Stage archive verification binding differs")
        for row in archive_manifest["files"]:
            if row["path"].startswith("raw/"):
                coverage[row["path"][4:]] = {k: row[k] for k in ("bytes", "sha256")}
        stage_rows.append({"sequence": index, "label": label, "request": stored["request"],
                           "ack": stored["ack"], "ack_verified": checked_stage_desc,
                           "items_verified": len(items), "remote_library_file_ids": sorted(remote_ids)})
        previous_ack = stored["ack"]
    need(primary["durable_raw_logical_files"] == len(coverage)
         and all(coverage.get(name) == {k: row[k] for k in ("bytes", "sha256")}
                 for name, row in entries.items()),
         "17 stage manifests do not cover every final RAW logical artifact")
    script_desc = descriptor(SOURCE / "supplements/parameter_field_fullstudy_20261030/postseal_supplement.py")
    need(script_desc["sha256"] == SUPPLEMENT_SHA
         and script_desc["bytes"] == 45470, "Pre-endpoint supplement identity changed")
    output = WORK / "supplement"
    audit = {"schema": "hepta.execution05.root-primary-metadata-audit.1",
             "at_utc": datetime.now(timezone.utc).isoformat(),
             "status": "PRIMARY_METADATA_AND_ACK_COVERAGE_VERIFIED",
             "primary": primary_desc, "outer_wait4": outer_desc, "jobs": ORDER,
             "declared_analysis_seals": 26, "declared_finalizer_seals": 30,
             "seal_byte_validation_deferred_to_registered_supplement_gate": True,
             "durable_stages": stage_rows, "final_logical_files_covered": len(entries),
             "durable_coverage_logical_files": len(coverage),
             "archive_binary_readbacks_rehashed": False, "literal_restore_rerun": False,
             "remote_authentication_basis": "existing actual root Library receipts and sealed ACK_VERIFIED",
             "scientific_values_decoded": False}
    options = {"raw-root": str(RAW), "source-root": str(SOURCE), "plan": plan_desc["path"],
               "expected-plan-sha256": plan_desc["sha256"], "pipeline-complete": primary_desc["path"],
               "expected-pipeline-sha256": primary_desc["sha256"],
               "verified": artifacts["verified"]["path"],
               "expected-verified-sha256": artifacts["verified"]["sha256"],
               "manifest": artifacts["manifest"]["path"],
               "expected-manifest-sha256": artifacts["manifest"]["sha256"],
               "finalizer-freeze": artifacts["finalizer_freeze"]["path"],
               "expected-finalizer-sha256": artifacts["finalizer_freeze"]["sha256"],
               "output": str(output)}
    argv = [PYTHON, "-B", str(layout.OWN / "run_supplement.py"),
            "--producer-config", cfg["descriptors"]["producer_config"]["path"],
            "--expected-producer-config-sha256", cfg["descriptors"]["producer_config"]["sha256"]]
    for name, value in options.items():
        argv.extend(["--" + name, value])
    argv.append("--execute-post-seal")
    pins = {"schema": "hepta.execution05.root-postseal-arguments.1",
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "primary": primary_desc, "outer_wait4": outer_desc, "artifacts": artifacts,
            "aggregate_source_freeze": aggregate_freeze_desc, "report_inputs": report_inputs_desc,
            "plan": plan_desc, "supplement_source": script_desc, "pipeline_config": config,
            "producer_config": cfg["descriptors"]["producer_config"],
            "producer_map": producer["producer_map"], "import_receipt": producer["import_receipt"],
            "preparation_code": descriptor(__file__), "argv": argv, "output": str(output),
            "scientific_values_decoded": False}
    return audit, pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pipeline-config", "expected-config-sha256", "plan", "expected-plan-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    need(args.execute, "Explicit metadata preparation required")
    config, plan = descriptor(Path(args.pipeline_config).absolute()), descriptor(Path(args.plan).absolute())
    need(config["sha256"] == args.expected_config_sha256 and plan["sha256"] == args.expected_plan_sha256,
         "External configuration or plan pin differs")
    need(not WORK.exists(), "Postseal workspace exists; preserve evidence, do not automatically retry")
    audit,pins = collect_primary(config, plan)
    (WORK/"control").mkdir(parents=True,exist_ok=False)
    audit_desc=write(WORK/"control/PRIMARY_ACK_AUDIT.json",audit)
    pins["metadata_audit"] = audit_desc
    pins_desc=write(WORK/"control/POSTSEAL_ARGUMENTS.json",pins)
    print(json.dumps({"audit":audit_desc,"arguments":pins_desc,"scientific_values_decoded":False}))


if __name__ == "__main__":
    main()
