"""Independent action-covariance, packet, and delivered-control checks."""

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile

import numpy as np

from .. import learners, task
from ..round2 import evaluation as old_evaluation
from ..transport import ArtifactTransport
from . import event_codec as codec
from .event_study import _new_control


def dense_scores(v, horizon, q, noise_scale, multiplier):
    """Dense conditioning reference, independently assembled sensor covariance."""
    r, s = noise_scale * task.REPAIR_VARIANCE, noise_scale * task.OBSERVATION_VARIANCE
    target = v + horizon * q
    repair = target - v * v / (v + r) + task.REPAIR_COST * multiplier
    result = {"stop": target, "repair": repair}
    if horizon == 2.0:
        p = v + q
        covariance = np.array([[p + s, p], [p, p + r]])
        cross = np.full(2, p)
        wait = target - p * p / (p + s)
        wait_repair = target - cross @ np.linalg.solve(covariance, cross) + task.REPAIR_COST * multiplier
        result["wait"] = task.WAIT_COST * multiplier + min(wait, wait_repair)
    return result


def run(output=None):
    checks = 0
    failures = []

    def check(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def rejects(function, message):
        try:
            function()
        except (ValueError, TypeError, OverflowError):
            check(True, message)
        else:
            check(False, message)

    rng = np.random.default_rng(2026102803)
    max_covariance_error = 0.0
    certified_cells = 0
    for i in range(600):
        v = math.exp(rng.uniform(-5, 2))
        q, scale, multiplier = math.exp(rng.uniform(-4, 0)), math.exp(rng.uniform(-2, 1)), math.exp(rng.uniform(-2, 2))
        horizon = (1.0, 2.0)[i % 2]
        a, b = codec.scores_for_variance(v, horizon, q, scale, multiplier), dense_scores(v, horizon, q, scale, multiplier)
        gap = max(abs(a[k] - b[k]) for k in a)
        max_covariance_error = max(max_covariance_error, gap)
        check(gap < 2e-13, f"dense conditional covariance mismatch {i}")
        encoder = codec.Encoder(codec.Config(8, i % 8, 24))
        encoder.send(float(rng.normal()), v, 0.0, "observed")
        model = {"planning_q": q, "planning_noise_scale": scale}
        certificate = codec.decision_certificate(encoder.decoder, model, horizon, multiplier)
        low, high = certificate["variance_interval"]
        check(low <= v <= high, f"variance cell misses encoded driver {i}")
        if certificate["certified"]:
            certified_cells += 1
            for point in np.linspace(low, high, 33):
                ref = dense_scores(float(point), horizon, q, scale, multiplier)
                check(min(ref, key=ref.get) == certificate["selected"], f"false certified action {i}")
    packet_count = 0
    for mode in ("error_feedback", "direct_quantization", "increment_only"):
        config = codec.Config(9, 2, 24, True, mode)
        encoder, independent = codec.Encoder(config), codec.Decoder(config)
        for i in range(256):
            mean, variance = float(rng.normal()), math.exp(rng.uniform(-5, 3))
            bits = (2, 8, 4, 20)[i % 4]
            observed = encoder.send(mean, variance, i / 7, "missing" if i % 7 == 0 else "observed")
            independent.apply(json.loads(json.dumps(observed)))
            packet_count += 1
            packet = observed
            if bits > config.initial_logvar_bits:
                packet = encoder.send(mean, variance, i / 7, "refinement", bits)
                independent.apply(json.loads(json.dumps(packet)))
                packet_count += 1
            check(independent.snapshot() == encoder.decoder.snapshot(), f"independent decoder mismatch {mode}:{i}")
            restored = codec.Decoder.restore(independent.snapshot())
            check(restored.snapshot() == independent.snapshot(), f"checkpoint round trip {mode}:{i}")
            if mode != "increment_only":
                expected = [math.floor(math.ldexp(mean, 9) + .5),
                            math.floor(math.ldexp(math.log(variance), bits) + .5)]
                check(independent.levels == expected, f"absolute-lattice reference {mode}:{i}")
                check(independent.variance_interval()[0] <= variance <= independent.variance_interval()[1],
                      f"variable-precision cell containment {mode}:{i}")
        duplicate = deepcopy(packet)
        rejects(lambda: independent.apply(duplicate), "duplicate packet accepted")
        regressed = {**packet, "sequence": independent.sequence + 1, "time": 0.0}
        rejects(lambda: independent.apply(regressed), "regressed time accepted")
        corrupt = {**packet, "sequence": independent.sequence + 1, "counts": [True, 0]}
        rejects(lambda: independent.apply(corrupt), "Boolean count accepted")
        corrupt = {**packet, "sequence": independent.sequence + 1, "bits": [9, 25]}
        rejects(lambda: independent.apply(corrupt), "out-of-domain precision accepted")
        corrupt = {**packet, "sequence": independent.sequence + 1, "kind": "refinement",
                   "time": independent.time + 1, "bits": [9, 22], "counts": [0, 0]}
        rejects(lambda: independent.apply(corrupt), "refinement advanced physical time")
        corrupt = {**packet, "sequence": independent.sequence + 1, "kind": "refinement",
                   "bits": [9, 2], "counts": [0, 0]}
        rejects(lambda: independent.apply(corrupt), "refinement lowered precision")
        corrupt = {**packet, "sequence": independent.sequence + 1, "kind": "observed",
                   "bits": [9, 2], "counts": [2**49, 0]}
        rejects(lambda: independent.apply(corrupt), "count overflow accepted")
        initial = codec.Decoder(config)
        corrupt = {**packet, "sequence": 1, "kind": "refinement", "bits": [9, 4], "counts": [0, 0]}
        rejects(lambda: initial.apply(corrupt), "refinement accepted without existing state")

    data = task.build_dataset(31000607, 32, "development")
    driver = {"kind": "filter", "parameters": [.12, .18, 1.], "planning_q": .18, "planning_noise_scale": 1.}
    model = {**driver, "kind": codec.KIND, "event_config": asdict(codec.Config(8, 2))}
    direct = {**model, "event_config": {**model["event_config"], "mode": "direct_quantization"}}
    residual_off = {**model, "event_config": {**model["event_config"], "mode": "increment_only"}}
    public = task.history(data)
    poisoned = {k: np.array(v, copy=True) for k, v in public.items()}
    for field in ("obs", "obs_var"):
        poisoned[field][~poisoned["mask"]] = np.nan
    check(all(np.array_equal(a, b) for a, b in zip(codec.predict(model, public), codec.predict(model, poisoned))),
          "missing payload changed a forecast")
    held = codec.Session(model)
    held.sync(task.subset(public, 0))
    rewrite = task.subset(public, 0)
    rewrite["obs"] = rewrite["obs"].copy()
    rewrite["obs"][0, -3] += 2.0
    rejects(lambda: held.sync(rewrite), "acquired history rewrite accepted")
    for horizon in (-1.0, .75, float("nan"), float("inf")):
        rejects(lambda: held.forecast(horizon), "invalid horizon accepted")
    invalid_driver = {**model, "planning_q": .2}
    rejects(lambda: codec.Session(invalid_driver), "inconsistent driver/planning parameters accepted")
    rejects(lambda: codec.scores_for_variance(float("nan"), 2.0, .18, 1., 1.), "nonfinite variance accepted")
    rejects(lambda: held.encoder.send(2.0**50, 1., held.timestamp, "observed"), "mean overflow accepted")
    rejects(lambda: held.encoder.send(0., math.exp(610), held.timestamp, "observed"), "log variance overflow accepted")
    rejects(lambda: held.encoder.send(held.current_target[0], held.current_target[1] * 2,
                                     held.timestamp, "refinement", 24), "refinement changed continuous target")
    rejects(lambda: codec.scores_for_variance(1e308, 2.0, 1e308, 1., 1.), "planning overflow accepted")
    with tempfile.TemporaryDirectory(prefix="hepta-r3-events-validation-") as temporary:
        transport = ArtifactTransport(Path(temporary) / "transport", "development_validation")
        control = _new_control({"adaptive": model, "direct": direct, "no_residual": residual_off}, data, transport)
        baseline = old_evaluation.evaluate_control({"analytic": driver}, data, include_fixed_policies=False)
        indexed = {(r["arm"], r["case"]): r for r in control["rows"]}
        baseline = {r["case"]: r for r in baseline["rows"]}
        certificates = 0
        for identity in data["ids"]:
            a, b = indexed[("adaptive", str(identity))], indexed[("direct", str(identity))]
            check(a["actions"] == b["actions"] and a["delivered_prediction"] == b["delivered_prediction"],
                  f"matched direct control mismatch {identity}")
            check(a["actions"] == baseline[str(identity)]["actions"], f"certified action differs from continuous {identity}")
            check(a["paid_cost"] == baseline[str(identity)]["paid_cost"], f"certified paid costs differ {identity}")
            check(a["final_readback_ns"] < a["score_started_ns"], f"score clock precedes final readback {identity}")
            restored = codec.Decoder(codec.Config(**model["event_config"]))
            file_path = transport.root / a["packet_transport"]["path"]
            packets = [json.loads(line) for line in file_path.read_text().splitlines()]
            check(packets == a["event_packets"], f"packet physical readback missing {identity}")
            for packet in packets:
                restored.apply(packet)
            check(restored.snapshot() == a["event_accounting"]["decoder"], f"stored packet replay differs {identity}")
            for stage in a["stages"]:
                check(stage["event_certificate"]["certified"], f"uncertified adaptive choice {identity}")
                certificates += 1
        mutated = {**data, "future": data["future"] + 17.0}
        repeated = _new_control({"adaptive": model}, mutated)
        for row in repeated["rows"]:
            original = indexed[("adaptive", row["case"])]
            check(row["actions"] == original["actions"] and row["delivered_prediction"] == original["delivered_prediction"],
                  "private target entered action or delivery")
            check(row["utility"] != original["utility"], "post-delivery score did not consume changed target")
        physical_files = sum(1 for p in transport.root.rglob("*") if p.is_file())
    result = {"schema": "hepta.decision-event.validation.v1", "passed": not failures,
              "checks": checks, "failures": failures, "random_covariance_cases": 600,
              "max_dense_covariance_score_error": max_covariance_error,
              "certified_cells_sampled_at_33_points": certified_cells,
              "variable_precision_packet_transitions": packet_count,
              "development_trajectories": 32, "physically_delivered_control_episodes": 96,
              "physical_files_written_read_and_deleted": physical_files,
              "control_decision_certificates": certificates,
              "confirmation_generated": False,
              "reference_scope": "dense Gaussian conditioning and independent integer replay; finite validation is not a universal FP64 proof"}
    if output is not None:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if failures:
        raise AssertionError(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output), sort_keys=True))
