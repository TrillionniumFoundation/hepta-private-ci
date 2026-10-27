"""Frozen-reference selection and exact terminal-tail labels on V3 fit roles."""

import json
from pathlib import Path
import time

import numpy as np

from .learning import (clone_state, guarded_block, hard_panel, make_model, new_optimizer,
                       panels, save_checkpoint, save_hard, schedule, state_identity)
from .training_common import Journal, configuration, file_hash, object_hash, require, write_json
from .training_features import NAMES, measure_state


def baseline_record(context):
    score = context.baseline_guard
    return {"source_ids": score["source_ids"], "values": score["values"]["reward"].tolist(),
            "output_sha256": score["output_sha256"], "mean": score["means"]["reward"]}


def stage_complete(out, context, summary, started):
    out = Path(out)
    files = {str(path.relative_to(out)): file_hash(path) for path in sorted(out.rglob("*")) if path.is_file()}
    complete = {"schema": "hepta.field-bridge.v3.training-stage-complete.1", "seed": context.seed,
                "group": context.group, "resources": context.costs.snapshot(), "files": files,
                "source_roles": list(context.corpus.splits), "wall_ns": time.perf_counter_ns() - started,
                "baseline_guard": baseline_record(context), **summary}
    write_json(out / "COMPLETE.json", complete)
    return complete


def commit_decision(journal, context, model, optimizer, *, stage, trajectory, step, schedule_id, action_index, **extra):
    p = configuration(context.protocol)
    record = {"kind": "decision_before_update", "stage": stage, "seed": context.seed,
              "trajectory": trajectory, "step": step, "schedule_id": schedule_id,
              "before": state_identity(model, optimizer), "action_index": action_index,
              "schedule_sha256": object_hash(schedule(context.seed, schedule_id, step, p["macro_steps"], context.protocol)),
              **extra}
    return journal.append(record)


def run_reference(context, out):
    """All four constants; selection uses only the two reference outcome roles."""
    p, out, started = configuration(context.protocol), Path(out), time.perf_counter_ns()
    require(context.group == "fit", "Reference training must use the fit adaptation roles")
    task = panels(context.corpus, "reference_task", context.seed, p["conditions"], context.protocol)
    clean = panels(context.corpus, "reference_clean", context.seed, ["clean"], context.protocol)
    observers = {"reward": context.observers["reward"]}
    originals = {"task": hard_panel(context.original, task, observers, context.action, context.protocol,
                                     context.costs, "reference_original_task", retain=True),
                 "clean": hard_panel(context.original, clean, observers, context.action, context.protocol,
                                      context.costs, "reference_original_clean", retain=True)}
    for name, score in originals.items():
        save_hard(out / f"original-{name}.npz", score)
    candidates = []
    with Journal(out / "decisions-and-outcomes.jsonl.gz") as journal:
        for action_index in range(len(p["multipliers"])):
            model = make_model(context.original, context.seed, context.protocol)
            optimizer = new_optimizer(model, context.protocol)
            before_cost = context.costs.snapshot()
            for step in range(0, p["steps"], p["macro_steps"]):
                decision = commit_decision(journal, context, model, optimizer, stage="reference",
                                          trajectory=action_index, step=step, schedule_id=p["reference_schedule_id"],
                                          action_index=action_index, policy="preregistered_constant")
                receipt = guarded_block(context, model, optimizer, step, action_index, p["reference_schedule_id"])
                journal.append({"kind": "block_outcome", "decision_sha256": decision, "receipt": receipt})
            scores = {}
            for role, panel in (("task", task), ("clean", clean)):
                score = hard_panel(model, panel, observers, context.action, context.protocol,
                                   context.costs, "reference_endpoint_" + role, retain=True)
                scores[role] = save_hard(out / f"constant-{action_index}-{role}.npz", score)
                scores[role]["paired_delta"] = float((score["values"]["reward"] - originals[role]["values"]["reward"]).mean())
            checkpoint = save_checkpoint(out / f"constant-{action_index}.pt", model, optimizer, context.protocol,
                                         {"seed": context.seed, "stage": "reference", "action_index": action_index,
                                          "schedule_id": p["reference_schedule_id"], "source_roles": list(context.corpus.splits)})
            candidates.append({"action_index": action_index, "scores": scores, "checkpoint": checkpoint,
                               "eligible": scores["clean"]["paired_delta"] >= p["reference_clean_min_delta"],
                               "resources": context.costs.since(before_cost)})
            print(f"reference seed={context.seed} constant={action_index} complete", flush=True)
    eligible = [candidate for candidate in candidates if candidate["eligible"]]
    require(eligible, "No admissible continuation reference, including the exact zero action")
    winner = max(eligible, key=lambda candidate: (candidate["scores"]["task"]["means"]["reward"], -candidate["action_index"]))
    result = {"schema": "hepta.field-bridge.v3.frozen-reference.1", "seed": context.seed,
              "selected_action_index": winner["action_index"], "candidates": candidates,
              "selection_rule": "highest reward mean among clean delta >=0; lowest action index tie",
              "reference_policy": "guarded constant multiplier through all remaining 48-step blocks",
              "fixed_output_action": context.action, "training_configuration_sha256": object_hash(p)}
    write_json(out / "REFERENCE.json", result)
    return stage_complete(out, context, {"stage": "reference", "reference_sha256": file_hash(out / "REFERENCE.json")}, started)


