"""Real owned subprocess scheduling probe; recognition evidence is unavailable."""

import argparse
import json
from pathlib import Path
import sys

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, CorrectnessValue, Modality, StopEvaluation,
)
from .execution import RealClock, run_episode
from .planning import Plan, Read, ServiceEstimate, Wait
from .service import SubprocessService


class FixtureHead:
    def evaluate(self, content):
        p = 0.5 if content.audio is None else 0.7
        return StopEvaluation((p, 1 - p), CorrectnessValue(p, "fixture-head"))


class FixtureForecast:
    kind = BackendKind.DIRECT_HISTORY
    reader_id = "fixture-forecast"

    def evaluate(self, content, state, plan):
        return CorrectnessValue(0.7, "fixture-head")


class FixtureServiceModel:
    def estimate(self, content, plan, now, deadline):
        return ServiceEstimate(1.0, 0.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("probe evidence must not overwrite an earlier run")
    results = []
    cases = (
        ("fixture-normal", 4.0, (Plan((Wait(0.02), Read(Modality.VIDEO, 1), Read(Modality.AUDIO, 2))),)),
        ("fixture-late", 0.2, ()),
    )
    for object_id, deadline, fixed in cases:
        clock = RealClock()
        result = run_episode(
            object_id, CacheBudget(4096), FixtureHead(), FixtureForecast(), FixtureServiceModel(),
            SubprocessService(object_id), lambda data: (sys.stdout.buffer.write(data), sys.stdout.buffer.flush()),
            clock=clock, deadline=deadline, horizon=3, fixed_plans=fixed)
        print(json.dumps({"kind": "episode_output", "episode_id": object_id,
                          "source_monotonic_ns": result["source_monotonic_ns"],
                          "output_flush_monotonic_ns": result["output_flush_monotonic_ns"]}), flush=True)
        results.append(result)
    checks = {
        "normal_three_charged_reads": results[0]["requested_observations"] == 3,
        "normal_three_acceptances": len(results[0]["source_window_updates"]) == 3,
        "wait_preserves_content": all(e["before"] == e["after"] for e in results[0]["events"] if e["kind"] == "wait"),
        "late_first_audio_still_charged": results[1]["requested_observations"] == 1,
        "late_output_excludes_feature": results[1]["output"]["accepted_event_ids"] == (),
        "drain_follows_output": results[1]["post_drain_elapsed_seconds"] > results[1]["output_elapsed_seconds"],
        "late_bytes_do_not_mutate_output": results[1]["late_drains"][0]["status"] == "discarded_after_output_attempt",
    }
    report = {"schema": "hcsn-v8-real-scheduler-probe.v1", "scientific_confirmation": False,
              "recognition_quality_measured": False, "checks": checks, "episodes": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
