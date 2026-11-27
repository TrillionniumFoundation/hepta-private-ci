"""Frozen Fashion TRAIN intake and corruption; no TEST or network interface.

Importing this module reads no files or data. Labels/identities are offline
metadata, never service features. The source unit is exact published pixels,
not an independently verified physical-product identifier.
"""

import gzip
import hashlib
import io
from pathlib import Path
import struct
import zlib

import numpy as np


EXPECTED_ROWS = 60000
PIXELS = 784
POLICY_GROUPS = 512
SIGMA = .20
NUMPY_VERSION = "2.3.5"
SPLIT_SALT = b"hepta-fashion-split-v1\0"
NOISE_SALT = b"hepta-fashion-noise-v1\0"
POLICY_SALT = b"hepta-fashion-policy-v1\0"
OOF_SALT = b"hepta-fashion-oof-v1\0"
OFFICIAL_MD5 = {
    "train-images-idx3-ubyte.gz": "8d4fb7e6c68d591d4c3dfef9ec88bf0d",
    "train-labels-idx1-ubyte.gz": "25c81989df183df01b3e8a0aad5dffbe",
}
CLASS_WORDS = ("T-shirt/top", "Trouser", "Pullover", "Dress", "Coat", "Sandal",
               "Shirt", "Sneaker", "Bag", "Ankle boot")


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _rank(salt, pixel_digest):
    return hashlib.sha256(salt + pixel_digest).digest()


def _images(images):
    if (not isinstance(images, np.ndarray) or images.dtype != np.uint8
            or images.ndim != 2 or images.shape[1] != PIXELS
            or not 1 <= len(images) <= EXPECTED_ROWS):
        raise ValueError("bounded uint8 [N,784] published pixels required")
    return images


def _arrays(images, labels):
    _images(images)
    if (not isinstance(labels, np.ndarray) or labels.dtype != np.uint8
            or labels.shape != (len(images),) or np.any(labels >= 10)):
        raise ValueError("one uint8 class 0..9 per image required")


def _class_counts(labels, indices):
    return np.bincount(labels[np.asarray(indices, dtype=np.int64)], minlength=10).tolist()


def _all_classes(counts, where):
    if not all(counts):
        raise ValueError("missing class in " + where + "; fixed salts are not retried")


def parse_idx(images_idx, labels_idx, *, expected_rows=EXPECTED_ROWS):
    """Strict pure IDX decoder; small expected_rows is for handmade fixtures."""
    if (type(expected_rows) is not int or not 1 <= expected_rows <= EXPECTED_ROWS
            or not isinstance(images_idx, bytes) or not isinstance(labels_idx, bytes)
            or len(images_idx) < 16 or len(labels_idx) < 8):
        raise ValueError("bounded complete IDX byte strings required")
    magic, count, height, width = struct.unpack(">IIII", images_idx[:16])
    label_magic, label_count = struct.unpack(">II", labels_idx[:8])
    if ((magic, count, height, width) != (2051, expected_rows, 28, 28)
            or (label_magic, label_count) != (2049, expected_rows)
            or len(images_idx) != 16 + expected_rows * PIXELS
            or len(labels_idx) != 8 + expected_rows):
        raise ValueError("TRAIN IDX magic/count/shape/payload mismatch")
    images = np.frombuffer(images_idx, dtype=np.uint8, offset=16).reshape(count, PIXELS).copy()
    labels = np.frombuffer(labels_idx, dtype=np.uint8, offset=8).copy()
    _arrays(images, labels)
    return images, labels


