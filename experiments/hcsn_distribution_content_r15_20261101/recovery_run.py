"""Registered recovery selection and confirmation on frozen value-trained models."""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from .campaign import configure, digest, tensors, verified, write
from .data import dataset
from .models import PRIMARY, restore
from .recovery import (ACTIONS, RecoveryPrices, StatefulContent, apply_selector,
                       corrupt_content, fit_selector, merge_cases, paired_recovery,
                       prefix_features, select_actions, summarize)


COHORTS = ("none", "sign", "zero")
DOMAINS = ("iid", "long_distractors")
SPLIT_SEEDS = {"train": 151911, "val": 151912, "test": 151913}


def prepare(output):
    protocol = verified(output)
    root = output / "recovery"
    root.mkdir(exist_ok=False)
    plan = dict(schema="hcsn.r15.paid-recovery.v1", families=list(PRIMARY),
                tasks=protocol["tasks"], seeds=protocol["seeds"], train_mode="value",
                training_domains=["iid"], confirmation_domains=list(DOMAINS),
                cohorts=list(COHORTS), split_fault_seeds=SPLIT_SEEDS, fault_probability=.5,
                prices=asdict(RecoveryPrices()), sensitivity_multipliers=[0., .5, 1., 2., 4.],
                intervention="After T-2 original frames, minimum one; content fault only; same mask for both families",
                selector="Fit four actual-action utilities on train; select whole rule on val; freeze every policy before any recovery confirmation",
                no_alarm="none with paid monitoring/cache", candidate_rules="four fixed alarm actions and ridge strengths .1,1,10",
                recovery_scope="Read-all diagnosed synthetic faults; source-time reconstruction; service delay costs but no external evolution during recovery",
                source_freeze_sha256=digest(output / "SOURCE_FREEZE.json"),
                training_protocol_sha256=digest(output / "PROTOCOL.json"))
    write(root / "PROTOCOL.json", plan)
    write(root / "REGISTRATION.json", dict(protocol_sha256=digest(root / "PROTOCOL.json"), heldout_opened=False))
    return plan


def registered(output):
    verified(output)
    root = output / "recovery"
    registration = json.loads((root / "REGISTRATION.json").read_text())
    if digest(root / "PROTOCOL.json") != registration["protocol_sha256"]:
        raise ValueError("Recovery registration changed")
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    if digest(output / "SOURCE_FREEZE.json") != protocol["source_freeze_sha256"]:
        raise ValueError("Campaign source freeze changed")
    return protocol


def load_group(output, task, seed):
    fit = output / "fits" / f"{task}_s{seed}_value"
    summary = json.loads((fit / "SUMMARY.json").read_text())
    if summary["development"] or digest(fit / "selected.pt") != summary["checkpoint_sha256"]:
        raise ValueError("Recovery requires a frozen nondevelopment selected checkpoint")
    return torch.load(fit / "selected.pt", weights_only=False), summary


def case(model, task, split, domain, cohort, protocol):
    values = dataset(task, split, domain)
    x, dt, y = tensors(values)
    seed = protocol["split_fault_seeds"][split] + 100 * COHORTS.index(cohort) + 1000 * (task == "binding")
    result = paired_recovery(model, x, dt, y, fault_kind=cohort,
                             fault_probability=0. if cohort == "none" else protocol["fault_probability"],
                             seed=seed, prices=RecoveryPrices(**protocol["prices"]), groups=values["group"])
    return result, values


def save_case(path, result, values, extra=None):
    arrays = {name: value for name, value in result.items() if isinstance(value, np.ndarray)}
    arrays.update(labels=values["y"], ids=values["ids"], dt=values["dt"],
                  context_ids=values["context_ids"], partition_ids=values["partition_ids"])
    if extra:
        arrays.update(extra)
    np.savez_compressed(path, **arrays)
    return dict(path=path.name, sha256=digest(path), data_sha256=values["sha256"],
                metadata=result["metadata"], summary=summarize(result))


