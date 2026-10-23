"""Opt-in, instance-local PNG reuse for a frozen learned 12-code RGB decoder.

This changes execution only. Every PNG/hash/base64 value is actually generated
from this instance's learned decoder during billed preparation. Sampling and
per-request caption/JSON serialization stay real. PNG/hash/base64/memory work
has byte counters and measured CPU, not invented arithmetic FLOP prices.
No dataset, label, renderer, task observer, global or cross-model cache is used.
The cache lasts only as long as its generator/measurement. This prototype covers
the finite twelve-code learned RGB8 decoder, with no AV, open-vocabulary or
photographic-generation claim. Payload byte counters describe array/string
contents, never Python heap size, peak allocation, RSS, or a measured speedup.
"""

import base64
from dataclasses import dataclass
import hashlib
import io
import json

import numpy as np
from PIL import Image

from data import caption
from model import JointModel
from independent.accounting import BudgetExceeded, WorkLedger
from independent.inference import FrozenGenerator


ROWWISE = "rowwise-png-v1"
CODEBOOK = "local-png-codebook-v1"
PROFILES = (ROWWISE, CODEBOOK)
MAX_CODEBOOK_ASCII_BYTES = 65536


def validate_profile(profile):
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError("unsupported output codec profile")
    return profile


def request_work(rows=1, classes=12):
    """Two draws, two CDFs, strict comparisons, reductions and clamping."""
    if type(rows) is not int or not 1 <= rows <= 65536 or classes != 12:
        raise ValueError("bounded twelve-class output rows required")
    return {"scalar_ops": rows * (4 * classes - 2),
            "compare_ops": rows * (2 * classes + 2)}


def preparation_work(classes=12, pixels=192):
    if classes != 12 or pixels != 192:
        raise ValueError("learned twelve-code RGB8 decoder required")
    elements = classes * pixels
    return {"scalar_ops": 5 * elements,
            "compare_ops": 4 * elements + (classes + 1) * pixels + 2 * classes,
            "exp_ops": elements, "div_ops": elements}


def _decoder(generator):
    if not isinstance(generator, FrozenGenerator) or generator.dimensions[:3] != (202, 12, 192):
        raise ValueError("immutable bounded FrozenGenerator required")
    decoder, bias = generator.params["decoder"], generator.params["decoder_bias"]
    if (decoder.dtype != np.float64 or bias.dtype != np.float64
            or decoder.shape != (12, 192) or bias.shape != (192,)
            or decoder.flags.writeable or bias.flags.writeable):
        raise ValueError("read-only learned decoder required")
    return decoder, bias


def _fingerprint(decoder, bias):
    return hashlib.sha256(decoder.tobytes(order="C") + bias.tobytes(order="C")).hexdigest()


@dataclass(frozen=True)
class LocalPNGCodebook:
    """Owned by one frozen generator, with immutable image-code entries."""

    _generator: FrozenGenerator
    _decoder_sha256: str
    _entries: tuple
    profile: str = CODEBOOK

    @property
    def storage(self):
        return {"entries": len(self._entries),
                "retained_encoded_ascii_bytes": sum(len(digest) + len(encoded) for digest, encoded, _ in self._entries),
                "retained_png_bytes": 0, "retained_decoded_array_bytes": 0,
                "payload_bound_bytes": MAX_CODEBOOK_ASCII_BYTES}

    def outputs(self, generator, p, q, ledger, sample_rng):
        if generator is not self._generator:
            raise ValueError("PNG codebook belongs to another generator")
        if not isinstance(ledger, WorkLedger):
            raise TypeError("WorkLedger required for output accounting")
        decoder, bias = _decoder(generator)
        ledger.record("output", decoder_binding_hash_bytes=decoder.nbytes + bias.nbytes)
        if _fingerprint(decoder, bias) != self._decoder_sha256:
            raise ValueError("learned decoder changed after PNG codebook preparation")
        n, k = p.shape
        if q.shape != p.shape or k != 12:
            raise ValueError("paired twelve-class output rows required")
        ledger.charge_kernel("output", "sample_categorical", **request_work(n, k))
        random_values = sample_rng.random((n, 2))
        choices = np.minimum(np.column_stack((
            (np.cumsum(p, axis=1) < random_values[:, 0, None]).sum(axis=1),
            (np.cumsum(q, axis=1) < random_values[:, 1, None]).sum(axis=1))), k - 1).tolist()
        outputs, sizes = [], []
        for text, image in choices:
            digest, encoded, png_size = self._entries[image]
            receipt = {"caption": caption(text), "choices": {"text": text, "image": image},
                       "png_sha256": digest, "png_base64": encoded}
            payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            outputs.append(receipt)
            sizes.append(png_size + len(payload))
        ledger.record("output", output_bytes=sum(sizes), serialized_requests=n,
                      png_codebook_lookups=n)
        return outputs, sizes


def prepare_codec(generator, profile, ledger, stage="prepare"):
    """Prepare once locally; the caller must include this entire call in CPU.

    Work caps are checked before decoding or encoding. A finite-validation
    failure bills only the scan actually attempted, never unexecuted decoding.
    The full canonical rowwise reference and service caps remain unchanged.
    """
    validate_profile(profile)
    if profile == ROWWISE:
        return None
    if not isinstance(ledger, WorkLedger):
        raise TypeError("WorkLedger required for codebook preparation")
    decoder, bias = _decoder(generator)
    work = preparation_work()
    if ledger.estimate_kernel(**work) > ledger.remaining_units:
        raise BudgetExceeded("PNG codebook preparation exceeds remaining work budget")
    validation = 13 * 192
    ledger.charge_kernel(stage, "decoder_finite_scan", compare_ops=validation)
    finite_decoder, finite_bias = np.isfinite(decoder).all(), np.isfinite(bias).all()
    if not finite_decoder or not finite_bias:
        raise ValueError("finite learned decoder required")
    decode_quantize = {**work, "compare_ops": work["compare_ops"] - validation}
    ledger.charge_kernel(stage, "decode_quantize_codebook", **decode_quantize,
        counts={"decoder_calls": 1, "decoder_elements": 12 * 192,
                "output_codec_prepare_calls": 1})
    images = JointModel.decode_images(generator, np.arange(12)).reshape(12, 8, 8, 3)
    images = np.rint(np.clip(images, 0, 1) * 255).astype(np.uint8)
    entries, total_bytes = [], 0
    for image in images:
        encoded = io.BytesIO()
        Image.fromarray(image).save(encoded, format="PNG")
        png = encoded.getvalue()
        entries.append((hashlib.sha256(png).hexdigest(), base64.b64encode(png).decode("ascii"), len(png)))
        total_bytes += len(png)
    ascii_bytes = sum(len(digest) + len(encoded) for digest, encoded, _ in entries)
    ledger.record(stage, png_encodes=12, png_hash_bytes=total_bytes,
                  base64_input_bytes=total_bytes, prepared_png_bytes=total_bytes,
                  prepared_decoded_array_payload_bytes=12 * 192 * 8,
                  prepared_quantized_array_payload_bytes=12 * 192,
                  retained_encoded_ascii_bytes=ascii_bytes, retained_decoded_array_bytes=0,
                  decoder_binding_hash_bytes=decoder.nbytes + bias.nbytes)
    if ascii_bytes > MAX_CODEBOOK_ASCII_BYTES:
        raise ValueError("local PNG codebook payload exceeds its bounded profile")
    return LocalPNGCodebook(generator, _fingerprint(decoder, bias), tuple(entries))