def _metadata(images, labels, *, policy_groups=POLICY_GROUPS):
    """Pure metadata builder; policy_groups is smaller only in handmade tests."""
    _arrays(images, labels)
    if type(policy_groups) is not int or not 1 <= policy_groups <= POLICY_GROUPS:
        raise ValueError("bounded fixed policy group count required")
    _all_classes(_class_counts(labels, range(len(labels))), "official TRAIN")
    groups, rows = {}, []
    for index, image in enumerate(images):
        pixel_digest = hashlib.sha256(image.tobytes()).digest()
        pixel_hash = pixel_digest.hex()
        bucket = int.from_bytes(_rank(SPLIT_SALT, pixel_digest), "big") % 6
        split = "FIT" if bucket < 4 else "SELECT" if bucket == 4 else "SCREEN"
        fold = int.from_bytes(_rank(OOF_SALT, pixel_digest), "big") % 3
        group = groups.setdefault(pixel_hash, {"indices": [], "labels": [],
            "split": split, "fold": fold, "policy_group": False})
        group["indices"].append(index)
        group["labels"].append(int(labels[index]))
        rows.append({"row_id": index, "pixel_sha256": pixel_hash, "split": split,
                     "policy_group": False, "fold": fold})
    fit_groups = [key for key, value in groups.items() if value["split"] == "FIT"]
    if len(fit_groups) < policy_groups:
        raise ValueError("not enough unique FIT groups; no resampling")
    fit_groups.sort(key=lambda key: (_rank(POLICY_SALT, bytes.fromhex(key)), key))
    chosen = fit_groups[:policy_groups]
    for key in chosen:
        groups[key]["policy_group"] = True
        for index in groups[key]["indices"]:
            rows[index]["policy_group"] = True
    indices = {name: [index for index, row in enumerate(rows) if row["split"] == name]
               for name in ("FIT", "SELECT", "SCREEN")}
    indices["POLICY"] = [index for key in chosen for index in groups[key]["indices"]]
    counts = {}
    for name, selected in indices.items():
        class_counts = _class_counts(labels, selected)
        _all_classes(class_counts, name)
        counts[name] = {"rows": len(selected), "class_counts": class_counts,
                       "groups": len({rows[index]["pixel_sha256"] for index in selected})}
    oof = {}
    for fold in range(3):
        hold = [index for index in indices["POLICY"] if rows[index]["fold"] == fold]
        train = [index for index in indices["POLICY"] if rows[index]["fold"] != fold]
        if not hold or not train:
            raise ValueError("empty policy OOF train/hold fold; no salt fallback")
        oof[str(fold)] = {"hold_indices": hold, "train_indices": train,
            "hold_class_counts": _class_counts(labels, hold),
            "train_class_counts": _class_counts(labels, train)}
    for group in groups.values():
        group.update(multiplicity=len(group["indices"]),
                     conflicting_labels=len(set(group["labels"])) > 1)
    return {"schema": "hepta.fashion.TRAIN-data.v1", "rows": rows,
        "source_unit": "exact-reference-pixel SHA256; no independently verified SKU mapping",
        "group_count": len(groups), "groups": dict(sorted(groups.items())),
        "indices": indices, "counts": counts, "policy_group_order": chosen, "oof": oof,
        "duplicate_rows": len(images)-len(groups),
        "conflicting_label_groups": sorted(key for key, value in groups.items()
                                           if value["conflicting_labels"]),
        "images_sha256": _hash(images.tobytes()), "labels_sha256": _hash(labels.tobytes()),
        "original_row_weights": "one per original row; duplicates retained with original multiplicity",
        "class_words": list(CLASS_WORDS), "salts": {"split": SPLIT_SALT.decode(),
            "noise": NOISE_SALT.decode(), "policy": POLICY_SALT.decode(), "oof": OOF_SALT.decode()},
        "noise": {"sigma": SIGMA, "numpy_version": NUMPY_VERSION, "rng": "PCG64DXSM",
            "seed": "first 128 bits big-endian SHA256(noise_salt || raw pixel digest)",
            "equation": "float64 raw/255 + sigma*float64 standard_normal; clip; cast once float32"}}


def noisy_images(images):
    """Fixed pixel-group noise only; no labels, row IDs or seeds accepted."""
    _images(images)
    if np.__version__ != NUMPY_VERSION:
        raise ValueError("fixed noise requires NumPy " + NUMPY_VERSION)
    noisy = np.empty(images.shape, dtype=np.float32)
    seen = {}
    for index, image in enumerate(images):
        pixel_digest = hashlib.sha256(image.tobytes()).digest()
        if pixel_digest in seen:
            noisy[index] = noisy[seen[pixel_digest]]
            continue
        seed = int.from_bytes(_rank(NOISE_SALT, pixel_digest)[:16], "big")
        rng = np.random.Generator(np.random.PCG64DXSM(seed))
        epsilon = rng.standard_normal(PIXELS)
        noisy[index] = np.clip(image.astype(np.float64)/255.0 + SIGMA*epsilon, 0., 1.).astype(np.float32)
        seen[pixel_digest] = index
    return noisy


