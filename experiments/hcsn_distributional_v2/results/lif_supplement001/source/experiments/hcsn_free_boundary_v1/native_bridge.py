"""Four causal continuous channels consumed by the unchanged native owner/NDU.

The maxout profile assigns all four signals to potentially winning native
coordinates with nonzero action-head weights. It is a declared engineering
controller, not a learned financial policy or a native tensor HCSN kernel.
"""

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from .restore_native import VENDOR, restore


MANIFEST = json.loads((VENDOR / "MANIFEST.json").read_text())
if hashlib.sha256((VENDOR / "adapter.py").read_bytes()).hexdigest() != MANIFEST["adapter_sha256"]:
    raise RuntimeError("The original native adapter changed")
_SPEC = importlib.util.spec_from_file_location("hcsn_native_upstream", VENDOR / "adapter.py")
UPSTREAM = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(UPSTREAM)
POLICIES = ("causal_maxout", "ordinary_affine", "continuation_only")
OBJECTIVE = {"name": "paid-prefix-classification-v1", "correct_reward": 1.0,
             "cost": "all executed reads including first", "terminal": "STOP or horizon"}


@dataclass(frozen=True)
class Signals:
    continuation: float
    margin: float
    risk: float
    activity: float

    def packet(self):
        values = asdict(self)
        if not all(math.isfinite(float(x)) for x in values.values()):
            raise ValueError("Nonfinite continuous signal")
        if not (-1 <= self.continuation <= 1 and -1 <= self.margin <= 1
                and 0 <= self.risk <= 1 and 0 <= self.activity <= 1):
            raise ValueError("Declared signal normalization domain exceeded")
        return UPSTREAM.features([self.continuation], margin=self.margin,
                                 risk=self.risk, flow=self.activity)


def profile(policy, model_digest, maximum_ticks=512):
    """Frozen policies all receive exactly the same four scalar inputs.

    Ordinary affine is a simple same-information control, with coefficients
    fixed before evaluation. Continuation-only is explicitly an ablation.
    """
    if policy not in POLICIES:
        raise ValueError("Unknown native controller")
    if policy == "causal_maxout":
        encoder = [[1, 0, 0, 0], [-1, 0, 0, 0], [0, 1, 0, 0],
                   [0, 0, 1, 0], [0, 0, 0, 1]]
        bias = [0.5, 0.5, 0.5, 0, 0]
        head = [1, -1, 1, -1, 1]
        keep_bias = -0.55
    else:
        weights = [1, 0.35, -0.75, 0.25] if policy == "ordinary_affine" else [1, 0, 0, 0]
        encoder = [weights, [-x for x in weights], [0, 0.1, 0, 0],
                   [0, 0, 0.1, 0], [0, 0, 0, 0.1]]
        bias = [-0.05, 0.05, -4, -4, -4]
        head, keep_bias = [1, -1, 0, 0, 0], 0
    kernel = {"width": 5, "top_k": 1, "temporal_decay_q24": 0,
              "activity_decay_q24": 0, "target_activity_q24": 0,
              "threshold_rate_q24": 0, "threshold_min_q24": 0,
              "threshold_max_q24": 0, "eligibility_decay_q24": 0}
    return UPSTREAM.make_profile(
        ["normalized_continuation"], encoder, bias,
        [head, [0] * 5, [0] * 5], [keep_bias, -8, 0],
        source_model_digest=model_digest, objective_digest=UPSTREAM.digest(OBJECTIVE),
        arm_id=policy, kernel=kernel, maximum_ticks=maximum_ticks)


def file_hashes(directory):
    directory = Path(directory)
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


class NativeSession:
    """Exact executable, immutable policy, real durable owner, actual actions."""

    def __init__(self, root, *, binary, policy, model_digest, case, seed, resume=False):
        self.root, self.case, self.seed = Path(root), case, seed
        self.policy = policy
        self.profile = profile(policy, model_digest)
        path, self.profile_digest = UPSTREAM.save_profile(self.root / "profiles", self.profile)
        self.bridge = UPSTREAM.NativeBridge(binary, self.root,
                                           expected_binary_sha256=MANIFEST["binary_sha256"])
        identity = self.bridge.identity
        if (identity["source_commit"] != MANIFEST["native_base_commit"] or
                identity["source_manifest_digest"] != MANIFEST["source_manifest_sha256"] or
                identity["owner_authority"] != "DENY_ALL"):
            self.bridge.close()
            raise ValueError("Original native identity or authority mismatch")
        self.bridge.load_profile(path, self.profile_digest)
        self.open_receipt = self.bridge.open(case, seed, self.profile_digest, resume=resume)
        self.terminal = bool(self.open_receipt["status"]["terminal"])
        self.events = []

    def tick(self, signals, *, context=None):
        if self.terminal:
            raise RuntimeError("Task already stopped; no further observation")
        packet = signals.packet()
        before = dict(self.bridge.current)
        evidence = UPSTREAM.digest({"signals": asdict(signals), "context": context})
        event_id = f"{self.case}.event.{before['step'] + 1}"
        result = self.bridge.tick(packet, evidence_digest=evidence, event_id=event_id)
        if result["owner_authority"] != "DENY_ALL" or result["native_abstain"]:
            raise RuntimeError("Unexpected native authority or calibration fallback")
        if result["effective_action"] not in {"keep", "stop"}:
            raise RuntimeError("Unexpected native action")
        self.terminal = result["effective_action"] == "stop"
        row = {"signals": asdict(signals), "context": context, "native": result}
        self.events.append(row)
        self.last_request = {"command": "Tick", "observation": {
            "event_id": event_id, "step": before["step"] + 1,
            "checkpoint": before["checkpoint"], "features": packet,
            "evidence_digest": evidence}}
        return row

    def verify_retry(self):
        before = self.bridge.rpc({"command": "Status"})
        kernels = self.bridge.counters["actual_kernel_calls"]
        result = self.bridge.rpc(self.last_request)
        after = self.bridge.rpc({"command": "Status"})
        if (before != after or self.bridge.counters["actual_kernel_calls"] != kernels
                or not result["duplicate_event_ignored"]):
            raise RuntimeError("Exact retry changed the native frontier")
        return {"passed": True, "status": after, "duplicate": result}

    def verify_terminal(self):
        if not self.terminal:
            raise ValueError("A terminal guard probe requires native STOP")
        before = self.bridge.rpc({"command": "Status"})
        request = {"command": "Tick", "observation": {
            "event_id": f"{self.case}.forbidden", "step": before["step"] + 1,
            "checkpoint": before["checkpoint"],
            "features": Signals(0.9, 0.9, 0.1, 0.9).packet(),
            "evidence_digest": UPSTREAM.digest("intentional-post-stop-probe")}}
        rejection = self.bridge.rpc(request, allow_error=True)
        after = self.bridge.rpc({"command": "Status"})
        if rejection.get("ok", True) or before != after or "Terminal episode" not in rejection["error"]:
            raise RuntimeError("Native terminal guard failed")
        return {"passed": True, "before": before, "after": after, "rejection": rejection}

    def close(self):
        return self.bridge.close()


def restored_binary(destination="/tmp/hcsn-free-boundary-native/continuous_host"):
    return restore(destination)[0]
