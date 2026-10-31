"""New-namespace development probe; never a heldout confirmation claim."""
import argparse
import gzip
import json
from pathlib import Path
import time

import numpy as np

from ..task_value_factorial_20261030.task import ContentAdapter, build_cohort, calibrate, save
from .execution import FLOAT64_CONTRACT, NUMERIC_CONTRACT, diagnose, rollout, source_hashes


def run(out, seed, count, checkpoint=None, numeric_contract=FLOAT64_CONTRACT):
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parents[1]/"task_value_factorial_20261030/PROTOCOL.json"
    protocol = json.loads(source.read_text())
    protocol["data_seed_base"] = 287103100
    adapter = ContentAdapter()
    confusion, calibration = calibrate(adapter, out, seed, 128, protocol)
    # Entirely new TRAIN-calibration data; no old heldout law or observations.
    rows, cohorts, diagnoses = [], {}, {}
    for label, spec in (("iid", protocol), ("ood", dict(protocol, **protocol["ood"]))):
        cohort = build_cohort(out/label, "validation", seed, count, spec)
        cohorts[label] = cohort
        policies = ["exact_teacher", "one_read"]+(["residual"] if checkpoint else [])
        order = np.random.default_rng(seed+10000+(label == "ood"))
        current = []
        for session in cohort["records"]:
            for policy in order.permutation(policies):
                row = rollout(session, adapter, confusion, protocol["multiplier"], protocol["latency_price"],
                              policy, checkpoint, numeric_contract=numeric_contract)
                row["development_distribution"] = label
                rows.append(row)
                current.append(row)
        meta = {s["id"]:json.loads((Path(s["folder"])/"public.json").read_text()) for s in cohort["records"]}
        diagnoses[label] = diagnose(current, meta, confusion, protocol["multiplier"], protocol["latency_price"])
    summaries = {}
    for label in cohorts:
        summaries[label] = {}
        for policy in policies:
            group = [r for r in rows if r["policy"] == policy and r["development_distribution"] == label]
            regrets = [r["cumulative_regret"] for r in diagnoses[label]["rows"] if r["policy"] == policy]
            summaries[label][policy] = dict(utility=float(np.mean([r["score"]["utility"] for r in group])),
                completed=float(np.mean([r["score"]["completed_jobs"] for r in group])),
                cpu_seconds=float(np.mean([r["cpu_seconds"] for r in group])),
                controller_cpu_seconds=float(np.mean([r["controller_cpu_seconds"] for r in group])),
                teacher_regret=float(np.mean(regrets)))
    result = dict(scope="Development probe on fresh namespace; not confirmation", source_hashes=source_hashes(),
        protocol=protocol, seed=seed, count=count, numeric_contract=numeric_contract,
        calibration=calibration, adapter_setup=adapter.setup,
        cohorts=cohorts, rows=rows, diagnoses=diagnoses, summaries=summaries)
    with (out/"PROBE.json.gz").open("xb") as stream:
        stream.write(gzip.compress(json.dumps(result, allow_nan=False, separators=(",", ":")).encode(), mtime=0))
    print(json.dumps(dict(out=str(out), summaries=summaries)), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=72031)
    parser.add_argument("--count", type=int, default=64)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--numeric-contract", choices=(FLOAT64_CONTRACT, NUMERIC_CONTRACT), default=FLOAT64_CONTRACT)
    args = parser.parse_args()
    checkpoint = json.loads(args.checkpoint.read_text()) if args.checkpoint else None
    run(args.out, args.seed, args.count, checkpoint, args.numeric_contract)


if __name__ == "__main__":
    main()
