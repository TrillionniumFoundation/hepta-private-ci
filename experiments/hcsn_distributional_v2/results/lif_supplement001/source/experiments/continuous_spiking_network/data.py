"""Auditable sequence datasets; no downloads or fitted preprocessing at import."""

from dataclasses import dataclass, field
import gzip
import hashlib
import json
from pathlib import Path
import struct
import wave

import numpy as np


DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "hcsn-data"
FSDD_COMMIT = "26eb9aaf76e81b692f806f9140c2d2777410d7a1"
SPEAKER_SPLITS = {
    "train": ("george", "jackson", "nicolas"),
    "val": ("theo",),
    "test": ("lucas", "yweweler"),
}
FEATURE_NAMES = tuple(
    [f"image_column_{i}" for i in range(28)]
    + [f"audio_mel_{i}" for i in range(20)]
    + [
        "image_present",
        "audio_present",
        "query_present",
        "position",
        "quality",
        "event_present",
    ]
    + [
        "identify",
        "image",
        "spoken",
        "digit",
        "both",
        "question",
        "key_0",
        "key_1",
        "key_2",
        "key_3",
    ]
)
TASKS = ("synthetic", "long_memory", "mnist", "fsdd", "multimodal", "multimodal_select")


@dataclass
class SplitData:
    x: np.ndarray
    dt: np.ndarray
    y: np.ndarray
    group_ids: np.ndarray
    sample_ids: np.ndarray
    metadata: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.y)

    def validate(self):
        if self.x.ndim != 3 or self.x.shape[:2] != self.dt.shape:
            raise ValueError("Expected x[N,T,F] and dt[N,T].")
        n = len(self.x)
        if (
            self.y.shape != (n,)
            or len(self.group_ids) != n
            or len(self.sample_ids) != n
        ):
            raise ValueError(
                "Labels and source identifiers must match the sample axis."
            )
        if (
            not np.isfinite(self.x).all()
            or not np.isfinite(self.dt).all()
            or np.any(self.dt <= 0)
        ):
            raise ValueError(
                "Inputs must be finite and every time increment strictly positive."
            )
        if (
            self.x.dtype != np.float32
            or self.dt.dtype != np.float32
            or self.y.dtype != np.int64
        ):
            raise ValueError("Dataset dtypes must be float32, float32 and int64.")
        if len(set(self.sample_ids.tolist())) != n:
            raise ValueError("Episode identifiers must be unique within a split.")
        return self


@dataclass
class DataBundle:
    train: SplitData
    val: SplitData
    test: SplitData
    feature_names: tuple
    class_names: tuple
    manifest: dict

    @property
    def input_dim(self):
        return len(self.feature_names)

    @property
    def num_classes(self):
        return len(self.class_names)

    def validate(self):
        splits = (self.train, self.val, self.test)
        for split in splits:
            split.validate()
            if split.x.shape[-1] != self.input_dim or np.any(
                (split.y < 0) | (split.y >= self.num_classes)
            ):
                raise ValueError(
                    "Feature or class dimension disagrees with the bundle."
                )
        for a, b in ((0, 1), (0, 2), (1, 2)):
            for key in ("image_source_ids", "audio_source_ids"):
                left = set(splits[a].metadata.get(key, [])) - {""}
                right = set(splits[b].metadata.get(key, [])) - {""}
                if left & right:
                    raise ValueError(f"Source leakage between splits: {key}.")
            if set(splits[a].sample_ids) & set(splits[b].sample_ids):
                raise ValueError("Episode leakage between splits.")
        return self


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expand_context(x, dt, length):
    """Insert no-evidence steps, preserving each event and its physical time."""
    if length < 32 or length % 32:
        raise ValueError("Context length must be a positive multiple of 32.")
    factor = length // 32
    if factor == 1:
        return x, dt
    expanded = np.zeros((len(x), length, x.shape[-1]), dtype=np.float32)
    expanded[:, factor - 1 :: factor] = x
    return expanded, np.repeat(dt / factor, factor, axis=1).astype(np.float32)


def _times(rng):
    gaps = rng.lognormal(mean=0.0, sigma=0.45, size=32)
    return (gaps * (32.0 / gaps.sum())).astype(np.float32)


