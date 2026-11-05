"""Meaningful synthetic checks and original-TRAIN source alignment, no efficacy scoring."""
import argparse
import copy
import gzip
import json
from pathlib import Path
import time
import numpy as np
import planning as p
import quadratic as q


def main(joint, inputs, history, output):
    start, wall = time.process_time(), time.perf_counter()
    source_paths = {"new/" + x.name: x for x in (Path(__file__), Path(p.__file__), Path(q.__file__))}
    source_paths.update({"joint/" + x.name: x for x in joint.iterdir() if x.suffix == ".py" or x.name in ("joint_protocol.json", "truth_transitions.npz")})
    source_identity = {name: p.sha(x.read_bytes()) for name, x in source_paths.items()}
    ctx = p.load_context(joint)
    source = json.loads((joint / "INPUT_ACQUISITION.json").read_text())
    for item in source["files"]:
        assert p.sha((inputs / item["archive_member"]).read_bytes()) == item["sha256"]
    old = json.loads(gzip.decompress((history / "OLD_CONTINUATION_HEADS.json.gz").read_bytes()))
    receipts = []
    for entry in old["fits"]:
        fit = entry["fit"]
        model = json.loads((inputs / f"fit_{fit}/model_renewal/model.json").read_text())
        incumbent = copy.deepcopy(model)
        incumbent["network"]["w2"], incumbent["network"]["b2"] = entry["network_w2"], entry["network_b2"]
        payload = (json.dumps(incumbent, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        assert p.sha(payload) == entry["candidate_model_sha256"]
        assert np.array_equal(ctx.head(incumbent)[3], ctx.head(model)[3])
        policy = ctx.NumpyPolicy(model)
        own = p.OwnTableLaw(policy, ctx)
        data = json.loads((inputs / f"fit_{fit}/data/fit_{fit}_data.json").read_text())
        oracles, maximum, mass_maximum = {}, 0., 0.
        for row in data["train"]["rows"]:
            public, state = row["public"], row["state"]
            if public["id"] not in oracles:
                oracles[public["id"]] = ctx.Oracle(public, own, model["confusion"])
            oracle = oracles[public["id"]]
            mass, bank, _ = policy.represent(public, state)
            maximum = max(maximum, abs(oracle.posterior(state) - bank[7]))
            mass_maximum = max(mass_maximum, float(np.max(abs(oracle.belief(state) - mass))))
        assert maximum <= 2e-12 and mass_maximum <= 2e-12
        receipts.append(dict(fit=fit, incumbent_sha256=p.sha(payload), rows=len(data["train"]["rows"]),
                             own_posterior_vs_bank7_max=maximum, own_mass_vs_deploy_max=mass_maximum))
    synthetic = copy.deepcopy(model)
    synthetic["confusion"] = [[.9, .1], [.1, .9]]
    for item in synthetic["core"]["tables"]:
        item["matrix"] = np.eye(33).tolist()
    for name, value in synthetic["network"].items():
        synthetic["network"][name] = np.zeros_like(value).tolist()
    synthetic_policy = ctx.NumpyPolicy(synthetic)
    public = dict(schema=ctx.ns["SCHEMA"], id="synthetic-only-no-efficacy", deadline=6, initial_budget=3, target_tick=6,
                  duration=[.25] * 6, drive=[0] * 6, reliability=[1.] * 6, read_price=[.01] + [2.] * 5,
                  read_delay=[1] * 6, prior_distance=.375, latency_price=0., repair_price=.03,
                  failure_probability=.2, packets=["synthetic.json"] * 6, packet_sha256=["0" * 64] * 6)
    compiled, identity, oracle = p.compile_own(ctx, synthetic_policy, public, 20000)
    state = ctx.initial(public)
    assert abs(max(compiled["rows"][p.markov_key(state)]["q"]) - .63) < 2e-12
    result = p.evaluate(ctx, public, p.WorldPolicy(ctx, public, synthetic_policy, compiled), ctx.head(synthetic), "J", oracle)
    assert abs(result["utility"] - .63) < 2e-12 and abs(result["fees"] - .01) < 2e-12
    assert result["reads_requested"] == 1 and abs(result["reads_completed"] - .8) < 2e-12
    wrong = copy.deepcopy(public); wrong["id"] += "-wrong"
    try:
        p.WorldPolicy(ctx, wrong, synthetic_policy, compiled)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong-world compiled policy accepted")
    try:
        p.enumerate_states(ctx, public, True, 4)
    except OverflowError:
        pass
    else:
        raise AssertionError("state-cap overrun accepted")
    first = ctx.successor(public, state, 2, dict(failure=True, observation_tick=1))
    first = ctx.successor(public, ctx.successor(public, first, 3), 1)
    second = ctx.successor(public, state, 1)
    second = ctx.successor(public, second, 2, dict(failure=True, observation_tick=2))
    second = ctx.successor(public, second, 3)
    assert p.markov_key(first) == p.markov_key(second) and first["charges"] != second["charges"]
    full = p.enumerate_states(ctx, public, True, 20000)
    assert p.canonical(first) in full and p.canonical(second) in full
    rng = np.random.default_rng(448017)
    H, original = rng.normal(size=(80, 49)) / 7, rng.normal(size=(3, 49)) * .05
    Y = ctx.checked_mm(H, original.T) + .03 * rng.normal(size=(80, 3))
    W = rng.uniform(.5, 1.5, size=(80, 3)) / 240
    problem = q.prepare(H, Y, W, original, ctx.checked_mm)
    direct, dr = q.direct(problem, ctx.checked_mm, lambda: None)
    gradient, gr = q.pgd(problem, ctx.checked_mm, lambda: None)
    assert dr["converged"] and gr["converged"]
    assert abs(dr["objective"] - gr["objective"]) <= 2e-8
    assert dr["kkt_stationarity_linf"] < 1e-10 and dr["independent_cholesky_l2_difference"] < 1e-10
    assert not q.norm_certificate(original + 1, original, problem["radius"])["within_declared"]
    assert source_identity == {name: p.sha(x.read_bytes()) for name, x in source_paths.items()}
    record = dict(schema="hepta-own-bellman-preparation-check-v1", source=receipts, source_identity=source_identity,
                  synthetic_bellman_identity=identity, synthetic_known_utility=result["utility"],
                  synthetic_sunk_charge_alias_distinguished=True, synthetic_norm_and_D_G_passed=True,
                  synthetic_D_FW_gap=dr["numerical_fw_gap"], synthetic_G_FW_gap=gr["numerical_fw_gap"],
                  actual_efficacy_scores_computed=False, actual_validation_or_test_accessed=False,
                  arithmetic=ctx.arithmetic_audit, cpu_seconds=time.process_time()-start, wall_seconds=time.perf_counter()-wall)
    output.write_text(json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("joint", "inputs", "history", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        main(args.joint, args.inputs, args.history, args.output)
