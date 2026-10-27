"""Append-only unique PNG/UTF-8/logit records with every delivery read back.

One indexed container avoids inode exhaustion. Identical immutable bytes share
one physical record. Every logical delivery gets a fresh receipt and readback;
an observer and verifier consume those decoded, reread bytes. Model computation
is never skipped or cached by this persistence-only deduplication.
"""

import hashlib
import io
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image
import torch

from ..field_bridge_20261027.task import HardOutput
from ..v6.data import render_tokens


HEADER = struct.Struct("<4sIII")
MAGIC = b"H3M1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode_record(raw):
    if len(raw) < HEADER.size:
        raise ValueError("Truncated media header")
    magic, npng, ntext, nlogits = HEADER.unpack(raw[:HEADER.size])
    if (magic != MAGIC or not 1 <= npng <= 100_000 or not 0 <= ntext <= 4096 or
            nlogits != 192 or len(raw) != HEADER.size + npng + ntext + nlogits):
        raise ValueError("Invalid media record bounds")
    start = HEADER.size
    png = raw[start:start + npng]
    text = raw[start + npng:start + npng + ntext]
    logits = raw[-nlogits:]
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG magic")
    with Image.open(io.BytesIO(png)) as image:
        if image.format != "PNG" or image.mode != "L" or image.size != (56, 28):
            raise ValueError("Invalid PNG profile")
        pixels = np.array(image, copy=True)
    caption = text.decode("utf-8", errors="strict")
    values = np.frombuffer(logits, dtype="<f4").copy().reshape(2, 24)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite public logits")
    return pixels, caption, values, {"image": sha(png), "text": sha(text), "public_logits": sha(logits)}


class MediaWriter:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("xb+")
        self.records = 0
        self.physical_records = 0
        self.bytes = 0
        self.index = {}

    def deliver(self, neural_output, case_ids, depth):
        pixels = (neural_output.image_logits.detach().cpu().sigmoid() * 255).round().to(torch.uint8)
        tokens = neural_output.token_ids.detach().cpu().clone()
        logits = neural_output.text_logits.detach().cpu()[:, [1, 3]].contiguous()
        if (pixels.shape != (len(case_ids), 1, 28, 56) or
                logits.shape != (len(case_ids), 2, 24) or logits.dtype != torch.float32):
            raise ValueError("Generated media does not match registered profile")
        if not torch.isfinite(logits).all() or not torch.isfinite(neural_output.image_logits).all():
            raise ValueError("Nonfinite generator output")
        captions, restored_pixels, receipts = [], [], []
        for i, case_id in enumerate(case_ids):
            caption = render_tokens(tokens[i])
            png_stream = io.BytesIO()
            Image.fromarray(pixels[i, 0].numpy()).save(png_stream, format="PNG", compress_level=6)
            png, text = png_stream.getvalue(), caption.encode("utf-8")
            raw_logits = logits[i].numpy().astype("<f4", copy=False).tobytes()
            payload = HEADER.pack(MAGIC, len(png), len(text), len(raw_logits)) + png + text + raw_logits
            identity = sha(payload)
            reused = identity in self.index
            if reused:
                offset = self.index[identity]
            else:
                self.stream.seek(0, 2)
                offset = self.stream.tell()
                self.stream.write(payload)
                self.stream.flush()
                self.index[identity] = offset
                self.physical_records += 1
                self.bytes += len(payload)
            self.stream.seek(offset)
            restored = self.stream.read(len(payload))
            if restored != payload:
                raise RuntimeError("Media readback bytes changed")
            image, reread_caption, reread_logits, hashes = decode_record(restored)
            if (reread_caption != caption or not np.array_equal(image, pixels[i, 0].numpy()) or
                    not np.array_equal(reread_logits, logits[i].numpy())):
                raise RuntimeError("Media/logit decoding changed delivered content")
            captions.append(reread_caption)
            restored_pixels.append(torch.from_numpy(image)[None])
            receipts.append({"case_id": case_id, "depth": depth, "container": self.path.name,
                "offset": offset, "length": len(payload), "record_sha256": sha(payload),
                "physical_record_reused": reused,
                "sha256": hashes, "public_text_logits": reread_logits.tolist(),
                "readback_monotonic_ns": time.monotonic_ns()})
            self.records += 1
        return HardOutput(tokens, torch.stack(restored_pixels), tuple(captions), tuple(receipts),
                          {"media_logical_deliveries_read_back": len(case_ids),
                           "physical_records_appended": sum(not r["physical_record_reused"] for r in receipts)})

    def close(self):
        if not self.stream.closed:
            self.stream.flush()
            self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def read_receipt(root, receipt):
    path = Path(root) / receipt["container"]
    if path.parent.resolve() != Path(root).resolve() or path.is_symlink():
        raise ValueError("Invalid evidence container path")
    with path.open("rb") as stream:
        stream.seek(receipt["offset"])
        raw = stream.read(receipt["length"])
    if sha(raw) != receipt["record_sha256"]:
        raise ValueError("Media record digest changed")
    pixels, caption, logits, hashes = decode_record(raw)
    if hashes != receipt["sha256"]:
        raise ValueError("Media component digest changed")
    return pixels, caption, logits
