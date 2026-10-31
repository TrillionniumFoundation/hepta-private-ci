"""Preserve actual delivered PNG/UTF-8 bytes with content-addressed ZIP storage.

This changes storage only. The unchanged task writes and reopens previews before
feature extraction, commits the decision before continuation, then reopens the
selected final output. No preview is reconstructed after the action decision.
"""

from copy import deepcopy
import hashlib
import io
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import torch


class MediaStore:
    def __init__(self, path):
        self.path = Path(path)
        self.archive = zipfile.ZipFile(self.path, "x", compression=zipfile.ZIP_STORED,
                                       allowZip64=True)
        self.identities = {}
        self.logical_files = self.unique_bytes = 0

    def ingest(self, receipt):
        result = deepcopy(receipt)
        result["archive"] = self.path.name
        for role, source in receipt["paths"].items():
            raw = Path(source).read_bytes()
            identity = hashlib.sha256(raw).hexdigest()
            if identity != receipt["sha256"][role]:
                raise ValueError("Delivered media changed before content-addressed preservation")
            suffix = Path(source).suffix
            if suffix not in {".png", ".txt"}:
                raise ValueError("Unexpected delivered media type")
            name = f"sha256/{identity[:2]}/{identity}{suffix}"
            if name not in self.identities:
                self.archive.writestr(name, raw)
                self.identities[name] = (identity, len(raw))
                self.unique_bytes += len(raw)
            elif self.identities[name] != (identity, len(raw)):
                raise RuntimeError("Inconsistent content-addressed identity")
            result["paths"][role] = name
            self.logical_files += 1
        return result

    def close(self):
        self.archive.close()
        return {"schema": "hepta.field-bridge.v2.media-store.1", "archive": self.path.name,
                "unique_files": len(self.identities), "logical_files": self.logical_files,
                "unique_payload_bytes": self.unique_bytes,
                "storage": "ZIP_STORED; exact original PNG and UTF-8 bytes; duplicate content stored once"}


def read_media(archive, receipt):
    raw = {key: archive.read(path) for key, path in receipt["paths"].items()}
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}
    if hashes != receipt["sha256"]:
        raise ValueError("Preserved media bytes differ from delivered output")
    # write_bundle uses image/text roles; preserve the same grayscale quantization.
    with Image.open(io.BytesIO(raw["image"])) as source:
        if source.mode != "L" or source.size != (56, 28):
            raise ValueError("Invalid delivered grayscale PNG")
        pixels = torch.from_numpy(np.array(source, dtype=np.uint8, copy=True)).float()[None, None] / 255
    caption = raw["text"].decode("utf-8")
    return pixels, caption, hashes
