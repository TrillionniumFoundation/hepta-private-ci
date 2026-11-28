"""Frozen late-quote task: graph intervention, four weight edits, random and BP.

No gradient flows through the physical operator; its final-step sufficient
coefficients are recomputed once from each complete raw-input trajectory.
"""
import copy
import hashlib
import json
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import time

import numpy as np
from scipy.special import expit

from bridge_replay import BridgeReplay
from temporal_probe import ROOT, PRIOR, PACKET, TRACE, PROTOCOL_SHA, previous, canonical, encode, save, sha

SEEDS = (47, 83, 137)
PRICE = 7
SIGNED = np.arange(2, 20, 5)


def metric(scores, y):
    margin = scores[:, 1].astype(float)-scores[:, 0].astype(float)
    p = expit(margin)
    return {"correct": int((scores.argmax(1) == y).sum()), "queries": len(y),
            "accuracy": float((scores.argmax(1) == y).mean()),
            "ce": float(np.mean(np.logaddexp(0., margin)-y*margin)),
            "brier": float(np.mean((p-y)**2)),
            "min_probability": float(p.min()), "max_probability": float(p.max())}


def task(seed, contexts, limit):
    rng = np.random.Generator(np.random.PCG64(seed))
    raw = rng.normal(0., .5, (contexts, 6, 9)).astype(np.float32)
    xs, ys = [], []
    for context in raw:
        prices = rng.uniform(-limit, limit, 2).astype(np.float32)
        while abs(float(prices[0]-prices[1])) < .2:
            prices = rng.uniform(-limit, limit, 2).astype(np.float32)
        for pair in (prices, prices[::-1]):
            x = np.repeat(context[:, None, :], 2, axis=1)
            x[5, :, PRICE] = pair
            xs.append(x)
            ys.append(int(pair.argmin()))
    return {"x": np.stack(xs), "base": np.zeros((2*contexts, 2), dtype=np.float32),
            "y": np.asarray(ys, dtype=np.int64), "seed": seed}


def historical(split):
    path = PRIOR / "payload/data" / f"{split}.npz"
    assert sha(path.read_bytes()) == previous().DATA_SHA[split]
    with np.load(path, allow_pickle=False) as a:
        shared = a["x"][:, :, [0, 1, 2, 3, 4, 5, 7]]
        base = a["read_scores"].astype(np.float32)
        audio = a["scores"]
        x = np.concatenate((np.broadcast_to(shared[:, :, None, :], (*base.shape, 7)),
                            audio[..., None], (2*a["read_scores"]-audio)[..., None]), -1).astype(np.float32)
        y = a["target"].astype(np.int64)
    moments = np.frombuffer((PACKET / "train_raw.bin").read_bytes()[24:100], dtype="<f4")
    return {"x": (x-moments[:9])/moments[9:18], "base": base[:, -1]/moments[18], "y": y}


def install(state, theta):
    candidate = {k: v.copy() for k, v in state.items()}
    candidate["body.input_mark.weight"][:, PRICE] = np.asarray(theta, dtype=np.float32)
    return candidate


def compile_sign(state):
    parent = state["body.input_mark.weight"][:, PRICE].copy()
    head = state["body.readout.weight"].astype(float)
    contrast = head[1, SIGNED]-head[0, SIGNED]
    desired = np.where(contrast != 0., -np.sign(contrast)*np.where(parent != 0., abs(parent), 1./16), parent).astype(np.float32)
    return desired, contrast


def represented(theta, parent, radius):
    delta = np.asarray(theta, dtype=float)-parent.astype(float)
    norm = np.linalg.norm(delta)
    if norm > radius:
        delta *= radius/norm
    actual = (parent.astype(float)+delta).astype(np.float32)
    for _ in range(10):
        if np.linalg.norm(actual.astype(float)-parent.astype(float)) <= radius:
            return actual
        delta *= 1-2**-20
        actual = (parent.astype(float)+delta).astype(np.float32)
    raise ArithmeticError("F32 realization escaped the frozen radius")


