"""Bind unchanged pre-observation features to subsequently observed labels.

Only label/outcome metadata may change. Original feature receipts and tensors
remain immutable; this is a zero-Encoder alias with explicit parent references.
"""

import argparse
import copy
import json
from pathlib import Path
import time

from long_document_sources import canonical, sha
from operational_feature_availability import capture_feature_bundle
from operational_field_plan import source_hashes, write_json
from operational_region_evidence import capture, verify_pins


def bind_labels(inputs, dataset, features, output, *, expected_report_sha256, dataset_sha256):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = Path(output)
    if root.exists():
        raise ValueError("new labelled-feature binding directory required")
    before, parent, _, _, availability, raw, pins = capture_feature_bundle(features, inputs, expected_report_sha256)
    alias_source_sha256 = sha(capture(Path(__file__), pins))
    labelled_raw = capture(dataset, pins, 64 * 1024**2)
    after = json.loads(labelled_raw)
    if (sha(labelled_raw) != dataset_sha256 or before.get("all_labels_unobserved") is not True
            or after.get("input_dataset_sha256") != parent["plan"]["dataset_sha256"]
            or after.get("all_proposed_actions_retained") is not True
            or after.get("post_outcome_candidate_selection") is not False
            or before.get("selected_tasks") != after.get("selected_tasks")
            or len(before["rows"]) != len(after["rows"])):
        raise ValueError("pinned prospective label attachment with every original row required")
    for old, new in zip(before["rows"], after["rows"], strict=True):
        if (type(old.get("labels")) is not dict or type(new.get("labels")) is not dict
                or not old["labels"] or old["labels"].keys() != new["labels"].keys()
                or any(value is not None for value in old["labels"].values())
                or any(value is not None and (type(value) is not int or value not in (0, 1)) for value in new["labels"].values())
                or {k: v for k, v in old.items() if k != "labels"} !=
                   {k: v for k, v in new.items() if k not in ("labels", "outcome_provenance")}):
            raise ValueError("labels/outcome metadata are the only permitted row changes")
    implementation = source_hashes()
    if implementation != parent["plan"]["source_code_sha256"]:
        raise ValueError("feature implementation changed before label attachment")
    pins.update({str(Path(__file__).with_name(name)): value for name, value in implementation.items()})
    root.mkdir(parents=True)
    for name in ("features.npz", "feature-availability.json", "source-bindings.json"):
        with (root / name).open("xb") as stream:
            stream.write(raw[name])
    plan = copy.deepcopy(parent["plan"])
    plan["dataset_sha256"] = dataset_sha256
    binding = {"schema": "hepta.operational-label-feature-binding.v1", "parent_report_sha256": expected_report_sha256,
        "parent_manifest_sha256": sha(raw["manifest.json"]), "parent_dataset_sha256": parent["plan"]["dataset_sha256"],
        "labelled_dataset_sha256": dataset_sha256, "feature_identity": parent["feature_identity"],
        "permitted_row_changes": ["labels", "outcome_provenance"], "source_rows_checked": len(before["rows"]),
        "all_source_versions_text_spans_order_identical": True, "numeric_payloads_byte_identical": True,
        "feature_availability_unchanged": True, "source_code_sha256": alias_source_sha256,
        "parent_path": str(Path(features).resolve()), "encoder_forward_calls": 0, "gradient_updates": 0}
    plan["label_attachment"] = binding
    write_json(root / "plan.json", plan)
    write_json(root / "label-binding.json", binding)
    verify_pins(pins)
    report = {key: parent[key] for key in ("feature_identity", "feature_shape", "feature_tensor_sha256",
        "feature_archive_sha256", "feature_archive_bytes", "retained_global_bytes", "source_record_digests",
        "source_bindings_sha256", "feature_availability_sha256", "available_feature_rows", "unavailable_feature_rows")}
    report.update({"plan": plan, "condition": parent["condition"], "label_binding": binding,
        "parent_report_sha256": expected_report_sha256, "historical_parent_encoder_forward_calls": parent["encoder_forward_calls"],
        "parent_work_is_charged_separately": True, "encoder_forward_calls": 0, "encoder_instances": 0,
        "gradient_updates": 0, "quality_qualified": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "cost": {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "scope": "inclusive parent verification, exact source comparison, byte-identical payload copy and final input pins; excludes report/manifest self-writes"}})
    write_json(root / "report.json", report)
    write_json(root / "manifest.json", {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
                                       for p in sorted(root.iterdir())})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "dataset", "features", "output", "expected-report-sha256", "dataset-sha256"):
        parser.add_argument("--" + name, required=True)
    result = bind_labels(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("feature_identity", "feature_shape", "encoder_forward_calls")}))
