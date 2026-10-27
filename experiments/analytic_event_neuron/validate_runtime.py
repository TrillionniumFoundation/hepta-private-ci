"""Executable integration audit of recurrent owners and original native ports."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np

from .analytic import event_probs
from .native_adapter import Native
from .runtime import (EventRuntime, Q24, counter_uniform, digest, pulse_features,
                      pulse_initial_state, pulse_transition, quantize_probabilities)


def validate(output, native_binary, native_receipt):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition, **detail):
        if not condition:
            raise AssertionError(name)
        checks.append({"name": name, "passed": True, **detail})
    def rejects(name, callback):
        try:
            callback()
        except (ValueError, RuntimeError) as error:
            checks.append({"name": name, "passed": True, "rejection": str(error)})
        else:
            raise AssertionError(name + " unexpectedly accepted")
    config = {"model_digest": digest("frozen-model"), "dataset_digest": digest("validation-only"),
              "subject_id": "validation.subject", "generation": 1, "seed": 47,
              "lower": -0.5, "upper": 0.5}
    means = np.linspace(-1.2, 1.2, 12).tolist()
    def request(owner, index, **extra):
        return owner.step(f"tick.{index}", index, float(index), means[index-1], 0.36,
                          digest(["observation", index]), **extra)
    with tempfile.TemporaryDirectory(prefix="aen-runtime-audit-") as temporary:
        directory = Path(temporary)
        uninterrupted = EventRuntime(directory / "uninterrupted", config)
        expected = [request(uninterrupted, i) for i in range(1, 13)]
        actual = []
        for i in range(1, 13):
            owner = EventRuntime(directory / "restart", config)
            if i == 4:
                rejects("lost acknowledgement after durable commit", lambda: request(owner, i, fail_after_commit=True))
                owner = EventRuntime(directory / "restart", config)
            actual.append(request(owner, i))
        semantic = lambda row: {k: v for k, v in row.items() if k != "compute_ns_before_commit"}
        check("restart and lost-ack replay preserve exact semantic receipts",
              [semantic(r) for r in expected] == [semantic(r) for r in actual], ticks=12)
        before = owner.path.read_bytes()
        check("historical duplicate is idempotent", request(owner, 3) == actual[2] and owner.path.read_bytes() == before)
        rejects("changed payload under duplicate tick ID", lambda: owner.step("tick.3", 3, 3., 9., .36, digest(["observation", 3])))
        rejects("clock regression", lambda: owner.step("clock", 13, 11.9, 0., .36, digest("clock")))
        rejects("sequence gap", lambda: owner.step("gap", 14, 14., 0., .36, digest("gap")))
        rejects("stale expected checkpoint", lambda: owner.step("cas", 13, 13., 0., .36, digest("cas"), expected_checkpoint=actual[10]["checkpoint_after"]))
        rejects("missing observation is not neutral evidence", lambda: owner.step("missing", 13, 13., 0., .36, digest("missing"), observation_kind="missing"))
        check("rejected transitions leave checkpoint unchanged", owner.path.read_bytes() == before)
        for key, value in [("seed", 48), ("subject_id", "another.subject"), ("generation", 2),
                           ("model_digest", digest("other-model")), ("dataset_digest", digest("other-dataset")),
                           ("reset_enabled", False)]:
            rejects("checkpoint identity mismatch: " + key,
                    lambda key=key, value=value: EventRuntime(directory / "restart", {**config, key: value}).snapshot())
        corrupt = json.loads(before)
        corrupt["state"]["potential"] += 0.01
        owner.path.write_text(json.dumps(corrupt))
        rejects("checkpoint byte corruption", owner.snapshot)
        owner.path.write_bytes(before)
        # A valid stale file alone cannot prove the acknowledged latest state;
        # the independently held caller anchor makes that rollback detectable.
        rollback = EventRuntime(directory / "rollback", config)
        request(rollback, 1)
        old = rollback.path.read_bytes()
        latest = request(rollback, 2)
        rollback.path.write_bytes(old)
        rejects("valid rollback rejected by caller-held anchor", lambda: rollback.step(
            "after.rollback", 2, 2., 0., .36, digest("rollback"), expected_checkpoint=latest["checkpoint_after"]))
        capacity = EventRuntime(directory / "capacity", {**config, "maximum_ticks": 2})
        request(capacity, 1); request(capacity, 2)
        rejects("bounded owner capacity", lambda: request(capacity, 3))
        shutil.copy2(owner.path, output / "python_checkpoint.json")

        timed = EventRuntime(directory / "physical-time", config)
        simultaneous = timed.step("t0", 1, 0., .1, .25, digest("observed.at.t0"))
        future = timed.step("future", 2, 0., .3, .5, digest("same-time.repair"), target_timestamp=2.)
        missing = timed.step("predict-only", 3, 1., .4, .75, digest("missing.measurement.propagated"),
                             target_timestamp=2., observation_kind="prediction_only")
        check("posterior and future target times are explicit in pulse receipts",
              simultaneous["target_timestamp"] == simultaneous["timestamp"] == 0.
              and future["timestamp"] == 0. and future["target_timestamp"] == 2.
              and future["request_digest"] != simultaneous["request_digest"]
              and np.array_equal(future["probabilities"], event_probs(.3, .5, -.5, .5)))
        check("prediction-only missing tick uses its propagated conditional law",
              missing["observation_kind"] == "prediction_only"
              and np.array_equal(missing["probabilities"], event_probs(.4, .75, -.5, .5))
              and missing["probabilities"][1] != 1.)
        rejects("target before conditioning time rejected", lambda: timed.step(
            "bad.target", 4, 1., .4, .75, digest("bad.target"), target_timestamp=.5))
        rejects("changed target time under duplicate ID rejected", lambda: timed.step(
            "future", 2, 0., .3, .5, digest("same-time.repair"), target_timestamp=3.))

        state = pulse_initial_state(); emissions = []
        for _ in range(5):
            state, result = pulse_transition(state, [0., 0., 1.], 0.5, refractory_ticks=2)
            emissions.append(result["emitted_pulse"])
        check("reset and refractory have explicit recurrence", emissions == [0, 1, 0, 0, 1] and state["potential"] == 0.)
        sample = pulse_initial_state(); no_reset = pulse_initial_state(); mean = pulse_initial_state()
        for tick in range(1, 21):
            p = [0.1, 0.2, 0.7]; u = counter_uniform(19, "mechanism", tick)
            sample, _ = pulse_transition(sample, p, u)
            no_reset, _ = pulse_transition(no_reset, p, u, reset_enabled=False)
            mean, event = pulse_transition(mean, p, u, mode="mean_drive")
        check("reset and mean-drive ablations change recurrent features",
              not np.array_equal(pulse_features(sample), pulse_features(no_reset))
              and not np.array_equal(pulse_features(sample), pulse_features(mean))
              and event["sampled_event"] is None)
        for field, value in [("potential", float("nan")), ("eligibility", float("inf")),
                             ("steps", -1), ("age", 1), ("last_output", 2), ("refractory", -1)]:
            rejects("invalid pure state: " + field,
                    lambda field=field, value=value: pulse_transition({**pulse_initial_state(), field: value}, [0., 1., 0.], .5))
        stream = [counter_uniform(19, "order", i) for i in range(1, 101)]
        check("counter RNG independent of iteration order", stream == list(reversed([counter_uniform(19, "order", i) for i in range(100, 0, -1)])))
        state = pulse_initial_state()
        for tick in range(1, 4097):
            state, _ = pulse_transition(state, [0.2, 0.5, 0.3], counter_uniform(19, "long-pure", tick))
        check("4096-step pure recurrence remains finite", np.isfinite(pulse_features(state)).all(),
              scope="numerical recurrence; not a multi-day retention qualification")
        probability_grid = np.random.default_rng(131).dirichlet([0.2, 0.5, 0.7], 2000)
        errors = [float(np.max(np.abs(p - np.asarray(quantize_probabilities(p)) / Q24))) for p in probability_grid]
        check("Q24 conserves probability mass independently of calibration",
              all(sum(quantize_probabilities(p)) == Q24 for p in probability_grid) and max(errors) <= 1/Q24,
              maximum_error=max(errors), cases=len(errors))

        with Native(native_binary, native_receipt) as native:
            observations = [.1, -.2, .35, .31]; times = [0., .4, .9, .9]
            mask = [True, False, True, True]; obs_var = [.64, .64, .64, .04]
            history = native.sparse_features(observations, times, mask, case="prefix", obs_var=obs_var)
            prefix = native.sparse_features(observations[:3], times[:3], mask[:3], case="prefix", obs_var=obs_var[:3])
            check("native prefix is append-stable including checkpoint identity",
                  [r["checkpoint_after"] for r in prefix["ticks"]] == [r["checkpoint_after"] for r in history["ticks"][:3]])
            masked = native.sparse_features([.1, 7., .35, .31], times, mask, case="prefix", obs_var=obs_var)
            check("missing payload cannot masquerade as measured evidence", history["features"] == masked["features"])
            neutral = native.sparse_features([.1, 0., .35, .31], times, [True]*4, case="prefix", obs_var=obs_var)
            check("missing and measured zero retain distinct drive masks",
                  history["ticks"][1]["drive_q24"] != neutral["ticks"][1]["drive_q24"])
            check("public reliability reaches the original kernel", history["ticks"][-1]["drive_q24"][-1] == round(.04*Q24))
            rejects("native physical clock regression", lambda: native.sparse_features([0., 0.], [1., .5], [True, True]))

            receipt = native.receipt
            reference = Path(receipt["reference_binary"])
            check("fresh legacy reference binary bound to receipt", hashlib.sha256(reference.read_bytes()).hexdigest() == receipt["reference_binary_sha256"])
            requests = [{"case": "parity", "readback_digest": digest("real.readback"), "feedback_q24": value,
                         "reset_before_readout": reset} for value in (-Q24, -Q24//3, 0, Q24//3, Q24) for reset in (False, True)]
            completed = subprocess.run([str(reference)], input="".join(json.dumps(x)+"\n" for x in requests),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            for request_body, line in zip(requests, completed.stdout.splitlines(), strict=True):
                original = json.loads(line)
                adapted = native.tick_pair(**request_body)
                strip = lambda row: [{k:v for k,v in tick.items() if k != "native_ns"} for tick in row["ticks"]]
                check("original feedback adapter exact semantic parity", strip(original) == strip(adapted),
                      feedback_q24=request_body["feedback_q24"], reset=request_body["reset_before_readout"])

            typed_directory = directory / "typed"
            first = native.typed("typed.audit", typed_directory, .2, .3, -.5, .5)
            second = native.typed("typed.audit", typed_directory, .2, .3, -.5, .5,
                                  expected_checkpoint=first["checkpoint_after"])
            check("original typed runtime recovers journal and independent witness",
                  first["sequence"] == 1 and not first["recovered"] and second["sequence"] == 2
                  and second["recovered"] and second["checkpoint_before"] == first["checkpoint_after"])
            rejects("original typed runtime rejects stale CAS", lambda: native.typed(
                "typed.audit", typed_directory, .2, .3, -.5, .5, expected_checkpoint=first["checkpoint_after"]))
            rejects("native witness enforces subject scope", lambda: native.typed("other.subject", typed_directory, .2, .3, -.5, .5))
            journal_path = typed_directory / "state.journal"
            original_bytes = journal_path.read_bytes()
            journal_path.write_bytes(original_bytes[:-464])
            rejects("native independent witness rejects acknowledged journal rollback", lambda: native.typed(
                "typed.audit", typed_directory, .2, .3, -.5, .5))
            journal_path.write_bytes(original_bytes)
            rng = np.random.default_rng(913)
            cases = [[m, 0., -.5, .5] for m in [-.6, -.5, 0., .5, .6]]
            cases += [[float(rng.uniform(-3, 3)), float(rng.uniform(.04, 4)), -.5, .5] for _ in range(80)]
            cases += [[7., 1e-5, -.5, .5], [-7., 1e-5, -.5, .5], [0., 1/Q24, -.5, .5]]
            raw_error = []; output_error = []; input_error = []; typed_samples = []
            for parameters in cases:
                result = native.typed("typed.audit", typed_directory, *parameters)
                head = result["head"]
                expected_quantized = event_probs(*head["parameters_q24_decoded"])
                original_fp64 = event_probs(*parameters)
                raw_error.append(float(np.max(np.abs(np.asarray(head["probabilities"]) - expected_quantized))))
                output_error.append(float(np.max(np.abs(np.asarray(head["probabilities_q24"])/Q24 - expected_quantized))))
                input_error.append(float(np.max(np.abs(original_fp64 - expected_quantized))))
                check("analytic probability stays distinct from runtime confidence",
                      sum(head["probabilities_q24"]) == Q24 and result["legacy_runtime_confidence_ppm"] == 0
                      and result["abstain"] and result["authority"] == "DENY_ALL")
                typed_samples.append(result)
            check("native erfc probability matches independent SciPy reference", max(raw_error) < 2e-15,
                  maximum_error=max(raw_error), cases=len(cases))
            check("native output Q24 error separately bounded", max(output_error) <= 1/Q24 + 2e-15,
                  maximum_error=max(output_error), input_parameter_quantization_max_probability_error=max(input_error))
            rejects("native sub-Q24 variance rejected explicitly", lambda: native.typed("typed.audit", typed_directory, 0., 1e-10, -.5, .5))
            rejects("native Q24 threshold collapse rejected explicitly", lambda: native.typed("typed.audit", typed_directory, 0., 1., 0., 1e-10))
            typed_latest = typed_samples[-1]
            check("native workload counted", native.original_sparse_ticks > 100,
                  requests=native.calls, original_sparse_ticks=native.original_sparse_ticks)
        with Native(native_binary, native_receipt) as fresh_process:
            after_restart = fresh_process.typed("typed.audit", typed_directory, 0., .25, -.5, .5,
                                                expected_checkpoint=typed_latest["checkpoint_after"])
            check("separate process recovers durable native owner",
                  after_restart["sequence"] == typed_latest["sequence"] + 1
                  and after_restart["checkpoint_before"] == typed_latest["checkpoint_after"])
        shutil.copytree(typed_directory, output / "native_owner", dirs_exist_ok=True)
        (output / "TYPED_SAMPLES.json").write_text(json.dumps([first, second, *typed_samples, after_restart], indent=2, sort_keys=True)+"\n")
        (output / "NATIVE_HISTORY_SAMPLE.json").write_text(json.dumps(history, indent=2, sort_keys=True)+"\n")

    summary = {"schema": "hepta.analytic-event.runtime-validation.v1", "all_passed": True,
               "checks": checks, "check_count": len(checks),
               "native_binary_sha256": hashlib.sha256(Path(native_binary).read_bytes()).hexdigest(),
               "limits": ["Linux x86_64 native libm qualification only", "No Agentd production owner integration",
                          "No empirical calibration claimed for typed legacy confidence",
                          "Python checksum alone is not hostile-writer authentication; rollback needs caller-held anchor",
                          "4096 steps validate numerical recurrence, not multi-day retention"]}
    (output / "RUNTIME_VALIDATION.json").write_text(json.dumps(summary, indent=2, sort_keys=True)+"\n")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--native-binary", required=True)
    parser.add_argument("--native-receipt", required=True)
    result = validate(**vars(parser.parse_args()))
    print(json.dumps({"all_passed": result["all_passed"], "check_count": result["check_count"]}))


if __name__ == "__main__":
    main()
