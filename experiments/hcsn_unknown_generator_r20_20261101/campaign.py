"""Frozen context-reference study with stratified selective-risk calibration."""

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
from scipy.stats import beta

from experiments.hcsn_unknown_generator_r18_20261101.campaign import evaluate
from experiments.hcsn_unknown_generator_r18_20261101.posterior import query_key
from .model import fit, infer
from .world import sample

ROOT = Path(__file__).parent


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen(name, receipt):
    freeze = json.loads((ROOT / name).read_text())
    for path, expected in freeze["files"].items():
        if digest(ROOT / path) != expected:
            raise ValueError("Frozen source/model changed: " + path)
    publication = json.loads((ROOT / receipt).read_text())
    if publication.get("readback_verified") is not True or publication["freeze_sha256"] != digest(ROOT / name):
        raise ValueError("Missing verified remote publication")
    return freeze


def archive(directory, name, rows):
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path = directory / (name + ".json.gz")
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
    return dict(path=str(path.relative_to(ROOT)), sha256=digest(path),
                raw_sha256=hashlib.sha256(raw).hexdigest(), records=len(rows))


def public(world):
    return {key:world[key].tolist() for key in ("prefix", "observed", "bridges", "query", "dt", "owner_events")}


def predictions(world, models, cutoffs, thresholds):
    result = {}
    for name, particles in models.items():
        try:
            state = infer(world["prefix"], world["observed"], particles)
            key = query_key(world["bridges"], world["query"])
            result[name] = {str(t):evaluate(world, state, key, world["price"], t, state.surprise <= cutoffs[name])
                            for t in thresholds[name]}
        except ValueError as error:
            result[name] = {str(t):dict(invalid=True, accepted=False, read_index=None, reason=str(error)) for t in thresholds[name]}
    return result


def upper(errors, count, delta):
    return 1. if not count or errors == count else float(beta.ppf(1 - delta, errors + 1, count - errors))


def prepare(spec):
    out = ROOT / "prepare_01"
    out.mkdir(exist_ok=False)
    groups = [[sample("train", g, i, complete=True)["prefix"] for i in range(spec["training_worlds_per_generator"])]
              for g in range(spec["training_generators"])]
    models, diagnostics = fit(groups)
    write(out / "FIT_DIAGNOSTICS.json", diagnostics)
    write(out / "MODELS_ARCHIVE.json", archive(out, "MODELS", models))
    archives = [archive(out, "training", [[x.tolist() for x in group] for group in groups])]
    scores = {name:[] for name in models}
    for g in range(spec["ood_generators"]):
        world = sample("ood", g, 0)
        for name, particles in models.items():
            scores[name].append(infer(world["prefix"], world["observed"], particles).surprise)
    cutoffs = {name:float(np.quantile(values, .99, method="higher")) for name, values in scores.items()}
    write(out / "OOD.json", dict(scores=scores, cutoffs=cutoffs))
    grid = {stratum:{name:{str(t):dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0)
                  for t in spec["thresholds"]} for name in models} for stratum in spec["calibration_strata"]}
    rows = []
    for stratum, count in spec["calibration_strata"].items():
        for g in range(count):
            world = sample(stratum, g, 0)
            values = predictions(world, models, cutoffs, {n:spec["thresholds"] for n in models})
            rows.append(dict(stratum=stratum, generator=g, target=world["target"], price=world["price"], public=public(world), predictions=values))
            for name, candidates in values.items():
                for t, value in candidates.items():
                    entry = grid[stratum][name][t]
                    entry["invalid"] += value["invalid"]
                    if not value["invalid"]:
                        a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                        for k, v in zip(("accepted", "errors", "fractional", "fractional_errors"), (a, a and e, f, f and e), strict=True):
                            entry[k] += v
            if len(rows) == 64:
                archives.append(archive(out, "risk_%03d" % len(archives), rows))
                rows = []
    delta = spec["family_error_probability"] / (len(models) * len(spec["thresholds"]) * len(grid) * 2)
    selected = {}
    for name in models:
        passing = []
        for threshold in map(str, spec["thresholds"]):
            entries = [grid[stratum][name][threshold] for stratum in grid]
            for entry in entries:
                entry["upper_error"] = upper(entry["errors"], entry["accepted"], delta)
                entry["upper_fractional_error"] = upper(entry["fractional_errors"], entry["fractional"], delta)
                entry["passed"] = bool(not entry["invalid"] and entry["upper_error"] <= spec["risk_limit"]
                    and entry["upper_fractional_error"] <= spec["risk_limit"] and entry["fractional"] >= spec["minimum_fractional_calibration_answers"])
            if all(entry["passed"] for entry in entries):
                passing.append((sum(entry["fractional"] for entry in entries), -float(threshold), float(threshold)))
        selected[name] = dict(calibration_gate_passed=bool(passing), threshold=max(passing)[2] if passing else 1 - 1e-12)
    write(out / "CALIBRATION.json", dict(grid=grid, selected=selected, simultaneous_delta=delta))
    write(out / "ARCHIVES.json", archives)
    write(ROOT / "POSTCALIBRATION_FREEZE.json", dict(schema="hcsn.r20.calibration.freeze.v1", confirmation_opened=False,
        files={str(p.relative_to(ROOT)):digest(p) for p in (out / n for n in ("MODELS.json.gz", "MODELS_ARCHIVE.json", "FIT_DIAGNOSTICS.json", "OOD.json", "CALIBRATION.json", "ARCHIVES.json"))}))


