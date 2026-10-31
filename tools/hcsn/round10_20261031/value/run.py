"""Registered equal-update value-head experiment and paired action evidence."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from heads import Head, features, gradient_check
from oracle import Oracle, choose, enumerate_world_value, expected_policy_value, outcomes
from task import ACTIONS, Config, Packet, config_digest, generate_world, initial, legal, posterior, rollout


PROTOCOL = {
    "schema": "hepta.r10.value.protocol.v1", "families": ["ordinary", "matched_c1", "analytic"],
    "training_seeds": [17, 29, 43], "hidden_width": 24, "steps": 1800,
    "batch_size": 256, "train_configs": 128, "validation_configs": 32,
    "test_id_configs": 48, "test_ood_configs": 48,
    "configuration_seeds": {"train": 3101, "validation": 3102, "test_id": 3103, "test_ood": 3104},
    "selection": "lowest validation action-advantage MSE at 100-update checkpoints",
    "primary": "held-out expected utility difference analytic minus ordinary, paired by configuration and fit seed",
    "secondary": "analytic minus matched_c1; regret against exact Bellman optimum; strong fixed-rule comparison",
    "uncertainty": "paired bootstrap of task configurations and training seeds, 2000 resamples",
    "test_adaptation": False, "energy": "unmeasured; never inferred from event count or CPU time",
    "contract": "native/task_contract.json; monetary task costs are declared units, not measured joules",
    "kernel_scope": "zero-drift Brownian first-passage gate as a differentiable feature; no claim of exact FullHX stochastic process",
}


def configurations(seed, count, ood=False):
    rng = np.random.default_rng(seed)
    result = []
    for _ in range(count):
        n = int(rng.integers(2, 5))
        arrivals = sorted([0] + rng.integers(0, 5, n-1).tolist())
        failure = float(rng.choice([.0, .08, .16] if not ood else [.20, .35]))
        packets = tuple(Packet(a, float(rng.uniform(.60, .93)), failure) for a in arrivals)
        result.append(Config(deadline=int(rng.integers(4, 9)), budget=int(rng.integers(1, n+1)),
                             prior=float(rng.choice([.30, .50, .70])),
                             read_cost=float(rng.uniform(.012, .09) if not ood else rng.uniform(.10, .20)),
                             latency_cost=float(rng.uniform(.002, .018)), stop_cost=.002,
                             failure_cost=.025, invalid_cost=.03,
                             refractory_ticks=int(rng.integers(0, 3)), packets=packets))
    return result


def dataset(configs):
    x, times, y, mask = [], [], [], []
    teachers = []
    for c in configs:
        teacher = Oracle(c)
        teacher.q(initial(c))
        teachers.append(teacher)
        for s in tuple(teacher.states.values()):
            q = teacher.q(s)
            f, t = features(c, s)
            m = [int(a in legal(c, s)) for a in ACTIONS[:2]]
            x.append(f)
            times.append(t)
            y.append([q[i]-q[2] if m[i] else 0 for i in range(2)])
            mask.append(m)
    return tuple(np.asarray(v, dtype=float) for v in (x, times, y, mask)), teachers


def threshold_policy(threshold):
    def policy(c, s):
        belief = posterior(c, s)
        if max(belief, 1-belief) >= threshold or not s.budget_left or s.next_packet == len(c.packets):
            return "STOP"
        if "READ" in legal(c, s):
            return "READ"
        ready = max(s.recovery_until, c.packets[s.next_packet].arrival)
        return "WAIT" if ready < c.deadline and "WAIT" in legal(c, s) else "STOP"
    return policy


def bootstrap(differences, seed=51):
    d = np.asarray(differences)
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(2000):
        ci = rng.integers(0, d.shape[0], d.shape[0])
        si = rng.integers(0, d.shape[1], d.shape[1])
        samples.append(d[np.ix_(ci, si)].mean())
    interval = np.quantile(samples, [.025, .975]).tolist()
    return {"mean": float(d.mean()), "ci95": interval, "positive_gate": interval[0] > 0}


def native_export(config, teacher, heads):
    # Runtime config adapter lives in native; these metadata and keys carry no votes.
    policies = {"oracle": {s.key: list(teacher.q(s)) for s in teacher.states.values()}}
    for family, models in heads.items():
        model = models[0]
        policies[family] = {s.key: model.q(config, s).tolist() for s in teacher.states.values()}
    return {"task": config.to_dict(), "config_digest": config_digest(config), "policies": policies}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    (output / "PROTOCOL.json").write_text(json.dumps(PROTOCOL, indent=2)+"\n")
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
    (output / "SOURCES.json").write_text(json.dumps(sources, indent=2)+"\n")
    splits = {name: configurations(PROTOCOL["configuration_seeds"][name], PROTOCOL[name+"_configs"], name=="test_ood")
              for name in ("train", "validation", "test_id", "test_ood")}
    (output / "CONFIGURATIONS.json").write_text(json.dumps({k:[c.to_dict() for c in v] for k,v in splits.items()}, indent=2)+"\n")
    preparation = time.process_time()
    train, _ = dataset(splits["train"])
    validation, validation_teachers = dataset(splits["validation"])
    _, id_teachers = dataset(splits["test_id"])
    _, ood_teachers = dataset(splits["test_ood"])
    preparation = time.process_time() - preparation
    checks = gradient_check()
    checks["independent_world_enumeration"] = []
    for c, teacher in zip(splits["validation"][:4], validation_teachers[:4]):
        q = teacher.q(initial(c))
        for action in legal(c, initial(c)):
            actual = enumerate_world_value(c, teacher.policy, forced_first=action)
            error = abs(actual-q[ACTIONS.index(action)])
            checks["independent_world_enumeration"].append({"config":config_digest(c), "action":action, "error":error})
            assert error < 2e-12
    thresholds = [.5, .6, .7, .8, .9, .98, 1.0]
    threshold_values = [np.mean([expected_policy_value(c, threshold_policy(t)) for c in splits["validation"]]) for t in thresholds]
    best_threshold = thresholds[int(np.argmax(threshold_values))]
    heads, fits = {}, []
    for family in PROTOCOL["families"]:
        heads[family] = []
        for seed in PROTOCOL["training_seeds"]:
            head = Head(train[0].shape[1], PROTOCOL["hidden_width"], family, seed)
            fit = head.train(train, validation, seed, PROTOCOL["steps"], PROTOCOL["batch_size"])
            fit.update(family=family, seed=seed, parameters=head.parameter_count)
            fits.append(fit)
            heads[family].append(head)
            (output / f"checkpoint_{family}_{seed}.json").write_text(json.dumps(head.checkpoint())+"\n")
            print(json.dumps({k:fit[k] for k in ("family","seed","validation_mse","training_cpu_seconds")}), flush=True)
    results, raw = {}, []
    for split, teachers in (("test_id", id_teachers), ("test_ood", ood_teachers)):
        configs = splits[split]
        optimal = np.array([max(t.q(initial(c))) for c,t in zip(configs,teachers)])
        fixed = np.array([expected_policy_value(c, threshold_policy(best_threshold)) for c in configs])
        stop = np.array([max(c.prior,1-c.prior)-c.stop_cost for c in configs])
        values = {family:np.array([[expected_policy_value(c,h.policy) for h in models] for c in configs])
                  for family,models in heads.items()}
        for i,c in enumerate(configs):
            raw.append({"split":split,"config":config_digest(c),"optimal":float(optimal[i]),
                        "fixed":float(fixed[i]),"stop":float(stop[i]),
                        **{f:values[f][i].tolist() for f in values}})
        results[split] = {"optimal":float(optimal.mean()),"fixed":float(fixed.mean()),"initial_stop":float(stop.mean()),
                          "family_utility":{f:float(v.mean()) for f,v in values.items()},
                          "family_regret":{f:float(np.mean(optimal[:,None]-v)) for f,v in values.items()},
                          "analytic_minus_ordinary":bootstrap(values["analytic"]-values["ordinary"]),
                          "analytic_minus_matched_c1":bootstrap(values["analytic"]-values["matched_c1"]),
                          "analytic_minus_fixed":bootstrap(values["analytic"]-fixed[:,None]),
                          "optimal_minus_initial_stop":bootstrap((optimal-stop)[:,None])}
    counterfactuals = []
    for i,(c,teacher) in enumerate(zip(splits["test_id"][:8],id_teachers[:8])):
        for seed in range(12):
            world = generate_world(c, 99000 + i*100 + seed)
            branches = {a:rollout(c, world, teacher.policy, forced_first=a) for a in legal(c, initial(c))}
            counterfactuals.append({"config":config_digest(c),"world":asdict(world),"start":asdict(initial(c)),"branches":branches})
        (output / f"native_case_{i}.json").write_text(json.dumps(native_export(c,teacher,heads))+"\n")
    benchmark = []
    c,s=splits["test_id"][0],initial(splits["test_id"][0])
    for family, models in heads.items():
        h=models[0]
        for _ in range(20): h.policy(c,s)
        start=time.process_time()
        for _ in range(2000): h.policy(c,s)
        benchmark.append({"family":family,"seconds_per_decision":(time.process_time()-start)/2000})
    summary = {"protocol":PROTOCOL,"checks":checks,"fits":fits,"results":results,
               "train_rows":len(train[0]),"validation_rows":len(validation[0]),
               "teacher_preparation_cpu_seconds":preparation,"fixed_threshold":best_threshold,
               "controller_costs":benchmark,"end_to_end_cpu_seconds":time.process_time()-start_cpu,
               "end_to_end_wall_seconds":time.perf_counter()-start_wall,
               "native_executed":False,"raw_counterfactual_worlds":len(counterfactuals),
               "energy_joules":None}
    for name,data in (("RESULTS",summary),("PAIRED_UTILITIES",raw),("COUNTERFACTUALS",counterfactuals)):
        (output/(name+".json")).write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps(results,indent=2))


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    run(p.parse_args().output)
