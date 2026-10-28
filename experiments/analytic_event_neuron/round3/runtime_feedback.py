"""Count-only feedback receiver and the original typed native prediction head.

Adapter state and native state are separate owners. Interrupted joint commits
fail closed; no claim of a cross-owner atomic transaction or production grant.
"""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

from ..analytic import event_probs
from ..runtime import _atomic, _lock
from ..round2.pulse import EventDecoder, PulseConfig, SignedEventNeuron
from .feedback import digest, STEP


ZERO = "0" * 64
SCHEMA = "hepta.feedback-count-owner.v3"


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    envelope = json.loads(Path(path).read_text())
    if set(envelope) != {"document", "sha256"} or digest(envelope["document"]) != envelope["sha256"]:
        raise ValueError("Corrupt feedback owner envelope")
    return envelope["document"]


def _write(path, document):
    _atomic(Path(path), {"document": document, "sha256": digest(document)})


class FeedbackOwner:
    def __init__(self, root, identity, model_sha256, native, mode="error_feedback"):
        if mode not in ("error_feedback", "direct_quantization") or len(model_sha256) != 64:
            raise ValueError("Frozen model binding and declared count coding required")
        self.config = PulseConfig(STEP, STEP, mode)
        self.subject = digest([SCHEMA, identity, model_sha256, asdict(self.config)])
        self.root = Path(root) / self.subject
        self.root.mkdir(parents=True, exist_ok=True)
        self.native, self.model_sha256 = native, model_sha256

    def step(self, public, mean, variance, sequence, *, expected_checkpoint=ZERO, fail_stage=None):
        started = time.perf_counter_ns()
        if (type(sequence) is not int or not 1 <= sequence <= 16 or not math.isfinite(mean)
                or not math.isfinite(variance) or variance <= 0 or abs(mean) > 8 or variance > 8
                or fail_stage not in (None, "after_pending", "after_native", "after_commit")):
            raise ValueError("Outside bounded registered feedback runtime domain")
        if set(public) != {"initial", "residuals", "variances", "repair_cost", "wait_cost", "wait_variance"}:
            raise ValueError("Only declared public feedback inputs accepted")
        if (not isinstance(public["residuals"], list) or not isinstance(public["variances"], list)
                or not 1 <= len(public["residuals"]) <= 2 or len(public["residuals"]) != len(public["variances"])
                or not math.isfinite(public["initial"]) or not all(math.isfinite(x) for x in public["residuals"])
                or not all(math.isfinite(x) and x > 0 for x in public["variances"])
                or not all(math.isfinite(public[k]) and public[k] > 0 for k in ("repair_cost", "wait_cost", "wait_variance"))):
            raise ValueError("Finite acquired observations and positive public variances/costs required")
        timestamp = float(len(public["residuals"]))
        request = {"schema": SCHEMA, "subject": self.subject, "model_sha256": self.model_sha256,
                   "public_sha256": digest(public), "source_sha256": digest([mean, variance]),
                   "sequence": sequence, "time": timestamp}
        request_sha = digest(request)
        state_path, witness_path, pending_path = [self.root / name for name in
            ("state.json", "delivery.witness.json", "pending.json")]
        with _lock(self.root / "owner.lock"):
            state = _read(state_path) if state_path.exists() else {
                "schema": SCHEMA, "subject": self.subject, "sequence": 0, "checkpoint": ZERO,
                "native_checkpoint": ZERO, "encoder": SignedEventNeuron(self.config).snapshot(),
                "decoder": EventDecoder(self.config).snapshot(), "receipts": []}
            witness = _read(witness_path) if witness_path.exists() else {"subject": self.subject, "records": []}
            if state["subject"] != self.subject or witness["subject"] != self.subject:
                raise ValueError("Owner identity mismatch")
            if len(witness["records"]) != state["sequence"] or len(state["receipts"]) != state["sequence"]:
                raise ValueError("State/witness length mismatch")
            if witness["records"] and (witness["records"][-1]["state_sha256"] != digest(state)
                    or witness["records"][-1]["checkpoint"] != state["checkpoint"]):
                raise ValueError("Independent witness rejects state rollback")
            predecessor = ZERO
            for index, item in enumerate(witness["records"], 1):
                if item["sequence"] != index or item["predecessor"] != predecessor:
                    raise ValueError("Witness ancestry failure")
                predecessor = item["checkpoint"]
            if sequence <= state["sequence"]:
                saved = state["receipts"][sequence - 1]
                if saved["request_sha256"] != request_sha:
                    raise ValueError("Duplicate sequence changed public evidence")
                return saved
            if pending_path.exists():
                raise RuntimeError("Partial native/adapter commit requires reconciliation")
            if sequence != state["sequence"] + 1 or state["checkpoint"] != expected_checkpoint:
                raise ValueError("Stale checkpoint or sequence gap")
            encoder, decoder = SignedEventNeuron.restore(state["encoder"]), EventDecoder.restore(state["decoder"])
            if encoder.decoder.snapshot() != decoder.snapshot() or decoder.config != self.config:
                raise ValueError("Encoder/decoder ancestry mismatch")
            packet = encoder.update(mean, variance, timestamp,
                "propagation" if decoder.time == timestamp else "observed")
            decoder.apply(packet)
            _write(pending_path, {"request_sha256": request_sha, "decoder": decoder.snapshot(), "packet": packet})
            if fail_stage == "after_pending":
                raise RuntimeError("Injected interruption after pending")
            reopened = _read(pending_path)
            decoded_mean, decoded_variance = EventDecoder.restore(reopened["decoder"]).readout()
            threshold = math.sqrt(public["repair_cost"])
            native = self.native.typed(self.subject, self.root / "native", decoded_mean, decoded_variance,
                -threshold, threshold, expected_checkpoint=state["native_checkpoint"])
            _write(pending_path, {**reopened, "native": native})
            if fail_stage == "after_native":
                raise RuntimeError("Injected interruption after native")
            if native["sequence"] != sequence:
                raise RuntimeError("Native sequence mismatch")
            parameters = native["head"]["parameters_q24_decoded"]
            law = {"mean": parameters[0], "variance": parameters[1],
                   "probabilities": native["head"]["probabilities_q24"], "native_quantized": True}
            law["probabilities"] = [x / (1 << 24) for x in law["probabilities"]]
            after = digest([state["checkpoint"], request_sha, decoder.snapshot(), native["checkpoint_after"], law])
            receipt = {**request, "request_sha256": request_sha, "public": public,
                "source_forecast": [mean, variance], "packet": packet, "decoder": reopened["decoder"],
                "law": law, "native": native, "checkpoint_before": state["checkpoint"], "checkpoint_after": after,
                "logical_unit_events": sum(abs(x) for x in packet["counts"]),
                "packet_bytes": len(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()),
                "native_cdf_error": max(abs(a - b) for a, b in zip(native["head"]["probabilities"], event_probs(*parameters))),
                "receiver_reopened_before_native": True, "encoder_residual_used_by_policy": False,
                "cross_owner_atomicity": False, "authority": "DENY_ALL",
                "compute_ns_before_commit": time.perf_counter_ns() - started}
            state.update(sequence=sequence, checkpoint=after, native_checkpoint=native["checkpoint_after"],
                         encoder=encoder.snapshot(), decoder=reopened["decoder"])
            state["receipts"].append(receipt)
            witness["records"].append({"sequence": sequence, "predecessor": receipt["checkpoint_before"],
                "checkpoint": after, "state_sha256": digest(state), "law_sha256": digest(law)})
            _write(witness_path, witness)
            _write(state_path, state)
            pending_path.unlink()
            if fail_stage == "after_commit":
                raise RuntimeError("Injected lost acknowledgement")
            return receipt
