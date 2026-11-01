"""Separate fitting/calibration and locked new-generator verification stages."""

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

from .fit import fit
from .posterior import infer, query_key
from .world import sample

ROOT = Path(__file__).parent


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen():
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for name, sha in freeze["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError(f"Source changed after freeze: {name}")
    publication = json.loads((ROOT / "SOURCE_PUBLICATION.json").read_text())
    if (publication.get("source_freeze_sha256") != digest(ROOT / "SOURCE_FREEZE.json")
            or publication.get("readback_verified") is not True or len(publication.get("commit_sha", "")) != 40):
        raise ValueError("Unverified immutable source publication")
    return json.loads((ROOT / "protocol.json").read_text())


def archive(directory, name, rows):
    data = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path = directory / (name + ".json.gz")
    with path.open("xb") as stream:
        stream.write(gzip.compress(data, mtime=0))
    return dict(path=str(path.relative_to(ROOT)), records=len(rows), compressed_sha256=digest(path),
                raw_sha256=hashlib.sha256(data).hexdigest(), raw_bytes=len(data))


def public(world):
    return {name:world[name].tolist() for name in ("prefix", "observed", "bridges", "query", "dt")}


def evaluate(world, posterior, key, price, threshold, admitted):
    before = posterior.probability(key)
    index, _ = posterior.choose(key, price, threshold) if admitted else (None, None)
    after = posterior.acquire(index, world["owner_events"][index]) if index is not None else posterior
    p = after.probability(key)
    confidence = float(p.max())
    accepted = bool(admitted and confidence >= threshold)
    fractional = bool(confidence < 1 - 1e-9)
    fee = price if index is not None else 0.
    # Owner target is accessed only after every inference/action decision above.
    correct, stop_correct = int(p.argmax() == world["target"]), int(before.argmax() == world["target"])
    stop_accepted = bool(admitted and before.max() >= threshold)
    return dict(invalid=False, admitted=bool(admitted), probability=p.tolist(), before=before.tolist(),
                accepted=accepted, fractional=fractional, correct=correct, confidence=confidence,
                fee=fee, read_index=index,
                actual_read=world["owner_events"][index].tolist() if index is not None else None,
                payoff=(2 * correct - 1 if accepted else 0) - fee,
                no_read_payoff=(2 * stop_correct - 1 if stop_accepted else 0),
                brier=float(np.sum((p - np.eye(4)[world["target"]]) ** 2)),
                before_brier=float(np.sum((before - np.eye(4)[world["target"]]) ** 2)),
                before_log_loss=float(-np.log(before[world["target"]])) if before[world["target"]] > 0 else None,
                log_loss=float(-np.log(p[world["target"]])) if p[world["target"]] > 0 else None,
                true_probability=float(p[world["target"]]), surprise=posterior.surprise)


def predictions(world, models, cutoffs, thresholds):
    result = {}
    for name, particles in models.items():
        try:
            key = query_key(world["bridges"], world["query"])
            posterior = infer(world["prefix"], world["observed"], particles)
            admitted = posterior.surprise <= cutoffs[name]
            result[name] = {str(threshold):evaluate(world, posterior, key, world["price"], threshold, admitted)
                            for threshold in thresholds[name]}
        except ValueError as error:
            result[name] = {str(threshold):dict(invalid=True, accepted=False, read_index=None,
                                                reason=str(error), admitted=False)
                            for threshold in thresholds[name]}
    return result


def upper(errors, count, delta):
    return 1. if count == 0 or errors == count else float(beta.ppf(1 - delta, errors + 1, count - errors))


def prepare():
    spec = frozen()
    output = ROOT / "calibration_01"
    output.mkdir(exist_ok=False)
    groups = [[sample("train", generator, index, complete=True)["prefix"]
               for index in range(spec["train_worlds_per_generator"])]
              for generator in range(spec["train_generators"])]
    models = fit(groups)
    write(output / "MODELS.json", models)
    training_archive = archive(output, "TRAINING_PUBLIC_RAW", [[x.tolist() for x in group] for group in groups])
    scores, ood_rows = {name:[] for name in models}, []
    for generator in range(spec["ood_calibration_generators"]):
        world = sample("ood_calibration", generator, 0)
        record = dict(generator=generator, public=public(world), scores={})
        for name, particles in models.items():
            value = infer(world["prefix"], world["observed"], particles).surprise
            scores[name].append(value)
            record["scores"][name] = value
        ood_rows.append(record)
    cutoffs = {name:float(np.quantile(values, .99, method="higher")) for name, values in scores.items()}
    write(output / "OOD_CUTOFFS.json", cutoffs)
    ood_archive = archive(output, "OOD_CALIBRATION_RAW", ood_rows)
    grid = {name:{str(t):dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0)
                  for t in spec["thresholds"]} for name in models}
    chunks, rows = [], []
    for generator in range(spec["risk_calibration_generators"]):
        world = sample("risk_calibration", generator, 0)
        predicted = predictions(world, models, cutoffs, {name:spec["thresholds"] for name in models})
        rows.append(dict(generator=generator, public=public(world), target=world["target"], price=world["price"], predictions=predicted))
        for name, thresholds in predicted.items():
            for threshold, value in thresholds.items():
                entry = grid[name][threshold]
                entry["invalid"] += value["invalid"]
                if not value["invalid"]:
                    entry["accepted"] += value["accepted"]
                    entry["errors"] += value["accepted"] and not value["correct"]
                    entry["fractional"] += value["accepted"] and value["fractional"]
                    entry["fractional_errors"] += value["accepted"] and value["fractional"] and not value["correct"]
        if len(rows) == 64 or generator + 1 == spec["risk_calibration_generators"]:
            chunks.append(archive(output, f"risk_{len(chunks):03d}", rows))
            rows = []
    delta = spec["family_error_probability"] / (len(models) * len(spec["thresholds"]) * 2)
    selected = {}
    for name, thresholds in grid.items():
        passing = []
        for threshold, entry in thresholds.items():
            entry["upper_error"] = upper(entry["errors"], entry["accepted"], delta)
            entry["upper_fractional_error"] = upper(entry["fractional_errors"], entry["fractional"], delta)
            entry["passed"] = bool(not entry["invalid"] and entry["upper_error"] <= spec["risk_limit"]
                                   and entry["upper_fractional_error"] <= spec["risk_limit"]
                                   and entry["fractional"] >= spec["minimum_fractional_calibration_answers"])
            if entry["passed"]:
                passing.append((entry["fractional"], -float(threshold), float(threshold)))
        selected[name] = dict(calibration_gate_passed=bool(passing),
                              threshold=max(passing)[2] if passing else 1 - 1e-12)
    write(output / "CALIBRATION.json", dict(grid=grid, selected=selected, simultaneous_delta=delta,
                                           units="One world/query for each of2048independent new generators"))
    write(output / "ARCHIVES.json", dict(training=training_archive, ood=ood_archive, risk=chunks))
    write(ROOT / "POSTCALIBRATION_FREEZE.json", dict(
        schema="hcsn.r18.postcalibration.freeze.v1", confirmation_opened=False,
        source_freeze_sha256=digest(ROOT / "SOURCE_FREEZE.json"),
        files={str((output / name).relative_to(ROOT)):digest(output / name)
               for name in ("MODELS.json", "OOD_CUTOFFS.json", "CALIBRATION.json", "ARCHIVES.json")},
        selected=selected))
    print(json.dumps(dict(postcalibration_sha256=digest(ROOT / "POSTCALIBRATION_FREEZE.json"), selected=selected)))


