"""Paired AV source-binding with identical single-modality byte marginals.

Every anchor has one same-clip positive and one within-actor deranged negative.
At fixed physical ticks both modality slots are always emitted. A modality's
payload/availability/age depends only on its own source, so neither class has a
different audio-only or video-only input distribution. Actor/emotion are never
model inputs. This is the historically seen small cohort, not a new benchmark.
"""

import hashlib
from pathlib import Path

import numpy as np

from .data import array_hash


def within_actor_derangement(actors, seed):
    rng = np.random.default_rng(seed)
    result = np.arange(len(actors))
    for actor in np.unique(actors):
        indices = np.flatnonzero(actors == actor)
        if len(indices) < 2:
            raise ValueError("Within-actor binding needs at least two recordings")
        proposed = indices.copy()
        while True:
            rng.shuffle(proposed)
            if np.all(proposed != indices):
                break
        result[indices] = proposed
    if len(np.unique(result)) != len(result) or np.any(result == np.arange(len(result))):
        raise AssertionError("Invalid label-independent pairing permutation")
    return result


def binding_data(job, split, diagnostic=None):
    if split not in ("train", "val", "test"):
        raise ValueError("Binding keeps train/val/test source roles, no fictitious OOD split")
    if diagnostic not in (None, "missing_audio", "missing_video", "content_shuffle", "metadata_only"):
        raise ValueError("Unsupported binding diagnostic")
    period = float(job.get("av_window_seconds", .1))
    deadline = float(job.get("binding_deadline_seconds", 1.5))
    if not (np.isfinite(period) and np.isfinite(deadline) and 0 < period <= deadline):
        raise ValueError("Invalid fixed binding clock")
    ticks = np.arange(1, int(round(deadline / period)) + 1) * period
    if not np.isclose(ticks[-1], deadline, atol=1e-10):
        raise ValueError("Binding deadline must be a whole number of fixed periods")
    path = Path(job["av_directory"]) / (("validation" if split == "val" else split) + ".npz")
    with np.load(path, allow_pickle=False) as archive:
        raw = {name: archive[name].copy() for name in archive.files}
    count = len(raw["clip_ids"])
    donor = within_actor_derangement(raw["actors"], job.get("binding_pair_seed", 2026110173))
    # Source-specific cache is built once. A source has the same bytes regardless
    # of whether it appears in a positive or negative pair.
    payload = np.zeros((count, len(ticks), 2, 32), np.float32)
    available = np.zeros((count, len(ticks), 2), bool)
    age = np.zeros((count, len(ticks), 2), np.float32)
    acquired = np.full((count, len(ticks), 2), np.nan, np.float64)
    for source in range(count):
        lo, hi = raw["offsets"][source:source + 2]
        for kind in (0, 1):
            candidates = np.flatnonzero(raw["modality"][lo:hi] == kind) + lo
            relative = raw["times"][candidates] - raw["origins"][source]
            for tick_index, tick in enumerate(ticks):
                selected = int(np.searchsorted(relative, tick, side="right") - 1)
                if selected >= 0:
                    payload[source, tick_index, kind] = raw["x"][candidates[selected], :32]
                    available[source, tick_index, kind] = True
                    age[source, tick_index, kind] = tick - relative[selected]
                    acquired[source, tick_index, kind] = relative[selected]
            if diagnostic == "content_shuffle":
                order = np.random.default_rng(2026110181 + source * 2 + kind).permutation(len(ticks))
                payload[source, :, kind] = payload[source, order, kind]
    anchor_indices = np.tile(np.arange(count), 2)
    video_indices = np.r_[np.arange(count), donor]
    labels = np.r_[np.ones(count, np.int64), np.zeros(count, np.int64)]
    pairs, length = 2 * count, 2 * len(ticks)
    x = np.zeros((pairs, length, 40), np.float32)
    observed = np.zeros((pairs, length), bool)
    release = np.repeat(ticks, 2)
    for row, (audio_source, video_source) in enumerate(zip(anchor_indices, video_indices, strict=True)):
        for kind, source in enumerate((audio_source, video_source)):
            columns = np.arange(kind, length, 2)
            x[row, columns, 32 + kind] = 1  # Unconditional shared slot clock.
            missing = diagnostic == ("missing_audio" if kind == 0 else "missing_video")
            if not missing:
                x[row, columns, :32] = payload[source, :, kind]
                x[row, columns, 34 + kind] = available[source, :, kind]
                x[row, columns, 36 + kind] = age[source, :, kind]
                x[row, columns, 38 + kind] = available[source, :, kind]
                observed[row, columns] = available[source, :, kind]
    if diagnostic == "metadata_only":
        x[:, :, :32] = 0
    dt = np.broadcast_to(np.diff(np.r_[0, release]), (pairs, length)).astype(np.float32).copy()
    y = np.full((pairs, length), -100, np.int64)
    y[:, -1] = labels
    audio_ids = raw["clip_ids"][anchor_indices].astype(str)
    video_ids = raw["clip_ids"][video_indices].astype(str)
    result = dict(x=x, dt=dt, y=y, valid=np.ones_like(observed), observed=observed,
        timestamps=np.broadcast_to(release, (pairs, length)).copy(),
        ids=np.array([f"audio:{a}|video:{v}" for a, v in zip(audio_ids, video_ids, strict=True)]),
        group_ids=raw["actors"][anchor_indices], donor_group_ids=raw["actors"][video_indices],
        audio_source_ids=audio_ids, video_source_ids=video_ids,
        pair_group_ids=raw["clip_ids"][anchor_indices].astype(str))
    result["metadata"] = dict(task="av_binding", split=split, diagnostic=diagnostic,
        source_path=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        pairs=pairs, positive_pairs=count, negative_pairs=count,
        independent_actor_groups=len(np.unique(raw["actors"])),
        pairing_seed=job.get("binding_pair_seed", 2026110173), video_permutation=donor.tolist(),
        emotion_labels_used_for_pairing=False, actor_identity_in_model=False,
        deadline_seconds=deadline, window_seconds=period, source_clips=raw["clip_ids"].astype(str).tolist(),
        clock="fixed tick audio then video slots; no source duration or EOF input",
        metadata="per-slot own-source age/availability only; missing source metadata is zeroed",
        metadata_only_diagnostic="zero payload; preserve fixed slots, age and availability to expose timestamp fingerprints",
        source_binding_label="1=same recording, 0=different recording within same actor",
        task_limitation="DFA/six-emotion small reused cohort; source binding, not natural semantic alignment",
        old_heldout_previously_observed=True, fresh_confirmation=False,
        raw_observation_compression=True, sensor_read_saving_claim=False)
    result["metadata"]["array_sha256"] = array_hash(result)
    return result


def verify_single_modality_marginals(audio_only, video_only):
    """Exact complete-input equality, stronger than balanced source counts."""
    count = len(audio_only["x"]) // 2
    if len(audio_only["x"]) != len(video_only["x"]) or count == 0:
        raise ValueError("Mismatched paired diagnostic datasets")
    for key in ("x", "dt", "valid", "observed", "timestamps"):
        if not np.array_equal(audio_only[key][:count], audio_only[key][count:]):
            raise AssertionError(f"Audio-only class leakage in {key}")
    positives = {source: index for index, source in enumerate(video_only["video_source_ids"][:count])}
    for row in range(count, 2 * count):
        counterpart = positives[video_only["video_source_ids"][row]]
        for key in ("x", "dt", "valid", "observed", "timestamps"):
            if not np.array_equal(video_only[key][row], video_only[key][counterpart]):
                raise AssertionError(f"Video-only class leakage in {key}")
    return dict(audio_pair_equal=True, video_by_source_equal=True,
                compared_fields=["x", "dt", "valid", "observed", "timestamps"], pairs=2 * count)

