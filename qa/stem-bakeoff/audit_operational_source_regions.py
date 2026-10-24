"""TRAIN-only source/pooling contrast diagnostic; no labels, fitting or scores."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

import numpy as np

from long_document_sources import canonical, sha
from operational_region_evidence import load_training_evidence
from operational_source_regions import parse_regions, pool_region


def cosine_distance(left, right):
    left, right = left.astype(np.float64), right.astype(np.float64)
    return float(np.clip(1 - np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)), 0, 2))


def summarize(values):
    return {"count": len(values), "quantiles": {str(q): float(np.quantile(values, q))
            for q in (0, .25, .5, .75, 1)}} if values else {"count": 0, "quantiles": {}}


def audit(dataset, features, prepared, output, *, dataset_sha256, report_sha256, training_repositories):
    started, cpu, root = time.perf_counter_ns(), time.process_time_ns(), Path(output)
    if root.exists():
        raise ValueError("new TRAIN-only audit output required")
    modules = ("audit_operational_source_regions.py", "operational_region_evidence.py",
               "operational_source_regions.py", "long_document_sources.py")
    implementation = {name: sha(Path(__file__).with_name(name).read_bytes()) for name in modules}
    bank = load_training_evidence(dataset, features, prepared, dataset_sha256=dataset_sha256,
        report_sha256=report_sha256, training_repositories=tuple(training_repositories))
    records, rows, unavailable, groups = bank.records(), [], [], defaultdict(list)
    for index, record in enumerate(records):
        text, document = record["text"], record["document"]
        try:
            regions = parse_regions(text)
            pooled, receipts = {}, {}
            for name, spans in regions.fields:
                pooled[name], receipts[name] = pool_region(text, spans, document, bank.chunks(index))
                receipts[name]["fraction_of_input_characters"] = receipts[name]["selected_characters"] / len(text)
                receipts[name]["source_spans_sha256"] = sha(canonical(spans))
            rows.append({"source_id": record["source_id"], "source_version": record["source_version"],
                "parent_source_record_digest": record["source_record_digest"], "family": regions.family,
                "source_utf8_sha256": regions.source_sha256, "source_characters": len(text),
                "pre_execution_input_proof": record["pre_execution_input_proof"], "regions": receipts})
            if regions.family == "regression":
                groups[record["group_id"]].append((record["source_id"], bank.global_features()[index], pooled))
        except ValueError as error:
            unavailable.append({"source_id": record["source_id"], "reason": str(error)})
    pairs = []
    for group, members in sorted(groups.items()):
        if len(members) != 2:
            continue
        a, b = sorted(members, key=lambda member: member[0])
        pairs.append({"group_id": group, "source_ids": [a[0], b[0]],
            "whole_source_cosine_distance": cosine_distance(a[1], b[1]),
            "implementation_pool_cosine_distance": cosine_distance(a[2]["implementation"], b[2]["implementation"]),
            "test_pool_cosine_distance": cosine_distance(a[2]["test"], b[2]["test"])})
    field_summaries = {}
    for family in sorted({row["family"] for row in rows}):
        selected = [row for row in rows if row["family"] == family]
        field_summaries[family] = {"rows": len(selected), "fields": {name: {
            "source_character_fraction": summarize([row["regions"][name]["fraction_of_input_characters"] for row in selected]),
            "selected_windows": summarize([row["regions"][name]["selected_chunks"] for row in selected]),
            "unselected_context_character_fraction_in_windows": summarize([
                row["regions"][name]["unselected_context_characters_in_windows"] /
                row["regions"][name]["selected_window_union_characters"] for row in selected])}
            for name in selected[0]["regions"]}}
    bank.verify_files()
    if {name: sha(Path(__file__).with_name(name).read_bytes()) for name in modules} != implementation:
        raise ValueError("audit implementation changed")
    result = {"schema": "hepta.train-only-source-region-audit.v1", "training_repositories": list(training_repositories),
        "parent_feature_identity": bank.parent_identity, "parent_report_sha256": report_sha256,
        "dataset_sha256": dataset_sha256, "source_code_sha256": implementation, "input_pins": dict(bank.file_pins),
        "selected_train_rows": len(records), "available_rows": len(rows), "unavailable_rows": unavailable,
        "field_summaries": field_summaries, "regression_pair_count": len(pairs),
        "paired_cosine_distances": {key: summarize([pair[key] for pair in pairs]) for key in
            ("whole_source_cosine_distance", "implementation_pool_cosine_distance", "test_pool_cosine_distance")},
        "pairs": pairs, "rows": rows, "encoder_forward_calls": 0, "gradient_updates": 0,
        "label_fields_read_for_analysis": False, "model_or_holdout_prediction_files_opened": False,
        "nontraining_statistics_computed": False, "quality_qualified": False,
        "container_scope": "Complete input containers checked; only allowlisted TRAIN source rows analyzed",
        "interpretation": "Cosine separation and source mass are descriptive. Larger local pair distance does not prove better execution prediction or identify encoder capacity as the bottleneck. Reused windows retain boundary context; this is not the prospective clean-field condition.",
        "cost": {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "scope": "inclusive container capture, source replay, selected TRAIN analysis and final pin checks; excludes imports/output serialization"},
        "retained_numeric_bytes": len(bank._globals) + sum(len(value) for value in bank._chunks),
        "captured_container_bytes": bank.container_bytes}
    root.parent.mkdir(parents=True, exist_ok=True)
    with root.open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "prepared", "output", "dataset-sha256", "report-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--training-repositories", nargs="+", required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("selected_train_rows", "available_rows", "field_summaries",
        "regression_pair_count", "paired_cosine_distances", "cost")}))
