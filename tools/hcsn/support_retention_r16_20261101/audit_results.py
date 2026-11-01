"""Independent raw-path, fee, fit-statistic and resource-ledger audit.

This module imports no experiment executor, planner, world or summarizer.
The saved finite owner export supplies path topology and model identity only.
It does not independently validate the financial kernel or CPU instrumentation.
"""

import argparse
import bisect
import gzip
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import t


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / "addressed_decision_r15_20261101"
ARMS = ("A", "B", "C", "D", "hmm", "free", "factorized", "mean", "block", "anchored")
METRICS = ("utility", "reward", "cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")
PATTERNS = dict(stop=(), read=("READ",), refresh=("REFRESH",), two_read=("READ", "READ"),
               wait_read=("WAIT", "READ"), read_refresh=("READ", "REFRESH"),
               wait_refresh=("WAIT", "REFRESH"), wait_wait_read=("WAIT", "WAIT", "READ"),
               wait_read_read=("WAIT", "READ", "READ"), read_wait_read=("READ", "WAIT", "READ"),
               three_read=("READ", "READ", "READ"), refresh_read=("REFRESH", "READ"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_text())


class Audit:
    def __init__(self):
        self.checks, self.numerical_checks, self.max_error = 0, 0, 0.
        self.failures = []

    def require(self, condition, label):
        self.checks += 1
        if not condition and len(self.failures) < 100:
            self.failures.append(label)

    def close(self, actual, expected, label, tolerance=2e-11):
        self.numerical_checks += 1
        if actual is None or expected is None:
            self.require(actual is expected, label)
        else:
            difference = abs(float(actual) - float(expected))
            self.max_error = max(self.max_error, difference)
            self.require(math.isfinite(difference) and difference <= tolerance, label)


def key_seed(*parts):
    encoded = json.dumps(parts, separators=(",", ":"), allow_nan=False).encode()
    return int.from_bytes(hashlib.blake2b(encoded, digest_size=16).digest(), "big")


def schedule(seed, domain):
    rng = np.random.default_rng(key_seed("r15-schedule", seed, domain))
    values = rng.permutation(4)
    repeats = rng.permutation(4)
    keys = np.r_[rng.permutation(4), repeats[:2]].astype(int)
    durations = rng.choice((.25, .50, .75) if domain == "iid" else (.35, .65, .95), size=6)
    ends = np.cumsum(3 * durations)
    starts = np.r_[0., ends[:-1]]
    events = []
    for query in range(6):
        row, changed_key = [], None
        if query in (2, 4):
            changed_key, value = int(rng.integers(4)), int(rng.integers(4))
            row.append(dict(kind="WRITE", key=changed_key, value=value, time=float(starts[query])))
        choices = [key for key in range(4) if key != int(keys[query]) and key != changed_key]
        row.append(dict(kind="DISTRACTOR", key=int(rng.choice(choices)), value=int(rng.integers(4)),
                        time=float(starts[query])))
        events.append(row)
    return dict(initial_values=values.tolist(), query_keys=keys.tolist(), dts=durations.tolist(),
                deadlines=ends.tolist(), events=events), starts.tolist()


def state_at(path, when, left):
    index = (bisect.bisect_left if left else bisect.bisect_right)(path["times"], when)
    return path["states"][max(0, index - 1)]


def inspect_world(audit, world, domain, owner):
    audit.require(len(world["paths"]) == 4, "exactly four owned address paths")
    metadata, starts = schedule(world["seed"], domain)
    complete = dict(schema="hcsn-r15-world-tape-v1", law=owner["identity"], seed=world["seed"],
                    domain=domain, **metadata,
                    paths=[(path["times"], path["states"]) for path in world["paths"]])
    audit.require(hashlib.sha256(canonical(complete).encode()).hexdigest() == world["fingerprint"], "owner tape fingerprint")
    q = owner["Q"]
    for key, path in enumerate(world["paths"]):
        times, states = path["times"], path["states"]
        audit.require(len(times) == len(states) and times[0] == 0. and times == sorted(times), "path shape/time")
        audit.require(all(0 <= state < 40 for state in states), "finite owner state range")
        audit.require(states[0] % 4 == metadata["initial_values"][key], "initial owner write")
        writes = {event["time"]: event["value"] for events in metadata["events"] for event in events
                  if event["kind"] == "WRITE" and event["key"] == key}
        for index in range(1, len(times)):
            previous, current = states[index - 1], states[index]
            if times[index] in writes:
                audit.require(current == 4 * (previous // 4) + writes[times[index]], "public write preserves phase")
            else:
                audit.require(q[previous][current] > 0., "owner edge belongs to frozen Q")
        for when, value in writes.items():
            audit.require(when in times and state_at(path, when, False) % 4 == value, "public write exists in tape")
    return metadata, starts


def inspect_row(audit, row, world, domain, metadata, starts, arm, pattern):
    audit.require(row["seed"] == world["seed"] and row["world"] == world["fingerprint"], "arm owner identity")
    if row.get("invalid"):
        audit.require("queries" not in row and row["cpu_seconds"] >= 0 and bool(row["error_type"]), "invalid attempt retained")
        return None
    audit.require(len(row["queries"]) == 6, "six executed queries")
    rewards, fees = [], []
    for index, query in enumerate(row["queries"]):
        key, dt, deadline = metadata["query_keys"][index], metadata["dts"][index], metadata["deadlines"][index]
        audit.require(query["query"] == index and query["key"] == key and query["events"] == metadata["events"][index], "causal schedule/events")
        audit.close(query["dt"], dt, "query interval")
        audit.close(query["deadline"], deadline, "fixed deadline")
        scale = (.5, 1., 2., 4.)[hashlib.sha256(f"r15-price:{world['seed']}:{index}".encode()).digest()[0] % 4]
        audit.close(query["price_scale"], scale, "public price")
        completed, fee = 0, 0.
        for action in query["actions"]:
            name = action["action"]
            audit.require(name in ("WAIT", "READ", "REFRESH"), "legal action")
            slots = 2 if name == "REFRESH" else 1
            completed += slots
            audit.require(action["step"] == completed and completed <= 3, "action consumes declared time")
            when = deadline if completed == 3 else starts[index] + completed * dt
            audit.close(action["time"], when, "observation after action", 1e-10)
            fee += .003 * slots * dt
            if name == "WAIT":
                audit.require(action["token"] is None, "WAIT has no observation")
                continue
            quality = name.lower()
            current = state_at(world["paths"][key], when, completed == 3)
            probabilities = [0.] * 5 if quality == "read" else [.01] * 4
            if quality == "read" and current >= 32:
                probabilities[4] = 1.
            elif quality == "read":
                probabilities[:4] = [.1] * 4
                probabilities[current % 4] = .7
            else:
                probabilities[current % 4] = .97
            noise = key_seed("r15-emission", world["seed"], domain, key, float(when).hex(), quality, index, completed)
            uniform = min(float(((noise >> 64) + .5) / 2 ** 64), np.nextafter(1., 0.))
            token = bisect.bisect_right(np.cumsum(probabilities).tolist(), uniform)
            audit.require(action["token"] == token, "owner keyed observation token")
            fee += (.025 if name == "READ" else .07) * scale
        if arm in ("A", "C"):
            expected, slots = [], 0
            for action in PATTERNS[pattern]:
                length = 2 if action == "REFRESH" else 1
                if slots + length > 3:
                    break
                expected.append(action)
                slots += length
            audit.require([x["action"] for x in query["actions"]] == expected, "frozen common fixed controller")
        target = state_at(world["paths"][key], deadline, True) % 4
        reward = int(query["answer"] == target)
        audit.require(0 <= query["answer"] < 4 and query["target"] == target, "pre-WRITE deadline target")
        audit.close(query["reward"], reward, "actual reward")
        audit.close(query["fee"], fee, "all executed action fees")
        audit.close(query["utility"], reward - fee, "query utility")
        audit.close(query["submitted_after"], completed * dt, "causal submission time")
        rewards.append(reward)
        fees.append(fee)
    result = dict(reward=statistics.mean(rewards), fee=statistics.mean(fees),
                  utility=statistics.mean(r - f for r, f in zip(rewards, fees)))
    for key, value in result.items():
        audit.close(row[key], value, "episode " + key)
    for metric in ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds"):
        audit.require(math.isfinite(row[metric]) and row[metric] >= 0, "finite nonnegative measured " + metric)
        result[metric] = row[metric]
    return result


def independent_interval(values, probability=.975):
    mean = statistics.mean(values)
    radius = t.ppf(probability, len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return dict(mean=mean, lower=mean - radius, upper=mean + radius, fits=values)


def independent_signflip(values):
    target, count = abs(statistics.mean(values)), 0
    for mask in range(1 << len(values)):
        total = math.fsum(value if mask & (1 << index) else -value for index, value in enumerate(values))
        count += abs(total / len(values)) >= target - 1e-15
    return count / (1 << len(values))


def audit_statistics(audit, metrics, workers, processes, protocol, summary, invalid):
    domains, seeds = protocol["domains"], protocol["fits"]
    core, compression, costs = {}, {}, {}
    for domain in domains:
        for arm in ARMS:
            actual = summary["arm_means"][domain][arm]
            if arm in invalid:
                audit.require(actual is None, "global invalid cannot have successful-subset means")
            else:
                for metric in METRICS:
                    audit.close(actual[metric], statistics.mean(metrics[seed, domain, arm][metric] for seed in seeds), "all-fit mean")
        core[domain] = {}
        if not set(("A", "B", "C", "D")) & set(invalid):
            for label, left, right in (("B-A", "B", "A"), ("D-C", "D", "C"), ("C-A", "C", "A"), ("D-B", "D", "B")):
                values = [metrics[seed, domain, left]["utility"] - metrics[seed, domain, right]["utility"] for seed in seeds]
                expected = independent_interval(values)
                expected["signflip_p"] = independent_signflip(values)
                core[domain][label] = expected
            values = [(metrics[s, domain, "D"]["utility"] - metrics[s, domain, "C"]["utility"])
                      - (metrics[s, domain, "B"]["utility"] - metrics[s, domain, "A"]["utility"]) for s in seeds]
            core[domain]["interaction"] = independent_interval(values)
        if not set(("anchored", "D")) & set(invalid):
            compression[domain] = {metric: independent_interval([
                metrics[s, domain, "anchored"][metric] - metrics[s, domain, "D"][metric] for s in seeds], .9875)
                for metric in ("utility", "reward")}
            costs[domain] = {}
            for uses in (1, 100, 1000, 10000):
                total = dict(D=0., anchored=0.)
                for seed in seeds:
                    training = read(BASE / "run_01/supervisor" / f"train_{seed}.json")["total_cpu_seconds"]
                    investment = training + sum(processes[seed, d]["cpu_total_seconds"] for d in domains)
                    for arm in total:
                        total[arm] += investment + workers[seed, domain]["arms"][arm]["preparation_cpu_seconds"] + uses * metrics[seed, domain, arm]["cpu_seconds"]
                costs[domain][str(uses)] = dict(cpu_seconds=total, ratio=total["anchored"] / total["D"])
            costs[domain]["online_ratio"] = sum(metrics[s, domain, "anchored"]["cpu_seconds"] for s in seeds) / sum(metrics[s, domain, "D"]["cpu_seconds"] for s in seeds)
    ordered = sorted([d for d in domains if "D-B" in core[d]], key=lambda d: core[d]["D-B"]["signflip_p"])
    last = 0.
    for rank, domain in enumerate(ordered):
        last = min(1., max(last, (len(ordered) - rank) * core[domain]["D-B"]["signflip_p"]))
        core[domain]["D-B"]["holm_p"] = last

    def compare(actual, expected, label):
        if isinstance(expected, dict):
            audit.require(set(actual) == set(expected), label + " keys")
            for key in expected:
                compare(actual[key], expected[key], label + "/" + key)
        elif isinstance(expected, list):
            audit.require(len(actual) == len(expected), label + " size")
            for a, b in zip(actual, expected):
                audit.close(a, b, label)
        else:
            audit.close(actual, expected, label)

    compare(summary["original_2x2"], {d: c for d, c in core.items() if c}, "core statistic")
    compare(summary["compression_minus_D"], compression, "compression statistic")
    compare(summary["reuse_cost"], costs, "full search reuse cost")
    gain = len(ordered) == 2 and all(core[d]["D-B"]["mean"] >= .01 and core[d]["D-B"]["lower"] > 0 and core[d]["D-B"]["holm_p"] < .05 for d in ordered)
    noninferior = len(compression) == 2 and all(c[m]["lower"] > -.01 for c in compression.values() for m in ("utility", "reward"))
    cost = noninferior and all(c["online_ratio"] <= .9 and c["1000"]["ratio"] <= .9 for c in costs.values())
    return dict(original_core_gain=gain, anchored_quality_noninferiority=noninferior, anchored_quality_guarded_cost=cost)


def run(complete=True):
    audit, started = Audit(), time.process_time()
    protocol, owner = read(HERE / "PROTOCOL.json"), read(HERE / "results/reachable_dependency_reference_audit.json")["law_export"]
    manifest = read(HERE / "SOURCE_MANIFEST.json")
    for name, expected in manifest["files"].items():
        audit.require(sha(ROOT / name) == expected, "frozen source/model hash: " + name)
    publication = read(HERE / "PUBLICATION.json")
    audit.require(publication["manifest_sha256"] == sha(HERE / "SOURCE_MANIFEST.json"), "published manifest")
    workers, metrics, failures, counts, archives = {}, {}, [], Counter(), []
    jobs = [(s, d) for s in protocol["fits"] for d in protocol["domains"]]
    if not complete:
        jobs = [next((s, d) for s, d in jobs if (HERE / "results" / f"summary_{s}_{d}.json").exists())]
    for seed, domain in jobs:
        worker = read(HERE / "results" / f"summary_{seed}_{domain}.json")
        workers[seed, domain] = worker
        training = read(BASE / "run_01/training" / f"{seed}.json.gz")
        audit.require(worker["fixed_pattern"] == training["light_pattern"] and worker["ordinary_selected"] == training["ordinary_selected"], "unchanged frozen selection")
        values, local_failures, seen = {arm: [] for arm in ARMS}, [], set()
        for item in worker["archives"]:
            path = HERE / item["path"]
            audit.require(sha(path) == item["sha256"] and path.stat().st_size == item["bytes"], "raw archive identity")
            raw = read(path)
            audit.require(raw["fit"] == seed and raw["domain"] == domain and set(raw["arms"]) == set(ARMS), "archive scope")
            audit.require(0 < len(raw["worlds"]) <= 32, "nonempty bounded archive")
            audit.require(all(len(raw["arms"][arm]) == len(raw["worlds"]) for arm in ARMS), "exact arm/world row counts")
            archives.append(item)
            for index, world in enumerate(raw["worlds"]):
                audit.require(world["seed"] not in seen, "world not duplicated")
                seen.add(world["seed"])
                meta, starts = inspect_world(audit, world, domain, owner)
                audit.require(raw["arms"]["D"][index].get("queries") == raw["arms"]["hmm"][index].get("queries") and "queries" in raw["arms"]["D"][index], "D/same-Q HMM exact trace")
                for arm in ARMS:
                    row = raw["arms"][arm][index]
                    counts["attempts_" + arm] += 1
                    value = inspect_row(audit, row, world, domain, meta, starts, arm, worker["fixed_pattern"])
                    if value is None:
                        local_failures.append(dict(arm=arm, **row))
                    else:
                        values[arm].append(value)
                        counts["valid_" + arm] += 1
                    counts["successful_queries"] += 6 if value is not None else 0
        expected_seeds = {protocol["confirmation_namespace"] * 10**12 + seed * 10**5 + (10000 if domain == "ood" else 0) + i for i in range(protocol["episodes_per_fit_domain"])}
        audit.require(seen == expected_seeds and len(seen) == worker["episodes"], "complete registered owner namespace")
        audit.require(Counter(map(canonical, worker["failures"])) == Counter(map(canonical, local_failures)), "every invalid attempt retained")
        for arm in ARMS:
            valid = len(values[arm]) == len(seen)
            audit.require(worker["arms"][arm]["valid"] == valid and worker["counts"]["valid"][arm] == len(values[arm]) and worker["counts"]["attempts"][arm] == len(seen), "worker attempt/invalid accounting")
            metrics[seed, domain, arm] = {m: statistics.mean(r[m] for r in values[arm]) if valid else None for m in METRICS}
            for metric, expected in metrics[seed, domain, arm].items():
                audit.close(worker["arms"][arm][metric], expected, "raw-to-worker mean")
            audit.close(worker["arms"][arm]["failure_cpu_seconds"], math.fsum(r["cpu_seconds"] for r in local_failures if r["arm"] == arm), "failed attempt CPU")
        failures.extend(dict(fit=seed, domain=domain, **row) for row in local_failures)
    invalid = [arm for arm in ARMS if any(metrics[s, d, arm]["utility"] is None for s, d in jobs)]
    independent_gates = None
    if complete:
        summary, parent = read(HERE / "results/SUMMARY.json"), read(HERE / "results/PROCESS_SUMMARY.json")
        proc = {(r["fit"], r["domain"]): r for r in parent["processes"]}
        audit.require(set(proc) == set(jobs) and len(proc) == len(parent["processes"]), "all registered child processes")
        audit.require(all(r["exit_code"] == 0 and r["source_verified_after_exit"] for r in proc.values()), "complete verified child success")
        for job, receipt in proc.items():
            audit.close(receipt["cpu_total_seconds"], receipt["cpu_user_seconds"] + receipt["cpu_system_seconds"], "child user+system CPU")
            audit.require(receipt["cpu_total_seconds"] + 1e-5 >= workers[job]["costs"]["worker_internal_cpu_seconds"], "complete process covers internal CPU")
        total = math.fsum(r["cpu_total_seconds"] for r in proc.values())
        audit.close(parent["complete_child_cpu_seconds"], total, "complete all-candidate child cost")
        audit.close(summary["costs"]["complete_confirmation_cpu_seconds"], total, "reported confirmation cost")
        audit.close(summary["costs"]["inherited_training_cpu_seconds"], math.fsum(read(BASE / "run_01/supervisor" / f"train_{s}.json")["total_cpu_seconds"] for s in protocol["fits"]), "full original training process cost")
        audit.require(set(summary["invalid_global"]) == set(invalid), "global two-domain invalid propagation")
        audit.require(Counter(map(canonical, summary["failures"])) == Counter(map(canonical, failures)), "global failures retained")
        for arm in ARMS:
            audit.require(summary["attempts"][arm] == counts["attempts_" + arm] and summary["valid_attempts"][arm] == counts["valid_" + arm], "global attempt counts")
        independent_gates = audit_statistics(audit, metrics, workers, proc, protocol, summary, invalid)
        for name, expected in independent_gates.items():
            audit.require(summary["gates"][name] == expected, "independently reconstructed gate: " + name)
        audit.require(summary["gates"]["same_matrix_hmm"] is True, "same-Q gate matches traces")
    for name, expected in manifest["files"].items():
        audit.require(sha(ROOT / name) == expected, "frozen source/model remains unchanged: " + name)
    audit.require(publication["manifest_sha256"] == sha(HERE / "SOURCE_MANIFEST.json"), "manifest unchanged through audit")
    return dict(schema="hcsn-r16-independent-raw-results-audit-v1", complete_campaign=complete,
                passed=not audit.failures, checks=audit.checks, numerical_checks=audit.numerical_checks,
                maximum_numeric_error=audit.max_error, failures=audit.failures, invalid_global=invalid,
                counts=dict(counts), archive_count=len(archives), archives=archives,
                reconstructed_gates=independent_gates, process_cpu_seconds=time.process_time() - started,
                audit_source_sha256=sha(Path(__file__)), source_manifest_sha256=sha(HERE / "SOURCE_MANIFEST.json"),
                publication=publication["source_commit"],
                evidence_scope="Reconstruct saved finite owner schedules/fingerprints, legal path edges, target and keyed observations; fees, raw summaries, fit inference, invalid propagation and resource accounting. No project executor/planner/world/summarizer import; no independent replay of policy optimization, clock internals or CPU instrumentation.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(not args.partial)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("archives", "evidence_scope")}, indent=2))
