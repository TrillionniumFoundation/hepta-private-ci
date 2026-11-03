"""Fashion-only output transport; references and labels belong only to scoring.

Rows use the existing text/image payload shapes and their actual validators.
This batch wrapper is not a RunSpec or a grant of runtime authority.
"""

import json

import numpy as np

from contracts import ContractError
from multimodal_contract import Modality, _payload


SCHEMA = "hepta.fashion-mnist.output-batch.v1"
WORDS = ("T-shirt/top", "Trouser", "Pullover", "Dress", "Coat", "Sandal",
         "Shirt", "Sneaker", "Bag", "Ankle boot")
MAX_ROWS = 64
MAX_WIRE_BYTES = 16 * 2**20


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ContractError("missing or unknown Fashion output fields")


def _float_array(value, shape, name):
    try:
        array = np.asarray(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ContractError("invalid " + name) from error
    if (array.shape != shape or array.dtype.kind != "f"
            or not np.isfinite(array).all() or np.any(array < 0) or np.any(array > 1)):
        raise ContractError("invalid " + name + " shape or finite normalized floats")
    return array


def encode(p, mu):
    """Encode 1..64 probability/gray rows, with no label or reference channel.

    p has shape [N,10]; mu has shape [N,28,28] and is already clipped to [0,1].
    Actual transmitted pixels are float32 RGB with three identical planes.
    """
    try:
        probabilities = np.asarray(p)
    except (TypeError, ValueError, OverflowError) as error:
        raise ContractError("invalid Fashion probabilities") from error
    if probabilities.ndim != 2 or not 1 <= len(probabilities) <= MAX_ROWS:
        raise ContractError("Fashion probability batch shape outside bounds")
    n = len(probabilities)
    probabilities = _float_array(probabilities, (n, 10), "probabilities")
    if not np.allclose(probabilities.sum(axis=1, dtype=np.float64), 1, rtol=0, atol=1e-6):
        raise ContractError("Fashion probabilities must sum to one")
    gray = _float_array(mu, (n, 28, 28), "mean pixels").astype(np.float32)
    rows = []
    for category, plane in zip(probabilities.argmax(axis=1), gray):
        text = {"encoding": "utf-8", "text": WORDS[int(category)]}
        image = {"dtype": "float32", "color_space": "RGB",
                 "pixels": np.repeat(plane[:, :, None], 3, axis=2)}
        # Existing payload validation, independent of the legacy RGB8 backend.
        _payload(Modality.TEXT, text, None)
        pixels = _payload(Modality.IMAGE, image, None).pixels
        rows.append({"text": text, "image": {**image, "pixels": pixels.tolist()}})
    raw = json.dumps({"schema": SCHEMA, "rows": rows}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_WIRE_BYTES:
        raise ContractError("Fashion wire byte bound exceeded")
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate Fashion wire field")
        result[key] = value
    return result


def decode(payload):
    """Decode actual UTF-8 wire bytes to canonical words and readonly float32 gray."""
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_WIRE_BYTES:
        raise ContractError("Fashion wire byte bound exceeded")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as error:
        raise ContractError("invalid Fashion wire JSON") from error
    _keys(value, ("schema", "rows"))
    if value["schema"] != SCHEMA:
        raise ContractError("unsupported Fashion output schema")
    rows = value["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ContractError("Fashion output row count outside bounds")
    words, planes = [], []
    for row in rows:
        _keys(row, ("text", "image"))
        text = _payload(Modality.TEXT, row["text"], None)
        image = _payload(Modality.IMAGE, row["image"], None)
        pixels = image.pixels
        if text.text not in WORDS:
            raise ContractError("unknown Fashion category word")
        if pixels.shape != (28, 28, 3):
            raise ContractError("Fashion image must be 28x28 RGB")
        if (not np.array_equal(pixels[:, :, 0], pixels[:, :, 1])
                or not np.array_equal(pixels[:, :, 0], pixels[:, :, 2])):
            raise ContractError("Fashion RGB channels must be identical")
        words.append(text.text)
        planes.append(pixels[:, :, 0])
    gray = np.stack(planes)
    gray.flags.writeable = False
    return tuple(words), gray


def score(payload, clean, labels):
    """Score every decoded row offline; clean is normalized [N,28,28] floats.

    Support is the predeclared clean>0.1 scoring definition, not an official
    mask. Empty regions have NaN MSE and count zero; sums/counts are returned
    for valid all-row aggregation. No classification-based filtering occurs.
    """
    words, gray = decode(payload)
    n = len(words)
    reference = _float_array(clean, (n, 28, 28), "clean reference").astype(np.float64)
    classes = np.asarray(labels)
    if (classes.shape != (n,) or classes.dtype.kind not in "iu"
            or np.any(classes < 0) or np.any(classes >= len(WORDS))):
        raise ContractError("invalid offline Fashion labels")
    squared = (gray.astype(np.float64) - reference) ** 2
    mse = squared.mean(axis=(1, 2))
    accuracy = np.array([word == WORDS[int(label)] for word, label in zip(words, classes)], dtype=np.float64)
    with np.errstate(divide="ignore"):
        psnr = -10 * np.log10(mse)
    result = {"accuracy": accuracy, "mse": mse, "psnr": psnr,
              "utility": accuracy * np.exp(-mse / .04)}
    support = reference > .1
    for name, mask in (("support", support), ("background", ~support)):
        counts = mask.sum(axis=(1, 2))
        error_sum = np.sum(squared * mask, axis=(1, 2))
        region_mse = np.full(n, np.nan)
        np.divide(error_sum, counts, out=region_mse, where=counts > 0)
        result.update({name + "_mse": region_mse, name + "_pixels": counts,
                       name + "_squared_error": error_sum})
    return result
