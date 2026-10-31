"""Once-only qualification of the development-selected event ASR on new speakers."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...closure_20261025.media.sources import save_json, sha
from .audio_sources import load_audio
from .selected_event import SelectedEventWaveAudit, PRIMARY, SECONDARY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "selection", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    allocation = json.loads(args.allocation.read_text())
    selection = json.loads(args.selection.read_text())
    if selection["new_qualification_allocation_sha256"] != sha(args.allocation):
        raise ValueError("New qualification source allocation changed")
    for path, expected in selection["frozen_candidate_sha256"].items():
        if sha(path) != expected:
            raise ValueError("Selected candidate bytes changed")
    rows = allocation["recordings"]
    if len(rows) != 300 or allocation["overlap_with_old_qualification_speakers"] != 0:
        raise ValueError("Require all three hundred previously unused qualification recordings")
    save_json(args.output / "registration.json", {"schema": "hepta.next.selected-event-qualification.v2",
              "selection_sha256": sha(args.selection), "source_allocation_sha256": sha(args.allocation),
              "primary": PRIMARY, "secondary": SECONDARY, "primary_accuracy_min": .85,
              "started_unix_ns": time.time_ns(), "new_confirmation_opened": False,
              "after_outcomes": "Do not change observer, transform, parser, selection or threshold using these qualification results"})
    sounds = load_audio(args.sources, rows)
    audit = SelectedEventWaveAudit(args.assets, args.output / "observed-events")
    save_json(args.output / "observers.json", audit.receipt)
    outcomes = []
    for index, (signal, source) in enumerate(zip(sounds, rows)):
        observed = audit.observe_event((signal.numpy() * 32767).round().astype("<i2").tobytes(), carrier=False)
        row = {"source": source, "observed_without_target": observed, "expected_after_observation": source["label"],
               "correct": {name: prediction == source["label"] for name, prediction in observed["predictions"].items()}}
        outcomes.append(row)
        save_json(args.output / f"row-{index:03d}.json", row)
        if len(outcomes) % 25 == 0:
            print(json.dumps({"new_qualification_recordings": len(outcomes)}), flush=True)
    accuracy = {name: sum(row["correct"][name] for row in outcomes) / len(outcomes) for name in audit.models}
    if any(sha(path) != expected for path, expected in selection["frozen_candidate_sha256"].items()):
        raise ValueError("Selected candidate changed during qualification")
    save_json(args.output / "summary.json", {"status": "completed", "phase": "independent_qualification",
              "accuracy": accuracy, "primary": PRIMARY, "secondary": SECONDARY,
              "source_recordings": len(outcomes), "source_speakers": len({row["speaker"] for row in rows}),
              "primary_eligible": accuracy[PRIMARY] >= .85, "secondary_eligible": accuracy[SECONDARY] >= .85,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "new_confirmation_opened": False, "source_role_independent_from_selected_development": True,
              "statistical_unit": "Speaker, not individual recording; .85 is a point gate, not a confidence lower bound"})


if __name__ == "__main__":
    main()
