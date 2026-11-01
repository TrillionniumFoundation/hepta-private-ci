"""Independent namespace17 raw scoring, feature, and fit-statistics audit.

No experiment owner, feature provider, or summarizer is imported. The audit
constructs finite-matrix reference features directly from the frozen arrays.
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
from scipy.linalg import expm
from scipy.stats import t


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
KINDS = ("state_confidence", "stop_value", "value_risk", "ordinary_dual")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, summary_path, output):
    started = time.process_time()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    summary = json.loads(summary_path.read_text())
    manifest = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for path, expected in manifest["files"].items():
        assert digest(ROOT / path) == expected
    ncheck, maximum = 0, 0.

    def close(actual, expected, tolerance=3e-11):
        nonlocal ncheck, maximum
        actual, expected = np.asarray(actual, float), np.asarray(expected, float)
        assert actual.shape == expected.shape
        difference = float(np.max(abs(actual - expected), initial=0))
        assert np.isfinite(actual).all() and np.isfinite(expected).all() and difference < tolerance
        ncheck += actual.size
        maximum = max(maximum, difference)

    worker_rows, archives, means = {}, {}, {}
    worlds = queries = observations = feature_rows = 0
    publications = set()
    for fit, domain in itertools.product(protocol["fit_seeds"], protocol["domains"]):
        worker = folder / f"{fit}_{domain}"
        assert not (worker / "FAILURE.json").exists()
        result = json.loads((worker / "RESULT.json").read_text())
        assert result["seed"] == fit and result["domain"] == domain and result["count"] == 64
        assert not result["development"]
        publications.add((result["source_commit"], result["source_manifest_sha256"]))
        training_path = HERE.parents[1] / f"addressed_decision_r15_20261101/run_01/training/{fit}.json.gz"
        assert digest(training_path) == result["training_input_sha256"]
        training = json.loads(gzip.decompress(training_path.read_bytes()))
        payload = training["calibration"]["models"]["hx"]["payload"]
        q, reward = np.asarray(payload["Q"]), np.asarray(payload["reward"])
        killed = q.copy()
        event = np.zeros(40)
        for state in range(4):
            event[state] = q[state, 32 + state]
            killed[state, 32 + state] = 0
        augmented = np.zeros((41, 41))
        augmented[:40, :40], augmented[:40, 40] = killed, event
        matrices, propagators = {}, {}
        sequences = []
        for entry in result["archives"]:
            path = worker / entry["file"]
            assert digest(path) == entry["sha256"] and path.stat().st_size == entry["bytes"]
            archives[path.relative_to(folder).as_posix()] = entry["sha256"]
            chunk = json.loads(gzip.decompress(path.read_bytes()))
            assert len(chunk) == 8
            sequences.extend(chunk)
        assert len(sequences) == 64 and len(result["archives"]) == 8
        for index, record in enumerate(sequences):
            world = record["world"]
            seed = 17 * 10**12 + fit * 10**5 + (10000 if domain == "ood" else 0) + index
            assert record["index"] == index and world["seed"] == seed and world["domain"] == domain
            assert record["order"] == list(np.random.default_rng(seed).permutation(KINDS))
            assert set(record["arms"]) == set(KINDS)
            metadata = dict(schema="hcsn-r15-world-tape-v1",
                            law="f9bbedf121707d5d78515698c05c2bc5f915f8a8fac78df42e5664f4d842ddf7",
                            seed=seed, domain=domain, initial_values=world["initial_values"],
                            query_keys=world["query_keys"], dts=world["dts"], deadlines=world["deadlines"],
                            events=world["public_events"], paths=[(p["times"], p["states"]) for p in world["paths"]])
            assert hashlib.sha256(canonical(metadata)).hexdigest() == world["fingerprint"]
            start_times = [0.] + world["deadlines"][:-1]
            for kind, row in record["arms"].items():
                weight = np.asarray(training["learned"]["models"][kind]["weights"])
                correctness, fees, utility, feature_cpu = [], [], [], 0.
                assert row["world"] == world["fingerprint"] and len(row["queries"]) == 6
                memory = np.zeros((4, 40))
                for key, value in enumerate(world["initial_values"]):
                    memory[key, value::4] = payload["phase_prior"]
                for j, query in enumerate(row["queries"]):
                    key, dt = world["query_keys"][j], world["dts"][j]
                    assert query["query"] == j and query["key"] == key
                    close(query["dt"], dt)
                    close(query["deadline"], world["deadlines"][j])
                    assert query["events"] == world["public_events"][j]
                    for event_row in world["public_events"][j]:
                        if event_row["kind"] == "WRITE":
                            index = event_row["key"]
                            marginal = memory[index].reshape(10, 4).sum(1)
                            memory[index] = 0
                            memory[index, event_row["value"]::4] = marginal
                    for slots in range(4):
                        if slots * dt not in propagators:
                            propagators[slots * dt] = expm(slots * dt * q)
                    saved = dict(query["prefix_checkpoint"])
                    expected = saved.pop("sha256")
                    assert hashlib.sha256(canonical(saved)).hexdigest() == expected
                    assert saved["model"] == payload["identity"] and saved["projection"] == "full"
                    p = np.array(saved["beliefs"])[key]
                    close(saved["beliefs"], memory)
                    close(p.sum(), 1.)
                    assert np.isfinite(p).all() and p.min() >= -1e-13
                    close(saved["clock"], start_times[j])
                    classes = p.reshape(10, 4).sum(0)
                    ordered = np.sort(classes)
                    mean_phase = float(p.reshape(10, 4).sum(1) @ np.arange(10)) / 9
                    scale = (.5, 1., 2., 4.)[hashlib.sha256(f"r15-price:{seed}:{j}".encode()).digest()[0] % 4]
                    row_features = [1., mean_phase, ordered[-1], ordered[-1] - ordered[-2],
                                    3 * dt, .025 * scale, .07 * scale,
                                    -float(np.sum(classes * np.log(np.maximum(classes, 1e-300))))]
                    if dt not in matrices:
                        matrices[dt] = expm(3 * dt * q), expm(3 * dt * augmented)[:40, 40]
                    transition, first_hit = matrices[dt]
                    if kind in ("stop_value", "value_risk"):
                        row_features.append(float(np.max(p @ transition @ reward)))
                    if kind == "value_risk":
                        row_features.append(float(p @ first_hit))
                    elif kind == "ordinary_dual":
                        row_features += [ordered[-1]**2, float(1 / (1 + np.exp(-8 * (mean_phase - .5))))]
                    close(query["features"], row_features)
                    gains = np.asarray(row_features) @ weight
                    close(query["gains"], gains)
                    action = ("STOP", "READ", "REFRESH")[int(np.argmax(np.r_[0., gains]))]
                    assert action == (query["actions"][0]["action"] if query["actions"] else "STOP")
                    assert len(query["actions"]) <= 1
                    fee, slots = 0., 0
                    if action != "STOP":
                        event_row = query["actions"][0]
                        slots = 1 if action == "READ" else 2
                        assert event_row["step"] == slots
                        expected_time = start_times[j] + slots * dt
                        close(event_row["time"], expected_time)
                        path = world["paths"][key]
                        state = path["states"][max(0, bisect.bisect_right(path["times"], expected_time) - 1)]
                        probabilities = np.zeros(5 if action == "READ" else 4)
                        if action == "READ" and state // 4 >= 8:
                            probabilities[4] = 1
                        else:
                            probabilities[:4] = .1 if action == "READ" else .01
                            probabilities[state % 4] = .7 if action == "READ" else .97
                        parts = ("r15-emission", seed, domain, key, float(expected_time).hex(), action.lower(), j, slots)
                        noise = int.from_bytes(hashlib.blake2b(canonical(parts), digest_size=16).digest(), "big")
                        u = min(float(((noise >> 64) + .5) / 2**64), np.nextafter(1., 0.))
                        assert event_row["token"] == bisect.bisect_right(list(itertools.accumulate(probabilities)), u)
                        fee = .003 * slots * dt + (.025 if action == "READ" else .07) * scale
                        memory = memory @ propagators[slots * dt]
                        emission = np.asarray(payload["E_read" if action == "READ" else "E_refresh"])
                        posterior = memory[key] * emission[:, event_row["token"]]
                        assert posterior.sum() > 0
                        memory[key] = posterior / posterior.sum()
                        observations += 1
                    close(query["submitted_after"], slots * dt)
                    expected_answer = int(np.argmax(memory[key] @ propagators[(3 - slots) * dt] @ reward))
                    assert query["answer"] == expected_answer
                    memory = memory @ propagators[(3 - slots) * dt]
                    path = world["paths"][key]
                    target = path["states"][max(0, bisect.bisect_left(path["times"], world["deadlines"][j]) - 1)] % 4
                    assert query["target"] == target
                    correct = int(query["answer"] == target)
                    close(query["reward"], correct)
                    close(query["fee"], fee)
                    close(query["utility"], correct - fee)
                    correctness.append(correct)
                    fees.append(fee)
                    utility.append(correct - fee)
                    feature_cpu += query["feature_cpu_seconds"]
                    queries += 1
                    feature_rows += 1
                close(row["reward"], np.mean(correctness))
                close(row["fee"], np.mean(fees))
                close(row["utility"], np.mean(utility))
                close(row["feature_cpu_seconds"], feature_cpu)
                assert row["operation_counts"]["first_hit_calls"] == (6 if kind == "value_risk" else 0)
                assert row["operation_counts"]["stop_value_calls"] == (6 if kind in ("stop_value", "value_risk") else 0)
            worlds += 1
        means[fit, domain] = {}
        for kind in KINDS:
            arm = result["arms"][kind]
            means[fit, domain][kind] = {}
            for singular, plural in (("utility", "utilities"), ("reward", "rewards"), ("fee", "fees")):
                values = [r["arms"][kind][singular] for r in sequences]
                close(arm[plural], values)
                close(arm["mean_" + singular], np.mean(values))
                means[fit, domain][kind][singular] = float(np.mean(values))
            close(arm["online_cpu_seconds"], sum(r["arms"][kind]["cpu_seconds"] for r in sequences))
            close(arm["feature_cpu_seconds"], sum(r["arms"][kind]["feature_cpu_seconds"] for r in sequences))
            expected_risk = 3 if kind == "value_risk" else 0
            assert result["preparation"][kind]["risk_matrices"] == expected_risk
            assert arm["final_event_cache_entries"] == expected_risk
            for key in ("first_hit_calls", "stop_value_calls"):
                assert arm[key] == sum(row["arms"][kind]["operation_counts"][key] for row in sequences)
        worker_rows[fit, domain] = result
    assert worlds == 1024 and queries == 24576 and len(archives) == 128 and len(publications) == 1
    assert (summary["source_commit"], summary["source_manifest_sha256"]) == next(iter(publications))
    assert summary["source_manifest_sha256"] == digest(HERE / "SOURCE_FREEZE.json")
    tests = {}
    for domain in protocol["domains"]:
        for reference in ("stop_value", "ordinary_dual"):
            delta = np.array([means[fit, domain]["value_risk"]["utility"] - means[fit, domain][reference]["utility"]
                              for fit in protocol["fit_seeds"]])
            mean, radius = float(delta.mean()), float(t.ppf(.975, 7) * delta.std(ddof=1) / np.sqrt(8))
            null = [sum((1 if mask & (1 << j) else -1) * delta[j] for j in range(8)) / 8 for mask in range(256)]
            probability = sum(abs(value) >= abs(mean) - 1e-15 for value in null) / 256
            name = f"{domain}:value_risk-minus-{reference}"
            saved = summary["tests"][name]
            close(saved["mean"], mean)
            close(saved["per_fit"], delta)
            close(saved["t95"], [mean - radius, mean + radius])
            close(saved["exact_two_sided_sign_flip_p"], probability)
            tests[name] = probability
        rows = [worker_rows[fit, domain] for fit in protocol["fit_seeds"]]
        for kind in KINDS:
            for metric in ("utility", "reward", "fee"):
                close(summary["arms"][domain][kind]["mean_" + metric],
                      np.mean([means[fit, domain][kind][metric] for fit in protocol["fit_seeds"]]))
            cold = np.mean([sum(row["preparation"][kind][key] for key in
                                ("law_restore_cpu_seconds", "common_transition_preparation_cpu_seconds", "channel_preparation_cpu_seconds"))
                            + row["shared_input_decode_cpu_seconds"] for row in rows])
            warm = np.mean([row["arms"][kind]["online_cpu_seconds"] / 64 for row in rows])
            costs = summary["current_costs"][domain][kind]
            close(costs["mean_cold_cpu_seconds"], cold)
            close(costs["mean_online_cpu_seconds"], warm)
            close(costs["mean_feature_cpu_per_query"], np.mean([row["arms"][kind]["feature_cpu_seconds"] / 384 for row in rows]))
            for count in (1, 100, 1000, 10000):
                close(costs["reused_current_cpu"][str(count)], cold + count * warm)
    previous = 0.
    for rank, name in enumerate(sorted(tests, key=tests.get)):
        adjusted = max(previous, min(1., (4 - rank) * tests[name]))
        previous = adjusted
        close(summary["tests"][name]["holm_p"], adjusted)
        saved = summary["tests"][name]
        assert saved["gain_gate"] == (saved["mean"] >= .001 and saved["t95"][0] > 0 and adjusted < .05)
    assert summary["gain_gate"] == all(row["gain_gate"] for row in summary["tests"].values())
    result = dict(schema="hcsn-r16-channel-independent-audit-v1", passed=True, raw_sha256=archives,
                  source_publication=list(next(iter(publications))), worlds=worlds, scored_queries=queries,
                  independently_recomputed_feature_rows=feature_rows, replayed_observations=observations,
                  numerical_comparisons=ncheck, maximum_absolute_difference=maximum,
                  no_unused_risk_cache=True, four_holm_tests_verified=True,
                  online_first_hit_calls={kind: sum(row["arms"][kind]["first_hit_calls"]
                                                   for row in worker_rows.values()) for kind in KINDS},
                  gain_gate=summary["gain_gate"], independent_units=8,
                  source_sha256=digest(Path(__file__)), process_cpu_seconds=time.process_time() - started,
                  scope="Raw scores, causal features from frozen arrays, frozen decisions, keyed observations, cold/warm aggregation and fit statistics independently checked. No actor/owner/summarizer imports; no life-cycle, energy or production claim.")
    output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "raw_sha256"}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.run, args.summary, args.output)
