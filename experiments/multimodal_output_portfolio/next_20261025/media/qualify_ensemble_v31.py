# Identity-binding amendment before first V3 qualification; algorithm and sources unchanged.
"""One prospective V3 ensemble qualification on previously untouched speakers."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...closure_20261025.media.sources import save_json, sha
from .audio_sources import load_audio
from .ensemble_event import EnsembleEventWaveAudit, PRIMARY, SECONDARIES, RULE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "selection", "assets", "development", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    allocation = json.loads(args.allocation.read_text())
    selection = json.loads(args.selection.read_text())
    development = json.loads(args.development.read_text())
    if (development.get("phase") != "development"
            or development.get("conditional_head_census", {}).get("audio_accuracy", 0) < .8
            or development.get("conditional_head_census", {}).get("video_accuracy", 0) < .9):
        raise ValueError("Do not spend new qualification sources on a failing actual head candidate")
    if selection["new_qualification_allocation_sha256"] != sha(args.allocation):
        raise ValueError("New ensemble source allocation changed")
    for path, expected in selection["frozen_candidate_sha256"].items():
        if sha(path) != expected:
            raise ValueError("Frozen ensemble candidate bytes changed")
    for name in SECONDARIES:
        manifest = args.assets / ("whisper-" + name) / "manifest.json"
        if selection["frozen_candidate_sha256"].get(str(manifest.resolve())) != sha(manifest):
            raise ValueError("Actual ASR manifest path or bytes differ from prospective selection")
        for item in json.loads(manifest.read_text())["sources"]:
            asset = manifest.parent / item["path"]
            actual_sha256 = sha(asset)
            if (actual_sha256 != item["sha256"]
                    or selection["frozen_candidate_sha256"].get(str(asset.resolve())) != actual_sha256):
                raise ValueError("Actual ASR asset path or bytes differ from prospective selection")
    development_registration = json.loads((args.development.parent / "registration.json").read_text())
    for path, expected in selection["development_model_sha256"].items():
        if development_registration["frozen_candidate_sha256"].get(path) != expected:
            raise ValueError("Actual generated development outputs came from a different model")
    rows = allocation["recordings"]
    if (allocation.get("official_split") != "test" or len(rows) != 300
            or allocation["overlap_with_excluded_speakers"] != 0
            or allocation["reserved_media_joint_speakers_excluded"] != 56
            or set(allocation["excluded_speakers"]) & {row["speaker"] for row in rows}):
        raise ValueError("Require exactly three hundred unused, nonreserved official test recordings")
    save_json(args.output / "registration.json", {"schema": "hepta.next.ensemble-event-qualification.v3",
              "selection_sha256": sha(args.selection), "source_allocation_sha256": sha(args.allocation),
              "selection_path": str(args.selection.resolve()), "actual_asr_asset_paths_bound_before_source_load": True,
              "primary": PRIMARY, "secondary_observers": SECONDARIES, "ensemble_rule": RULE,
              "primary_accuracy_min": .85, "development_path": str(args.development.resolve()),
              "development_sha256": sha(args.development), "started_unix_ns": time.time_ns(),
              "new_media_confirmation_opened": False,
              "after_outcomes": "No observer, transform, parser, ensemble, threshold or cohort changes"})
    sounds = load_audio(args.sources, rows)
    audit = EnsembleEventWaveAudit(args.assets, args.output / "observed-events")
    save_json(args.output / "observers.json", audit.receipt)
    outcomes = []
    for index, (signal, source) in enumerate(zip(sounds, rows)):
        observed = audit.observe_event((signal.numpy() * 32767).round().astype("<i2").tobytes(), carrier=False)
        row = {"source": source, "observed_without_target": observed, "expected_after_observation": source["label"],
               "correct": {name: prediction == source["label"] for name, prediction in observed["predictions"].items()}}
        outcomes.append(row)
        save_json(args.output / f"row-{index:03d}.json", row)
        if len(outcomes) % 25 == 0:
            print(json.dumps({"v3_new_qualification_recordings": len(outcomes)}), flush=True)
    accuracy = {name: sum(row["correct"][name] for row in outcomes) / len(outcomes)
                for name in (*SECONDARIES, PRIMARY)}
    if any(sha(path) != expected for path, expected in selection["frozen_candidate_sha256"].items()):
        raise ValueError("Frozen ensemble candidate changed during qualification")
    save_json(args.output / "summary.json", {"status": "completed", "phase": "independent_qualification",
              "version": "v3", "accuracy": accuracy, "primary": PRIMARY, "secondary_observers": SECONDARIES,
              "source_recordings": len(outcomes), "source_speakers": len({row["speaker"] for row in rows}),
              "primary_eligible": accuracy[PRIMARY] >= .85, "primary_gate_min": .85,
              "secondary_eligible": {name: accuracy[name] >= .85 for name in SECONDARIES},
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "new_media_confirmation_opened": False,
              "v2_qualification_failed_and_retained": True,
              "source_role_independent_from_all_observer_development": True,
              "statistical_unit": "Speaker; .85 is the unchanged point gate, not a confidence lower bound"})


if __name__ == "__main__":
    main()
