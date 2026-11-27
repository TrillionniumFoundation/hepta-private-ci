"""Source-disjoint MNIST pair tasks with explicitly constructed instructions.

The source pixels are genuine MNIST images. Pair layouts, occlusions and textual
instructions are a bounded experimental task, not natural unrestricted media.
Only Observation may enter an inference backend; Target is training/evaluation
truth. Neither targets nor source labels are fields of Observation.
"""

from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import random
import struct
import urllib.request

import torch


VOCAB = (
    "<pad>", "<bos>", "<eos>", "left", "right", "relation", "less", "equal",
    "greater", "keep", "swap", "unknown", "hint_left", "hint_right",
) + tuple(str(i) for i in range(10))
PAD, BOS, EOS, DIGIT_OFFSET = 0, 1, 2, 14
CAPTION_LENGTH = 8
SOURCE_BASE = "https://ossci-datasets.s3.amazonaws.com/mnist/"
# These published checksums are also used by torchvision.datasets.MNIST.
RESOURCES = (
    ("train-images-idx3-ubyte.gz", "f68b3c2dcbeaaa9fbdd348bbdeb94873"),
    ("train-labels-idx1-ubyte.gz", "d53e105ee54ea40749a09fcbcd1e9432"),
    ("t10k-images-idx3-ubyte.gz", "9fb629c4189551a2d022fa330f9573f3"),
    ("t10k-labels-idx1-ubyte.gz", "ec29112dd5afa0611ce80d1b7f02629c"),
)


@dataclass(frozen=True)
class Observation:
    pixels: torch.Tensor
    mask: torch.Tensor
    text_tokens: torch.Tensor


@dataclass(frozen=True)
class Target:
    pixels: torch.Tensor
    text_tokens: torch.Tensor
    labels: torch.Tensor


@dataclass(frozen=True)
class Batch:
    observation: Observation
    target: Target
    source_ids: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SourceSplit:
    images: torch.Tensor
    labels: torch.Tensor
    ids: tuple[str, ...]
    pixel_hashes: tuple[str, ...]

    def __len__(self):
        return len(self.ids)


@dataclass(frozen=True)
class SourceCorpus:
    splits: dict[str, SourceSplit]
    manifest: dict


def render_tokens(tokens):
    """Render actual emitted tokens without repairing their grammar/content."""
    result = []
    for item in tokens:
        index = int(item)
        if index == EOS:
            break
        if index in (PAD, BOS):
            continue
        result.append(VOCAB[index] if 0 <= index < len(VOCAB) else "<invalid>")
    return " ".join(result)