def build_bank(context, reference_path, out):
    """Four balanced paths. Each candidate is continued exactly to the terminal time."""
    p, out, started = configuration(context.protocol), Path(out), time.perf_counter_ns()
    reference = json.loads(Path(reference_path).read_text())
    require(context.group == "fit" and reference["seed"] == context.seed, "Reference/fit scope mismatch")
    require(reference["training_configuration_sha256"] == object_hash(p), "Reference configuration changed")
    reference_action, reference_hash = reference["selected_action_index"], file_hash(reference_path)
    records = []
    with Journal(out / "decisions-and-outcomes.jsonl.gz") as journal:
        for trajectory, path in enumerate(p["exploration_paths"]):
            model = make_model(context.original, context.seed, context.protocol)
            optimizer = new_optimizer(model, context.protocol)
            schedule_id = p["fit_schedule_ids"][trajectory]
            for decision_index, step in enumerate(range(0, p["steps"], p["macro_steps"])):
                state, current, feature_receipt = measure_state(context, model, optimizer, step, schedule_id, retain=True)
                prefix = f"trajectory-{trajectory}-step-{step}"
                save_hard(out / (prefix + "-current.npz"), current)
                saved = save_checkpoint(out / (prefix + "-state.pt"), model, optimizer, context.protocol,
                                        {"seed": context.seed, "stage": "fit_bank", "trajectory": trajectory,
                                         "step": step, "schedule_id": schedule_id})
                chosen = path[decision_index]
                before = state_identity(model, optimizer)
                commitment = journal.append({"kind": "branch_set_before_outcomes", "seed": context.seed,
                    "trajectory": trajectory, "step": step, "schedule_id": schedule_id, "before": before,
                    "state": state, "feature_receipt": feature_receipt, "selected_exploration_action": chosen,
                    "reference_action_index": reference_action, "reference_sha256": reference_hash,
                    "complete_future_schedule_sha256": object_hash(schedule(context.seed, schedule_id, step, p["steps"] - step, context.protocol))})
                values, branches, selected_first = [], [], None
                for action_index in range(len(p["multipliers"])):
                    branch, branch_optimizer = clone_state(model, optimizer, context.protocol, context.costs)
                    before_cost = context.costs.snapshot()
                    first_receipt = None
                    for future in range(step, p["steps"], p["macro_steps"]):
                        next_action = action_index if future == step else reference_action
                        decision = commit_decision(journal, context, branch, branch_optimizer, stage="reference_tail",
                            trajectory=trajectory, step=future, schedule_id=schedule_id, action_index=next_action,
                            branch_start_step=step, branch_action_index=action_index, branch_set_commit=commitment)
                        receipt = guarded_block(context, branch, branch_optimizer, future, next_action, schedule_id)
                        journal.append({"kind": "block_outcome", "decision_sha256": decision, "receipt": receipt})
                        if future == step:
                            first_receipt = receipt
                            if action_index == chosen:
                                selected_first = receipt
                    score = hard_panel(branch, context.probe, {"reward": context.observers["reward"]}, context.action,
                                       context.protocol, context.costs, "terminal_fit_label", retain=True)
                    output_path = out / f"{prefix}-action-{action_index}-terminal.npz"
                    output = save_hard(output_path, score)
                    value = score["means"]["reward"]
                    values.append(value)
                    branch_record = {"action_index": action_index, "terminal_value": value,
                        "terminal": state_identity(branch, branch_optimizer), "first_block_after": first_receipt["after"],
                        "first_block_accepted": first_receipt["accepted"], "output": output,
                        "resources": context.costs.since(before_cost)}
                    branches.append(branch_record)
                    journal.append({"kind": "terminal_branch_outcome", "branch_set_commit": commitment,
                                    "trajectory": trajectory, "step": step, **branch_record})
                require(state_identity(model, optimizer) == before, "Counterfactual branches mutated their common parent")
                decision = commit_decision(journal, context, model, optimizer, stage="exploration_path",
                    trajectory=trajectory, step=step, schedule_id=schedule_id, action_index=chosen,
                    predetermined_path=path, branch_set_commit=commitment)
                actual = guarded_block(context, model, optimizer, step, chosen, schedule_id)
                require(actual["after"] == selected_first["after"] and actual["candidate"] == selected_first["candidate"]
                        and actual["guard_output_sha256"] == selected_first["guard_output_sha256"]
                        and actual["guard_values"] == selected_first["guard_values"], "Selected path did not replay its exact candidate prefix")
                journal.append({"kind": "block_outcome", "decision_sha256": decision, "receipt": actual,
                                "selected_prefix_replay_exact": True})
                records.append({"trajectory": trajectory, "step": step, "schedule_id": schedule_id,
                    "state": state, "current_value": current["means"]["reward"], "action_values": values,
                    "state_checkpoint": saved, "branch_set_commit": commitment, "branches": branches,
                    "selected_action_index": chosen, "selected_after": actual["after"]})
                print(f"bank seed={context.seed} trajectory={trajectory} step={step} complete", flush=True)
            save_checkpoint(out / f"trajectory-{trajectory}-terminal.pt", model, optimizer, context.protocol,
                            {"seed": context.seed, "stage": "fit_bank", "trajectory": trajectory,
                             "step": p["steps"], "schedule_id": schedule_id})
    require(len(records) == 24, "A complete bank requires four balanced trajectories and six decisions")
    result = {"schema": "hepta.field-bridge.v3.terminal-reference-bank.1", "seed": context.seed,
              "records": records, "feature_names": list(NAMES), "reference_sha256": reference_hash,
              "reference_action_index": reference_action, "training_configuration_sha256": object_hash(p),
              "resources": context.costs.snapshot(), "target_scope": p["value_target"],
              "selected_prefixes_independently_replayed": True, "future_policy_is_reference_not_deployed_policy": True}
    write_json(out / "BANK.json", result)
    return stage_complete(out, context, {"stage": "bank", "bank_sha256": file_hash(out / "BANK.json")}, started)