def service_input(noisy):
    """Whitelisted service payload; never include offline identity/target fields."""
    if (not isinstance(noisy, np.ndarray) or noisy.dtype != np.float32
            or noisy.ndim != 2 or noisy.shape[1] != PIXELS or not 1 <= len(noisy) <= EXPECTED_ROWS
            or not np.isfinite(noisy).all() or np.any(noisy < 0) or np.any(noisy > 1)):
        raise ValueError("finite float32 noisy [N,784] service input required")
    value = noisy.copy()
    value.flags.writeable = False
    return {"noisy": value, "sigma": SIGMA}


def _gzip_payload(compressed, expected_size):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            value = stream.read(expected_size + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError("invalid TRAIN gzip") from error
    if len(value) != expected_size:
        raise ValueError("bounded TRAIN gzip payload size mismatch")
    return value


def load_train(localdir, *, expected_sha256=None, cache_noisy=False):
    """Read exactly the two local official TRAIN files; never fetch or read TEST.

    Publisher MD5 is mandatory. SHA256 is always observed/recorded and also
    verified when caller supplies both expected pins. A missing SHA pin is not
    reported as a verified pin. cache_noisy materializes FIT only, never SCREEN.
    """
    if type(cache_noisy) is not bool:
        raise ValueError("cache_noisy must be boolean")
    if expected_sha256 is not None and (not isinstance(expected_sha256, dict)
            or set(expected_sha256) != set(OFFICIAL_MD5)
            or any(not isinstance(value, str) or len(value) != 64
                   or any(c not in "0123456789abcdef" for c in value)
                   for value in expected_sha256.values())):
        raise ValueError("exact two lowercase TRAIN SHA256 pins required")
    directory = Path(localdir)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("existing regular local TRAIN directory required")
    payloads, files = {}, {}
    for filename, expected_md5 in OFFICIAL_MD5.items():
        path = directory/filename
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular local TRAIN file required: " + filename)
        image_file = filename.startswith("train-images")
        bound = 32*1024**2 if image_file else 128*1024
        with path.open("rb") as stream:
            compressed = stream.read(bound + 1)
        if len(compressed) > bound:
            raise ValueError("compressed TRAIN byte bound exceeded")
        observed_md5, observed_sha = hashlib.md5(compressed).hexdigest(), _hash(compressed)
        if observed_md5 != expected_md5:
            raise ValueError("publisher TRAIN MD5 mismatch: " + filename)
        expected_sha = None if expected_sha256 is None else expected_sha256[filename]
        if expected_sha is not None and observed_sha != expected_sha:
            raise ValueError("pinned TRAIN SHA256 mismatch: " + filename)
        size = 16 + EXPECTED_ROWS*PIXELS if image_file else 8 + EXPECTED_ROWS
        payloads[filename] = _gzip_payload(compressed, size)
        files[filename] = {"compressed_bytes": len(compressed), "md5": observed_md5,
            "publisher_md5_verified": True, "sha256": observed_sha,
            "expected_sha256": expected_sha, "sha256_pin_verified": expected_sha is not None,
            "IDX_bytes": size}
    images, labels = parse_idx(*(payloads[name] for name in OFFICIAL_MD5), expected_rows=EXPECTED_ROWS)
    metadata = _metadata(images, labels)
    metadata.update(files=files, original_rows=EXPECTED_ROWS, official_TEST_accessed=False)
    images.flags.writeable = labels.flags.writeable = False
    indices = {key: np.asarray(value, dtype=np.int64) for key, value in metadata["indices"].items()}
    fit_cache = noisy_images(images[indices["FIT"]]) if cache_noisy else None
    return {"images": images, "labels": labels, "metadata": metadata, "indices": indices,
            "noisy": fit_cache, "noisy_indices": indices["FIT"].copy() if cache_noisy else None}
