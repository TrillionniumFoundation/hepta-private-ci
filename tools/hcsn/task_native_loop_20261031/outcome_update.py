"""Development-only delayed outcome feedback; primary frozen models stay intact.

One predeclared critic gradient step uses actual archived TRAIN rewards/costs
and a frozen successor-Q bootstrap. Validation is reported without selection.
This is offline outcome-driven refitting, not production online plasticity.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import time

import numpy as np

from ..task_value_factorial_20261030.controller import forward, loss_and_gradient, validation_regret
from ..task_value_factorial_20261030.task import ACTIONS, ContentAdapter, save, sha
from .experiment import MAX_BLOB_BYTES, verify_training
from .model import design, identity
from .reference import play_episode
from .train import HERE, announce, packed


def realized_training(dataset, archive):
    """Only previously completed TRAIN episodes supply reward labels."""
    rows = dataset["rows"]
    immediate, expected, following, actions = [], [], [], []
    with tarfile.open(archive, "r:gz") as tar:
        for episode in dataset["episodes"]:
            if episode["split"] != "train" or not episode["score"]["label_access_after_terminal"]:
                raise ValueError("Outcome update requires terminal TRAIN receipts")
            name = f"{episode['session']}/evaluator_labels.json"
            raw = tar.extractfile(name).read()
            if hashlib.sha256(raw).hexdigest() != dataset["cohort"]["files"][name]:
                raise ValueError("Archived training label identity mismatch")
            labels = json.loads(raw)["labels"]
            previous_cost, total = 0., 0.
            for offset, event in enumerate(episode["events"]):
                index = episode["first_row"]+offset
                row = rows[index]
                if row["session"] != episode["session"] or row["chosen_action"] != event["action"]:
                    raise ValueError("Training state/action alignment mismatch")
                reward = 0.
                if event["action"] == "FIRE":
                    answer = event["answer"]
                    reward = 1. if answer["prediction"] == labels[answer["job"]] else -1.
                cost = event["charged_cost"]-previous_cost
                previous_cost = event["charged_cost"]
                immediate.append(reward-cost)
                expected.append((abs(2*row["features"][3]-1) if event["action"] == "FIRE" else 0.)-cost)
                actions.append(ACTIONS.index(event["action"]))
                following.append(-1 if event["terminal"] else index+1)
                total += reward-cost
            if abs(total-episode["score"]["utility"]) > 5e-10:
                raise ValueError("Archived real reward/cost does not reconstruct the terminal score")
    if len(immediate) != len(rows):
        raise ValueError("Every TRAIN decision must have an aligned executed outcome")
    return np.asarray(immediate), np.asarray(expected), np.asarray(following), np.asarray(actions)


def summarize(traces):
    completed = sum(r["score"]["completed_jobs"] for r in traces)
    correct = sum(r["score"]["correct_jobs"] for r in traces)
    return dict(sessions=len(traces), utility=float(np.mean([r["score"]["utility"] for r in traces])),
                completed_jobs=completed, correct_jobs=correct,
                completed_accuracy=correct/completed if completed else None,
                fitted_law_regret=float(np.mean([r["fitted_law_regret"] for r in traces])))


def run(args):
    training, out = args.training.resolve(), args.out.resolve()
    freeze, protocol = verify_training(training, args.training_freeze_sha)
    out.mkdir(parents=True, exist_ok=False)
    source_hash = sha(Path(__file__))
    plan = dict(schema="hcsn.task.outcome.feedback.v1", training_freeze_sha256=args.training_freeze_sha,
        source_sha256=source_hash, optimizer_steps=1, learning_rate=.001, gradient_clip=2.,
        trainable="Critic weights only; all 11 cell parameters remain frozen", seeds=protocol["seeds"],
        target="Actual immediate TRAIN outcome utility + max legal Q of observed successor under the original frozen critic; terminal bootstrap zero",
        selection="No model selection and no additional updates after inspecting validation; preserve both improvements and regressions",
        heldout_access=False, primary_models_modified=False,
        scope="Offline delayed-outcome recovery mechanism; not an efficacy claim or production online learning")
    save(out / "PLAN.json", plan)
    start, cpu = time.perf_counter(), time.process_time()
    inventory, summaries = {}, []
    for seed in protocol["seeds"]:
        announce("development_outcome_update", seed=seed)
        data_path = training / "training" / f"seed{seed}.json.gz"
        data = json.loads(gzip.decompress(data_path.read_bytes()))
        archive = training / "data" / f"development_seed{seed}.tar.gz"
        train, validation = data["train"]["rows"], data["validation"]["rows"]
        immediate, expected, following, actions = realized_training(data["train"], archive)
        detail = dict(seed=seed, training_dataset_sha256=sha(data_path), archive_sha256=sha(archive), families={})
        adapter = ContentAdapter()
        with tempfile.TemporaryDirectory(prefix=f"hcsn_outcome_validation_{seed}_") as temporary:
            root = Path(temporary)
            with tarfile.open(archive, "r:gz") as tar:
                members = [m for m in tar.getmembers() if m.name.startswith(f"validation_seed{seed}_")]
                tar.extractall(root, members=members, filter="data")
            for family in ("ordinary", "analytic"):
                begin, begin_cpu = time.perf_counter(), time.process_time()
                original_path = training / "models" / f"seed{seed}_{family}_value.json"
                policy = json.loads(original_path.read_text())
                weights = {k: np.asarray(v) for k, v in policy["weights"].items()}
                x = design(train, policy["family"], policy["parameters"], policy["norm"])
                vx = design(validation, policy["family"], policy["parameters"], policy["norm"])
                q, _ = forward(weights, x)
                valid = np.asarray([r["feasible"] for r in train], bool)
                continuation = np.asarray([0. if j < 0 else np.max(np.where(valid[j], q[j], -np.inf)) for j in following])
                targets, masks = np.zeros_like(q), np.zeros_like(q, dtype=bool)
                indices = np.arange(len(train))
                targets[indices, actions] = immediate+continuation
                masks[indices, actions] = True
                before_loss, gradient = loss_and_gradient(weights, x, targets, masks, 0.)
                expected_targets = targets.copy()
                expected_targets[indices, actions] = expected+continuation
                _, expected_gradient = loss_and_gradient(weights, x, expected_targets, masks, 0.)
                grad_norm = np.sqrt(sum(float(np.square(g).sum()) for g in gradient.values()))
                factor = min(1., plan["gradient_clip"]/max(grad_norm, 1e-15))
                updated = {k: v-plan["learning_rate"]*factor*gradient[k] for k, v in weights.items()}
                after_loss, _ = loss_and_gradient(updated, x, targets, masks, 0.)
                candidate = dict(policy, weights={k: v.tolist() for k, v in updated.items()})
                path = out / "models" / f"seed{seed}_{family}_outcome_update.json"
                save(path, candidate)
                inventory[str(path.relative_to(out))] = sha(path)
                vtarget = np.asarray([r["q"] for r in validation], float)
                vvalid = np.asarray([r["feasible"] for r in validation], bool)
                before_traces, after_traces = [], []
                for session in data["validation"]["cohort"]["records"]:
                    folder = root / session["id"]
                    before_traces.append(play_episode(folder, policy, adapter))
                    after_traces.append(play_episode(folder, candidate, adapter))
                receipt = dict(family=family, original_sha256=sha(original_path), updated_sha256=sha(path),
                    original_model_identity=identity(policy), updated_model_identity=identity(candidate),
                    train_decisions=len(train), immediate_realized_utility=immediate.tolist(),
                    frozen_bootstrap=continuation.tolist(), observed_action=actions.tolist(),
                    chosen_td_target=(immediate+continuation).tolist(),
                    training_td_mse_before=before_loss, training_td_mse_after=after_loss,
                    actual_outcome_vs_expected_reward_target_l2=float(np.linalg.norm(immediate-expected)),
                    actual_vs_expected_reward_gradient_l2=float(np.sqrt(sum(np.square(gradient[k]-expected_gradient[k]).sum() for k in gradient))),
                    parameter_change_l2=float(np.sqrt(sum(np.square(updated[k]-weights[k]).sum() for k in weights))),
                    gradient_norm=float(grad_norm), validation_before=summarize(before_traces),
                    validation_after=summarize(after_traces),
                    validation_state_regret_before=validation_regret(weights, vx, vtarget, vvalid),
                    validation_state_regret_after=validation_regret(updated, vx, vtarget, vvalid),
                    cpu_seconds=time.process_time()-begin_cpu, wall_seconds=time.perf_counter()-begin,
                    validation_before_traces=before_traces, validation_after_traces=after_traces)
                detail["families"][family] = receipt
                summaries.append(dict(seed=seed, **{k: v for k, v in receipt.items() if k not in (
                    "validation_before_traces", "validation_after_traces", "immediate_realized_utility",
                    "frozen_bootstrap", "observed_action", "chosen_td_target")}))
        path = out / "receipts" / f"seed{seed}.json.gz"
        inventory[str(path.relative_to(out))] = packed(path, detail)
        if path.stat().st_size > MAX_BLOB_BYTES:
            raise ValueError("Development feedback receipt exceeds repository blob budget")
    verify_training(training, args.training_freeze_sha)
    if sha(Path(__file__)) != source_hash:
        raise ValueError("Development outcome-update code changed during execution")
    save(out / "REPORT.json", dict(plan=plan, artifacts=inventory, summaries=summaries,
        primary_freeze_unchanged=True, heldout_access=False, cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-start, production_activation=False,
        conclusion_scope="Observed TRAIN outcomes actually change critic targets, gradients and a separately identified candidate. Validation changes are descriptive; no updated candidate replaces the primary efficacy experiment."))
    announce("development_outcome_update_complete", out=str(out))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--training-freeze-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