def fit_group(output, task, seed):
    protocol = registered(output)
    candidate, source = load_group(output, task, seed)
    dest = output / "recovery" / "fits" / f"{task}_s{seed}"
    dest.mkdir(parents=True, exist_ok=False)
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    records, policies = [], {}
    for family in PRIMARY:
        model = restore(candidate, family)
        splits = {}
        for split in ("train", "val"):
            cases = []
            for cohort in COHORTS:
                result, values = case(model, task, split, "iid", cohort, protocol)
                raw_path = dest / f"{family}_{split}_{cohort}.npz"
                receipt = save_case(raw_path, result, values)
                receipt.update(path=str(raw_path.relative_to(output)), task=task, seed=seed,
                               family=family, split=split, cohort=cohort)
                records.append(receipt); cases.append(result)
            splits[split] = merge_cases(cases)
        fitted = fit_selector(splits["train"], splits["val"])
        fitted.update(task=task, seed=seed, family=family, checkpoint_sha256=source["checkpoint_sha256"],
                      source_model_hash=source["model_hashes"][family],
                      source_training_mode="value", recovery_protocol_sha256=digest(output / "recovery" / "PROTOCOL.json"))
        write(dest / f"{family}_POLICY.json", fitted)
        policies[family] = dict(path=str((dest / f"{family}_POLICY.json").relative_to(output)),
                               sha256=digest(dest / f"{family}_POLICY.json"),
                               validation_utility=fitted["validation_utility"], selected=fitted["policy"]["kind"])
    write(dest / "INDEX.json", dict(records=records, policies=policies, task=task, seed=seed,
                                    cpu_seconds=time.process_time()-started_cpu,
                                    wall_seconds=time.perf_counter()-started_wall, heldout_opened=False))
    return dict(task=task, seed=seed, policies=policies)


def freeze_policies(output):
    protocol = registered(output)
    policies = []
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            for family in PRIMARY:
                path = output / "recovery" / "fits" / f"{task}_s{seed}" / f"{family}_POLICY.json"
                value = json.loads(path.read_text())
                if value["heldout_opened"]:
                    raise ValueError("Policy was not selected before confirmation")
                policies.append(dict(path=str(path.relative_to(output)), sha256=digest(path),
                                     task=task, seed=seed, family=family,
                                     checkpoint_sha256=value["checkpoint_sha256"]))
    frozen = dict(policies=policies, expected_policies=len(protocol["tasks"])*len(protocol["seeds"])*len(PRIMARY),
                  recovery_protocol_sha256=digest(output / "recovery" / "PROTOCOL.json"), heldout_opened=False)
    write(output / "recovery" / "POLICY_FREEZE.json", frozen)
    return dict(policies=len(policies))


@torch.inference_mode()
def actual_selected_execution(model, values, result, policy, prices):
    """Execute only chosen actions, independently of four-arm evaluator outputs."""
    x, dt, labels = tensors(values)
    cut = result["metadata"]["cut"]
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    adapter = StatefulContent(model, x, dt)
    prefix = adapter.consume(adapter.initial(), 0, cut)
    alarm = torch.from_numpy(result["alarm"])
    damaged = corrupt_content(prefix, alarm, result["metadata"]["fault_kind"])
    features = prefix_features(adapter.logits(damaged), alarm, dt, cut, prices,
                               result["metadata"]["cached_bytes_per_episode"]).numpy()
    chosen = select_actions(policy, features)
    prediction = np.empty(len(x), dtype=np.int64)
    processed = adapter.consumed_frames
    for j, action in enumerate(ACTIONS):
        ids = np.flatnonzero(chosen == j)
        if not len(ids):
            continue
        sub = StatefulContent(model, x[ids], dt[ids])
        state = sub.initial() if action in ("reset_only", "reset_replay") else {
            key: tensor[ids].clone() for key, tensor in damaged.items()}
        if action in ("replay_only", "reset_replay"):
            state = sub.consume(state, 0, cut,
                                clock="observation_only" if action == "replay_only" else "source")
        state = sub.consume(state, cut, x.shape[1])
        prediction[ids] = sub.logits(state).argmax(-1).numpy()
        processed += sub.consumed_frames
    cpu, wall = time.process_time()-start_cpu, time.perf_counter()-start_wall
    expected = apply_selector(policy, result)
    if not np.array_equal(chosen, expected["actions"]) or not np.array_equal(prediction, expected["predictions"]):
        raise AssertionError("Frozen selector real execution differs from paired evaluator")
    return dict(actions=chosen, prediction=prediction), dict(
        cpu_seconds=cpu, wall_seconds=wall, episodes=len(x), processed_frames=processed,
        replay_frame_reads=int(sum(chosen == ACTIONS.index("replay_only"))
                               + sum(chosen == ACTIONS.index("reset_replay"))) * cut,
        resets=int(sum(chosen == ACTIONS.index("reset_only"))
                   + sum(chosen == ACTIONS.index("reset_replay"))),
        batch_scope="actual full batch single chosen action per episode, including prefix/control and state slicing",
        prediction_mismatches=0, action_mismatches=0)


