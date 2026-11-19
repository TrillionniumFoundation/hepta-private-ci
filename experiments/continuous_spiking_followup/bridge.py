"""Pinned #4157 native owner consumer for continuous policy values.

The original Rust sparse kernel and NDU select every returned action. This is
a deterministic value-to-action compilation, not a newly learned sparse head.
The tensor HCSN retains its own recurrence; native transport adds no recurrence.
"""

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
import types


NATIVE_BASE = "5898cd8b0f724c3152b6cc52856721f72e5e08be"
NATIVE_WRAPPER = "7bec42aa4f79432f4a724d5295c67f9d69ee5a8d"
NATIVE_BINARY_SHA256 = (
    "1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5"
)
NATIVE_SOURCE_MANIFEST_SHA256 = (
    "6addea031fa9ba2ca403137d8d10da6088c255474c681b106d9a2706c645dd09"
)
ADAPTER_SHA256 = "2a7be4914211a5166fc8ef7fbbf6a2de8632b2e7651c7175d6e3888ddbb1ec0c"
Q = 1 << 24
SCORE_KINDS = {"value_model_advantage", "threshold_confidence_advantage"}


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _identity(value, name):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value == "0" * 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{name} must be a nonzero lowercase SHA-256")
    return value


@lru_cache(maxsize=1)
def _upstream_adapter():
    path = Path(__file__).with_name("native_reference.py")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ADAPTER_SHA256:
        raise ValueError("pinned upstream native adapter identity mismatch")
    module = types.ModuleType("hcsn_verified_native_reference")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def make_profile(
    model_sha256,
    objective_sha256,
    arm_id,
    score_kind,
    maximum_ticks=512,
    *,
    policy_sha256=None,
):
    """Compile signed values without altering the upstream owner or NDU.

    Five native coordinates preserve signed decision score, natural margin,
    task risk and interval activity. The original 20% activity cap permits one
    winner. The two signed score coordinates cannot both be positive. Auxiliary
    coordinates are nonpositive, so they enter native temporal state without
    displacing the score. Their independent causal utility is not established.
    """
    _identity(model_sha256, "model identity")
    _identity(objective_sha256, "objective identity")
    if policy_sha256 is not None:
        _identity(policy_sha256, "policy identity")
    if type(maximum_ticks) is not int or not 1 <= maximum_ticks <= 512:
        raise ValueError("native owner supports 1..512 ticks")
    if not isinstance(arm_id, str) or not arm_id:
        raise ValueError("arm identity is required")
    if score_kind not in SCORE_KINDS:
        raise ValueError("undeclared decision score semantics")
    upstream = _upstream_adapter()
    # Raw decision score, then typed natural margin/risk/flow. All five
    # coordinates consume inputs; no zero padding or sparse-ratio exception.
    encoder = [
        [1, 0, 0, 0],
        [-1, 0, 0, 0],
        [0, 0.5, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]
    kernel = {
        "width": 5,
        "top_k": 1,
        "temporal_decay_q24": 0,
        "activity_decay_q24": 0,
        "target_activity_q24": 0,
        "threshold_rate_q24": 0,
        "threshold_min_q24": 0,
        "threshold_max_q24": 0,
        "eligibility_decay_q24": 0,
    }
    return upstream.make_profile(
        [score_kind],
        encoder,
        [0, 0, -4, -1, -1],
        [[1, -1, 0, 0, 0], [0] * 5, [0] * 5],
        [0, -8, 0],
        source_model_digest=model_sha256
        if policy_sha256 is None
        else _digest(
            {
                "neural_model_sha256": model_sha256,
                "policy_sha256": policy_sha256,
            }
        ),
        objective_digest=objective_sha256,
        arm_id=arm_id,
        kernel=kernel,
        maximum_ticks=maximum_ticks,
    )


def signals(
    continue_score,
    *,
    score_kind,
    natural_margin,
    task_risk,
    activity,
    continuation_value=None,
    stopping_value=None,
    forced_terminal=False,
):
    """Keep task risk, natural margin and interval event probability distinct.

    Values/margin are bounded by the native Q24 domain [-8,8]. The caller must
    declare any normalization; this function never silently clips observations.
    Task risk is an estimate, not a calibration or safety certificate.
    """
    if not math.isfinite(float(activity)) or not 0 <= float(activity) <= 1:
        raise ValueError("activity must be an interval event probability")
    if score_kind not in SCORE_KINDS:
        raise ValueError("undeclared decision score semantics")
    if type(forced_terminal) is not bool:
        raise ValueError("terminal constraint must be explicit")
    if forced_terminal:
        if float(continue_score) != -1.0 or continuation_value is not None:
            raise ValueError(
                "terminal constraint requires score -1 and no continuation value"
            )
        if score_kind == "value_model_advantage":
            if (
                stopping_value is None
                or not math.isfinite(float(stopping_value))
                or abs(float(stopping_value)) > 8
            ):
                raise ValueError(
                    "terminal value policy requires its genuine stopping value"
                )
        elif stopping_value is not None:
            raise ValueError("threshold scores are not task values")
    elif score_kind == "value_model_advantage":
        if continuation_value is None or stopping_value is None:
            raise ValueError(
                "value scores require separate continuation and stopping values"
            )
        values = [float(continuation_value), float(stopping_value)]
        if not all(math.isfinite(v) and abs(v) <= 8 for v in values):
            raise ValueError("invalid task values")
        if not math.isclose(
            float(continue_score), values[0] - values[1], abs_tol=1e-12, rel_tol=1e-12
        ):
            raise ValueError(
                "decision score does not equal the declared task-value advantage"
            )
    elif continuation_value is not None or stopping_value is not None:
        raise ValueError("threshold scores are not task continuation values")
    payload = _upstream_adapter().features(
        [continue_score],
        margin=natural_margin,
        risk=task_risk,
        flow=activity,
    )
    return {
        "features": payload,
        "semantics": {
            "continue_score": float(continue_score),
            "score_kind": score_kind,
            "natural_margin": float(natural_margin),
            "task_risk": float(task_risk),
            "activity": float(activity),
            "continuation_value": None
            if continuation_value is None
            else float(continuation_value),
            "stopping_value": None if stopping_value is None else float(stopping_value),
            "forced_terminal": forced_terminal,
        },
    }


class NativeClient:
    """One actual native process with a version-bound durable owner directory.

    Call open(..., resume=True) in a new client to cold-recover the native state.
    The caller separately restores the model stream and complete task state,
    then checks verify_binding before the next observation. No Python action
    is substituted when the native output disagrees with an expectation.
    """

    def __init__(
        self,
        binary,
        root,
        *,
        model_sha256,
        objective_sha256,
        arm_id,
        score_kind,
        maximum_ticks=512,
        policy_sha256=None,
    ):
        self.model_sha256 = _identity(model_sha256, "model identity")
        self.objective_sha256 = _identity(objective_sha256, "objective identity")
        self.score_kind = score_kind
        self.policy_sha256 = policy_sha256
        self.profile = make_profile(
            model_sha256,
            objective_sha256,
            arm_id,
            score_kind,
            maximum_ticks,
            policy_sha256=policy_sha256,
        )
        upstream = _upstream_adapter()
        self.native = upstream.NativeBridge(
            binary, root, expected_binary_sha256=NATIVE_BINARY_SHA256
        )
        identity = self.native.identity
        if (
            identity.get("source_commit") != NATIVE_BASE
            or identity.get("source_manifest_digest") != NATIVE_SOURCE_MANIFEST_SHA256
            or identity.get("owner_authority") != "DENY_ALL"
        ):
            self.native.close()
            raise ValueError("native source or authority identity mismatch")
        try:
            self.profile_path, self.profile_sha256 = upstream.save_profile(
                Path(root) / "profiles", self.profile
            )
            self.native.load_profile(self.profile_path, self.profile_sha256)
        except Exception:
            self.native.close()
            raise
        self.last_request = None

    @property
    def process_id(self):
        return self.native.process.pid

    def open(self, case_id, seed, *, resume=False):
        if type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError("seed must be a native unsigned 64-bit integer")
        return self.native.open(case_id, seed, self.profile_sha256, resume=resume)

    def tick(self, values, *, evidence_digest, event_id=None):
        _identity(evidence_digest, "causal evidence identity")
        if (
            set(values) != {"features", "semantics"}
            or values != signals(**values["semantics"])
            or values["semantics"]["score_kind"] != self.score_kind
        ):
            raise ValueError("signal packet or score semantics mismatch")
        current = self.native.current
        if current is None:
            raise ValueError("open a native owner before ticking")
        step = current["step"] + 1
        event_id = event_id or f"{current['case']}.event.{step}"
        request = {
            "command": "Tick",
            "observation": {
                "event_id": event_id,
                "step": step,
                "checkpoint": current["checkpoint"],
                "features": values["features"],
                "evidence_digest": _digest(
                    {"causal_source": evidence_digest, "signal_packet": values}
                ),
            },
        }
        result = self.native.rpc(request)
        current.update(step=result["step"], checkpoint=result["checkpoint_after"])
        self.last_request = request
        return result

    def status(self):
        return self.native.rpc({"command": "Status"})

    def binding(self):
        """Return the native frontier to bind into the caller's task checkpoint."""
        return {
            "model_sha256": self.model_sha256,
            "objective_sha256": self.objective_sha256,
            "profile_sha256": self.profile_sha256,
            "binary_sha256": NATIVE_BINARY_SHA256,
            "score_kind": self.score_kind,
            "policy_sha256": self.policy_sha256,
            "status": self.status(),
        }

    def verify_binding(self, expected):
        actual = self.binding()
        if actual != expected:
            raise ValueError("native/model/task checkpoint frontier mismatch")
        return actual

    def close(self):
        return self.native.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
