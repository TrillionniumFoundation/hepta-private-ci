#!/usr/bin/env python3
"""Read existing V4 cost receipts; no experiment, model, array or label loading.

Writes JSON to stdout only. Redirect it outside every sealed evidence directory.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

SOURCE = "fa2a8f928dc41f8f3c48ea9bd0d45adf1e27ee09"
RUN_SEAL = "a7dfa11a64deef982d0ebdc36dc746b2b3e31c3a0b7def28920d4ab070177346"
PROTOCOL = "fe0057c499c1a77ca7f5781a05425d83d59693b4250fb1560cab978afb4cd5b2"
PROTOCOL_SEMANTIC = "8c4dbc77dc6b495173f7ea85f004360d18fe74fc4cb886f18fce9fc5ceecdaf7"
SOURCE_HASHES = {
    "cell_field_closure_run.py": "e6101d6f4cbe7c122bfa29a9584a248667199baaaf06c811313670ff81fd8cb3",
    "cell_field_closure_control.py": "f941a43b563f118442336673a7d972c291a790770fef4748dfbf5af90daf8813",
    "cell_field_closure_features.py": "d475395320abdbdf7a61f3ca5c9d0ced8ab4d18563f915b8a568748d4cdb89c2",
    "cell_field_control.py": "b91260462b26492e29d17da4daaa7f16be429e3b6f33e4af587bf0471e15780b",
    "shared_feature_extract.py": "7338e9eb36f8909828b528ff926e9d3412ffa1c653d141dcea39af3cb2b0fa73",
    "real_encoder.py": "c0255c26dd9c73cfb737f6acec48f8ae1fdd07a7e7477e98691603e724fba2af"
}
BUNDLE = "c462a550e18baa63ba230c9dd6c076d676b5fcc0f281589c023b82251b0aa579"
ARMS = ("loss2", "history2", "history4", "moment4", "full")
INPUTS = []


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), "not an original regular file: " + path.name)
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            result.update(chunk)
    return result.hexdigest()


def read(path, label, expected=None, byte_limit=8_388_608):
    require(path.is_file() and not path.is_symlink(), "missing original receipt: " + label)
    require(path.stat().st_size <= byte_limit, "oversized receipt: " + label)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    require(expected is None or sha == expected, "original receipt SHA differs: " + label)
    value = json.loads(raw)
    INPUTS.append({"path": label, "sha256": sha, "bytes": len(raw)})
    return value


def integer(value, label):
    require(type(value) is int and value >= 0, "invalid nonnegative integer: " + label)
    return value


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid finite nonnegative number: " + label)
    return value


def stats(values, unit):
    require(bool(values), "empty cost group")
    return {"count": len(values), "unit": unit, "sum": sum(values),
            "mean": statistics.mean(values), "median": statistics.median(values),
            "minimum": min(values), "maximum": max(values)}


def timed(rows):
    return {key: stats([integer(row[key], key) for row in rows], "ns")
            for key in ("wall_ns", "cpu_ns")}


def feature_receipt(row, label):
    require(row["schema"] == "hepta.shared-event-feature-forward.v1", "feature receipt schema")
    require(row["authority"] == "DENY_ALL" and row["mode"] == "SHADOW_ONLY", "feature authority")
    require(row["candidate"] == "granite97m" and row["device"] == "cpu", "feature owner")
    result = {"label": label}
    for key in ("model_forward_calls", "model_forward_calls_total", "batch_size", "token_count", "retained_tensor_bytes"):
        result[key] = integer(row[key], key)
    for key in ("forward_ms", "encode_ms"):
        result[key] = number(row[key], key)
    require(result["model_forward_calls"] == 1, "receipt does not record exactly one forward")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    seal = read(args.run / "run-seal.json", "run/run-seal.json", RUN_SEAL)
    require(seal["schema"] == "hepta.cell-closure-seal.v4", "run seal schema")
    inventory = seal["files"]

    def sealed(relative):
        require(relative in inventory, "receipt absent from original run seal: " + relative)
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "invalid relative path")
        value = read(args.run / relative, "run/" + relative, inventory[relative]["sha256"])
        require(INPUTS[-1]["bytes"] == inventory[relative]["bytes"], "sealed file length differs")
        return value

    plan = sealed("protocol.json")
    inputs = sealed("inputs.json")
    source_freeze = sealed("source-freeze.json")
    runs = sealed("runs.json")
    # run/protocol.json was canonicalized by the original writer. The raw
    # committed protocol SHA belongs to source-freeze, not that rewritten file.
    require(source_freeze["protocol_sha256"] == PROTOCOL, "registered protocol differs")
    semantic = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    require(semantic == PROTOCOL_SEMANTIC, "executed protocol semantics differ")
    require(all(source_freeze["files"][name] == sha for name, sha in SOURCE_HASHES.items()),
            "cost instrumentation source differs from executed commit")
    require(source_freeze["git_commit"] == runs["source_commit"] == SOURCE, "source commit differs")
    require(runs["schema"] == "hepta.cell-closure-run.v4" and runs["authority"] == "DENY_ALL"
            and runs["production_authority"] is False and runs["final_labels_opened"] is False,
            "run schema/authority/final-access state differs")
    anchors, records = runs["anchors"], runs["records"]
    require(len(anchors) == 18 and len(records) == runs["registered"] == runs["completed"] == 306, "registered census differs")
    identities = [row["id"] for row in anchors]
    require(len(set(identities)) == 18, "duplicate anchor")
    require({(row["seed"], row["head"], row["anchor_offset"]) for row in anchors}
            == {(seed, head, offset) for seed in (7, 17, 29) for head in ("linear", "gated") for offset in (0, 8, 16)}, "anchor grid differs")
    require(all(row["status"] == "completed" for row in records), "uncompleted branch")
    require(Counter((row["anchor"], row["action"]) for row in records)
            == Counter((identity, action) for identity in identities for action in range(17)), "branch census differs")
    maps, references = [], []
    for anchor in anchors:
        identity = anchor["id"]
        require(identity == f"seed{anchor['seed']}-{anchor['head']}-step{anchor['anchor_offset']}", "anchor path identity differs")
        forecast = sealed(identity + "/forecast.json")
        require(set(forecast["arms"]) == set(ARMS) and forecast["selected"] == anchor["selected"], "forecast arm/selection binding differs")
        references.append({"anchor": identity, "head": anchor["head"], "parameter_count": anchor["parameter_count"],
                           "wall_ns": integer(anchor["reference_wall_ns"], "reference_wall_ns")})
        for arm in ARMS:
            meta = forecast["arms"][arm]["metadata"]
            require(meta["arm"] == arm and meta["full_state_calibration_required"] is True, "map owner metadata differs")
            row = {"anchor": identity, "head": anchor["head"], "arm": arm}
            for key in ("wall_ns", "cpu_ns", "map_bytes", "projected_dimension", "retained_output_scalars",
                        "retained_action_scalars_upper_bound", "common_full_state_dimension"):
                row[key] = integer(meta[key], key)
            history = meta["history_audit"]
            require(len(history) == (8 if arm in ("history2", "history4") else 0), "history audit census differs")
            row["history_audit_rows"] = len(history)
            maps.append(row)
    per_arm = []
    for arm in ARMS:
        chosen = [row for row in maps if row["arm"] == arm]
        per_head = []
        for head in ("linear", "gated"):
            rows = [row for row in chosen if row["head"] == head]
            dimensions = {key: sorted({row[key] for row in rows}) for key in
                          ("map_bytes", "projected_dimension", "retained_output_scalars",
                           "retained_action_scalars_upper_bound", "common_full_state_dimension")}
            per_head.append({"head": head, "anchors": len(rows), **timed(rows), **dimensions,
                             "retained_state_scalars_upper_bounds": sorted({row["retained_output_scalars"] + row["retained_action_scalars_upper_bound"] for row in rows})})
        per_arm.append({"arm": arm, "anchors": len(chosen), **timed(chosen),
                        "map_array_nbytes_sum": sum(row["map_bytes"] for row in chosen), "by_head": per_head})
    feature = read(args.features / "report.json", "features/report.json", inputs["new_feature_report_sha256"])
    require(feature["schema"] == "hepta.cell-closure-features.v4" and feature["authority"] == "DENY_ALL"
            and feature["production_authority"] is False and feature["encoder_updates"] == 0, "feature authority/schema")
    require(feature["plan"]["protocol_sha256"] == PROTOCOL and feature["plan"]["labels_enter_encoder"] is False
            and feature["shape"] == [96, 384] and feature["dtype"] == "float32", "feature shape/protocol")
    require(feature["feature_sha256"] == inputs["new_feature_sha256"], "feature tensor binding")
    require(feature["encoder_identity"]["checkpoint_revision"] == plan["encoder_revision"], "encoder revision")
    bridge = feature["bridge"]
    bridge_file = read(args.features / "bridge.json", "features/bridge.json")
    require(bridge_file == bridge, "standalone bridge receipt differs from sealed feature report")
    error = number(bridge["maximum_absolute_feature_difference"], "bridge error")
    require(bridge["passed"] is True and error <= plan["encoder_bridge"]["maximum_absolute_feature_difference"]
            and len(bridge["source_indices"]) == len(bridge["source_ids"]) == 8, "bridge gate differs")
    bridge_receipt = feature_receipt(bridge["receipt"], "bridge")
    require(bridge_receipt["batch_size"] == 8, "bridge batch differs")
    new_receipts = [feature_receipt(row, "new-source-batch-" + str(index)) for index, row in enumerate(feature["receipts"])]
    require(len(new_receipts) == 6 and all(row["batch_size"] == 16 for row in new_receipts), "new source batch census differs")
    receipts = [bridge_receipt, *new_receipts]
    require([row["model_forward_calls_total"] for row in receipts] == list(range(1, 8)), "forward counter differs")
    require(feature["encoding"]["forward_calls"] == sum(row["model_forward_calls"] for row in receipts) == 7
            and feature["encoding"]["encoded_tokens"] == sum(row["token_count"] for row in receipts)
            and feature["encoding"]["includes_old_training_source_bridge"] is True, "encoding aggregate differs")
    require(len(feature["token_lengths"]) == 96
            and feature["truncated_inputs"] == sum(n > plan["encoder_max_tokens"] for n in feature["token_lengths"]), "token-length census differs")
    accounting = feature["encoder_load"]["model"]
    require(accounting["trainable_parameter_count"] == 0, "encoder is not frozen")
    run_wall = integer(runs["wall_ns"], "run wall")
    run_cpu = integer(runs["cpu_ns"], "run CPU")
    reference_wall = sum(row["wall_ns"] for row in references)
    map_wall, map_cpu = (sum(row[key] for row in maps) for key in ("wall_ns", "cpu_ns"))
    branch_wall, branch_cpu = (sum(row[key] for row in records) for key in ("wall_ns", "cpu_ns"))
    require(reference_wall + map_wall + branch_wall <= run_wall and map_cpu + branch_cpu <= run_cpu,
            "subphase costs exceed containing run interval")
    groups = {}
    for path, row in inventory.items():
        category = ("reference_npz" if path.endswith("/reference.npz") else
                    "forecast_npz" if path.endswith("-forecast.npz") else
                    "forecast_json" if path.endswith("/forecast.json") else
                    "action_npz" if "/action-" in path and path.endswith(".npz") else
                    "action_receipts_json" if "/action-" in path and path.endswith("-receipts.json") else "other_run_files")
        group = groups.setdefault(category, {"files": 0, "bytes": 0})
        group["files"] += 1
        group["bytes"] += integer(row["bytes"], "sealed artifact size")
    bundle = {"root_reported_expected_sha256": BUNDLE, "root_reported_expected_bytes": 13_267_684, "verified_by_this_helper": False}
    if args.bundle:
        require(args.bundle.stat().st_size == 13_267_684 and digest(args.bundle) == BUNDLE, "raw bundle pin differs")
        bundle["verified_by_this_helper"] = True
    output = {
        "schema": "hepta.cell-closure-cost-aggregation.v4", "authority": "DENY_ALL", "production_authority": False,
        "source_commit": SOURCE, "run_seal_sha256": RUN_SEAL, "collector_sha256": digest(Path(__file__)),
        "executed_protocol_sha256": PROTOCOL, "executed_protocol_semantic_sha256": PROTOCOL_SEMANTIC,
        "collector_revision": 2, "prior_failed_collector_preserved": True,
        "raw_bundle": bundle, "input_files": INPUTS, "input_file_count": len(INPUTS),
        "frozen_source_hashes": {name: source_freeze["files"][name] for name in
                                ("cell_field_closure_run.py", "cell_field_closure_control.py", "cell_field_closure_features.py", "cell_field_control.py", "shared_feature_extract.py", "real_encoder.py")},
        "census": {"anchors": 18, "map_builds": len(maps), "branch_records": 306, "branch_optimizer_steps": 2448,
                   "bridge_sources": 8, "new_sources": 96, "feature_forward_calls": 7},
        "reference": {"charged_once_per_anchor": True, "wall_ns": stats([row["wall_ns"] for row in references], "ns"),
                      "cpu_ns": None, "cpu_scope": "not instrumented by original build_reference; never imputed", "per_anchor": references},
        "maps": {"all_builds": timed(maps), "per_arm": per_arm,
                 "array_nbytes_scope": "logical NumPy map elements, not peak RSS or compressed artifact bytes",
                 "includes_shared_reference": False},
        "branches": {"count": 306, **timed(records), "per_head": [
            {"head": head, **timed([row for row in records if row["anchor"] in {a["id"] for a in anchors if a["head"] == head}])}
            for head in ("linear", "gated")]},
        "run_interval": {"wall_ns": run_wall, "cpu_ns": run_cpu,
                         "wall_ns_other_unallocated": run_wall - reference_wall - map_wall - branch_wall,
                         "cpu_ns_reference_plus_other_unallocated": run_cpu - map_cpu - branch_cpu,
                         "scope": "original inner run interval; nested within wrapper run stage, do not add again"},
        "features": {"shape": feature["shape"], "dtype": feature["dtype"], "encoder_updates": 0,
                     "encoder_load": feature["encoder_load"], "encoding": feature["encoding"],
                     "peak_rss_bytes": integer(feature["peak_rss_bytes"], "feature RSS"),
                     "peak_rss_scope": "original feature process RUSAGE_SELF high-water mark",
                     "bridge": {"passed": True, "sources": 8, "maximum_absolute_feature_difference": error,
                                "maximum_allowed_difference": plan["encoder_bridge"]["maximum_absolute_feature_difference"], "receipt": bridge_receipt},
                     "new_source_receipts": new_receipts, "token_lengths": stats(feature["token_lengths"], "tokens_before_truncation"),
                     "truncated_inputs": feature["truncated_inputs"], "maximum_tokens": plan["encoder_max_tokens"],
                     "new_source_token_count": sum(row["token_count"] for row in new_receipts),
                     "all_forward_ms_sum": sum(row["forward_ms"] for row in receipts),
                     "all_encode_ms_sum": sum(row["encode_ms"] for row in receipts),
                     "timing_scope": "forward is nested within receipt encode; receipts nested within encoding; no bridge CPU separately recorded"},
        "sealed_run_artifact_inventory": {"file_count": len(inventory), "bytes": sum(row["bytes"] for row in inventory.values()),
                                          "by_category": groups, "scope": "original run-seal inventory; only listed input files rehashed by helper; excludes run-seal itself and data/features/evaluation directories"},
        "no_new_training_model_or_raw_label_access": True,
    }
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
