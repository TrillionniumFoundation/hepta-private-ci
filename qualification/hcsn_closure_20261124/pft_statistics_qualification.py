"""Reuse sealed #7071 training shards; no training or final-test access."""

import argparse
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np

from .pft_linear import solve_normal
from .pft_statistics import StatisticsLedger, canonical, digest, make_packet


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def cold_snapshot(database, contract, output):
    write(
        output,
        dict(
            pid=os.getpid(),
            **StatisticsLedger(database, contract).snapshot()["candidate"],
        ),
    )


def one_case(original, shards, output):
    started = time.perf_counter()
    output.mkdir()
    manifest = json.loads((original / "ring/MANIFEST.json").read_text())
    binding = manifest["objective_binding"]
    contract = dict(
        schema="pft-online-statistics-v1",
        model_family="hcsn-pft-readout-research-v1",
        epoch=0,
        parent_model_sha256=binding["parent_digest"],
        feature_program_sha256="c369c1393db613ff64b4b5e219e637d512e52d0841201bfb972f485cec9dfd1a",
        normalization_sha256=digest(
            dict(transform=binding["feature_transform"], scale=binding["scale"])
        ),
        objective_sha256=digest(dict(target=binding["target"], loss=binding["loss"])),
        time_semantics_sha256=digest(
            dict(
                original_protocol=binding["protocol_sha256"],
                scope="frozen final-state cache; no time resampling",
            )
        ),
        dimension=manifest["dimension"],
        outputs=manifest["outputs"],
        regularizer=manifest["regularizer"],
        dtype="float64",
        aggregation="sum-f64-canonical-batch-id",
        statistics_validation="augmented-psd-rtol-1e-10-v1",
    )
    xs, ys, packets, sources = [], [], [], []
    for i, entry in enumerate(manifest["peers"]):
        path = shards / f"shard{i}.npz"
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if source_hash != entry["sha256"]:
            raise ValueError("historical shard bytes differ")
        with np.load(path, allow_pickle=False) as z:
            x, y = z["x"].astype(np.float64), z["y"].astype(np.float64)
        ids = [digest([binding["train_sha256"], i, j]) for j in range(len(x))]
        packets.append(make_packet(contract, f"shard-{i}", source_hash, ids, x, y))
        xs.append(x)
        ys.append(y)
        sources.append(dict(shard=i, sha256=source_hash, count=len(x)))
    prepared = time.perf_counter()
    candidates = []
    for label, order in (("forward", packets), ("reverse", list(reversed(packets)))):
        ledger = StatisticsLedger(output / f"{label}.db", contract)
        receipts = []
        for packet in order:
            receipts.append(ledger.append(packet, ledger.state()["head"]))
        snapshot = ledger.snapshot()
        candidates.append(snapshot["candidate"])
        write(output / f"{label}-receipts.json", receipts)
        write(output / f"{label}-candidate.json", snapshot["candidate"])
    admitted = time.perf_counter()
    process = multiprocessing.get_context("spawn").Process(
        target=cold_snapshot,
        args=(str(output / "forward.db"), contract, str(output / "cold.json")),
    )
    process.start()
    process.join(45)
    if process.is_alive():
        process.terminate()
        process.join()
        raise TimeoutError("owned cold-reload worker timed out")
    if process.exitcode != 0:
        raise RuntimeError(f"cold reload exited {process.exitcode}")
    cold = json.loads((output / "cold.json").read_text())
    cold_pid = cold.pop("pid")
    x, y = np.vstack(xs), np.vstack(ys)
    regularizer, d = contract["regularizer"], contract["dimension"]
    # Independent augmented least squares: no normal-equation implementation reuse.
    pooled = np.linalg.lstsq(
        np.vstack((x, np.sqrt(regularizer) * np.eye(d))),
        np.vstack((y, np.zeros((d, contract["outputs"])))),
        rcond=None,
    )[0]
    with np.load(original / "SOLUTIONS.npz", allow_pickle=False) as z:
        historical = z["full"].copy()
    weight = np.asarray(candidates[0]["weight"])
    objective = lambda w: float(
        0.5 * (np.sum((x @ w - y) ** 2) + regularizer * np.sum(w * w))
    )
    duplicate = solve_normal(
        x.T @ x + xs[0].T @ xs[0], x.T @ y + xs[0].T @ ys[0], regularizer
    )
    repeated = solve_normal(x.T @ x, x.T @ y, len(xs) * regularizer)
    mixed = x.copy()
    mixed[: len(xs[0]), 0] *= 2
    wrong_normalization = solve_normal(mixed.T @ mixed, mixed.T @ y, regularizer)
    passed = (
        candidates[0] == candidates[1] == cold
        and cold_pid != os.getpid()
        and np.allclose(weight, pooled, rtol=1e-7, atol=1e-7)
        and np.allclose(weight, historical, rtol=1e-7, atol=1e-7)
    )
    with (output / "statistics.npz").open("xb") as stream:
        np.savez_compressed(
            stream, gram=snapshot["gram"], rhs=snapshot["rhs"], yty=snapshot["yty"]
        )
    write(output / "CONTRIBUTIONS.json", packets)
    result = dict(
        parent=original.name,
        passed=bool(passed),
        sources=sources,
        candidate_head=candidates[0]["head"],
        weight_sha256=candidates[0]["weight_sha256"],
        contract_sha256=digest(contract),
        cold_pid=cold_pid,
        cold_exit=process.exitcode,
        max_pooled_error=float(np.max(np.abs(weight - pooled))),
        max_historical_error=float(np.max(np.abs(weight - historical))),
        count=len(x),
        dimensions=[d, contract["outputs"]],
        objectives={
            "canonical": objective(weight),
            "pooled": objective(pooled),
            "duplicate_bypass": objective(duplicate),
            "regularizer_per_shard": objective(repeated),
            "mixed_normalization_bypass": objective(wrong_normalization),
        },
        preparation_seconds=prepared - started,
        admission_and_solve_seconds=admitted - prepared,
        cold_and_independent_validation_seconds=time.perf_counter() - admitted,
        total_seconds=time.perf_counter() - started,
        optimizer_steps=0,
        final_test_access=False,
        scope="historical synthetic-source HCSN training caches; engineering consistency only",
    )
    write(output / "RESULT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-root", "shards-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    source = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in (
            "pft_statistics.py",
            "pft_statistics_tests.py",
            "pft_statistics_qualification.py",
            "pft_linear.py",
        )
    }
    write(
        args.output / "SOURCE_FROZEN.json",
        dict(
            source=source,
            protocol_commit="2f1550b2e05505a2940687c2a9d7dbb08ef2fd31",
            parent_commit="88414dda04443897def179754779aecdca6f0296",
            numeric_rtol=1e-7,
            numeric_atol=1e-7,
            no_candidate_selection=True,
            pid=os.getpid(),
        ),
    )
    rows = []
    for parent in [f"n{n}-s{s}" for n in (8, 32, 64) for s in (17011, 27011, 37011)]:
        try:
            rows.append(
                one_case(
                    args.original_root / parent,
                    args.shards_root / parent,
                    args.output / parent,
                )
            )
        except Exception as error:
            rows.append(dict(parent=parent, passed=False, error=repr(error)))
        print(json.dumps({k: rows[-1][k] for k in ("parent", "passed")}), flush=True)
    summary = dict(
        schema="pft-online-cache-qualification-v1",
        rows=rows,
        expected=9,
        passed=sum(v["passed"] for v in rows),
        total_wall_seconds=time.perf_counter() - started,
        real_user_adoption=False,
        learned_circuit_superiority=False,
        production_settlement=False,
    )
    write(args.output / "RESULTS.json", summary)
    raise SystemExit(0 if summary["passed"] == 9 else 1)


if __name__ == "__main__":
    main()