def _resource(cache_dir, name, expected_md5):
    path = cache_dir / name
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".download")
        with urllib.request.urlopen(SOURCE_BASE + name, timeout=60) as response:
            payload = response.read()
        if hashlib.md5(payload).hexdigest() != expected_md5:
            raise ValueError(f"MNIST published checksum mismatch: {name}")
        temporary.write_bytes(payload)
        temporary.replace(path)
    raw = path.read_bytes()
    if hashlib.md5(raw).hexdigest() != expected_md5:
        raise ValueError(f"MNIST cached checksum mismatch: {name}")
    return gzip.decompress(raw), {
        "name": name, "url": SOURCE_BASE + name,
        "md5": expected_md5, "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _parse_images(payload):
    magic, count, height, width = struct.unpack(">IIII", payload[:16])
    if (magic, height, width) != (2051, 28, 28) or len(payload) != 16 + 784 * count:
        raise ValueError("Invalid MNIST image IDX header or length")
    raw_pixels = payload[16:]
    hashes = tuple(hashlib.sha256(raw_pixels[i:i + 784]).hexdigest()
                   for i in range(0, len(raw_pixels), 784))
    pixels = torch.frombuffer(bytearray(raw_pixels), dtype=torch.uint8)
    return pixels.reshape(count, 1, 28, 28), hashes


def _parse_labels(payload):
    magic, count = struct.unpack(">II", payload[:8])
    if magic != 2049 or len(payload) != 8 + count:
        raise ValueError("Invalid MNIST label IDX header or length")
    labels = torch.frombuffer(bytearray(payload[8:]), dtype=torch.uint8).long()
    if torch.any(labels > 9):
        raise ValueError("Invalid MNIST class")
    return labels


def load_corpus(cache_dir, train_sources=10000, validation_sources=2000,
                evaluator_sources=5000, retention_sources=1000,
                test_sources=2000, seed=271828):
    """Download checked originals; split unique pixel identities, not pairs.

    Test uses official test sources. Conflicting labels for identical pixels are
    excluded. Official-train pixels duplicated in official-test are excluded
    from all train-derived splits. Evaluator training has its own source pool.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    counts = {
        "train": train_sources, "validation": validation_sources,
        "evaluator": evaluator_sources, "retention": retention_sources,
        "test": test_sources,
    }
    if any(not isinstance(n, int) or n < 2 for n in counts.values()):
        raise ValueError("Every source split requires at least two images")
    loaded = [_resource(cache_dir, *resource) for resource in RESOURCES]
    train_images, train_hashes = _parse_images(loaded[0][0])
    train_labels = _parse_labels(loaded[1][0])
    test_images, test_hashes = _parse_images(loaded[2][0])
    test_labels = _parse_labels(loaded[3][0])
    if len(train_images) != len(train_labels) or len(test_images) != len(test_labels):
        raise ValueError("MNIST image/label cardinality mismatch")
    observed_labels = {}
    conflicts = set()
    for hashes, labels in ((train_hashes, train_labels), (test_hashes, test_labels)):
        for digest, label in zip(hashes, labels.tolist()):
            previous = observed_labels.setdefault(digest, label)
            if previous != label:
                conflicts.add(digest)
    test_hash_set = set(test_hashes)
    eligible = {}
    for name, hashes in (("train", train_hashes), ("test", test_hashes)):
        seen = set()
        indices = []
        for index, digest in enumerate(hashes):
            if digest in conflicts or digest in seen:
                continue
            seen.add(digest)
            if name == "train" and digest in test_hash_set:
                continue
            indices.append(index)
        random.Random(seed + (1 if name == "test" else 0)).shuffle(indices)
        eligible[name] = indices
    need_train = sum(counts[name] for name in counts if name != "test")
    if need_train > len(eligible["train"]) or test_sources > len(eligible["test"]):
        raise ValueError("Requested split sizes exceed unique MNIST sources")
    splits = {}
    manifest_splits = {}
    offset = 0
    for name, count in counts.items():
        origin = "test" if name == "test" else "train"
        start = 0 if origin == "test" else offset
        indices = eligible[origin][start:start + count]
        if origin == "train":
            offset += count
        images, labels, hashes = ((test_images, test_labels, test_hashes)
                                 if origin == "test" else
                                 (train_images, train_labels, train_hashes))
        selected_hashes = tuple(hashes[index] for index in indices)
        identities = tuple(f"mnist:{origin}:{index}:{hashes[index]}" for index in indices)
        splits[name] = SourceSplit(images[indices].clone(), labels[indices].clone(),
                                   identities, selected_hashes)
        manifest_splits[name] = {
            "count": count, "official_partition": origin,
            "identity_sha256": hashlib.sha256("\n".join(identities).encode()).hexdigest(),
            "pixel_set_sha256": hashlib.sha256(
                "\n".join(sorted(selected_hashes)).encode()).hexdigest(),
        }
    all_hashes = [digest for split in splits.values() for digest in split.pixel_hashes]
    if len(all_hashes) != len(set(all_hashes)):
        raise AssertionError("Source leakage across benchmark splits")
    manifest = {
        "schema": "hepta.ndu-v6.mnist-source-manifest.v1",
        "dataset": "MNIST", "split_seed": seed,
        "task": "constructed handwritten pair reconstruction and relation caption",
        "source_files": [entry[1] for entry in loaded], "splits": manifest_splits,
        "conflicting_pixel_identities_excluded": len(conflicts),
        "cross_split_duplicate_pixel_identities": 0,
        "neural_modalities": ["text", "image"],
        "unsupported_neural_modalities": ["audio", "video"],
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return SourceCorpus(splits, manifest)


def make_batch(corpus, split, batch_size, seed, corruption="train", offset=None,
               drop_hint=False):
    """Construct examples; offset addresses source-disjoint evaluation pairs.

    Textual hints are declared input evidence for a missing source digit, not a
    hidden label channel. A hint gives a class, never its original handwriting.
    """
    if corruption not in {"train", "clean", "occlusion", "missing", "heavy_noise"}:
        raise ValueError(f"Unknown corruption: {corruption}")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    source = corpus.splits[split]
    rng = torch.Generator().manual_seed(int(seed))
    if offset is None:
        left = torch.randint(len(source), (batch_size,), generator=rng)
        right = (left + torch.randint(1, len(source), (batch_size,), generator=rng)) % len(source)
    else:
        if offset < 0 or 2 * (offset + batch_size) > len(source):
            raise ValueError("No-replacement evaluation pair range exceeds source split")
        left = torch.arange(2 * offset, 2 * (offset + batch_size), 2)
        right = left + 1
    pixels = torch.cat((source.images[left], source.images[right]), dim=3).float() / 255
    source_labels = torch.stack((source.labels[left], source.labels[right]), dim=1)
    swap = torch.randint(2, (batch_size,), generator=rng).bool()
    target_pixels = pixels.clone()
    target_pixels[swap] = torch.cat((pixels[swap, :, :, 28:], pixels[swap, :, :, :28]), dim=3)
    labels = source_labels.clone()
    labels[swap] = labels[swap].flip(1)
    captions = torch.tensor([BOS, 3, 0, 4, 0, 5, 0, EOS]).repeat(batch_size, 1)
    captions[:, 2], captions[:, 4] = labels[:, 0] + DIGIT_OFFSET, labels[:, 1] + DIGIT_OFFSET
    captions[:, 6] = torch.sign(labels[:, 0] - labels[:, 1]) + 7
    tokens = torch.tensor([BOS, 9, 12, 11, 13, 11, EOS, PAD]).repeat(batch_size, 1)
    tokens[:, 1] = 9 + swap.long()
    mask = torch.ones_like(pixels)
    noise_scale = {"train": .12, "clean": 0., "occlusion": .08,
                   "missing": .08, "heavy_noise": .4}[corruption]
    if corruption != "clean":
        side = torch.randint(2, (batch_size,), generator=rng)
        missing = (torch.ones(batch_size, dtype=torch.bool) if corruption == "missing"
                   else torch.rand(batch_size, generator=rng) < (.2 if corruption == "train" else 0.))
        for index in range(batch_size):
            if missing[index]:
                digit_side = int(side[index])
                mask[index, :, :, 28 * digit_side:28 * (digit_side + 1)] = 0
                if not drop_hint:
                    tokens[index, 3 + 2 * digit_side] = source_labels[index, digit_side] + DIGIT_OFFSET
            else:
                width = 11 if corruption == "occlusion" else 6
                row = int(torch.randint(0, 29 - width, (), generator=rng))
                col = int(torch.randint(0, 57 - width, (), generator=rng))
                mask[index, :, row:row + width, col:col + width] = 0
    public_pixels = (pixels + noise_scale * torch.randn(pixels.shape, generator=rng)).clamp(0, 1) * mask
    identities = tuple((source.ids[int(i)], source.ids[int(j)]) for i, j in zip(left, right))
    return Batch(Observation(public_pixels, mask, tokens),
                 Target(target_pixels, captions, labels), identities)