def _query(x, kind):
    """Four literal query tokens, with no digit identity among their features."""
    tokens = (0, {"image": 1, "spoken": 2, "both": 4}[kind], 3, 5)
    for step, token in zip(range(28, 32), tokens):
        x[step, 50] = x[step, 53] = 1.0
        x[step, 54 + token] = 1.0


def _synthetic_split(n, split, seed, context_length):
    split_code = ("train", "val", "test").index(split)
    x = np.zeros((n, 32, 64), dtype=np.float32)
    dt = np.empty((n, 32), dtype=np.float32)
    y = np.empty(n, dtype=np.int64)
    for i in range(n):
        rng = np.random.default_rng(np.random.SeedSequence([seed, split_code, i]))
        values = rng.integers(0, 4, size=4)
        query_key = int(rng.integers(4))
        keys = np.tile(np.arange(4), 7)
        rng.shuffle(keys)
        dt[i] = _times(rng)
        for t, key in enumerate(keys):
            modality = int(rng.integers(2))
            quality = float(rng.choice([0.25, 1.0], p=[0.25, 0.75]))
            evidence = np.eye(4, dtype=np.float32)[values[key]]
            evidence = evidence + rng.normal(0, 0.12 / quality, size=4)
            x[i, t, :4] = np.eye(4)[key]
            x[i, t, 4 + 4 * modality : 8 + 4 * modality] = evidence
            x[i, t, 48 + modality] = x[i, t, 53] = 1.0
            x[i, t, 52] = quality
        x[i, 31, 50] = x[i, 31, 53] = 1.0
        x[i, 31, 60 + query_key] = 1.0
        x[i, :, 51] = dt[i].cumsum() / 32.0
        y[i] = values[query_key]
    x, dt = expand_context(x, dt, context_length)
    identifiers = np.array([f"synthetic:{seed}:{split}:{i}" for i in range(n)])
    return SplitData(
        x, dt, y, identifiers.copy(), identifiers, {"independent_episodes": n}
    )


def _long_memory_split(n, split, seed, context_length):
    """Retain four early associations through genuinely additional distractors."""
    if context_length < 8:
        raise ValueError("Long-memory contexts need at least eight events.")
    split_code = ("train", "val", "test").index(split)
    x = np.zeros((n, context_length, 64), dtype=np.float32)
    dt = np.empty((n, context_length), dtype=np.float32)
    y = np.empty(n, dtype=np.int64)
    for i in range(n):
        # Independent streams prohibit query, timing or distractors carrying values.
        streams = np.random.SeedSequence([seed, 29, split_code, i]).spawn(4)
        initial, distractor, query, timing = [
            np.random.default_rng(stream) for stream in streams
        ]
        values = initial.permutation(4)
        order = initial.permutation(4)
        first_modalities = initial.integers(0, 2, size=4)
        query_key = int(query.integers(4))
        dt[i] = timing.lognormal(mean=-0.5 * 0.35**2, sigma=0.35, size=context_length)
        for t in range(context_length - 1):
            if t < 4:
                key, value, modality = (
                    int(order[t]),
                    int(values[order[t]]),
                    int(first_modalities[t]),
                )
            else:
                key, value, modality = (
                    int(distractor.integers(4, 8)),
                    int(distractor.integers(4)),
                    int(distractor.integers(2)),
                )
            x[i, t, key] = 1.0
            x[i, t, 8 + 4 * modality + value] = 1.0
            x[i, t, 48 + modality] = x[i, t, 52] = x[i, t, 53] = 1.0
        x[i, -1, 50] = x[i, -1, 53] = 1.0
        x[i, -1, 60 + query_key] = 1.0
        # A fixed time unit, not division by T: common observation prefixes match.
        x[i, :, 51] = dt[i].cumsum() / 32.0
        y[i] = values[query_key]
    identifiers = np.array([f"long_memory:{seed}:{split}:{i}" for i in range(n)])
    metadata = {
        "independent_episodes": n,
        "initial_associations": 4,
        "distractor_observations": context_length - 5,
        "mean_physical_duration": float(dt.sum(1).mean()),
    }
    return SplitData(x, dt, y, identifiers.copy(), identifiers, metadata)


