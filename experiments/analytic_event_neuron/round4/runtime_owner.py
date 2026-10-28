"""Matched durable receiver, actual per-component native heads, and release."""

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import time

from ..analytic import event_probs, quantize_simplex
from ..runtime import _atomic, _lock, digest
from .runtime_codec import Decoder, Encoder, MODES
from .runtime_law import Q24, make_law, positive_q24, release_law, validate_law


SCHEMA = "hepta.packed-mixture-owner.v4"
ZERO = "0" * 64


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_document(path):
    item = json.loads(Path(path).read_text())
    if set(item) != {"document", "sha256"} or digest(item["document"]) != item["sha256"]:
        raise ValueError("Invalid durable document digest")
    return item["document"]


def write_document(path, item):
    _atomic(Path(path), {"document": item, "sha256": digest(item)})


def validate_public(public):
    if set(public) != {"initial", "residuals", "variances", "repair_cost", "wait_cost", "wait_variance"}:
        raise ValueError("Only declared target-free acquired fields accepted")
    if (not isinstance(public["residuals"], list) or not isinstance(public["variances"], list)
            or not 1 <= len(public["residuals"]) <= 2 or len(public["residuals"]) != len(public["variances"])
            or not math.isfinite(public["initial"]) or not all(math.isfinite(v) for v in public["residuals"])
            or not all(math.isfinite(v) and v > 0 for v in public["variances"])
            or not all(math.isfinite(public[k]) and public[k] > 0 for k in ("repair_cost", "wait_cost", "wait_variance"))):
        raise ValueError("Finite acquired observations and positive public costs required")


