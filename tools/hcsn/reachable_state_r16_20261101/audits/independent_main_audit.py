"""Independent raw-evidence scoring and statistics audit of the R16 main run.

This script does not import the experiment, its world, planner, or summarizer.
It verifies archived owner paths, observation draws, fees, checkpoint hashes,
complete episode coverage, fit aggregation, and registered numerical statistics.
It does not rerun action optimization or measure deployment performance.
"""

import argparse
import bisect
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import t


BASE = Path(__file__).resolve().parents[1]
REPOSITORY = BASE.parents[2]
WORLD_LAW_ID = "f9bbedf121707d5d78515698c05c2bc5f915f8a8fac78df42e5664f4d842ddf7"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Audit:
    def __init__(self):
        self.numerical_checks = 0
        self.maximum_difference = 0.
        self.queries = self.observations = self.checkpoints = 0

    def close(self, actual, expected, tolerance=2e-11):
        actual, expected = np.asarray(actual, float), np.asarray(expected, float)
        assert actual.shape == expected.shape
        assert np.isfinite(actual).all() and np.isfinite(expected).all()
        delta = float(np.max(abs(actual - expected), initial=0))
        self.numerical_checks += actual.size
        self.maximum_difference = max(self.maximum_difference, delta)
        assert delta <= tolerance, (delta, tolerance)

    def episode(self, record, result, expected_index):
        assert record["index"] == expected_index
        world = record["world"]
        seed = 16 * 10**12 + result["seed"] * 10**5
        seed += (10000 if result["domain"] == "ood" else 0) + expected_index
        assert world["seed"] == seed and world["domain"] == result["domain"]
        assert len(world["paths"]) == 4 and len(world["query_keys"]) == 6
        metadata = dict(schema="hcsn-r15-world-tape-v1", law=WORLD_LAW_ID,
                        seed=seed, domain=world["domain"], initial_values=world["initial_values"],
                        query_keys=world["query_keys"], dts=world["dts"], deadlines=world["deadlines"],
                        events=world["public_events"],
                        paths=[(p["times"], p["states"]) for p in world["paths"]])
        assert hashlib.sha256(canonical(metadata)).hexdigest() == world["fingerprint"]
        starts = [0.] + world["deadlines"][:-1]
        self.close(np.cumsum(3 * np.array(world["dts"])), world["deadlines"])
        assert set(record["arms"]) == set(result["arms"])
        expected_order = np.random.default_rng(seed).permutation([
            "A", "B", "C", "D", "hmm_same_matrix", "factorized", "block2", "block4", "block5"])
        assert record["actor_order"] == expected_order.tolist()
        for name, row in record["arms"].items():
            spec = result["arms"][name]
            assert row["world"] == world["fingerprint"] and row["seed"] == seed
            assert row["policy"] == spec["policy"] and row["projection"] == spec["projection"]
            assert row["pattern"] == spec["pattern"] and len(row["queries"]) == 6
            correctness, fees, utilities = [], [], []
            action_counts = {"READ": 0, "REFRESH": 0, "WAIT": 0}
            for query_index, query in enumerate(row["queries"]):
                self.queries += 1
                key, dt = world["query_keys"][query_index], world["dts"][query_index]
                assert query["key"] == key and query["query"] == query_index
                assert query["events"] == world["public_events"][query_index]
                path = world["paths"][key]
                target_index = max(0, bisect.bisect_left(path["times"], world["deadlines"][query_index]) - 1)
                target = path["states"][target_index] % 4
                assert query["target"] == target
                correct = int(query["answer"] == target)
                assert query["reward"] == correct
                scale = (.5, 1., 2., 4.)[hashlib.sha256(f"r15-price:{seed}:{query_index}".encode()).digest()[0] % 4]
                self.close(query["price_scale"], scale)
                fee, completed = 0., 0
                for action in query["actions"]:
                    kind = action["action"]
                    assert kind in action_counts
                    action_counts[kind] += 1
                    completed += 2 if kind == "REFRESH" else 1
                    assert action["step"] == completed and completed <= 3
                    elapsed = (2 if kind == "REFRESH" else 1) * dt
                    fee += .003 * elapsed
                    expected_time = (world["deadlines"][query_index] if completed == 3 else
                                     starts[query_index] + completed * dt)
                    self.close(action["time"], expected_time)
                    if kind == "WAIT":
                        assert action["token"] is None
                    else:
                        fee += (.025 if kind == "READ" else .07) * scale
                        locate = bisect.bisect_left if completed == 3 else bisect.bisect_right
                        index = max(0, locate(path["times"], expected_time) - 1)
                        state = path["states"][index]
                        probabilities = np.zeros(5 if kind == "READ" else 4)
                        if kind == "READ" and state // 4 >= 8:
                            probabilities[4] = 1.
                        else:
                            probabilities[:4] = .10 if kind == "READ" else .01
                            probabilities[state % 4] = .70 if kind == "READ" else .97
                        parts = ("r15-emission", seed, world["domain"], key,
                                 float(expected_time).hex(), kind.lower(), query_index, completed)
                        noise = int.from_bytes(hashlib.blake2b(
                            json.dumps(parts, separators=(",", ":"), allow_nan=False).encode(),
                            digest_size=16).digest(), "big")
                        uniform = min(float(((noise >> 64) + .5) / 2**64), np.nextafter(1., 0.))
                        token = bisect.bisect_right(list(itertools.accumulate(probabilities)), uniform)
                        assert action["token"] == token
                        self.observations += 1
                self.close(query["submitted_after"], completed * dt)
                self.close(query["fee"], fee)
                self.close(query["utility"], correct - fee)
                correctness.append(correct)
                fees.append(fee)
                utilities.append(correct - fee)
            self.close(row["reward"], np.mean(correctness))
            self.close(row["fee"], np.mean(fees))
            self.close(row["utility"], np.mean(utilities))
            assert row["reads"] == action_counts["READ"]
            assert row["refreshes"] == action_counts["REFRESH"]
            assert row["waits"] == action_counts["WAIT"]
            assert row["all_queries_correct"] == all(correctness)
            assert len(row["states"]) == 6 and row["state_bytes"] == 1280
            for index, saved in enumerate(row["states"]):
                body = dict(saved)
                expected_hash = body.pop("sha256")
                assert hashlib.sha256(canonical(body)).hexdigest() == expected_hash
                assert body["model"] == spec["model_identity"]
                assert body["projection"] == row["projection"]
                beliefs = np.asarray(body["beliefs"])
                assert beliefs.shape == (4, 40) and beliefs.min() >= -1e-13
                self.close(beliefs.sum(1), np.ones(4))
                self.close(body["clock"], starts[index])
                self.checkpoints += 1
            if name.startswith("block"):
                assert row["compressed_state_bytes"] == {"block2": 576, "block4": 832, "block5": 960}[name]
        left, right = dict(record["arms"]["D"]), dict(record["arms"]["hmm_same_matrix"])
        left.pop("cpu_seconds")
        right.pop("cpu_seconds")
        assert left == right