def summarize(rows, spec, selected):
    summary = dict(models={}, production_activation=False, all_blockers_closed=False)
    for panel in spec["panels"]:
        main = [r for r in rows if r["panel"] == panel]
        rng = np.random.default_rng(2005513)
        boot = rng.integers(spec["confirmation_generators_per_panel"], size=(4096, spec["confirmation_generators_per_panel"]))
        grouped = {}
        for name in spec["models"]:
            raw = [next(iter(r["predictions"][name].values())) for r in main]
            invalid = sum(v["invalid"] for v in raw)
            value = dict(attempts=len(raw), invalid=invalid, quality=None)
            if not invalid:
                stats = np.zeros((spec["confirmation_generators_per_panel"], 9))
                for row, record in zip(main, raw, strict=True):
                    a, f, e = record["accepted"], record["accepted"] and record["fractional"], not record["correct"]
                    stats[row["generator"]] += [a, a and e, f, f and e, record["payoff"], record["before_brier"],
                        record["true_probability"] <= 0, record["read_index"] is not None, record["payoff"] - record["no_read_payoff"]]
                grouped[name] = stats / spec["worlds_per_generator"]
                draws = stats[boot].sum(1)
                risk = np.divide(draws[:, 3], draws[:, 2], out=np.ones(4096), where=draws[:, 2] > 0)
                overall = np.divide(draws[:, 1], draws[:, 0], out=np.ones(4096), where=draws[:, 0] > 0)
                total = stats.sum(0)
                value["quality"] = dict(accepted=int(total[0]), errors=int(total[1]), fractional=int(total[2]), fractional_errors=int(total[3]),
                    payoff=float(total[4] / len(main)), before_brier=float(total[5] / len(main)), support_losses=int(total[6]), reads=int(total[7]),
                    read_net_effect=float(total[8] / len(main)), upper95_fractional=float(np.quantile(risk, .95)), upper95_overall=float(np.quantile(overall, .95)),
                    gate=bool(selected[name]["calibration_gate_passed"] and not total[6] and total[2] >= spec["minimum_fractional_confirmation_answers"]
                              and np.quantile(risk, .95) <= spec["risk_limit"] and np.quantile(overall, .95) <= spec["risk_limit"]))
            summary["models"][panel + ":" + name] = value
        if len(grouped) == 3:
            payoff = grouped["context_orbit"][:, 4] - grouped["orbit_first_order"][:, 4]
            brier = grouped["orbit_first_order"][:, 5] - grouped["context_orbit"][:, 5]
            summary[panel + ":paired"] = dict(payoff_difference=float(payoff.mean()), payoff_ci95=np.quantile(payoff[boot].mean(1), [.025, .975]).tolist(),
                before_brier_improvement=float(brier.mean()), before_brier_ci95=np.quantile(brier[boot].mean(1), [.025, .975]).tolist())
    summary["declared_shift_gate"] = all(summary["models"][p + ":context_orbit"]["quality"] is not None
        and summary["models"][p + ":context_orbit"]["quality"]["gate"] for p in ("relabeled_lag2", "lag2_skip"))
    return summary


def confirm(spec):
    frozen("POSTCALIBRATION_FREEZE.json", "CALIBRATION_PUBLICATION.json")
    prepared = ROOT / "prepare_01"
    models = json.loads(gzip.decompress((prepared / "MODELS.json.gz").read_bytes()))
    cutoffs = json.loads((prepared / "OOD.json").read_text())["cutoffs"]
    selected = json.loads((prepared / "CALIBRATION.json").read_text())["selected"]
    thresholds = {name:[v["threshold"]] for name, v in selected.items()}
    out = ROOT / "confirm_01"
    out.mkdir(exist_ok=False)
    rows, archives, chunk = [], [], []
    for panel in spec["panels"]:
        for g in range(spec["confirmation_generators_per_panel"]):
            for index in range(spec["worlds_per_generator"]):
                world = sample(panel, g, index)
                row = dict(panel=panel, generator=g, index=index, public=public(world), target=world["target"], price=world["price"],
                    predictions=predictions(world, models, cutoffs, thresholds))
                rows.append(row)
                chunk.append(row)
                if len(chunk) == 64:
                    archives.append(archive(out, "worlds_%03d" % len(archives), chunk))
                    chunk = []
    write(out / "ARCHIVES.json", archives)
    write(out / "SUMMARY.json", summarize(rows, spec, selected))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "confirm"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    frozen("SOURCE_FREEZE.json", "SOURCE_PUBLICATION.json")
    spec = json.loads((ROOT / "protocol.json").read_text())
    if args.child:
        (prepare if args.stage == "prepare" else confirm)(spec)
        return
    start = time.perf_counter()
    process = subprocess.Popen([sys.executable, "-m", __spec__.name, args.stage, "--child"])
    _, status, usage = os.wait4(process.pid, 0)
    process.returncode = os.waitstatus_to_exitcode(status)
    write(ROOT / (args.stage.upper() + "_PROCESS_RECEIPT.json"), dict(exit_code=process.returncode,
        child_cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.perf_counter() - start, max_rss_kib=usage.ru_maxrss,
        scope="Full child interpreter/import/all candidates/all attempts/output; engineering and independent audits separate"))
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
