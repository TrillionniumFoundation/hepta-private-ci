"""Independent raw owner/scoring, equivalence and statistics audit of fast runs.

Does not import the campaign, compression implementations or project summarizer.
"""

import bisect
import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.stats import t


HERE = Path(__file__).parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def state_at(world, key, at, left=False):
    path = world["paths"][key]
    index = (bisect.bisect_left if left else bisect.bisect_right)(path["times"], at) - 1
    return path["states"][max(0, index)]


def observation(world, query, key, step, quality):
    starts = [0.] + world["deadlines"][:-1]
    at = world["deadlines"][query] if step == 3 else starts[query] + step * world["dts"][query]
    hidden = state_at(world, key, at, left=step == 3)
    if quality == "read":
        probabilities = ([.1] * 4 + [0.]) if hidden // 4 < 8 else [0., 0., 0., 0., 1.]
        if hidden // 4 < 8:
            probabilities[hidden % 4] = .7
    else:
        probabilities = [.01] * 4
        probabilities[hidden % 4] = .97
    parts = ("r15-emission", world["seed"], world["domain"], key, float(at).hex(), quality, query, step)
    digest = hashlib.blake2b(json.dumps(parts, separators=(",", ":")).encode(), digest_size=16).digest()
    integer = int.from_bytes(digest, "big")
    uniform = min(((integer >> 64) + .5) / 2**64, np.nextafter(1., 0.))
    return int(np.searchsorted(np.cumsum(probabilities), uniform, side="right"))


