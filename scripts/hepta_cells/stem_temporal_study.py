"""Semantic/GRU/CfC retained replay under one research-only protocol.

B selects a candidate for subsequent C replay. All groups were historically
exposed; neither the replay clock nor source independence is authenticated.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .component_types import Partition, digest
from .lifecycle import CellOwner
from .semantic import LocalHead, SemanticBinding
from .stem_study_support import (
    prepare,
    recover,
    save_semantic,
    semantic_component,
    serve,
    temporal_component,
    write_json,
)
from .temporal import TemporalConfig, TemporalKernel


def run(dataset, output, *, widths=(2, 4, 8), updates=32):
    if (
        not widths
        or len(set(widths)) != len(widths)
        or any(type(w) is not int or not 1 <= w <= 32 for w in widths)
        or type(updates) is not int
        or not 1 <= updates <= 128
    ):
        raise ValueError("invalid predeclared model budget")
    root = Path(output)
    root.mkdir()
    wall, cpu = time.perf_counter(), time.process_time()
    data, data_hash, panels, episodes, flat, contract, normalizer = prepare(dataset)
    write_json(
        root / "DESIGN.json",
        {
            "dataset_sha256": data_hash,
            "panels": panels,
            "normalizer": normalizer,
            "widths": list(widths),
            "updates": updates,
            "semantic_lr": 0.03,
            "temporal_lr": 0.003,
            "selection": "lowest B source-group mean Brier; C never selects",
            "seed": 0,
            "ordinary_daemon_qualification": False,
            "fresh_confirmation": 0,
            "time_provenance": "offline replay derived from observed capture spacing, not original availability",
            "matched": [
                "retained input/feedback rows",
                "task identity",
                "time information",
                "train-only normalization",
                "updates per fit",
            ],
            "unmatched": [
                "parameters",
                "optimizer rule",
                "state capacity",
                "actual compute and latency",
            ],
            "historically_exposed_B_C": True,
            "source_independence_verified": False,
        },
    )
    labels = np.asarray([r["target"] for r in data["records"]], dtype=np.int64)
    train = panels["train"]
    binding = SemanticBinding(
        *(
            digest([data_hash, name])
            for name in (
                "retained-feature-identity",
                "flattened-time-history",
                "identity-provider",
                "no-tokenizer",
                "numpy-float64",
            )
        )
    )
    head = LocalHead.initialize(flat.shape[1], 2)
    entries, components, failures = {}, {}, []
    prevalence = float(labels[train].mean())
    recipes = [
        ("constant-zero", "baseline", 0),
        ("train-prevalence", "baseline", prevalence),
        ("semantic-linear", "semantic", 0),
    ]
    recipes += [
        (f"{kind}-{width}", kind, width) for kind in ("gru", "cfc") for width in widths
    ]
    for name, kind, size in recipes:
        directory = root / name
        directory.mkdir()
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        write_json(
            directory / "STARTED.json",
            {
                "arm": name,
                "kind": kind,
                "dataset_sha256": data_hash,
                "planned_updates": 0 if kind == "baseline" else updates,
                "started_unix_seconds": time.time(),
                "status": "started; unresolved without a terminal receipt",
                "actual_cost_unknown_until_settled": True,
            },
        )
        stage = "initialize"
        try:
            source = semantic_component(head, binding)
            if kind == "baseline":
                biases = np.log(np.array([1 - size, size]).clip(np.exp(-700), 1))
                current = semantic_component(LocalHead(head.first, biases), binding)
                measured_kind, receipt = "semantic", None
            elif kind == "semantic":
                stage = "training"
                current, candidate = source.propose(
                    list(flat[train]),
                    labels[train],
                    artifact_id="retained-linear-candidate",
                    evaluation_profile=digest([data_hash, panels["B"]]),
                    steps=updates,
                    learning_rate=0.03,
                )
                receipt, measured_kind = candidate.training_receipt, "semantic"
                write_json(directory / "TRAINING.json", receipt)
            else:
                kernel = TemporalKernel(
                    "predictor",
                    TemporalConfig(
                        2 * contract.value_dim + 1, 1, 2, hidden_dim=size, kind=kind
                    ),
                )
                source = temporal_component(kernel, data_hash, contract)
                stage = "training"
                candidate, receipt = source.train_candidate(
                    [episodes[i] for i in train],
                    [0] * len(train),
                    np.zeros((len(train), 1)),
                    np.eye(2, dtype=bool)[labels[train]],
                    updates=updates,
                    lr=0.003,
                )
                write_json(directory / "TRAINING.json", receipt)
                stage = "binding"
                candidate_bundle = source.inner.bundle.successor(
                    "retained-candidate-" + name,
                    {
                        **source.inner.bundle.components,
                        "base": candidate.kernel_sha256,
                        "heads": candidate.heads_sha256,
                    },
                    receipt["data_sha256"],
                    digest(["adam", updates, 0.003]),
                    digest([data_hash, panels["B"]]),
                )
                current, measured_kind = (
                    temporal_component(
                        candidate, data_hash, contract, bundle=candidate_bundle
                    ),
                    "temporal",
                )
            stage = "checkpoint"
            saved = (
                save_semantic(current, directory)
                if measured_kind == "semantic"
                else current.checkpoint(directory / "model", current.initial_state())
            )
            write_json(directory / "SAVE.json", saved)
            stage = "B-evaluation"
            metrics, _ = serve(
                current,
                measured_kind,
                directory,
                data["records"],
                panels["B"],
                episodes,
                flat,
                "B",
            )
            parameters = (
                sum(a.size for a in current._cell.head.arrays)
                if measured_kind == "semantic"
                else current.inner.kernel.parameter_count
            )
            entries[name] = {
                "kind": measured_kind,
                "baseline": kind == "baseline",
                "B": metrics,
                "parameters": parameters,
                "identity": current.identity.digest,
                "save": saved,
                "training": receipt,
                "wall_seconds": time.perf_counter() - start_wall,
                "process_cpu_seconds": time.process_time() - start_cpu,
            }
            components[name] = current
        except Exception as error:
            if (
                stage == "training"
                and hasattr(error, "receipt")
                and not (directory / "TRAINING.json").exists()
            ):
                write_json(directory / "TRAINING.json", error.receipt)
            failure = {
                "arm": name,
                "stage": stage,
                "error": f"{type(error).__name__}: {error}",
                "receipt": getattr(error, "receipt", None),
                "wall_seconds": time.perf_counter() - start_wall,
                "process_cpu_seconds": time.process_time() - start_cpu,
            }
            failures.append(failure)
            write_json(directory / "FAILURE.json", failure)
    candidates = [name for name in entries if not entries[name]["baseline"]]
    if not candidates:
        raise RuntimeError("all candidate attempts failed; original receipts retained")
    selected = min(candidates, key=lambda name: (entries[name]["B"]["brier"], name))
    selection = {
        "selected_for_research_next_use": selected,
        "B_scores": {n: e["B"]["brier"] for n, e in entries.items()},
        "promotion": "NoUpdate",
        "ordinary_Adopt": 0,
        "ordinary_NoUpdate": 0,
        "fresh_confirmation": 0,
    }
    write_json(root / "SELECTION.json", selection)
    for name in ("constant-zero", "train-prevalence", selected):
        if name in entries:
            entries[name]["C"], outputs = serve(
                components[name],
                entries[name]["kind"],
                root / name,
                data["records"],
                panels["C"],
                episodes,
                flat,
                "C",
            )
            if name == selected:
                selected_outputs = outputs
    current, directory, index = components[selected], root / selected, panels["C"][0]
    partition = Partition("research", "stem-study", "predictor", f"row-{index}")
    owner = CellOwner(directory / "owner.sqlite")
    state = owner.checkpoint(partition)["state"]
    owner.close()
    if entries[selected]["kind"] == "semantic":
        saved = entries[selected]["save"]
    else:
        current = temporal_component(
            current.inner.kernel,
            data_hash,
            contract,
            partition.run_id,
            current.inner.bundle,
        )
        saved = current.checkpoint(directory / "live-snapshot", state)
        write_json(directory / "LIVE_SAVE.json", saved)
    spec = {
        "directory": str(directory.resolve()),
        "kind": entries[selected]["kind"],
        "manifest_sha256": saved["manifest_sha256"],
        "identity": current.identity.digest,
        "partition": asdict(partition),
        "state": state,
        "flat": flat[index].tolist(),
        "expected_logits": selected_outputs[0]["logits"],
    }
    write_json(root / "COLD_REQUEST.json", spec)
    cold_wall, cold_cpu = time.perf_counter(), time.process_time()
    child_env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(
            [str(Path(__file__).resolve().parents[1]), os.environ.get("PYTHONPATH", "")]
        ),
    )
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "hepta_cells.stem_temporal_study",
            "--recover",
            str((root / "COLD_REQUEST.json").resolve()),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=child_env,
    )
    write_json(
        root / "COLD_PROCESS.json",
        {
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "wall_seconds": time.perf_counter() - cold_wall,
            "parent_cpu_seconds": time.process_time() - cold_cpu,
        },
    )
    if process.returncode:
        raise RuntimeError("cold recovery failed; retained original child logs")
    recovery = json.loads((directory / "COLD_RESULT.json").read_text())
    if not recovery["matches_pre_restart"] or recovery["pid"] == os.getpid():
        raise RuntimeError("cold recovery prediction or process identity failed")
    sources = {
        n: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
        for n, m in sys.modules.items()
        if n.startswith(("hepta_cells", "hepta_pred1")) and getattr(m, "__file__", None)
    }
    sources["hepta_cells.stem_temporal_study"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    report = {
        "schema": "hepta.cell.stem-temporal-study.v1",
        "dataset_sha256": data_hash,
        "status": "HOLD-RESEARCH_ONLY",
        "selection": selection,
        "arms": entries,
        "failed_attempts": failures,
        "cold_recovery": recovery,
        "source_groups": len({r["source_group"] for r in data["records"]}),
        "fresh_confirmation": 0,
        "ordinary_daemon_complete_loop": False,
        "dataset_fixture_only": data.get("fixture_only", False),
        "energy_joules": None,
        "encoder_capture_cost": "not measured in this retained replay",
        "total_wall_seconds": time.perf_counter() - wall,
        "parent_process_cpu_seconds": time.process_time() - cpu,
        "child_recovery_process_cpu_seconds": recovery["process_cpu_seconds"],
        "cost_scope": "all attempted fits, provider copies, SQLite serving, serialization, B/C and child wall; historical encoder capture and child interpreter startup CPU excluded",
        "source_sha256": sources,
    }
    write_json(root / "RESULT.json", report)
    return report


if __name__ == "__main__":
    if sys.argv[1:2] == ["--recover"]:
        recover(sys.argv[2])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("dataset", type=Path)
        parser.add_argument("output", type=Path)
        parser.add_argument("--updates", type=int, default=32)
        parser.add_argument("--widths", default="2,4,8")
        args = parser.parse_args()
        result = run(
            args.dataset,
            args.output,
            widths=tuple(map(int, args.widths.split(","))),
            updates=args.updates,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "selection": result["selection"],
                    "failed_attempts": len(result["failed_attempts"]),
                },
                sort_keys=True,
            )
        )