def reduced(state, basis, theta, gradient=False, y=None):
    mark = state["body.input_mark.weight"].copy()
    mark[:, PRICE] = theta
    if not gradient:
        z = basis["xlast"] @ mark.T + state["body.input_mark.bias"]
        z = basis["rec"]+z
        signed = basis["offset"]+basis["alpha"]*np.tanh(z).astype(float)
        features = basis["features"].copy().reshape(-1, 20)
        features[:, SIGNED] = signed.astype(np.float32)
        f = features.reshape(-1, 2, 20)
        heads = f @ state["body.readout.weight"].T+state["body.readout.bias"]
        scores = basis["baseline"]+(heads[..., 1]-heads[..., 0])
        return f, scores
    z = basis["xlast"].astype(float) @ mark.astype(float).T + state["body.input_mark.bias"].astype(float)
    z += basis["rec"].astype(float)
    tanh = np.tanh(z)
    features = basis["features"].astype(float).reshape(-1, 20)
    features[:, SIGNED] = basis["offset"]+basis["alpha"]*tanh
    head = state["body.readout.weight"].astype(float)
    contrast = head[1]-head[0]
    scores = basis["baseline"].astype(float)+(features @ contrast+float(state["body.readout.bias"][1]-state["body.readout.bias"][0])).reshape(-1, 2)
    margin = scores[:, 1]-scores[:, 0]
    loss = np.mean(np.logaddexp(0., margin)-y*margin)
    upstream = ((expit(margin)-y)[:, None]*np.array([-1., 1.])/len(y)).reshape(-1)
    jac = contrast[SIGNED]*basis["alpha"]*(1-tanh*tanh)*basis["xlast"][:, PRICE, None]
    return float(loss), (upstream[:, None]*jac).sum(0)


def native_run(native, directory, name, parent_path, profile, candidate_theta, inputs, mode):
    raw = encode(inputs["x"], inputs["base"], inputs["y"])
    input_path = directory / f"{name}.input.bin"
    input_path.write_bytes(raw)
    p = copy.deepcopy(profile)
    p["input_sha256"], p["input_bytes"] = sha(raw), len(raw)
    p["source_declarations"]["task_input"] = "Declared new late-quote family" if "seed" in inputs else "Historical RAVDESS retention"
    profile_path = directory / f"{name}.profile.json"
    save(profile_path, p)
    payload = bytearray(parent_path.read_bytes())
    header_len = struct.unpack("<Q", payload[:8])[0]
    header = json.loads(payload[8:8+header_len])
    start = 8+header_len+header["body.input_mark.weight"]["data_offsets"][0]
    for j, value in enumerate(candidate_theta):
        struct.pack_into("<f", payload, start+(j*9+PRICE)*4, value)
    candidate = directory / f"{name}.safetensors"
    candidate.write_bytes(payload)
    output = directory / f"{name}.native.json"
    cmd = [str(native), mode, str(profile_path), sha(profile_path.read_bytes()),
           str(parent_path), sha(parent_path.read_bytes()), str(candidate), sha(payload),
           str(input_path), sha(raw), str(output)]
    begin = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    save(directory / f"{name}.receipt.json", {"command": cmd, "exit_code": proc.returncode,
        "wall_seconds": time.perf_counter()-begin, "stdout": proc.stdout, "stderr": proc.stderr})
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    value = json.loads(output.read_text())
    return value, sha(payload)


