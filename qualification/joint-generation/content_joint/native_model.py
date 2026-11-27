"""One semantic categorical law, shared encoder and unchanged RGB decoder."""

import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from model import JointModel, _read_tensor, softmax


KEYS = ("encoder", "bias", "shared", "shared_bias")


class Native12:
    _input = JointModel._input
    decode_images = JointModel.decode_images
    apply_gradients = JointModel.apply_gradients

    def __init__(self, base):
        if tuple(base.dimensions) != (202, 12, 192, 32):
            raise ValueError("fixed original decoder/encoder geometry required")
        self.dimensions = tuple(base.dimensions)
        self.params = {key: base.params[key].copy()
                       for key in ("encoder", "bias", "decoder", "decoder_bias")}
        self.params["shared"] = base.params["text"] + base.params["image"]
        self.params["shared_bias"] = base.params["text_bias"] + base.params["image_bias"]
        self._moments, self.updates = {}, 0

    def state(self, x):
        x = self._input(x)
        h = np.tanh(x @ self.params["encoder"] + self.params["bias"])
        s = softmax(h @ self.params["shared"] + self.params["shared_bias"])
        return h, s

    def forward(self, x):
        return self.state(x)[1]

    def digest(self):
        result = hashlib.sha256(json.dumps(self.dimensions).encode())
        for key in sorted(self.params):
            result.update(key.encode())
            result.update(self.params[key].astype("<f8", copy=False).tobytes())
        return result.hexdigest()

    def save(self, path):
        np.savez_compressed(path, native12_version=np.asarray([1]),
                            dimensions=np.asarray(self.dimensions), **self.params)

    @classmethod
    def load(cls, path):
        if Path(path).stat().st_size > 16_000_000:
            raise ValueError("oversized native bundle")
        shapes = dict(encoder=(202, 32), bias=(32,), shared=(32, 12),
                      shared_bias=(12,), decoder=(12, 192), decoder_bias=(192,))
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            expected = {key + ".npy" for key in shapes} | {"dimensions.npy", "native12_version.npy"}
            if len(names) != len(set(names)) or set(names) != expected:
                raise ValueError("invalid native tensor inventory")
            dims = _read_tensor(archive, "dimensions", (4,), "integer")
            version = _read_tensor(archive, "native12_version", (1,), "integer")
            if tuple(dims) != (202, 12, 192, 32) or version[0] != 1:
                raise ValueError("invalid native geometry/version")
            out = cls.__new__(cls)
            out.dimensions = tuple(int(x) for x in dims)
            out.params = {key: _read_tensor(archive, key, shape, "float64")
                          for key, shape in shapes.items()}
            out._moments, out.updates = {}, 0
            return out
