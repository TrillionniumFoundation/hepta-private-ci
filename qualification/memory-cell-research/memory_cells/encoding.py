"""Frozen, data-independent feature encoder for the bounded CPU research profile.

This is signed feature hashing, not a pretrained language model. Its manifest is
the complete shared encoder: no training vocabulary or record values are stored.
"""

import hashlib
import json
import re
import unicodedata

import numpy as np


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


class FrozenEncoder:
    """Map text to deterministic normalized features without fitting on examples."""

    def __init__(self, dim=128, seed=0):
        if type(dim) is not int or not 8 <= dim <= 4096:
            raise ValueError("encoder dimension must be an integer in [8, 4096]")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("encoder seed must be an unsigned 32-bit integer")
        self.dim = dim
        self.seed = seed

    def manifest(self):
        return {
            "schema": "hepta.memory-cell.encoder.v1",
            "algorithm": "signed-token-trigram-l2",
            "dim": self.dim,
            "seed": self.seed,
            "unicode": "NFKC-casefold",
            "token_weight": 3.0,
            "trigram_weight": 0.2,
        }

    @property
    def digest(self):
        return hashlib.sha256(canonical_bytes(self.manifest())).hexdigest()

    @classmethod
    def from_manifest(cls, manifest):
        if not isinstance(manifest, dict):
            raise ValueError("encoder manifest must be an object")
        encoder = cls(manifest.get("dim"), manifest.get("seed"))
        if manifest != encoder.manifest():
            raise ValueError("unsupported or modified encoder manifest")
        return encoder

    def encode(self, texts):
        if not isinstance(texts, (list, tuple)) or len(texts) > 65536:
            raise ValueError("texts must be a bounded list or tuple")
        result = np.zeros((len(texts), self.dim), dtype=np.float64)
        prefix = self.seed.to_bytes(4, "big")
        for row, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip() or len(text) > 16384:
                raise ValueError("each text must contain 1..16384 characters")
            normalized = unicodedata.normalize("NFKC", text).casefold()
            tokens = re.findall(r"[\w:/.-]+", normalized)
            features = [("token:" + token, 3.0) for token in tokens]
            for token in tokens:
                padded = "^" + token + "$"
                features.extend(
                    ("tri:" + padded[i : i + 3], 0.2)
                    for i in range(max(0, len(padded) - 2))
                )
            if not features:
                features = [("raw:" + normalized, 1.0)]
            for feature, weight in features:
                digest = hashlib.blake2b(
                    prefix + feature.encode(), digest_size=16
                ).digest()
                index = int.from_bytes(digest[:8], "big") % self.dim
                sign = 1.0 if digest[8] & 1 else -1.0
                result[row, index] += sign * weight
            norm = np.linalg.norm(result[row])
            if norm == 0:
                raise ValueError("input features cancel to zero")
            result[row] /= norm
        return result
