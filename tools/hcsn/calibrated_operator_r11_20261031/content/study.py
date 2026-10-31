"""Registered causal content training, then fresh heldout generation.

All arms receive identical RAW synthetic symbols, current elapsed time, and
observed marker/query bits. This is not a public-media or native Bellman study.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

from models import Adam, KINDS, Model, gates

HERE = Path(__file__).resolve().parent
PROTOCOL = dict(schema="hcsn.r11.causal.content.v1", seeds=[111031, 111037, 111043, 111049, 111057],
    tasks=["marked_memory", "noisy_evidence"], arms=list(KINDS), hidden_width=12,
    input_fields=["symbol_0", "symbol_1", "symbol_2", "symbol_3", "observed_marker", "evidence_task", "observed_query", "log_dt"],
    data_counts=dict(train=512, validation=256, test=768, ood_long=768, ood_shift=768),
    train_length=24, long_length=72, batch_size=32, updates=320, learning_rate=.003,
    selection_updates=[80, 160, 240, 320], objective="CE at all already-observed target prefixes; no auxiliary posterior or future input",
    selection="minimum validation final CE; earliest on ties; then validation-only scalar temperature and STOP threshold",
    thresholds=[.60, .70, .80, .90, .95, .99, 1.01], minimum_reads=2,
    read_price=.005, elapsed_price=.001, cpu_price_per_second=.001, amortization_queries=10000,
    heldout_creation="test/OOD RNG and arrays opened only after every selected model/calibration is hashed in FREEZE.json",
    statistics="paired bootstrap of seed clusters and within-seed episodes, 2000 draws; primary utility contrasts analytic_dual vs four controls, two tasks, three conditions; 24 one-sided familywise lower bounds",
    scope="synthetic raw-symbol causal content tasks; operator-gated recurrent models, not full HX/regenerative neuron, native two-job Bellman or real multimodal confirmation")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(obj, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def generate(task, split, seed, out):
    namespaces = dict(train=0, validation=1, test=2, ood_long=3, ood_shift=4)
    namespace = seed*1000 + namespaces[split]*100 + PROTOCOL["tasks"].index(task)
    rng = np.random.default_rng(namespace)
    n = PROTOCOL["data_counts"][split]
    length = PROTOCOL["long_length"] if split == "ood_long" else PROTOCOL["train_length"]
    y = rng.integers(0, 2, n)
    symbols = rng.integers(0, 4, (n, length))
    marker = rng.integers(0, 4, n)
    if task == "noisy_evidence":
        low, high = (.53, .72) if split == "ood_shift" else (.62, .90)
        reliability = rng.uniform(low, high, (n, 1))
        symbols = np.where(rng.random((n, length)) < reliability, y[:, None], 1-y[:, None])
        marker[:] = 0
    else:
        if split == "ood_shift":
            symbols = np.where(rng.random((n, length)) < .7, 1-y[:, None], symbols)
        symbols[np.arange(n), marker] = y
    choices = [.1, .3, 1.5, 2.5] if split == "ood_shift" else [.2, .4, .8, 1.2, 1.6]
    dt = rng.choice(choices, (n, length))
    raw = dict(symbols=symbols.astype(np.int8), dt=dt, marker=marker.astype(np.int8), y=y.astype(np.int8))
    path = out / f"{task}_{split}_seed{seed}.npz"
    np.savez_compressed(path, **raw)
    x = np.zeros((n, length, 8)); x[:, :, :4] = np.eye(4)[symbols]
    x[np.arange(n), marker, 4] = 1.
    x[:, :, 5] = task == "noisy_evidence"; x[:, -1, 6] = 1.; x[:, :, 7] = np.log(dt)
    mask = (np.arange(length)[None] >= marker[:, None]).astype(float)
    return dict(x=x, dt=dt, y=y, mask=mask, file=path.name, sha256=digest(path), namespace=namespace)


def probability(logits, temperature=1.):
    scaled = logits/temperature
    return np.exp(scaled-logsumexp(scaled, axis=-1, keepdims=True))


def scores(p, y):
    losses = -np.log(np.maximum(p[np.arange(len(y)), y], 1e-300))
    correct = (p.argmax(1) == y).astype(float)
    brier = np.sum((p-np.eye(2)[y])**2, axis=1)
    confidence = p.max(1); ece = 0.
    for lo, hi in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:]):
        select = (confidence >= lo) & (confidence <= hi if hi == 1 else confidence < hi)
        if select.any():
            ece += float(select.mean()*abs(correct[select].mean()-confidence[select].mean()))
    return dict(accuracy=float(correct.mean()), nll=float(losses.mean()), brier=float(brier.mean()), ece=ece), dict(correct=correct, nll=losses, brier=brier)


def stop_indices(p, task, threshold):
    eligible = p.max(2) >= threshold
    eligible[:, :PROTOCOL["minimum_reads"]-1] = False
    if task == "marked_memory":
        eligible[:] = False
    eligible[:, -1] = True
    return np.argmax(eligible, axis=1)


def utility(p, dt, y, end):
    rows = np.arange(len(y)); selected = p[rows, end]
    elapsed = np.cumsum(dt, axis=1)[rows, end]
    reads = end+1
    correct = selected.argmax(1) == y
    raw = 2*correct.astype(float)-1 - PROTOCOL["read_price"]*reads - PROTOCOL["elapsed_price"]*elapsed
    return raw


def stream(model, x, dt, task, temperature, threshold, intervention=None):
    """Only active rows fetch their CURRENT frame; no labels or future statistics."""
    n, length = x.shape[:2]
    active = np.ones(n, bool); h = np.zeros((n, model.width))
    result = np.zeros((n, 2)); end = np.zeros(n, int); channels = np.zeros((n, 2))
    cpu, wall = time.process_time(), time.perf_counter(); frames = 0
    for tick in range(length):
        ids = np.flatnonzero(active)
        if not len(ids):
            break
        # x is a harness-owned backing array. Only this slice enters Model.step.
        logits, state, _, (up, down) = model.step(x[ids, tick], dt[ids, tick], h[ids], intervention=intervention)
        frames += len(ids); h[ids] = state
        p = probability(logits, temperature)
        stop = (p.max(1) >= threshold) & (tick+1 >= PROTOCOL["minimum_reads"])
        if task == "marked_memory":
            stop[:] = False
        if tick == length-1:
            stop[:] = True
        done = ids[stop]; result[done] = p[stop]; end[done] = tick
        channels[done] = np.column_stack((up.mean(1), down.mean(1)))[stop]
        active[done] = False
    return result, end, channels, dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                                     frames_read=frames, labels_supplied_to_model=False, unread_frames_processed=0)


def checks(out):
    rng = np.random.default_rng(68321)
    x = rng.normal(0, .2, (3, 6, 8)); dt = rng.choice([.2, .8, 1.6], (3, 6))
    y = np.array([0, 1, 0]); mask = np.ones((3, 6)); results = {}
    for kind in KINDS:
        model = Model(kind, seed=940)
        loss, grad = model.loss(x, dt, y, mask)
        errors = []
        for _ in range(12):
            direction = {k: rng.normal(size=v.shape) for k, v in model.p.items()}
            norm = np.sqrt(sum(np.sum(v*v) for v in direction.values()))
            direction = {k: v/norm for k, v in direction.items()}
            base = {k: v.copy() for k, v in model.p.items()}
            analytic = sum(float(np.sum(grad[k]*v)) for k, v in direction.items())
            samples = []
            for sign in [1, -1]:
                model.p = {k: base[k]+sign*1e-5*v for k, v in direction.items()}
                samples.append(model.loss(x, dt, y, mask, False))
            model.p = base
            errors.append(abs(analytic-(samples[0]-samples[1])/2e-5))
        prefix = model.forward(x, dt)[0][:, :3]
        changed = x.copy(); changed[:, 3:] += 50
        error = float(np.max(np.abs(prefix-model.forward(changed, dt)[0][:, :3])))
        results[kind] = dict(loss=loss, max_directional_gradient_error=max(errors), future_mutation_prefix_error=error,
                            parameter_count=model.parameters, nonzero_gradient_blocks={k: bool(np.any(v)) for k, v in grad.items()})
    zeros = np.zeros((3, 5)); elapsed = np.array([.2, .8, 1.6])[:, None]
    exact = gates("analytic_dual", zeros, zeros, elapsed, True)
    approx = gates("matched_slope", zeros, zeros, elapsed, True)
    match_error = max(float(np.max(abs(a-b))) for a, b in zip([exact[0], exact[1], *exact[2]], [approx[0], approx[1], *approx[2]]))
    passed = all(r["max_directional_gradient_error"] < 1e-7 and r["future_mutation_prefix_error"] == 0 for r in results.values()) and match_error < 1e-12
    save(out/"GRADIENT_CAUSALITY.json", dict(passed=passed, models=results, matched_value_and_partial_gradient_error=match_error))
    if not passed:
        raise ValueError("Numerical or causality check failed")


def train(task, seed, kind, data, val, folder):
    folder.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    model = Model(kind, PROTOCOL["hidden_width"], seed)
    initial = {k: v.copy() for k, v in model.p.items()}; optimizer = Adam(model, PROTOCOL["learning_rate"])
    rng = np.random.default_rng(seed+611); trace = []; validations = []; best = float("inf")
    train_cpu = train_wall = validation_cpu = 0.
    for update in range(1, PROTOCOL["updates"]+1):
        cpu, wall = time.process_time(), time.perf_counter()
        ids = rng.integers(0, len(data["y"]), PROTOCOL["batch_size"])
        loss, grad = model.loss(data["x"][ids], data["dt"][ids], data["y"][ids], data["mask"][ids])
        norm = optimizer.update(model, grad)
        train_cpu += time.process_time()-cpu; train_wall += time.perf_counter()-wall
        trace.append(dict(update=update, loss=loss, gradient_norm=norm, gradient_blocks={k: float(np.linalg.norm(v)) for k, v in grad.items()}))
        if update in PROTOCOL["selection_updates"]:
            cpu = time.process_time(); logits = model.forward(val["x"], val["dt"])[0]
            result = scores(probability(logits[:, -1]), val["y"])[0]
            validations.append(dict(update=update, **result)); validation_cpu += time.process_time()-cpu
            if result["nll"] < best:
                best, selected_update = result["nll"], update
                chosen = {k: v.copy() for k, v in model.p.items()}
    np.savez_compressed(folder/"final.npz", **model.p)
    model.p = chosen
    cpu = time.process_time(); logits = model.forward(val["x"], val["dt"])[0]
    temperature_trace = []
    def objective(log_temperature):
        value = scores(probability(logits[:, -1], np.exp(log_temperature)), val["y"])[0]["nll"]
        temperature_trace.append(dict(log_temperature=float(log_temperature), nll=value))
        return value
    fitted = minimize_scalar(objective, bounds=(-2, 2), method="bounded", options=dict(xatol=1e-5))
    temperature = float(np.exp(fitted.x)); p = probability(logits, temperature)
    candidates = []
    for threshold in PROTOCOL["thresholds"]:
        end = stop_indices(p, task, threshold)
        candidates.append(dict(threshold=threshold, utility=float(utility(p, val["dt"], val["y"], end).mean()), reads=float(np.mean(end+1))))
    threshold = max(candidates, key=lambda r: (r["utility"], -r["reads"], -r["threshold"]))["threshold"]
    calibration_cpu = time.process_time()-cpu
    np.savez_compressed(folder/"selected.npz", **chosen)
    save(folder/"TRAINING_TRACE.json", trace); save(folder/"VALIDATION.json", validations)
    save(folder/"CALIBRATION.json", dict(temperature=temperature, trace=temperature_trace, thresholds=candidates, selected_threshold=threshold, fit_success=bool(fitted.success)))
    info = dict(task=task, seed=seed, kind=kind, parameter_count=model.parameters, calibrated_parameters=1,
        selected_update=selected_update, updates=PROTOCOL["updates"], temperature=temperature, threshold=threshold,
        checkpoint_sha256=digest(folder/"selected.npz"), unseen_heldout=True,
        parameter_l2_changes={k: float(np.linalg.norm(chosen[k]-initial[k])) for k in chosen},
        training_cpu_seconds=train_cpu, training_wall_seconds=train_wall, validation_cpu_seconds=validation_cpu,
        calibration_selection_cpu_seconds=calibration_cpu, development_cpu_seconds=time.process_time()-start_cpu,
        development_wall_seconds=time.perf_counter()-start_wall,
        training_affine_flops=PROTOCOL["updates"]*PROTOCOL["batch_size"]*PROTOCOL["train_length"]*3*(2*(8+model.width)*3*model.width+2*model.width*2),
        flop_scope="forward/backward affine matrix estimate only; activations/special functions/Adam/memory traffic excluded; measured CPU includes them")
    save(folder/"MODEL_RECEIPT.json", info)
    return info


def evaluate(info, data, task, condition, folder):
    model = Model(info["kind"], PROTOCOL["hidden_width"], info["seed"])
    with np.load(folder/"selected.npz", allow_pickle=False) as arrays:
        model.p = dict(arrays)
    if digest(folder/"selected.npz") != info["checkpoint_sha256"]:
        raise ValueError("Frozen weights changed")
    cpu, wall = time.process_time(), time.perf_counter()
    logits = model.forward(data["x"], data["dt"])[0]
    all_p = probability(logits, info["temperature"])
    fixed_metrics, fixed_raw = scores(all_p[:, -1], data["y"])
    p, end, channels, runtime = stream(model, data["x"], data["dt"], task, info["temperature"], info["threshold"])
    expected = all_p[np.arange(len(end)), end]
    parity = float(np.max(np.abs(p-expected)))
    if parity > 1e-12:
        raise ValueError("Batch and executed causal stream disagree")
    dynamic_metrics, raw = scores(p, data["y"])
    elapsed = np.cumsum(data["dt"], 1)[np.arange(len(end)), end]
    task_utility = 2*raw["correct"]-1-PROTOCOL["read_price"]*(end+1)-PROTOCOL["elapsed_price"]*elapsed
    overhead = info["development_cpu_seconds"]/PROTOCOL["amortization_queries"] + runtime["cpu_seconds"]/len(end)
    net = task_utility-PROTOCOL["cpu_price_per_second"]*overhead
    record = dict(task=task, seed=info["seed"], kind=info["kind"], condition=condition,
        fixed_metrics=fixed_metrics, stream_metrics=dynamic_metrics, task_utility=float(task_utility.mean()),
        net_utility_declared_cpu_price=float(net.mean()), mean_reads=float(np.mean(end+1)), runtime=runtime,
        batch_stream_probability_error=parity, evaluation_cpu_seconds=time.process_time()-cpu,
        evaluation_wall_seconds=time.perf_counter()-wall)
    arrays = dict(y=data["y"], final_probability=all_p[:, -1], stream_probability=p, stop_index=end,
        utility=task_utility, net_utility=net, elapsed=elapsed, channels=channels, **fixed_raw)
    if info["kind"] == "analytic_dual":
        record["channel_interventions"] = {}
        for intervention in ("remove_up", "remove_down"):
            altered, altered_end, _, cost = stream(model, data["x"], data["dt"], task, info["temperature"], info["threshold"], intervention)
            record["channel_interventions"][intervention] = dict(
                changed_stop_episodes=int(np.sum(end != altered_end)), changed_predictions=int(np.sum(p.argmax(1) != altered.argmax(1))),
                metrics=scores(altered, data["y"])[0], runtime=cost, interpretation="post-training intervention; not evidence that retrained dual channels are necessary")
            arrays[intervention+"_probability"] = altered; arrays[intervention+"_stop_index"] = altered_end
    # Bounded chunks preserve actual per-episode results without giant blobs.
    for first in range(0, len(end), 256):
        np.savez_compressed(folder/f"{condition}_raw_{first//256:02d}.npz", **{k: v[first:first+256] for k, v in arrays.items()})
    save(folder/f"{condition}_RESULT.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    save(out/"PROTOCOL.json", PROTOCOL)
    save(out/"REGISTRATION.json", dict(time=now(), source={p: digest(HERE/p) for p in ["models.py", "study.py"]},
        protocol_sha256=digest(out/"PROTOCOL.json"), python=platform.python_version(), numpy=np.__version__, all_heldout_uncreated=True))
    checks(out); (out/"data").mkdir()
    infos, data_manifest = [], []
    for task in PROTOCOL["tasks"]:
        for seed in PROTOCOL["seeds"]:
            train_data = generate(task, "train", seed, out/"data")
            validation = generate(task, "validation", seed, out/"data")
            data_manifest += [{k: d[k] for k in ["file", "sha256", "namespace"]} for d in [train_data, validation]]
            for kind in KINDS:
                folder = out/"models"/f"{task}_{kind}_{seed}"
                info = train(task, seed, kind, train_data, validation, folder)
                infos.append(info)
                print(json.dumps(dict(phase="trained", task=task, kind=kind, seed=seed, selected=info["selected_update"], cpu=info["development_cpu_seconds"])), flush=True)
    save(out/"FREEZE.json", dict(time=now(), models=infos, development_data=data_manifest, heldout_generated=False,
        source={p: digest(HERE/p) for p in ["models.py", "study.py"]}, protocol_sha256=digest(out/"PROTOCOL.json")))
    results = []
    for task in PROTOCOL["tasks"]:
        for seed in PROTOCOL["seeds"]:
            for condition in ["test", "ood_long", "ood_shift"]:
                data = generate(task, condition, seed, out/"data")
                data_manifest.append({k: data[k] for k in ["file", "sha256", "namespace"]})
                for info in [v for v in infos if v["task"] == task and v["seed"] == seed]:
                    folder = out/"models"/f"{task}_{info['kind']}_{seed}"
                    results.append(evaluate(info, data, task, condition, folder))
                print(json.dumps(dict(phase="heldout", task=task, seed=seed, condition=condition)), flush=True)
    save(out/"RESULTS.json", dict(models=results, data=data_manifest, freeze_sha256=digest(out/"FREEZE.json"),
        completed_at=now(), total_process_cpu_seconds=time.process_time()-start_cpu,
        total_wall_seconds=time.perf_counter()-start_wall, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        energy_joules=None, gpu=False, scope=PROTOCOL["scope"]))


if __name__ == "__main__":
    main()
