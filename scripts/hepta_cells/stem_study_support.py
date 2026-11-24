"""Strict retained-input replay support; never authenticates task evidence."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from .bundle import Bundle, OPTIONAL, REQUIRED
from .component_types import Budget, Partition, digest
from .lifecycle import CellOwner
from .semantic import (
    CallableFeatureBackend,
    LocalHead,
    LocalObjective,
    SemanticBinding,
    SemanticCell,
    SharedSemanticPool,
)
from .semantic_component import SemanticComponent, semantic_bundle
from .stem_contract import TimeContract, TimedTemporalComponent, restore_run

ROUTES = ("upper", "middle", "lower")


def write_json(path, value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def semantic_component(head, binding, bundle=None):
    pool = SharedSemanticPool()
    pool.register_backend(
        CallableFeatureBackend(
            binding, head.first.shape[0], np.asarray, lambda: binding.base
        )
    )
    cell = SemanticCell(
        "predictor",
        binding,
        head,
        LocalObjective("cross_entropy", 2, "retained-post-observation-correctness"),
    )
    return SemanticComponent(
        pool, cell, bundle or semantic_bundle(cell, "retained-source")
    )


def temporal_component(kernel, data_hash, contract, episode="artifact", bundle=None):
    parts = {key: digest(["retained-cord-time", data_hash, key]) for key in REQUIRED}
    parts.update({key: None for key in OPTIONAL})
    parts.update(
        base=kernel.kernel_sha256,
        heads=kernel.heads_sha256,
        composition=kernel.config.sha256,
    )
    return TimedTemporalComponent(
        kernel,
        bundle or Bundle("retained-" + kernel.config.kind, 1, parts),
        episode,
        contract,
        0,
    )


def prepare(path):
    raw = Path(path).read_bytes()
    data, data_hash = json.loads(raw), hashlib.sha256(raw).hexdigest()
    if (
        data["schema"] != "hepta.cell.cord-retained-replay.v1"
        or type(data["feature_dim"]) is not int
        or not 1 <= data["feature_dim"] <= 128
    ):
        raise ValueError("unsupported bounded frozen replay dataset")
    records = data["records"]
    if (
        not 1 <= len(records) <= 384
        or data.get("fresh_confirmation") != 0
        or data.get("source_independence_verified") is not False
    ):
        raise ValueError(
            "bounded replay requires explicit zero fresh confirmation and unverified source independence"
        )
    by_source, documents = {}, {}
    for row in records:
        key = row["source_group"]
        if (
            not isinstance(key, str)
            or not key
            or row["candidate_id"] not in ROUTES
            or row["task_id"] != row["candidate_id"]
            or type(row["target"]) is not int
            or row["target"] not in (0, 1)
        ):
            raise ValueError("invalid source, route identity or outcome label")
        hashes = [
            row["document_sha256"],
            row["feature_profile_sha256"],
            *row["receipt_sha256s"],
        ]
        if len(hashes) != 4 or any(
            type(h) is not str
            or len(h) != 64
            or any(c not in "0123456789abcdef" for c in h)
            for h in hashes
        ):
            raise ValueError("original source and receipt identities are required")
        document = row["document_sha256"]
        if documents.setdefault(document, key) != key:
            raise ValueError("document reused under a different source group")
        by_source.setdefault(key, []).append(row)
    for rows in by_source.values():
        if (
            len(rows) != 3
            or {r["candidate_id"] for r in rows} != set(ROUTES)
            or len({r["split"] for r in rows}) != 1
            or rows[0]["split"] not in ("train", "dev")
        ):
            raise ValueError(
                "source groups must contain exactly three routes in one split"
            )
        for row in rows[1:]:
            if (
                any(
                    row[key] != rows[0][key]
                    for key in (
                        "document_sha256",
                        "feature_profile_sha256",
                        "initial_latent",
                    )
                )
                or row["receipt_sha256s"][0] != rows[0]["receipt_sha256s"][0]
            ):
                raise ValueError("routes do not share the original initial observation")
    train = [i for i, row in enumerate(records) if row["split"] == "train"]
    dev = sorted(k for k, rows in by_source.items() if rows[0]["split"] == "dev")
    if not train or len(dev) < 2:
        raise ValueError("training and disjoint development B/C source groups required")
    b_groups = dev[: len(dev) // 2]
    panels = {
        "train": train,
        "B": [i for i, r in enumerate(records) if r["source_group"] in b_groups],
        "C": [
            i
            for i, r in enumerate(records)
            if r["split"] == "dev" and r["source_group"] not in b_groups
        ],
    }
    values = np.asarray(
        [[r["initial_latent"], r["candidate_latent"]] for r in records],
        dtype=np.float64,
    )
    if (
        values.shape != (len(records), 2, data["feature_dim"])
        or not np.isfinite(values).all()
    ):
        raise ValueError("invalid retained latent vectors")
    mean, scale = values[train].mean(axis=(0, 1)), values[train].std(axis=(0, 1))
    scale = np.maximum(scale, 1e-8)
    values = (values - mean) / scale
    contract = TimeContract(
        data["feature_dim"] + 3, "retained-cord", "offline-replay", data_hash[:32]
    )
    episodes = []
    for row, pair in zip(records, values):
        capture, replay = row["observed_at_us"], row["replay_exposure_us"]
        if (
            len(capture) != 2
            or len(replay) != 2
            or any(type(t) is not int or t < 0 for t in capture + replay)
            or replay != [0, capture[1] - capture[0]]
        ):
            raise ValueError("replay schedule must retain exact capture spacing")
        route = [float(row["candidate_id"] == name) for name in ROUTES]
        episodes.append(
            [
                {
                    "cursor": j,
                    "available_us": replay[j],
                    "clock_identity": contract.clock_identity,
                    "values": x.tolist() + route,
                }
                for j, x in enumerate(pair)
            ]
        )
    encoded = contract.episodes(episodes, [0] * len(episodes))
    return (
        data,
        data_hash,
        panels,
        episodes,
        encoded.reshape(len(records), -1),
        contract,
        {"mean": mean.tolist(), "scale": scale.tolist(), "fit_rows": train},
    )


def serve(component, kind, directory, records, indices, episodes, flat, panel):
    wall, cpu = time.perf_counter(), time.process_time()
    outputs = []
    owner = CellOwner(directory / "owner.sqlite")
    try:
        for index in indices:
            run = f"row-{index}"
            partition = Partition("research", "stem-study", "predictor", run)
            current = (
                component
                if kind == "semantic"
                else temporal_component(
                    component.inner.kernel,
                    "unused",
                    component.contract,
                    run,
                    component.inner.bundle,
                )
            )
            owner.create(
                partition,
                current,
                budget=Budget(max_work_units=1_000_000),
                total_work_units=1_000_000_000,
            )
            if kind == "semantic":
                receipt = owner.step(
                    partition, current, "prediction", {"inputs": [flat[index].tolist()]}
                )
                logits = receipt["output"]["logits"][0]
            else:
                for j, event in enumerate(episodes[index]):
                    owner.step(
                        partition,
                        current,
                        f"event-{j}",
                        {"operation": "observe", "event": event},
                    )
                receipt = owner.step(
                    partition,
                    current,
                    "prediction",
                    {"operation": "predict", "action": [0.0]},
                )
                logits = receipt["output"]["logits"]
            exponential = np.exp(np.asarray(logits) - np.max(logits))
            outputs.append(
                {
                    "row": index,
                    "source_group": records[index]["source_group"],
                    "target": records[index]["target"],
                    "probability": float(exponential[1] / exponential.sum()),
                    "logits": logits,
                    "receipt": receipt,
                }
            )
    finally:
        owner.close()
    write_json(directory / f"{panel}.json", outputs)
    groups = sorted({r["source_group"] for r in outputs})
    brier = [
        float(
            np.mean(
                [
                    (r["probability"] - r["target"]) ** 2
                    for r in outputs
                    if r["source_group"] == group
                ]
            )
        )
        for group in groups
    ]
    return {
        "rows": len(outputs),
        "source_groups": len(groups),
        "group_brier": dict(zip(groups, brier)),
        "brier": float(np.mean(brier)),
        "correct": sum(int((r["probability"] > 0.5) == r["target"]) for r in outputs),
        "wall_seconds": time.perf_counter() - wall,
        "process_cpu_seconds": time.process_time() - cpu,
    }, outputs


def save_semantic(component, directory):
    wall, cpu = time.perf_counter(), time.process_time()
    with (directory / "model.npz").open("xb") as stream:
        np.savez(
            stream, first=component._cell.head.first, bias=component._cell.head.bias
        )
        stream.flush()
        os.fsync(stream.fileno())
    manifest = {
        "kind": "semantic",
        "binding": asdict(component._cell.binding),
        "bundle": asdict(component.bundle),
        "model_sha256": hashlib.sha256(
            (directory / "model.npz").read_bytes()
        ).hexdigest(),
        "identity": component.identity.digest,
    }
    manifest_hash = write_json(directory / "model.json", manifest)
    return {
        "manifest_sha256": manifest_hash,
        "wall_seconds": time.perf_counter() - wall,
        "process_cpu_seconds": time.process_time() - cpu,
        "serialized_bytes": sum(
            (directory / name).stat().st_size for name in ("model.npz", "model.json")
        ),
    }


def recover(spec_path):
    """Fresh interpreter: original owner readback and a new inference invocation."""
    wall, cpu = time.perf_counter(), time.process_time()
    spec = json.loads(Path(spec_path).read_text())
    directory = Path(spec["directory"])
    if spec["kind"] == "semantic":
        raw = (directory / "model.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["manifest_sha256"]:
            raise ValueError("semantic manifest changed")
        manifest = json.loads(raw)
        if (
            hashlib.sha256((directory / "model.npz").read_bytes()).hexdigest()
            != manifest["model_sha256"]
        ):
            raise ValueError("semantic model changed")
        with np.load(directory / "model.npz", allow_pickle=False) as data:
            component = semantic_component(
                LocalHead(data["first"], data["bias"]),
                SemanticBinding(**manifest["binding"]),
                Bundle(**manifest["bundle"]),
            )
        payload = {"inputs": [spec["flat"]]}
    elif spec["kind"] == "temporal":
        component, state, _, _ = restore_run(
            directory / "live-snapshot",
            expected_sha256=spec["manifest_sha256"],
            expected_identity=spec["identity"],
        )
        if state != spec["state"]:
            raise ValueError("restored temporal state differs")
        payload = {"operation": "predict", "action": [0.0]}
    else:
        raise ValueError("unknown recovery kind")
    if component.identity.digest != spec["identity"]:
        raise ValueError("cold component identity mismatch")
    partition = Partition(**spec["partition"])
    owner = CellOwner(directory / "owner.sqlite")
    try:
        if owner.checkpoint(partition)["state"] != spec["state"]:
            raise ValueError("original durable owner state differs")
        receipt = owner.step(partition, component, "cold-next-prediction", payload)
        logits = receipt["output"]["logits"]
        if spec["kind"] == "semantic":
            logits = logits[0]
        write_json(
            directory / "COLD_RESULT.json",
            {
                "pid": os.getpid(),
                "identity": component.identity.digest,
                "logits": logits,
                "receipt": receipt,
                "matches_pre_restart": logits == spec["expected_logits"],
                "wall_seconds": time.perf_counter() - wall,
                "process_cpu_seconds": time.process_time() - cpu,
            },
        )
    finally:
        owner.close()
