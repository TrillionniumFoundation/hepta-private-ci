"""Independent actual-media, public-event, feedback and observer arithmetic.

No generator is imported. CNN verification uses the two frozen observers on
one image pair per call; repeated identical image bytes may reuse an audit-only
cache. Logical verification and actual observer calls are counted separately.
"""

from collections import OrderedDict
import hashlib
import io
import math
from pathlib import Path
import re
import struct

import numpy as np
from PIL import Image
import torch


HEADER = struct.Struct("<4sIII")
CAPTION = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    require(len(raw) >= HEADER.size, "Truncated H3M header")
    magic, png_count, text_count, logit_count = HEADER.unpack(raw[:HEADER.size])
    require(magic == b"H3M1" and 1 <= png_count <= 100000 and 0 <= text_count <= 4096 and
            logit_count == 192 and len(raw) == HEADER.size + png_count + text_count + logit_count,
            "Invalid H3M component bounds")
    png = raw[HEADER.size:HEADER.size + png_count]
    text = raw[HEADER.size + png_count:HEADER.size + png_count + text_count]
    logits = raw[-logit_count:]
    require(png.startswith(b"\x89PNG\r\n\x1a\n"), "Invalid delivered PNG signature")
    with Image.open(io.BytesIO(png)) as image:
        require(image.format == "PNG" and image.mode == "L" and image.size == (56, 28), "Wrong delivered PNG profile")
        image.verify()
    with Image.open(io.BytesIO(png)) as image:
        pixels = np.asarray(image).copy()
    caption = text.decode("utf-8", errors="strict")
    public_logits = np.frombuffer(logits, dtype="<f4").reshape(2, 24).copy()
    require(np.isfinite(public_logits).all(), "Nonfinite delivered public logits")
    return {"pixels": pixels, "caption": caption, "logits": public_logits,
            "record_sha256": sha(raw), "sha256": {"image": sha(png), "text": sha(text), "public_logits": sha(logits)}}


class MediaIndex:
    def __init__(self, path, cache_size=2048):
        self.path = Path(path)
        require(self.path.is_file() and not self.path.is_symlink(), "Invalid media container")
        self.records, self.cache, self.used = {}, OrderedDict(), set()
        self.cache_size = cache_size
        self.logical_reads = 0
        self.physical_bytes = self.path.stat().st_size
        digests = set()
        with self.path.open("rb") as stream:
            while stream.tell() < self.physical_bytes:
                offset = stream.tell()
                header = stream.read(HEADER.size)
                require(len(header) == HEADER.size, "Trailing truncated H3M header")
                magic, png, text, logits = HEADER.unpack(header)
                require(magic == b"H3M1" and 1 <= png <= 100000 and 0 <= text <= 4096 and logits == 192,
                        "Invalid physical media record header")
                raw = header + stream.read(png + text + logits)
                record = decode(raw)
                require(record["record_sha256"] not in digests, "Duplicate physical content despite immutable content deduplication")
                digests.add(record["record_sha256"])
                self.records[offset] = {"length": len(raw), "record_sha256": record["record_sha256"], "sha256": record["sha256"]}
            require(stream.tell() == self.physical_bytes, "Media extent mismatch")

    def receipt(self, receipt):
        require(receipt["container"] == self.path.name and type(receipt["offset"]) is int and
                receipt["offset"] in self.records, "Receipt refers outside the indexed media")
        bound = self.records[receipt["offset"]]
        require(all(receipt[key] == bound[key] for key in ("length", "record_sha256", "sha256")),
                "Media receipt/component binding differs")
        key = receipt["offset"]
        if key in self.cache:
            record = self.cache.pop(key)
        else:
            with self.path.open("rb") as stream:
                stream.seek(key)
                record = decode(stream.read(bound["length"]))
            require(record["record_sha256"] == bound["record_sha256"], "Media changed after physical scan")
        self.cache[key] = record
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        require(np.array_equal(np.asarray(receipt["public_text_logits"], dtype=np.float64), record["logits"].astype(np.float64)),
                "Public logit receipt differs from actual little-endian float32 bytes")
        self.used.add(key)
        self.logical_reads += 1
        return record


