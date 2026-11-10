"""Bounded actual v4 text/image calls; finite-study gains are a separate profile."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import math
from pathlib import Path
import resource
import struct
import subprocess
import time

import torch

from scripts.joint_generation_v4_codecs import flush_mean
from scripts.joint_generation_v4_diagnostic import _assert_state
from scripts.joint_generation_v4_io import (
    DeliveryObservation,
    PROFILES,
    framed_media,
    read_packet,
    read_response,
    request_bytes,
)
from scripts.joint_generation_v4_model import ACTIONS, JointGeneratorV4, public_packet
from scripts.ndu_bimodal.delivery import commit_delivery, prepare_delivery, read_delivery


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode_input(text, image_bytes):
    """Only bytes released by the observation owner enter the encoder."""
    from PIL import Image
    import numpy as np

    if type(text) is not str or not 0 < len(text.encode("utf-8")) <= 4096:
        raise ValueError("Text must contain 1..4096 valid UTF-8 bytes")
    if type(image_bytes) is not bytes or not 0 < len(image_bytes) <= 1_048_576:
        raise ValueError("Image packet must contain 1..1048576 bytes")
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.format not in {"PNG", "PPM"} or image.size != (16, 16):
            raise ValueError("This numerical profile admits only 16x16 PNG/PPM")
        pixels = np.asarray(image.convert("RGB"), dtype=np.float64).copy() / 255
    public = {
        name: torch.zeros(shape, dtype=torch.float64)
        for name, shape in (
            ("image", (1, 3, 16, 16)),
            ("image_mask", (1, 3, 16, 16)),
            ("audio", (1, 1024)),
            ("audio_mask", (1, 1024)),
            ("video", (1, 4, 3, 16, 16)),
            ("video_mask", (1, 4, 3, 16, 16)),
        )
    }
    public["image"] = torch.tensor(pixels.transpose(2, 0, 1)[None])
    public["image_mask"].fill_(1)
    public["tokens"] = torch.tensor([list(text.encode("utf-8"))], dtype=torch.float64)
    JointGeneratorV4._validate_public(public)
    return public


def load_generator(raw):
    """Read a canonical numerical packet, never executable Python objects."""
    metadata, tensors = read_packet(raw)
    if any(metadata.get(key) != value for key, value in PROFILES.items()):
        raise ValueError("Unknown generator profile")
    if (metadata.get("width"), metadata.get("depth")) != ("32", "1"):
        raise ValueError("Native candidate requires width32/depth1")
    if metadata.get("mode") not in {"dual", "ordinary"} or metadata.get("boundary") != "direct":
        raise ValueError("Unsupported native core")
    with torch.random.fork_rng():
        generator = JointGeneratorV4(
            width=32,
            depth=1,
            mode=metadata["mode"],
            core_state_profile=metadata["core_state_profile"],
            allow_initial_stop=metadata["allow_initial_stop"] == "true",
            suppress_redundant_verify=metadata["suppress_redundant_verify"] == "true",
        )
    generator.load_state_dict(tensors, strict=True)
    if generator.export_weights(inference_profile=metadata["inference_profile"]) != raw:
        raise ValueError("Weight packet does not round-trip")
    return generator.eval().requires_grad_(False)


def _public_snapshot(public):
    if not isinstance(public, dict) or any(
        not torch.is_tensor(v) for v in public.values()
    ):
        raise ValueError("Expected the strict public tensor inventory")
    JointGeneratorV4._validate_public(public)
    return {name: value.detach().clone() for name, value in public.items()}


class NativeSession:
    """Bounded unsubmitted candidate. READ pays for re-encoding and replay.

    The v4 state binds the whole public packet. SUBMIT writes local delivery;
    it grants no production or external-service authority. Content validity
    beyond the explicit numerical profile is not certified. Torch checks and
    native calls occupy separate sequential ledger operations, never nested
    billable wall spans; child CPU remains a separately identified receipt.
    """

    def __init__(
        self,
        weights,
        binary,
        public,
        *,
        wall_seconds=30.0,
        call_seconds=3.0,
        reserve_seconds=3.0,
        max_calls=16,
        required_mask=9,
        ledger=None,
    ):
        if not all(
            type(x) in (int, float) and math.isfinite(x) and x > 0
            for x in (wall_seconds, call_seconds, reserve_seconds)
        ):
            raise ValueError("Positive finite physical time limits required")
        if (
            reserve_seconds >= wall_seconds
            or type(max_calls) is not int
            or not 2 <= max_calls <= 128
        ):
            raise ValueError("Insufficient or unbounded finalization reserve")
        if type(required_mask) is not int or required_mask not in {1, 8, 9}:
            raise ValueError("Only text, image or text+image are implemented")
        self.started, self.ledger = time.monotonic(), ledger
        with self._operation("control"):
            self.weights, self.binary = weights, Path(binary).resolve(strict=True)
            self.generator = load_generator(weights)
            self.binary_sha = sha(self.binary.read_bytes())
            self.public = _public_snapshot(public)
            self.public_bytes = public_packet(self.public)
        self.deadline = self.started + wall_seconds
        self.call_seconds, self.reserve, self.max_calls = (
            call_seconds,
            reserve_seconds,
            max_calls,
        )
        self.total_micros = int(wall_seconds * 1_000_000)
        self.owner = DeliveryObservation(
            required_mask,
            0,
            self.total_micros,
            self.total_micros,
            bytes.fromhex(sha(self.public_bytes)),
        )
        self.native_state, self.prefix, self.history, self.calls = b"", b"", [], []
        self.closed, self.state_error = False, 0.0
        self._terminal_result, self._terminal_assets, self._terminal_output = None, None, None
        self._initialize("observation")

    def _operation(self, kind, *, calls=0, finalization=False):
        return (
            self.ledger.operation(kind, calls=calls, finalization=finalization)
            if self.ledger is not None
            else nullcontext()
        )

    def _invoke(self, command, kind, *, terminal=False):
        if self.closed or len(self.calls) >= self.max_calls - (0 if terminal else 1):
            raise RuntimeError("Native call budget exhausted")
        remaining = self.deadline - time.monotonic()
        timeout = min(self.call_seconds, remaining - (0 if terminal else self.reserve))
        if self.ledger is not None:
            timeout = min(timeout, self.ledger.remaining_seconds(finalization=terminal))
        if timeout <= 0:
            raise TimeoutError("Owner finalization reserve reached")
        self.owner = replace(
            self.owner, budget_remaining=max(0, int(remaining * 1_000_000))
        )
        request = request_bytes(
            self.weights,
            self.public_bytes,
            self.native_state,
            self.prefix,
            command,
            self.owner,
        )
        receipt = {
            "kind": kind,
            "command_hex": command.hex(),
            "status": "started",
            "request_sha256": sha(request),
            "request_bytes": len(request),
            "owner_remaining_micros": self.owner.budget_remaining,
            "timeout_seconds": timeout,
            "stdout_sha256": None,
            "stderr_sha256": None,
            "exit_code": None,
        }
        self.calls.append(receipt)
        started, before = (
            time.perf_counter(),
            resource.getrusage(resource.RUSAGE_CHILDREN),
        )
        try:
            with self._operation(kind, calls=1, finalization=terminal):
                try:
                    process = subprocess.run(
                        [str(self.binary)],
                        input=request,
                        capture_output=True,
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired as error:
                    receipt.update(
                        stdout_sha256=sha(error.stdout or b""),
                        stderr_sha256=sha(error.stderr or b""),
                        status="timeout",
                    )
                    raise
                receipt.update(
                    exit_code=process.returncode,
                    stdout_sha256=sha(process.stdout),
                    stderr_sha256=sha(process.stderr),
                )
                if (
                    process.returncode
                    or len(process.stdout) > 262144
                    or len(process.stderr) > 262144
                ):
                    raise RuntimeError(
                        "Native process failed or exceeded its stream bound"
                    )
                response = read_response(process.stdout)
                receipt.update(status="passed", phase_micros=response["phase_micros"])
                return response
        except BaseException as error:
            receipt["error"] = type(error).__name__
            if receipt["status"] == "started":
                receipt["status"] = "failed"
            raise
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            receipt.update(
                wall_seconds=time.perf_counter() - started,
                child_cpu_seconds=after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime,
                cost_scope="native invocation nested in owner ledger; do not add twice",
            )

    def _initialize(self, kind):
        response = self._invoke(b"\x00" + struct.pack("<Q", 17) + b"\x00", kind)
        with self._operation("control"):
            self.native_state = response["state"]
            self.state = self.generator.encode(self.public)
            self.state_error = max(
                self.state_error, _assert_state(self.native_state, self.state)
            )

    def repair(self, modality, *, replay=False):
        if modality not in {"text", "image", "both"}:
            raise ValueError("Unsupported repair modality")
        name = "shared" if modality == "both" else modality
        index = ACTIONS.index(name)
        with self._operation("control"):
            inspection = self.generator.inspect(self.state, self.owner, self.public)
            if not bool(inspection["policy.legal_mask"].flatten()[index]):
                raise ValueError("Repair unavailable for this portfolio/state")
            before = sha(self.native_state)
            candidates = {
                key: value.detach().clone()
                for key, value in self.generator.outputs(self.state).items()
                if key in {"text", "image"}
            }
        response = self._invoke(
            bytes([1, index]), "recompute" if replay else "generate"
        )
        with self._operation("control"):
            self.state = self.generator.advance(self.state, name, self.public)
            self.native_state = response["state"]
            self.state_error = max(
                self.state_error, _assert_state(self.native_state, self.state)
            )
            outputs = self.generator.outputs(self.state)
            deltas = {
                key: float((outputs[key] - value).abs().max())
                for key, value in candidates.items()
            }
            if not replay:
                self.history.append(modality)
        return {
            "action": "REPAIR",
            "modality": modality,
            "before_sha256": before,
            "after_sha256": sha(self.native_state),
            "continuous_candidate_changed": any(value > 0 for value in deltas.values()),
            "continuous_candidate_max_abs_change": deltas,
            "quality_improvement_certified": False,
        }

    def read(self, public):
        if self.closed or self.prefix:
            raise ValueError("Cannot replace input after terminal delivery")
        needed = 1 + len(self.history)
        if len(self.calls) + needed > self.max_calls - 1:
            raise RuntimeError("READ replay would consume the finalization call")
        if (
            self.ledger is not None
            and self.ledger.calls + needed
            > self.ledger.limits.max_calls - self.ledger.limits.finalization_calls
        ):
            raise RuntimeError("READ replay exceeds the owner call reserve")
        with self._operation("control"):
            following = _public_snapshot(public)
            encoded = public_packet(following)
        saved = (
            self.public,
            self.public_bytes,
            self.owner,
            self.native_state,
            self.state,
        )
        try:
            self.public, self.public_bytes = following, encoded
            self.owner = replace(self.owner, task_digest=bytes.fromhex(sha(encoded)))
            self.native_state = b""
            self._initialize("observation")
            return [self.repair(modality, replay=True) for modality in self.history]
        except BaseException:
            # Restore candidate identity, never elapsed time, receipts or spent calls.
            (
                self.public,
                self.public_bytes,
                self.owner,
                self.native_state,
                self.state,
            ) = saved
            raise

    def finish(self, *, submit=False, output=None):
        if submit and output is None:
            raise ValueError("Local SUBMIT requires a delivery directory")
        destination = Path(output).absolute() if submit else None
        if self.closed:
            if self._terminal_result is None:
                raise RuntimeError(
                    "Terminal validation/accounting failed; closed generation cannot be redispatched"
                )
            if (
                submit != (self._terminal_result["action"] == "SUBMIT")
                or destination != self._terminal_output
            ):
                raise ValueError("Terminal recovery must retain its original delivery intent")
            return self._publish_terminal() if submit else deepcopy(self._terminal_result)
        if submit and (destination.exists() or destination.is_symlink()):
            raise ValueError("Delivery directory already exists")
        response = self._invoke(bytes([1, 6]), "submit", terminal=True)
        with self._operation("control", finalization=True):
            state = self.generator.advance(self.state, "stop", self.public)
            state, owner, expected = flush_mean(self.generator, state, self.owner)
            if expected != response["delta"] or response["stopped"] is not True:
                raise AssertionError("Native/Torch terminal bytes differ")
            self.state_error = max(
                self.state_error, _assert_state(response["state"], state)
            )
            self.native_state, self.prefix, self.state, self.owner = (
                response["state"],
                expected,
                state,
                owner,
            )
            self.closed = True
            cursors, media = framed_media(self.prefix)
            result = {
                "action": "SUBMIT" if submit else "STOP",
                "cursors": cursors,
                "checkpoint_sha256": sha(self.weights),
                "binary_sha256": self.binary_sha,
                "public_sha256": sha(self.public_bytes),
                "state_sha256": sha(self.native_state),
                "text_utf8": media[3].decode("utf-8"),
                "image_sha256": sha(media[0]) if media[0] else None,
                "state_max_abs_error": self.state_error,
                "calls": self.calls,
                "semantic_quality": None,
                "production_update": "no-update",
                "allocation": {
                    name: self.history.count(name) for name in ("text", "image", "both")
                },
            }
            assets = {
                name: media[index]
                for index, name in ((0, "generated.ppm"), (3, "generated.txt"))
                if media[index]
            }
            if submit:
                result = prepare_delivery(result, assets)
        self._terminal_result, self._terminal_assets, self._terminal_output = (
            deepcopy(result), assets, destination
        )
        if submit:
            return self._publish_terminal()
        if time.monotonic() > self.deadline:
            self._terminal_result = None
            raise TimeoutError("Terminal result exceeded the owner deadline")
        return deepcopy(result)

    def _publish_terminal(self):
        # A completed receipt is historical readback, even after expiry. It
        # does not renew generation budget or append to original call evidence.
        if (self._terminal_output / "delivery.json").exists():
            return read_delivery(
                self._terminal_output,
                expected_identity=self._terminal_result["delivery"]["identity"],
            )

        def before_commit():
            if time.monotonic() > self.deadline:
                raise TimeoutError("Terminal publication exceeded the original deadline")
            if self.ledger is not None and self.ledger.remaining_seconds(finalization=True) <= 0:
                raise TimeoutError("Terminal publication exhausted the original owner budget")

        with self._operation("submit", finalization=True):
            result = commit_delivery(
                self._terminal_output, self._terminal_result, self._terminal_assets,
                before_commit=before_commit,
            )
            if time.monotonic() > self.deadline:
                raise TimeoutError("Terminal result exceeded the original deadline")
            return result
