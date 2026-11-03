"""Targeted pathwise adapter checks against the frozen v0 event engine."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np

from rrsnn_experiments.runtime.event_runtime import Neuron, InputEvent, simulate
from .exact_rollout import ExactIndependentRollout

OUT = Path(__file__).resolve().parent / "results"


def execute_continuation(engine, continuation):
    events = []
    for row in continuation:
        events.extend(engine.advance_to(row["time"]))
        if "parameters" in row:
            events.extend(engine.observe(**row["parameters"]))
    return [asdict(event) for event in events]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    findings = []
    for seed in (101, 211, 307, 401, 503):
        spec = Neuron(drift=1.1, sigma=.65, threshold=.8, reset=0, refractory=.13)
        inputs = [InputEvent(.4, 0, drift=-.2), InputEvent(.8, 0, drift=1.6, kick=.2),
                  InputEvent(1.25, 0, threshold=.65), InputEvent(1.6, 0, kick=.15)]
        original = simulate([spec], 2.0, inputs, seed=seed, record_trace=True)
        adapter = ExactIndependentRollout([0.0], drift=1.1, sigma=.65, threshold=.8,
                                         reset=0, refractory=.13, seed=seed)
        emitted = []
        for event in inputs:
            emitted.extend(adapter.advance_to(event.time))
            params = {name: getattr(event, name) for name in ("drift", "sigma", "threshold", "kick")
                      if getattr(event, name) is not None}
            emitted.extend(adapter.observe(**params))
        emitted.extend(adapter.advance_to(2.0))
        times_a = np.array([event.time for event in emitted])
        times_b = np.array([event["time"] for event in original["spikes"]])
        assert np.array_equal(times_a, times_b)
        assert np.array_equal(adapter.evidence, original["final_values"])
        assert np.array_equal(adapter.refractory_until, original["refractory_until"])
        findings.append({"name": "pathwise_frozen_v0", "seed": seed,
                         "spikes": len(emitted), "times": times_a.tolist(),
                         "identical_times_and_final_state": True})
    # No elapsed time is invented for an observation. A lower threshold is an
    # instantaneous event, and a subsequent refractory kick must be discarded.
    engine = ExactIndependentRollout([.7], drift=.0, sigma=.0, threshold=1., refractory=.2)
    assert engine.advance_to(0) == [] and engine.time == 0 and engine.count[0] == 0
    immediate = engine.observe(threshold=.6)
    assert len(immediate) == 1 and immediate[0].time == 0
    assert engine.observe(kick=100.) == [] and engine.evidence[0] == 0
    engine.observe(drift=2.)
    engine.advance_to(.3)
    assert abs(engine.evidence[0]-.2) < 1e-12
    findings.append({"name": "initial_observation_and_refractory", "passed": True})

    # Two components, stochastic spikes, checkpoint during active/refractory
    # evolution, and coefficient changes after the split for the Rust bridge.
    engine = ExactIndependentRollout([.15, -.1], drift=[1.2, .65], sigma=[.55, .4],
        threshold=[.8, .9], reset=[0, .05], refractory=[.17, .12], seed=83011)
    initial = engine.checkpoint()
    first = execute_continuation(engine, [
        {"time": .35, "parameters": {"drift": [1.45, .8], "kick": [.1, -.05]}},
        {"time": .8, "parameters": {"threshold": [.7, .85]}},
        {"time": 1.0},
    ])
    checkpoint = engine.checkpoint()
    continuation = [
        {"time": 1.2, "parameters": {"drift": [.35, 1.5], "kick": [0, .25]}},
        {"time": 1.6, "parameters": {"threshold": [.75, .7]}},
        {"time": 2.2},
    ]
    later = execute_continuation(engine, continuation)
    final = engine.checkpoint()
    restored = ExactIndependentRollout.from_checkpoint(json.loads(json.dumps(checkpoint)))
    restored_events = execute_continuation(restored, continuation)
    assert later == restored_events and restored.checkpoint() == final
    fixture = {"schema": "rrsnn.exact-rollout-replay-fixture.v1",
        "semantics": "Independent Brownian components; old controls advance then observed updates; no resource ledger in this fixture.",
        "initial": initial, "events_before_split": first,
        "checkpoint_at_split": checkpoint, "continuation": continuation,
        "expected_continuation_events": later, "expected_final": final,
        "numpy_version": np.__version__}
    fixture_path = OUT/"exact_replay_fixture.json"
    fixture_path.write_text(json.dumps(fixture, indent=2, allow_nan=False)+"\n")
    findings.append({"name": "json_checkpoint_resume", "passed": True,
                     "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
                     "continuation_spikes": len(later)})
    report = {"schema": "rrsnn.exact-adapter-audit.v1", "checks": findings,
              "v0_source_sha256": hashlib.sha256((Path(__file__).resolve().parents[2]/
                "rrsnn_experiments/runtime/event_runtime.py").read_bytes()).hexdigest()
              if (Path(__file__).resolve().parents[2]/"rrsnn_experiments/runtime/event_runtime.py").exists() else None,
              "limits": ["Independent components between externally supplied control changes.",
                         "No continuous within-block recurrent coupling implemented here.",
                         "Replay equality depends on retaining the NumPy generator implementation and full bit-generator state."]}
    (OUT/"exact_adapter_validation.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"checks": len(findings), "passed": True, "fixture": str(fixture_path)}))


if __name__ == "__main__":
    main()
