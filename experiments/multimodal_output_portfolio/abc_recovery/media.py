"""Persist original sampled PNG/UTF-8 bytes before assigning offline utility.

Content-addressed ZIP members deduplicate identical media, not observations or
statistical units. Every sample retains its own source/seed/path row elsewhere.
Completion means decodable required media and nonempty text, not factual truth.
"""

import hashlib
import io
import os
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import torch

from ..v6.data import CAPTION_LENGTH, VOCAB, render_tokens


def _decode(image_raw, text_raw):
    if len(image_raw) > 1_000_000 or len(text_raw) > 4096:
        raise ValueError("Output exceeds the registered media bounds")
    with Image.open(io.BytesIO(image_raw)) as image:
        if image.format != "PNG" or image.mode != "L" or image.size != (56, 28):
            raise ValueError("Output is not the registered grayscale PNG")
        pixels = torch.from_numpy(np.array(image, copy=True)).float()[None] / 255
    caption = text_raw.decode("utf-8", errors="strict")
    return pixels, caption


def _read(zip_file, record):
    payloads = {}
    for kind in ("image", "text"):
        name = record[kind + "_member"]
        expected = record[kind + "_sha256"]
        suffix = ".png" if kind == "image" else ".txt"
        if name != f"{kind}s/{expected}{suffix}":
            raise ValueError("Media member is not content addressed")
        if zip_file.getinfo(name).file_size > 1_000_000:
            raise ValueError("Oversized media member")
        raw = zip_file.read(name)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Persisted raw media checksum mismatch")
        payloads[kind] = raw
    pixels, caption = _decode(payloads["image"], payloads["text"])
    if record["required_output_complete"] != bool(caption.strip()):
        raise ValueError("Physical completion does not match persisted media")
    return pixels, caption


class RawMediaArchive:
    """Append-only actual emissions, flushed and reopened before offline scoring."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.archive = zipfile.ZipFile(self.path, "x", compression=zipfile.ZIP_STORED,
                                       allowZip64=True)
        self.members = set()
        self.samples = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def close(self):
        if self.archive.fp is not None:
            self.archive.close()
            with self.path.open("rb") as stream:
                os.fsync(stream.fileno())

    def append(self, pixels, tokens):
        if (pixels.ndim != 4 or pixels.shape[1:] != (1, 28, 56)
                or len(pixels) < 1 or not torch.isfinite(pixels).all()
                or not ((pixels == 0) | (pixels == 1)).all()):
            raise ValueError("Archive requires actual binary Bernoulli samples")
        if (tokens.dtype != torch.long or tokens.shape != (len(pixels), CAPTION_LENGTH)
                or tokens.min() < 0 or tokens.max() >= len(VOCAB)):
            raise ValueError("Invalid actual categorical token paths")
        records = []
        arrays = (pixels.detach().cpu().numpy()[:, 0] * 255).astype(np.uint8)
        for array, token_row in zip(arrays, tokens.detach().cpu()):
            buffer = io.BytesIO()
            Image.fromarray(array).save(buffer, format="PNG")
            image_raw = buffer.getvalue()
            text_raw = render_tokens(token_row).encode("utf-8")
            record = {"required_output_complete": bool(text_raw.decode("utf-8").strip())}
            for kind, raw, suffix in (("image", image_raw, ".png"),
                                      ("text", text_raw, ".txt")):
                sha = hashlib.sha256(raw).hexdigest()
                name = f"{kind}s/{sha}{suffix}"
                if name not in self.members:
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o600 << 16
                    self.archive.writestr(info, raw)
                    self.members.add(name)
                record.update({kind + "_member": name, kind + "_sha256": sha})
            records.append(record)
        self.archive.fp.flush()
        os.fsync(self.archive.fp.fileno())
        decoded = [_read(self.archive, record) for record in records]
        self.samples += len(records)
        return torch.stack([item[0] for item in decoded]), [item[1] for item in decoded], records


def reopen_archive_records(path, records):
    """Independent consumer; verify hashes and decode the persisted bytes again."""
    if not records:
        raise ValueError("An empty raw-media census cannot be scored")
    with zipfile.ZipFile(path, "r") as archive:
        values = [_read(archive, record) for record in records]
    return torch.stack([value[0] for value in values]), [value[1] for value in values]
