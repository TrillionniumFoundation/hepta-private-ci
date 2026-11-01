"""Registered bounded checks and complete child-process CPU accounting."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .posterior import Profile, encode, infer
from .world import sample

ROOT = Path(__file__).parent


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def audit():
    from .audit import grouped_cases
    checks, largest, groups = 0, 0., 0
    for generator in ("without_replacement", "with_replacement"):
        for mask in ((True, False, False, True, True), (False, True, False, True, False)):
            for case in grouped_cases(generator, mask):
                prefix = np.zeros((5, 24), dtype=np.int8)
                for index, event in enumerate(case["prefix"]):
                    if event is not None:
                        prefix[index] = encode(*event)
                result = infer(prefix, np.array(mask), generator, Profile(2, 3, 1))
                errors = [float(np.max(abs(result.marginals() - case["marginals"]))), abs(result.evidence - case["evidence"])]
                for index in result.missing:
                    events = sorted(set(events[index] for events, _ in case["rows"]))
                    expected_gain = -np.max(case["marginals"], axis=1).mean()
                    for event in events:
                        subset = [final for full, final in case["rows"] if full[index] == event]
                        expected = np.eye(3)[np.asarray(subset)].mean(0)
                        acquired = result.acquire(index, encode(*event))
                        errors.append(float(np.max(abs(acquired.marginals() - expected))))
                        if acquired.acquire(index, encode(*event)) is not acquired:
                            raise AssertionError("Identical READ replay must be idempotent")
                        conflicting = (event[0], event[1], (event[2] + 1) % 3)
                        try:
                            acquired.acquire(index, encode(*conflicting))
                        except ValueError:
                            checks += 1
                        else:
                            raise AssertionError("Conflicting acquired token replay was accepted")
                        expected_gain += len(subset) / len(case["rows"]) * expected.max(1).mean()
                        checks += 1
                    errors.append(abs(result.gain(index) - expected_gain))
                largest = max(largest, *errors)
                checks += len(errors)
                groups += 1
    if largest > 2e-12:
        raise AssertionError(f"Independent exact reference error {largest}")
    # Explicit nonidentifiability witness: same observed all-zero prefix under
    # two point-mass generators can give disjoint final values. No unique
    # arbitrary-unknown-generator posterior exists.
    witness_prefix = [encode(0, i, 2 + i).tolist() for i in range(3)] + [[0] * 24]
    witness_prefix += [encode(2, 0, 7).tolist()] * 3 + [[0] * 24]
    witness = dict(observed=witness_prefix, mask=[True, True, True, False, True, True, True, False],
                   target_world_a=[2, 3, 4, 0], target_world_b=[2, 3, 4, 1],
                   conclusion="Arbitrary unknown generator is not identifiable from the raw prefix; finite-model robust probabilities do not certify unseen generators")
    return dict(groups=groups, checks=checks, maximum_absolute_error=largest,
                criterion_passed=True, nonidentifiability_witness=witness)


def supported_models(prefix, mask, profile, names):
    result, rejected = {}, []
    for name in names:
        try:
            result[name] = infer(prefix, mask, name, profile)
        except ValueError as error:
            rejected.append(dict(model=name, error=str(error)))
    return result, rejected


def choose_read(models, price):
    if not models:
        return None
    indices = next(iter(models.values())).missing
    gains = [min(model.gain(index) for model in models.values()) for index in indices]
    best = int(np.argmax(gains))
    return int(indices[best]) if gains[best] > price else None


def metrics(probability, target, accepted):
    probability, target = np.asarray(probability), np.asarray(target)
    return dict(correct=(probability.argmax(1) == target).astype(int).tolist(),
                accepted=np.asarray(accepted, dtype=bool).tolist(),
                squared_error=float(np.mean(np.sum((probability - np.eye(8)[target]) ** 2, axis=1))),
                target_probability=probability[np.arange(4), target].tolist())


def one_policy(name, models, rejected, world, price):
    if not models:
        return dict(policy=name, invalid=True, rejections=rejected, read_index=None)
    index = choose_read(models, price)
    before = {key: value.marginals().tolist() for key, value in models.items()}
    if index is not None:
        acquired = {}
        for key, value in models.items():
            try:
                acquired[key] = value.acquire(index, world["owner_events"][index])
            except ValueError as error:
                rejected = rejected + [dict(model=key, stage="actual_READ", error=str(error))]
        models = acquired
        if not models:
            return dict(policy=name, invalid=True, rejections=rejected, read_index=index)
    predictions = np.stack([model.marginals() for model in models.values()])
    p = predictions.mean(0)
    accepted = np.ones(4, dtype=bool)
    if name == "unknown_finite_set":
        winner = p.argmax(1)
        accepted = np.all(predictions.argmax(2) == winner[None, :], axis=0)
        accepted &= np.min(predictions[:, np.arange(4), winner], axis=0) >= .8
    stats = metrics(p, world["target"], accepted)
    correct = np.asarray(stats["correct"])
    fee = price if index is not None else 0.
    return dict(policy=name, invalid=False, rejections=rejected, read_index=index,
                actual_read_token=world["owner_events"][index].tolist() if index is not None else None,
                probabilities=p.tolist(), before_models=before, model_count=len(models),
                fee=fee, utility=float(correct.mean() - fee),
                abstention_utility=float(np.mean(np.where(accepted, 2 * correct - 1, 0)) - fee), **stats)


def worker(output):
    protocol = json.loads((ROOT / "protocol.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen source mismatch: {name}")
    publication_path = ROOT / "SOURCE_PUBLICATION.json"
    publication = json.loads(publication_path.read_text()) if publication_path.exists() else None
    output.mkdir(exist_ok=False)
    cpu, wall, rows, failures = time.process_time(), time.perf_counter(), [], []
    for generator_index, generator in enumerate(protocol["profiles"]):
        for task_index, task in enumerate(protocol["tasks"]):
            for missing in protocol["missing_counts"]:
                rng = np.random.default_rng(np.random.SeedSequence([protocol["seed"], generator_index, task_index, missing]))
                for episode in range(protocol["episodes_per_cell"]):
                    world = sample(rng, generator, task, missing)
                    profile = Profile(overwrites=2 if task == "selective" else 0)
                    price = float(protocol["prices"][episode % 4])
                    start = time.process_time()
                    true, rejected = supported_models(world["prefix"], world["observed"], profile, [generator])
                    wrong, rejected_wrong = supported_models(world["prefix"], world["observed"], profile, ["without_replacement"])
                    uncertain, rejected_uncertain = supported_models(world["prefix"], world["observed"], profile, protocol["profiles"])
                    policies = [one_policy("known_exact", true, rejected, world, price),
                                one_policy("fixed_without_replacement", wrong, rejected_wrong, world, price),
                                one_policy("unknown_finite_set", uncertain, rejected_uncertain, world, price)]
                    exact = policies[0]
                    pre = next(iter(true.values())).marginals()
                    if (exact["invalid"] or np.any(pre[np.arange(4), world["target"]] <= 0)
                            or min(exact["target_probability"]) <= 0):
                        failures.append(dict(generator=generator, task=task, missing=missing, episode=episode, policies=policies))
                    rows.append(dict(generator=generator, task=task, missing_count=missing, episode=episode,
                                     raw_prefix=world["prefix"].tolist(), observed=world["observed"].tolist(),
                                     target=world["target"].tolist(), public_aliases=world["aliases"].tolist(),
                                     price=price, policies=policies, cpu_seconds=time.process_time() - start))
    write_new(output / "RAW.json", rows)
    summaries = []
    for generator in protocol["profiles"]:
        for name in ("known_exact", "fixed_without_replacement", "unknown_finite_set"):
            records = [p for row in rows if row["generator"] == generator for p in row["policies"] if p["policy"] == name]
            valid = [p for p in records if not p["invalid"]]
            answered = sum(sum(p["accepted"]) for p in valid)
            errors = sum(sum(bool(a) and not c for a, c in zip(p["accepted"], p["correct"], strict=True)) for p in valid)
            summaries.append(dict(generator=generator, policy=name, attempts=len(records), invalid=len(records) - len(valid),
                                  valid_mean_accuracy=float(np.mean([np.mean(p["correct"]) for p in valid])) if valid else None,
                                  whole_population_quality=None if len(valid) != len(records) else float(np.mean([np.mean(p["correct"]) for p in valid])),
                                  reads=sum(p["read_index"] is not None for p in records), answered_queries=answered,
                                  accepted_errors=errors, accepted_error_rate=errors / answered if answered else None,
                                  query_coverage=answered / (4 * len(records)),
                                  mean_fee=float(np.mean([p["fee"] for p in valid])) if valid else None,
                                  mean_net_accuracy=float(np.mean([p["utility"] for p in valid])) if len(valid) == len(records) else None,
                                  mean_brier=float(np.mean([p["squared_error"] for p in valid])) if valid else None,
                                  mean_confidence=float(np.mean([np.max(p["probabilities"], axis=1).mean() for p in valid])) if valid else None))
    summary = dict(schema=protocol["schema"], source_freeze=freeze, source_publication=publication,
                   role="bounded_new_world_verification" if publication else "development_verification",
                   episodes=len(rows), known_support_failures=len(failures), failures=failures,
                   summaries=summaries, measured_loop_cpu_seconds=time.process_time() - cpu,
                   measured_loop_wall_seconds=time.perf_counter() - wall,
                   criteria_passed=len(failures) == 0,
                   limits=["Complete symbolic alias map is supplied; binding is an index permutation, not natural multimodal binding",
                           "Uniform independent mask mechanism differs from previous informative-WRITE-only erasure",
                           "Robust acceptance is limited to the explicitly declared two-generator set",
                           "No analytical-cell mechanism or learned network is used; core independent contribution remains open"])
    write_new(output / "SUMMARY.json", summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.audit:
        started = time.process_time()
        result = audit()
        result["cpu_seconds"] = time.process_time() - started
        write_new(args.audit, result)
        print(json.dumps({key: value for key, value in result.items() if key != "nonidentifiability_witness"}))
    elif args.worker:
        worker(args.worker)
    elif args.run:
        wall = time.perf_counter()
        process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", str(args.run)])
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        receipt = dict(exit_code=process.returncode, child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                       wall_seconds=time.perf_counter() - wall, peak_rss_kib=usage.ru_maxrss,
                       scope="Complete child interpreter/import/inference/all candidate attempts/JSON output; parent and development/audit costs separate")
        write_new(ROOT / "PROCESS_RECEIPT.json", receipt)
        print(json.dumps(receipt))
        if process.returncode:
            raise SystemExit(process.returncode)
    else:
        parser.error("Select --audit, --run, or --worker")


if __name__ == "__main__":
    main()
