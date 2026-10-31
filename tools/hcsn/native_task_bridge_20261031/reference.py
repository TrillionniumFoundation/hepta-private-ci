"""The explicit numeric deployment profile shared by Python and native Rust.

A float64 policy is a separate reference. Equal native integer scores select the
lowest legal action index; a mathematically tied float64 last bit cannot decide.
"""
import hashlib
import numpy as np

NUMERIC_CONTRACT = "hepta.task.native-q24-residual.v1"
SCALE = 2**24


def deployment_digest(model_sha256):
    return hashlib.sha256(b"hepta.task.deployment-model.v1"
        + bytes.fromhex(model_sha256) + NUMERIC_CONTRACT.encode()).hexdigest()


def q24(values):
    value = np.asarray(values, float)
    if not np.all(np.isfinite(value)) or np.any(np.abs(value) > 8.):
        raise ValueError("Outside finite signed Q24 input envelope [-8,8]")
    return np.sign(value)*np.floor(np.abs(value)*SCALE+.5)/SCALE


def select_action(scores, feasible):
    scores, feasible = np.asarray(scores, float), np.asarray(feasible, bool)
    if scores.shape != (4,) or feasible.shape != (4,) or not feasible[0]:
        raise ValueError("Require four scores and legal STOP")
    if not np.all(np.isfinite(scores[feasible])) or np.any(scores[feasible] < -4.) or np.any(scores[feasible] >= 4.):
        raise ValueError("Legal scores must be in [-4,4); saturation rejects instead of clipping")
    drive = np.zeros(5, dtype=np.int64)
    drive[:4][feasible] = np.floor((scores[feasible]+4.)*SCALE+.5).astype(np.int64)
    action = int(np.argmax(drive))
    if action >= 4 or not feasible[action]:
        raise ArithmeticError("Native action contract cannot choose sentinel or infeasible action")
    return action, drive


def infer(checkpoint, features, prior, feasible):
    raw = q24(features)
    legal = np.asarray(feasible, bool)
    prior = q24(np.where(legal, np.asarray(prior, float), 0.))
    weights = {k:np.asarray(v, float) for k,v in checkpoint["weights"].items()}
    x = np.clip((raw-checkpoint["norm"]["mean"])/checkpoint["norm"]["scale"], -8., 8.)
    q = prior+np.maximum(0., np.tanh(x@weights["w"]+weights["b"])@weights["v"]+weights["c"])
    q[0] = 0.
    action, drive = select_action(q, legal)
    return action, q, drive


def quantization_error_bound(checkpoint):
    """Conservative real-arithmetic bound; separate finite-arithmetic tolerance."""
    w = np.abs(np.asarray(checkpoint["weights"]["w"], float))
    v = np.abs(np.asarray(checkpoint["weights"]["v"], float))
    scale = np.asarray(checkpoint["norm"]["scale"], float)
    lipschitz = np.sum(w/scale[:, None], axis=0)@v
    # One half ULP for each raw feature, prior score, and final score conversion.
    bound = (2.+lipschitz)/(2*SCALE)
    bound[0] = 0.
    return dict(per_action_absolute=bound.tolist(), maximum_absolute=float(bound.max()),
        formula="2^-25 * (2 + sum_j |v[j,a]| sum_i |w[i,j]|/scale[i])",
        assumptions="Real arithmetic, identical legal mask, no input or score-envelope rejection; tanh, ReLU and clip are 1-Lipschitz",
        finite_arithmetic_tolerance=2e-12,
        stable_argmax_condition="The original top-two legal Q gap exceeds twice the maximum bound plus finite-arithmetic tolerance")
