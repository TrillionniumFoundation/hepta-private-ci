"""Offline, byte-pinned Colab qualification assets; no provider or model calls."""
import argparse
import json
from pathlib import Path

from qualification.hcsn_regenerative.colab_qualification_v3.asset_transport import (
    canonical, make_launcher, prepare_archive, regular_bytes, require, sha, _new_file)
from qualification.hcsn_regenerative.colab_qualification_v3.qualification_runner import (
    CONTRACT_SHA256, REQUEST_ID, SOURCE35_SHA256, STUDY_ID)

PUBLIC_DIR = "qualification/hcsn_regenerative/colab_qualification_v3"
CONTROL_FILES = ("__init__.py", "asset_transport.py", "qualification_runner.py",
                 "build_qualification.py", "test_asset_transport.py")
GUARD_PATH = "qualification/hcsn_regenerative/colab_execution_v3/fixed_kernel_provider.py"
PARENT_PLAN_SHA256 = "cc2fe01594bd77721eda1f2a3130257ba5dbfa61c498a9f469f91195598c2550"


def build(*, original_source, parent_plan, contract_path, bundle, bundle_metadata,
          fixed_kernel_provider, output_dir, remote_root="/content/hepta_jobs"):
    """Create a fresh local package and small launcher; never dispatch anything."""
    original_source, output = Path(original_source).absolute(), Path(output_dir).absolute()
    contract_raw, parent_raw = regular_bytes(contract_path), regular_bytes(parent_plan)
    require(sha(contract_raw) == CONTRACT_SHA256 and sha(parent_raw) == PARENT_PLAN_SHA256,
            "FROZEN_PARENT_OR_CONTRACT_IDENTITY")
    contract, parent = json.loads(contract_raw), json.loads(parent_raw)
    require(contract["request_id"] == REQUEST_ID and contract["study_id"] == STUDY_ID
            and contract["parent_plan_sha256"] == PARENT_PLAN_SHA256,
            "QUALIFICATION_IDENTITY")
    original42, sources = parent["source_pins"], contract["source_files"]
    require(len(original42) == 42 and len(sources) == 35
            and sha(canonical(sources)) == contract["source_set_sha256"] == SOURCE35_SHA256,
            "PRESERVED_SOURCE_ROSTER")
    files = {}
    for name, expected in original42.items():
        data = regular_bytes(original_source / name)
        require(sha(data) == expected, "ORIGINAL_SOURCE_BYTES_CHANGED")
        if name in sources:
            require(sources[name] == dict(bytes=len(data), sha256=expected), "SOURCE35_BYTES_CHANGED")
        files[name] = original_source / name
    require(set(sources) <= set(original42), "SOURCE35_NOT_IN_ORIGINAL42")
    local_control = Path(__file__).absolute().parent
    controls = {}
    for name in CONTROL_FILES:
        logical, path = PUBLIC_DIR + "/" + name, local_control / name
        data = regular_bytes(path)
        compile(data, logical, "exec")  # Compiles only; no source or model execution.
        require(logical not in files, "CONTROL_COLLIDES_WITH_PRESERVED_SOURCE")
        files[logical] = path
        controls[logical] = dict(bytes=len(data), sha256=sha(data))
    guard_raw = regular_bytes(fixed_kernel_provider)
    compile(guard_raw, GUARD_PATH, "exec")
    fixed_inputs = {"operators-s81.npz": Path(bundle).absolute(),
                    "operators-s81.json": Path(bundle_metadata).absolute()}
    for record in contract["fixed_input"]["members"].values():
        path = fixed_inputs[record["output_name"]]
        data = regular_bytes(path)
        require(dict(bytes=len(data), sha256=sha(data)) == {k: record[k] for k in ("bytes", "sha256")},
                "HISTORICAL_FIXED_INPUT_CHANGED")
        files["inputs/prior-qualified-bundle/" + record["output_name"]] = path
    require(len(contract["commands"]) == 12 and sum(row["timeout_seconds"] for row in contract["commands"]) == 2700,
            "COMMAND_BUDGET_CHANGED")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    _new_file(output / "qualification-contract.json", contract_raw)
    config = dict(schema="hcsn-colab-qualification-local-config-v3", request_id=REQUEST_ID,
                  study_id=STUDY_ID, original42_source_pins=original42, control_source_files=controls,
                  fixed_kernel_provider_sha256=sha(guard_raw), native_identity_claimed=False)
    _new_file(output / "qualification-config.json", canonical(config) + b"\n")
    files["qualification-contract.json"] = output / "qualification-contract.json"
    files["qualification-config.json"] = output / "qualification-config.json"
    prepared = prepare_archive(files, output / "assets", REQUEST_ID, remote_root,
                               max_archive_bytes=33554432)
    manifest_bytes = regular_bytes(prepared["manifest_path"])
    launcher = make_launcher(manifest_bytes, prepared["manifest_sha256"], "qualified-s81-v3",
        PUBLIC_DIR + "/qualification_runner.py", regular_bytes(local_control / "asset_transport.py"))
    _new_file(output / "qualification-payload.py", launcher["source_text"].encode())
    qualification = dict(schema="hcsn-colab-qualification-manifest-v3", request_id=REQUEST_ID,
        study_id=STUDY_ID, status="PROSPECTIVE_OFFLINE_NOT_EXECUTED", provider="colab",
        parent_plan_sha256=PARENT_PLAN_SHA256, command_contract_sha256=CONTRACT_SHA256,
        commands=contract["commands"], provider_timeout_seconds=3000, stage_timeout_sum_seconds=2700,
        source_files=sources, source_set_sha256=SOURCE35_SHA256,
        subset_identities=contract["subset_identities"], original42_source_pins=original42,
        control_source_files=controls, fixed_kernel_provider_sha256=sha(guard_raw),
        fixed_kernel_provider_source_path=GUARD_PATH,
        payload_sha256=launcher["code_sha256"], payload_bytes=launcher["code_bytes"],
        asset_manifest_sha256=prepared["manifest_sha256"], asset_manifest_bytes=len(manifest_bytes),
        asset_archive=prepared["manifest"]["archive"], asset_parts=prepared["manifest"]["parts"],
        asset_file_count=len(prepared["manifest"]["files"]),
        fixed_input=contract["fixed_input"], fresh_slots=contract["fresh_slots"],
        requested_artifacts=contract["requested_artifacts"],
        bundle_zip_member=contract["bundle_zip_member"],
        bundle_metadata_zip_member=contract["bundle_metadata_zip_member"],
        native_evidence_schema=contract["native_evidence_schema"],
        execution_schema=contract["execution_schema"],
        fresh_evidence_prepopulated=False, formal_training_fits=0, formal_task_dataset_reads=0,
        independent_nontask_budget_updates_registered=400, full_physical_energy_joules=None,
        native_producer_binding="Required separately from actual same-ledger job, fixed profile, stop proof and complete fetch receipts.",
        admission="HOLD until actual owned bind, capability, reviewed native assets and all fresh gates.")
    encoded = json.dumps(qualification, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    _new_file(output / "qualification-manifest-v3.json", encoded)
    return dict(schema="hcsn-colab-qualification-offline-build-v3", status="OFFLINE_READY",
        output_dir=str(output), qualification_manifest_sha256=sha(encoded),
        qualification_manifest_bytes=len(encoded), payload_sha256=launcher["code_sha256"],
        payload_bytes=launcher["code_bytes"], original42_source_pins=original42,
        control_source_files=controls, fixed_kernel_provider_sha256=sha(guard_raw),
        asset_manifest_sha256=prepared["manifest_sha256"], asset_archive=prepared["manifest"]["archive"],
        asset_part_count=len(prepared["manifest"]["parts"]),
        asset_max_part_bytes=max(p["bytes"] for p in prepared["manifest"]["parts"]),
        provider_operations=0, model_executions=0, task_dataset_reads=0, optimizer_updates=0)


def main():
    parser = argparse.ArgumentParser()
    for arg in ("original-source", "parent-plan", "contract-path", "bundle", "bundle-metadata",
                "fixed-kernel-provider", "output-dir"):
        parser.add_argument("--" + arg, required=True)
    parser.add_argument("--remote-root", default="/content/hepta_jobs")
    result = build(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
