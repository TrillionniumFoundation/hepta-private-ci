"""Context-reconstructed execution06 ancestry adapter; Linux metadata only.

Only the closed execution04 A17 may be imported. Independent external pins are
mandatory; original scientific bytes and seals are never rewritten.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time

from operational.parameter_field_recovery04 import durable_archive as archive

SOURCE_EPISODE = "execution04_durable_20261030"
TARGET_EPISODE = "execution06_detached_20261030"
PIN_SCHEMA = "hepta.execution06.a17-ancestry-pins.1"
RECEIPT_SCHEMA = "hepta.execution06.a17-import.1"
STUDY = "hepta.parameter-field.fullstudy.20261029.1"
PROTOCOL_SHA = "2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55"
PARENT_SHA = "2a5219147d38ebb6514059bd69e2d3489bf7d69d213cd01343455f63a08a53d2"
SOURCE_COMMIT = "bf59ac45860884d770dfd437d8a447068c5ef9a9"
FIXED_ANCHORS = {
    "manifest": "6d66a5864b773adad19d2d767cfe2bb536a22f4a3296e03540aa7b2f317b5bfc",
    "ack": "d7e9bcb25e6c665269980622fa7cff4e454134ef63699add94a5261c60d0e480",
    "ack_verified": "e89c99e65a0723b46cacf18183f860b12e8c7d23ff8ccfd0c52126bbed354e57",
    "config": "c1a541cd8fca9e43c710cfd5ccf1cb76793a28712d66eed65a238f158de0e57e",
    "source_freeze": "6cad1806689a4f5b6e7527139a5755b54cef16e921a093bb714cfc9c3bdec182",
    "profile": "30a8e41c8fa8692cfb6a79f1dfcf3a10c5f2cda1c7cdd4259e874d156c22ca7e",
    "runtime": "53eec2c5e41de7469d2f9a7afc0990b9d0fbc02cc454e52af73a1e8e20bc1b5b",
    "cleanup_plan": "0bed83ac65d1f54ea81621bc8cce26f856c1df651a844f7d58dfebe395829ed9",
    "cleanup_result": "413ade94e818bea442fd5e0649209d1ac0441ff097368d2a6c5102ddd1b02f80",
    "cleanup_journal": "66ec162dce8903102c12f558bfb9112d7b68e8ca5cde996a6d94dc21ad3c2d2e",
}
REQUIRED_ANCHORS = set(FIXED_ANCHORS) | {"request", "controller_result", "operation_complete",
    "scientific_complete", "archive_verification", "asset_restoration", "protocol"}
MAGIC = b"HEPTA_BRANCH_PREPARATION_1\n"
require = archive.require


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def absolute(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts and path.resolve() == path,
            "Require an absolute path without symlink components")
    return path


def checked(item):
    path = absolute(item["path"])
    require(type(item["bytes"]) is int and item["bytes"] >= 0
            and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "Invalid fixed descriptor")
    require(archive.descriptor(path) == {key: item[key] for key in ("path", "bytes", "sha256")},
            "Pinned bytes differ: " + str(path))
    return path


def hash_checked(path, expected):
    item = archive.descriptor(absolute(path))
    require(item["sha256"] == expected, "Pinned SHA differs: " + str(path))
    return item


def load_pins(path, expected_sha256):
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256), "An external pins SHA is required")
    return {"document": archive.read(checked(hash_checked(path, expected_sha256))),
            "descriptor": hash_checked(path, expected_sha256)}


def stage_inventory():
    rows = {"COMPLETE.json": None, "bank/BANK.json": None, "bank/trace.jsonl.gz": None, "paths/PATHS.json": None}
    for mode in ("field12", "full_current_state", "history6"):
        for suffix in ("head", "bank"):
            rows[f"bank/{mode}-{suffix}.npz"] = None
    for schedule in range(6000, 6004):
        for prefix in ("baseline", "balanced"):
            for step in range(0, 288, 48):
                stem = f"bank/schedule-{schedule}-{prefix}-step-{step}"
                rows[stem + ".state"] = (schedule, prefix, step)
                for action in range(4):
                    rows[stem + f"-action-{action}.npz"] = None
        for mode in ("ordinary", "field12", "full_current_state", "history6"):
            stem = f"paths/seed-17-schedule-{schedule}-{mode}"
            rows[stem + ".json"] = None
            rows[stem + ".state"] = (schedule, mode, 288)
    return rows


def _tagged_dict(node):
    require(isinstance(node, list) and len(node) == 2 and node[0] == "dict", "Expected metadata dictionary")
    result = {}
    for key, value in node[1]:
        require(key[0] == "str" and key[1] not in result, "Invalid/duplicate metadata key")
        result[key[1]] = value
    return result


def state_metadata(path):
    with Path(path).open("rb") as stream:
        require(stream.read(len(MAGIC)) == MAGIC, "Wrong state envelope magic")
        count = stream.read(8)
        require(len(count) == 8, "Truncated state header length")
        length = struct.unpack(">Q", count)[0]
        require(0 < length <= 1024 ** 2, "State header exceeds frozen bound")
        raw = stream.read(length)
        require(len(raw) == length, "Truncated state header")
    tree = _tagged_dict(json.loads(raw)["tree"])
    result = {}
    for section in ("binding", "cursor"):
        values = {}
        for key, node in _tagged_dict(tree[section]).items():
            require(node[0] in ("str", "int"), "Non-scalar provenance metadata")
            values[key] = node[1] if node[0] == "str" else int(node[1])
        result[section] = values
    return result


def _roots(pins):
    require(pins["schema"] == PIN_SCHEMA and pins["source_episode"] == SOURCE_EPISODE
            and pins["target_episode"] == TARGET_EPISODE, "Only the registered execution04 A17 import is allowed")
    old, ops, fresh = (absolute(pins[key]) for key in ("old_raw", "old_ops", "fresh_raw"))
    base = old.parent
    require(old == base / "fullstudy_execution04_durable_raw" and ops == base / "fullstudy_execution04_ops"
            and fresh == base / "fullstudy_execution06_durable_raw", "Wrong source/destination episode roots")
    return old, ops, fresh


def _sources(documents, anchors, expected, old, ops):
    config, freeze, profile = (documents[key] for key in ("config", "source_freeze", "profile"))
    source = old.parent / "fullstudy_git"
    require(config["execution_episode"] == freeze["execution_episode"] == SOURCE_EPISODE
            and config["raw_root"] == profile["raw_root"] == str(old) and config["ops_root"] == str(ops)
            and config["source_root"] == freeze["source_git_root"] == str(source), "Old producer paths/episode differ")
    require(expected["registered_commit"] == freeze["registered_commit"] == config["source_commit"] == SOURCE_COMMIT
            and expected["source_freeze_sha256"] == anchors["source_freeze"]["sha256"]
            and expected["profile_sha256"] == freeze["operational_amendment_sha256"] == anchors["profile"]["sha256"]
            and expected["protocol_sha256"] == freeze["protocol_sha256"] == anchors["protocol"]["sha256"] == PROTOCOL_SHA,
            "Old producer source/profile/protocol identity differs")
    require(config["descriptors"]["amendment"] == anchors["profile"]
            and config["descriptors"]["runtime_receipt"] == anchors["runtime"]
            and expected["runtime_receipt_sha256"] == anchors["runtime"]["sha256"], "Runtime/profile receipt binding differs")
    require(freeze["allowed_phases"] == ["A"] and freeze["attempt_id"] == "attempt02", "Wrong source phase")
    parent = freeze["scientific_parent"]
    require(parent["source_root"] == str(source) and parent["sha256"] == PARENT_SHA
            and parent["protocol_sha256"] == PROTOCOL_SHA, "Original science ancestor differs")
    hash_checked(parent["path"], PARENT_SHA)
    original = archive.read(parent["path"])
    require(original["registered_commit"] == parent["registered_commit"]
            and all(freeze["source_files"].get(name) == digest for name, digest in original["source_files"].items()),
            "Actual producer changed original scientific source closure")
    for name, digest in freeze["source_files"].items():
        hash_checked(source / archive.safe_relative(name), digest)
    for path, digest in freeze["artifacts"].items():
        hash_checked(path, digest)
    require(documents["asset_restoration"]["archive_sha256"] == expected["assets"]["original_archive_sha256"]
            and documents["asset_restoration"]["all_pinned_bytes_verified"] is True, "Original input archive identity differs")
    for name, digest in expected["assets"]["pinned_files"].items():
        hash_checked(old.parent / "assets_original" / archive.safe_relative(name), digest)
    return source, parent


def _durability(documents, anchors):
    manifest, request, ack, verified = (documents[key] for key in ("manifest", "request", "ack", "ack_verified"))
    binding = {"completed_jobs": ["A-17"], "execution_episode": SOURCE_EPISODE, "label": "A-17",
               "pipeline_config": anchors["config"], "previous_ack": None, "sequence": 1}
    require(all(document["binding"] == binding for document in (manifest, request, ack, verified)), "A17 archive/ACK binding differs")
    require(manifest["schema"] == "hepta.fullstudy.durable-archive-manifest.1"
            and request["schema"] == "hepta.fullstudy.library-archive-request.1"
            and ack["schema"] == "hepta.fullstudy.library-archive-ack.1"
            and ack["status"] == "VERIFIED_REMOTE_READBACK" and ack["unknown_upload_outcome"] is False
            and ack["request"] == anchors["request"] and verified["ack"] == anchors["ack"]
            and verified["request"] == anchors["request"] and verified["readback_bytes_verified_here"] is True,
            "The old remote ACK was not closed")
    plan, result = documents["cleanup_plan"], documents["cleanup_result"]
    require(plan["actual_ack"] == anchors["ack"] and plan["actual_ack_verified"] == anchors["ack_verified"]
            and result["plan"] == anchors["cleanup_plan"] and plan["count"] == result["count"] == 2
            and result["all_duplicate_paths_absent"] is True and result["all_originals_retained"] is True
            and result["remote_items_changed"] is False
            and result["historical_ack_reverification_requires_rematerializing_duplicate_bytes"] is True,
            "Missing/invalid readback retirement evidence")
    retired = plan["rows"]
    require(len(retired) == 2 and result["removed"] == [row["duplicate"] for row in retired], "Retired readback inventory differs")
    journal = [json.loads(line) for line in Path(anchors["cleanup_journal"]["path"]).read_text().splitlines()]
    require(journal == [entry for row in retired for entry in (
        {"intent": row["duplicate"], "stat": row["stat"]},
        {"unlinked": row["duplicate"], "immediately_absent": True})], "Readback retirement journal differs")
    require(len(request["items"]) == len(ack["items"]) == verified["items_verified"] == 5, "Incomplete remote archive population")
    require([item["local"] for item in ack["items"]] == request["items"], "ACK ordered items differ")
    require([part["artifact"] for part in manifest["parts"]] == request["items"][:2]
            and request["items"][2] == anchors["manifest"] and request["items"][3] == anchors["archive_verification"],
            "Archive parts/manifest receipt chain differs")
    ids = []
    for index, item in enumerate(ack["items"]):
        checked(item["local"])
        remote = item["remote_identity"]
        require(item["upload_item_success"] is True and item["remote_readback_performed"] is True
                and item["readback_remote_identity"] == remote
                and item["library_file_id_xattr_verified"] == remote["library_file_id"], "Remote identity/readback binding differs")
        ids.append(remote["library_file_id"])
        for key in ("upload_receipt", "upload_wait4", "readback_receipt", "complete_transfer_receipt", "readback_helper_stdout", "readback_helper_wait4"):
            checked(item[key])
        if index < 2:
            row = retired[index]
            require(row["duplicate"] == item["readback"] and row["retained_original"] == item["local"]
                    and row["remote_identity"] == remote and row["verified_remote_identity_xattr"] == remote["library_file_id"]
                    and not os.path.lexists(item["readback"]["path"]), "Only the two actually retired duplicates may be absent")
        else:
            checked(item["readback"])
        require(all(item["readback"][key] == item["local"][key] for key in ("bytes", "sha256")), "Readback bytes differ")
    require(len(set(ids)) == 5 and sorted(ids) == verified["remote_library_file_ids"], "Remote archive identity set differs")
    checked(ack["root_operational_binding"])
    check = archive.verify_parts(manifest, Path(anchors["manifest"]["path"]).parent)
    prior = documents["archive_verification"]
    require(prior["manifest"] == anchors["manifest"] and prior["binding"] == binding
            and all(prior[key] == value for key, value in check.items()), "Original streaming archive verification differs")
    return check


@dataclass(frozen=True)
class VerifiedImport:
    pins: bytes
    pins_descriptor: bytes
    plan: bytes


def validate_import(pins, old_raw, old_ops):
    started, cpu = time.monotonic(), time.process_time()
    hash_checked(Path(archive.__file__).resolve(), "dfeee33870f3ca429284542cb8ca9ff8c9471a8fc8ff0339c3de251cabf260da")
    checked(pins["descriptor"])
    require(archive.read(pins["descriptor"]["path"]) == pins["document"], "Pins document changed after loading")
    value = pins["document"]
    old, ops, fresh = _roots(value)
    require(absolute(old_raw) == old and absolute(old_ops) == ops, "Caller source roots differ")
    anchors, expected = value["anchors"], value["expected"]
    require(REQUIRED_ANCHORS <= set(anchors), "Missing externally pinned ancestry anchors")
    for key, digest in FIXED_ANCHORS.items():
        require(anchors[key]["sha256"] == digest, "Wrong execution04 trust anchor: " + key)
    for item in anchors.values():
        checked(item)
    documents = {key: archive.read(item["path"]) for key, item in anchors.items() if key != "cleanup_journal"}
    source, parent = _sources(documents, anchors, expected, old, ops)
    archive_check = _durability(documents, anchors)
    manifest, inventory = documents["manifest"], stage_inventory()
    prefix = "raw/stage_A/seed-17/"
    stage = {row["path"][len(prefix):]: row for row in manifest["files"] if row["path"].startswith(prefix)}
    require(set(stage) == set(inventory) and len(stage) == 282, "The complete fixed A17 stage population is required")
    files = archive.regular_tree(old / "stage_A/seed-17")
    require({str(path.relative_to(old / "stage_A/seed-17")) for path in files} == set(inventory), "Missing/additional A17 artifacts")
    require(not any(row["path"].startswith("raw/stage_A/") and not row["path"].startswith(prefix) for row in manifest["files"]),
            "A partial/different seed cannot be imported")
    for name in ("stage_A/seed-17/FAILED.json", "operations/A-seed-17.FAILED.json"):
        require(not os.path.lexists(old / name), "A17 has failure evidence")
    indexed = {row["path"]: row for row in manifest["files"]}
    require(len(indexed) == len(manifest["files"]), "Duplicate archive logical paths")
    for row in manifest["files"]:
        if row["path"].startswith("raw/"):
            require(Path(row["source"]) == old / archive.safe_relative(row["path"][4:]), "Archive source root differs")
        checked({"path": row["source"], "bytes": row["bytes"], "sha256": row["sha256"]})
    for key, relative in (("scientific_complete", "stage_A/seed-17/COMPLETE.json"),
                          ("operation_complete", "operations/A-seed-17.COMPLETE.json"), ("controller_result", "controller/A-17.RESULT.json")):
        row = indexed["raw/" + relative]
        require(anchors[key] == {"path": str(old / relative), "bytes": row["bytes"], "sha256": row["sha256"]}, "Completion is outside sealed manifest")
    science, operation, controller = (documents[key] for key in ("scientific_complete", "operation_complete", "controller_result"))
    require(science["complete"] is True and operation["complete"] is True and controller["complete"] is True
            and controller["exit_code"] == 0 and operation["schema"] == "hepta.fullstudy.training-operation.2"
            and operation["attempt_id"] == "attempt02" and operation["execution_kind"] == "training"
            and science["phase"] == operation["phase"] == "A" and science["seed"] == operation["seed"] == 17
            and science["path_count"] == 16 and science["costs"]["scheduled_gradient_microsteps"] == 39168,
            "A17 is not a closed complete registered training job")
    require(science["registered_commit"] == operation["registered_commit"] == expected["registered_commit"]
            and science["source_freeze_sha256"] == operation["source_freeze_sha256"] == expected["source_freeze_sha256"]
            and operation["operational_amendment_sha256"] == expected["profile_sha256"]
            and operation["scientific_protocol_sha256"] == operation["entrypoint_protocol_sha256"] == PROTOCOL_SHA
            and operation["post_execution_storage_check"] is True and operation["scientific_source_bytes_unchanged"] is True
            and operation["scientific_parent"] == parent and science["assets"] == expected["assets"], "A17 producer/input identity differs")
    for outer, field, inner in ((operation, "scientific_complete", anchors["scientific_complete"]), (controller, "completion", anchors["operation_complete"])):
        require(outer[field] == {**inner, "path": str(Path(inner["path"]).relative_to(old))}, "Broken completion chain")
    binding = {"study_id": STUDY, "protocol_sha256": PROTOCOL_SHA,
               "source_freeze_sha256": expected["source_freeze_sha256"], "runtime_sha256": expected["runtime_sha256"]}
    require(re.fullmatch(r"[0-9a-f]{64}", binding["runtime_sha256"]), "Missing state runtime identity")
    for name, cursor in inventory.items():
        if cursor is not None:
            schedule, kind, clock = cursor
            require(state_metadata(stage[name]["source"]) == {"binding": binding, "cursor": {
                "seed": 17, "schedule_id": schedule, "path_kind": kind, "clock": clock,
                "remaining_steps": 288 - clock, "total_steps": 288, "guard_grain": 48, "baseline_action": 2}}, "State identity differs: " + name)
    materialize = [{"source": {"path": row["source"], "bytes": row["bytes"], "sha256": row["sha256"]},
                    "relative": "stage_A/seed-17/" + name} for name, row in sorted(stage.items())]
    materialize += [{"source": anchors["operation_complete"], "relative": "operations/A-seed-17.COMPLETE.json"},
                    {"source": anchors["controller_result"], "relative": "imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json"}]
    plan = {"source_episode": SOURCE_EPISODE, "target_episode": TARGET_EPISODE, "seed": 17, "fresh_raw": str(fresh),
            "source_root": str(source), "expected": expected, "anchors": anchors, "scientific_parent": parent,
            "materialize": materialize, "stage_files": len(stage), "state_headers": 64, "archive_verification": archive_check,
            "validation_cpu_seconds": time.process_time() - cpu, "validation_wall_seconds": time.monotonic() - started}
    return VerifiedImport(canonical(value), canonical(pins["descriptor"]), canonical(plan))


def materialize_import(verified, fresh_raw, method="copy"):
    require(isinstance(verified, VerifiedImport) and method in ("copy", "hardlink"), "Invalid verified import/method")
    started, cpu = time.monotonic(), time.process_time()
    pins = {"document": json.loads(verified.pins), "descriptor": json.loads(verified.pins_descriptor)}
    old, ops, fresh = _roots(pins["document"])
    require(absolute(fresh_raw) == fresh and not os.path.lexists(fresh), "Import destination must be registered and nonexistent")
    plan = json.loads(validate_import(pins, old, ops).plan)
    fresh.mkdir(exist_ok=False)
    receipt_root = fresh / "imports/execution04/A-17"
    receipt_root.mkdir(parents=True)
    archive.write_json(receipt_root / "IMPORT_STARTED.json", {"source_episode": SOURCE_EPISODE, "target_episode": TARGET_EPISODE,
                       "pins": pins["descriptor"], "method": method, "scientific_workers_started": 0})
    try:
        for row in plan["materialize"]:
            source = checked(row["source"])
            target = fresh / archive.safe_relative(row["relative"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if method == "hardlink":
                os.link(source, target, follow_symlinks=False)
            else:
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    while chunk := incoming.read(1024 ** 2):
                        outgoing.write(chunk)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
            checked({**row["source"], "path": str(target)})
            checked(row["source"])
        receipt = {"schema": RECEIPT_SCHEMA, "complete": True, "imported": True, "executed_here": False,
            "automatic_scientific_retry": False, "original_seals_modified": False, "pins": pins["descriptor"], "method": method, **plan,
            "scientific_cost_owner": SOURCE_EPISODE + ":A-17",
            "scientific_cost_counting": "Include original A17 once; exclude it from failed-attempt increments.",
            "new_scheduled_gradient_microsteps": 0, "scientific_workers_started": 0, "new_controller_started": False,
            "old_remote_ack_reauthenticated_here": False, "readback_retirement_scope": "Only the two pinned actually removed duplicates.",
            "import_cost_scope": "Repeated validation/materialization/hash checks; excludes final receipt serialization/write.",
            "validation_cost_nested_in_import_cost": True,
            "import_cpu_seconds": time.process_time() - cpu, "import_wall_seconds": time.monotonic() - started}
        return archive.write_json(receipt_root / "IMPORT_RECEIPT.json", receipt)
    except BaseException as error:
        archive.write_json(receipt_root / "IMPORT_FAILED.json", {"complete": False, "error_type": type(error).__name__, "error": str(error),
            "automatic_retry_safe": False, "partial_import_preserved": True, "scientific_workers_started": 0,
            "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.monotonic() - started})
        raise


def producer_map(import_receipt, fresh_registration):
    receipt = archive.read(checked(import_receipt))
    require(receipt["schema"] == RECEIPT_SCHEMA and receipt["complete"] is True and receipt["imported"] is True
            and receipt["executed_here"] is False and receipt["source_episode"] == SOURCE_EPISODE
            and receipt["target_episode"] == TARGET_EPISODE and receipt["seed"] == 17
            and receipt["scientific_cost_owner"] == SOURCE_EPISODE + ":A-17" and receipt["new_scheduled_gradient_microsteps"] == 0,
            "Invalid imported producer receipt")
    value, fresh = fresh_registration, Path(receipt["fresh_raw"])
    require(value["execution_episode"] == TARGET_EPISODE and value["raw_root"] == str(fresh)
            and value["source_root"] == str(fresh.parent / "fullstudy_recovery06_git")
            and re.fullmatch(r"[0-9a-f]{40}", value["registered_commit"]) and value["protocol_sha256"] == PROTOCOL_SHA
            and value["runtime_sha256"] == receipt["expected"]["runtime_sha256"], "Fresh registration identity differs")
    for key in ("source_freeze", "profile"):
        checked(value[key])
    freeze, profile = (archive.read(value[key]["path"]) for key in ("source_freeze", "profile"))
    require(freeze["execution_episode"] == TARGET_EPISODE and freeze["allowed_phases"] == ["A"]
            and freeze["registered_commit"] == value["registered_commit"]
            and freeze["operational_amendment_sha256"] == value["profile"]["sha256"] and freeze["protocol_sha256"] == PROTOCOL_SHA
            and profile["raw_root"] == str(fresh) and freeze["scientific_parent"]["sha256"] == PARENT_SHA, "Fresh producer freeze/profile differs")
    original = archive.read(receipt["scientific_parent"]["path"])
    for name, digest in original["source_files"].items():
        require(freeze["source_files"].get(name) == digest, "Fresh producer changed frozen scientific bytes")
        hash_checked(Path(value["source_root"]) / archive.safe_relative(name), digest)
    shared = {"phase": "A", "raw_root": str(fresh), "protocol_sha256": PROTOCOL_SHA, "runtime_sha256": value["runtime_sha256"]}
    result = {str(seed): {**shared, "seed": seed, "kind": "executed", "execution_episode": TARGET_EPISODE,
        "registered_commit": value["registered_commit"], "source_root": value["source_root"], "source_freeze": value["source_freeze"],
        "profile": value["profile"], "scientific_parent": freeze["scientific_parent"]} for seed in (29, 43)}
    result["17"] = {**shared, "seed": 17, "kind": "imported", "execution_episode": SOURCE_EPISODE,
        "registered_commit": receipt["expected"]["registered_commit"], "source_root": receipt["source_root"],
        "source_freeze": receipt["anchors"]["source_freeze"], "profile": receipt["anchors"]["profile"],
        "scientific_parent": receipt["scientific_parent"], "import_receipt": import_receipt, "scientific_cost_owner": receipt["scientific_cost_owner"]}
    return result


def verify_producer(seed, operation_descriptor, expected_map):
    require(type(seed) is int and seed in (17, 29, 43) and set(expected_map) == {"17", "29", "43"}, "Wrong source population")
    for key, row in expected_map.items():
        require(row["seed"] == int(key) and row["phase"] == "A" and row["kind"] == ("imported" if key == "17" else "executed")
                and row["execution_episode"] == (SOURCE_EPISODE if key == "17" else TARGET_EPISODE), "Producer-map scope differs")
    require(expected_map["17"]["source_freeze"]["sha256"] == FIXED_ANCHORS["source_freeze"]
            and expected_map["17"]["profile"]["sha256"] == FIXED_ANCHORS["profile"]
            and expected_map["29"]["source_freeze"] == expected_map["43"]["source_freeze"]
            and expected_map["29"]["profile"] == expected_map["43"]["profile"]
            and expected_map["29"]["source_freeze"]["sha256"] != FIXED_ANCHORS["source_freeze"]
            and expected_map["29"]["profile"]["sha256"] != FIXED_ANCHORS["profile"], "Wrong producer pair")
    row = expected_map[str(seed)]
    raw = absolute(row["raw_root"])
    require(Path(operation_descriptor["path"]) == raw / f"operations/A-seed-{seed}.COMPLETE.json", "Operation outside fresh RAW")
    operation = archive.read(checked(operation_descriptor))
    require(operation["complete"] is True and operation["phase"] == "A" and operation["seed"] == seed
            and operation["attempt_id"] == "attempt02" and operation["post_execution_storage_check"] is True
            and operation["scientific_source_bytes_unchanged"] is True and operation["registered_commit"] == row["registered_commit"]
            and operation["source_freeze_sha256"] == row["source_freeze"]["sha256"]
            and operation["operational_amendment_sha256"] == row["profile"]["sha256"]
            and operation["scientific_protocol_sha256"] == operation["entrypoint_protocol_sha256"] == PROTOCOL_SHA, "Operation producer differs")
    require(operation["scientific_parent"] == row["scientific_parent"]
            and operation["scientific_complete"]["path"] == f"stage_A/seed-{seed}/COMPLETE.json", "Scientific ancestor/completion path differs")
    science = archive.read(checked({**operation["scientific_complete"], "path": str(raw / operation["scientific_complete"]["path"])}))
    require(science["complete"] is True and science["phase"] == "A" and science["seed"] == seed
            and science["source_freeze_sha256"] == row["source_freeze"]["sha256"]
            and science["registered_commit"] == row["registered_commit"], "Scientific completion producer differs")
    if seed == 17:
        receipt = archive.read(checked(row["import_receipt"]))
        require(all(operation_descriptor[key] == receipt["anchors"]["operation_complete"][key] for key in ("bytes", "sha256")),
                "Imported operation must retain original seal bytes")
    return row
