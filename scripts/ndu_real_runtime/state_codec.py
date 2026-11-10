"""Bounded research-actor continuation; never a journal commit or adoption.

The checkpoint is after a decision and before its external effect. Its owner
must reconcile that effect and pin the next public input before resuming. OCR
cache bytes are recomputed and metered; prior feature digests must still match.
"""

import base64
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys

import numpy as np
import PIL
import torch

from .metering import atomic_json, canonical_sha, file_sha

SCHEMA = "ndu.real.actor-checkpoint.v1"
MAX_BYTES = 131072
FIELDS = ("content", "voltage", "adaptation", "event")
STEP_FIELDS = {
    "schema",
    "case_id",
    "step",
    "remaining_seconds",
    "prepared_roi",
    "observation",
    "delivery",
    "text_committed",
    "forced_action",
}


def read_bounded(path, maximum):
    """Pin the exact bytes consumed, without unpickling or following a leaf link."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Actor artifact must be a regular file")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Actor artifact exceeds its byte bound")
    return raw


def checkpoint_binding(args, packet, model, plan, deployment, parameters):
    directory = Path(__file__).parent
    sources = {
        name: file_sha(directory / (name + ".py"))
        for name in (
            "actor",
            "state_codec",
            "neural",
            "controllers",
            "objective",
            "ocr",
            "metering",
            "span_meter",
        )
    }
    sources["hepta_core"] = file_sha(inspect.getfile(type(model.core)))
    if not args.tessdata_dir or not args.ocr_library_dir:
        raise ValueError("Checkpoint requires explicit OCR data and library roots")
    executable = shutil.which(args.tesseract)
    if executable is None:
        raise ValueError("Checkpoint OCR executable is unavailable")
    data = Path(args.tessdata_dir).resolve(strict=True)
    libraries = Path(args.ocr_library_dir).resolve(strict=True)
    library_files = sorted(path for path in libraries.rglob("*") if not path.is_dir())
    if not libraries.is_dir() or len(library_files) > 256:
        raise ValueError("Checkpoint OCR library inventory exceeds its bound")
    ocr = {
        "executable": file_sha(executable),
        "eng.traineddata": file_sha(data / "eng.traineddata"),
        "libraries": {
            str(path.relative_to(libraries)): file_sha(path) for path in library_files
        },
    }
    return {
        "operation_id": args.operation_id,
        "case_id": packet["case_id"],
        "case_sha256": canonical_sha(packet),
        "weights_sha256": args.expected_weights_sha256,
        "parameters_sha256": parameters,
        "core": args.core,
        "controller": args.controller,
        "control_plan_sha256": canonical_sha(plan),
        "deployment_sha256": canonical_sha(deployment),
        "training_exploration": args.training_exploration,
        "sources": sources,
        "state_schema": {
            "fields": FIELDS,
            "dtype": "float32",
            "device": "cpu",
            "depth": model.core.depth,
            "width": model.core.width,
        },
        "memory_mode": plan["control"].get("memory_mode", "reset"),
        "runtime": {
            "torch": torch.__version__,
            "numpy": np.__version__,
            "pillow": PIL.__version__,
            "python": list(sys.version_info[:3]),
        },
        "controller_rng": "per-decision forecast_seed(control-plan seed, step, action)",
        "ocr": ocr,
    }


def _memory(value, binding, *, encode):
    if value is None:
        return None
    shape = binding["state_schema"]
    if binding["memory_mode"] != "persistent" or len(value) != shape["depth"]:
        raise ValueError("Checkpoint memory mode or depth differs")
    result = []
    for layer in value:
        if not isinstance(layer, dict) or set(layer) != set(FIELDS):
            raise ValueError("Checkpoint memory fields differ")
        row = {}
        for name in FIELDS:
            item = layer[name]
            if not encode:
                if (
                    not isinstance(item, list)
                    or len(item) != 1
                    or not isinstance(item[0], list)
                    or len(item[0]) != shape["width"]
                    or any(
                        type(x) not in (int, float) or not math.isfinite(x)
                        for x in item[0]
                    )
                ):
                    raise ValueError("Invalid checkpoint tensor encoding")
                item = torch.tensor(item, dtype=torch.float32)
            if (
                not isinstance(item, torch.Tensor)
                or item.dtype != torch.float32
                or item.device.type != "cpu"
                or tuple(item.shape) != (1, shape["width"])
                or not bool(torch.isfinite(item).all())
            ):
                raise ValueError("Invalid checkpoint tensor")
            row[name] = item.detach().tolist() if encode else item
        result.append(row)
    return result


def _step(value):
    if (
        not isinstance(value, dict)
        or set(value) != STEP_FIELDS
        or value["schema"] != "ndu.real.actor-step.v1"
        or type(value["step"]) is not int
        or not 0 <= value["step"] < 8
        or type(value["remaining_seconds"]) not in (int, float)
        or not math.isfinite(value["remaining_seconds"])
        or value["remaining_seconds"] < 0
        or not isinstance(value["delivery"], dict)
        or set(value["delivery"]) != {"schema", "case_id", "text", "image"}
        or value["delivery"]["schema"] != "ndu.real.delivery.v1"
        or value["delivery"]["case_id"] != value["case_id"]
        or type(value["text_committed"]) is not bool
    ):
        raise ValueError("Invalid checkpoint public step")


def save_checkpoint(path, binding, memory, state, action, ocr_pins):
    _step(state)
    if state["case_id"] != binding["case_id"] or len(ocr_pins) > 8:
        raise ValueError("Checkpoint case or OCR inventory differs")
    checkpoint = {
        "schema": SCHEMA,
        "binding": binding,
        "next_step": state["step"] + 1,
        "input": state,
        "action": action,
        "memory": _memory(memory, binding, encode=True),
        "torch_rng": base64.b64encode(torch.get_rng_state().numpy().tobytes()).decode(),
        "ocr_pins": ocr_pins,
    }
    if (
        len(json.dumps(checkpoint, indent=2, sort_keys=True, allow_nan=False).encode())
        + 1
        > MAX_BYTES
    ):
        raise ValueError("Checkpoint exceeds its byte bound")
    digest = atomic_json(path, checkpoint)
    return {
        "path": str(path),
        "sha256": digest,
        "next_step": checkpoint["next_step"],
        "external_effect_confirmed": False,
    }


def load_checkpoint(path, expected_sha256, binding, next_step):
    raw = read_bounded(path, MAX_BYTES)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Checkpoint bytes differ from the host pin")

    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("Duplicate checkpoint field")
        return value

    checkpoint = json.loads(raw, object_pairs_hook=unique)
    fields = {
        "schema",
        "binding",
        "next_step",
        "input",
        "action",
        "memory",
        "torch_rng",
        "ocr_pins",
    }
    if (
        not isinstance(checkpoint, dict)
        or set(checkpoint) != fields
        or checkpoint["schema"] != SCHEMA
        or canonical_sha(checkpoint["binding"]) != canonical_sha(binding)
        or type(next_step) is not int
        or type(checkpoint["next_step"]) is not int
        or checkpoint["next_step"] != next_step
        or not 1 <= next_step < 8
    ):
        raise ValueError("Checkpoint binding or continuation step differs")
    _step(checkpoint["input"])
    action = checkpoint["action"]
    if (
        checkpoint["input"]["case_id"] != binding["case_id"]
        or checkpoint["input"]["step"] + 1 != next_step
        or not isinstance(action, dict)
        or set(action) != {"schema", "action", "arguments"}
        or action["schema"] != "ndu.real.actor-action.v1"
        or action["action"]
        not in {"WRITE_TEXT", "RENDER_IMAGE", "PREPARE_ROI", "READ_ROI"}
        or not isinstance(checkpoint["ocr_pins"], dict)
        or len(checkpoint["ocr_pins"]) > 8
    ):
        raise ValueError("Checkpoint is terminal or incomplete")
    for key, value in checkpoint["ocr_pins"].items():
        if any(
            not isinstance(x, str) or len(x) != 64 or set(x) - set("0123456789abcdef")
            for x in (key, value)
        ):
            raise ValueError("Invalid checkpoint OCR pins")
    memory = _memory(checkpoint["memory"], binding, encode=False)
    if binding["memory_mode"] == "persistent" and memory is None:
        raise ValueError("Persistent continuation has no complete memory")
    raw_rng = base64.b64decode(checkpoint["torch_rng"], validate=True)
    if len(raw_rng) != torch.get_rng_state().numel():
        raise ValueError("Checkpoint RNG shape differs")
    rng = torch.tensor(list(raw_rng), dtype=torch.uint8)
    torch.Generator().set_state(rng)  # Validate before changing the actor's generator.
    torch.set_rng_state(rng)
    return checkpoint, memory


def validate_continuation(checkpoint, state, expected_input_sha256):
    """Verify the host-pinned public successor after its independent effect reconciliation."""
    _step(state)
    old, action = checkpoint["input"], checkpoint["action"]
    name, arguments = action["action"], action["arguments"]
    if (
        canonical_sha(state) != expected_input_sha256
        or state["case_id"] != old["case_id"]
        or state["step"] != checkpoint["next_step"]
        or state["remaining_seconds"] > old["remaining_seconds"]
        or state["text_committed"] != old["text_committed"]
    ):
        raise ValueError("Continuation public input or budget differs")
    expected_text = (
        arguments["text"] if name == "WRITE_TEXT" else old["delivery"]["text"]
    )
    expected_roi = arguments["bbox"] if name == "PREPARE_ROI" else old["prepared_roi"]
    if (
        state["delivery"]["text"] != expected_text
        or state["prepared_roi"] != expected_roi
    ):
        raise ValueError("Continuation lost the previous text or ROI result")
    if name == "RENDER_IMAGE":
        image = state["delivery"]["image"]
        if not isinstance(image, dict) or image.get("bbox") != arguments["bbox"]:
            raise ValueError("Continuation lost the previous image result")
    elif state["delivery"]["image"] != old["delivery"]["image"]:
        raise ValueError("Continuation changed unrelated image delivery")
    if name == "READ_ROI":
        observed = state["observation"]
        if (
            not old["prepared_roi"]
            or observed.get("kind") != "roi"
            or observed.get("bbox") != old["prepared_roi"]
        ):
            raise ValueError("Continuation lost the previous observed ROI")
    elif state["observation"] != old["observation"]:
        raise ValueError("Continuation changed unrelated observation")
