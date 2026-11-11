#!/usr/bin/env python3
"""Offline verification of retained source metadata; never starts a host or model."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

PIN_SHA = "f5b31eba60a4606ebd967bc8360173d2b1b0dc4e90d2b4fad91ff3759061a8e7"
EXPECTED_HOST_SHA = "e7c0e282168dc4ad02b3f4ed49b8d25393cf98b285039d8b3daf19d83d9a6ae5"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pairs(values):
    out = {}
    for key, value in values:
        require(key not in out, "duplicate JSON key")
        out[key] = value
    return out


def parse(data):
    return json.loads(data, object_pairs_hook=pairs)


def canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def pointer(value, field):
    require(field.startswith("/"), "not a JSON pointer")
    for token in field[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def read_checked(path, pin):
    raw = path.read_bytes()
    require(len(raw) == pin["bytes"] and sha(raw) == pin["sha256"], f"pin: {path.name}")
    if "git_blob" in pin:
        require(blob(raw) == pin["git_blob"], f"Git blob: {path.name}")
    return raw


def check_archive(path, pins, prepare, categories, mem5, model):
    expected = pins["external_archives"]["mem6"]
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    require(path.stat().st_size == expected["bytes"], "full CAS length")
    require(h.hexdigest() == expected["sha256"], "full CAS SHA")
    wanted = {row["sha256"] for row in pins["mem6_logical_metadata"]}
    objects = {}
    manifest_raw = None
    member_count = 0
    with tarfile.open(path, "r|xz") as bundle:
        for entry in bundle:
            require(entry.isfile(), "unexpected CAS member type")
            member_count += 1
            if entry.name == "MANIFEST.json":
                manifest_raw = bundle.extractfile(entry).read()
            elif entry.name.startswith("objects/") and entry.name[8:] in wanted:
                require(entry.name[8:] not in objects, "duplicate requested CAS object")
                objects[entry.name[8:]] = bundle.extractfile(entry).read()
    require(member_count == 7123, "CAS physical member count")
    require(manifest_raw is not None, "missing CAS manifest")
    require(len(manifest_raw) == expected["manifest_bytes"], "CAS manifest length")
    require(sha(manifest_raw) == expected["manifest_sha256"], "CAS manifest SHA")
    manifest = parse(manifest_raw)
    logical = {row["path"]: row for row in manifest["files"]}
    require(len(logical) == len(manifest["files"]) == 10365, "CAS logical count")
    require(sum(row["bytes"] for row in logical.values()) == 243281645, "CAS logical bytes")
    selected = {}
    for row in pins["mem6_logical_metadata"]:
        require(logical[row["path"]] == row, "CAS mapping differs")
        raw = objects[row["sha256"]]
        require(len(raw) == row["bytes"] and sha(raw) == row["sha256"], "CAS object pin")
        selected[row["path"]] = parse(raw)
    retention = selected["freeze-retention/PLAN.json"]
    selector = selected["freeze-selector/PLAN.json"]
    require({x["source_group_id"] for x in retention["episodes"]} == categories["mem6_working_state"], "CAS retention roster")
    require({x["source_group_id"] for x in selector["episodes"]} == categories["mem6_selector"], "CAS selector roster")
    inherited = set(mem5["excluded_source_groups"]) | categories["mem5_selector"]
    require(set(retention["excluded_source_groups"]) == inherited, "CAS inherited 33")
    require(set(selector["excluded_source_groups"]) == inherited | categories["mem6_working_state"], "CAS reserved 53")
    require(retention["groups_per_role"] == {"development": 16, "retention_validation": 4}, "CAS retention allocation")
    require(selected["retention-request.json"]["groups_per_role"] == retention["groups_per_role"], "CAS request allocation")
    require(selected["selector-request.json"]["groups_per_role"] == selector["groups_per_role"] == {"development": 10, "retention_validation": 4}, "CAS selector allocation")
    require(set(selected["reserved-retention-exposure.json"]["quarantined_source_groups"]) == categories["mem6_working_state"], "CAS reservation")
    require(selected["PREPARE_RECEIPT.json"] == prepare, "CAS prepare bytes")
    require(selected["freeze-retention/MODEL.json"] == model, "CAS model bytes")
    return {"status": "PASS", "bytes": expected["bytes"], "sha256": expected["sha256"],
            "physical_members": member_count, "logical_members": len(logical),
            "selected_metadata_members": len(selected), "unselected_objects_parsed": 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--mem6-archive", type=Path)
    ap.add_argument("--mem5-zip", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    root = args.root
    raw_pins = (root / "METADATA_INPUT_PINS.json").read_bytes()
    require(sha(raw_pins) == PIN_SHA, "input index SHA")
    pins = parse(raw_pins)
    by_pin = {row["path"]: row for row in pins["files"]}
    require(len(by_pin) == len(pins["files"]) == 17, "input roster")
    raw = {name: read_checked(root / name, pin) for name, pin in by_pin.items()}
    data = {name: parse(value) for name, value in raw.items() if name.endswith(".json")}
    host = data["HOST_INVENTORY.stdout.json"]
    status = data["HOST_STATUS.json"]
    start = data["HOST_START.json"]
    prepare = data["inputs/PREPARE_RECEIPT.json"]
    mem5 = data["inputs/mem5/PLAN.json"]
    model = data["inputs/MODEL.json"]
    selected = data["inputs/cell-causal/selected-sources.json"]
    pilot = data["inputs/cell-causal/PILOT_PLAN.json"]
    aggregate = data["inputs/cell-causal/EVALUATION_RESULT.json"]
    acceptance = data["inputs/protocol/ACCEPTANCE.json"]
    require(sha(raw["HOST_INVENTORY.stdout.json"]) == EXPECTED_HOST_SHA, "host stdout")
    offset = 0
    rebuilt = bytearray()
    for receipt in data["HOST_READ_RANGES.json"]:
        require(receipt["job_id"] == status["job_id"], "range job")
        row = receipt["stdout"]
        chunk = bytes.fromhex(row["bytes_hex"])
        require(chunk == row["text"].encode(), "range text/hex")
        require(row["offset"] == offset and row["next_offset"] == offset + len(chunk), "range gap")
        require(row["size"] == 58248, "range original size")
        require(receipt["stderr"]["bytes_hex"] == "" and receipt["stderr"]["size"] == 0, "unexpected stderr")
        rebuilt.extend(chunk)
        offset = row["next_offset"]
    require(bytes(rebuilt) == raw["HOST_INVENTORY.stdout.json"] and offset == 58248, "complete stdout")
    require(status["state"] == "succeeded" and status["exit_code"] == 0, "original terminal")
    require(status["output_complete"] and status["output_durable"] and status["terminal_publication_confirmed"], "terminal durability")
    require(not any(status[x] for x in ["automatic_retry", "cancelled", "timed_out"]), "original job retry")
    require(status["log_bytes"]["stdout"] == {"seen": 58248, "stored": 58248}, "stdout byte accounting")
    require(not any(status["log_truncated"].values()), "log truncation")
    require(start["job"]["id"] == status["job_id"] == "1a1c917a98a-135c4-3d9", "job identity")
    require(start["job"]["idempotency_key"] == host["request_id"] == "mem-next-source-inventory-ed353817-20261111-v1", "request identity")
    require(start["job"]["args"] == ["-c", raw["read_pinned_source_inventory.py"].decode()], "executed script")
    require(start["reused"] is False and host["errors"] == [], "once and clean metadata")
    require(all(host[x] == 0 for x in ["model_calls", "actor_executions", "reference_content_files_opened"]), "metadata-only boundary")
    require(host["status"] == "PINNED_METADATA_VERIFIED_GLOBAL_EXPOSURE_NOT_CERTIFIED", "exposure scope")
    require(host["registry_sha256"] == mem5["registry_sha256"] == pilot["registry_sha256"], "registry")
    require(mem5["catalog"]["sha256"] == host["bindings"]["catalog"]["sha256"], "catalog")
    require(pilot["selected_sources_sha256"] == sha(raw["inputs/cell-causal/selected-sources.json"]), "pilot selection")
    require(pilot["source_exposure_ledger_sha256"] == host["bindings"]["exposure"]["sha256"], "exposure pin")
    categories = {
        "model_training": set(model["training_source_groups"]),
        "tuning": set(selected["groups"]["tuning"]),
        "public_quarantine": set(host["exposure"]["quarantined_source_groups"]),
        "original_working_state": {x["source_group_id"] for x in host["baseline_plan"]["sources"]},
        "mem5_selector": {x["source_group_id"] for x in mem5["episodes"]},
        "mem6_working_state": set(prepare["retention_sources"]),
        "mem6_selector": set(prepare["selector_sources"]),
        "earlier_causal_pilot": set(selected["groups"]["pilot_new"]) | set(selected["groups"]["pilot_retention"]),
    }
    require(categories["model_training"] == set(selected["groups"]["training"]), "training corroboration")
    initial = categories["model_training"] | categories["tuning"] | categories["public_quarantine"]
    require(initial == set(host["baseline_plan"]["excluded_source_groups"]), "initial exclusions")
    require(initial | categories["original_working_state"] == set(mem5["excluded_source_groups"]), "MEM5 inherited exclusions")
    require(categories["original_working_state"] == set(mem5["prior_episode_plans"][0]["source_groups"]), "baseline cross receipt")
    require(mem5["prior_episode_plans"][0]["pin"]["sha256"] == host["bindings"]["baseline_plan"]["sha256"], "baseline bytes")
    require(set(pilot["quarantined_source_groups"]) == categories["public_quarantine"], "quarantine corroboration")
    require(model["actual_weights_sha256"] == mem5["model"]["weights"]["sha256"], "frozen weights")
    require(model["actual_parameters_sha256"] == mem5["model"]["parameters_sha256"], "parameters")
    require(aggregate["pilot_dispatched"] == aggregate["pilot_planned"] == 960, "published aggregate")
    require(categories["mem6_working_state"].isdisjoint(categories["mem6_selector"]), "MEM6 joint overlap")
    mem = set().union(*(v for k, v in categories.items() if k != "earlier_causal_pilot"))
    all_ids = set().union(*categories.values())
    require(len(mem) == 67 and len(all_ids) == 69, "source union")
    catalog = {x["source_group_id"]: x for x in host["catalog"]["groups"]}
    require(len(catalog) == len(host["catalog"]["groups"]) == 178, "unique catalog")
    require(sum(x["case_count"] for x in catalog.values()) == 2199, "catalog cases")
    require(dict(Counter(x["role"] for x in catalog.values())) == {"train": 97, "development": 54, "retention_validation": 27}, "catalog roles")
    for row in host["baseline_plan"]["sources"]:
        require(catalog[row["source_group_id"]]["role"] == row["role"], "baseline role consistency")
    for row in mem5["episodes"]:
        require(catalog[row["source_group_id"]]["role"] == row["split"], "MEM5 role consistency")
    exclusions = parse((root / "EXCLUSIONS.json").read_bytes())
    capacity = parse((root / "CAPACITY.json").read_bytes())
    require(exclusions["categories"] == {k: sorted(v) for k, v in categories.items()}, "published categories")
    require(exclusions["category_counts"] == {k: len(v) for k, v in categories.items()}, "published counts")
    require(exclusions["added_by_earlier_pilot"] == sorted(categories["earlier_causal_pilot"] - mem), "extra pilot")
    groups = exclusions["groups"]
    require(len(groups) == len({r["source_group_id"] for r in groups}) == 69, "published unique groups")
    require({r["source_group_id"] for r in groups} == all_ids, "published union")
    for row in groups:
        sid = row["source_group_id"]
        role = catalog.get(sid, {}).get("role")
        require(row["hard_exclude"] and row["role_in_pinned_released_catalog"] == role, "published source role")
        expected_categories = {k for k, values in categories.items() if sid in values}
        require({r["category"] for r in row["reasons"]} == expected_categories, "per-source categories")
        for reason in row["reasons"]:
            require(reason["evidence"], "missing provenance")
            for evidence in reason["evidence"]:
                name = evidence["path"]
                require(evidence["sha256"] == by_pin[name]["sha256"], "evidence SHA")
                value = pointer(data[name], evidence["field"])
                if evidence["field"] == "/episodes":
                    indices = [i for i, r in enumerate(value) if r["source_group_id"] == sid]
                    require(indices == evidence["matching_row_indices"] and indices, "episode provenance")
                elif evidence["field"] == "/selected_sources_sha256":
                    require(value == sha(raw["inputs/cell-causal/selected-sources.json"]), "pilot receipt pointer")
                elif evidence["field"] == "/pilot_dispatched":
                    require(value == 960, "aggregate pointer")
                else:
                    require(value == sid or isinstance(value, dict) and value.get("source_group_id") == sid, "source pointer")
    allowed = {k: v for k, v in catalog.items() if v["role"] in {"development", "retention_validation"}}
    remaining = {k: v for k, v in allowed.items() if k not in all_ids}
    require(len(allowed) == 81 and len(remaining) == 16, "upper bound")
    role_counts = dict(Counter(v["role"] for v in remaining.values()))
    require(role_counts == {"development": 7, "retention_validation": 9}, "upper-bound roles")
    require(all(v["complete_episode_count_for_existing_released_role"] > 0 for v in remaining.values()), "legacy family completeness")
    published_remaining = {r["source_group_id"]: r for r in capacity["remaining_not_known_excluded"]}
    require(set(published_remaining) == set(remaining), "residual roster")
    for sid, original in remaining.items():
        row = published_remaining[sid]
        require(all(row[k] == v for k, v in original.items()), "residual metadata")
        require(row["current_exposure_status"] == "UNKNOWN" and not row["verified_unseen"] and not row["admitted_to_new_study"], "unknown not promoted")
    require(capacity["capacity"]["verified_unseen_capacity"] is None and not exclusions["global_exposure_complete"], "global scope")
    require(capacity["capacity"]["not_in_known_union_upper_bound"] == 16 and capacity["capacity"]["upper_bound_by_original_role"] == role_counts, "published capacity")
    w = acceptance["prospective_benefit_gate"]
    e = acceptance["real_successor_task_gate"]
    require(w["minimum_source_groups"] == 20 and w["minimum_groups_each_role"] == 4 and w["primary_contrast"] == "bounded_minus_current_only", "W requirements")
    require(e["separate_pre_execution_protocol_required"] and "minimum_source_groups" not in e and "groups_per_role" not in e, "E threshold not invented")
    require(capacity["protocol_scope"]["episodic_E"]["minimum_source_groups"] is None and capacity["protocol_scope"]["episodic_E"]["old_working_state_minima_transferred"] is False, "W/E distinction")
    require(capacity["protocol_scope"]["historic_mem6_retention_allocation"]["groups_per_role"] == {"development": 16, "retention_validation": 4}, "historic allocation")
    require(b'groups_per_role={"development": 16, "retention_validation": 4}' in raw["inputs/launch.py"], "exact launcher allocation")
    archive_result = {"status": "NOT_REQUESTED"}
    if args.mem6_archive:
        archive_result = check_archive(args.mem6_archive, pins, prepare, categories, mem5, model)
    zip_result = {"status": "NOT_REQUESTED"}
    if args.mem5_zip:
        archive_raw = read_checked(args.mem5_zip, pins["external_archives"]["mem5"])
        with zipfile.ZipFile(args.mem5_zip) as z:
            require(z.read("PLAN.json") == raw["inputs/mem5/PLAN.json"], "MEM5 ZIP PLAN")
            require(z.read("REQUEST.json") == raw["inputs/mem5/REQUEST.json"], "MEM5 ZIP REQUEST")
        zip_result = {"status": "PASS", "bytes": len(archive_raw), "sha256": sha(archive_raw), "content_members_read": ["PLAN.json", "REQUEST.json"]}
    result = {
        "schema": "hepta.mem.source-exclusion-offline-audit.v1", "status": "PASS",
        "meaning": "Retained metadata and exact per-group provenance verified; no unseen-source or owner authority certification.",
        "input_files_verified": len(raw), "known_exclusion_count": len(all_ids),
        "not_in_known_union_upper_bound": len(remaining), "upper_bound_by_role": role_counts,
        "verified_unseen_capacity": None, "global_exposure_status": "UNKNOWN",
        "host_job_id": status["job_id"], "host_stdout_sha256": EXPECTED_HOST_SHA,
        "metadata_observed_at_utc": host["observed_at_utc"],
        "outputs": {n: {"bytes": (root / n).stat().st_size, "sha256": sha((root / n).read_bytes())} for n in ["EXCLUSIONS.json", "CAPACITY.json"]},
        "mem6_archive": archive_result, "mem5_zip": zip_result,
        "new_host_jobs": 0, "new_models": 0, "new_actor_episodes": 0,
    }
    if args.output:
        args.output.write_bytes(canonical(result))
    print(canonical(result).decode(), end="")


if __name__ == "__main__":
    main()
