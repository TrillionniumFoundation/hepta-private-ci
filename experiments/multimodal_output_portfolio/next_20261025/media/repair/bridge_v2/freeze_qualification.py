# Early public semantic commitment; all previous candidate source remains unchanged.
"""Freeze both repaired ingress and the V3.1 observer before the fresh cohort."""

import argparse
import json
from pathlib import Path
import time

from .....closure_20261025.media.sources import save_json, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "old-development", "model", "sources", "allocation", "selection", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never replace a prospective qualification freeze")
    development = json.loads(args.development.read_text())
    old_development = json.loads(args.old_development.read_text())
    if (development.get("version") != "repair-v2" or development.get("phase") != "development"
            or not development.get("all_media_sample_gates_pass")
            or old_development.get("conditional_head_census", {}).get("audio_accuracy", 0) < .8
            or old_development.get("conditional_head_census", {}).get("video_accuracy", 0) < .9):
        raise ValueError("Actual old-development repairs must pass all original sample gates before new qualification")
    registration = args.development.parent / "registration.json"
    pins = dict(json.loads(registration.read_text())["frozen_candidate_sha256"])
    if pins.get(str(args.model.resolve())) != sha(args.model):
        raise ValueError("Actual classifier differs from the executed development model")
    observer = json.loads(args.selection.read_text())
    if any(path in pins and pins[path] != expected for path, expected in observer["frozen_candidate_sha256"].items()):
        raise ValueError("Development and observer freezes disagree on a shared dependency")
    pins.update(observer["frozen_candidate_sha256"])
    allocation = json.loads(args.allocation.read_text())
    if (sha(args.allocation) != observer["new_qualification_allocation_sha256"]
            or len(allocation["recordings"]) != 300 or len(allocation["speakers"]) != 147):
        raise ValueError("Require the same still-unscored prospective V3 cohort")
    for name in ("base.en", "small.en"):
        manifest = args.assets / ("whisper-" + name) / "manifest.json"
        if pins.get(str(manifest.resolve())) != sha(manifest):
            raise ValueError("Actual ASR asset root differs from selected identity")
        for item in json.loads(manifest.read_text())["sources"]:
            asset = manifest.parent / item["path"]
            if pins.get(str(asset.resolve())) != sha(asset):
                raise ValueError("Actual ASR asset differs from selected identity")
    for path in (args.development, registration, args.old_development,
                 args.old_development.parent / "registration.json", args.selection,
                 args.allocation, args.model.parent / "summary.json", args.model.parent / "registration.json"):
        pins[str(path.resolve())] = sha(path)
    for row in allocation["recordings"]:
        path = args.sources / row["path"]
        if sha(path) != row["sha256"]:
            raise ValueError("Registered new source recording bytes differ")
        pins[str(path.resolve())] = row["sha256"]
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError("Frozen qualification dependency changed")
    save_json(args.output, {"schema": "hepta.next.media-repair-qualification-protocol.v1",
              "registered_unix_ns": time.time_ns(), "frozen_candidate_sha256": pins,
              "source_allocation_sha256": sha(args.allocation), "observer_selection_sha256": sha(args.selection),
              "classifier_checkpoint_sha256": sha(args.model), "sources": 300, "speakers": 147,
              "fixed_gates": {"ASR_ensemble_accuracy": .85, "audio_ingress_accuracy": .85},
              "model_selection_used_only_old300_and_old12": True, "new_source_scores_opened": False,
              "before_reading_new_scores": "All model and parser/ensemble choices are now fixed",
              "after_outcomes": "Retain all rows; no head, observer, cohort, parser, threshold, or ensemble changes using these results"})
    print(json.dumps({"protocol_sha256": sha(args.output), "pins": len(pins)}))


if __name__ == "__main__":
    main()
