"""Artifact-backed text/image experiment boundary, never a model-quality claim.

Commands are supplied explicitly by the experiment owner, run without a shell,
and receive one JSON request on stdin. They must return one JSON object on stdout.
No command is discovered in prompts, generated artifacts, or dataset rows.
"""

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Protocol


ACTIONS = ("reason", "visual_repair", "cross_modal_check", "stop")
BASELINES = (
    "fixed", "greedy", "ordinary_router", "ndu_no_interaction",
    "ndu_no_preference", "ndu_no_risk", "ndu", "ndu_planning",
)
PROTOCOL = "hepta.ndu-portfolio.generation.v1"
MAX_WIRE_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def checked_number(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a finite nonnegative number")
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{name}: outside declared bounds")
    return float(value)


def checked_digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("expected lowercase SHA-256")
    return value


@dataclass(frozen=True)
class ModelBinding:
    model_id: str
    revision: str
    weights_sha256: str

    def __post_init__(self):
        if not self.model_id or not self.revision:
            raise ValueError("model identity and immutable revision are required")
        checked_digest(self.weights_sha256)


@dataclass(frozen=True)
class ActionLimit:
    compute_units: float
    timeout_seconds: float

    def __post_init__(self):
        if checked_number(self.compute_units, "compute units") <= 0:
            raise ValueError("positive reservation required")
        if not 0 < checked_number(self.timeout_seconds, "timeout") <= 60:
            raise ValueError("action timeout must be in (0, 60] seconds")


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    evidence_kind: str
    text_model: ModelBinding
    image_model: ModelBinding
    cost_unit: str
    limits: dict
    observer_id: str = ""

    def __post_init__(self):
        if not self.provider_id or not self.cost_unit:
            raise ValueError("provider and compute unit are required")
        if self.evidence_kind not in ("real", "synthetic_fixture"):
            raise ValueError("evidence kind must be explicit")
        if set(self.limits) != set(ACTIONS) - {"stop"}:
            raise ValueError("every generation action needs a resource reservation")
        if any(not isinstance(v, ActionLimit) for v in self.limits.values()):
            raise ValueError("invalid action limits")

    @property
    def sha256(self):
        return digest(asdict(self))


class JsonlCommand:
    """Explicit local command with a deadline and bounded accepted response size.

    stdout/stderr spool to temporary files, not unbounded process-memory buffers.
    The command is trusted experiment configuration; its OS-level resource limits
    and any descendants remain the responsibility of its runner/container.
    """

    def __init__(self, argv, cwd=None, response_limit=MAX_WIRE_BYTES):
        if not argv or not all(isinstance(x, str) and x for x in argv):
            raise ValueError("an explicit executable argv is required")
        if not 0 < response_limit <= MAX_WIRE_BYTES:
            raise ValueError("invalid response limit")
        self.argv = tuple(argv)
        self.cwd = None if cwd is None else str(Path(cwd).resolve())
        self.response_limit = response_limit

    def __call__(self, request, timeout_seconds):
        wire = json.dumps(request, allow_nan=False).encode() + b"\n"
        if len(wire) > MAX_WIRE_BYTES or not 0 < timeout_seconds <= 60:
            raise ValueError("request bytes or timeout exceed boundary")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            done = subprocess.run(self.argv, input=wire, stdout=out, stderr=err,
                                  cwd=self.cwd, timeout=timeout_seconds, check=False)
            if done.returncode:
                raise RuntimeError(f"provider exited with status {done.returncode}")
            if out.tell() > self.response_limit:
                raise ValueError("provider response exceeds byte limit")
            out.seek(0)
            lines = out.read().decode("utf-8").splitlines()
        if len(lines) != 1:
            raise ValueError("provider must emit exactly one JSONL response")
        value = json.loads(lines[0])
        if not isinstance(value, dict):
            raise ValueError("provider response must be an object")
        return value


class Provider(Protocol):
    manifest: ProviderManifest

    def generate(self, request: dict, timeout_seconds: float) -> dict:
        """Return a bound output and actual usage, even on observed failure."""


class SubprocessProvider:
    def __init__(self, manifest, argv, cwd=None):
        self.manifest = manifest
        self.command = JsonlCommand(argv, cwd)

    def generate(self, request, timeout_seconds):
        return self.command(request, timeout_seconds)


def verify_artifact(root, value):
    """Read bounded artifact bytes, verify their digest and actual modality."""
    if not isinstance(value, dict) or set(value) != {"path", "modality", "sha256"}:
        raise ValueError("invalid artifact record")
    relative = Path(value["path"])
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("artifact must be a file within the bound output directory")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds byte limit")
    data = path.read_bytes()
    if not data or sha256(data).hexdigest() != checked_digest(value["sha256"]):
        raise ValueError("empty or mismatched artifact")
    if value["modality"] == "text":
        if not data.decode("utf-8").strip():
            raise ValueError("empty text delivery")
    elif value["modality"] == "image":
        from PIL import Image
        with Image.open(path) as image:
            if image.width * image.height > 16_777_216:
                raise ValueError("image exceeds decoded pixel limit")
            image.verify()
    else:
        raise ValueError("phase 2 accepts only text/image artifacts")
    return {**value, "byte_size": len(data)}


@dataclass
class Session:
    provider: Provider
    artifact_root: Path
    task_id: str
    sample_id: str
    seed: int
    dataset_sha256: str
    objective_sha256: str
    budget_compute: float
    budget_seconds: float
    baseline: str
    clock: object = time.monotonic
    receipts: list = field(default_factory=list, init=False)
    artifacts: dict = field(default_factory=dict, init=False)
    spent_compute: float = field(default=0.0, init=False)
    spent_seconds: float = field(default=0.0, init=False)
    stopped: bool = field(default=False, init=False)
    evaluation_attempted: bool = field(default=False, init=False)
    evaluation_receipt: dict | None = field(default=None, init=False)

    def __post_init__(self):
        if not self.task_id or not self.sample_id or self.baseline not in BASELINES:
            raise ValueError("task, sample and registered baseline are required")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("an explicit nonnegative seed is required")
        checked_digest(self.dataset_sha256)
        checked_digest(self.objective_sha256)
        checked_number(self.budget_compute, "budget compute")
        checked_number(self.budget_seconds, "budget seconds")
        self.artifact_root = Path(self.artifact_root).resolve()
        self.manifest_digest = self.provider.manifest.sha256

    def step(self, action, controller_seconds=None, controller_compute=None,
             controller_usage_source="declared"):
        """Charge decisions, reserve dispatch, and retain every failure.

        Caller supplies controller usage including planning and its source. Missing
        or merely declared usage cannot qualify equal-resource evidence. Unknown
        provider usage consumes its reservation; an observed overrun retains its
        full actual cost. Failed/late outputs never replace active artifacts.
        """
        if self.stopped or self.evaluation_attempted:
            raise ValueError("session already stopped or evaluated")
        if controller_usage_source not in ("measured", "declared"):
            raise ValueError("controller usage source must be measured or declared")
        controller_known = controller_seconds is not None and controller_compute is not None
        cs = 0.0 if controller_seconds is None else checked_number(controller_seconds, "controller seconds")
        cc = 0.0 if controller_compute is None else checked_number(controller_compute, "controller compute")
        self.spent_seconds += cs
        self.spent_compute += cc
        receipt = {"action": action, "controller_seconds": cs, "controller_compute": cc,
                   "controller_usage_source": controller_usage_source if controller_known else "unavailable",
                   "provider_seconds": 0.0, "provider_compute": 0.0, "provider_reservation_exceeded": False,
                   "usage_known": True, "status": "rejected", "reason": ""}
        if self.provider.manifest.sha256 != self.manifest_digest:
            receipt["reason"] = "frozen_provider_manifest_changed"
        elif self.spent_seconds > self.budget_seconds or self.spent_compute > self.budget_compute:
            receipt["reason"] = "controller_budget_exhausted"
        elif action not in ACTIONS:
            receipt["reason"] = "invalid_action"
        elif action == "stop":
            self.stopped = True
            receipt.update(status="stopped", reason="" if set(self.artifacts) == {"text", "image"}
                           else "missing_required_delivery")
        else:
            limit = self.provider.manifest.limits[action]
            remaining_seconds = self.budget_seconds - self.spent_seconds
            if limit.compute_units > self.budget_compute - self.spent_compute or remaining_seconds <= 0:
                receipt["reason"] = "insufficient_dispatch_reservation"
            else:
                request = {"protocol": PROTOCOL, "manifest_sha256": self.manifest_digest,
                           "task_id": self.task_id, "sample_id": self.sample_id, "seed": self.seed,
                           "dataset_sha256": self.dataset_sha256,
                           "objective_sha256": self.objective_sha256, "action": action,
                           "sequence": len(self.receipts), "previous_artifacts": self.artifacts,
                           "max_compute_units": limit.compute_units,
                           "output_directory": str(self.artifact_root)}
                request["request_sha256"] = digest(request)
                receipt["request_sha256"] = request["request_sha256"]
                start = self.clock()
                actual_compute = None
                outputs = []
                timeout = min(limit.timeout_seconds, remaining_seconds)
                try:
                    response = self.provider.generate(request, timeout)
                    if not isinstance(response, dict):
                        raise ValueError("provider response must be an object")
                    for key in ("request_sha256", "manifest_sha256"):
                        if response.get(key) != request[key]:
                            raise ValueError(f"response {key} mismatch")
                    actual_compute = checked_number(response["compute_units"], "provider compute")
                    receipt["provider_compute"] = actual_compute
                    if actual_compute > limit.compute_units:
                        receipt["provider_reservation_exceeded"] = True
                        raise ValueError("provider_reservation_exceeded")
                    if response.get("status") not in ("succeeded", "failed"):
                        raise ValueError("missing terminal provider status")
                    values = response.get("artifacts", [])
                    if not isinstance(values, list) or len(values) > 2:
                        raise ValueError("invalid output list")
                    outputs = [verify_artifact(self.artifact_root, item) for item in values]
                    if len({item["modality"] for item in outputs}) != len(outputs):
                        raise ValueError("duplicate modality in response")
                    receipt["status"] = response["status"]
                    if response["status"] == "failed":
                        receipt["reason"] = "provider_reported_failure"
                except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
                    overrun = actual_compute is not None and actual_compute > limit.compute_units
                    receipt.update(status="failed", reason="provider_reservation_exceeded" if overrun else type(error).__name__,
                                   usage_known=actual_compute is not None,
                                   provider_compute=actual_compute if actual_compute is not None else limit.compute_units)
                finally:
                    elapsed = self.clock() - start
                    if not math.isfinite(elapsed) or elapsed < 0:
                        raise ValueError("clock must be finite and monotonic")
                    receipt["provider_seconds"] = elapsed
                    self.spent_seconds += elapsed
                    self.spent_compute += receipt["provider_compute"]
                if self.spent_seconds > self.budget_seconds:
                    receipt.update(status="failed", reason="deadline_exceeded")
                elif elapsed > timeout:
                    receipt.update(status="failed", reason="action_deadline_exceeded")
                if receipt["status"] == "succeeded":
                    self.artifacts.update({item["modality"]: item for item in outputs})
        receipt["total_compute"] = self.spent_compute
        receipt["total_seconds"] = self.spent_seconds
        self.receipts.append(receipt)
        return receipt.copy()

    def evidence(self):
        reasons = []
        if self.provider.manifest.sha256 != self.manifest_digest:
            reasons.append("frozen_provider_manifest_changed")
        if self.provider.manifest.evidence_kind != "real":
            reasons.append("synthetic_fixture_not_generation_evidence")
        else:
            reasons.append("real_backend_execution_provenance_unverified")
        if not self.stopped:
            reasons.append("no_observed_stop")
        if set(self.artifacts) != {"text", "image"}:
            reasons.append("missing_required_delivery")
        if any(not item["usage_known"] for item in self.receipts):
            reasons.append("unknown_usage_on_attempt")
        if any(item["controller_usage_source"] != "measured" for item in self.receipts):
            reasons.append("controller_usage_not_measured")
        if any(item["provider_reservation_exceeded"] for item in self.receipts):
            reasons.append("provider_reservation_exceeded")
        if self.spent_compute > self.budget_compute or self.spent_seconds > self.budget_seconds:
            reasons.append("total_budget_exceeded")
        return {"status": "HOLD" if reasons else "READY_FOR_INDEPENDENT_EVALUATION",
                "reasons": reasons, "evidence_kind": self.provider.manifest.evidence_kind,
                "execution_provenance": "DECLARED_UNVERIFIED",
                "controller_metering_provenance": "CALLER_REPORTED",
                "evaluation_attempted": self.evaluation_attempted,
                "evaluation_receipt": self.evaluation_receipt,
                "manifest_sha256": self.manifest_digest, "task_id": self.task_id,
                "sample_id": self.sample_id, "seed": self.seed, "baseline": self.baseline,
                "dataset_sha256": self.dataset_sha256, "objective_sha256": self.objective_sha256,
                "budget_compute": self.budget_compute, "budget_seconds": self.budget_seconds,
                "total_compute": self.spent_compute, "total_seconds": self.spent_seconds,
                "artifacts": self.artifacts.copy(), "receipts": list(self.receipts)}


class SyntheticFixtureProvider:
    """Small rendered files exercise transport only, never real model quality."""

    def __init__(self):
        binding = ModelBinding("synthetic-fixture", "v1", digest("fixture-only"))
        self.manifest = ProviderManifest("synthetic-fixture", "synthetic_fixture", binding, binding,
                                         "fixture_units", {x: ActionLimit(2.0, 5.0) for x in ACTIONS[:-1]})

    def generate(self, request, timeout_seconds):
        root = Path(request["output_directory"])
        root.mkdir(parents=True, exist_ok=True)
        outputs = []
        action = request["action"]
        if action == "reason":
            path = root / f"{request['sequence']}.txt"
            path.write_text("SYNTHETIC FIXTURE: a blue square, not model-generated evidence.\n")
            outputs.append({"path": path.name, "modality": "text", "sha256": sha256(path.read_bytes()).hexdigest()})
        elif action == "visual_repair":
            from PIL import Image
            path = root / f"{request['sequence']}.png"
            Image.new("RGB", (8, 8), "blue").save(path)
            outputs.append({"path": path.name, "modality": "image", "sha256": sha256(path.read_bytes()).hexdigest()})
        return {"request_sha256": request["request_sha256"], "manifest_sha256": request["manifest_sha256"],
                "status": "succeeded", "compute_units": 1.0, "artifacts": outputs}


def fixture_smoke(output_directory):
    """Reproducible fixture transport run. Its evidence status is always HOLD."""
    session = Session(SyntheticFixtureProvider(), Path(output_directory), "fixture-task", "fixture-sample", 0,
                      digest("synthetic-dataset-v1"), digest("synthetic-objective-v1"),
                      10.0, 30.0, "fixed")
    for action in ("reason", "visual_repair", "cross_modal_check", "stop"):
        session.step(action, controller_seconds=0.0, controller_compute=0.0)
    return session.evidence()
