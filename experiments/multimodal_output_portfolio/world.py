"""A small raw multimodal world with explicit, reproducible sensor failures.

Class ``2 * color + direction`` encodes four colors and left/right motion.
The controller may consume only ``raw``. Truth, sensor reports, scenario labels,
and IDs are evaluation metadata; none is embedded in nuisance variables.
This is a synthetic mechanism test, not a natural-language or video benchmark.
"""

import numpy as np


MODALITIES = ("text", "audio", "image", "video")
NUM_CLASSES = 8
TEXT_VOCABULARY = (
    "red", "green", "blue", "yellow", "left", "right", "moves", "now",
    "today", "<pad>",
)
SHAPES = {
    "text": (4, len(TEXT_VOCABULARY)),
    "audio": (1024,),
    "image": (16, 16, 3),
    "video": (4, 16, 16, 3),
}
COLORS = np.array(
    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 1.0, 0.0]],
    dtype=np.float32,
)
AUDIO_SAMPLE_RATE = 8192
AUDIO_FREQUENCIES = 256.0 + 64.0 * np.arange(NUM_CLASSES)

# These values are fixed before train/calibration/validation/test generation.
# Splits differ in random streams, never in these IID mechanism parameters.
MIXTURE_NAMES = ("independent", "shared", "single", "missing")
MIXTURE_PROBABILITIES = np.array([0.45, 0.30, 0.15, 0.10])
INDEPENDENT_ERROR_RATES = np.array([0.12, 0.16, 0.14, 0.10])
SHARED_FAILURE_RATE = 0.90
SHARED_RELIABLE_ERROR_RATE = 0.06
MISSING_OBSERVED_ERROR_RATE = 0.12
MISSING_TWO_PROBABILITY = 0.25


def _class_array(classes):
    classes = np.asarray(classes)
    if classes.ndim != 1 or not np.issubdtype(classes.dtype, np.integer):
        raise ValueError("classes must be a one-dimensional integer array")
    if np.any((classes < -1) | (classes >= NUM_CLASSES)):
        raise ValueError("classes must be -1 (missing) or in [0, 7]")
    return classes.astype(np.int64, copy=False)


def _render_modality(classes, modality, rng, nuisance):
    """Render only a sensor's reported class, without access to world truth."""
    n = len(classes)
    present = classes >= 0
    safe = np.maximum(classes, 0)
    color, direction = safe // 2, safe % 2

    if modality == "text":
        # Actual four-token sequence, e.g. "red moves left today". The final
        # token varies independently of semantics; missing text has no tokens.
        tokens = np.empty((n, 4), dtype=np.int64)
        tokens[:, 0] = color
        tokens[:, 1] = 6
        tokens[:, 2] = 4 + direction
        tokens[:, 3] = rng.integers(7, 9, size=n) if nuisance else 7
        raw = np.eye(len(TEXT_VOCABULARY), dtype=np.float32)[tokens]
    elif modality == "audio":
        # Each semantic class has one FFT-bin-aligned tone. Random phase and
        # gain cannot reveal whether the sensor's report is true or false.
        t = np.arange(SHAPES["audio"][0], dtype=np.float64) / AUDIO_SAMPLE_RATE
        phase = rng.uniform(-np.pi, np.pi, size=n) if nuisance else np.zeros(n)
        gain = rng.uniform(0.65, 0.95, size=n) if nuisance else np.full(n, 0.85)
        raw = gain[:, None] * np.sin(
            2 * np.pi * AUDIO_FREQUENCIES[safe, None] * t + phase[:, None]
        )
        if nuisance:
            raw += rng.normal(0.0, 0.01, size=raw.shape)
        raw = np.clip(raw, -1.0, 1.0).astype(np.float32)
    else:
        frames = 4 if modality == "video" else 1
        # A 4x4 square sits on the left/right in an image. In a video it
        # moves six pixels in the indicated direction over four frames.
        base_x = np.where(direction == 0, 10, 2) if frames == 4 else np.where(
            direction == 0, 2, 10
        )
        if nuisance:
            base_x = base_x + rng.integers(-1, 2, size=n)
            y = 6 + rng.integers(-2, 3, size=n)
            gain = rng.uniform(0.70, 1.0, size=n)
            background = rng.uniform(0.01, 0.04, size=n)
        else:
            y = np.full(n, 6)
            gain = np.ones(n)
            background = np.zeros(n)
        x = base_x[:, None] + (
            (2 * direction - 1)[:, None] * 2 * np.arange(frames)[None, :]
            if frames == 4 else np.zeros((n, 1), dtype=np.int64)
        )
        rows = np.arange(16)[None, None, :, None]
        cols = np.arange(16)[None, None, None, :]
        mask = (
            (rows >= y[:, None, None, None])
            & (rows < y[:, None, None, None] + 4)
            & (cols >= x[:, :, None, None])
            & (cols < x[:, :, None, None] + 4)
        )
        foreground = gain[:, None] * COLORS[color]
        raw = np.where(
            mask[..., None], foreground[:, None, None, None, :],
            background[:, None, None, None, None],
        ).astype(np.float32)
        if nuisance:
            raw += rng.normal(0.0, 0.005, size=raw.shape).astype(np.float32)
        raw = np.clip(raw, 0.0, 1.0)

    flat = raw.reshape(n, int(np.prod(SHAPES[modality])))
    flat[~present] = 0.0
    return np.ascontiguousarray(flat, dtype=np.float32)


