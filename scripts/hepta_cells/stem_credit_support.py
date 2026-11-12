"""Bounded initial-only replay preparation and durable experiment bookkeeping."""

import hashlib
import json
import os
from pathlib import Path
import time

try:
    import resource
except ImportError:  # Windows has no child-process rusage accounting.
    resource = None

import numpy as np


BANDS = ("upper", "middle", "lower")
WIDTH = 68
CPU_SCOPE = (
    "parent plus waited child processes"
    if resource
    else "parent only; child CPU unknown"
)


def _raw(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _sha(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else _raw(value)
    ).hexdigest()


def _write(path, value):
    raw = value if isinstance(value, bytes) else _raw(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha(raw)


def _event(path, value):
    with path.open("ab") as stream:
        stream.write(_raw(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _cpu():
    if resource is None:
        return time.process_time()
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


def _documents(dataset):
    if (
        dataset["schema"] != "hepta.cell.cord-retained-replay.v1"
        or dataset["feature_dim"] != 64
        or len(dataset["records"]) != 96
        or dataset.get("fresh_confirmation") != 0
        or dataset.get("source_independence_verified") is not False
    ):
        raise ValueError("complete retained CORD schema required")
    groups = {}
    for row in dataset["records"]:
        hashes = [
            row["document_sha256"],
            row["feature_profile_sha256"],
            *row["receipt_sha256s"],
        ]
        if (
            type(row["source_group"]) is not str
            or not 1 <= len(row["source_group"]) <= 96
            or row["task_id"] != row["candidate_id"]
            or len(hashes) != 4
            or any(
                type(h) is not str
                or len(h) != 64
                or any(c not in "0123456789abcdef" for c in h)
                for h in hashes
            )
        ):
            raise ValueError("bounded source, route and evidence identities required")
        groups.setdefault(row["source_group"], []).append(row)
    if len({r["feature_profile_sha256"] for r in dataset["records"]}) != 1:
        raise ValueError("one frozen feature profile required")
    docs, document_ids = [], set()
    for group, rows in sorted(groups.items()):
        indexed = {r["candidate_id"]: r for r in rows}
        if len(rows) != 3 or set(indexed) != set(BANDS):
            raise ValueError("complete unique three-region feedback required")
        first = rows[0]
        x = np.asarray(first["initial_latent"], dtype=np.float64)
        if x.shape != (64,) or not np.isfinite(x).all() or (np.abs(x) > 1e6).any():
            raise ValueError("invalid initial-only observation")
        if first["document_sha256"] in document_ids:
            raise ValueError("document reused across source groups or splits")
        document_ids.add(first["document_sha256"])
        for row in rows:
            capture = row["observed_at_us"]
            if (
                any(
                    row[k] != first[k]
                    for k in (
                        "split",
                        "initial_latent",
                        "document_sha256",
                        "feature_profile_sha256",
                    )
                )
                or row["receipt_sha256s"][0] != first["receipt_sha256s"][0]
                or row["split"] not in ("train", "dev")
                or type(row["target"]) is not int
                or row["target"] not in (0, 1)
                or len(capture) != 2
                or any(type(t) is not int or not 0 <= t < 2**63 for t in capture)
                or len(row["replay_exposure_us"]) != 2
                or row["replay_exposure_us"][0] != 0
                or type(row["replay_exposure_us"][1]) is not int
                or not 0 <= row["replay_exposure_us"][1] < 2**53
                or row["replay_exposure_us"][1] != capture[1] - capture[0]
            ):
                raise ValueError(
                    "inconsistent pre-action, label or replay-time binding"
                )
        docs.append(
            dict(
                source_group=group,
                split=first["split"],
                initial=x.tolist(),
                targets=[indexed[b]["target"] for b in BANDS],
                delay_us=max(r["replay_exposure_us"][1] for r in rows),
            )
        )
    if [sum(d["split"] == s for d in docs) for s in ("train", "dev")] != [24, 8]:
        raise ValueError("complete 24 train / 8 dev source split required")
    return docs


def _features(kernel, doc):
    """One initial-only observation, fresh hidden state, fixed direct skip features."""
    x = np.asarray(doc["initial"], dtype=np.float64)
    state = kernel.initial_state(doc["source_group"])
    state = kernel.observe(
        state, np.r_[x, np.ones(64), 0.0], episode_id=doc["source_group"], cursor=0
    )
    return np.r_[x / max(1.0, float(np.linalg.norm(x))), state["hidden"]["fast"][0]]


def _score(predictions, targets):
    p, y = np.asarray(predictions), np.asarray(targets)
    return dict(
        mse=float(np.mean((p - y) ** 2)),
        mse_by_cell=dict(zip(BANDS, np.mean((p - y) ** 2, axis=0).tolist())),
        accuracy_at_half=float(np.mean((p >= 0.5) == y)),
    )


def _semantic_state(model):
    value = model.record()
    for row in value["settled"].values():
        row["receipt"].pop("wall_seconds")
        row["receipt"].pop("cpu_seconds")
    return _sha(value)
