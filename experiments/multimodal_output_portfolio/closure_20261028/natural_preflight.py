"""Census the completed natural studies without changing their frozen records."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def annotations(root, kind):
    path = root / f"{kind}_localisation_train_annotations.zip"
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read(archive.namelist()[0]))


def census(root):
    official = {}
    for kind in ("action", "sound"):
        data = annotations(root / "natural_assets", kind)
        counts = Counter(segment["label_id"] for row in data.values()
                         for segment in row[f"{kind}_localisation"])
        source_counts = Counter(label for row in data.values()
                                for label in {x["label_id"] for x in row[f"{kind}_localisation"]})
        labels = {x["label_id"]: x["label"] for row in data.values()
                  for x in row[f"{kind}_localisation"]}
        official[kind] = {"videos": len(data), "segments": sum(counts.values()),
                          "classes": len(counts), "label_segment_counts": dict(counts),
                          "label_source_counts": dict(source_counts), "labels": labels,
                          "annotation_archive_sha256": sha(root / "natural_assets" /
                              f"{kind}_localisation_train_annotations.zip")}
    old = {}
    used = set()
    for name in ("natural_assets", "natural_expanded_assets"):
        meta = json.loads((root / name / "EVENTS.json").read_text())
        training = [x for x in meta["events"] if x["split"] == "train"]
        splits = {}
        for split in sorted({x["split"] for x in meta["events"]}):
            rows = [x for x in meta["events"] if x["split"] == split]
            entry = {"events": len(rows), "sources": len({x["source_id"] for x in rows})}
            for kind in ("action", "sound"):
                field = kind + "_id"
                counts = Counter(x[field] for x in rows)
                seen = {x[field] for x in training}
                source_ids = {x["source_id"] for x in rows}
                covered = sum(sum(x[field] in seen for x in rows if x["source_id"] == source) /
                              sum(x["source_id"] == source for x in rows)
                              for source in source_ids) / len(source_ids)
                majority = Counter(x[field] for x in training).most_common(1)[0][0]
                majority_acc = sum(x[field] == majority for x in rows) / len(rows)
                entry[kind] = {"classes": len(counts), "label_event_counts": dict(counts),
                               "out_of_training_ontology_event_fraction":
                               sum(x[field] not in seen for x in rows) / len(rows),
                               "source_uniform_seen_ontology_upper_bound": covered,
                               "training_majority_class": majority,
                               "training_majority_event_accuracy": majority_acc}
            splits[split] = entry
            used.update(x["source_id"] for x in rows)
        old[name] = {"metadata_sha256": sha(root / name / "EVENTS.json"), "splits": splits}
    return {
        "schema": "hepta.closure.natural-preflight.v1", "official_train": official,
        "completed_studies": old, "consumed_original_video_ids": sorted(used),
        "consumed_source_count": len(used), "new_qualification_calls": 0,
        "diagnosis": [
            "The completed observer used 13 handcrafted features, with only 8 action inputs and 6 sound inputs including an intercept.",
            "The completed target was four 32x32 video frames lasting 0.5 seconds, limiting fine-grained action observability.",
            "Only 32 original training videos and 102 events supported the old 23-class action and 8-class sound observers.",
            "All original calibration/qualification allocations remain consumed and cannot serve as fresh confirmation.",
            "Old training excluded draw-call timing and duplicated shared-forward CPU across replicates; the new executor must meter complete episodes once.",
        ],
        "source_selection_constraint": "No class removal or source selection based on observer/generator outcomes; freeze new protocol and source roles before new calibration or qualification metrics.",
        "official_sources": [
            "https://github.com/google-deepmind/perception_test",
            "https://docs.pytorch.org/vision/main/models/generated/torchvision.models.video.s3d.html",
            "https://github.com/qiuqiangkong/audioset_tagging_cnn",
            "https://github.com/HumamAlwassel/TSP",
        ],
        "resource_options": {
            "tsp_r2plus1d34_weights_bytes": 509101103,
            "tsp_full_train_feature_archive_documented_mb": 81.7,
            "tsp_status": "Storage-heavy candidate; exact official feature-extractor identity is required before scoring generated media.",
            "s3d_weights_documented_mb": 32.0,
            "chosen_initial_observer_route": "Official S3D pretrained temporal features plus PANN compact audio features; train-only classifier with source-held-out development, then freeze and independent calibration.",
            "sustained_new_storage_budget_bytes": 650000000,
        },
        "scientific_limits": [
            "Passing file/cost/gradient checks does not imply passing semantic or quality gates.",
            "No model score is available yet for the new observer, and no positive outcome is promised.",
            "Video-source separation does not establish participant independence.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = census(args.prior_root)
    result["audit_source_sha256"] = sha(__file__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"consumed_source_count": result["consumed_source_count"],
                      "official_action_classes": result["official_train"]["action"]["classes"],
                      "official_sound_classes": result["official_train"]["sound"]["classes"]}))