def render(classes: np.ndarray, seed: int, nuisance: bool = True) -> dict[str, np.ndarray]:
    """Render each class into all four raw modalities, flattened batch-first.

    Text/image/video values lie in [0, 1], audio in [-1, 1]; all are float32.
    ``-1`` renders as all zeros for every modality. Nuisance streams are
    independent across modalities and draws/worlds and are unrelated to truth.
    """
    classes = _class_array(classes)
    streams = np.random.SeedSequence(seed).spawn(len(MODALITIES))
    return {
        modality: _render_modality(classes, modality, np.random.default_rng(stream), nuisance)
        for modality, stream in zip(MODALITIES, streams)
    }


def canonical() -> dict[str, np.ndarray]:
    """Return the eight noiseless class targets in class-index order."""
    return render(np.arange(NUM_CLASSES, dtype=np.int64), seed=0, nuisance=False)


def sample_worlds(n, seed, split, scenario="train") -> dict:
    """Generate independent worlds with a fixed IID mixture or an OOD failure.

    ``train`` and ``iid`` use the same mixture for every split. ``independent``
    uses per-sensor error rates; ``shared`` gives the first three sensors a
    common wrong report with probability 0.90 and video an independent 0.06
    error rate; ``single`` corrupts exactly one uniformly selected sensor;
    ``missing`` removes one (75%) or two (25%) uniformly selected sensors,
    with independent 0.12 errors in the observed sensors.

    OOD ``correlation_shift`` moves the shared-error coalition to text/audio/
    video and leaves image as the more reliable sensor. ``all_shared_wrong``
    makes every sensor agree on one wrong class: no sensor carries a reliable
    report, and rendering nuisances provide no information about the truth.

    The split name is part of the deterministic RNG namespace, so equal seeds
    in distinct splits do not reuse worlds. IDs are metadata only, not input.
    """
    if not isinstance(n, (int, np.integer)) or n < 0:
        raise ValueError("n must be a nonnegative integer")
    if not isinstance(split, str) or not split:
        raise ValueError("split must be a nonempty string")
    allowed = ("train", "iid", "correlation_shift", "all_shared_wrong") + MIXTURE_NAMES
    if scenario not in allowed:
        raise ValueError("unknown scenario: " + str(scenario))
    # UTF-8 bytes give a stable namespace, unlike Python's randomized hash().
    namespace = [int(seed), len(split.encode("utf-8")), *split.encode("utf-8")]
    streams = np.random.SeedSequence(namespace).spawn(1 + len(MODALITIES))
    rng = np.random.default_rng(streams[0])
    truth = rng.integers(NUM_CLASSES, size=n, dtype=np.int64)
    reports = np.repeat(truth[:, None], len(MODALITIES), axis=1)
    scenarios = (
        rng.choice(MIXTURE_NAMES, size=n, p=MIXTURE_PROBABILITIES)
        if scenario in ("train", "iid") else np.full(n, scenario)
    )

    for name in MIXTURE_NAMES + ("correlation_shift", "all_shared_wrong"):
        indices = np.flatnonzero(scenarios == name)
        k = len(indices)
        if k == 0:
            continue
        labels = truth[indices]
        if name in ("independent", "missing"):
            error_rates = (
                INDEPENDENT_ERROR_RATES if name == "independent"
                else MISSING_OBSERVED_ERROR_RATE
            )
            errors = rng.random((k, len(MODALITIES))) < error_rates
            wrong = (labels[:, None] + rng.integers(1, NUM_CLASSES, size=(k, 4))) % NUM_CLASSES
            values = np.where(errors, wrong, labels[:, None])
            if name == "missing":
                count = 1 + (rng.random(k) < MISSING_TWO_PROBABILITY)
                rank = np.argsort(np.argsort(rng.random((k, 4)), axis=1), axis=1)
                values[rank < count[:, None]] = -1
            reports[indices] = values
        elif name == "single":
            sensor = rng.integers(len(MODALITIES), size=k)
            reports[indices, sensor] = (
                labels + rng.integers(1, NUM_CLASSES, size=k)
            ) % NUM_CLASSES
        else:
            wrong = (labels + rng.integers(1, NUM_CLASSES, size=k)) % NUM_CLASSES
            if name == "all_shared_wrong":
                reports[indices] = wrong[:, None]
            else:
                coalition, reliable = ((0, 1, 3), 2) if name == "correlation_shift" else (
                    (0, 1, 2), 3
                )
                common = np.where(rng.random(k) < SHARED_FAILURE_RATE, wrong, labels)
                reports[np.ix_(indices, coalition)] = common[:, None]
                reliable_wrong = (labels + rng.integers(1, NUM_CLASSES, size=k)) % NUM_CLASSES
                reports[indices, reliable] = np.where(
                    rng.random(k) < SHARED_RELIABLE_ERROR_RATE, reliable_wrong, labels
                )

    raw = {
        modality: _render_modality(
            reports[:, index], modality, np.random.default_rng(streams[index + 1]), True
        )
        for index, modality in enumerate(MODALITIES)
    }
    return {
        "ids": [f"{split}:{seed}:{index:08d}" for index in range(n)],
        "truth": truth,
        "reports": reports,
        "raw": raw,
        "scenario": scenarios,
    }
