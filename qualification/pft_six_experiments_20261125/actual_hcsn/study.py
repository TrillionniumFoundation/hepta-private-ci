#!/usr/bin/env python3
"""New SmallHCSN integration study; never resumes or qualifies an old test ledger.
Pinned real finite-population kernels; N16 explicitly extended under a new source
identity. Fixed-parent value/risk versus ordinary tanh readout-feature control.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
sys.path.insert(0, str(BASE / "src"))
DEPENDENCY_ERROR = None
try:
    import numpy as np
    import torch
    from qualification.hcsn_smallnet_20261124.model import ModelConfig, PopulationState, SmallHCSN
except (ImportError, OSError) as exc:
    DEPENDENCY_ERROR = repr(exc)
FIELDS = ("density", "boundary", "drift", "cost", "message")
SOURCES = {"train": (91000, 91001, 91002, 91003), "dev": (92000, 92001),
           "test": (93000, 93001, 93002, 93003)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def validate_sources():
    provenance = json.loads((BASE / "source_provenance.json").read_text())
    for name, expected in provenance["research_source_hashes"].items():
        if sha(BASE / "src" / name) != expected:
            raise ValueError("Research source identity mismatch: " + name)
    imported = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
                if (name == "qualification" or name.startswith("qualification.")) and getattr(module, "__file__", None)}
    if any(not Path(path).is_relative_to((BASE / "src").resolve()) for path in imported.values()):
        raise ValueError("Live qualification package escaped isolated research source root")
    return provenance, imported


def task(split, count, seed):
    xs, ys, margins, late, ids = [], [], [], [], []
    for source in SOURCES[split]:
        rng = np.random.default_rng(20261125 + seed * 10007 + source * 1009)
        a, b = rng.uniform(-1, 1, (2, count))
        gain, noise, correlation = rng.uniform(.85, 1.15), rng.uniform(.08, .35), rng.uniform(-.5, .7)
        arrival = rng.integers(4, 7, count)
        x = np.zeros((12, count, 6))
        x[0, :, 0], x[0, :, 2] = gain * a, 1
        x[arrival, np.arange(count), 1], x[arrival, np.arange(count), 3] = gain * b, 1
        x[:, :, 4] = np.arange(12)[:, None] / 11
        for t in range(12):
            x[t, :, 5] = noise * rng.normal(size=count)
            if t:
                x[t, :, 5] += correlation * x[t - 1, :, 5]
        xs.append(x); ys.append((a + b > 0).astype(np.int64))
        margins.append(rng.uniform(.45, .85, count)); late.append(arrival)
        ids.extend(f"pft-six-new:{seed}:{source}:{i}" for i in range(count))
    return {"x": torch.tensor(np.concatenate(xs, 1), dtype=torch.float32),
            "y": torch.tensor(np.concatenate(ys)), "margin": torch.tensor(np.concatenate(margins)),
            "late": torch.tensor(np.concatenate(late)), "ids": ids}


def task_hash(data):
    h = hashlib.sha256()
    for key in ("x", "y", "margin", "late"):
        a = data[key].numpy()
        h.update(str((a.dtype.str, a.shape)).encode()); h.update(a.tobytes())
    h.update("\n".join(data["ids"]).encode())
    return h.hexdigest()


def state_dict(state):
    return {**{k: getattr(state, k).detach().clone() for k in FIELDS}, "step": state.step}


def state_error(a, b):
    return {k: float((a[k].double() - b[k].double()).abs().max()) for k in FIELDS}


def extract(model, data, batch=8):
    all_logits, all_features, states = [], [], []
    mass, mark, min_p = 0., 0., 1.
    start = time.perf_counter()
    with torch.no_grad():
        for i in range(0, len(data["y"]), batch):
            x = data["x"][:, i:i + batch].to(model.input_drive.weight)
            state = model.initial_state(x.shape[1], data["margin"][i:i + batch, None])
            logits, features, state = model(x, state=state, return_features=True)
            p, m = state.density[..., 0, :], state.density[..., 1, :]
            mass = max(mass, model.last_diagnostics["mass_error"])
            mark = max(mark, float((m.abs() - p).max()))
            min_p = min(min_p, float(p.min()))
            states.append(state_dict(state)); all_logits.append(logits); all_features.append(features)
    return torch.cat(all_logits, 1), torch.cat(all_features, 1), states, {
        "wall_s": time.perf_counter() - start, "max_probability_mass_error": mass,
        "max_signed_mark_excess": mark, "min_probability": min_p,
        "population_state_shape_per_batch": list(states[0]["density"].shape),
        "complete_state_fields": list(FIELDS), "absolute_final_step": states[0]["step"]}


def metrics(logits, data):
    probs = logits.double().softmax(-1)
    rows = torch.arange(len(data["y"]))
    target = torch.nn.functional.one_hot(data["y"], 2).double()
    return {"accuracy": float((probs[-1].argmax(-1) == data["y"]).double().mean()),
            "pre_late_accuracy": float((probs[data["late"] - 1, rows].argmax(-1) == data["y"]).double().mean()),
            "brier": float(((probs[-1] - target) ** 2).sum(-1).mean()), "n": len(rows)}


def bootstrap16(data, seed, steps, budget):
    torch.manual_seed(seed + 1600)
    model = SmallHCSN(ModelConfig(neurons=16, precision="mixed", backend="dense"))
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=.01)
    gen = torch.Generator().manual_seed(seed + 1601)
    start, cpu, losses = time.perf_counter(), time.process_time(), []
    for _ in range(steps):
        if time.process_time() - cpu >= budget:
            break
        idx = torch.randperm(len(data["y"]), generator=gen)[:8]
        opt.zero_grad(set_to_none=True)
        logits = model(data["x"][:, idx], state=model.initial_state(len(idx), data["margin"][idx, None]))
        y = data["y"][idx]
        loss = .8 * torch.nn.functional.cross_entropy(logits[-1], y)
        loss += .2 * torch.nn.functional.cross_entropy(logits.flatten(0, 1), y.repeat(len(logits)))
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 3.); opt.step()
        losses.append(float(loss.detach()))
    return model, {"kind": "new_N16_parent_research_bootstrap", "updates": len(losses), "losses": losses,
                   "wall_s": time.perf_counter() - start, "cpu_s": time.process_time() - cpu,
                   "requested_steps": steps, "cpu_budget_s": budget, "qualified_as_converged": False}


def replay_child(source, output):
    validate_sources()
    obj = torch.load(source, map_location="cpu", weights_only=True)
    config = ModelConfig(**obj["config"])
    model = SmallHCSN(config); model.load_state_dict(obj["weights"])
    saved = obj["prefix_state"]
    state = PopulationState(*(saved[k] for k in FIELDS), saved["step"], config)
    with torch.no_grad():
        logits, features, state = model(obj["tail"], state=state, return_features=True)
    torch.save({"logits": logits, "features": features, "state": state_dict(state)}, output)


def replay(model, data, out):
    x = data["x"][:, :2].to(model.input_drive.weight)
    margin = data["margin"][:2, None]
    with torch.no_grad():
        logits, features, final = model(x, state=model.initial_state(2, margin), return_features=True)
        _, _, prefix = model(x[:6], state=model.initial_state(2, margin), return_features=True)
    payload, resumed = out / "replay_input.pt", out / "replay_output.pt"
    torch.save({"config": asdict(model.config), "weights": model.state_dict(),
                "prefix_state": state_dict(prefix), "tail": x[6:]}, payload)
    start = time.perf_counter()
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "replay", "--input", str(payload),
                    "--output", str(resumed)], check=True, timeout=120, capture_output=True, text=True)
    loaded = torch.load(resumed, map_location="cpu", weights_only=True)
    errors = state_error(state_dict(final), loaded["state"])
    errors["logits"] = float((logits[6:] - loaded["logits"]).abs().max())
    errors["features"] = float((features[6:] - loaded["features"]).abs().max())
    return {"scope": "fresh_Python_process_full_state_continuation", "max_errors": errors,
            "step_equal": final.step == loaded["state"]["step"], "wall_s": time.perf_counter() - start,
            "input_sha256": sha(payload), "output_sha256": sha(resumed),
            "pass": max(errors.values()) <= 1e-10 and final.step == loaded["state"]["step"]}


def run(args):
    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError("New study requires a fresh output directory")
    out.mkdir(parents=True)
    if DEPENDENCY_ERROR:
        dump(out / "RESULT.json", {"status": "BLOCKED_MISSING_DEPENDENCY", "error": DEPENDENCY_ERROR})
        return 2
    torch.set_num_threads(1)
    start = time.perf_counter()
    provenance, imported = validate_sources()
    protocol = {"experiment": "PFT6-ACTUAL-SMALLHCSN-NEW-SOURCES-v1", "registered_utc": utc(),
                "origin_commit": provenance["origin_commit"], "source_provenance_sha256": sha(BASE / "source_provenance.json"),
                "study_sha256": sha(__file__), "arguments": vars(args), "source_ids": SOURCES,
                "imported_qualification_module_paths": imported,
                "runtime": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__, "threads": 1, "device": "cpu"},
                "pre_late_Bayes_accuracy": .75, "post_information_Bayes_accuracy": 1.,
                "old_qualification_transferred": False, "test_labels_created_before_global_freeze": False,
                "scope": "real_SmallHCSN_new_synthetic_tasks_fixed_parent_readout_and_replay",
                "ordinary_control": "same_population_dynamics; only value/risk replaced by tanh(drive)/tanh(raw_mark)",
                "old_parent_training_cost_included_in_new_timings": False,
                "cross_width_budget_matched": False, "full_network_retraining_gate_claimed": False}
    dump(out / "PROTOCOL.json", protocol)
    train = task("train", args.train_per_source, args.data_seed)
    dev = task("dev", args.dev_per_source, args.data_seed)
    candidates, parent_records, failures = [], [], []
    for width in [int(w) for w in args.widths.split(",")]:
        case = out / f"n{width}"; case.mkdir()
        try:
            if width == 16:
                parent, info = bootstrap16(train, args.data_seed, args.bootstrap_steps, args.bootstrap_cpu_seconds)
                source = case / "new_parent.pt"
                torch.save({"config": asdict(parent.config), "selected_model": parent.state_dict()}, source)
            else:
                source = BASE / f"parents/training/n{width}-qvi_full-s1101/checkpoint.pt"
                expected = next(r["sha256"] for r in provenance["extracted_files"] if r["path"] == str(source.relative_to(BASE)))
                if sha(source) != expected:
                    raise ValueError("Archived parent differs from pinned extraction manifest")
                saved = torch.load(source, map_location="cpu", weights_only=True)
                parent = SmallHCSN(ModelConfig(**saved["config"])); parent.load_state_dict(saved["selected_model"])
                info = {"kind": "archived_trained_qvi_full_parent", "seed": 1101, "selected_step": saved.get("best_step")}
            info.update(width=width, parent_sha256=sha(source), config=asdict(parent.config),
                        parameter_count=sum(p.numel() for p in parent.parameters()),
                        trainable_parameters=sum(p.numel() for p in parent.parameters() if p.requires_grad))
            info["cold_replay"] = replay(parent, train, case)
            parent_records.append(info)
            base_states = None
            for bank in ("value_risk", "tanh"):
                model = SmallHCSN(replace(parent.config, feature_bank=bank)); model.load_state_dict(parent.state_dict())
                _, features, states, timing = extract(model, train)
                if base_states is None:
                    base_states = states
                same_state = max(max(state_error(a, b).values()) for a, b in zip(base_states, states))
                solve_start = time.perf_counter()
                x = features[-1].double().numpy(); x = np.c_[x, np.ones(len(x))]
                target = 2 * np.eye(2)[train["y"].numpy()] - 1
                regularizer = np.eye(x.shape[1]); regularizer[-1, -1] = 0
                coefficient = np.linalg.solve(x.T @ x / (len(x) * 2) + args.ridge * regularizer,
                                              x.T @ target / (len(x) * 2))
                with torch.no_grad():
                    model.readout.weight.copy_(torch.from_numpy(coefficient[:-1].T).to(model.readout.weight))
                    model.readout.bias.copy_(torch.from_numpy(coefficient[-1]).to(model.readout.bias))
                solve_s = time.perf_counter() - solve_start
                dev_logits, _, _, dev_time = extract(model, dev)
                path = case / f"{bank}_candidate.pt"
                torch.save({"config": asdict(model.config), "weights": model.state_dict()}, path)
                candidates.append({"width": width, "bank": bank, "path": str(path), "sha256": sha(path),
                    "feature_dim": int(features.shape[-1]), "train_features_timing": timing, "solve_s": solve_s,
                    "dev_metrics": metrics(dev_logits, dev), "dev_timing": dev_time,
                    "max_population_state_difference_to_value_risk": same_state})
        except Exception as exc:
            failures.append({"width": width, "stage": "parent_or_candidate", "error": repr(exc)})
    freeze = {"frozen_utc": utc(), "protocol_sha256": sha(out / "PROTOCOL.json"),
              "train_data_sha256": task_hash(train), "dev_data_sha256": task_hash(dev),
              "test_source_ids": SOURCES["test"], "test_generation_seed": args.data_seed,
              "candidates": candidates, "parents": parent_records, "failures": failures}
    dump(out / "GLOBAL_CANDIDATE_FREEZE.json", freeze)
    for candidate in candidates:
        if sha(candidate["path"]) != candidate["sha256"]:
            raise ValueError("Candidate changed before test labels opened")
    test_opened = utc()
    test = task("test", args.test_per_source, args.data_seed)
    results = []
    for candidate in candidates:
        try:
            if sha(candidate["path"]) != candidate["sha256"]:
                raise ValueError("Candidate changed after global freeze")
            saved = torch.load(candidate["path"], map_location="cpu", weights_only=True)
            model = SmallHCSN(ModelConfig(**saved["config"])); model.load_state_dict(saved["weights"])
            logits, _, _, timing = extract(model, test)
            score = metrics(logits, test); score["final_minus_pre_late_accuracy"] = score["accuracy"] - score["pre_late_accuracy"]
            results.append({**candidate, "test": score, "test_timing": timing, "status": "MEASURED"})
        except Exception as exc:
            results.append({**candidate, "status": "FAILED", "error": repr(exc)})
    complete = len(results) == 2 * len(args.widths.split(",")) and all(r["status"] == "MEASURED" for r in results)
    result = {"experiment": protocol["experiment"], "status": "COMPLETED_MEASUREMENTS" if complete else "PARTIAL_OR_FAILED",
              "global_freeze_sha256": sha(out / "GLOBAL_CANDIDATE_FREEZE.json"), "candidate_frozen_utc": freeze["frozen_utc"],
              "test_labels_opened_utc": test_opened, "test_data_sha256": task_hash(test), "parents": parent_records,
              "results": results, "failures": failures, "wall_s": time.perf_counter() - start,
              "gates": {"real_population_kernel_executed": bool(candidates), "all_requested_cases_completed": complete,
                        "cold_replays_passed": bool(parent_records) and all(r["cold_replay"]["pass"] for r in parent_records),
                        "feature_controls_same_final_population_states": bool(candidates) and all(r["max_population_state_difference_to_value_risk"] == 0 for r in candidates),
                        "real_cross_user": "BLOCKED_SYNTHETIC_DATA", "learned_circuit_superiority": "NOT_TESTED",
                        "N16_formal_qualification": "NOT_INHERITED_NEW_RESEARCH_EXTENSION"}}
    dump(out / "RESULT.json", result)
    print(json.dumps({"status": result["status"], "gates": result["gates"], "failures": failures,
                      "rows": [{"width": r["width"], "bank": r["bank"], "status": r["status"], "test": r.get("test")} for r in results]}))
    return 0 if result["gates"]["all_requested_cases_completed"] else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run"); r.add_argument("--out", required=True)
    r.add_argument("--widths", default="8,16,32,64"); r.add_argument("--data-seed", type=int, default=731)
    r.add_argument("--train-per-source", type=int, default=16); r.add_argument("--dev-per-source", type=int, default=16)
    r.add_argument("--test-per-source", type=int, default=24); r.add_argument("--ridge", type=float, default=.01)
    r.add_argument("--bootstrap-steps", type=int, default=24); r.add_argument("--bootstrap-cpu-seconds", type=float, default=30.)
    c = sub.add_parser("replay"); c.add_argument("--input", required=True); c.add_argument("--output", required=True)
    args = p.parse_args()
    if args.command == "replay":
        if DEPENDENCY_ERROR:
            raise RuntimeError(DEPENDENCY_ERROR)
        torch.set_num_threads(1); replay_child(args.input, args.output)
    else:
        raise SystemExit(run(args))


if __name__ == "__main__":
    main()
