"""Export one already observed v6 group for a local owner engineering test.

This does not train a neural model, collect a new scientific sample, or confer
production authority. Exports are posthoc engineering data, excluded from any
later efficacy assessment. Only standard-library reads touch source evidence.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct


SCHEMA = "hepta.ndu-v6.local-terminal-owner-fixture.v2"
FULL_001_PINS = {
    "status.json": "517ebf31ee23ec897365eb3142580f4f2dd5cf14a62b3dc7de2281b00213fb69",
    "protocol.json": "dc22a1aef41852dfd21c42a4ddebf62897f52165a2ef805b08957fa7e8694c26",
    "summary.json": "6810b5ca546c21bac2df467b2f34c0d6c6496da8e642450379c39ae586de9c3d",
    "rows.jsonl": "6b847965030b71309a278a489244b000b4ada0f31a5ddab7477b8fbeb3b92b31",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utility_q32(value):
    """Round the original JSON binary64 value, exactly as Rust round_ties_even."""
    if type(value) not in (float, int) or not math.isfinite(value) or not -1 <= value <= 1:
        raise ValueError("Invalid bounded binary64 utility")
    return round(float(value) * (1 << 32))


def checked_read(root, relative, expected=None):
    path = root / relative
    if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
        raise ValueError("Evidence path escapes the selected source directory")
    raw = path.read_bytes()
    if expected is not None and sha(raw) != expected:
        raise ValueError(f"Source evidence changed: {relative}")
    return raw


def export_fixture(source, destination, *, fixed_full_001=False, selection=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    # Status is always read before any outcome. The optional original pins
    # reproduce the first fixed real fixture; CI may export its completed smoke.
    expected_pins = FULL_001_PINS if fixed_full_001 else {}
    status = json.loads(checked_read(source, "status.json", expected_pins.get("status.json")))
    if status.get("state") != "completed" or type(status.get("rows")) is not int or status["rows"] < 1:
        raise ValueError("The source experiment is not completed")
    source_bytes = {name: checked_read(source, name, expected_pins.get(name))
                    for name in FULL_001_PINS}
    source_pins = {name: sha(raw) for name, raw in source_bytes.items()}
    protocol = json.loads(source_bytes["protocol.json"])
    summary = json.loads(source_bytes["summary.json"])
    summary_json = canonical(summary)
    if sha(summary_json.encode()) != status["summary_sha256"]:
        raise ValueError("Completed summary identity mismatch")
    protocol_json = canonical(protocol)
    if (summary.get("protocol_sha256") != sha(protocol_json.encode())
            or summary.get("rows") != status["rows"]):
        raise ValueError("Completed protocol/summary/census identity mismatch")
    policies = sorted(protocol["policies"])
    if len(policies) != 7 or len(set(policies)) != 7:
        raise ValueError("Original seven-policy census changed")
    expected_rows = (len(protocol["seeds"]) * len(protocol["trainings"]) * len(protocol["budgets"])
                     * len(policies) * sum(len(cases) for cases in protocol["cases"].values()))
    if expected_rows != status["rows"] or protocol["hard_output_modalities"] != ["text", "image"]:
        raise ValueError("Completed source census or modality contract mismatch")
    # The default group is chosen from protocol metadata, before parsing rows,
    # and does not depend on measured success, utility, or action usage.
    selected_fields = {"seed": protocol["seeds"][0], "training": protocol["trainings"][0],
                       "split": "future", "case_id": protocol["cases"]["future"][0]["case_id"],
                       "budget": protocol["budgets"][0]}
    selected_fields.update(selection or {})
    if set(selected_fields) != {"seed", "training", "split", "case_id", "budget"}:
        raise ValueError("Unknown selection field")
    if (selected_fields["seed"] not in protocol["seeds"]
            or selected_fields["training"] not in protocol["trainings"]
            or selected_fields["budget"] not in protocol["budgets"]
            or selected_fields["split"] not in protocol["cases"]):
        raise ValueError("Selection is outside the frozen protocol")
    case = next((c for c in protocol["cases"][selected_fields["split"]]
                 if c["case_id"] == selected_fields["case_id"]), None)
    if case is None:
        raise ValueError("Selected case is outside the frozen protocol")
    selected = []
    total_rows = 0
    for raw_line in source_bytes["rows.jsonl"].splitlines():
        total_rows += 1
        row = json.loads(raw_line)
        if all(row[key] == value for key, value in selected_fields.items()):
            receipt = row.pop("receipt_sha256")
            payload = canonical(row)
            if sha(payload.encode()) != receipt:
                raise ValueError("Original row receipt mismatch")
            selected.append((row, payload, receipt, sha(raw_line)))
    if total_rows != status["rows"] or sorted(r[0]["policy"] for r in selected) != policies:
        raise ValueError("Selected group is incomplete or duplicated")
    selected.sort(key=lambda item: item[0]["policy"])
    first = selected[0][0]
    common = ["snapshot_sha256", "forecast_sha256", "observer_sha256",
              "reward_observer_sha256", "source_ids", "corruption"]
    if any(row[key] != first[key] for row, *_ in selected for key in common):
        raise ValueError("The fixed-state group mixes model/input/observer identities")
    if case["source_ids"] != first["source_ids"] or case["corruption"] != first["corruption"]:
        raise ValueError("Source membership differs from the frozen protocol")
    state = {**selected_fields, **{key: first[key] for key in common},
             "source_protocol_sha256": sha(canonical(protocol).encode()),
             "noise_seed": selected_fields["seed"] * 10000 + case["index"],
             "state_semantics": "same public observation, frozen model and budget; policies are macro actions"}
    state_json = canonical(state)
    weights = protocol["metric"]["weights"]
    records, extra_pins = [], {}
    for row, payload, receipt, line_digest in selected:
        metrics = row["metrics"]
        joint = sum(float(weights[key]) * float(metrics[key]) for key in weights)
        if abs(joint - metrics["joint_loss"]) > 1e-12 or abs(1 - 2 * joint - metrics["utility"]) > 1e-12:
            raise ValueError("Recorded metric arithmetic changed")
        if not -1 <= metrics["utility"] <= 1:
            raise ValueError("Terminal utility is not bounded")
        output = {}
        for kind in ("text", "image"):
            relative = row["output_paths"][kind]
            raw = checked_read(source, relative, row["output_hashes"][kind])
            extra_pins[relative] = sha(raw)
            output[kind] = raw
        png = output["image"]
        if (png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR"
                or struct.unpack(">II", png[16:24]) != (56, 28) or png[24:26] != b"\x08\x00"):
            raise ValueError("Recorded output does not use the real PNG profile")
        caption = output["text"].decode("utf-8")
        if len(caption) > 4096:
            raise ValueError("Oversized original caption")
        value = utility_q32(metrics["utility"])
        records.append({"policy": row["policy"], "row_payload_json": payload,
                        "row_receipt_sha256": receipt, "source_row_sha256": line_digest,
                        "value_q32": value, "caption": caption, "png": list(png)})
    label = f"seed-{selected_fields['seed']}-{selected_fields['training']}"
    for name in (f"{label}.pt", f"{label}-forecast.pt", "audit-observer.pt"):
        extra_pins[name] = sha(checked_read(source, name))
    for field, name in (("snapshot_file_sha256", f"{label}.pt"),
                        ("forecast_file_sha256", f"{label}-forecast.pt")):
        if any(field in row and row[field] != extra_pins[name] for row, *_ in selected):
            raise ValueError("Recorded model/forecast file identity mismatch")
    if extra_pins["audit-observer.pt"] != first["observer_sha256"]:
        raise ValueError("Observer bytes do not match the original scoring identity")
    source_usage = ("Previously observed full-001 holdout reused only as an engineering fixture; not new scientific data or production certification"
                    if source_pins == FULL_001_PINS else
                    "Previously observed completed-run outputs reused only as a posthoc engineering fixture; not new scientific data or production certification")
    result = {
        "schema": SCHEMA, "scope": "local_research_replay", "authority": "deny_all",
        "source_usage": source_usage,
        "source_root": str(source), "source_commit": protocol["source"]["git_commit"],
        "source_bundle_sha256": protocol["source"]["bundle_sha256"],
        "source_pins": {**source_pins, **extra_pins}, "selection": selected_fields,
        "protocol_json": protocol_json, "summary_json": summary_json,
        "state_json": state_json, "state_sha256": sha(state_json.encode()),
        "objective_sha256": sha(canonical({"metric": protocol["metric"], "requirements": 3}).encode()),
        "metric_sha256": protocol["metric_sha256"], "metric_json": canonical(protocol["metric"]),
        "policy_ids": policies, "selected_propensity_q32": 1 << 32,
        "behavior": "Each execution was forced by the original exhaustive experimental policy schedule; not a randomized 1/7 behavior policy",
        "records": records,
    }
    # Every source file, including model and emitted media, must remain unchanged.
    for name, expected in result["source_pins"].items():
        checked_read(source, name, expected)
    if destination == source or source in destination.parents:
        raise ValueError("The engineering fixture must not be written into old evidence")
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical(result) + "\n").encode()
    if len(raw) > 1024 * 1024:
        raise ValueError("Fixture exceeds the bounded 1 MiB import profile")
    with destination.open("xb") as handle:
        handle.write(raw)
    return {"path": str(destination), "sha256": sha(raw), "rows": len(records),
            "source_files_verified_unchanged": len(result["source_pins"]),
            "scope": result["scope"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--fixed-full-001", action="store_true", help="Require the original full-001 source byte pins")
    args = parser.parse_args()
    print(canonical(export_fixture(args.source, args.destination, fixed_full_001=args.fixed_full_001)))
