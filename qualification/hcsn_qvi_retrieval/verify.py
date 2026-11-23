"""Independent sealed replay. Uses the released dynamics, NumPy normal equations
and a separate scalar retrieval environment. No campaign, NDU, or editor import.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import torch

from .dynamics import RetrievalFlow


HERE = Path(__file__).parent
SCIENCE = ("adapt.py", "agent_edit.py", "campaign.py", "dynamics.py", "ndu.py", "media.py",
           "run_study.py", "acquire_media.py")
UPSTREAM = {
    "hcsn_adaptive/__init__.py": "be61dbd4202a3224f90a96d053b25c3ff3fe1430",
    "hcsn_adaptive/batched_flow.py": "02d49b790a58146c34f9d8501da8c2ef1ec236e2",
    "hcsn_adaptive/finite_control.py": "26da3fb6052793bef8f404e0c23490d2f6a8f3ad",
    "hcsn_adaptive/flow_semantics.py": "d45b2734acdecb7f765bc8c5c33e7d948ec7fede",
    "hcsn_adaptive/impulse_execution.py": "2e071a049969ff86eaf28c63aead648a8738a549",
    "hcsn_differentiable/__init__.py": "480da60a88839bc88708c1e2b93f00df26ee6abe",
    "hcsn_differentiable/contract.py": "802c227f7104658ef0accdb7b92bf497000eb714",
    "hcsn_differentiable/neural_control.py": "a86a0298ee79c0abdddffb2a8d425e763d4eb6df",
    "hcsn_differentiable/operator.py": "560fac36e2fd8530d7fb269670cf1c6743e1ceec",
    "hcsn_differentiable/regenerative.py": "050b58e079b0a0b3e61dec56774e8cabaa098d81",
    "hcsn_training/__init__.py": "6fbe676a1200a57029b70c99dd4e8fac527dd30d",
    "hcsn_training/population_generator.py": "fc0322aa90a51c4c5a491d30dc8d1bd2dd7a0957",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(a, b):
    np.testing.assert_allclose(a, b, atol=1e-9, rtol=1e-9, equal_nan=False)


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_cost(evidence, phase, key):
    stem = evidence / phase / key
    cost = load(stem.with_suffix(".cost.json"))
    require(cost["returncode"] == 0 and cost["log_sha"] == digest(stem.with_suffix(".log"))
            and cost["output_sha"] == digest(stem.with_suffix(".json")), f"invalid child receipt {stem}")
    wall = cost["wall_seconds"]
    same(wall, cost["end_unix"] - cost["start_unix"])
    require(wall > 0 and math.isfinite(wall), "invalid cold-process time")
    return cost


def read_shard(data, name, manifest, clock):
    path = data / f"{name}.npz"
    receipt = load(data / f"{name}.receipt.json")
    require(receipt["split"] == name and receipt["output_sha256"] == digest(path)
            and receipt["implementation"] == digest(HERE / "media.py"), "unbound decoded data")
    with np.load(path, allow_pickle=False) as source:
        s = {key: source[key] for key in source.files}
    actors = manifest["splits"][name]
    expect = {f"01-01-{emotion:02}-01-{statement:02}-{rep:02}-{actor:02}.mp4"
              for actor, emotion, statement, rep in itertools.product(
                  actors, manifest["emotion_ids"], manifest["statement_ids"], manifest["repetition_ids"])}
    raw_names = expect
    hashes = receipt["source_sha256"]
    require(set(hashes)==raw_names and all(len(v)==64 for v in hashes.values()), "source identities")
    require(manifest["source_integrity_erratum"]["excluded_actor_emotion"] == [[7,3]],
            "unexpected source integrity exclusion")
    aliases = {v:sorted(k for k in hashes if hashes[k]==v) for v in set(hashes.values())
               if list(hashes.values()).count(v)>1}
    known_hash = "5dd27eab5b1eaa8d7f8523b113231e426881f316d275a02a358bf1001c876969"
    expected_aliases = {known_hash:[f"01-01-03-01-02-0{r}-07.mp4" for r in (1,2)]} if name=="retain" else {}
    require(aliases==expected_aliases,"unaccounted duplicate recording")
    expect = {q for q in raw_names if not (q.startswith("01-01-03-") and q.endswith("-07.mp4"))}
    require(len(s["query_id"]) == len(expect) and set(s["query_id"]) == expect and set(s["split"]) == {name},
            f"incomplete independent opposite-take pairs for {name}")
    for q, gallery, target, group in zip(s["query_id"], s["gallery_id"], s["target"], s["group"], strict=True):
        fields = Path(q).stem.split("-")
        actor, emotion, statement, rep = [int(fields[i]) for i in (6, 2, 4, 5)]
        key = f"hepta-qvi-ravdess-v1/{actor}/{emotion}/{rep}".encode()
        order = (1,2) if hashlib.sha256(key).digest()[0] % 2 == 0 else (2,1)
        check = [f"01-01-{emotion:02}-01-{n:02}-{3-rep:02}-{actor:02}.mp4" for n in order]
        require(group == f"ravdess-actor-{actor:02}" and list(gallery) == check
                and target == order.index(statement), "invalid gallery, label or actor")
    same(s["dt"], np.full((len(expect), clock["steps"]), clock["seconds_per_step"]))
    same(s["x"][:, :, -1], np.tile(np.arange(1,clock["steps"]+1)/clock["steps"], (len(expect),1)))
    same(s["x"][:, :, -2], np.abs(np.diff(s["scores"], axis=-1)[:,:,0]))
    s["truth"] = np.stack([a.argmax(-1) == s["target"][:, None] for a in (s["scores"], s["read_scores"])], axis=-1)
    s["hash"] = receipt["output_sha256"]
    s["source_hashes"] = set(hashes.values())
    return s


def discounted(reward, elapsed, cost):
    return np.exp(-cost["discount"]*elapsed) * reward + (
        cost["wait_rate"] / cost["discount"] * np.expm1(-cost["discount"]*elapsed)
    )


def teacher(s, cost):
    # Explicit enumeration over each possible later exit, no recursive teacher.
    rewards = s["truth"].astype(float) - [0, cost["read_price"]]
    times = s["dt"].cumsum(axis=1)
    target = np.empty((*times.shape, 3))
    target[:, :, :2] = rewards
    target[:, -1, 2] = rewards[:, -1, 0]
    for t in range(times.shape[1]-1):
        delta = times[:, t+1:] - times[:, t:t+1]
        target[:,t,2] = discounted(rewards[:,t+1:], delta[:,:,None], cost).max(axis=(1,2))
    return target


def evaluate(q, s, cost):
    outcomes = []
    for i, (scores, intervals) in enumerate(zip(q, s["dt"], strict=True)):
        time = 0.
        for t, row in enumerate(scores):
            if t:
                time += intervals[t]
            act = int(np.argmax(row[:2] if t == len(intervals)-1 else row))
            if act == 2:
                continue
            hit = int(s["truth"][i,t,act])
            reward = hit - (cost["read_price"] if act else 0.)
            utility = float(discounted(reward, time, cost))
            outcomes.append((act,t,hit,utility))
            break
    a, t, hit, u = map(np.asarray, zip(*outcomes))
    actor = s["group"]
    return dict(terminal_action=a.tolist(), exit_prefix=t.tolist(), hits=hit.tolist(),
                episode_utility=u.tolist(), episodes=len(a), reads=int(a.sum()), wait_steps=int(t.sum()),
                utility=float(u.mean()), r1=float(hit.mean()),
                per_actor={g:float(u[actor==g].mean()) for g in np.unique(actor)},
                per_actor_r1={g:float(hit[actor==g].mean()) for g in np.unique(actor)})


def compare_metrics(replay, recorded, *, episodes):
    keys = set(replay)
    if not episodes:
        keys -= {"terminal_action","exit_prefix","hits","episode_utility"}
    for key in keys:
        if isinstance(replay[key],dict):
            require(set(replay[key]) == set(recorded[key]), f"actor identities differ for {key}")
            for g in replay[key]:
                same(replay[key][g], recorded[key][g])
        else:
            same(replay[key], recorded[key])


def min_actor(a, b):
    return min(a["per_actor"][g]-b["per_actor"][g] for g in a["per_actor"])


def margin_bins(s, edges):
    spread = np.ptp(s["scores"], axis=-1)
    # Strict > replicates closed upper edge at each marginal quartile.
    return (spread[:,:,None] > edges).sum(-1)


def finite_bellman(train, cost):
    edges = np.percentile(np.ptp(train["scores"], axis=-1), [25,50,75])
    bins = margin_bins(train, edges)
    n,tmax = bins.shape
    table = np.zeros((tmax,4,3))
    for t in reversed(range(tmax)):
        r = train["truth"][:,t].astype(float) - [0,cost["read_price"]]
        for k in range(4):
            # One global-prior pseudo-episode per sparse state.
            w = (bins[:,t] == k).astype(float) + 1./n
            w /= w.sum()
            table[t,k,:2] = w @ r
            if t == tmax-1:
                table[t,k,2] = table[t,k,0]
            else:
                continuation = table[t+1,bins[:,t+1]].max(axis=1)
                table[t,k,2] = w @ discounted(continuation,train["dt"][:,t+1],cost)
    return edges, table


def controls(split, edges, table, cost):
    shape = (*split["dt"].shape,3)
    outcomes = {}
    for i, name in enumerate(("immediate_stop", "immediate_read")):
        q = np.zeros(shape)
        q[:,:,i] = 1
        outcomes[name] = evaluate(q, split, cost)
    outcomes["hindsight_upper"] = evaluate(teacher(split,cost), split, cost)
    q = table[np.arange(shape[1])[None,:], margin_bins(split,edges)]
    outcomes["empirical_bellman"] = evaluate(q,split,cost)
    return outcomes


def regression(h, targets, ridge):
    # Independent normal equations, rather than the production centered SVD.
    matrix = np.column_stack((h.reshape(-1,h.shape[-1]), np.ones(h.shape[0]*h.shape[1])))
    y = targets.reshape(len(matrix),-1)
    penalty = np.full(matrix.shape[1], ridge*len(matrix))
    penalty[-1] = 0.
    return np.linalg.solve(matrix.T @ matrix + np.diag(penalty), matrix.T @ y)


def verify(data, evidence):
    plan, manifest = load(HERE/"protocol.json"), load(HERE/"data_manifest.json")
    sealpath = evidence/"selection_seal.json"
    seal = load(sealpath)
    arms = list(itertools.product(plan["modes"],plan["methods"],plan["seed"]))
    names = {f"{m}-{a}-{s}.json" for m,a,s in arms}
    require(len(names)==27 and set(seal["files"]) == names
            and seal["arms"] == [list(a) for a in arms]
            and seal["protocol"] == digest(HERE/"protocol.json"), "wrong sealed experiment")
    for name, sha in seal["files"].items():
        require(digest(evidence/"fit"/name)==sha, f"fit seal mismatch {name}")
    for name in SCIENCE:
        require(seal["fit_source"].get(name)==digest(HERE/name), f"scientific source differs {name}")
    for name, expected in UPSTREAM.items():
        b = (HERE.parent/name).read_bytes()
        require(hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()==expected,
                f"upstream Git object differs {name}")
    seal_sha = digest(sealpath)
    # All model decisions have been sealed before any observed TEST scores enter this program.
    shards = {s:read_shard(data,s,manifest,manifest["clock"]) for s in manifest["splits"]}
    require(len(set.union(*(s["source_hashes"] for s in shards.values()))) == 191,
            "source recording bytes overlap between actor splits")
    raw = shards["train"]["x"]
    mean, scale = raw.mean((0,1)), np.maximum(raw.std((0,1)), 1e-8)
    cost = plan["cost"]
    target = teacher(shards["train"],cost)
    edges, table = finite_bellman(shards["train"],cost)
    baselines = controls(shards["test"],edges,table,cost)
    for s in shards.values():
        s["standard"] = torch.from_numpy((s["x"]-mean)/scale)
        s["dt_t"] = torch.from_numpy(s["dt"])
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    seen, selections, nsamples = {}, {}, 0
    totals = {phase:0. for phase in ("fit","confirm")}
    chosen_results = {}
    counters = {}
    for mode, method, seed in arms:
        key = f"{mode}-{method}-{seed}"
        f = load(evidence/"fit"/f"{key}.json")
        c = load(evidence/"confirm"/f"{key}.json")
        for record in (f,c):
            require((record["mode"],record["method"],record["seed"]) == (mode,method,seed),f"misidentified {key}")
        require(c["selection_seal"]==seal_sha and c["fit_hash"]==seal["files"][key+".json"],"wrong confirmation")
        for name in SCIENCE:
            require(f["sources"].get(name) == seal["fit_source"][name], f"fit source differs {name}")
        require(f["protocol_hash"] == seal["protocol"], "fit protocol mismatch")
        for n in shards:
            recorded = c if n=="test" else f
            require(recorded[n+"_hash"] == shards[n]["hash"], f"wrong {n} shard")
        require(c["query_id"]==shards["test"]["query_id"].tolist() and c["actor"]==shards["test"]["group"].tolist(),
                "confirmed row identities differ")
        for phase, record in (("fit",f),("confirm",c)):
            cold = process_cost(evidence,phase,key)
            require(0 <= record["elapsed_seconds"] <= cold["wall_seconds"]+1e-4, "inner cost exceeds cold cost")
            totals[phase] += cold["wall_seconds"]
        same(f["mean"],mean)
        same(f["scale"],scale)
        same(f["finite_edges"],edges)
        same(f["finite_q"],table)
        torch.manual_seed(seed)
        model = RetrievalFlow(raw.shape[-1],mode=mode)
        require(list(model.feature_names)==f["physical_channels"] and list(model.edit_names)==list(f["names"]),
                "physical operator layout differs")
        def features(t, n):
            cache_key = (seed, mode, tuple(t), n)
            if cache_key not in seen:
                s = shards[n]
                with torch.no_grad():
                    physical = model.features_with_edit(torch.tensor(t,dtype=torch.float64),s["standard"],s["dt_t"])
                    seen[cache_key] = torch.cat((s["standard"],physical),-1).numpy()
            return seen[cache_key]
        def predictions(t,head,n):
            h = features(t,n)
            return evaluate(h@head[:-1] + head[-1],shards[n],cost)
        fit = f["fit"]
        attempts = fit["attempts"]
        zero = [0.]*len(model.edit_names)
        require(attempts[0]["name"]=="KEEP" and attempts[0]["theta"] == zero and f["keep_theta"] == zero,
                "post-SVD incumbent is not shared zero edit")
        keep_head = regression(features(zero,"train"),target,plan["training"]["ridge"])
        same(f["keep_head"],keep_head)
        retention = predictions(zero,keep_head,"retain")
        best_idx, best_utility, selected_head = None, -np.inf, None
        for i,row in enumerate(attempts):
            require(0 <= sum(v["wall_seconds"] for v in row["stages"].values()) <= row["wall_seconds"]+1e-4,
                    "invalid stage accounting")
            if "error" in row:
                continue
            t = row["theta"]
            require(np.linalg.norm(t)<=plan["training"]["radius"]+1e-12, "candidate outside trust region")
            head = regression(features(t,"train"),target,plan["training"]["ridge"])
            dev = predictions(t,head,"dev")
            retain = predictions(t,head,"retain")
            details, = row["diagnostics"]
            compare_metrics(dev,details["dev"],episodes=False)
            compare_metrics(retain,details["retain"],episodes=False)
            same(row["utility"],dev["utility"])
            delta = min_actor(retain,retention)
            same(details["worst_retain_delta"],delta)
            allowed = delta >= -.05-1e-12
            require(allowed==row["allowed"], "selection preservation gate differs")
            if allowed and dev["utility"] > best_utility+1e-12:
                best_idx, best_utility, selected_head = i, dev["utility"], head
            nsamples += 1
        require(best_idx==fit["selected_index"] and f["theta"]==attempts[best_idx]["theta"]
                and f["theta"]==fit["selected_theta"], "selected edit differs")
        same(fit["selected_utility"],best_utility)
        same(f["head"],selected_head)
        # Independently decode the exact stored head to recover its decisions.
        selected = predictions(f["theta"],np.asarray(f["head"]),"test")
        unchanged = predictions(zero,np.asarray(f["keep_head"]),"test")
        compare_metrics(selected,c["chosen"],episodes=True)
        compare_metrics(unchanged,c["keep"],episodes=True)
        actor_delta = {g:selected["per_actor"][g]-unchanged["per_actor"][g] for g in selected["per_actor"]}
        for name, independent in baselines.items():
            compare_metrics(independent,c["controls"][name],episodes=True)
        impossible = int((~shards["test"]["truth"].any((1,2))).sum())
        require(c["controls"]["structurally_unretrievable"]==impossible, "retriever structural ceiling differs")
        same(c["worst_actor_delta"],min(actor_delta.values()))
        same(c["worst_vs_common_stop"],min_actor(selected,baselines["immediate_stop"]))
        require(np.all(np.asarray(selected["episode_utility"])<=np.asarray(baselines["hindsight_upper"]["episode_utility"])+1e-12),
                "policy exceeded per-episode perfect-information utility")
        ok = (selected["utility"]>=plan["success"]["utility_at_least"] and
              selected["r1"]>=plan["success"]["retrieval_R1_at_least"] and
              min(actor_delta.values())>=plan["success"]["worst_actor_utility_delta_at_least"]-1e-12)
        require(c["success"]==ok, "threshold mismatch")
        chosen_results[key] = dict(passed=bool(ok),utility=selected["utility"],r1=selected["r1"],
                                   actor_delta=actor_delta)
        selections[key] = attempts[best_idx]["name"]
        counts = fit["cost"]
        require(int(counts["backward_calls"]) == sum("profiled_backward" in r["stages"] for r in attempts)
                and int(counts["dev_score_calls"]) == sum("selection_and_retention" in r["stages"] for r in attempts),
                "candidate counters differ from stage receipts")
        if method != "bp":
            require(counts["backward_calls"]==0, "unregistered nonlinear gradient for non-BP arm")
        if not fit["errors"]:
            expected_f = len(attempts) + len(fit["editor_probes"]) + int(method=="wsp")
            require(counts["condition_solves"]==expected_f==counts["train_feature_calls"]
                    and counts["train_rows"]==expected_f*len(raw)*raw.shape[1], "TRAIN cost counters disagree")
        require(sum(r["wall_seconds"] for r in attempts)<=fit["wall_seconds"]+1e-4
                and fit["wall_seconds"]<=f["elapsed_seconds"]+1e-4, "nested fit times disagree")
        counters[key] = counts
    family = {f"{m}-{a}":all(chosen_results[f"{m}-{a}-{s}"]["passed"] for s in plan["seed"])
              for m,a in itertools.product(plan["modes"],plan["methods"])}
    return {"passed":True, "models_verified":len(arms),"candidate_selections_replayed":nsamples,
            "independent_replay_physical_feature_calls":len(seen),"selected":selections,"arms":chosen_results,
            "family_success":family,"summed_cold_child_seconds":totals,"fit_counters":counters,
            "selection_seal_sha256":seal_sha,
            "scope":"Checks scalar physical-object source, actor/source receipts and conditional ridge/selection/held-out execution. Does not independently decode raw MP4s or measure external editing labor."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    parser.add_argument("evidence",type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.data,args.evidence),allow_nan=False,sort_keys=True))
