"""Bounded, train/dev-only SmallHCSN fitting with complete cost and failure ledgers."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import traceback

from common import (ScaledReadout, data, data_hash, dump, extract, feature_statistics, fit_ridge, forward,
                    metrics, np, parameter_summary, ridge_logits, runtime, select, sha,
                    state_payload, torch, utc, validate_sources)
from optimized import make_model


def source_hashes():
    return {name: sha(Path(__file__).with_name(name)) for name in ("common.py", "optimized.py", "runner.py", "evaluate.py", "register.py")}


def case_name(case):
    return (f"n{case['width']}-s{case['seed']}-{case['bank']}-{case['message']}-"
            f"{case['connection']}-m{case['train_n']}-lr{case['physical_lr']:g}")


def take(batch, indices):
    result = select(batch, indices)
    idx = list(indices)
    result["ids"] = [batch["ids"][i] for i in idx]
    result["latent"] = batch["latent"][idx]
    return result


def nested_indices(total, count):
    if count % 4 or total % 4 or count > total:
        raise ValueError("Nested equal source quotas required")
    per = total // 4
    return [source * per + i for source in range(4) for i in range(count // 4)]


def tensor_digest(state, exclude_readout=False):
    h = hashlib.sha256()
    for name, value in sorted(state.items()):
        if exclude_readout and name.startswith("readout."):
            continue
        a = value.detach().numpy()
        h.update(name.encode()); h.update(str((a.dtype.str, a.shape)).encode()); h.update(a.tobytes())
    return h.hexdigest()


def fit_to_torch(fit):
    return {key: torch.from_numpy(value.copy()) if isinstance(value, np.ndarray) else value for key, value in fit.items()}


def fit_to_numpy(fit):
    return {key: value.numpy() if isinstance(value, torch.Tensor) else value for key, value in fit.items()}


def validate_protocol(protocol):
    if protocol["source_hashes"] != source_hashes():
        raise ValueError("Frozen experiment source changed")
    actual = runtime()
    if any(protocol["runtime"][key] != actual[key] for key in ("python", "numpy", "torch", "threads", "device")):
        raise ValueError("Frozen runtime changed")
    physical = validate_sources()
    for key in ("capsule_source_provenance_sha256", "research_source_hashes"):
        if physical[key] != protocol["physical_source"][key]:
            raise ValueError("Frozen physical source binding changed")


def fit_case(protocol, case, out, protocol_sha):
    out.mkdir(exist_ok=False)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    cost, history, baselines = {}, [], {}
    record = {"case": case, "protocol_sha256": protocol_sha, "started_utc": utc(), "test_read": False}
    dump(out / "STARTED.json", record)
    checkpoint, model, error, grad0 = None, None, None, {}
    updates, attempted, selected_step, train_cpu, train_wall = 0, 0, 0, 0., 0.
    terminal = "FAILED"
    phase = "setup"
    try:
        t = time.perf_counter()
        all_train = data("train", protocol["data"]["per_source_train"], protocol["data"]["seed"], protocol["phase"])
        dev = data("dev", protocol["data"]["per_source_dev"], protocol["data"]["seed"], protocol["phase"])
        train = take(all_train, nested_indices(len(all_train["y"]), case["train_n"]))
        model = make_model(case["width"], case["seed"], case["bank"], case["message"], case["connection"])
        initial_physical = state_payload(model)
        record.update(train_sha256=data_hash(train), dev_sha256=data_hash(dev),
                      initial_physical_sha256=tensor_digest(initial_physical, True))
        cost["data_and_model_setup_wall_s"] = time.perf_counter() - t
        phase = "initial_features"
        _, features, feature_time = extract(model, train)
        _, dev_features, initial_dev_time = extract(model, dev)
        cost["train_feature_propagation_wall_s"] = feature_time["wall_s"]
        cost["initial_dev_propagation_wall_s"] = initial_dev_time["wall_s"]
        x, xd = features[-1].numpy(), dev_features.numpy()
        t = time.perf_counter()
        record["initial_feature_statistics"] = feature_statistics(x, train["y"])
        cost["feature_diagnostics_wall_s"] = time.perf_counter() - t
        phase = "normalization_and_solve"
        t = time.perf_counter()
        fits = {}
        for key, scaled, penalty in (("raw_same_penalty", False, protocol["ridge"]),
                                     ("raw_old_penalty", False, .02),
                                     ("standardized", True, protocol["ridge"])):
            fit = fit_ridge(x, train["y"], penalty, scaled, protocol["scale_floor"])
            fits[key] = fit
            baselines[key] = {"train": metrics(ridge_logits(fit, x), train),
                              "dev": metrics(ridge_logits(fit, xd), dev), "solve_wall_s": fit["solve_s"]}
        cost["normalization_and_all_solve_wall_s"] = time.perf_counter() - t
        model.readout = ScaledReadout(fits["standardized"])
        initial_weights = state_payload(model)
        best_weights = initial_weights
        best = baselines["standardized"]["dev"]
        history.append({"step": 0, "dev": best, "train": baselines["standardized"]["train"],
                        "optimization_cpu_s": 0., "optimization_wall_s": 0.})
        optimizer = torch.optim.Adam([
            {"params": [p for name, p in model.named_parameters() if p.requires_grad and not name.startswith("readout.")],
             "lr": case["physical_lr"]},
            {"params": list(model.readout.parameters()), "lr": protocol["head_lr"]}])
        generator = torch.Generator().manual_seed(case["seed"] * 991 + case["width"])
        unique_ids = set()
        evaluated_last = 0
        phase = "optimization"
        for step in range(1, protocol["max_updates"] + 1):
            if train_cpu >= protocol["optimization_cpu_budget_s"] or train_wall >= protocol["optimization_wall_budget_s"]:
                break
            tick, cpu = time.perf_counter(), time.process_time()
            attempted += 1
            try:
                idx = torch.randperm(len(train["y"]), generator=generator)[:protocol["batch_size"]]
                unique_ids.update(train["ids"][int(i)] for i in idx)
                part = take(train, idx.tolist())
                optimizer.zero_grad(set_to_none=True)
                logits, _, _ = forward(model, part)
                loss = torch.nn.functional.cross_entropy(logits[-1], part["y"])
                loss.backward()
                if step == 1:
                    grad0 = {name: {"norm": float(p.grad.norm()), "max_abs": float(p.grad.abs().max())}
                             for name, p in model.named_parameters() if p.grad is not None}
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["gradient_clip"])
                if not bool(torch.isfinite(loss) & torch.isfinite(norm)):
                    raise FloatingPointError("Nonfinite loss or gradient")
                optimizer.step()
                updates = step
                loss_value = float(loss.detach())
            finally:
                train_cpu += time.process_time() - cpu
                train_wall += time.perf_counter() - tick
            must_evaluate = (step in protocol["development_steps"] or step == protocol["max_updates"]
                             or train_cpu >= protocol["optimization_cpu_budget_s"]
                             or train_wall >= protocol["optimization_wall_budget_s"])
            if must_evaluate:
                logits, _, dev_time = extract(model, dev)
                cost["development_selection_wall_s"] = cost.get("development_selection_wall_s", 0.) + dev_time["wall_s"]
                score = metrics(logits, dev)
                if score["cross_entropy"] < best["cross_entropy"] - 1e-12:
                    best_weights, best, selected_step = state_payload(model), score, step
                history.append({"step": step, "minibatch_loss": loss_value, "dev": score,
                                "optimization_cpu_s": train_cpu, "optimization_wall_s": train_wall,
                                "distinct_BP_training_ids": len(unique_ids), "BP_label_exposures": step * len(idx)})
                evaluated_last = step
                dump(out / "HISTORY.json", history)
        if updates and evaluated_last != updates:
            logits, _, dev_time = extract(model, dev)
            cost["development_selection_wall_s"] = cost.get("development_selection_wall_s", 0.) + dev_time["wall_s"]
            score = metrics(logits, dev)
            if score["cross_entropy"] < best["cross_entropy"] - 1e-12:
                best_weights, best, selected_step = state_payload(model), score, updates
            history.append({"step": updates, "dev": score, "optimization_cpu_s": train_cpu,
                            "optimization_wall_s": train_wall, "distinct_BP_training_ids": len(unique_ids)})
        terminal = "COMPLETED_MAX_UPDATES" if updates == protocol["max_updates"] else "CENSORED_BUDGET"
        selected_physical = tensor_digest(best_weights, True)
        parameter_deltas = {}
        for name, parameter in model.named_parameters():
            initial_value, selected_value = initial_weights[name], best_weights[name]
            parameter_deltas[name] = {"selected_changed_elements": int(torch.count_nonzero(selected_value != initial_value)),
                                     "last_changed_elements": int(torch.count_nonzero(parameter.detach() != initial_value)),
                                     "selected_l2_delta": float((selected_value - initial_value).norm())}
        record.update(parameters=parameter_summary(model), selected_step=selected_step,
                      parameter_deltas=parameter_deltas,
                      selected_updated_parameter_elements=sum(v["selected_changed_elements"] for v in parameter_deltas.values()),
                      last_updated_parameter_elements=sum(v["last_changed_elements"] for v in parameter_deltas.values()),
                      selected_dev=best, baseline_heads=baselines, initial_gradient=grad0,
                      selected_physical_sha256=selected_physical,
                      selected_physical_changed=selected_physical != record["initial_physical_sha256"],
                      unique_training_labels_used_including_ridge=len(train["y"]))
        phase = "serialize_and_readback"
        checkpoint = {"schema": "actual-hcsn-v2-candidate-v1", "protocol_sha256": protocol_sha, "case": case,
                      "config": asdict(model.config), "initial_weights": initial_weights,
                      "selected_weights": best_weights, "last_weights": state_payload(model),
                      "baseline_fits": {key: fit_to_torch(value) for key, value in fits.items()},
                      "selected_step": selected_step, "updates": updates, "status": terminal}
        t = time.perf_counter()
        torch.save(checkpoint, out / "candidate.pt")
        cost["serialize_wall_s"] = time.perf_counter() - t
        t = time.perf_counter()
        loaded = torch.load(out / "candidate.pt", map_location="cpu", weights_only=True)
        if tensor_digest(loaded["selected_weights"]) != tensor_digest(best_weights):
            raise ValueError("Cold file readback differs")
        cost["file_deserialize_and_verify_wall_s"] = time.perf_counter() - t
        model.load_state_dict(loaded["selected_weights"])
        t = time.perf_counter()
        _, _, state = forward(model, take(train, list(range(min(protocol["batch_size"], len(train["y"]))))))
        cost["postload_state_validation_wall_s"] = time.perf_counter() - t
        record.update(state_tensor_bytes=sum(getattr(state, key).numel() * getattr(state, key).element_size()
                                            for key in ("density", "boundary", "drift", "cost", "message")),
                      state_batch=min(protocol["batch_size"], len(train["y"])),
                      state_fields=["density", "boundary", "drift", "cost", "message", "step", "config"],
                      candidate_sha256=sha(out / "candidate.pt"), candidate_bytes=(out / "candidate.pt").stat().st_size)
    except Exception as exc:
        terminal = "FAILED"
        error = {"stage": phase, "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    cost.update(optimization_wall_s=train_wall, optimization_cpu_s=train_cpu,
                total_case_wall_s=time.perf_counter() - start_wall, total_case_cpu_s=time.process_time() - start_cpu)
    record.update(status=terminal, error=error, updates=updates, attempted_updates=attempted, selected_step=selected_step,
                  optimization_cpu_budget_s=protocol["optimization_cpu_budget_s"],
                  optimization_wall_budget_s=protocol["optimization_wall_budget_s"],
                  optimization_cpu_overrun_s=max(0., train_cpu - protocol["optimization_cpu_budget_s"]),
                  optimization_wall_overrun_s=max(0., train_wall - protocol["optimization_wall_budget_s"]),
                  cost=cost, initial_gradient=grad0, completed_utc=utc())
    dump(out / "HISTORY.json", history)
    record["history_sha256"] = sha(out / "HISTORY.json")
    dump(out / "RESULT.json", record)
    print(json.dumps({"case": out.name, "status": terminal, "updates": updates, "selected_step": selected_step,
                      "selected_dev": record.get("selected_dev"), "wall_s": cost["total_case_wall_s"],
                      "error": error}), flush=True)
    return record


def run(protocol_path, out):
    protocol = json.loads(Path(protocol_path).read_text())
    validate_protocol(protocol)
    root = Path(out)
    root.mkdir(exist_ok=True)
    summary = []
    for case in protocol["cases"]:
        path = root / case_name(case)
        if path.exists():
            row = json.loads((path / "RESULT.json").read_text())
            if row["protocol_sha256"] != sha(protocol_path) or row["case"] != case:
                raise ValueError("Existing immutable attempt identity mismatch")
        else:
            row = fit_case(protocol, case, path, sha(protocol_path))
        summary.append({"case": case_name(case), "status": row["status"], "result_sha256": sha(path / "RESULT.json"),
                        "candidate_sha256": row.get("candidate_sha256")})
    dump(root / "TRAINING_TERMINALS.json", {"protocol_sha256": sha(protocol_path), "rows": summary,
                                          "all_roster_slots_terminal": len(summary) == len(protocol["cases"]),
                                          "test_created": False})
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.protocol, args.out))
