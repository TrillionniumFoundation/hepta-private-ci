"""Signed error-feedback events carrying a learned Gaussian conditional state.

Counts transport changes of mean and log-variance. They are not sampled
put/call outcomes. The readout uses decoder counts, never encoder residuals.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import time

import numpy as np

from .. import learners, task


MODES = ("error_feedback", "direct_quantization", "increment_only")
OBSERVATION_KINDS = ("observed", "missing", "propagation")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class PulseConfig:
    mean_step: float = 1.0 / 64.0
    logvar_step: float = 1.0 / 64.0
    mode: str = "error_feedback"
    maximum_count: int = 2147483647

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError("Unknown event coding mode")
        if any(not math.isfinite(x) or x <= 0 or x > 32
               for x in (self.mean_step, self.logvar_step)):
            raise ValueError("Event steps must be finite and in (0,32]")
        if type(self.maximum_count) is not int or not 0 < self.maximum_count <= 2**52:
            raise ValueError("Invalid per-channel event-count limit")


class EventDecoder:
    """A receiver that reconstructs its state solely from signed count packets."""

    def __init__(self, config):
        self.config = config
        self.config_sha256 = digest(asdict(config))
        self.levels = [0, 0]
        self.sequence = 0
        self.time = None

    def apply(self, packet):
        required = {"schema", "config_sha256", "sequence", "time", "observation_kind", "counts"}
        if set(packet) != required or packet["schema"] != "hepta.signed-event.packet.v1":
            raise ValueError("Invalid event packet schema")
        if packet["config_sha256"] != self.config_sha256:
            raise ValueError("Event configuration mismatch")
        if type(packet["sequence"]) is not int or packet["sequence"] != self.sequence + 1:
            raise ValueError("Event sequence gap, duplicate or regression")
        timestamp = float(packet["time"])
        if not math.isfinite(timestamp) or timestamp < 0 or (self.time is not None and timestamp < self.time):
            raise ValueError("Event clock regression or invalid time")
        if packet["observation_kind"] not in OBSERVATION_KINDS:
            raise ValueError("Unknown observation kind")
        counts = packet["counts"]
        if not isinstance(counts, list) or len(counts) != 2 or any(
                type(x) is not int or abs(x) > self.config.maximum_count for x in counts):
            raise ValueError("Invalid signed event counts")
        levels = [self.levels[j] + counts[j] for j in range(2)]
        if any(abs(x) > 2**52 for x in levels) or abs(levels[1] * self.config.logvar_step) > 700:
            raise ValueError("Decoder state outside numerical domain")
        self.levels, self.sequence, self.time = levels, packet["sequence"], timestamp
        return self.readout()

    def readout(self):
        return (self.levels[0] * self.config.mean_step,
                math.exp(self.levels[1] * self.config.logvar_step))

    def snapshot(self):
        return {"schema": "hepta.signed-event.decoder.v1", "config": asdict(self.config),
                "levels": list(self.levels), "sequence": self.sequence, "time": self.time}

    @classmethod
    def restore(cls, saved):
        if set(saved) != {"schema", "config", "levels", "sequence", "time"} or saved["schema"] != "hepta.signed-event.decoder.v1":
            raise ValueError("Invalid decoder checkpoint schema")
        result = cls(PulseConfig(**saved["config"]))
        levels, sequence, timestamp = saved["levels"], saved["sequence"], saved["time"]
        if not isinstance(levels, list) or len(levels) != 2 or any(type(x) is not int or abs(x) > 2**52 for x in levels):
            raise ValueError("Invalid decoder checkpoint levels")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("Invalid decoder checkpoint sequence")
        if (sequence == 0 and (levels != [0, 0] or timestamp is not None)) or (sequence > 0 and
                (timestamp is None or not math.isfinite(float(timestamp)) or float(timestamp) < 0)):
            raise ValueError("Invalid decoder checkpoint clock")
        if abs(levels[1] * result.config.logvar_step) > 700:
            raise ValueError("Decoder checkpoint outside numerical domain")
        result.levels, result.sequence, result.time = list(levels), sequence, timestamp
        return result


class SignedEventNeuron:
    """Encoder plus an independently applicable count receiver.

    Subtractive reset retains the rounding residual. Increment-only is the
    matched residual-discarding ablation. Direct quantization is a deliberately
    equivalent statistical control, implemented without residual recurrence.
    """

    def __init__(self, config=None):
        self.config = config or PulseConfig()
        self.decoder = EventDecoder(self.config)
        self.last_target = [0.0, 0.0]
        self.residual = [0.0, 0.0]

    def update(self, mean, variance, time, observation_kind="observed"):
        if not math.isfinite(mean) or not math.isfinite(variance) or variance <= 0:
            raise ValueError("Event encoding requires finite mean and strictly positive finite variance")
        target = [float(mean), math.log(float(variance))]
        if abs(target[1]) > 600:
            raise ValueError("Log-variance outside registered event coding domain [-600,600]")
        steps = (self.config.mean_step, self.config.logvar_step)
        counts = []
        for j, step in enumerate(steps):
            if self.config.mode == "direct_quantization":
                count = math.floor(target[j] / step + 0.5) - self.decoder.levels[j]
            else:
                feedback = self.residual[j] if self.config.mode == "error_feedback" else 0.0
                accumulator = math.fsum([target[j], -self.last_target[j], feedback])
                count = math.floor(accumulator / step + 0.5)
            counts.append(int(count))
        packet = {"schema": "hepta.signed-event.packet.v1", "config_sha256": self.decoder.config_sha256,
                  "sequence": self.decoder.sequence + 1, "time": float(time),
                  "observation_kind": observation_kind, "counts": counts}
        self.decoder.apply(packet)
        self.last_target = target
        self.residual = ([target[j] - self.decoder.levels[j] * steps[j] for j in range(2)]
                         if self.config.mode != "increment_only" else [0.0, 0.0])
        return packet

    def readout(self):
        return self.decoder.readout()

    def snapshot(self):
        return {"schema": "hepta.signed-event.neuron.v1", "decoder": self.decoder.snapshot(),
                "last_target": list(self.last_target), "residual": list(self.residual)}

    @classmethod
    def restore(cls, saved):
        if set(saved) != {"schema", "decoder", "last_target", "residual"} or saved["schema"] != "hepta.signed-event.neuron.v1":
            raise ValueError("Invalid neuron checkpoint schema")
        decoder = EventDecoder.restore(saved["decoder"])
        result = cls(decoder.config)
        result.decoder = decoder
        for key in ("last_target", "residual"):
            value = saved[key]
            if not isinstance(value, list) or len(value) != 2 or not all(math.isfinite(x) for x in value):
                raise ValueError("Invalid encoder checkpoint values")
            setattr(result, key, [float(x) for x in value])
        if abs(result.last_target[1]) > 600:
            raise ValueError("Encoder checkpoint outside log-variance domain")
        if decoder.sequence == 0 and (result.last_target != [0.0, 0.0] or result.residual != [0.0, 0.0]):
            raise ValueError("Unstarted encoder checkpoint has nonzero state")
        if result.config.mode == "increment_only":
            if result.residual != [0.0, 0.0]:
                raise ValueError("Residual-discarding checkpoint contains residual")
        else:
            steps = (result.config.mean_step, result.config.logvar_step)
            for j, step in enumerate(steps):
                expected = result.last_target[j] - decoder.levels[j] * step
                tolerance = 16 * math.ulp(max(1.0, abs(result.last_target[j])))
                if abs(result.residual[j] - expected) > tolerance or abs(result.residual[j]) > step / 2 + tolerance:
                    raise ValueError("Inconsistent error-feedback checkpoint")
        return result


def probability_error_bound(mean, variance, decoded_mean, decoded_variance):
    """Uniform endpoint/interval bound from the Gaussian CDF derivatives."""
    if min(variance, decoded_variance) <= 0 or not all(math.isfinite(x) for x in
                                                     (mean, variance, decoded_mean, decoded_variance)):
        raise ValueError("Probability bound requires finite positive Gaussian variances")
    mean_term = abs(mean - decoded_mean) / (math.sqrt(2 * math.pi) * math.sqrt(max(variance, decoded_variance)))
    scale_term = abs(math.log(variance) - math.log(decoded_variance)) / (2 * math.sqrt(2 * math.pi * math.e))
    endpoint = min(1.0, mean_term + scale_term)
    return [endpoint, min(1.0, 2 * endpoint), endpoint]


def encode_history(model, history, include_packets=False):
    """Encode public-history posteriors; targets and private labels are absent."""
    config = PulseConfig(**model["event_config"])
    _, _, path = learners.filter_states(history, model["parameters"], return_path=True)
    means, variances, receipts = [], [], []
    for row in range(len(history["obs"])):
        neuron = SignedEventNeuron(config)
        packets = []
        units = channels = wire_bytes = 0
        for column, (mean, variance, active) in enumerate(path):
            if not active[row]:
                continue
            kind = "observed" if history["mask"][row, column] else "missing"
            packet = neuron.update(float(mean[row]), float(variance[row]),
                                   float(history["times"][row, column]), kind)
            units += sum(abs(n) for n in packet["counts"])
            channels += sum(n != 0 for n in packet["counts"])
            wire_bytes += len(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode())
            if include_packets:
                packets.append(packet)
        mean, variance = neuron.readout()
        means.append(mean)
        variances.append(variance)
        receipt = {"logical_unit_events": units, "nonzero_channel_packets": channels,
                   "updates": neuron.decoder.sequence, "packet_bytes": wire_bytes,
                   "state_sha256": digest(neuron.snapshot()), "decoder": neuron.decoder.snapshot()}
        if include_packets:
            receipt.update({"packets": packets, "encoder_checkpoint": neuron.snapshot()})
        receipts.append(receipt)
    return np.asarray(means), np.asarray(variances), receipts


def predict(model, h, native=None, raw=None):
    if model.get("kind") != "signed_event_filter":
        return learners.predict(model, h, native=native, raw=raw)
    mean, variance, _ = encode_history(model, h)
    drift, q, _ = model["parameters"]
    return mean[:, None] + drift * task.HORIZONS, variance[:, None] + q * task.HORIZONS


def fit_event_models(models, development, steps=None, maximum_development_nll_deficit=0.002,
                     driver_training_receipt=None):
    """Select a transport resolution on development data after driver training.

    This is a finite codec selection, not a claim of a gradient through spikes.
    The driver parameters are copied exactly from the actually fitted filter.
    """
    if development["split"] != "development":
        raise ValueError("Event resolution selection accepts development data only")
    if models["analytic"]["kind"] != "filter":
        raise ValueError("Event driver must be the trained Gaussian filter")
    if not math.isfinite(maximum_development_nll_deficit) or maximum_development_nll_deficit < 0:
        raise ValueError("Invalid development NLL budget")
    steps = list(steps) if steps is not None else [2.0**-k for k in (7, 6, 5, 4, 3)]
    if not steps:
        raise ValueError("Event resolution grid is empty")
    history, target = task.combine_training(development)
    driver = models["analytic"]
    training_link = None
    if driver_training_receipt is not None:
        if driver_training_receipt["fitted_filter_parameters"] != driver["parameters"]:
            raise ValueError("Training receipt does not identify the supplied driver")
        training_link = {"receipt_sha256": digest(driver_training_receipt),
                         "initial_filter_parameters": driver_training_receipt["initial_filter_parameters"],
                         "fitted_filter_parameters": driver_training_receipt["fitted_filter_parameters"],
                         "filter_parameter_l2_change": driver_training_receipt["filter_parameter_l2_change"],
                         "optimizer_success": driver_training_receipt["optimizer_success"],
                         "objective_trace_sha256": digest(driver_training_receipt["objective_trace"])}
    baseline_nll = learners.nll(target, *learners.predict(driver, history))
    candidates = []
    started = time.perf_counter_ns()
    for mean_step in steps:
        for logvar_step in steps:
            config = PulseConfig(float(mean_step), float(logvar_step))
            model = {**driver, "kind": "signed_event_filter", "event_config": asdict(config),
                     "driver_sha256": digest(driver), "driver_parameters_frozen": True}
            mean, variance, receipt = encode_history(model, history)
            drift, q, _ = model["parameters"]
            nll = learners.nll(target, mean[:, None] + drift * task.HORIZONS,
                               variance[:, None] + q * task.HORIZONS)
            candidates.append({"event_config": asdict(config), "development_nll": nll,
                               "deficit": nll - baseline_nll,
                               "logical_unit_events": sum(r["logical_unit_events"] for r in receipt),
                               "nonzero_channel_packets": sum(r["nonzero_channel_packets"] for r in receipt),
                               "packet_bytes": sum(r["packet_bytes"] for r in receipt)})
    qualifying = [i for i, candidate in enumerate(candidates)
                  if candidate["deficit"] <= maximum_development_nll_deficit]
    fallback = not qualifying
    eligible = qualifying if qualifying else list(range(len(candidates)))
    selected = min(eligible, key=lambda i: ((candidates[i]["deficit"] if fallback else
                                            candidates[i]["logical_unit_events"]),
                                           candidates[i]["development_nll"], i))
    config = candidates[selected]["event_config"]
    extras = {}
    for name, mode in (("event_feedback", "error_feedback"), ("event_direct", "direct_quantization"),
                       ("event_no_residual", "increment_only")):
        extras[name] = {**driver, "kind": "signed_event_filter", "event_config": {**config, "mode": mode},
                        "driver_sha256": digest(driver), "driver_parameters_frozen": True}
    return extras, {"schema": "hepta.signed-event.selection.v1", "development_dataset_sha256": task.dataset_digest(development),
                    "driver_sha256": digest(driver), "fitted_driver_parameters": driver["parameters"],
                    "driver_training_link": training_link, "independent_development_trajectories": len(development["obs"]),
                    "baseline_development_nll": baseline_nll, "maximum_development_nll_deficit": maximum_development_nll_deficit,
                    "selection_rule": "minimum logical unit counts within development NLL budget; best NLL fallback if none qualify",
                    "candidates": candidates, "selected_index": selected, "selected_config": config,
                    "development_budget_met": not fallback, "selection_ns": time.perf_counter_ns() - started,
                    "training_scope": "driver fitted externally; finite development-only resolution selection; no gradient-through-spikes claim",
                    "model_sha256": digest(extras)}
