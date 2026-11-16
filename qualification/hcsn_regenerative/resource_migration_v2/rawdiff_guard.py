"""Exact prospective V1->V2 identity/budget diff and native artifact gates.

No network, provider operation, task data generation, training or owner recovery.
Native receipt/payload hashes are supplied from independently reviewed actual
readback; a self-reported authenticated/status boolean is never sufficient.
"""

import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


PARENT_SHA = "cc2fe01594bd77721eda1f2a3130257ba5dbfa61c498a9f469f91195598c2550"
STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v2"
SLOTS = ("unit", "graph_cpu", "graph_cuda", "sequence_cpu", "sequence_cuda", "resolution", "fixed_renewal", "budget")
ALLOWED_CHANGED = {"study_id", "frozen_at", "source_pins", "qualification_receipts", "numerical_resolution", "execution_environment"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def raw(path, limit=268435456):
    path = Path(path).absolute()
    require(".." not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), "Unsafe input path")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit, "Unsafe or oversized input")
    data = path.read_bytes()
    after = path.stat()
    version = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    require(version(before) == version(after) and len(data) == before.st_size, "Input changed during read")
    return data


def read(path, expected=None):
    data = raw(path)
    require(expected is None or digest(data) == expected, "Raw SHA256 mismatch: " + str(path))
    def pairs(items):
        value = {}
        for key, entry in items:
            require(key not in value, "Duplicate JSON key")
            value[key] = entry
        return value
    value = json.loads(data, object_pairs_hook=pairs)
    canonical(value)
    return value


def amendment():
    return read(Path(__file__).with_name("RESOURCE_AMENDMENT.json"))


def audit_diff(parent, child, registration=None):
    """Allow only declared fresh resource/provenance differences; zero tuning."""
    registration = registration or amendment()
    require(set(child) == set(parent) | {"resource_migration"}, "Plan keys changed outside the resource amendment")
    for key in set(parent) - ALLOWED_CHANGED:
        require(child[key] == parent[key], "Scientific/budget/statistical field changed: " + key)
    require(child["study_id"] == STUDY_ID and child["study_id"] != parent["study_id"], "Distinct fixed V2 identity required")
    require(child["frozen_at"] != parent["frozen_at"], "Old freeze timestamp reused")
    original = parent["source_pins"]
    require(original == registration["preserved_parent_source_pins"] and len(original) == 42, "Parent42 map differs")
    require(all(child["source_pins"].get(name) == value for name, value in original.items()), "Original science/source pin changed")
    require(set(child["source_pins"]) - set(original) == set(registration["additional_source_paths"]), "Undeclared extra source/control pin")
    require(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in child["source_pins"].values()), "Invalid source pin")
    require(set(child["qualification_receipts"]) == set(SLOTS), "Fresh eight-slot qualification roster differs")
    for name in SLOTS:
        value = child["qualification_receipts"][name]
        require(value["sha256"] != parent["qualification_receipts"][name]["sha256"], "Old qualification receipt reused as fresh: " + name)
        require(value["schema"] == parent["qualification_receipts"][name]["schema"] and value["status"] == parent["qualification_receipts"][name]["status"], "Qualification status/schema changed")
    numerical = child["numerical_resolution"]
    require(set(numerical) == set(parent["numerical_resolution"]) and numerical["active_cells"] == 64
            and numerical["phase_cells"] == 16 and numerical["eligible"] is True, "Fixed S81 grid changed")
    for key, ceiling in (("maximum_state_l1_error", .02), ("maximum_hit_relative_error", .03)):
        require(type(numerical[key]) in (int, float) and math.isfinite(numerical[key]) and 0 <= numerical[key] <= ceiling, "Fixed S81 error gate failed")
    environment = child["execution_environment"]
    require(set(environment) == set(parent["execution_environment"]) and environment["gpu"] == parent["execution_environment"]["gpu"]
            and environment["gpu_uuid_policy"] == "same_model_new_lease" and environment["device"] == "cuda"
            and environment["cpu_threads"] == 1 and environment["deterministic_algorithms"] is True, "Unqualified device class/execution policy")
    lineage = child["resource_migration"]
    require(lineage["parent_plan_sha256"] == PARENT_SHA and lineage["parent_study_id"] == parent["study_id"]
            and lineage["account_selector"] == "tomas" and lineage["expected_username"] == "braynttomas"
            and lineage["prior_v1_state_unchanged"] is True and lineage["v1_fit_completion_credit"] == 0,
            "Resource lineage or original-owner preservation differs")
    require(lineage["qualification_request_id"] == registration["qualification_request_id"]
            and lineage["native_producer"]["notebook_ref"].startswith("braynttomas/")
            and lineage["native_producer"]["notebook_version"] == 1, "New qualification producer identity differs")
    require(all(re.fullmatch(r"[0-9a-f]{64}", lineage[name]) for name in
                ("native_receipt_sha256", "qualification_payload_sha256", "qualification_manifest_sha256", "amendment_sha256")), "Missing exact native/prospective proof pins")
    return dict(schema="hcsn-s81-resource-rawdiff-v2", status="DECLARED_RESOURCE_DIFF_ONLY",
                unchanged_parent_source_files=42, added_source_files=len(registration["additional_source_paths"]),
                registered_training_attempts=160, registered_optimizer_updates=64000,
                independent_training_seeds_per_task_arm=4, statistical_family_size=20,
                original_campaign_completion_credit=0, v1_fit_completion_credit=0,
                full_physical_energy_joules=None, expansion_admission="HOLD")


