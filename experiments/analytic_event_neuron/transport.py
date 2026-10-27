"""Actual numeric text/PNG delivery and public-observation readback.

PNG is a lossless numeric transport fixture, not natural-image generation.
The policy consumes returned disk readbacks; targets are never accepted here.
"""

import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_value(value):
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def encode_prediction_png(path, value):
    bits = np.unpackbits(np.frombuffer(struct.pack(">d", value), dtype=np.uint8))
    pixels = np.full((32, 256), 127, dtype=np.uint8)
    for index, bit in enumerate(bits):
        pixels[:16, index * 4:(index + 1) * 4] = 255 * int(bit)
        pixels[16:, index * 4:(index + 1) * 4] = 255 * (1 - int(bit))
    Image.fromarray(pixels).save(path, format="PNG", optimize=False)


def decode_prediction_png(path):
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "L" or image.size != (256, 32):
            raise ValueError("Unexpected prediction transport format")
        pixels = np.asarray(image)
    bits = []
    for index in range(64):
        upper = pixels[:16, index * 4:(index + 1) * 4]
        lower = pixels[16:, index * 4:(index + 1) * 4]
        value = int(upper[0, 0])
        if value not in (0, 255) or not np.all(upper == value) or not np.all(lower == 255 - value):
            raise ValueError("Corrupt numeric prediction pixels")
        bits.append(value // 255)
    value = struct.unpack(">d", np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes())[0]
    if not np.isfinite(value):
        raise ValueError("Nonfinite decoded prediction")
    return value


class ArtifactTransport:
    """One evaluation scope with append-only receipts and no private targets."""

    def __init__(self, root, scope):
        self.root = Path(root)
        self.scope = str(scope)
        self.root.mkdir(parents=True, exist_ok=True)
        self.receipts = []
        self.counts = {"observations": 0, "deliveries": 0, "files": 0}
        self._operations = set()

    def _directory(self, case, arm, stage, operation):
        identity = json.dumps([self.scope, str(case), str(arm), stage, operation], separators=(",", ":"))
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        if key in self._operations:
            raise ValueError("Duplicate transport operation; replay must use the retained artifact")
        self._operations.add(key)
        directory = self.root / key
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def observer(self, case, arm, stage, value):
        began = time.perf_counter_ns()
        if isinstance(value, dict):
            if set(value) != {"obs", "times", "mask", "occupied", "obs_var"}:
                raise ValueError("Only registered public history fields may enter the observer")
        elif not np.isfinite(value):
            raise ValueError("Observation must be finite")
        directory = self._directory(case, arm, stage, "observe")
        path = directory / "observation.json"
        payload = {"schema": "hepta.analytic-event.public-observation.v1", "value": _json_value(value)}
        _write_new(path, (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode())
        written = time.perf_counter_ns()
        loaded = json.loads(path.read_text())["value"]
        if isinstance(loaded, dict):
            readback = {key: np.asarray(item, dtype=bool if key in ("mask", "occupied") else float)
                        for key, item in loaded.items()}
        else:
            readback = float(loaded)
        reopened = time.perf_counter_ns()
        self.receipts.append({"scope": self.scope, "case": str(case), "arm": arm,
            "stage": stage, "kind": "observation", "began_ns": began,
            "written_ns": written, "readback_ns": reopened,
            "path": str(path.relative_to(self.root)), "sha256": file_digest(path),
            "private_target_supplied": False})
        self.counts["observations"] += 1
        self.counts["files"] += 1
        return readback

    def deliver(self, case, arm, stage, prediction, action):
        began = time.perf_counter_ns()
        prediction = float(prediction)
        if not np.isfinite(prediction):
            raise ValueError("Prediction must be finite")
        directory = self._directory(case, arm, stage, "deliver")
        text_path, image_path = directory / "prediction.txt", directory / "prediction.png"
        _write_new(text_path, (format(prediction, ".17g") + "\n").encode())
        encode_prediction_png(image_path, prediction)
        written = time.perf_counter_ns()
        text_value = float(text_path.read_text())
        image_value = decode_prediction_png(image_path)
        if struct.pack(">d", text_value) != struct.pack(">d", image_value):
            raise ValueError("Text and PNG prediction disagree")
        reopened = time.perf_counter_ns()
        self.receipts.append({"scope": self.scope, "case": str(case), "arm": arm,
            "stage": stage, "kind": "delivery", "action": action,
            "began_ns": began, "written_ns": written, "readback_ns": reopened,
            "prediction": image_value, "text_path": str(text_path.relative_to(self.root)),
            "image_path": str(image_path.relative_to(self.root)),
            "text_sha256": file_digest(text_path), "image_sha256": file_digest(image_path),
            "private_target_supplied": False})
        self.counts["deliveries"] += 1
        self.counts["files"] += 2
        return image_value

    def save_receipts(self):
        path = self.root / "TRANSPORT_RECEIPTS.jsonl"
        _write_new(path, "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n"
                                for row in self.receipts).encode())
        return {**self.counts, "receipt_path": str(path), "receipt_sha256": file_digest(path)}
