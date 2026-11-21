"""H2 finite-control pilot: independent reward observations, no QVI teacher labels."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from .environment import execution_identity
from .run import finish, runtime, save, sha, sources

METHODS = ("howard_qvi", "lookup_gate_bp", "never_reset")


def process():
    import torch
    g = torch.zeros(6, 6, dtype=torch.float64)
    for i in range(5):
        if i > 0:
            g[i, i-1] = .45 + .1 * (4-i)
        if i < 4:
            g[i, i+1] = .65 + .05 * i
        g[i, 5] = (.6, .3, .1, .05, .02)[i]
    g[5, 2] = 2.
    g -= torch.diag(g.sum(1))
    payoff = torch.tensor([-.12, -.10, -.08, -.10, -.12], dtype=g.dtype)
    initial = torch.tensor([.2, .2, .2, .2, .1, .1], dtype=g.dtype)
    return g, payoff, .3, initial


def observations(namespace, seed, split, count):
    import numpy as np
    if split not in ("train", "dev", "final") or count < 2:
        raise ValueError("fresh named reward split and multiple state probes required")
    def generator(label):
        key = hashlib.sha256(f"{namespace}/{seed}/{label}".encode()).digest()[:8]
        return np.random.default_rng(int.from_bytes(key, "little"))
    # External synthetic running utility; neither generator nor target calls QVI.
    plant = np.array([-.8, .25, -.25, .7, .35, -.04]) + generator("plant").normal(0, .08, 6)
    samples = plant[None] + generator(split).normal(0, .2, (count, 6))
    return samples


def soft_value(generator, reward, payoff, discount, probability):
    """Decision at each uniformization epoch; reset is immediate into locked phase."""
    import torch
    from qualification.hcsn_adaptive.finite_control import _control_inputs
    identity, rewards = _control_inputs(generator, reward, payoff, discount, 5, 5)
    if (probability.shape != (5,) or probability.dtype != generator.dtype
            or probability.device != generator.device or not bool(torch.isfinite(probability).all())
            or bool((probability < 0).any()) or bool((probability > 1).any())):
        raise ValueError("five finite reset probabilities in [0,1] required")
    chosen = torch.cat((probability, generator.new_zeros(1)))
    keep, rate = 1 - chosen, float((-generator.diagonal()).max())
    transition = (rate * identity + generator) / (discount + rate)
    matrix = identity - keep[:, None] * transition - chosen[:, None] * identity[5]
    rhs = keep * reward / (discount + rate) + chosen * rewards
    result = torch.linalg.solve(matrix, rhs)
    if not bool(torch.isfinite(result).all()):
        raise FloatingPointError("nonfinite full policy return")
    return result


def freeze(path, namespace, seeds):
    if (not namespace.startswith("hcsn-boundary-confirmatory-v1/") or len(namespace) < 49
            or not 1 <= len(seeds) <= 5 or len(set(seeds)) != len(seeds) or min(seeds) < 0):
        raise ValueError("fresh root namespace and distinct paired seeds required")
    save(path, {"schema": "hepta.hcsn-boundary-confirmatory.v1", "namespace": namespace,
                "seeds": seeds, "sources": sources(), "runtime": runtime(),
                "execution": execution_identity(), "methods": list(METHODS),
                "train": 32, "dev": 32, "final": 128, "steps": 128, "learning_rate": .1,
                "discount": .3, "active": 5, "locked_reset": 5, "howard_tolerance": 1e-10,
                "budget": {"wall_seconds": 90, "training_examples": 1000000,
                           "encoder_events": 1000000, "forward_examples": 1000000,
                           "backward_examples": 1000000, "development_queries": 100,
                           "proposals": 100}})


def verify(path):
    cfg = json.loads(Path(path).read_text())
    if (cfg["schema"] != "hepta.hcsn-boundary-confirmatory.v1" or cfg["sources"] != sources()
            or cfg["runtime"] != runtime() or cfg["execution"] != execution_identity()
            or cfg["methods"] != list(METHODS) or cfg["discount"] != .3
            or cfg["active"] != 5 or cfg["locked_reset"] != 5):
        raise ValueError("boundary source/protocol/execution identity changed")
    return cfg


def array_digest(value):
    return hashlib.sha256(str((value.shape, value.dtype)).encode() + value.tobytes()).hexdigest()


def fit_case(seed, cfg, ledger):
    import torch
    from qualification.hcsn_adaptive.finite_control import solve_impulse_control
    shared_start = time.perf_counter()
    g, payoff, discount, initial = process()
    with ledger.operation("fresh_running_reward_measurements",
                          training_examples=6 * cfg["train"]):
        train = observations(cfg["namespace"], seed, "train", cfg["train"])
        dev = observations(cfg["namespace"], seed, "dev", cfg["dev"])
        train_mean = torch.from_numpy(train.mean(0))
        dev_mean = torch.from_numpy(dev.mean(0))
    never = torch.zeros(5, dtype=g.dtype)
    with ledger.operation("incumbent_dev", development_queries=1, forward_examples=6):
        incumbent = float(initial @ soft_value(g, dev_mean, payoff, discount, never))
    record = {"train_sha256": array_digest(train), "dev_sha256": array_digest(dev),
              "observed_train_reward_mean": train_mean.tolist(), "observed_dev_reward_mean": dev_mean.tolist(),
              "G": g.tolist(), "reset_payoff": payoff.tolist(), "discount": discount,
              "initial_distribution": initial.tolist(), "uniformization_rate": float((-g.diagonal()).max()),
              "base_dev_return": incumbent, "methods": {}}
    shared_seconds = time.perf_counter() - shared_start
    record["common_setup_seconds"] = shared_seconds
    for method in METHODS:
        started = time.perf_counter()
        try:
            diagnostics = {"dp_linear_solves": 0, "bp_linear_solves": 0, "backward_passes": 0}
            with ledger.operation("proposal", proposals=1):
                probability = never.clone()
            if method == "howard_qvi":
                with ledger.operation("howard_policy_iteration", training_examples=6):
                    solution = solve_impulse_control(g, train_mean, payoff, discount=discount,
                        active_count=5, reset_entry=5, tolerance=cfg["howard_tolerance"], max_iterations=128)
                    probability = solution.reset_policy.to(g)
                    diagnostics.update(dp_linear_solves=solution.iterations,
                                       howard_iterations=solution.iterations,
                                       bellman_residual=solution.bellman_residual)
            elif method == "lookup_gate_bp":
                logits = torch.zeros(5, dtype=g.dtype, requires_grad=True)
                optimizer = torch.optim.Adam([logits], lr=cfg["learning_rate"])
                with ledger.operation("lookup_gate_bp", training_examples=6 * cfg["steps"],
                                      forward_examples=6 * cfg["steps"], backward_examples=6 * cfg["steps"]):
                    for _ in range(cfg["steps"]):
                        optimizer.zero_grad(set_to_none=True)
                        objective = initial @ soft_value(g, train_mean, payoff, discount, logits.sigmoid())
                        (-objective).backward()
                        if logits.grad is None or not bool(torch.isfinite(logits.grad).all()):
                            raise FloatingPointError("nonfinite full-state lookup gradient")
                        optimizer.step()
                        diagnostics["bp_linear_solves"] += 1
                        diagnostics["backward_passes"] += 1
                probability = logits.detach().sigmoid()
                diagnostics["logits"] = logits.detach().tolist()
            if method == "never_reset":
                value = incumbent
            else:
                with ledger.operation("candidate_dev", development_queries=1, forward_examples=6):
                    value = float(initial @ soft_value(g, dev_mean, payoff, discount, probability))
            accept = value > incumbent
            chosen = probability if accept else never
            record["methods"][method] = {
                "status": "reference" if method == "never_reset" else ("selected" if accept else "no_update"),
                "candidate_probability": probability.tolist(), "selected_probability": chosen.tolist(),
                "candidate_dev_return": value, "diagnostics": diagnostics,
                "adaptation_wall_seconds": time.perf_counter() - started}
            arm = record["methods"][method]
            arm["standalone_wall_lower_bound"] = shared_seconds + arm["adaptation_wall_seconds"]
        except Exception as error:
            record["methods"][method] = {"status": "failed", "error": repr(error),
                                         "completed_work": diagnostics,
                                         "adaptation_wall_seconds": time.perf_counter() - started}
    return record


def final_case(seed, cfg, record, ledger):
    import numpy as np
    import torch
    g, payoff, discount, initial = process()
    with ledger.operation("fresh_final_running_reward_measurements"):
        samples = observations(cfg["namespace"], seed, "final", cfg["final"])
    output = {"seed": seed, "reward_sha256": array_digest(samples),
              "reward_observations": samples.tolist(), "methods": {}}
    for method in METHODS:
        arm = record["methods"][method]
        if arm["status"] == "failed":
            output["methods"][method] = arm
            continue
        probability = torch.tensor(arm["selected_probability"], dtype=g.dtype)
        returns = []
        with ledger.operation("independent_full_return", forward_examples=6 * len(samples)):
            for row in samples:
                value = initial @ soft_value(g, torch.from_numpy(row), payoff, discount, probability)
                returns.append(float(value))
        output["methods"][method] = {"status": arm["status"], "reset_probability": probability.tolist(),
                                      "mean_full_return": float(np.mean(returns)), "measured_returns": returns,
                                      "evaluation_linear_solves": len(returns)}
    baseline = output["methods"]["never_reset"].get("measured_returns")
    if baseline is not None:
        for arm in output["methods"].values():
            if "measured_returns" in arm:
                arm["paired_return_gain"] = (np.asarray(arm["measured_returns"]) - baseline).tolist()
    return output


def execute(manifest, output, phase, selection_sha):
    started = time.perf_counter()
    cfg, identity = verify(manifest), sha(manifest)
    from qualification.hcsn_adaptive.budget import Budget, CostLedger
    output = Path(output)
    if phase == "fit":
        output.mkdir(parents=True, exist_ok=False)
        save(output / "admission.json", {"manifest_sha256": identity, "config": cfg})
        selected = {}
    else:
        if (not selection_sha or sha(output / "selection.json") != selection_sha
                or json.loads((output / "admission.json").read_text())["manifest_sha256"] != identity):
            raise ValueError("final requires original manifest and externally sealed selection")
        with (output / "FINAL_CONSUMED").open("x") as handle:
            handle.write(selection_sha)
        selected = json.loads((output / "selection.json").read_text())["cases"]
    ledger = CostLedger(output / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    results = []
    for seed in cfg["seeds"]:
        try:
            if phase == "fit":
                selected[str(seed)] = fit_case(seed, cfg, ledger)
                save(output / f"fit-{seed}.json", selected[str(seed)])
            elif "methods" in selected.get(str(seed), {}):
                results.append(final_case(seed, cfg, selected[str(seed)], ledger))
            else:
                results.append({"seed": seed, "status": "no_fitted_case", "fit_record": selected.get(str(seed))})
        except Exception as error:
            failure = {"seed": seed, "status": "failed", "error": repr(error)}
            if phase == "fit":
                selected[str(seed)] = failure
            else:
                results.append(failure)
    result = {"manifest_sha256": identity, "phase": phase, "cost": ledger.snapshot(),
              "claim_scope": "known finite-control benchmark with independent synthetic reward measurements",
              "cases" if phase == "fit" else "results": selected if phase == "fit" else results}
    finish(output / ("selection.json" if phase == "fit" else "final.json"), result, ledger)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "fit", "final"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--namespace")
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--selection-sha256")
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze(args.manifest, args.namespace or "", args.seeds or [])
    elif not args.output:
        parser.error("--output required")
    else:
        execute(args.manifest, args.output, args.phase, args.selection_sha256)

