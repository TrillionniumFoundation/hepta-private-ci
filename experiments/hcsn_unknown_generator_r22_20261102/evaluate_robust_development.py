"""OLD development cohort only: maximin control versus the same density's nominal policy."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from experiments.hcsn_unknown_generator_r18_20261101.posterior import query_key
from experiments.hcsn_unknown_generator_r20_20261101.model import infer
from .controller import execute
from .evaluate_development import PANELS, archive, write

ROOT = Path(__file__).parent


def child():
    output = ROOT / "robust_development_01"
    output.mkdir(exist_ok=False)
    models = json.loads(gzip.decompress((ROOT / "development_fit_final/MODELS.json.gz").read_bytes()))
    summary, inputs = {}, {}
    for panel in PANELS:
        old = ROOT / "masked_development_01"
        index = json.loads((old / (panel + "_ARCHIVES.json")).read_text())
        counts = {name:dict(worlds=0, accepted=0, errors=0, fractional=0, fractional_errors=0,
            reads=0, fees=0., utility=0., before_brier=0.) for name in
            ("context_robust", "first_robust", "context_nominal", "first_nominal")}
        rows, archives = [], []
        for item in index[:4]:
            path = old / item["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Old development output changed")
            inputs[str(path.relative_to(ROOT))] = item["sha256"]
            for record in json.loads(gzip.decompress(path.read_bytes())):
                if record["generator"] >= 64:
                    raise ValueError("Fixed old cohort range changed")
                world = {name:np.asarray(value) for name, value in record["old_public"].items()}
                world.update(target=record["target"], price=record["price"])
                key = query_key(world["bridges"], world["query"])
                states = {name:infer(world["prefix"], world["observed"], model) for name, model in models.items()}
                values = {}
                for family in ("context", "first"):
                    values[family + "_robust"] = execute(world, [states[family + "_mixture"], states[family + "_orbit"]], key, .9)
                    values[family + "_nominal"] = record["predictions"][family + "_mixture"]["0.9"]
                    if values[family + "_robust"]["before"] != values[family + "_nominal"]["before"]:
                        raise ValueError("Controller comparison changed its normalized forecast")
                for name, value in values.items():
                    c = counts[name]
                    a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                    for label, amount in zip(("worlds", "accepted", "errors", "fractional", "fractional_errors", "reads"),
                            (1, a, a and e, f, f and e, value["read_index"] is not None), strict=True):
                        c[label] += amount
                    c["fees"] += value["fee"]
                    c["utility"] += value["payoff"]
                    c["before_brier"] += value["before_brier"]
                rows.append(dict(panel=panel, generator=record["generator"], index=record["index"],
                    old_public=record["old_public"], target=record["target"], price=record["price"], predictions=values))
                if len(rows) == 64:
                    archives.append(archive(output / (panel + "_%03d.json.gz" % len(archives)), rows))
                    rows = []
        for value in counts.values():
            if value["worlds"] != 256:
                raise ValueError("Incomplete development cohort")
            value["fractional_rate"] = value["fractional"] / 256
            value["fractional_risk"] = value["fractional_errors"] / value["fractional"] if value["fractional"] else None
            value["mean_utility"] = value["utility"] / 256
        summary[panel] = counts
        write(output / (panel + "_ARCHIVES.json"), archives)
    write(output / "SUMMARY.json", dict(panels=summary, input_hashes=inputs, threshold=.9,
        scope="ExistingR20development only, first64oldgenerators x4worlds/panel. Samefirstnormalizedforecast forrobust/nominal, distinctdecisionconfidence, eachpolicy ownactualREAD/fee. No new world generator calls or confidence qualification.",
        fresh_calibration=False, fresh_confirmation=False, full_model_adoption=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        child()
        return
    start = time.perf_counter()
    process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--child"])
    _, status, usage = os.wait4(process.pid, 0)
    process.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(exit_code=process.returncode, child_cpu_seconds=usage.ru_utime + usage.ru_stime,
        wall_seconds=time.perf_counter() - start, max_process_rss_kib=usage.ru_maxrss, new_worlds_opened=0)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    write(ROOT / "ROBUST_DEVELOPMENT_01_PROCESS_RECEIPT.json", receipt)
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