class ObserverArithmetic:
    def __init__(self, observers, cache_size=16384):
        require(set(observers) == {"reward", "audit"} and all(not model.training for model in observers.values()),
                "Two frozen eval observers are required")
        self.observers, self.cache_size, self.cache = observers, cache_size, OrderedDict()
        self.calls = {name: 0 for name in observers}
        self.logical_images = {name: 0 for name in observers}

    @torch.inference_mode()
    def image(self, pixels, observer):
        pixels = np.asarray(pixels)
        require(pixels.shape == (28, 56) and pixels.dtype == np.uint8, "Observer input must be actual quantized image bytes")
        key = (observer, sha(pixels.tobytes()))
        self.logical_images[observer] += 1
        if key in self.cache:
            result = self.cache.pop(key)
        else:
            image = torch.from_numpy(pixels.copy()).float()[None, None] / 255
            raw = [self.observers[observer](image[:, :, :, start:start + 28])[0] for start in (0, 28)]
            self.calls[observer] += 2
            probabilities = torch.stack([value.softmax(-1) for value in raw])
            result = {"probabilities": probabilities.detach().clone(), "raw_digits": [int(value.argmax()) for value in raw],
                      "probability_digits": probabilities.argmax(-1).tolist()}
        self.cache[key] = result
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return result

    @torch.inference_mode()
    def public(self, record, public_mask):
        image = torch.from_numpy(record["pixels"].copy()).float()[None, None] / 255
        logits = torch.from_numpy(record["logits"].copy())[None]
        text_confidence = logits.softmax(-1)[:, :, 14:24].amax(-1)
        classified = self.image(record["pixels"], "reward")
        image_confidence = classified["probabilities"].amax(-1)[None]
        match = CAPTION.fullmatch(record["caption"].strip())
        disagreement = torch.ones(1, 2)
        if match:
            disagreement[0] = torch.tensor([int(match[side + 1]) != classified["probability_digits"][side] for side in (0, 1)], dtype=torch.float32)
        mask = torch.as_tensor(public_mask).float().reshape(1, 1, 28, 56)
        require(torch.isfinite(mask).all().item() and mask.min() >= 0 and mask.max() <= 1, "Invalid public mask")
        missing = 1 - mask.flatten(1).mean(1)
        entropy = -(torch.special.xlogy(image, image) + torch.special.xlogy(1 - image, 1 - image)).flatten(1).mean(1) / math.log(2)
        features = torch.cat((text_confidence, image_confidence, disagreement, missing[:, None], entropy[:, None]), dim=1).float().clamp(0, 1)
        require(torch.isfinite(features).all().item(), "Nonfinite rebuilt public features")
        return (2 * features.double().numpy() - 1)[0]

    @torch.inference_mode()
    def score(self, record, target_pixels, target_labels, observer, depth):
        expected = torch.as_tensor(target_labels).reshape(2).tolist()
        target = torch.as_tensor(target_pixels).float().reshape(1, 1, 28, 56)
        image = torch.from_numpy(record["pixels"].copy()).float()[None, None] / 255
        digits = self.image(record["pixels"], observer)["raw_digits"]
        match = CAPTION.fullmatch(record["caption"].strip())
        parsed = [int(match[1]), int(match[2])] if match else None
        relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
        fields = {
            "text_fact": sum(a != b for a, b in zip(parsed, expected, strict=True)) / 2 if match else 1.,
            "relation": float(match[3] != relation) if match else 1.,
            "image_fact": sum(a != b for a, b in zip(digits, expected, strict=True)) / 2,
            "crossmodal_disagreement": sum(a != b for a, b in zip(parsed, digits, strict=True)) / 2 if match else 1.,
            "pixel_mse": float((image - target).square().flatten(1).mean(1)[0]),
        }
        weights = {"text_fact": .30, "relation": .15, "image_fact": .35, "crossmodal_disagreement": .10, "pixel_mse": .10}
        loss = sum(weights[key] * value for key, value in fields.items())
        utility = 1 - 2 * loss
        return {**fields, "joint_loss": loss, "utility": utility, "caption_valid": match is not None,
                "image_digits": digits, "caption_digits": parsed, "caption_relation": match[3] if match else None,
                "net_utility": utility - .002 * (1 + depth)}


@torch.inference_mode()
def feedback_values(record, target_pixels, target_labels, case_id, depth):
    require(depth in (1, 2), "Feedback cannot precede the first or follow the last revision")
    side = hashlib.sha256(f"{case_id}:{depth}".encode()).digest()[0] % 2
    expected = torch.as_tensor(target_labels).reshape(2)
    target = torch.as_tensor(target_pixels).float().reshape(1, 28, 56)
    pixels = torch.from_numpy(record["pixels"].copy()).float()[None] / 255
    match = CAPTION.fullmatch(record["caption"].strip())
    correct = bool(match and int(match[side + 1]) == int(expected[side]))
    mse = float((pixels[:, :, side * 28:(side + 1) * 28] - target[:, :, side * 28:(side + 1) * 28]).square().mean())
    return [1., float(2 * side - 1), 1. if correct else -1., 1. - 2 * mse]


def event(public, feedback=None, previous_action=0):
    require(np.asarray(public).shape == (8,), "Eight public output features required")
    result = np.zeros(16, dtype=np.float64)
    result[:8] = public
    if feedback is not None:
        require(previous_action in (1, 2, 3, 4) and len(feedback) == 4, "Invalid feedback/action continuation")
        result[8:12] = feedback
        result[12 + previous_action - 1] = 1.
    else:
        require(previous_action == 0, "Initial event cannot include an unexecuted prior action")
    require(np.isfinite(result).all() and abs(result).max() <= 1, "Unbounded public event")
    return result


def nonnative_action(controller, history):
    """Independent current/history transform, Fourier coordinates and head."""
    raw = np.asarray(history, dtype=np.float64)
    require(raw.ndim == 2 and raw.shape[1] == 16 and 1 <= len(raw) <= 3, "Invalid causal history dimensions")
    transform = controller["transform"]
    values = raw.copy()
    if transform["name"] != "raw":
        values = np.clip((values - transform["normalizer"]["mean"]) / transform["normalizer"]["scale"] / transform["k"], -1, 1)
    if controller["representation"] == "current":
        public, value = raw[-1], values[-1]
    else:
        require(controller["representation"] == "history", "Native action replay has separate ownership")
        public, value = np.zeros(48), np.zeros(48)
        public[:raw.size], value[:values.size] = raw.reshape(-1), values.reshape(-1)
    weights = np.asarray(controller["fourier"]["weights"], dtype=np.float64)
    projection = np.einsum("bi,ij->bj", value[None], weights, optimize=False)[0]
    residual = np.r_[np.cos(projection), np.sin(projection)] / np.sqrt(controller["fourier"]["frequencies"])
    features = np.r_[public, residual]
    head = controller["heads"][len(raw) - 1]
    standardized = (features - head["normalizer"]["mean"]) / head["normalizer"]["scale"]
    predictions = np.einsum("bi,ij->bj", np.r_[standardized, 1.][None], np.asarray(head["coefficient"]), optimize=False)[0]
    require(np.isfinite(predictions).all() and features.shape == (88,), "Invalid frozen runtime head")
    return int(predictions.argmax()), features, predictions
