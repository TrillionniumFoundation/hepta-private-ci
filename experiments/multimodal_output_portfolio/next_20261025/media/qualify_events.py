"""Develop event observation on old qualifications, then confirm on new speakers."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...closure_20261025.media.sources import save_json, sha
from .audio_sources import load_audio, rank
from .event_observer import EventWaveAudit, RECIPE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--phase", choices=("development", "qualification"), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    allocation = json.loads(args.allocation.read_text())
    if args.phase == "development":
        original = allocation["roles"]["qualification"]
        rows = [row for digit in range(10)
                for row in sorted((r for r in original if r["label"] == digit), key=lambda r: rank(r["path"]))[:6]]
    else:
        rows = allocation["recordings"]
        if allocation["frozen_event_observer_sha256"] != sha(Path(__file__).with_name("event_observer.py")):
            raise ValueError("Event observer recipe changed after source freeze")
        if len(rows) != 300 or allocation["overlap_with_old_qualification_speakers"] != 0:
            raise ValueError("New qualification must remain speaker independent")
    config = {"schema": "hepta.next.event-observer-qualification.v1", "phase": args.phase,
              "source_allocation_sha256": sha(args.allocation), "rows": len(rows),
              "recipe": RECIPE, "primary_digit_accuracy_min": .85,
              "source_sha256": {str(p.resolve()): sha(p) for p in
                                (Path(__file__), Path(__file__).with_name("event_observer.py"))},
              "confirmation_opened": False}
    save_json(args.output / "registration.json", config)
    sounds = load_audio(args.sources, rows)
    audit = EventWaveAudit(args.assets, args.output / "observed-events")
    save_json(args.output / "observers.json", audit.receipt)
    outcomes = []
    for index, (signal, source) in enumerate(zip(sounds, rows)):
        pcm = (signal.numpy() * 32767).round().astype("<i2").tobytes()
        observed = audit.observe_event(pcm, carrier=False)
        row = {"source": source, "observed_without_target": observed,
               "expected_after_observation": source["label"],
               "correct": {name: predicted == source["label"] for name, predicted in observed["predictions"].items()}}
        outcomes.append(row)
        save_json(args.output / f"row-{index:03d}.json", row)
        if len(outcomes) % 25 == 0:
            print(json.dumps({"phase": args.phase, "recordings": len(outcomes)}), flush=True)
    accuracy = {name: sum(row["correct"][name] for row in outcomes) / len(outcomes) for name in audit.models}
    save_json(args.output / "summary.json", {"status": "completed", "phase": args.phase,
              "accuracy": accuracy, "source_recordings": len(outcomes),
              "source_speakers": len({row["speaker"] for row in rows}),
              "primary_eligible": accuracy["small.en"] >= .85,
              "secondary_eligible": accuracy["base.en"] >= .85,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "confirmation_opened": False,
              "statistical_unit": "Speech Commands speaker; recordings within one speaker are dependent"})


if __name__ == "__main__":
    main()
