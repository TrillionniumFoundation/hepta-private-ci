"""Replay saved continuous-task owner laws; imports no task/solver/executor."""

import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t


BASE = Path(__file__).resolve().parent.parent / "continuous_task_r18_20261101"
INITIAL = [(-1.5, 0), (-.25, 0), (.30, 0), (1.2, 0),
           (-1.5, 1), (-.25, 1), (.30, 1), (1.2, 1)]


def read(path):
    return json.loads(path.read_text())


def uniform(seed, time, channel):
    raw = hashlib.sha256(f"r18-owner:{seed}:{time}:{channel}".encode()).digest()
    return [(int.from_bytes(raw[j:j + 8], "big") + .5) / 2 ** 64 for j in (0, 8)]


def replay(row, dt):
    x, mode = row["initial"]
    elapsed, remaining, fee = 0, round(1.2 / dt), 0.
    resets = []
    lag = round(.2 / dt)
    assert row["actions"][-1] == "S" and "S" not in row["actions"][:-1]
    for action in row["actions"][:-1]:
        assert remaining > 0
        if row["policy"] in ("fixed", "fixed_mode"):
            low, high = row["thresholds"] if row["policy"] == "fixed" else row["thresholds"][mode]
            expected = "S" if x >= high or (remaining < lag and x <= low) else (
                "R" if x <= low and remaining >= lag else "W")
            assert expected == action
        if action == "W":
            a, b = uniform(row["seed"], elapsed, 0)
            increment = row["sigma"] * math.sqrt(dt) * math.sqrt(-2 * math.log(a)) * math.cos(2 * math.pi * b)
            folded = (x + increment + 4) % 16
            x = 4 - abs(folded - 8)
            fee += .03 * dt
            elapsed, remaining = elapsed + 1, remaining - 1
        else:
            assert action == "R" and remaining >= lag
            fee += (.035 if mode == 0 else .025) + .02 * .2
            old = mode
            u, _ = uniform(row["seed"], elapsed, 1)
            mode = 0 if u < (.90 if old == 0 else .25) else 1
            resets.append(dict(start=elapsed, before=old, after=mode))
            x = .6
            elapsed, remaining = elapsed + lag, remaining - lag
    assert row["resets"] == resets
    assert row["elapsed_steps"] == elapsed and row["remaining_steps"] == remaining
    assert elapsed + remaining == round(1.2 / dt) and row["final_mode"] == mode
    error = abs(x - row["final_x"])
    assert error < 2e-10
    probability = (.20 if mode == 0 else .10) + (.75 if mode == 0 else .40) / (1 + math.exp(-1.3 * x))
    u, _ = uniform(row["seed"], elapsed, 2)
    assert row["success"] == int(u < probability)
    assert abs(probability - row["success_probability"]) < 1e-11
    assert fee == row["fee"]
    assert abs(row["utility"] - (row["success"] - fee)) < 1e-14
    assert abs(row["propensity_utility"] - (probability - fee)) < 1e-11
    if row["policy"] == "stop_now":
        assert row["actions"] == "S" and elapsed == 0 and fee == 0
    return error, len(resets), row["actions"].count("W")


def audit_run(name, dt, primary):
    folder = BASE / name
    summary = read(folder / "RESULTS.json")
    groups, inputs = {}, {}
    checked, reset_count, waits, maximum_error = 0, 0, 0, 0.
    for item in summary["raw_manifest"]:
        path = folder / item["path"]
        packed = path.read_bytes()
        assert hashlib.sha256(packed).hexdigest() == item["sha256"]
        raw = gzip.decompress(packed)
        assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
        rows = [json.loads(line) for line in raw.splitlines()]
        assert len(rows) == item["rows"]
        inputs[path.name] = item["sha256"]
        for row in rows:
            assert tuple(row["initial"]) == INITIAL[row["world"] % 8]
            error, resets, wait = replay(row, dt)
            maximum_error = max(maximum_error, error)
            reset_count += resets
            waits += wait
            groups.setdefault((row["sigma"], row["arm"]), []).append(row)
            checked += 1
    assert checked == 12288
    comparisons = {}
    for profile in summary["owner"]:
        sigma = profile["sigma"]
        primary_rows = sorted(groups[sigma, primary], key=lambda r: r["world"])
        assert [r["world"] for r in primary_rows] == list(range(1024))
        for arm, delivered in profile["arms"].items():
            rows = sorted(groups[sigma, arm], key=lambda r: r["world"])
            assert [r["seed"] for r in rows] == [r["seed"] for r in primary_rows]
            for metric in ("utility", "propensity_utility", "success", "fee"):
                assert abs(delivered["mean_" + metric] - np.mean([r[metric] for r in rows])) < 1e-14
        for arm, metrics in profile["comparisons"].items():
            rows = sorted(groups[sigma, arm], key=lambda r: r["world"])
            for metric, delivered in metrics.items():
                delta = np.array([a[metric] - b[metric] for a, b in zip(primary_rows, rows, strict=True)])
                mean = float(delta.mean())
                radius = float(t.ppf(.975, 1023) * delta.std(ddof=1) / math.sqrt(1024))
                assert abs(delivered["mean"] - mean) < 1e-14
                assert np.max(abs(np.asarray(delivered["t95"]) - [mean - radius, mean + radius])) < 1e-14
                comparisons[f"{sigma}:{arm}:{metric}"] = dict(mean=mean, t95=[mean-radius, mean+radius])
    return dict(executions=checked, reset_actions=reset_count, wait_actions=waits,
                maximum_replayed_final_state_error=maximum_error, gates=summary["gates"],
                raw_archive_sha256=inputs, paired_intervals=comparisons)


def run():
    initial = audit_run("run_01", .0025, "free_fd")
    followup = audit_run("run_02", .000625, "jump_fd")
    assert sum(not v for v in initial["gates"].values()) == 2
    assert all(followup["gates"].values())
    for file in ("SOURCE_FREEZE.json", "SOURCE_FREEZE_FOLLOWUP.json"):
        for name, sha in read(BASE / file)["files"].items():
            assert hashlib.sha256((BASE / name).read_bytes()).hexdigest() == sha
    return dict(schema="hcsn-r18-continuous-independent-owner-review-v1", all_checks_passed=True,
                scope="Independent sampled-law replay from saved actions and keyed random draws, fees, recovery states and summaries. No task/solver/executor imports.",
                run01=initial, run02=followup,
                source_review=["Delayed reset keeps all remaining time after its registered recovery duration",
                               "Jump solver evolves left limit before admitting new reset obstacle at multiples of rho",
                               "Positive Gaussian-image hat quadrature has nonnegative weights without clipping/renormalization",
                               "Followup preserves the original two numerical gate failures and strengthens the fixed comparator"],
                limits=["Recorded free-policy actions are replayed under owner law; the optimizer is not independently rerun by this auditor",
                        "Numerical gate flags reflect stored finite-grid measurements; not rigorous PDE error bounds",
                        "Policies act only on a decision mesh, not exact continuous first crossings",
                        "Known synthetic task/observed quality does not establish learned semantic content or analytic-core advantage",
                        "Original active-branch derivative checks do not automatically qualify new jump solver gradients"])


if __name__ == "__main__":
    report = run()
    target = BASE / "INDEPENDENT_REVIEW.json"
    with target.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"all_checks_passed": True, "run01_executions": report["run01"]["executions"],
                      "run02_executions": report["run02"]["executions"],
                      "maximum_replayed_final_state_error": max(report["run01"]["maximum_replayed_final_state_error"],
                                                                  report["run02"]["maximum_replayed_final_state_error"])}))
