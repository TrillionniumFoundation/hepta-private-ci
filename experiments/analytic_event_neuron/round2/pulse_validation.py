"""Development-only independent checks for the signed event state contract."""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
from scipy.special import ndtr

from .. import learners, task, train
from ..analytic import event_probs
from .pulse import (EventDecoder, PulseConfig, SignedEventNeuron, digest,
                    encode_history, fit_event_models, predict, probability_error_bound)


def validate():
    started = time.perf_counter_ns()
    checks = []

    def check(name, passed, **evidence):
        checks.append({"name": name, "passed": bool(passed), **evidence})

    def rejects(action):
        try:
            action()
        except (ValueError, TypeError, OverflowError):
            return True
        return False

    rng = np.random.default_rng(730091)
    length = 4096
    target = np.column_stack([np.cumsum(rng.normal(0.001, 0.13, length)),
                              np.cumsum(rng.normal(0, 0.035, length))])
    config = PulseConfig(1 / 32, 1 / 16)
    feedback = SignedEventNeuron(config)
    receiver = EventDecoder(config)
    direct = SignedEventNeuron(PulseConfig(config.mean_step, config.logvar_step, "direct_quantization"))
    maxima = np.zeros(2)
    differences = independent_failures = restarts = units = 0
    state_hashes = []
    for i, (mean, logvar) in enumerate(target):
        kind = ("observed", "missing", "propagation")[i % 3]
        packet = feedback.update(float(mean), math.exp(float(logvar)), i * 0.3, kind)
        wire = json.loads(json.dumps(packet, sort_keys=True))
        decoded = receiver.apply(wire)
        direct_packet = direct.update(float(mean), math.exp(float(logvar)), i * 0.3, kind)
        differences += packet["counts"] != direct_packet["counts"]
        units += sum(abs(x) for x in packet["counts"])
        independent = [math.floor(mean / config.mean_step + 0.5) * config.mean_step,
                       math.exp(math.floor(math.log(math.exp(logvar)) / config.logvar_step + 0.5) * config.logvar_step)]
        independent_failures += list(decoded) != independent
        maxima = np.maximum(maxima, np.abs([mean - decoded[0], logvar - math.log(decoded[1])]))
        if i in (0, 36, 255, 1023, 2047):
            original = feedback.snapshot()
            feedback = SignedEventNeuron.restore(json.loads(json.dumps(original)))
            receiver = EventDecoder.restore(json.loads(json.dumps(receiver.snapshot())))
            restarts += original == feedback.snapshot()
            state_hashes.append(digest(original))
    check("residual_bound_over_4096_updates", np.all(maxima <= np.array([config.mean_step, config.logvar_step]) / 2 + 1e-13),
          updates=length, maximum_errors=maxima.tolist(), logical_unit_events=units)
    check("independent_absolute_quantizer", independent_failures == 0, differing_updates=independent_failures)
    check("matched_direct_control", differences == 0, differing_count_packets=differences)
    check("decoder_only_reconstruction_and_checkpoint_continuation", restarts == 5 and receiver.snapshot() == feedback.decoder.snapshot(),
          checkpoint_restarts=restarts, checkpoint_sha256=state_hashes)

    bad = SignedEventNeuron(PulseConfig(0.1, 0.1, "increment_only"))
    good = SignedEventNeuron(PulseConfig(0.1, 0.1))
    for i in range(1, 101):
        bad.update(i * 0.049, 1.0, i)
        good.update(i * 0.049, 1.0, i)
    bad_error = abs(4.9 - bad.readout()[0])
    good_error = abs(4.9 - good.readout()[0])
    check("residual_discard_counterexample", bad_error > 4.8 and good_error <= 0.05 + 1e-13,
          increment_only_error=bad_error, error_feedback_error=good_error)

    # This is an independent Gaussian CDF implementation, not event_probs.
    max_excess = 0.0
    max_probability_error = 0.0
    for i in range(2000):
        mean = float(rng.normal(0, 8))
        variance = float(np.exp(rng.uniform(-12, 8)))
        current = SignedEventNeuron(PulseConfig(0.125, 0.125))
        current.update(mean, variance, i)
        decoded_mean, decoded_variance = current.readout()
        lo, hi = np.sort(rng.normal(mean, 4 * math.sqrt(variance), 2))
        exact_cdf = ndtr((np.array([lo, hi]) - mean) / math.sqrt(variance))
        coded_cdf = ndtr((np.array([lo, hi]) - decoded_mean) / math.sqrt(decoded_variance))
        exact = np.array([exact_cdf[0], exact_cdf[1] - exact_cdf[0], 1 - exact_cdf[1]])
        coded = np.array([coded_cdf[0], coded_cdf[1] - coded_cdf[0], 1 - coded_cdf[1]])
        error = np.abs(exact - coded)
        bound = probability_error_bound(mean, variance, decoded_mean, decoded_variance)
        max_excess = max(max_excess, float(np.max(error - bound)))
        max_probability_error = max(max_probability_error, float(error.max()))
    check("uniform_cdf_and_interval_error_bound", max_excess <= 2e-14,
          cases=2000, maximum_bound_excess=max_excess, maximum_probability_error=max_probability_error,
          qualification="Absolute bound can be loose for tiny variance; no relative tail-error guarantee")

    silent = SignedEventNeuron(PulseConfig())
    packets = [silent.update(0.0, 1.0, i, kind) for i, kind in enumerate(OBSERVATION_KINDS_LOCAL)]
    probability = event_probs(*silent.readout(), task.LOWER, task.UPPER)
    check("missing_propagation_and_silence_are_distinct", all(p["counts"] == [0, 0] for p in packets)
          and len({p["observation_kind"] for p in packets}) == 3 and probability[1] < 1,
          packets=packets, terminal_probabilities=probability.tolist())

    fresh = SignedEventNeuron(PulseConfig())
    packet = fresh.update(0.5, 0.3, 2)
    original = fresh.snapshot()
    bad_checkpoint = copy.deepcopy(original)
    bad_checkpoint["residual"][0] += 0.1
    malformed = copy.deepcopy(packet)
    malformed["sequence"] = fresh.decoder.sequence + 1
    malformed["counts"][0] = 1.0
    rejection_cases = {
        "zero_variance": lambda: fresh.update(0.0, 0.0, 3),
        "negative_variance": lambda: fresh.update(0.0, -1.0, 3),
        "nonfinite_mean": lambda: fresh.update(float("nan"), 1.0, 3),
        "clock_regression": lambda: fresh.update(0.0, 1.0, 1),
        "duplicate_packet": lambda: fresh.decoder.apply(packet),
        "noninteger_counts": lambda: fresh.decoder.apply(malformed),
        "inconsistent_encoder_residual": lambda: SignedEventNeuron.restore(bad_checkpoint),
        "unknown_version": lambda: EventDecoder.restore({**fresh.decoder.snapshot(), "schema": "unknown"}),
        "oversized_counts": lambda: fresh.update(1e10, 1.0, 3),
    }
    rejections = {name: rejects(action) for name, action in rejection_cases.items()}
    check("domain_and_state_rejections_are_transactional", all(rejections.values()) and fresh.snapshot() == original,
          rejections=rejections, checkpoint_unchanged=fresh.snapshot() == original)

    # Independent development fixtures; no confirmation or old confirmation is read.
    training = task.build_dataset(87301, 256, "train")
    development = task.build_dataset(98301, 96, "development")
    models, training_receipt = train.fit_models(training, development, 7301)
    extras, selection = fit_event_models(models, development, driver_training_receipt=training_receipt)
    history, targets = task.combine_training(development)
    continuous = learners.predict(models["analytic"], history)
    equivalent = learners.predict(models["equivalent_gaussian"], history)
    encoded = predict(extras["event_feedback"], history)
    direct_prediction = predict(extras["event_direct"], history)
    continuous_gap = max(float(np.max(np.abs(a - b))) for a, b in zip(continuous, equivalent))
    direct_gap = max(float(np.max(np.abs(a - b))) for a, b in zip(encoded, direct_prediction))
    first = training_receipt["objective_trace"][0]["composite_conditional_nll"]
    fitted = learners.nll(task.combine_training(training)[1],
                         *learners.predict(models["analytic"], task.combine_training(training)[0]))
    check("driver_is_actually_trained_and_bound", training_receipt["optimizer_success"]
          and training_receipt["filter_parameter_l2_change"] > 1e-6 and fitted < first
          and selection["driver_training_link"]["receipt_sha256"] == digest(training_receipt),
          initial_parameters=training_receipt["initial_filter_parameters"],
          fitted_parameters=training_receipt["fitted_filter_parameters"], initial_loss=first, fitted_loss=fitted,
          optimizer_success=training_receipt["optimizer_success"])
    check("trained_adapter_matches_direct_and_independent_probit_control", direct_gap < 1e-12 and continuous_gap < 1e-10,
          direct_event_prediction_gap=direct_gap, continuous_dense_gaussian_gap=continuous_gap)
    mean, variance, receipts = encode_history(extras["event_feedback"], history, include_packets=True)
    replayed = []
    for receipt in receipts:
        decoder = EventDecoder(PulseConfig(**extras["event_feedback"]["event_config"]))
        for packet in receipt["packets"]:
            decoder.apply(json.loads(json.dumps(packet)))
        replayed.append(decoder.readout())
    replayed = np.asarray(replayed)
    check("trained_history_packets_reconstruct_without_analog_bypass", np.array_equal(replayed[:, 0], mean)
          and np.array_equal(replayed[:, 1], variance), histories=len(receipts),
          packet_count=sum(r["updates"] for r in receipts))
    check("selection_rejects_confirmation_labels", rejects(lambda: fit_event_models(models, {**development, "split": "confirmation"})),
          existing_development_values_relabelled_only=True)
    return {"schema": "hepta.signed-event.validation.v1", "passed": all(x["passed"] for x in checks),
            "checks": checks, "passed_checks": sum(x["passed"] for x in checks), "total_checks": len(checks),
            "development_selection": selection, "training_receipt": training_receipt,
            "validation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "implementation_source_sha256": hashlib.sha256(Path(__file__).with_name("pulse.py").read_bytes()).hexdigest(),
            "python": platform.python_version(), "numpy": np.__version__, "elapsed_ns": time.perf_counter_ns() - started,
            "no_confirmation_data_used": True,
            "scope": "Numerical, codec, checkpoint and development training validation; no task superiority or hardware-efficiency qualification"}


OBSERVATION_KINDS_LOCAL = ("observed", "missing", "propagation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate()
    serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(json.dumps({"passed": result["passed"], "checks": result["total_checks"],
                      "failures": [x["name"] for x in result["checks"] if not x["passed"]],
                      "selected_config": result["development_selection"]["selected_config"]}))
    raise SystemExit(0 if result["passed"] else 1)