def confirm_group(output, task, seed):
    protocol = registered(output)
    frozen = json.loads((output / "recovery" / "POLICY_FREEZE.json").read_text())
    if frozen["recovery_protocol_sha256"] != digest(output / "recovery" / "PROTOCOL.json"):
        raise ValueError("Recovery protocol changed after policy freeze")
    if len(frozen["policies"]) != frozen["expected_policies"]:
        raise ValueError("Every policy must be frozen before recovery confirmation")
    for item in frozen["policies"]:
        if digest(output / item["path"]) != item["sha256"]:
            raise ValueError("Frozen recovery policy changed")
    candidate, source = load_group(output, task, seed)
    dest = output / "recovery" / "confirmation" / f"{task}_s{seed}"
    dest.mkdir(parents=True, exist_ok=False)
    records, receipts = [], []
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    for family in PRIMARY:
        path = output / "recovery" / "fits" / f"{task}_s{seed}" / f"{family}_POLICY.json"
        fitted = json.loads(path.read_text())
        if fitted["checkpoint_sha256"] != source["checkpoint_sha256"]:
            raise ValueError("Model changed after policy selection")
        policy = fitted["policy"]
        model = restore(candidate, family)
        for domain in DOMAINS:
            for cohort in COHORTS:
                result, values = case(model, task, "test", domain, cohort, protocol)
                selected = apply_selector(policy, result)
                actual, receipt = actual_selected_execution(model, values, result, policy, RecoveryPrices(**protocol["prices"]))
                extra = {"selected_action": actual["actions"], "selected_prediction": actual["prediction"],
                         **{"selected_"+key: selected[key] for key in ("correct", "fee", "utility")}}
                filename = f"{family}_{domain}_{cohort}.npz"
                row = save_case(dest / filename, result, values, extra)
                row.update(path=str((dest / filename).relative_to(output)), task=task, seed=seed,
                           family=family, domain=domain, cohort=cohort,
                           policy_sha256=digest(path), checkpoint_sha256=source["checkpoint_sha256"],
                           policy_freeze_sha256=digest(output / "recovery" / "POLICY_FREEZE.json"),
                           selected=summarize(result, policy)["selected"], sensitivity=[])
                incremental_fee = selected["fee"] - result["unprotected_fee"]
                accuracy_gain = selected["correct"] - result["correct"][:, 0]
                for multiplier in protocol["sensitivity_multipliers"]:
                    row["sensitivity"].append(dict(incremental_price_multiplier=multiplier,
                        fixed_policy_gain_vs_unprotected_none=float((accuracy_gain-multiplier*incremental_fee).mean()),
                        fixed_policy_mean_fee=float((result["unprotected_fee"]+multiplier*incremental_fee).mean())))
                row["selected"]["gross_accuracy_gain_vs_none"] = float(accuracy_gain.mean())
                row["selected"]["incremental_fee_vs_unprotected_none"] = float(incremental_fee.mean())
                records.append(row)
                receipts.append(dict(task=task, seed=seed, family=family, domain=domain, cohort=cohort, **receipt))
    write(dest / "INDEX.json", dict(records=records))
    write(dest / "ACTUAL_EXECUTION.json", dict(records=receipts))
    write(dest / "PROCESS.json", dict(cpu_seconds=time.process_time()-started_cpu,
                                      wall_seconds=time.perf_counter()-started_wall,
                                      includes="four-arm research plus independent actual selected execution; do not add nested timers"))
    return dict(task=task, seed=seed, records=len(records), actual_execution_mismatches=0)


def aggregate(output):
    protocol = registered(output)
    records, receipts = [], []
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            path = output / "recovery" / "confirmation" / f"{task}_s{seed}" / "INDEX.json"
            part = json.loads(path.read_text())["records"]
            actual = json.loads(path.with_name("ACTUAL_EXECUTION.json").read_text())["records"]
            if len(part) != len(PRIMARY)*len(DOMAINS)*len(COHORTS) or len(actual) != len(part):
                raise ValueError("Incomplete registered recovery confirmation group")
            records.extend(part); receipts.extend(actual)
    write(output / "recovery" / "CONFIRMATION_INDEX.json", dict(records=records))
    write(output / "recovery" / "ACTUAL_EXECUTION_INDEX.json", dict(records=receipts))
    return dict(records=len(records), receipts=len(receipts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "fit", "freeze", "confirm", "aggregate"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", choices=("recall", "binding"))
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(); configure()
    if args.action in ("fit", "confirm"):
        result = (fit_group if args.action == "fit" else confirm_group)(args.output, args.task, args.seed)
    else:
        result = {"prepare": prepare, "freeze": freeze_policies, "aggregate": aggregate}[args.action](args.output)
    print(json.dumps(result, sort_keys=True))
