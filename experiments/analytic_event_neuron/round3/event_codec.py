"""Integer event transport with decoder-side action interval certificates.

Communication events carry Gaussian state changes; they are not call/put draws.
Precision changes explicitly rebase the integer state. No continuous posterior
or encoder residual enters the decoder, forecast, or action calculation.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np

from .. import learners, task
from ..round2 import predictors as prior_predictors


KIND = "decision_event_filter_v1"
SCHEMA = "hepta.decision-event.packet.v1"
KINDS = ("observed", "missing", "refinement")
MODES = ("error_feedback", "direct_quantization", "increment_only")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def nearest(value):
    """Nearest integer; exact half ties go to the positive side."""
    return math.floor(value + .5)


@dataclass(frozen=True)
class Config:
    mean_bits: int = 8
    initial_logvar_bits: int = 4
    maximum_logvar_bits: int = 24
    adaptive: bool = True
    mode: str = "error_feedback"

    def __post_init__(self):
        if (type(self.mean_bits) is not int or not 0 <= self.mean_bits <= 24
                or type(self.initial_logvar_bits) is not int
                or type(self.maximum_logvar_bits) is not int
                or not 0 <= self.initial_logvar_bits <= self.maximum_logvar_bits <= 24
                or type(self.adaptive) is not bool or self.mode not in MODES):
            raise ValueError("Invalid event precision or mode")


class Decoder:
    """Independent integer packet receiver with strict clocks and rebase rules."""

    def __init__(self, config):
        self.config = config
        self.config_sha256 = digest(asdict(config))
        self.bits = [config.mean_bits, config.initial_logvar_bits]
        self.levels = [0, 0]
        self.sequence = 0
        self.time = None

    def rebased(self, bits):
        return [nearest(math.ldexp(self.levels[j], bits[j] - self.bits[j]))
                for j in range(2)]

    def apply(self, packet):
        required = {"schema", "config_sha256", "sequence", "time", "kind", "bits", "counts"}
        if set(packet) != required or packet["schema"] != SCHEMA:
            raise ValueError("Unknown event packet schema")
        if packet["config_sha256"] != self.config_sha256:
            raise ValueError("Event configuration mismatch")
        if type(packet["sequence"]) is not int or packet["sequence"] != self.sequence + 1:
            raise ValueError("Duplicate, regressed, or skipped event sequence")
        timestamp = packet["time"]
        if (type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0
                or (self.time is not None and timestamp < self.time) or packet["kind"] not in KINDS):
            raise ValueError("Invalid event clock or observation kind")
        bits, counts = packet["bits"], packet["counts"]
        if (not isinstance(bits, list) or len(bits) != 2 or bits[0] != self.config.mean_bits
                or any(type(x) is not int for x in bits)
                or not self.config.initial_logvar_bits <= bits[1] <= self.config.maximum_logvar_bits
                or not isinstance(counts, list) or len(counts) != 2
                or any(type(x) is not int or abs(x) > 2**48 for x in counts)):
            raise ValueError("Invalid event precision or signed counts")
        if packet["kind"] == "refinement":
            if (self.sequence == 0 or float(timestamp) != self.time
                    or bits[1] <= self.bits[1] or counts[0] != 0):
                raise ValueError("Refinement requires existing state, the same time and increased log-variance precision")
        elif bits[1] != self.config.initial_logvar_bits:
            raise ValueError("Observation packets reset to the registered initial log-variance precision")
        base = self.rebased(bits)
        levels = [base[j] + counts[j] for j in range(2)]
        if any(abs(x) > 2**48 for x in levels) or abs(math.ldexp(levels[1], -bits[1])) > 600:
            raise ValueError("Event state outside numerical domain")
        self.bits, self.levels = list(bits), levels
        self.sequence, self.time = packet["sequence"], float(timestamp)
        return self.readout()

    def readout(self):
        return math.ldexp(self.levels[0], -self.bits[0]), math.exp(math.ldexp(self.levels[1], -self.bits[1]))

    def variance_interval(self):
        center = math.ldexp(self.levels[1], -self.bits[1])
        half = math.ldexp(.5, -self.bits[1])
        # Outward FP64 allowance for logarithm, exponentiation and encoding.
        pad = 32 * math.ulp(max(1.0, abs(center)))
        return math.exp(center - half - pad), math.exp(center + half + pad)

    def snapshot(self):
        return {"schema": "hepta.decision-event.decoder.v1", "config": asdict(self.config),
                "bits": list(self.bits), "levels": list(self.levels),
                "sequence": self.sequence, "time": self.time}

    @classmethod
    def restore(cls, state):
        if set(state) != {"schema", "config", "bits", "levels", "sequence", "time"}:
            raise ValueError("Unknown decoder checkpoint fields")
        if state["schema"] != "hepta.decision-event.decoder.v1":
            raise ValueError("Unknown decoder checkpoint schema")
        decoder = cls(Config(**state["config"]))
        if state["sequence"] == 0:
            if state != decoder.snapshot():
                raise ValueError("Nonempty initial decoder checkpoint")
            return decoder
        if type(state["sequence"]) is not int or state["sequence"] < 1:
            raise ValueError("Invalid checkpoint sequence")
        bits, levels, timestamp = state["bits"], state["levels"], state["time"]
        if (not isinstance(bits, list) or len(bits) != 2 or any(type(x) is not int for x in bits)
                or bits[0] != decoder.config.mean_bits
                or not decoder.config.initial_logvar_bits <= bits[1] <= decoder.config.maximum_logvar_bits
                or not isinstance(levels, list) or len(levels) != 2
                or any(type(x) is not int or abs(x) > 2**48 for x in levels)
                or type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0
                or abs(math.ldexp(levels[1], -bits[1])) > 600):
            raise ValueError("Invalid checkpoint precision, values, or clock")
        decoder.bits, decoder.levels = list(bits), list(levels)
        decoder.sequence, decoder.time = state["sequence"], float(timestamp)
        return decoder


class Encoder:
    """Subtractive residual encoder; integer receiver is its only output state."""

    def __init__(self, config, channel=None):
        self.decoder = Decoder(config)
        self.target = [0.0, 0.0]
        self.residual = [0.0, 0.0]
        self.channel = channel
        self.packets = []
        self.units_by_bits = {}
        self.rebases = 0
        self.wire_bytes = 0

    def send(self, mean, variance, timestamp, kind, logvar_bits=None):
        if not math.isfinite(mean) or not math.isfinite(variance) or variance <= 0:
            raise ValueError("Finite mean and positive variance required")
        target = [float(mean), math.log(float(variance))]
        if abs(target[1]) > 600:
            raise ValueError("Log variance outside [-600, 600]")
        if kind == "refinement" and target != self.target:
            raise ValueError("Refinement may not introduce a new continuous target")
        config = self.decoder.config
        bits = [config.mean_bits, config.initial_logvar_bits if logvar_bits is None else logvar_bits]
        base = self.decoder.rebased(bits)
        counts = []
        for j in range(2):
            step = math.ldexp(1.0, -bits[j])
            if config.mode == "direct_quantization":
                count = nearest(target[j] / step) - base[j]
            else:
                old_center = math.ldexp(self.decoder.levels[j], -self.decoder.bits[j])
                residual = self.residual[j] if config.mode == "error_feedback" else 0.0
                delta = math.fsum([target[j], -self.target[j], residual,
                                   old_center, -base[j] * step])
                count = nearest(delta / step)
            counts.append(int(count))
        packet = {"schema": SCHEMA, "config_sha256": self.decoder.config_sha256,
                  "sequence": self.decoder.sequence + 1, "time": float(timestamp),
                  "kind": kind, "bits": bits, "counts": counts}
        rebased = int(bits != self.decoder.bits)
        payload = (json.dumps(packet, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        readback = self.channel(payload) if self.channel is not None else payload
        if readback != payload:
            raise ValueError("Integer event transport readback differs from submission")
        reopened = json.loads(readback)
        self.decoder.apply(reopened)
        self.rebases += rebased
        self.packets.append(reopened)
        self.wire_bytes += len(readback)
        for j, name in enumerate(("mean", "logvar")):
            key = f"{name}:{bits[j]}"
            self.units_by_bits[key] = self.units_by_bits.get(key, 0) + abs(counts[j])
        self.target = target
        self.residual = ([target[j] - math.ldexp(self.decoder.levels[j], -bits[j]) for j in range(2)]
                         if config.mode != "increment_only" else [0.0, 0.0])
        return reopened


def scores_for_variance(variance, horizon, q, noise_scale, multiplier):
    """Monotone variance VOI scores, algebraically equal to frozen Round 2."""
    values = (variance, q, noise_scale, multiplier)
    if (horizon not in (1.0, 2.0) or not all(math.isfinite(x) for x in values)
            or min(values) <= 0):
        raise ValueError("Unregistered planning domain")
    r = noise_scale * task.REPAIR_VARIANCE
    repair_cost = task.REPAIR_COST * multiplier
    def harmonic(a, b):
        small, large = min(a, b), max(a, b)
        return small / (1.0 + small / large)
    scores = {"stop": variance + q * horizon,
              "repair": q * horizon + harmonic(variance, r) + repair_cost}
    if horizon == 2.0:
        p, s = variance + q, noise_scale * task.OBSERVATION_VARIANCE
        after = harmonic(p, s)
        scores["wait"] = (task.WAIT_COST * multiplier + q
                          + min(after, harmonic(after, r) + repair_cost))
    if not all(math.isfinite(value) for value in scores.values()):
        raise ValueError("Planning score exceeds finite numerical domain")
    return scores


def decision_certificate(decoder, model, horizon, multiplier):
    """One decoded choice is optimal throughout its represented variance cell."""
    _, variance = decoder.readout()
    low, high = decoder.variance_interval()
    args = (horizon, model["planning_q"], model["planning_noise_scale"], multiplier)
    center = scores_for_variance(variance, *args)
    lower, upper = scores_for_variance(low, *args), scores_for_variance(high, *args)
    selected = min(center, key=center.get)
    # Strict separation avoids silently asserting a tie-breaking theorem.
    margin = min(lower[other] - upper[selected] for other in center if other != selected)
    tolerance = 64 * math.ulp(max(1.0, *upper.values()))
    valid_cell = decoder.config.mode != "increment_only"
    return {"selected": selected, "scores": center, "variance_interval": [low, high],
            "score_intervals": {name: [lower[name], upper[name]] for name in center},
            "separation_margin": margin, "numeric_allowance": tolerance,
            "certified": bool(valid_cell and margin > tolerance),
            "cell_contains_driver_claimed": valid_cell}


class Session:
    """A persistent episode receiver; only newly acquired history slots are sent."""

    def __init__(self, model, channel=None):
        if model.get("kind") != KIND:
            raise ValueError("Expected decision-event model")
        parameters = model.get("parameters")
        if (not isinstance(parameters, list) or len(parameters) != 3
                or not all(math.isfinite(x) for x in parameters) or min(parameters[1:]) <= 0
                or model.get("planning_q") != parameters[1]
                or model.get("planning_noise_scale") != parameters[2]):
            raise ValueError("Finite Gaussian driver and matching positive planning parameters required")
        self.model = model
        self.encoder = Encoder(Config(**model["event_config"]), channel)
        self.history_prefix = []
        self.current_target = (0.0, 1.0)
        self.timestamp = 0.0

    def sync(self, h):
        if len(h["obs"]) != 1:
            raise ValueError("A persistent event session holds exactly one episode")
        shape = np.asarray(h["obs"]).shape
        fields = ("obs", "times", "mask", "occupied", "obs_var")
        if any(np.asarray(h[key]).shape != shape for key in fields):
            raise ValueError("History fields must have identical shapes")
        if any(np.asarray(h[key]).dtype != bool for key in ("mask", "occupied")):
            raise ValueError("History masks must be Boolean")
        occupied = h["occupied"][0]
        n = int(np.sum(occupied))
        if not np.array_equal(occupied, np.arange(len(occupied)) < n):
            raise ValueError("History occupancy must be a prefix")
        seen = h["occupied"] & h["mask"]
        if (not np.isfinite(h["times"][h["occupied"]]).all()
                or np.any(h["times"][h["occupied"]] < 0)
                or not np.isfinite(h["obs"][seen]).all()
                or not np.isfinite(h["obs_var"][seen]).all() or np.any(h["obs_var"][seen] <= 0)):
            raise ValueError("Invalid public observation, time, or variance")
        # Missing payload bytes carry no information, including arbitrary NaNs.
        h = {**h, "obs": np.where(seen, h["obs"], 0.0),
             "times": np.where(h["occupied"], h["times"], 0.0),
             "obs_var": np.where(seen, h["obs_var"], 1.0), "mask": seen}
        _, _, path = learners.filter_states(h, self.model["parameters"], return_path=True)
        for j in range(n):
            seen = bool(h["mask"][0, j])
            item = [float(h["times"][0, j]), seen,
                    float(h["obs"][0, j]) if seen else None,
                    float(h["obs_var"][0, j]) if seen else None]
            if j < len(self.history_prefix):
                if item != self.history_prefix[j]:
                    raise ValueError("Previously acquired history was rewritten")
                continue
            mean, variance, _ = path[j]
            self.current_target = float(mean[0]), float(variance[0])
            self.timestamp = item[0]
            self.encoder.send(*self.current_target, self.timestamp, "observed" if seen else "missing")
            self.history_prefix.append(item)
        if n < len(self.history_prefix):
            raise ValueError("History was truncated")

    def forecast(self, horizon):
        if not math.isfinite(horizon) or horizon not in task.HORIZONS:
            raise ValueError("Forecast horizon must be finite and registered")
        mean, variance = self.encoder.decoder.readout()
        drift, q, _ = self.model["parameters"]
        return mean + drift * horizon, variance + q * horizon

    def decide(self, horizon, multiplier):
        decoder = self.encoder.decoder
        certificate = decision_certificate(decoder, self.model, horizon, multiplier)
        config = decoder.config
        if config.adaptive and config.mode != "increment_only":
            while not certificate["certified"] and decoder.bits[1] < config.maximum_logvar_bits:
                bits = min(decoder.bits[1] + 2, config.maximum_logvar_bits)
                self.encoder.send(*self.current_target, self.timestamp, "refinement", bits)
                certificate = decision_certificate(decoder, self.model, horizon, multiplier)
        certificate["precision_bits"] = list(decoder.bits)
        certificate["maximum_precision_exhausted"] = bool(
            not certificate["certified"] and decoder.bits[1] == config.maximum_logvar_bits)
        return certificate

    def accounting(self):
        return {"packets": len(self.encoder.packets), "packet_bytes": self.encoder.wire_bytes,
                "logical_unit_events": sum(self.encoder.units_by_bits.values()),
                "logical_unit_events_by_resolution": dict(self.encoder.units_by_bits),
                "nonzero_channels": sum(sum(x != 0 for x in p["counts"]) for p in self.encoder.packets),
                "precision_rebases": self.encoder.rebases,
                "refinement_packets": sum(p["kind"] == "refinement" for p in self.encoder.packets),
                "decoder": self.encoder.decoder.snapshot()}


def predict(model, history, native=None):
    if model.get("kind") != KIND:
        return prior_predictors.predict(model, history, native)
    means, variances = [], []
    for i in range(len(history["obs"])):
        session = Session(model)
        session.sync(task.subset(history, i))
        row = [session.forecast(float(horizon)) for horizon in task.HORIZONS]
        means.append([x[0] for x in row])
        variances.append([x[1] for x in row])
    return np.asarray(means), np.asarray(variances)
