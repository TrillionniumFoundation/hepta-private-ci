"""Training-only annotation ambiguity audit; never changes sources or the gate."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .data_sources import digest, load_annotations, save


def audit(root, output):
    source = json.loads((root / "SOURCE_PROTOCOL.json").read_text())
    annotations = {kind: load_annotations(root, "train", kind)[0] for kind in ("action", "sound")}
    roles = {}
    for role in ("generator_train", "observer_train"):
        selected = [row for row in source["selected"] if row["role"] == role]
        records = []
        for row in selected:
            events = row["events"][:row["retained_event_count"]]
            for event in events:
                begin, end = event["target_start_seconds"], event["target_end_seconds"]
                item = {"source_id": row["source_id"], "window_start_seconds": begin,
                        "weight": 1/(len(selected)*len(events))}
                for kind in ("action", "sound"):
                    visible = annotations[kind][row["source_id"]][kind + "_localisation"]
                    overlapping = {entry["label_id"] for entry in visible
                        if min(end, entry["timestamps"][1]/1e6)-max(begin, entry["timestamps"][0]/1e6) >= .15-1e-9}
                    interval = event[kind + "_interval_seconds"]
                    overlap = max(0., min(end, interval[1])-max(begin, interval[0]))
                    item[kind] = {"selected_label": event[kind + "_id"], "all_overlapping_labels": sorted(overlapping),
                                  "selected_label_duration_seconds": overlap,
                                  "fraction_of_selected_annotation_inside_target": overlap/(interval[1]-interval[0])}
                    if event[kind + "_id"] not in overlapping:
                        raise ValueError("A frozen training target does not contain its selected label")
                records.append(item)
        report = {"sources": len(selected), "retained_events": len(records), "annotations_unchanged": True}
        for kind in ("action", "sound"):
            report[kind] = {"classes_present": len({row[kind]["selected_label"] for row in records}),
                "published_class_count": len(source["ontology"][kind]),
                "overlapping_class_count_histogram": dict(Counter(len(row[kind]["all_overlapping_labels"]) for row in records)),
                "source_uniform_fraction_with_other_labels_in_same_target": sum(row["weight"] for row in records if len(row[kind]["all_overlapping_labels"])>1),
                "source_uniform_selected_label_duration_seconds": sum(row["weight"]*row[kind]["selected_label_duration_seconds"] for row in records),
                "source_uniform_selected_annotation_fraction_in_target": sum(row["weight"]*row[kind]["fraction_of_selected_annotation_inside_target"] for row in records)}
        report["records"] = records
        roles[role] = report
    result = {"schema": "hepta.closure.training-window-ambiguity-audit.v1",
        "source_protocol_sha256": source["protocol_sha256"], "implementation_sha256": digest(Path(__file__).read_bytes()),
        "input_annotation_sha256": {kind: source["annotation_archives"]["train_" + kind]["sha256"] for kind in annotations},
        "only_training_annotations_read": True, "heldout_predictions_or_pixels_read": False,
        "source_or_event_filtering": False, "adequacy_threshold_changed": False,
        "interpretation": "Multiple overlapping annotated labels make a single selected-label classification target ambiguous; this descriptive training diagnostic does not excuse or change the frozen60percent empirical gate.",
        "roles": roles}
    save(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.assets, args.output)
    print(json.dumps({role: {key: value for key, value in report.items() if key != "records"}
                      for role, report in result["roles"].items()}))