def run():
    start = time.perf_counter()
    cpu_start = time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert sha((ROOT / "LATE_INFORMATION_PROTOCOL.md").read_bytes()) == PROTOCOL_SHA
    out = ROOT / "late_results"
    out.mkdir(exist_ok=False)
    native = out / "native-bridge-frozen"
    shutil.copy2(TRACE, native)
    save(out / "EXECUTION_SEAL.json", {"protocol_sha256": PROTOCOL_SHA,
        "source_sha256": sha(Path(__file__).read_bytes()), "bridge_source_sha256": sha((ROOT / "bridge_replay.py").read_bytes()),
        "native_binary_sha256": sha(native.read_bytes()), "start_unix": time.time(),
        "observed_new_task_results": 0})
    original = previous()
    states = {s: original.read_checkpoint(s) for s in SEEDS}
    direct, program_rows = {}, []
    for seed, state in states.items():
        begin_wall, begin_cpu = time.perf_counter(), time.process_time()
        direct[seed], v = compile_sign(state)
        parent = state["body.input_mark.weight"][:, PRICE]
        program_rows.append({"seed": seed, "parent_price_weights": parent.tolist(),
            "head_signed_contrast": v.tolist(), "direct_price_weights": direct[seed].tolist(),
            "changed_scalars": int((parent != direct[seed]).sum()),
            "delta_l2": float(np.linalg.norm(direct[seed].astype(float)-parent.astype(float))),
            "parameter_output_sha256": sha(direct[seed].astype("<f4").tobytes()),
            "wall_seconds": time.perf_counter()-begin_wall, "cpu_seconds": time.process_time()-begin_cpu,
            "label_accesses": 0, "objective_calls": 0, "forward_calls": 0, "backward_calls": 0})
    save(out / "DIRECT_PROGRAMS_BEFORE_DATA.json", program_rows)
    train, dev = task(2026112801, 32, 1.), task(2026112802, 16, 1.5)
    np.savez_compressed(out / "train_dev_inputs.npz", train_x=train["x"], train_y=train["y"], dev_x=dev["x"], dev_y=dev["y"])
    selected, records, common_cost, objective_counts = {}, [], [], []
    python_forwards = 0
    for seed in SEEDS:
        state = states[seed]
        parent = state["body.input_mark.weight"][:, PRICE].copy()
        radius = float(np.linalg.norm(direct[seed].astype(float)-parent.astype(float)))
        begin = time.perf_counter()
        _, _, diag, basis = BridgeReplay(state).forward(train["x"], train["base"])
        python_forwards += 1
        _, _, dev_diag, dev_basis = BridgeReplay(state).forward(dev["x"], dev["base"])
        python_forwards += 1
        common_cost.append({"seed": seed, "shared_full_forwards": 2, "wall_seconds": time.perf_counter()-begin,
                            "train_physical": diag, "dev_physical": dev_diag})
        # Independent finite differences of the reduced real-arithmetic objective.
        _, grad = reduced(state, basis, parent, True, train["y"])
        fd = []
        for j in range(4):
            t1, t0 = parent.astype(float), parent.astype(float)
            t1[j] += 1e-3
            t0[j] -= 1e-3
            fd.append((reduced(state, basis, t1, True, train["y"])[0]-reduced(state, basis, t0, True, train["y"])[0])/(2e-3))
        gradient_error = float(np.max(abs(grad-np.asarray(fd))))
        if gradient_error > 2e-5:
            raise ArithmeticError(f"reduced gradient check failed: {gradient_error}")
        # Every random direction remains visible; train CE selects one once.
        random_start = time.perf_counter()
        rng = np.random.Generator(np.random.PCG64(2026112810+seed))
        random_rows, random_thetas = [], []
        for index in range(64):
            direction = rng.normal(size=4)
            theta = represented(parent.astype(float)+radius*direction/np.linalg.norm(direction), parent, radius)
            _, scores = reduced(state, basis, theta)
            random_rows.append({"index": index, "theta": theta.tolist(), **metric(scores, train["y"])})
            random_thetas.append(theta)
        chosen = min(range(64), key=lambda i: (random_rows[i]["ce"], i))
        random_cost = time.perf_counter()-random_start
        # Ordinary chain-rule training on exactly the same four parameters.
        bp_start = time.perf_counter()
        theta, moment, variance = parent.copy(), np.zeros(4), np.zeros(4)
        curve = []
        for step in range(1, 65):
            loss, g = reduced(state, basis, theta, True, train["y"])
            moment = .9*moment+.1*g
            variance = .999*variance+.001*g*g
            proposal = theta.astype(float)-.03*(moment/(1-.9**step))/(np.sqrt(variance/(1-.999**step))+1e-8)
            theta = represented(proposal, parent, radius)
            curve.append({"step": step, "loss_before_step": loss, "theta_after_step": theta.tolist(), "gradient_norm": float(np.linalg.norm(g))})
        bp_cost = time.perf_counter()-bp_start
        arms = {"KEEP": parent, "DIRECT_SIGN": direct[seed],
                "REVERSE_SIGN": -direct[seed], "RANDOM64": random_thetas[chosen], "BP64": theta}
        selected[seed] = arms
        save(out / f"selection{seed}.json", {"gradient_max_abs_error": gradient_error, "radius": radius,
             "random_rows": random_rows, "selected_random": chosen, "bp_curve": curve,
             "random_wall_seconds": random_cost, "bp_wall_seconds": bp_cost,
             "candidate_price_weights": {name: value.tolist() for name, value in arms.items()}})
        objective_counts.append({"seed": seed, "random_objective_calls": 64, "bp_objective_and_backward_calls": 64,
                                 "gradient_validation_objective_calls": 9, "gradient_validation_backward_calls": 9})
        for name, candidate in arms.items():
            _, scores = reduced(state, dev_basis, candidate)
            records.append({"seed": seed, "arm": name, "phase": "DEV_DESCRIPTIVE", **metric(scores, dev["y"])})
    sealed = {str(s): {k: {"sha256": sha(v.astype("<f4").tobytes()), "values": v.tolist()} for k, v in a.items()} for s, a in selected.items()}
    save(out / "CANDIDATES_SEALED_BEFORE_TEST.json", {"protocol_sha256": PROTOCOL_SHA, "candidates": sealed,
                                                    "test_generated": False, "selection_rule": "fixed direct/BP; random TRAIN CE only"})
    test = task(2026112803, 40, 3.)
    np.savez_compressed(out / "new_test_inputs.npz", x=test["x"], y=test["y"])
    retain = historical("retain")
    native_calls = 0
    equivalence_rows, retention_rows = [], []
    for seed in SEEDS:
        state = states[seed]
        work = out / str(seed)
        work.mkdir()
        parent_theta = state["body.input_mark.weight"][:, PRICE]
        parent_path, profile = canonical(state, seed, original.CHECKPOINT_SHA[seed], work, encode(test["x"], test["base"], test["y"]))
        _, _, _, test_basis = BridgeReplay(state).forward(test["x"], test["base"])
        _, _, _, retain_basis = BridgeReplay(state).forward(retain["x"], retain["base"])
        python_forwards += 2
        for name, candidate in selected[seed].items():
            observed, candidate_sha = native_run(native, work, f"test_{name}", parent_path, profile, candidate, test, "late-bridge")
            native_calls += observed["full_model_forward_calls"]
            predicted_features, predicted_scores = reduced(state, test_basis, candidate)
            feature_error = float(abs(np.asarray(observed["features"]).reshape(-1, 2, 20)-predicted_features).max())
            score_error = float(abs(np.asarray(observed["scores"]).reshape(-1, 2)-predicted_scores).max())
            row = {"seed": seed, "arm": name, "feature_error": feature_error, "score_error": score_error,
                   "physical_residuals": observed["physical_residuals"], "candidate_sha256": candidate_sha}
            equivalence_rows.append(row)
            if max(feature_error, score_error) > 2e-6 or max(observed["physical_residuals"]) > 2e-9:
                raise ArithmeticError(row)
            records.append({"seed": seed, "arm": name, "phase": "FRESH_SYNTHETIC_TEST", **metric(np.asarray(observed["scores"]).reshape(-1, 2), test["y"])})
        for name in ("KEEP", "DIRECT_SIGN"):
            observed, _ = native_run(native, work, f"oldgraph_test_{name}", parent_path, profile, selected[seed][name], test, "mark-control")
            native_calls += observed["full_model_forward_calls"]
            records.append({"seed": seed, "arm": "ORIGINAL_GRAPH_"+name, "phase": "FRESH_SYNTHETIC_TEST", **metric(np.asarray(observed["scores"]).reshape(-1, 2), test["y"])})
        normal = {}
        for name, candidate, mode in (("PARENT", parent_theta, "mark-control"),
                 ("UNCONDITIONAL_DIRECT", selected[seed]["DIRECT_SIGN"], "late-bridge"),
                 ("SCOPED_DIRECT", selected[seed]["DIRECT_SIGN"], "mark-control"),
                 ("UNCONDITIONAL_BP", selected[seed]["BP64"], "late-bridge"),
                 ("UNCONDITIONAL_RANDOM", selected[seed]["RANDOM64"], "late-bridge")):
            observed, _ = native_run(native, work, f"retain_{name}", parent_path, profile, candidate, retain, mode)
            native_calls += observed["full_model_forward_calls"]
            scores = np.asarray(observed["scores"], dtype=np.float32).reshape(-1, 2)
            features = np.asarray(observed["features"], dtype=np.float32)
            met = metric(scores, retain["y"])
            normal[name] = {"scores": scores, "features": features, "metrics": met}
            if name != "PARENT":
                original_normal = normal["PARENT"]
                old_correct = original_normal["scores"].argmax(1) == retain["y"]
                lost = int((old_correct & (scores.argmax(1) != retain["y"])).sum())
                identical = scores.tobytes() == original_normal["scores"].tobytes() and features.tobytes() == original_normal["features"].tobytes()
                retention_rows.append({"seed": seed, "arm": name, "lost_correct": lost,
                   "score_feature_bytes_identical": identical, "parent": original_normal["metrics"], "candidate": met,
                   "retention_pass": lost == 0 and met["ce"] <= original_normal["metrics"]["ce"]+1e-6})
        elapsed_child = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_total = (time.process_time()-cpu_start+elapsed_child.ru_utime+elapsed_child.ru_stime
                     -child_start.ru_utime-child_start.ru_stime)
        if cpu_total > 300:
            raise TimeoutError("pre-registered complete experiment CPU cap")
    end_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"protocol_sha256": PROTOCOL_SHA, "records": records, "programs": program_rows,
       "native_independent_equivalence": equivalence_rows, "retention": retention_rows,
       "common_costs": common_cost, "objective_counts": objective_counts,
       "full_python_forwards": python_forwards, "full_native_forwards": native_calls,
       "wall_seconds": time.perf_counter()-start, "python_cpu_seconds": time.process_time()-cpu_start,
       "native_cpu_seconds": end_child.ru_utime+end_child.ru_stime-child_start.ru_utime-child_start.ru_stime,
       "actual_parent_parameters": 330, "editable_parameters": 4,
       "new_learned_parameters": 0, "graph_effective_connectivity_changed": True,
       "task_scoped_mode_is_explicit": True, "normal_data_are_historical": True,
       "deployment": "none", "claims": "controlled late-quote mechanism only"}
    save(out / "RESULT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("records", "programs", "native_independent_equivalence", "retention", "common_costs", "objective_counts")}))


if __name__ == "__main__":
    run()