def audit(run, summary_path, output):
    started = time.process_time()
    protocol = json.loads((BASE / "PROTOCOL.json").read_text())
    frozen = json.loads((BASE / "SOURCE_FREEZE.json").read_text())
    for relative, expected in frozen["files"].items():
        assert sha(REPOSITORY / relative) == expected
    report = json.loads(summary_path.read_text())
    check, means, archive_hashes, workers = Audit(), {}, {}, {}
    worlds, source_pairs = 0, set()
    for fit, domain in itertools.product(protocol["fit_seeds"], protocol["domains"]):
        worker = run / f"{fit}_{domain}"
        assert not (worker / "FAILURE.json").exists()
        result = json.loads((worker / "RESULT.json").read_text())
        workers[fit, domain] = result
        assert result["seed"] == fit and result["domain"] == domain and not result["development"]
        assert result["count"] == result["completed"] == 64
        source_pairs.add((result["freeze_commit"], result["source_manifest"]))
        assert len(result["archives"]) == 8
        rows = []
        for entry in result["archives"]:
            path = worker / entry["file"]
            assert sha(path) == entry["sha256"] and path.stat().st_size == entry["bytes"]
            archive_hashes[path.relative_to(run).as_posix()] = entry["sha256"]
            shard = json.loads(gzip.decompress(path.read_bytes()))
            assert len(shard) == 8
            rows.extend(shard)
        assert len(rows) == 64
        for index, row in enumerate(rows):
            check.episode(row, result, index)
        worlds += len(rows)
        means[fit, domain] = {}
        for name, actor in result["arms"].items():
            means[fit, domain][name] = {}
            for singular, plural in (("reward", "rewards"), ("fee", "fees"), ("utility", "utilities")):
                values = [row["arms"][name][singular] for row in rows]
                check.close(actor[plural], values)
                check.close(actor["mean_" + plural], np.mean(values))
                means[fit, domain][name][singular] = float(np.mean(values))
            check.close(actor["online_cpu"], sum(row["arms"][name]["cpu_seconds"] for row in rows))
    assert len(source_pairs) == 1 and worlds == 1024 and len(archive_hashes) == 128
    assert report["source_manifest"] == sha(BASE / "SOURCE_FREEZE.json")
    assert (report["freeze_commit"], report["source_manifest"]) == next(iter(source_pairs))
    assert report["complete_workers"] == 16 and report["fresh_worlds"] == worlds
    assert report["checked_archives"] == 128 and report["same_matrix_identical_worlds"] == worlds
    raw_p, quality_all = {}, True
    for domain in protocol["domains"]:
        values = {name: np.array([means[fit, domain][name]["utility"] for fit in protocol["fit_seeds"]])
                  for name in protocol["arms"]}
        contrasts = {"B-A": values["B"] - values["A"], "D-C": values["D"] - values["C"],
                     "C-A": values["C"] - values["A"], "D-B": values["D"] - values["B"],
                     "interaction": values["D"] - values["C"] - values["B"] + values["A"]}
        contrasts.update({f"D-{name}": values["D"] - values[name]
                          for name in ("factorized", "block2", "block4", "block5")})
        for name, delta in contrasts.items():
            mean = float(sum(delta) / 8)
            se = float(np.sqrt(sum((delta - mean)**2) / 7) / np.sqrt(8))
            low, high = mean - t.ppf(.975, 7) * se, mean + t.ppf(.975, 7) * se
            permuted = [sum((1 if mask & (1 << i) else -1) * delta[i] for i in range(8)) / 8
                        for mask in range(256)]
            p = sum(abs(v) >= abs(mean) - 1e-14 for v in permuted) / 256
            saved = report["paired_contrasts"][domain][name]
            check.close(saved["mean"], mean)
            check.close(saved["per_fit"], delta)
            check.close(saved["confidence_interval_95"], [low, high])
            check.close(saved["two_sided_sign_flip_p"], p)
            if name == "D-B":
                raw_p[domain] = p
                for key in ("mean", "per_fit", "confidence_interval_95", "two_sided_sign_flip_p"):
                    check.close(report["primary"][domain][key], saved[key])
        for mode in ("block2", "block4", "block5"):
            for metric in ("reward", "utility"):
                delta = np.array([means[fit, domain][mode][metric] - means[fit, domain]["D"][metric]
                                  for fit in protocol["fit_seeds"]])
                lower = float(delta.mean() - t.ppf(1 - .05 / 12, 7) * delta.std(ddof=1) / np.sqrt(8))
                plural = "rewards" if metric == "reward" else "utilities"
                saved = report["compression"][mode]["domains"][domain]["quality_guard"][plural]
                check.close(saved["mean"], delta.mean())
                check.close(saved["simultaneous_lower"], lower)
                check.close(saved["per_fit"], delta)
                assert saved["passes"] == (lower > -.01)
                quality_all &= lower > -.01
            measured = report["compression"][mode]["domains"][domain]
            independently_computed = {}
            for actor in (mode, "D"):
                totals = dict(online_cpu=0., full_cpu_at_1000_uses=0.)
                for fit in protocol["fit_seeds"]:
                    r = workers[fit, domain]
                    metadata = r["arms"][actor]
                    totals["online_cpu"] += metadata["online_cpu"]
                    totals["full_cpu_at_1000_uses"] += metadata["preparation_cpu"]
                    totals["full_cpu_at_1000_uses"] += 1000 * (
                        metadata["online_cpu"] + metadata["checkpoint_cpu"]) / r["count"]
                independently_computed[actor] = totals
                for key, value in totals.items():
                    check.close(measured["measured_costs"][actor][key], value)
            ratios = [independently_computed[mode][key] / independently_computed["D"][key]
                      for key in ("online_cpu", "full_cpu_at_1000_uses")]
            for key, value in zip(("online_cpu", "full_cpu_at_1000_uses"), ratios):
                check.close(measured["cost_ratios"][key], value)
            assert measured["passes"] == (all(g["passes"] for g in measured["quality_guard"].values())
                                           and max(ratios) <= .9)
        for name in protocol["arms"]:
            aggregate = report["arm_aggregates"][domain][name]
            for metric in ("utility", "reward"):
                check.close(aggregate[metric], np.mean([means[fit, domain][name][metric]
                                                       for fit in protocol["fit_seeds"]]))
            for field, raw_field in (("online_cpu_seconds", "online_cpu"),
                                     ("checkpoint_cpu_seconds", "checkpoint_cpu")):
                check.close(aggregate[field], sum(workers[fit, domain]["arms"][name][raw_field]
                                                 for fit in protocol["fit_seeds"]))
    previous = 0.
    for rank, domain in enumerate(sorted(raw_p, key=raw_p.get)):
        adjusted = max(previous, min(1., (2 - rank) * raw_p[domain]))
        previous = adjusted
        check.close(report["primary"][domain]["holm_p"], adjusted)
        primary = report["primary"][domain]
        assert primary["passes"] == (primary["mean"] >= .01
                                      and primary["confidence_interval_95"][0] > 0 and adjusted < .05)
    assert report["primary_passes"] == all(p["passes"] for p in report["primary"].values())
    for item in report["compression"].values():
        assert item["passes"] == all(row["passes"] for row in item["domains"].values())
    check.close(report["research_cpu_seconds"], sum(r["process_cpu_seconds"] for r in workers.values()))
    check.close(report["world_generation_cpu_seconds"], sum(r["world_generation_cpu"] for r in workers.values()))
    result = dict(schema="hcsn-r16-independent-main-audit-v1", passed=True,
                  source_publication=list(next(iter(source_pairs))),
                  archive_sha256=archive_hashes, complete_workers=16,
                  worlds=worlds, checked_archives=len(archive_hashes),
                  scored_queries=check.queries, independently_replayed_observations=check.observations,
                  validated_checkpoint_hashes=check.checkpoints, same_matrix_equal_worlds=worlds,
                  numerical_comparisons=check.numerical_checks,
                  maximum_absolute_difference=check.maximum_difference,
                  all_twelve_compression_quality_bounds_pass=bool(quality_all),
                  each_mode_four_quality_bounds_pass={mode: all(
                      guard["passes"] for row in item["domains"].values()
                      for guard in row["quality_guard"].values())
                      for mode, item in report["compression"].items()},
                  source_sha256=sha(Path(__file__)), summary_sha256=sha(summary_path),
                  process_cpu_seconds=time.process_time() - started,
                  scope="No project summarizer/owner/planner imports. Raw scoring, keyed emissions, checkpoint hash/state contracts and fit-level statistical arithmetic checked. This does not re-solve every action, certify global float arithmetic, or certify production crash recovery.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "archive_sha256"}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.run, args.summary, args.output)