def confirm():
    spec = frozen()
    freeze = json.loads((ROOT / "POSTCALIBRATION_FREEZE.json").read_text())
    publication = json.loads((ROOT / "CALIBRATION_PUBLICATION.json").read_text())
    if (publication.get("postcalibration_freeze_sha256") != digest(ROOT / "POSTCALIBRATION_FREEZE.json")
            or publication.get("readback_verified") is not True):
        raise ValueError("Calibration was not published before confirmation")
    for name, sha in freeze["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("Fitted model or control threshold changed")
    calibration = ROOT / "calibration_01"
    models = json.loads((calibration / "MODELS.json").read_text())
    cutoffs = json.loads((calibration / "OOD_CUTOFFS.json").read_text())
    thresholds = {name:[entry["threshold"]] for name, entry in freeze["selected"].items()}
    output = ROOT / "confirmation_01"
    output.mkdir(exist_ok=False)
    archives, rows = [], []
    for split, generators, worlds in (("confirm", spec["confirm_generators"], spec["confirm_worlds_per_generator"]),
                                     ("rotor", spec["rotor_generators"], 4), ("vocabulary", spec["vocabulary_generators"], 2)):
        for generator in range(generators):
            for index in range(worlds):
                world = sample(split, generator, index)
                rows.append(dict(split=split, generator=generator, index=index, public=public(world),
                                 target=world["target"], price=world["price"],
                                 predictions=predictions(world, models, cutoffs, thresholds)))
                if len(rows) == 64:
                    archives.append(archive(output, f"worlds_{len(archives):03d}", rows))
                    rows = []
    if rows:
        archives.append(archive(output, f"worlds_{len(archives):03d}", rows))
    write(output / "ARCHIVES.json", archives)
    from .statistics import summarize
    write(output / "SUMMARY.json", summarize(archives, spec, freeze["selected"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "confirm"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        (prepare if args.stage == "prepare" else confirm)()
        return
    start = time.perf_counter()
    process = subprocess.Popen([sys.executable, "-m", __spec__.name, args.stage, "--child"])
    _, status, usage = os.wait4(process.pid, 0)
    process.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(stage=args.stage, exit_code=process.returncode, child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                   wall_seconds=time.perf_counter() - start, max_rss_kib=usage.ru_maxrss,
                   scope="Full child interpreter/import/all attempts/all candidates/output; development/audits separate")
    write(ROOT / (args.stage.upper() + "_PROCESS_RECEIPT.json"), receipt)
    print(json.dumps(receipt))
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