def run():
    started = time.process_time()
    root = HERE / "fast_run_01"
    expected = json.loads((root / "SUMMARY.json").read_text())
    protocol = json.loads((HERE / "FAST_PROTOCOL.json").read_text())
    comparisons, maximum, belief_error, observed, count = 0, 0., 0., 0, 0
    hashes, records, seen = {}, [], set()

    def near(actual, reference):
        nonlocal comparisons, maximum
        error = abs(float(actual) - float(reference))
        comparisons += 1
        maximum = max(maximum, error)
        if error > 2e-12:
            raise AssertionError((actual, reference, error))

    for fit in protocol["fit_seeds"]:
        for domain in protocol["domains"]:
            directory = root / f"{fit}_{domain}"
            record = json.loads((directory / "RESULT.json").read_text())
            assert (record["fit"], record["domain"], record["completed"]) == (fit, domain, 32)
            metric = {name: dict(utilities=[], rewards=[], online_cpu=0.) for name in protocol["arms"]}
            worker_worlds = 0
            for archive in record["archives"]:
                raw = (directory / archive["file"]).read_bytes()
                hashed = hashlib.sha256(raw).hexdigest()
                assert hashed == archive["sha256"] and len(raw) == archive["bytes"]
                hashes[f"{fit}_{domain}/{archive['file']}"] = hashed
                for item in json.loads(gzip.decompress(raw)):
                    world = item["world"]
                    assert world["seed"] == 18 * 10**12 + fit * 10**5 + (10000 if domain == "ood" else 0) + item["index"]
                    assert world["seed"] not in seen and sorted(item["actor_order"]) == sorted(protocol["arms"])
                    seen.add(world["seed"])
                    count += 1
                    worker_worlds += 1
                    old, fast = item["arms"]["old_block2"], item["arms"]["fast_block2"]
                    clean = lambda rows: [{k: v for k, v in row.items() if k != "checkpoint_sha256"} for row in rows]
                    assert clean(old["queries"]) == clean(fast["queries"])
                    for left, right in zip(old["states"], fast["states"], strict=True):
                        error = float(np.max(np.abs(np.array(left["beliefs"]) - np.array(right["beliefs"]))))
                        belief_error = max(belief_error, error)
                        assert error < 2e-11
                        for key in ("clock", "operations", "model", "projection", "method"):
                            assert left[key] == right[key]
                    for name, arm in item["arms"].items():
                        utilities, rewards = [], []
                        assert len(arm["queries"]) == 6
                        for q, row in enumerate(arm["queries"]):
                            key, dt = world["query_keys"][q], world["dts"][q]
                            assert (row["query"], row["key"], row["dt"], row["deadline"]) == (q, key, dt, world["deadlines"][q])
                            assert row["events"] == world["public_events"][q]
                            scale = (.5, 1., 2., 4.)[hashlib.sha256(f"r15-price:{world['seed']}:{q}".encode()).digest()[0] % 4]
                            near(row["price_scale"], scale)
                            step, fee = 0, 0.
                            for action in row["actions"]:
                                slots = 2 if action["action"] == "REFRESH" else 1
                                step += slots
                                assert step == action["step"] and step <= 3
                                fee += .003 * slots * dt
                                if action["action"] != "WAIT":
                                    fee += (.025 if action["action"] == "READ" else .07) * scale
                                    assert action["token"] == observation(world, q, key, step, action["action"].lower())
                                    observed += 1
                                else:
                                    assert action["token"] is None
                            near(row["submitted_after"], step * dt)
                            target = state_at(world, key, world["deadlines"][q], left=True) % 4
                            assert target == row["target"]
                            reward = int(row["answer"] == target)
                            near(row["reward"], reward)
                            near(row["fee"], fee)
                            near(row["utility"], reward - fee)
                            utilities.append(reward - fee)
                            rewards.append(reward)
                        near(arm["utility"], np.mean(utilities))
                        near(arm["reward"], np.mean(rewards))
                        metric[name]["utilities"].append(float(np.mean(utilities)))
                        metric[name]["rewards"].append(float(np.mean(rewards)))
                        metric[name]["online_cpu"] += arm["cpu_seconds"]
            assert worker_worlds == 32
            for name in protocol["arms"]:
                for measure in ("utilities", "rewards"):
                    for actual, value in zip(record["arms"][name][measure], metric[name][measure], strict=True):
                        near(actual, value)
                near(record["arms"][name]["online_cpu"], metric[name]["online_cpu"])
            records.append(record)
    assert count == 512 and len(hashes) == 64
    for domain in protocol["domains"]:
        rows = [row for row in records if row["domain"] == domain]
        for measure in ("utilities", "rewards"):
            delta = np.array([np.mean(row["arms"]["fast_block2"][measure]) - np.mean(row["arms"]["D_full"][measure]) for row in rows])
            result = expected["domains"][domain]["quality"][measure]
            lower = float(delta.mean() - t.ppf(.9875, 7) * delta.std(ddof=1) / np.sqrt(8))
            near(result["mean"], delta.mean())
            near(result["simultaneous_lower"], lower)
            for a, b in zip(result["per_fit"], delta, strict=True):
                near(a, b)
            assert result["passes"] == (lower > -.01)
        costs = {}
        for name in protocol["arms"]:
            costs[name] = dict(online=sum(row["arms"][name]["online_cpu"] for row in rows),
                preparation_and_1000_owner_uses=sum(row["arms"][name]["preparation_cpu"] +
                    1000 * (row["arms"][name]["online_cpu"] + row["arms"][name]["checkpoint_cpu"]) / 32 for row in rows))
            for key, value in costs[name].items():
                near(expected["domains"][domain]["measured_cpu"][name][key], value)
        for reference in ("old_block2", "D_full"):
            for key in costs[reference]:
                near(expected["domains"][domain]["fast_over"][reference][key], costs["fast_block2"][key] / costs[reference][key])
        assert expected["domains"][domain]["engineering_speed_gate"]
        assert not expected["domains"][domain]["full_state_benefit_gate"]
    receipt = json.loads((HERE / "results/FAST_PROCESS_RECEIPT.json").read_text())
    assert receipt["exit_code"] == 0
    publication = json.loads((root / "PUBLICATION.json").read_text())
    assert publication["commit"] == expected["source_commit"] == "4a74cc79584da5302aa8d0bfcd7d01aa66ba0cd7"
    return dict(schema="hcsn-r16-fast-independent-audit-v1", passed=True,
                source_commit=expected["source_commit"], worlds=count, arm_queries=count * 3 * 6,
                old_fast_query_pairs=count * 6, raw_archives=len(hashes), raw_sha256=hashes,
                replayed_observation_tokens=observed, comparisons=comparisons,
                maximum_numeric_difference=maximum, maximum_old_fast_belief_difference=belief_error,
                quality_guards_pass=True, engineering_speed_to_old_pass=True, benefit_over_full_pass=False,
                whole_child_cpu_seconds=receipt["user_cpu_seconds"] + receipt["system_cpu_seconds"],
                scope="Raw owner targets/tokens/fees, old-fast complete action traces and prefix beliefs, fit statistics and costs; not an independent planner-optimality or production proof.",
                cost_formula="Per-fit preparation + 1000*(online+checkpoint CPU)/32; checkpoint is paid per owner use.",
                cpu_seconds=time.process_time() - started)


if __name__ == "__main__":
    result = run()
    with (HERE / "fast_run_01/INDEPENDENT_AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "worlds", "comparisons", "maximum_numeric_difference", "maximum_old_fast_belief_difference", "whole_child_cpu_seconds")}))
