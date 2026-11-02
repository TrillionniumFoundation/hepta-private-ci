"""Masked OLD R20 data are development only; no new generator is called."""

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

from experiments.hcsn_unknown_generator_r18_20261101.campaign import evaluate
from experiments.hcsn_unknown_generator_r18_20261101.posterior import query_key
from experiments.hcsn_unknown_generator_r20_20261101.model import infer

ROOT = Path(__file__).parent
OLD = ROOT.parent / "hcsn_unknown_generator_r20_20261101"
PANELS = ("confirm", "reverse", "lag2", "relabeled_lag2", "lag2_skip")
THRESHOLDS = (.9, .95, .975)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def archive(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
    return dict(path=path.name, sha256=digest(path), raw_sha256=hashlib.sha256(raw).hexdigest())


def child():
    output = ROOT / "masked_development_01"
    output.mkdir(exist_ok=False)
    models = json.loads(gzip.decompress((ROOT / "development_fit_final/MODELS.json.gz").read_bytes()))
    old_models = json.loads(gzip.decompress((OLD / "prepare_01/MODELS.json.gz").read_bytes()))
    models["r20_context_common"] = old_models["context_orbit"]
    summary, inputs = {}, {}
    for panel in PANELS:
        rows, archives, seen = [], [], set()
        counts = {name:{str(t):dict(worlds=0, invalid=0, accepted=0, errors=0, fractional=0,
            fractional_errors=0, reads=0, fees=0., utility=0., before_brier=0., after_brier=0.)
            for t in THRESHOLDS} for name in models}
        index = json.loads((OLD / "confirm_v2_01" / panel / "ARCHIVES.json").read_text())
        for entry in index[:4]:
            source = OLD / entry["path"]
            if digest(source) != entry["sha256"]:
                raise ValueError("R20 development archive changed")
            raw = gzip.decompress(source.read_bytes())
            if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
                raise ValueError("R20 raw archive changed")
            inputs[entry["path"]] = entry["sha256"]
            for record in json.loads(raw):
                identity = record["generator"], record["index"]
                if identity in seen or not 0 <= identity[0] < 256 or not 0 <= identity[1] < 4:
                    raise ValueError("Development generator selection changed")
                seen.add(identity)
                world = {name:np.asarray(value) for name, value in record["public"].items()}
                world.update(price=record["price"], target=record["target"])
                key = query_key(world["bridges"], world["query"])
                predicted = {}
                for name, model in models.items():
                    state = infer(world["prefix"], world["observed"], model)
                    predicted[name] = {}
                    for threshold in THRESHOLDS:
                        value = evaluate(world, state, key, world["price"], threshold, True)
                        predicted[name][str(threshold)] = value
                        c = counts[name][str(threshold)]
                        a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                        for label, amount in zip(("worlds", "accepted", "errors", "fractional", "fractional_errors", "reads"),
                            (1, a, a and e, f, f and e, value["read_index"] is not None), strict=True):
                            c[label] += amount
                        for label, field in (("fees", "fee"), ("utility", "payoff"), ("before_brier", "before_brier"), ("after_brier", "brier")):
                            c[label] += value[field]
                rows.append(dict(panel=panel, generator=identity[0], index=identity[1],
                    old_public=record["public"], target=record["target"], price=record["price"], predictions=predicted))
                if len(rows) == 64:
                    archives.append(archive(output / (panel + "_%03d.json.gz" % len(archives)), rows))
                    rows = []
        if len(seen) != 1024 or rows:
            raise ValueError("Incomplete fixed old-development cohort")
        for values in counts.values():
            for value in values.values():
                value["fractional_rate"] = value["fractional"] / value["worlds"]
                value["fractional_risk"] = value["fractional_errors"] / value["fractional"] if value["fractional"] else None
                value["mean_utility"] = value["utility"] / value["worlds"]
                value["mean_before_brier"] = value["before_brier"] / value["worlds"]
        summary[panel] = counts
        write(output / (panel + "_ARCHIVES.json"), archives)
    write(output / "SUMMARY.json", dict(schema="hcsn.r22.old-development.v1", panels=summary,
        input_archive_hashes=inputs, candidate_models_sha256=digest(ROOT / "development_fit_final/MODELS.json.gz"),
        old_model_sha256=digest(OLD / "prepare_01/MODELS.json.gz"),
        scope="R20 examined panels are development. First256generators x4worlds/panel. No new world calls. Allfive density models use same schema-valid admission, same oneREAD/fees/threshold grid; old R20 OOD policy is not reused or claimed unchanged.",
        fresh_calibration=False, fresh_confirmation=False, full_model_adoption=False, production_activation=False))


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
        wall_seconds=time.perf_counter() - start, max_process_rss_kib=usage.ru_maxrss,
        scope="Complete old-development evaluation child/imports/allmodels/allthresholds/paidactions/rawoutput; not new confirmation")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    write(ROOT / "MASKED_DEVELOPMENT_01_PROCESS_RECEIPT.json", receipt)
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
