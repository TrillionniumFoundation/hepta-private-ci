"""Content tasks and deterministic causal-window AV observations.

Only train/validation may be opened without explicit heldout permission. AV uses
the already observed 48-clip cohort. Fixed physical windows never use a fraction
of total clip duration; the last incomplete window is flushed on declared EOF.
"""

import hashlib
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_free_boundary_v1.datasets import synthetic
from experiments.hcsn_task_value_v1.async_av import event_inputs


def array_hash(values):
    digest = hashlib.sha256()
    for name in ("x", "dt", "y", "observed", "valid"):
        value = np.ascontiguousarray(values[name])
        digest.update(name.encode())
        digest.update(str((str(value.dtype), value.shape)).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def check_split(split, allow_heldout):
    if split not in ("train", "val", "test", "ood"):
        raise ValueError("Unknown data split")
    if split in ("test", "ood") and not allow_heldout:
        raise PermissionError("Heldout access requires allow_heldout=True")


def causal_windows(x, times, modality, origin, seconds):
    """Last observation of each modality released at a fixed window boundary.

All selected observations were already acquired at their release. Simultaneous
releases use audio then video. EOF flush is an explicitly observed end event.
No duration-normalized resampling or future-payload aggregation is performed.
"""
    if seconds < 0 or not np.isfinite(seconds):
        raise ValueError("Nonnegative finite window period required")
    if seconds == 0:
        return x.copy(), np.asarray(times).copy()
    buckets = np.floor(np.maximum(0, times - origin) / seconds).astype(np.int64)
    selected, released = [], []
    for bucket in np.unique(buckets):
        release = min(origin + (int(bucket) + 1) * seconds, float(times[-1]))
        for kind in (0, 1):
            indices = np.flatnonzero((buckets == bucket) & (modality == kind))
            if len(indices):
                selected.append(int(indices[-1]))
                released.append(release)
    result = x[selected].copy()
    released = np.asarray(released, np.float64)
    # Ages and availability refer to the accepted observations, never future rows.
    seen = np.zeros(2, bool)
    latest = np.zeros(2, np.float64)
    for row, index in enumerate(selected):
        kind = int(modality[index])
        if result[row, 34 + kind] > 0:
            seen[kind] = True
            latest[kind] = times[index]
        result[row, 36:38] = np.where(seen, released[row] - latest, 0)
        result[row, 38:40] = seen
    if np.any(released < times[selected]):
        raise AssertionError("Released an observation before acquisition")
    return result, released


def copy_prefix_addresses(x):
    """Causal task-known four-slot address features, shared by every model arm."""
    result = x.copy()
    selected, query = result[:, :, 8] > 0, result[:, :, 9] > 0
    selected_count, query_count = np.cumsum(selected, axis=1), np.cumsum(query, axis=1)
    result[:, :, 10] = selected_count / 4
    result[:, :, 11] = query_count / 4
    for address in range(1, 5):
        result[:, :, 11 + address] = ((selected & (selected_count == address)) |
                                      (query & (query_count == address)))
    return result


def synthetic_data(task, split, length, size, seed, diagnostic=None):
    x, dt, y, meta = synthetic(task, size, split, length, seed=seed)
    dt *= .1
    dt[:, 0] = 0
    if diagnostic:
        rng = np.random.default_rng(np.random.SeedSequence([seed, length, 9901]))
        for row in range(size):
            if diagnostic == "query_permute" and task == "mqar":
                x[row, -4:, :8] = np.roll(x[row, -4:, :8].copy(), 1, axis=0)
                y[row, -4:] = np.roll(y[row, -4:].copy(), 1)
            elif diagnostic == "content_shuffle":
                if task == "mqar":
                    indices = np.flatnonzero(x[row, :, 16])
                    x[row, indices, 8:16] = x[row, rng.permutation(indices), 8:16]
                else:
                    indices = np.arange(length - 4)
                    x[row, indices, :8] = x[row, rng.permutation(indices), :8]
            else:
                raise ValueError("Unsupported synthetic intervention")
    if task == "selective_copy":
        x = copy_prefix_addresses(x)
    result = dict(x=x, dt=dt, y=y, observed=np.ones(dt.shape, bool),
                  valid=np.ones(dt.shape, bool), ids=np.array(meta["episode_ids"]))
    result["metadata"] = dict(task=task, split=split, seed=seed, length=length,
        diagnostic=diagnostic, source_kind="synthetic", label_contract=meta["label_contract"],
        derived_address_features=("causal selected/query prefix counts /4 in channels10/11; "
            "current selected/query ordinal one-hot 1..4 in12:16; no labels, future or total length; all families identical"
            if task == "selective_copy" else None),
        diagnostic_labels="query_permute changes both query and gold; content_shuffle preserves original gold")
    result["metadata"]["array_sha256"] = array_hash(result)
    return result


def audiovisual_data(directory, split, window_seconds, diagnostic=None):
    split_name = "validation" if split == "val" else split
    if split_name == "ood":
        raise ValueError("AV OOD requires an explicit intervention, not a relabeled split")
    path = Path(directory) / (split_name + ".npz")
    with np.load(path, allow_pickle=False) as archive:
        raw = {name: archive[name].copy() for name in archive.files}
    norm = dict(mean=raw["normalization_mean"], scale=raw["normalization_scale"])
    # Random derangement uses only row indices, never emotions or actor labels.
    donor_rng = np.random.default_rng(2026110171)
    donor_order = np.arange(len(raw["clip_ids"]))
    while True:
        donor_rng.shuffle(donor_order)
        if np.all(donor_order != np.arange(len(donor_order))):
            break
    sequences, intervals, releases, observed_rows, donors = [], [], [], [], []
    for row, identifier in enumerate(raw["clip_ids"]):
        start, stop = raw["offsets"][row:row + 2]
        base = raw["base"][start:stop].copy()
        times = raw["times"][start:stop]
        kinds = raw["modality"][start:stop]
        origin = float(raw["origins"][row])
        available = np.ones(len(times), bool)
        donor_id = None
        if diagnostic in ("missing_audio", "missing_video"):
            available[kinds == (0 if diagnostic == "missing_audio" else 1)] = False
        elif diagnostic == "modality_mismatch":
            donor = int(donor_order[row])
            lo, hi = raw["offsets"][donor:donor + 2]
            donor_indices = np.flatnonzero(raw["modality"][lo:hi] == 1) + lo
            donor_times = raw["times"][donor_indices] - raw["origins"][donor]
            target_indices = np.flatnonzero(kinds == 1)
            positions = np.searchsorted(donor_times, times[target_indices] - origin, side="right") - 1
            for index, position in zip(target_indices, positions, strict=True):
                if position < 0:
                    available[index] = False
                else:
                    base[index] = raw["base"][donor_indices[position]]
            donor_id = str(raw["clip_ids"][donor])
        elif diagnostic == "content_shuffle":
            rng = np.random.default_rng(83001 + row)
            for kind in (0, 1):
                indices = np.flatnonzero(kinds == kind)
                base[indices] = base[rng.permutation(indices)]
        elif diagnostic is not None:
            raise ValueError("Unsupported AV intervention")
        x, _ = event_inputs(base, times, kinds, origin, norm, available)
        x, released = causal_windows(x, times, kinds, origin, window_seconds)
        sequences.append(x)
        intervals.append(np.diff(np.r_[origin, released]).astype(np.float32))
        releases.append(released)
        observed_rows.append(x[:, 34:36].any(-1))
        donors.append(donor_id)
    length = max(map(len, sequences))
    count = len(sequences)
    x = np.zeros((count, length, 40), np.float32)
    dt = np.zeros((count, length), np.float32)
    valid = np.zeros((count, length), bool)
    observed = np.zeros_like(valid)
    y = np.full((count, length), -100, np.int64)
    timestamps = np.zeros((count, length), np.float64)
    for row, sequence in enumerate(sequences):
        size = len(sequence)
        x[row, :size], dt[row, :size] = sequence, intervals[row]
        valid[row, :size], observed[row, :size] = True, observed_rows[row]
        timestamps[row, :size] = releases[row]
        y[row, size - 1] = raw["labels"][row]
    result = dict(x=x, dt=dt, y=y, valid=valid, observed=observed,
                  ids=raw["clip_ids"], group_ids=raw["actors"], timestamps=timestamps)
    result["metadata"] = dict(task="async_av", split=split, window_seconds=window_seconds,
        source_path=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        raw_events=int(raw["offsets"][-1]), emitted_events=int(valid.sum()),
        diagnostic=diagnostic, modality_donors=donors, old_heldout_previously_observed=True,
        fresh_confirmation=False, frontend="fixed log-mel/DCT; trainable downstream content encoder",
        release_contract="fixed physical windows; last available per modality; EOF flush",
        donor_contract="seed-2026110171 index-only random derangement in same split; as-of relative time",
        compression_contract="all original observations read; retained deltas may describe un-emitted earlier rows; no sensor-read saving")
    result["metadata"]["array_sha256"] = array_hash(result)
    return result


def load_data(job, split, *, length=None, diagnostic=None, allow_heldout=False):
    check_split(split, allow_heldout)
    if job["task"] == "av_binding":
        from .binding_data import binding_data
        return binding_data(job, split, diagnostic=diagnostic)
    if job["task"] == "async_av":
        return audiovisual_data(job["av_directory"], split, job.get("av_window_seconds", .1), diagnostic)
    size = job.get("train_size", 512) if split == "train" else job.get("validation_size", 128) if split == "val" else job.get("eval_size", 256)
    return synthetic_data(job["task"], split, length or job.get("length", 32),
                          size, job.get("data_seed", 2026110103), diagnostic)


def tensor_batch(values, index):
    index = np.asarray(index)
    valid = values["valid"][index]
    length = int(np.max(np.where(valid, np.arange(valid.shape[1]) + 1, 0)))
    return {key: torch.from_numpy(values[key][index, :length])
            for key in ("x", "dt", "y", "observed", "valid")}