class Owner:
    """Local advisory-lock owner, with native transactions explicitly separate."""
    def __init__(self, root, identity, model_sha256, native, mode="event"):
        if mode not in MODES or len(model_sha256) != 64 or any(c not in "0123456789abcdef" for c in model_sha256):
            raise ValueError("Explicit profile and SHA256 model binding required")
        self.subject = digest([SCHEMA, identity, model_sha256, mode])
        self.root = Path(root) / self.subject
        self.root.mkdir(parents=True, exist_ok=True)
        self.native, self.mode, self.model_sha256 = native, mode, model_sha256

    def step(self, public, law, sequence, *, expected_checkpoint=ZERO, fail_stage=None):
        started = time.perf_counter_ns()
        validate_public(public)
        validate_law(law)
        if type(sequence) is not int or not 1 <= sequence <= 16 or fail_stage not in (None, "after_packet", "after_first_native", "after_native", "after_commit"):
            raise ValueError("Bounded sequence and declared interruption stage required")
        timestamp = float(len(public["residuals"]))
        request = {"schema": SCHEMA, "subject": self.subject, "model_sha256": self.model_sha256,
                   "public_sha256": digest(public), "source_sha256": digest(law), "sequence": sequence, "time": timestamp}
        request_sha = digest(request)
        state_path, witness_path, pending_path = [self.root / name for name in ("state.json", "witness.json", "pending.json")]
        with _lock(self.root / "owner.lock"):
            state = read_document(state_path) if state_path.exists() else {
                "schema": SCHEMA, "subject": self.subject, "sequence": 0, "checkpoint": ZERO,
                "native_checkpoints": [ZERO] * len(law["weights"]), "decoder": Decoder(self.mode).snapshot(), "receipts": []}
            witness = read_document(witness_path) if witness_path.exists() else {"subject": self.subject, "records": []}
            if (state["subject"] != self.subject or witness["subject"] != self.subject
                    or len(state["receipts"]) != state["sequence"] or len(witness["records"]) != state["sequence"]):
                raise ValueError("Owner ancestry length or identity mismatch")
            previous = ZERO
            for i, row in enumerate(witness["records"], 1):
                if row["sequence"] != i or row["before"] != previous:
                    raise ValueError("Witness ancestry mismatch")
                previous = row["after"]
            if witness["records"] and (previous != state["checkpoint"] or witness["records"][-1]["state_sha256"] != digest(state)):
                raise ValueError("Independent local witness rejects state rollback/corruption")
            if sequence <= state["sequence"]:
                saved = state["receipts"][sequence - 1]
                if saved["request_sha256"] != request_sha:
                    raise ValueError("Changed duplicate request")
                return saved
            if pending_path.exists():
                raise RuntimeError("Partial native/adapter transaction requires reconciliation")
            if sequence != state["sequence"] + 1 or expected_checkpoint != state["checkpoint"]:
                raise ValueError("Stale checkpoint or skipped sequence")
            encoder = Encoder(self.mode, state["decoder"])
            kind = "propagation" if state["decoder"]["time"] == timestamp else "observed"
            packet = encoder.encode(law, sequence, timestamp, kind)
            packet_path = self.root / f"packet-{sequence}.bin"
            encoded = time.perf_counter_ns()
            write_document(pending_path, {"request_sha256": request_sha, "packet_sha256": hashlib.sha256(packet).hexdigest(), "native": []})
            with packet_path.open("xb") as stream:
                stream.write(packet)
                stream.flush()
                os.fsync(stream.fileno())
            reopened = packet_path.read_bytes()
            if reopened != packet:
                raise ValueError("Packed frame changed during actual readback")
            decoder = Decoder.restore(state["decoder"])
            decoded = decoder.apply(reopened)
            readback = time.perf_counter_ns()
            if fail_stage == "after_packet":
                raise RuntimeError("Injected interruption after frame persistence")
            cutoff = math.sqrt(public["repair_cost"])
            native_rows = []
            for component, (mean, variance) in enumerate(zip(decoded["means"], decoded["variances"])):
                row = self.native.typed(self.subject + f"/component{component}", self.root / f"native-{component}",
                    mean, variance, -cutoff, cutoff, expected_checkpoint=state["native_checkpoints"][component])
                if row["sequence"] != sequence:
                    raise RuntimeError("Native component sequence mismatch")
                native_rows.append(row)
                write_document(pending_path, {"request_sha256": request_sha, "packet_sha256": hashlib.sha256(packet).hexdigest(), "native": native_rows})
                if component == 0 and fail_stage == "after_first_native":
                    raise RuntimeError("Injected partial mixture-native commit")
            if fail_stage == "after_native":
                raise RuntimeError("Injected interruption after native commits")
            parameters = [r["head"]["parameters_q24_decoded"] for r in native_rows]
            if any(p[2:] != parameters[0][2:] for p in parameters):
                raise ValueError("Mixture component threshold disagreement")
            effective = make_law(decoded["weights"], [p[0] for p in parameters], [p[1] for p in parameters])
            released = release_law(effective, *parameters[0][2:])
            native_probabilities = [sum(weight * row["head"]["probabilities"][j]
                for weight, row in zip(decoded["weights"], native_rows)) for j in range(3)]
            released["native_component_probabilities"] = [r["head"]["probabilities"] for r in native_rows]
            released["native_mixture_probabilities"] = native_probabilities
            released["native_probability_origin"] = "actual per-component native typed CDF; weighted after actual native parameter quantization"
            released["native_vs_reference_max_absolute_error"] = max(abs(a - b) for a, b in zip(native_probabilities, released["physical_probabilities"]))
            released["probabilities_q24"] = positive_q24(native_probabilities)
            released["probabilities"] = [v / Q24 for v in released["probabilities_q24"]]
            released["raw_probabilities_q24"] = quantize_simplex(native_probabilities).tolist()
            after = digest([state["checkpoint"], request_sha, decoder.snapshot(), [r["checkpoint_after"] for r in native_rows], released])
            receipt = {**request, "request_sha256": request_sha, "public": public, "source_law": law,
                "packet_base64": base64.b64encode(packet).decode(), "decoder": decoder.snapshot(), "law": released,
                "native": native_rows, "checkpoint_before": state["checkpoint"], "checkpoint_after": after,
                "packet_bytes": len(packet), "frame_header_and_crc_bytes": 24, "payload_bytes": len(packet) - 24,
                "native_max_cdf_error": max(max(abs(a - b) for a, b in zip(r["head"]["probabilities"], event_probs(*p))) for r, p in zip(native_rows, parameters)),
                "receiver_reopened_before_native": True, "policy_receives_encoder_residual": False,
                "cross_owner_atomicity": False, "authority": "DENY_ALL",
                "encode_and_owner_load_ns": encoded - started, "packet_persist_readback_ns": readback - encoded,
                "compute_ns_before_commit": time.perf_counter_ns() - started}
            state.update(sequence=sequence, checkpoint=after, decoder=decoder.snapshot(),
                         native_checkpoints=[r["checkpoint_after"] for r in native_rows])
            state["receipts"].append(receipt)
            witness["records"].append({"sequence": sequence, "before": receipt["checkpoint_before"], "after": after, "state_sha256": digest(state)})
            write_document(witness_path, witness)
            write_document(state_path, state)
            pending_path.unlink()
            if fail_stage == "after_commit":
                raise RuntimeError("Injected lost acknowledgement")
            return receipt