def verify_archive(archive, expected, paths, parent):
    blob = raw(archive)
    require(dict(bytes=len(blob), sha256=digest(blob)) == expected, "Actual qualification archive differs")
    hashes = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) <= 1000 and sum(i.file_size for i in z.infolist()) <= 268435456, "Duplicate/oversized qualification archive")
        for item in z.infolist():
            name = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            require(not name.is_absolute() and ".." not in name.parts and str(name) == item.filename
                    and not stat.S_ISLNK(mode) and item.file_size <= 33554432, "Unsafe qualification member")
            if not item.is_dir():
                hashes[item.filename] = digest(z.read(item))
        require(z.testzip() is None, "Qualification archive CRC failed")
    for name, path in paths.items():
        value = digest(raw(path))
        require(value in hashes.values(), "Input is not an actual fresh archive member: " + name)
        if name in SLOTS:
            require(value != parent["qualification_receipts"][name]["sha256"], "Old receipt relabelled as fresh: " + name)
    return hashes


def archive_inputs(paths):
    require(set(paths) == set(SLOTS) | {"bundle", "output"}, "Freezer input roster differs")
    result = {name: paths[name] for name in (*SLOTS, "bundle")}
    result["metadata"] = paths["bundle"].with_suffix(".json")
    return result


def preflight(args, paths):
    """Bind new native producer, actual HTTP/artifact bytes and all fresh slots."""
    registration = amendment()
    parent = read(args.parent_plan, PARENT_SHA)
    require(parent["source_pins"] == registration["preserved_parent_source_pins"], "Wrong original source identity")
    read(args.scope_receipt, registration["resource_selection"]["scope_receipt_sha256"])
    manifest = read(args.qualification_manifest, args.qualification_manifest_sha256)
    require(manifest["resource_lineage_id"] == STUDY_ID and manifest["account_selector"] == "tomas"
            and manifest["expected_username"] == "braynttomas"
            and manifest["request_id"] == registration["qualification_request_id"], "Prospective resource/payload identity differs")
    require(manifest["source_files"] == registration["qualification_source_files"]
            and manifest["source_set_sha256"] == registration["qualification_source_set_sha256"], "Exact35 qualification source map changed")
    require([c["name"] for c in manifest["commands"]] == registration["fresh_qualification"]["stages"]
            and sum(c["timeout_seconds"] for c in manifest["commands"]) == 2700
            and manifest["provider_timeout_seconds"] == 3000, "Prospective qualification roster/budget changed")
    native = read(args.native_receipt, args.native_receipt_sha256)
    require(native.get("status") == "terminal_artifact_readback_verified" and native.get("remote_terminal_observed") is True,
            "Native qualification not authoritatively terminal")
    remote, artifacts = native["latest_remote"], native["artifacts"]
    request = registration["qualification_request_id"]
    require(remote.get("schema") == "hepta-kaggle-job-v1" and remote.get("request_id") == request
            and native.get("request_id") == request and remote.get("remote_state") == "COMPLETE"
            and remote.get("remote_effect_unknown") is False and remote.get("identity_verified") is True
            and remote.get("remote_submission_state") == "ACKNOWLEDGED" and remote.get("submission_state") == "ACCEPTED", "Native producer/effect is unknown or failed")
    account = remote["account"]
    require(account.get("username") == "braynttomas" and account.get("user_id") == 37790778
            and account.get("method") == "oauth" and account.get("verification") == "official_token_introspection",
            "Qualification came from a different authorised namespace")
    require(re.fullmatch(r"braynttomas/[a-z0-9-]+", remote.get("notebook_ref", ""))
            and type(remote.get("notebook_version")) is int and remote["notebook_version"] == 1
            and type(remote.get("kernel_id")) is int and remote["kernel_id"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", remote.get("input_digest", "")), "Actual new private producer identity absent")
    intent = remote["intent"]
    require(intent["source_sha256"] == native["payload_sha256"] == manifest["payload_sha256"]
            and intent["timeout_seconds"] == 3000 and intent["accelerator"] == "NvidiaTeslaT4"
            and intent["is_private"] is True and intent["internet"] is False
            and all(intent.get(name, []) == [] for name in ("kernel_sources", "dataset_sources", "model_sources", "competition_sources")),
            "Payload changed or accessed another provider input")
    require(artifacts.get("verification_policy") == "manifest-and-http-v1" and artifacts.get("remote_manifest_verified") is True
            and artifacts.get("remote_manifest_name") == "artifact-manifest.json", "Actual HTTP/manifest readback missing")
    for key in ("request_id", "notebook_ref", "notebook_version", "input_digest"):
        require(artifacts.get(key) == remote[key], "Artifact and producer identities differ")
    artifact_root, entries = Path(args.artifact_root), artifacts["files"]
    require(len(entries) == len({x["path"] for x in entries}) <= 1000, "Artifact listing duplicated")
    inventory = {}
    for row in entries:
        name = PurePosixPath(row["path"])
        require(not name.is_absolute() and ".." not in name.parts and str(name) == row["path"], "Unsafe artifact path")
        data = raw(artifact_root / str(name))
        require(row.get("http_content_length_verified") is True and row["bytes"] == len(data)
                and row["sha256"] == digest(data), "Actual native artifact bytes differ")
        inventory[row["path"]] = dict(bytes=len(data), sha256=digest(data))
    actual_manifest = read(artifact_root / "artifact-manifest.json")
    require(actual_manifest["request_id"] == request
            and len(actual_manifest["files"]) == len(inventory)-1
            and {x["path"]: dict(bytes=x["bytes"], sha256=x["sha256"]) for x in actual_manifest["files"]}
                == {k: v for k, v in inventory.items() if k != "artifact-manifest.json"}, "Actual artifact manifest roster differs")
    execution = read(artifact_root / "execution.json")
    require(execution == native["execution"] and execution["request_id"] == request and execution["status"] == "pass"
            and execution["source_unchanged"] is True and execution["formal_training_fits"] == 0
            and execution["source_files"] == registration["qualification_source_files"], "Actual execution/source differs")
    stages = execution["stages"]
    require([s["name"] for s in stages] == registration["fresh_qualification"]["stages"], "Missing, reordered or duplicate fresh stage")
    for stage, command in zip(stages, manifest["commands"]):
        require(stage.get("returncode") == 0 and stage.get("skipped") is False
                and stage.get("semantic_gate_pass") is True and stage.get("timeout") is False
                and stage.get("timeout_seconds") == command["timeout_seconds"]
                and stage.get("argv", [])[1:] == ["-B", *command["args"]], "Failed/skipped/changed fresh qualification command")
    hashes = verify_archive(artifact_root / "suite-artifacts.zip", inventory["suite-artifacts.zip"],
                            archive_inputs(paths), parent)
    lineage = dict(parent_plan_sha256=PARENT_SHA, parent_study_id=parent["study_id"], account_selector="tomas",
        expected_username="braynttomas", prior_v1_state_unchanged=True, v1_fit_completion_credit=0,
        qualification_request_id=request, native_receipt_sha256=args.native_receipt_sha256,
        qualification_payload_sha256=manifest["payload_sha256"], qualification_manifest_sha256=args.qualification_manifest_sha256,
        amendment_sha256=digest(raw(Path(__file__).with_name("RESOURCE_AMENDMENT.json"))),
        native_producer={k: remote[k] for k in ("notebook_ref", "notebook_version", "kernel_id", "input_digest")},
        qualification_archive=inventory["suite-artifacts.zip"], scope_receipt_sha256=registration["resource_selection"]["scope_receipt_sha256"],
        reused_asset_only=dict(bundle_sha256=parent["bundle_sha256"], metadata_sha256=parent["bundle_metadata_sha256"], v1_qualification_credit=0),
        fresh_qualification_cost_scope="Actual new runtime only; all prior costs and failures retained separately, no nested-scope total",
        full_physical_energy_joules=None)
    return parent, lineage


def add_prospective_pins(plan, source_root):
    for name in amendment()["additional_source_paths"]:
        require(name not in plan["source_pins"], "V2 control path overwrites an original source pin")
        plan["source_pins"][name] = digest(raw(Path(source_root) / name))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-plan", required=True)
    parser.add_argument("--candidate-plan", required=True)
    args = parser.parse_args()
    print(json.dumps(audit_diff(read(args.parent_plan, PARENT_SHA), read(args.candidate_plan)), sort_keys=True))


if __name__ == "__main__":
    main()
