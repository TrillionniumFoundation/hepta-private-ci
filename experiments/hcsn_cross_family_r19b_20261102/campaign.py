"""Public fitting, family-wise risk calibration, then immutable confirmation."""

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

from .masked_fit import fit_candidate
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
    source = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for name, sha in source["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("Source changed after freeze: " + name)
    receipt = json.loads((ROOT / "SOURCE_PUBLICATION.json").read_text())
    if receipt.get("source_freeze_sha256") != digest(ROOT / "SOURCE_FREEZE.json") or receipt.get("readback_verified") is not True:
        raise ValueError("Missing verified source publication")
    return json.loads((ROOT / "protocol.json").read_text())


def archive(directory, name, rows):
    data = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path = directory / (name + ".json.gz")
    with path.open("xb") as stream:
        stream.write(gzip.compress(data, mtime=0))
    return dict(path=str(path.relative_to(ROOT)), records=len(rows), raw_bytes=len(data),
                raw_sha256=hashlib.sha256(data).hexdigest(), compressed_sha256=digest(path))


def public(world):
    return {key:world[key].tolist() for key in ("prefix", "observed", "bridges", "query", "dt")}


def load_candidate():
    lock = json.loads((ROOT / "FITTED_CANDIDATE_FREEZE.json").read_text())
    publication = json.loads((ROOT / "CANDIDATE_PUBLICATION.json").read_text())
    if (lock.get("source_freeze_sha256") != digest(ROOT / "SOURCE_FREEZE.json")
            or publication.get("candidate_freeze_sha256") != digest(ROOT / "FITTED_CANDIDATE_FREEZE.json")
            or publication.get("readback_verified") is not True):
        raise ValueError("Missing verified source-bound fitted candidate")
    for name, sha in lock["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("Fitted candidate changed: " + name)
    folder = ROOT / "candidate_01"
    fitted = json.loads((folder / "MODELS.json").read_text())
    for name, spec in fitted["selected"].items():
        table = np.array(json.loads(gzip.decompress((folder / ("TABLE_" + name + ".json.gz")).read_bytes())))
        spec["runtime_model"] = dict(fitted["shared"], sequence_table=table)
    return fitted


def posteriors(world, fitted):
    main, reference = fitted["selected"]["class_mixture"], fitted["selected"]["best_static"]
    mixture = infer(world["prefix"], world["observed"], main["runtime_model"], main["prior"])
    static = (mixture.reprior(reference["prior"]) if main["beta"] == reference["beta"] else
              infer(world["prefix"], world["observed"], reference["runtime_model"], reference["prior"]))
    return dict(class_mixture=mixture, best_static=static)


def evaluate(world, posterior, key, threshold, guard):
    before = posterior.probability(key)
    admitted = bool(posterior.surprise <= guard["surprise"] and posterior.broad_mass <= guard["broad"] + 1e-12)
    index, _ = posterior.choose(key, world["price"], threshold, guard["broad"]) if admitted else (None, None)
    after = posterior.acquire(index, world["owner_events"][index]) if index is not None else posterior
    p = after.probability(key)
    accepted = bool(admitted and after.broad_mass <= guard["broad"] + 1e-12 and p.max() >= threshold)
    fee = world["price"] if index is not None else 0.
    # No target participates in inference, guard, READ choice or acceptance above.
    target = world["target"]
    correct, before_correct = int(p.argmax() == target), int(before.argmax() == target)
    before_accepted = bool(admitted and before.max() >= threshold)
    return dict(invalid=False, accepted=accepted, admitted=admitted, probability=p.tolist(), before=before.tolist(),
                confidence=float(p.max()), fractional=bool(p.max() < 1 - 1e-9), correct=correct,
                fee=fee, read_index=index, actual_read=world["owner_events"][index].tolist() if index is not None else None,
                payoff=(2 * correct - 1 if accepted else 0) - fee,
                no_read_payoff=(2 * before_correct - 1 if before_accepted else 0),
                before_brier=float(np.sum((before - np.eye(4)[target]) ** 2)),
                after_brier=float(np.sum((p - np.eye(4)[target]) ** 2)),
                before_log_loss=float(-np.log(before[target])) if before[target] > 0 else None,
                after_log_loss=float(-np.log(p[target])) if p[target] > 0 else None,
                true_probability=float(p[target]), surprise=posterior.surprise,
                broad_before=posterior.broad_mass, broad_after=after.broad_mass,
                class_before=posterior.class_masses.sum(0).tolist(), class_after=after.class_masses.sum(0).tolist())


def predictions(world, fitted, guards, thresholds):
    try:
        key = query_key(world["bridges"], world["query"])
        choices = posteriors(world, fitted)
        return {name:{str(t):evaluate(world, choices[name], key, t, guards[name]) for t in values}
                for name, values in thresholds.items()}
    except ValueError as error:
        return {name:{str(t):dict(invalid=True, accepted=False, read_index=None, reason=str(error)) for t in values}
                for name, values in thresholds.items()}


def upper(errors, count, delta):
    return 1. if count == 0 or errors == count else float(beta.ppf(1 - delta, errors + 1, count - errors))


def fit_public():
    spec = frozen()
    output = ROOT / "candidate_01"
    output.mkdir(exist_ok=False)
    groups, fitting, calibration = [], [], []
    for family in spec["trained_families"]:
        groups += [[sample("train", family, generator, index, complete=True)["prefix"]
                    for index in range(spec["train_worlds_per_generator"])]
                   for generator in range(spec["train_generators_per_family"])]
        fitting += [public(sample("public_fit", family, generator, index, complete=True))
                    for generator in range(spec["public_fit_generators_per_family"])
                    for index in range(spec["public_fit_worlds_per_generator"])]
        calibration += [public(sample("public_cal", family, generator, index, complete=True))
                        for generator in range(spec["public_cal_generators_per_family"])
                        for index in range(spec["public_cal_worlds_per_generator"])]
    inputs = dict(training=archive(output, "TRAINING_PUBLIC_RAW", [[x.tolist() for x in group] for group in groups]),
                  fitting=archive(output, "FITTING_PUBLIC_RAW", fitting),
                  calibration=archive(output, "FORECAST_CAL_PUBLIC_RAW", calibration))
    write(output / "PUBLIC_INPUTS.json", inputs)
    fitted, choices, tables = fit_candidate(groups, fitting, calibration)
    write(output / "MODELS.json", fitted)
    write(output / "PUBLIC_OBJECTIVE.json", dict(candidates=choices, selected=fitted["selected"],
        visibility="All targets and READ tokens derived only from complete raw public streams; no owner target or family parameters"))
    for name, table in tables.items():
        inputs["table_" + name] = archive(output, "TABLE_" + name, table.tolist())
    write(output / "ARCHIVES.json", inputs)
    names = ["MODELS.json", "PUBLIC_OBJECTIVE.json", "ARCHIVES.json",
             "TABLE_class_mixture.json.gz", "TABLE_best_static.json.gz"]
    write(ROOT / "FITTED_CANDIDATE_FREEZE.json", dict(schema="hcsn.r19b.candidate.freeze.v1",
        formal_risk_calibration_opened=False, confirmation_opened=False,
        source_freeze_sha256=digest(ROOT / "SOURCE_FREEZE.json"),
        files={str((output / name).relative_to(ROOT)):digest(output / name) for name in names}))
    print(json.dumps(dict(candidate_sha256=digest(ROOT / "FITTED_CANDIDATE_FREEZE.json"), selected=fitted["selected"])))


def calibrate():
    spec = frozen()
    lock = json.loads((ROOT / "FITTED_CANDIDATE_FREEZE.json").read_text())
    publication = json.loads((ROOT / "CANDIDATE_PUBLICATION.json").read_text())
    if publication.get("candidate_freeze_sha256") != digest(ROOT / "FITTED_CANDIDATE_FREEZE.json") or publication.get("readback_verified") is not True:
        raise ValueError("Candidate was not published before fresh fixed-N calibration")
    for name, sha in lock["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("Candidate changed before calibration")
    fitted = load_candidate()
    output = ROOT / "calibration_01"
    output.mkdir(exist_ok=False)
    scores = {name:{family:[] for family in spec["trained_families"]} for name in spec["models"]}
    ood_rows = []
    for family in spec["trained_families"]:
        for generator in range(spec["ood_generators_per_family"]):
            world = sample("ood", family, generator, 0)
            posterior = posteriors(world, fitted)
            values = {name:dict(surprise=p.surprise, broad=p.broad_mass) for name, p in posterior.items()}
            for name, value in values.items():
                scores[name][family].append(value)
            ood_rows.append(dict(family=family, generator=generator, public=public(world), values=values))
    guards = {name:{key:max(float(np.quantile([row[key] for row in values], .99, method="higher"))
                           for values in families.values()) for key in ("surprise", "broad")}
              for name, families in scores.items()}
    write(output / "GUARDS.json", guards)
    ood_archive = archive(output, "OOD_PUBLIC_RAW", ood_rows)
    grid = {name:{str(t):{family:dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0)
                          for family in spec["trained_families"]} for t in spec["thresholds"]} for name in spec["models"]}
    archives, rows = [], []
    for family in spec["trained_families"]:
        for generator in range(spec["risk_generators_per_family"]):
            world = sample("calibration", family, generator, 0)
            result = predictions(world, fitted, guards, {name:spec["thresholds"] for name in spec["models"]})
            rows.append(dict(family=family, generator=generator, public=public(world), target=world["target"],
                             price=world["price"], predictions=result))
            for name, thresholds in result.items():
                for threshold, value in thresholds.items():
                    entry = grid[name][threshold][family]
                    entry["invalid"] += value["invalid"]
                    if not value["invalid"]:
                        entry["accepted"] += value["accepted"]
                        entry["errors"] += value["accepted"] and not value["correct"]
                        entry["fractional"] += value["accepted"] and value["fractional"]
                        entry["fractional_errors"] += value["accepted"] and value["fractional"] and not value["correct"]
            if len(rows) == 64:
                archives.append(archive(output, f"risk_{len(archives):03d}", rows))
                rows = []
    if rows:
        archives.append(archive(output, f"risk_{len(archives):03d}", rows))
    delta = spec["calibration_family_error"] / (len(spec["models"]) * len(spec["thresholds"]) * len(spec["trained_families"]) * 2)
    selected = {}
    for name, thresholds in grid.items():
        passing = []
        for threshold, families in thresholds.items():
            for entry in families.values():
                entry["upper_error"] = upper(entry["errors"], entry["accepted"], delta)
                entry["upper_fractional_error"] = upper(entry["fractional_errors"], entry["fractional"], delta)
                entry["passed"] = bool(not entry["invalid"] and entry["upper_error"] <= spec["risk_limit"]
                    and entry["upper_fractional_error"] <= spec["risk_limit"]
                    and entry["fractional"] >= spec["minimum_fractional_calibration"])
            if all(entry["passed"] for entry in families.values()):
                passing.append((min(entry["fractional"] for entry in families.values()),
                                sum(entry["fractional"] for entry in families.values()), -float(threshold), float(threshold)))
        selected[name] = dict(calibration_gate_passed=bool(passing), threshold=max(passing)[3] if passing else 1 - 1e-12)
    write(output / "CALIBRATION.json", dict(grid=grid, selected=selected, simultaneous_delta=delta,
        role="Family labels used only offline to require EACH trained family; runtime model is family-blind"))
    write(output / "ARCHIVES.json", dict(ood=ood_archive, risk=archives))
    write(ROOT / "POSTCALIBRATION_FREEZE.json", dict(schema="hcsn.r19b.postcalibration.v1", confirmation_opened=False,
        source_freeze_sha256=digest(ROOT / "SOURCE_FREEZE.json"),
        candidate_freeze_sha256=digest(ROOT / "FITTED_CANDIDATE_FREEZE.json"), selected=selected,
        files={str((output / name).relative_to(ROOT)):digest(output / name)
               for name in ("GUARDS.json", "CALIBRATION.json", "ARCHIVES.json")}))
    print(json.dumps(dict(postcalibration_sha256=digest(ROOT / "POSTCALIBRATION_FREEZE.json"), selected=selected)))


def confirm():
    spec = frozen()
    lock = json.loads((ROOT / "POSTCALIBRATION_FREEZE.json").read_text())
    if set(lock.get("selected", {})) != set(spec["models"]) or any(
            entry.get("calibration_gate_passed") is not True for entry in lock["selected"].values()):
        raise ValueError("Calibration gate failed: confirmation worlds must remain unopened")
    receipt = json.loads((ROOT / "CALIBRATION_PUBLICATION.json").read_text())
    if receipt.get("postcalibration_freeze_sha256") != digest(ROOT / "POSTCALIBRATION_FREEZE.json") or receipt.get("readback_verified") is not True:
        raise ValueError("Missing verified calibration publication")
    if lock.get("candidate_freeze_sha256") != digest(ROOT / "FITTED_CANDIDATE_FREEZE.json"):
        raise ValueError("Calibration is not bound to this fitted candidate")
    for name, sha in lock["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("Fitted source changed: " + name)
    fitted = load_candidate()
    guards = json.loads((ROOT / "calibration_01/GUARDS.json").read_text())
    thresholds = {name:[entry["threshold"]] for name, entry in lock["selected"].items()}
    output = ROOT / "confirmation_01"
    output.mkdir(exist_ok=False)
    archives, rows = [], []
    for family in spec["all_families"]:
        for generator in range(spec["confirm_generators_per_family"]):
            for index in range(spec["confirm_worlds_per_generator"]):
                world = sample("confirm", family, generator, index)
                rows.append(dict(family=family, generator=generator, index=index, public=public(world),
                                 target=world["target"], price=world["price"],
                                 predictions=predictions(world, fitted, guards, thresholds)))
                if len(rows) == 64:
                    archives.append(archive(output, f"worlds_{len(archives):03d}", rows))
                    rows = []
    if rows:
        archives.append(archive(output, f"worlds_{len(archives):03d}", rows))
    write(output / "ARCHIVES.json", archives)
    from .statistics import summarize
    write(output / "SUMMARY.json", summarize(archives, spec, lock["selected"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("fit", "calibrate", "confirm"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        {"fit":fit_public, "calibrate":calibrate, "confirm":confirm}[args.stage]()
        return
    start = time.perf_counter()
    with (ROOT / (args.stage.upper() + ".stdout.log")).open("x") as stdout, (ROOT / (args.stage.upper() + ".stderr.log")).open("x") as stderr:
        process = subprocess.Popen([sys.executable, "-m", __spec__.name, args.stage, "--child"], stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(stage=args.stage, exit_code=process.returncode,
        child_cpu_seconds=usage.ru_utime + usage.ru_stime,
        wall_seconds=time.perf_counter() - start, max_rss_kib=usage.ru_maxrss,
        scope="Whole child interpreter/import/fitting/all candidates/failed attempts/output; development/audits separate")
    write(ROOT / (args.stage.upper() + "_PROCESS_RECEIPT.json"), receipt)
    print(json.dumps(receipt))
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