def _read_idx(path, dimensions):
    with gzip.open(path, "rb") as handle:
        blob = handle.read()
    expected_magic = 0x800 + dimensions
    header = struct.unpack(">" + "I" * (dimensions + 1), blob[: 4 * (dimensions + 1)])
    if header[0] != expected_magic:
        raise ValueError(f"Invalid IDX header in {path}.")
    values = np.frombuffer(blob, dtype=np.uint8, offset=4 * (dimensions + 1))
    if values.size != int(np.prod(header[1:])):
        raise ValueError(f"Truncated IDX data in {path}.")
    return values.reshape(header[1:])


def _mnist(cache_dir):
    raw = Path(cache_dir) / "mnist"
    train_x = _read_idx(raw / "train-images-idx3-ubyte.gz", 3)
    train_y = _read_idx(raw / "train-labels-idx1-ubyte.gz", 1)
    test_x = _read_idx(raw / "t10k-images-idx3-ubyte.gz", 3)
    test_y = _read_idx(raw / "t10k-labels-idx1-ubyte.gz", 1)
    # The partition is fixed independently of model/training seed and train size.
    rng = np.random.default_rng(40217)
    train_ids, val_ids = [], []
    for label in range(10):
        ids = rng.permutation(np.flatnonzero(train_y == label))
        cut = min(1000, max(1, len(ids) // 6))
        val_ids.extend(ids[:cut])
        train_ids.extend(ids[cut:])
    result = {}
    for split, images, labels, ids, source in (
        ("train", train_x, train_y, np.array(train_ids), "train"),
        ("val", train_x, train_y, np.array(val_ids), "train"),
        ("test", test_x, test_y, np.arange(len(test_y)), "test"),
    ):
        result[split] = (
            images,
            labels,
            ids,
            np.array([f"mnist:{source}:{i}" for i in range(len(labels))]),
        )
    return result


def audio_features(path):
    """Fixed 20-band log-mel frontend; no per-utterance or corpus fitting."""
    with wave.open(str(path), "rb") as handle:
        if (
            handle.getnchannels() != 1
            or handle.getsampwidth() != 2
            or handle.getframerate() != 8000
        ):
            raise ValueError(f"Expected mono PCM16 8 kHz audio: {path}.")
        signal = (
            np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(
                np.float32
            )
            / 32768.0
        )
    if not len(signal):
        raise ValueError(f"Empty recording: {path}.")
    padded = np.pad(signal, (199, 0))
    ends = np.arange(0, len(signal), 80)
    frames = np.stack([padded[t : t + 200] for t in ends]) * np.hanning(200)
    power = np.abs(np.fft.rfft(frames, n=256)) ** 2 / 256.0
    mel = np.linspace(
        2595 * np.log10(1 + 80 / 700), 2595 * np.log10(1 + 3800 / 700), 22
    )
    hz = 700 * (10 ** (mel / 2595) - 1)
    frequencies = np.fft.rfftfreq(256, 1 / 8000)
    filters = np.stack(
        [
            np.maximum(
                0,
                np.minimum(
                    (frequencies - hz[j]) / (hz[j + 1] - hz[j]),
                    (hz[j + 2] - frequencies) / (hz[j + 2] - hz[j + 1]),
                ),
            )
            for j in range(20)
        ]
    )
    filters /= np.maximum(filters.sum(axis=1, keepdims=True), 1e-8)
    features = np.log1p(100 * (power @ filters.T)) / 6.0
    # Fixed offline encoder resampling; this is not a claim of native causal audio streaming.
    positions = np.minimum(
        (np.arange(28) + 1) * len(features) // 28, len(features) - 1
    ).astype(int)
    return features[positions].astype(np.float32), len(signal) / 8000.0


def prepare_audio_features(cache_dir):
    cache_dir = Path(cache_dir)
    paths = sorted((cache_dir / "fsdd" / "recordings").glob("*.wav"))
    if not paths:
        raise FileNotFoundError("FSDD recordings missing; run prepare_data first.")
    features, durations, labels, speakers, ids = [], [], [], [], []
    for path in paths:
        label, speaker, _ = path.stem.split("_")
        feature, duration = audio_features(path)
        features.append(feature)
        durations.append(duration)
        labels.append(int(label))
        speakers.append(speaker)
        ids.append(f"fsdd:{FSDD_COMMIT}:{path.name}")
    output = cache_dir / "fsdd_features_v1.npz"
    np.savez_compressed(
        output,
        x=np.stack(features),
        duration=np.array(durations),
        y=np.array(labels),
        speakers=np.array(speakers),
        ids=np.array(ids),
    )
    return output


def _class_orders(labels, allowed, seed):
    rng = np.random.default_rng(seed)
    return [rng.permutation(allowed[labels[allowed] == label]) for label in range(10)]


def _real_split(task, n, split, seed, context_length, mnist, audio):
    split_code = ("train", "val", "test").index(split)
    x = np.zeros((n, 32, 64), dtype=np.float32)
    dt = np.empty((n, 32), dtype=np.float32)
    y = np.empty(n, dtype=np.int64)
    images, image_labels, allowed, image_ids = mnist[split]
    image_order = _class_orders(image_labels, allowed, 743 + split_code)
    audio_allowed = (
        np.flatnonzero(np.isin(audio["speakers"], SPEAKER_SPLITS[split]))
        if audio is not None
        else None
    )
    audio_order = (
        _class_orders(audio["y"], audio_allowed, 987 + split_code)
        if audio is not None
        else None
    )
    image_sources, audio_sources, speakers, queries = [], [], [], []
    image_classes, audio_classes = [], []
    counts_i = np.zeros(10, dtype=int)
    counts_a = np.zeros(10, dtype=int)
    for i in range(n):
        rng = np.random.default_rng(np.random.SeedSequence([seed, 18 + split_code, i]))
        target = (i + seed) % 10
        selected = (
            "image" if task == "mnist" else "spoken" if task == "fsdd" else "both"
        )
        image_label = audio_label = target
        if task == "multimodal_select":
            selected = "image" if rng.integers(2) == 0 else "spoken"
            if selected == "image":
                audio_label = int(rng.integers(10))
            else:
                image_label = int(rng.integers(10))
        image_source = audio_source = speaker = ""
        if task != "fsdd":
            pool = image_order[image_label]
            if counts_i[image_label] >= len(pool):
                raise ValueError(
                    f"Requested more unique {split} MNIST images than available."
                )
            index = pool[counts_i[image_label]]
            counts_i[image_label] += 1
            x[i, :28, :28] = images[index] / 255.0
            x[i, :28, 48] = 1.0
            image_source = image_ids[index]
        if task != "mnist":
            pool = audio_order[audio_label]
            if not len(pool):
                raise ValueError(
                    f"Missing FSDD class {audio_label} for {split} speakers."
                )
            index = pool[counts_a[audio_label] % len(pool)]
            counts_a[audio_label] += 1
            x[i, :28, 28:48] = audio["x"][index]
            x[i, :28, 49] = 1.0
            audio_source, speaker = (
                str(audio["ids"][index]),
                str(audio["speakers"][index]),
            )
        dt[i] = _times(rng)
        x[i, :, 51] = dt[i].cumsum() / 32.0
        x[i, :28, 52:54] = 1.0
        _query(x[i], selected)
        y[i] = target
        image_sources.append(image_source)
        audio_sources.append(audio_source)
        speakers.append(speaker)
        queries.append(selected)
        image_classes.append(image_label if image_source else -1)
        audio_classes.append(audio_label if audio_source else -1)
    x, dt = expand_context(x, dt, context_length)
    sample_ids = np.array([f"{task}:{seed}:{split}:{i}" for i in range(n)])
    metadata = {
        "image_source_ids": image_sources,
        "audio_source_ids": audio_sources,
        "speakers": speakers,
        "query_modalities": queries,
        "image_labels": image_classes,
        "audio_labels": audio_classes,
        "unique_images": len(set(image_sources) - {""}),
        "unique_recordings": len(set(audio_sources) - {""}),
        "episodes": n,
    }
    return SplitData(
        x,
        dt,
        y,
        np.array(speakers if task != "mnist" else image_sources),
        sample_ids,
        metadata,
    )


def load_data(
    task="synthetic",
    train_size=1024,
    val_size=256,
    test_size=512,
    context_length=32,
    seed=0,
    cache_dir=DEFAULT_CACHE,
):
    """Return nested train prefixes and source-disjoint, independently held-out splits."""
    if task not in TASKS:
        raise ValueError(f"Unknown task {task}; choose from {TASKS}.")
    if min(train_size, val_size, test_size) <= 0 or seed < 0:
        raise ValueError("Split sizes must be positive and seed nonnegative.")
    sizes = {"train": train_size, "val": val_size, "test": test_size}
    manifest = {
        "schema": "hcsn-data-v1",
        "task": task,
        "seed": seed,
        "context_length": context_length,
        "canonical_events": 32,
        "physical_duration": 32.0,
        "sizes": sizes,
        "context_policy": "identical evidence; subdivided dt and zero-input null steps",
        "preprocessing_fit": "none; fixed transforms only",
    }
    if task in ("synthetic", "long_memory"):
        builder = _synthetic_split if task == "synthetic" else _long_memory_split
        splits = {
            name: builder(size, name, seed, context_length)
            for name, size in sizes.items()
        }
        if task == "synthetic":
            manifest["interpretation"] = (
                "Synthetic causal cross-modal keyed evidence retrieval; not real-world data."
            )
        else:
            manifest.pop("canonical_events")
            manifest["physical_duration"] = {
                "expected": float(context_length),
                "mean_by_split": {
                    name: split.metadata["mean_physical_duration"]
                    for name, split in splits.items()
                },
            }
            manifest["context_policy"] = (
                "four fixed early associations; T-5 fresh independent distractor observations; final fixed-key query"
            )
            manifest["interpretation"] = (
                "Synthetic true-history retention growth, with disjoint distractor keys and no repeated target association; not natural data."
            )
            manifest["initial_associations"] = 4
            manifest["distractor_observations"] = context_length - 5
            manifest["timing_policy"] = (
                "independent lognormal increments with expected dt=1; duration grows with T"
            )
        classes = tuple(str(i) for i in range(4))
    else:
        source_manifest = Path(cache_dir) / "sources_manifest.json"
        source_data = (
            json.loads(source_manifest.read_text())
            if source_manifest.exists()
            else None
        )
        if source_data:
            for item in source_data["mnist"]["files"]:
                if (
                    sha256(Path(cache_dir) / "mnist" / item["filename"])
                    != item["sha256"]
                ):
                    raise ValueError(
                        f"MNIST cache checksum mismatch: {item['filename']}."
                    )
        mnist = _mnist(cache_dir)
        audio = None
        if task != "mnist":
            feature_path = Path(cache_dir) / "fsdd_features_v1.npz"
            if not feature_path.exists():
                prepare_audio_features(cache_dir)
            if (
                source_data
                and sha256(feature_path) != source_data["fsdd"]["features"]["sha256"]
            ):
                raise ValueError(
                    "FSDD feature cache checksum mismatch; prepare sources again."
                )
            with np.load(feature_path, allow_pickle=False) as loaded:
                audio = {key: loaded[key] for key in loaded.files}
        splits = {
            name: _real_split(task, size, name, seed, context_length, mnist, audio)
            for name, size in sizes.items()
        }
        if source_data:
            source_data["fsdd"].pop("recording_hashes", None)
            manifest["sources"] = source_data
            manifest["source_manifest_sha256"] = sha256(source_manifest)
        else:
            manifest["sources"] = {"status": "local fixture or unmanifested source"}
        manifest["speaker_splits"] = SPEAKER_SPLITS
        manifest["interpretation"] = (
            "Independent MNIST/FSDD samples; artificial class pairing or query-selected pairing, never natural synchronization. "
            "The four-token text query names a modality but never a digit; it is not a general language benchmark. "
            "FSDD sources repeat when requested episodes exceed the split's unique recordings."
        )
        manifest["source_counts"] = {
            name: {
                key: value
                for key, value in split.metadata.items()
                if key in ("unique_images", "unique_recordings", "episodes")
            }
            for name, split in splits.items()
        }
        classes = tuple(str(i) for i in range(10))
    names = FEATURE_NAMES
    if task == "synthetic":
        names = (
            tuple(
                [f"key_{i}" for i in range(4)]
                + [f"view_{view}_value_{i}" for view in ("a", "b") for i in range(4)]
            )
            + FEATURE_NAMES[12:]
        )
    elif task == "long_memory":
        names = (
            tuple(
                [f"key_{i}" for i in range(8)]
                + [f"view_{view}_value_{i}" for view in ("a", "b") for i in range(4)]
            )
            + FEATURE_NAMES[16:]
        )
    return DataBundle(
        splits["train"], splits["val"], splits["test"], names, classes, manifest
    ).validate()
