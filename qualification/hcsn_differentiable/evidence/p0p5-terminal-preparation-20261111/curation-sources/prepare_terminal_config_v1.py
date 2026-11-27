"""Freeze exact preparation inputs for one append-only evidence curation."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path("/workspace/scratch/c385a7439f8e")


def identify(path):
    raw = path.read_bytes()
    if path.is_symlink() or not path.is_file() or len(raw) > 500000:
        raise ValueError("nonregular or oversized input: " + str(path))
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--renderer-copy", type=Path, required=True)
    parser.add_argument("--renderer-sha256", required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    bundles = [
        ("terminal-bootstrap", "c2-terminal-bootstrap-recovery-v3-COPY_LIST.json", "f75201c8eac516bbd07f4355be10a6eda804d273ddfbb1ab123d22f2fb00dd32"),
        ("resource-core", "c2-resource-core-v2-final-preparation/COPY_LIST.json", "f600d5e92c9ab251957dd1eb3d540482cfc33b8ca4ec1f79bab3413377ee6eff"),
        ("os-helper-validation", "os-helper-validation-v3/COPY_LIST.json", "f1a06b151f831f8966a98ebd8e5a6dc8656f0aec8df1a2619ac60fd72cc50698"),
        ("os-helper-validation/persistence", "os-helper-validation-v3/RECOVERY-COPY_LIST.json", "d5f21e4e4ff89ecb8cc91cce850388f76ca8c65304128b2125d0e9d43ffba3fd"),
        ("control-followup", "c2-control-handoff-20261111-v1/COPY_LIST-v2.json", "0f0a04470c5cf548bfef2f27202320df1c5e35379fabcac9ec57d628148da796"),
        ("control-0055", "c2-sparse-control-observation-20261111-v1/COPY_LIST.json", "a547fbb443b0a4e4e61a1b19c6b587b55f832942d010f29a32c9314899fd4cf4"),
        ("control-0110", "c2-sparse-control-observation-20261111-v2/COPY_LIST.json", "941e3aee3cd7a6480224f9fb28d512e7a1663ae6965a45605f614dd257b6d452"),
        ("control-0130", "c2-sparse-control-observation-20261111-v3/COPY_LIST.json", "b06a883b44d28d99e8bd8429ef1dfc6caa6f93b180bcfc895b7d18311450e082"),
        ("control-0150", "native-c2-control-0150-20261111-v1/COPY_LIST.json", "79d54b969412e58b26e7a79a4d1a849163da8c65faf3013eb1a450db6578b4ce"),
        ("control-recovery", "c2-sparse-control-recovery-20261111-v1/COPY_LIST.json", "16360c1ea89d269ec104f971781da884243305e24464fb8b962d609a0c5dde8a"),
        ("operator-schema", "operator-native-schema-handoff-v1/COPY_LIST.json", "2383d379a8fc8cba6db553e24068b7aa614b176c6162761520fc9ed6e249f03b"),
        ("training-review", "c2-followup-training-static-review-v1/COPY_LIST.json", "3b064c17342dc3fe8b7fd395b9438396a45f8f07f36ed738a7001101ffff3824"),
        ("status-time", "c2-status-time-clarification-20261111-v1/COPY_LIST.json", "465e8b1e9887d79992646f1d219a742d441a4a5e476b777adecdfd61a4fa6fa0"),
        ("supervisor/review", "complete-os-supervisor-rebind-training-static-review-v1/COPY_LIST.json", "60667baf9d0d50a51e4caae83f196b2276bc92e63954801f20c8236401fc1a45"),
        ("documentation-review", "terminal-preparation-text-review-numerics-v1/COPY_LIST.json", "9bed50e11141f2f2d4437848e8e15307da552c5b4e3f6c84ada2f24a40234b3f"),
        ("renderer", str(args.renderer_copy), args.renderer_sha256),
    ]
    copies = []
    for destination, name, expected in bundles:
        path = ROOT / name
        actual = identify(path)
        if actual["sha256"] != expected:
            raise ValueError("copy-list pin mismatch: " + name)
        rows = json.loads(path.read_bytes())
        rows = rows.get("files", rows.get("entries"))
        row = {"source": str(path), "destination": destination, **actual}
        targets = [next(x[k] for k in ("destination", "target", "relative_destination", "relative_path", "suggested_name") if k in x) for x in rows]
        if targets and all(x.startswith(destination + "/") for x in targets):
            row["strip_prefix"] = destination
        copies.append(row)
    files = []

    def add(name, destination):
        path = ROOT / name
        files.append({"source": str(path), "destination": destination, **identify(path)})

    add("terminal_preparation_readme_v1.md", "README.md")
    add("complete-os-supervisor-rebind-v3.zip", "supervisor/program.zip")
    for name in ("ORIGINALS.zip", "MEMBERS.json", "RECEIPT.json", "BLOB-CREATE-RAW.json"):
        add("recovery-verification-capsule-v1/" + name, "verification/" + name)
    for directory, destination in (("complete-os-supervisor-rebind-v3", "supervisor/program"),
                                   ("complete-os-supervisor-rebind-v3-execution", "supervisor/preparation-execution"),
                                   ("recovery-verification-pack-execution-v1", "verification/packing-execution"),
                                   ("terminal-preparation-root-records-v1", "ci-blocking")):
        for path in sorted((ROOT / directory).iterdir()):
            if path.is_file():
                add(str(path.relative_to(ROOT)), destination + "/" + path.name)
    for name in ("run_frozen_local_v1.py", "package_metadata_handoff_v1.py", "verify_remote_evidence_objects_v2.py", "prepare_terminal_config_v1.py"):
        add(name, "curation-sources/" + name)
    status = {
        "schema": "hcsn-c2-terminal-preparation-state-v1",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "original_job_id": "1a1c74f3308-be2a-75",
        "original_idempotency_key": "hcsn-c2-native-execution-c385-v1",
        "last_full_epoch_observation_utc": "2026-11-10T23:49:03.598037Z",
        "latest_three_001_commit_read_span_utc": ["2026-11-11T01:55:09.609Z", "2026-11-11T01:55:17.790Z"],
        "latest_three_001_reported_complete_epochs": [105, 104, 105],
        "latest_three_001_seed_order": [101, 211, 307],
        "latest_three_commit_scope": "SHA-checked producer metadata only; not terminal, independent replay, common-rate selection or complete final cost",
        "last_valid_status_read_span_utc": ["2026-11-11T01:50:50.391Z", "2026-11-11T01:50:52.855Z"],
        "last_valid_status_native_sample_timestamp": None,
        "last_failed_read_span_utc": ["2026-11-11T01:30:42.885Z", "2026-11-11T01:30:44.341Z"],
        "current_native_state": "same original job running at the last valid status read; complete 24917-byte journal at 01:52 retains three producer terminals; individual remaining worker liveness is not inferred from this journal",
        "v9_observer_launch_outcome": "unknown after two identical requests with the same idempotency key; no replacement or later launch",
        "original_training_budget_changed": False,
        "actual_terminal_assembly_executed": False,
        "actual_independent_C2_auditor_executed": False,
        "actual_C2_resource_analysis_executed": False,
        "actual_C2_rendering_executed": False,
        "subject_E_scoring_executed": False,
        "resource_core_manifest_sha256": "f2d1ce683591a9b8575aab2d0981bf67b9e465bf9686a8da2e87a2246a0ea70e",
        "resource_final_source_tests": {"run": 52, "failures": 0, "actual_C2_data": False},
        "bootstrap_v2_tests": 21,
        "bootstrap_v3_targeted_tests": 4,
        "OS_helper_new_tests": 9,
        "complete_supervisor_rebind": "one program-manifest literal changed; independent static review; zero full-supervisor functional tests",
        "renderer_program_manifest_sha256": "eb88492821fed51acd1f3280e5b895bb7c54510d1900591dee3049f1a4396071",
        "renderer_final_native_gate_tests": 8,
        "renderer_independent_review": "Three consistency gaps closed in bounded JSON probes; original nine-versus-seven source enumeration error retained, followed by a separate nine-file unchanged-hash check. No actual rendering.",
        "missing_old_test_receipts_reconstructed": False,
        "new_local_resource_costs": "Preserved in component receipts; nested scopes are not added. Tests do not grant actual execution or scientific credit.",
        "prior_head_publication_verified": "9f16aa325b12004ddc0d9fa325fdc67531d027fc",
        "prior_head_complete_remote_files_read": 87,
        "prior_head_science_CI_run": 42933021590,
        "prior_head_science_CI_result": "92 fixtures and all declared steps passed at its exact tested tree",
        "prior_head_repository_wide_CI": "not all green; raw run and first page of jobs preserved, failure causes not inferred",
        "whole_training_numerical_admission": "HOLD",
        "scientific_benefit_admission": "HOLD",
        "P5": "gated on demonstrated scientific benefit",
    }
    save(args.output / "STATUS.json", status)
    add(str((args.output / "STATUS.json").resolve()), "STATUS.json")
    save(args.output / "CONFIG.json", {"schema": "hcsn-terminal-preparation-curation-inputs-v1", "copy_lists": copies, "files": files})
    print(json.dumps({"config": str(args.output / "CONFIG.json"), "copy_lists": len(copies), "direct_files": len(files), "preparation_only": True}))


if __name__ == "__main__":
    main()
