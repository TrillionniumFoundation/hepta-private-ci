"""Eight hard bipolar IF cells, deployment step and explicit SG reverse mode."""

import hashlib
import json

import numpy as np
from scipy.special import expit

from .kernel import activation, physical
from .task import features


THRESHOLDS = np.linspace(0.7, 1.4, 8)


def initialize(seed):
    random = np.random.default_rng(np.random.SeedSequence([seed, 1701]))
    weights = random.normal(0, 0.005, (6, 8))
    weights[0] = np.linspace(0.65, 1.35, 8) + random.normal(0, 0.02, 8)
    weights[1] = np.linspace(0.1, 0.3, 8)
    return {"weights": weights, "readout": np.full(8, 0.14), "bias": np.zeros(1)}


def parameter_digest(parameters):
    digest = hashlib.sha256()
    for key, value in sorted(parameters.items()):
        digest.update(key.encode())
        digest.update(np.ascontiguousarray(value).tobytes())
    return digest.hexdigest()


def initial_state():
    return {"membrane": [0.0] * 8, "trace": [0.0] * 8}


def step(
    parameters,
    state,
    observation,
    reliability,
    cost,
    deadline,
    elapsed,
    *,
    thresholds=THRESHOLDS,
):
    """One actual causal inference step; no future prefix or surrogate work."""
    inputs = features(observation, reliability, cost, deadline, elapsed)
    membrane, trace, signed, spikes = [], [], [], 0
    for cell in range(8):
        drive = 0.0
        for channel in range(6):
            drive += inputs[channel] * float(parameters["weights"][channel][cell])
        before = state["membrane"][cell] + drive
        positive = int(before > thresholds[cell])
        negative = int(-before > thresholds[cell])
        spike = positive - negative
        membrane.append(before - thresholds[cell] * spike)
        trace.append(state["trace"][cell] + spike)
        signed.append(spike)
        spikes += positive + negative
    voltage = 0.0
    for cell in range(8):
        voltage += trace[cell] * float(parameters["readout"][cell])
    voltage += float(np.asarray(parameters["bias"]).reshape(-1)[0])
    if not np.isfinite(voltage) or not np.all(np.isfinite(membrane)):
        raise FloatingPointError("nonfinite deployed neural state")
    return {"membrane": membrane, "trace": trace}, {
        "logit": voltage,
        "signed_spikes": signed,
        "spikes": spikes,
        "cell_updates": 8,
        "input_multiply_accumulates": 48,
        "readout_multiply_accumulates": 8,
    }


def forward(parameters, batch, raw, family, *, soft=False, mixed=False):
    count, horizon, _ = batch.features.shape
    membrane, trace = np.zeros((count, 8)), np.zeros((count, 8))
    voltages, traces, slopes, tangents, spike_counts = [], [], [], [], []
    for time_index in range(horizon):
        before = membrane + batch.features[:, time_index] @ parameters["weights"]
        positive, dp, tp = activation(
            before - THRESHOLDS, raw, family, soft=soft, mixed=mixed
        )
        negative, dn, tn = activation(
            -before - THRESHOLDS, raw, family, soft=soft, mixed=mixed
        )
        signed = positive - negative
        membrane = before - THRESHOLDS * signed
        trace = trace + signed
        voltages.append(trace @ parameters["readout"] + parameters["bias"][0])
        traces.append(trace.copy())
        slopes.append(dp + dn)
        if mixed:
            tangents.append(tp + tn)
        spike_counts.append(np.sum(positive + negative, axis=-1))
    return np.stack(voltages, axis=1), {
        "trace": np.stack(traces, axis=1),
        "slope": np.stack(slopes, axis=1),
        "slope_tangent": np.stack(tangents, axis=1) if mixed else None,
        "spike_counts": np.stack(spike_counts, axis=1),
        "cell_updates": count * horizon * 8,
        "surrogate_scalar_evaluations": count * horizon * 16,
    }


def loss_gradient(parameters, batch, raw, family, *, soft=False, mixed=False):
    """Calibration BCE, SG weight gradient and analytic d(SG gradient)/d(raw).

    With a hard forward, the weight derivative is explicitly a surrogate rule.
    At fixed weights the hard path is independent of raw, so mixed derivatives
    of that rule are well-defined. Soft validation always uses the standard
    logistic primitive and has an ordinary differentiable objective.
    """
    if soft and mixed:
        raise ValueError("mixed rule is defined for a fixed hard support path")
    voltage, tape = forward(parameters, batch, raw, family, soft=soft, mixed=mixed)
    valid = np.arange(voltage.shape[1])[None, :] < batch.deadline[:, None]
    target = (batch.truth[:, None] + 1) / 2
    loss = np.sum((np.logaddexp(0, voltage) - target * voltage) * valid) / valid.sum()
    dv = (expit(voltage) - target) * valid / valid.sum()
    gradient = {key: np.zeros_like(value) for key, value in parameters.items()}
    gradient["bias"][0] = np.sum(dv)
    gradient["readout"] = np.einsum("nt,nth->h", dv, tape["trace"])
    tangent = (
        {key: np.zeros(value.shape + (3,)) for key, value in parameters.items()}
        if mixed
        else None
    )
    dm = np.zeros((len(batch.truth), 8))
    dt = np.zeros_like(dm)
    dm_tangent = np.zeros(dm.shape + (3,)) if mixed else None
    for time_index in range(voltage.shape[1] - 1, -1, -1):
        dt += dv[:, time_index, None] * parameters["readout"]
        slope = tape["slope"][:, time_index]
        coefficient = dt - THRESHOLDS * dm
        du = dm + coefficient * slope
        gradient["weights"] += batch.features[:, time_index].T @ du
        if mixed:
            du_tangent = dm_tangent * (1 - THRESHOLDS * slope)[..., None]
            du_tangent += coefficient[..., None] * tape["slope_tangent"][:, time_index]
            tangent["weights"] += np.einsum(
                "nf,nhk->fhk", batch.features[:, time_index], du_tangent
            )
            dm_tangent = du_tangent
        dm = du
    return (
        float(loss),
        gradient,
        tangent,
        {
            "cell_updates": tape["cell_updates"],
            "surrogate_scalar_evaluations": tape["surrogate_scalar_evaluations"],
            "mixed_backward_parameter_channels": 3 if mixed else 0,
            "spike_sum": float(tape["spike_counts"].sum()),
            "soft_forward": soft,
        },
    )


def model_payload(parameters, raw, family, checkpoint_sha256):
    if (
        family not in ("standard", "first_passage")
        or len(checkpoint_sha256) != 64
        or any(character not in "0123456789abcdef" for character in checkpoint_sha256)
    ):
        raise ValueError("registered surrogate and checkpoint SHA-256 required")
    if any(
        np.asarray(parameters[key]).shape != shape
        for key, shape in (("weights", (6, 8)), ("readout", (8,)), ("bias", (1,)))
    ):
        raise ValueError("invalid neural parameter shape")
    values, _ = physical(raw)
    result = {
        "schema": "hepta.adaptive-neuron.snn.v2",
        "feature_schema": "bernoulli-six-v1",
        "weights": parameters["weights"].tolist(),
        "readout": parameters["readout"].tolist(),
        "bias": float(parameters["bias"][0]),
        "thresholds": THRESHOLDS.tolist(),
        "surrogate": {
            "family": family,
            **dict(zip(("mu", "sigma", "lambda"), values.tolist())),
            "horizon": 1.0,
        },
        "training_checkpoint_sha256": checkpoint_sha256,
    }
    json.dumps(result, allow_nan=False)
    return result
