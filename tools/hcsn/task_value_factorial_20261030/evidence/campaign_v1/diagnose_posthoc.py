"""Exploratory read-only diagnosis of the already-frozen Hepta campaign.

Never fits parameters, selects checkpoints, reruns content inference, or changes
training/confirmation evidence. Its CPU/wall time is an extra posthoc audit cost.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import time

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def matrix_receipt(items, fitted):
    counts = np.zeros((2, 2), dtype=int)
    for item in items:
        counts[item["symbol"], item["observation"]] += 1
    denominators = counts.sum(1)
    empirical = [counts[i].astype(float).tolist() if denominators[i] == 0
                 else (counts[i]/denominators[i]).tolist() for i in range(2)]
    return dict(unique_executed_payloads=int(counts.sum()), counts=counts.tolist(),
        empirical_confusion=empirical, class_counts=denominators.tolist(),
        actual_errors=int(counts.sum()-np.trace(counts)),
        empirical_accuracy=float(np.trace(counts)/counts.sum()) if counts.sum() else None,
        fitted_confusion=np.asarray(fitted).tolist(),
        expected_errors_from_train_confusion=float(sum(denominators[i]*fitted[i][1-i] for i in range(2))),
        max_absolute_confusion_difference=float(np.max(np.abs(np.asarray(empirical)-fitted)))
            if np.all(denominators > 0) else None)


def summarize_policy(episodes, decisions, seeds):
    by_seed = []
    for seed in seeds:
        rows = [r for r in episodes if r["seed"] == seed]
        ds = [d for d in decisions if d["seed"] == seed]
        by_seed.append(dict(seed=seed, sessions=len(rows), decisions=len(ds),
            mean_utility=float(np.mean([r["utility"] for r in rows])),
            mean_initial_fitted_value=float(np.mean([r["initial_fitted_value"] for r in rows])),
            mean_path_teacher_regret=float(np.mean([r["path_teacher_regret"] for r in rows])),
            mean_realization_residual=float(np.mean([r["realization_residual"] for r in rows])),
            mean_read_innovation=float(np.mean([r["residual_by_action"]["READ"] for r in rows])),
            mean_fire_outcome_residual=float(np.mean([r["residual_by_action"]["FIRE"] for r in rows])),
            mean_reads=float(np.mean([r["reads"] for r in rows])),
            mean_fires=float(np.mean([r["fires"] for r in rows]))))
    action_pairs = Counter((d["selected_action"]+" -> "+d["teacher_action"]) for d in decisions)
    regrets_by_chosen = {}
    for action in ("STOP", "SKIP", "READ", "FIRE"):
        ds = [d for d in decisions if d["selected_action"] == action]
        regrets_by_chosen[action] = dict(count=len(ds), suboptimal=sum(d["regret"] > 1e-10 for d in ds),
            total_regret=float(sum(d["regret"] for d in ds)))
    return dict(sessions=len(episodes), decisions=len(decisions), per_seed=by_seed,
        seed_mean={key:float(np.mean([row[key] for row in by_seed])) for key in by_seed[0]
                   if key not in ("seed", "sessions", "decisions")},
        mean_decision_teacher_regret=float(np.mean([d["regret"] for d in decisions])),
        teacher_optimal_decisions=sum(d["regret"] <= 1e-10 for d in decisions),
        suboptimal_STOP=sum(d["selected_action"] == "STOP" and d["regret"] > 1e-10 for d in decisions),
        premature_FIRE=sum(d["selected_action"] == "FIRE" and d["teacher_action"] in ("READ", "SKIP")
                          and d["regret"] > 1e-10 for d in decisions),
        READ_when_FIRE_or_STOP_optimal=sum(d["selected_action"] == "READ" and d["teacher_action"] in ("FIRE", "STOP")
                          and d["regret"] > 1e-10 for d in decisions),
        SKIP_when_READ_optimal=sum(d["selected_action"] == "SKIP" and d["teacher_action"] == "READ"
                          and d["regret"] > 1e-10 for d in decisions),
        chosen_to_teacher_action_counts=dict(sorted(action_pairs.items())),
        regret_by_chosen_action=regrets_by_chosen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo))
    from tools.hcsn.task_value_factorial_20261030.dataset import decode_features
    from tools.hcsn.task_value_factorial_20261030.cells import physical
    from tools.hcsn.task_value_factorial_20261030.storage import source_identity
    from tools.hcsn.task_value_factorial_20261030.task import ACTIONS, Bellman

    wall, cpu = time.perf_counter(), time.process_time()
    out = args.out.resolve()
    destination = out/"POSTHOC_DIAGNOSTIC.json.gz"
    if destination.exists():
        raise FileExistsError(destination)
    protocol = json.loads((out/"PROTOCOL.json").read_text())
    freeze = json.loads((out/"FREEZE.json").read_text())
    if source_identity() != freeze["source"]:
        raise ValueError("Current imported source differs from the published frozen source")
    inputs = {str(path.relative_to(out)):digest(path) for path in
              [out/"PROTOCOL.json", out/"FREEZE.json", out/"CONFIRMATION.json"]}
    models, training = {}, {}
    for seed in protocol["seeds"]:
        path = out/"models"/f"seed{seed}.json.gz"
        inputs[str(path.relative_to(out))] = digest(path)
        if inputs[str(path.relative_to(out))] != freeze["models"][str(path.relative_to(out))]:
            raise ValueError("Frozen model hash mismatch")
        model = models[seed] = load(path)
        development = out/"training"/f"seed{seed}.json.gz"
        inputs[str(development.relative_to(out))] = digest(development)
        calibration = load(development)["calibration"]
        summary = dict(fitted_confusion=model["confusion"], calibration_counts=calibration["counts"],
                       cellfits={}, controllers={})
        for family, fit in model["cellfits"].items():
            receipt = fit["receipt"]
            initial = np.asarray(receipt["initial_parameters"])
            final = np.asarray(fit["parameters"])
            actual = {}
            for driver in (-1., 0., 1.):
                actual[str(driver)] = {}
                for name, values in (("initial", initial), ("final", final)):
                    cell = physical(values, driver)
                    actual[str(driver)][name] = {key:float(getattr(cell, key))
                        for key in ("drift", "sigma", "boundary", "reset", "refractory")}
            summary["cellfits"][family] = {key:receipt[key] for key in
                ("converged", "termination", "iterations", "nfev", "loss", "train_read_rows",
                 "physical_parameter_change", "initial_parameters", "parameters")}
            summary["cellfits"][family].update(physical_theta_change_l2=float(np.linalg.norm(final[:6]-initial[:6])),
                parameters_at_box_bounds=np.flatnonzero(np.abs(final) >= 3.-1e-9).tolist(),
                physical_map_diagnostic=actual,
                physical_map_scope="Mechanistic map for analytic cell; ordinary cell uses these theta coordinates as gate parameters")
        for arm, fitted in model["controllers"].items():
            receipt = fitted["receipt"]
            summary["controllers"][arm] = {key:receipt[key] for key in
                ("selected_update", "selected_validation_regret", "train_states", "validation_states", "updates", "target")}
            summary["controllers"][arm]["checkpoint_regrets"] = [dict(update=c["update"],
                validation_regret=c["validation_regret"]) for c in receipt["candidates"]]
        training[str(seed)] = summary

    episode_rows, decision_rows = [], []
    observed_payloads = {split:{} for split in ("test", "ood")}
    integrity = dict(recomputed_fitted_dp_max_q_difference=0., max_path_decomposition_error=0.,
                     source_matched_freeze=True, payload_hashes_verified=0)
    for seed in protocol["seeds"]:
        for split in ("test", "ood"):
            print(json.dumps(dict(stage="posthoc_recompute", seed=seed, split=split)), flush=True)
            result_path = out/"results"/f"seed{seed}_{split}.json.gz"
            archive_path = out/"data"/f"confirmation_seed{seed}_{split}.tar.gz"
            for path in (result_path, archive_path):
                inputs[str(path.relative_to(out))] = digest(path)
            result = load(result_path)
            meta_cache, labels_cache, teachers, packet_cache = {}, {}, {}, {}
            with tarfile.open(archive_path, "r:gz") as tar:
                for row in result["rows"]:
                    sid = row["session_id"]
                    if row["status"] != "complete" or len(row["events"]) != len(row["decision_trace"]):
                        raise ValueError("Incomplete execution needs explicit preservation, not silent filtering")
                    if sid not in teachers:
                        public = tar.extractfile(sid+"/public.json").read()
                        if hashlib.sha256(public).hexdigest() != row["public_sha256"]:
                            raise ValueError("Public metadata hash mismatch")
                        meta_cache[sid] = json.loads(public)
                        labels_cache[sid] = json.load(tar.extractfile(sid+"/evaluator_labels.json"))["labels"]
                        teachers[sid] = Bellman(meta_cache[sid], models[seed]["confusion"],
                            protocol["multiplier"], protocol["latency_price"], future=True)
                    teacher, meta, labels = teachers[sid], meta_cache[sid], labels_cache[sid]
                    initial_value = teacher.value(0, 0, meta["budget"], .5)
                    cumulative_regret, previous_cost = 0., 0.
                    residuals = {action:0. for action in ACTIONS}
                    for decision_index, (decision, event) in enumerate(zip(row["decision_trace"], row["events"], strict=True)):
                        decoded = decode_features(decision["record"]["features"])
                        for key in ("deadline", "budget", "reliability", "price", "duration"):
                            if decoded["meta"][key] != meta[key]:
                                raise ValueError("Decoded public state differs from actual archived metadata")
                        if decoded["confusion"] != models[seed]["confusion"]:
                            raise ValueError("Decision observation law differs from fitted TRAIN law")
                        state = decoded["state"]
                        q = np.asarray(teacher.q(**state))
                        legal = np.asarray(decision["record"]["feasible"], bool)
                        selected = ACTIONS.index(decision["picked_action"])
                        best = int(np.argmax(q))
                        if not legal[selected] or decision["picked_action"] != event["action"]:
                            raise ValueError("Action trace mismatch")
                        regret = max(0., float(q[best]-q[selected]))
                        cumulative_regret += regret
                        if row["policy"] == "fitted_dp":
                            error = float(np.max(np.abs(np.asarray(decision["q"])[legal]-q[legal])))
                            integrity["recomputed_fitted_dp_max_q_difference"] = max(error, integrity["recomputed_fitted_dp_max_q_difference"])
                        reward = (1. if event["answer"]["prediction"] == labels[event["job"]] else -1.) if event["action"] == "FIRE" else 0.
                        cost_increment = event["charged_cost"]-previous_cost
                        previous_cost = event["charged_cost"]
                        next_value = 0. if event["terminal"] else teacher.value(event["next_job"], event["next_tick"],
                            event["budget_after"], event["posterior_after"])
                        residual = reward-cost_increment+next_value-float(q[selected])
                        residuals[event["action"]] += residual
                        decision_rows.append(dict(seed=seed, split=split, session_id=sid, policy=row["policy"],
                            decision_index=decision_index, state=state, selected_action=ACTIONS[selected],
                            teacher_action=ACTIONS[best], regret=regret, teacher_q=np.where(legal, q, 0.).tolist(),
                            feasible=legal.tolist(), realized_td_residual=residual))
                        if event["action"] == "READ":
                            payload_hash = event["payload_sha256"]
                            if payload_hash not in packet_cache:
                                payload = tar.extractfile(sid+"/"+event["packet"]).read()
                                if hashlib.sha256(payload).hexdigest() != payload_hash:
                                    raise ValueError("Observed payload bytes disagree with archived evidence")
                                packet_cache[payload_hash] = int(json.loads(payload)["symbols"][0])
                                integrity["payload_hashes_verified"] += 1
                            symbol = packet_cache[payload_hash]
                            entry = observed_payloads[split].setdefault(payload_hash,
                                dict(seed=seed, symbol=symbol, observation=event["observation"],
                                     session_id=sid, packet=event["packet"], policies=[]))
                            if (entry["seed"], entry["symbol"], entry["observation"]) != (seed, symbol, event["observation"]):
                                raise ValueError("Conflicting duplicate observed payload receipt")
                            if row["policy"] not in entry["policies"]:
                                entry["policies"].append(row["policy"])
                    expected_utility = initial_value-cumulative_regret+sum(residuals.values())
                    error = abs(expected_utility-row["score"]["utility"])
                    integrity["max_path_decomposition_error"] = max(error, integrity["max_path_decomposition_error"])
                    episode_rows.append(dict(seed=seed, split=split, session_id=sid, policy=row["policy"],
                        utility=row["score"]["utility"], initial_fitted_value=initial_value,
                        path_teacher_regret=cumulative_regret, realization_residual=sum(residuals.values()),
                        residual_by_action=residuals, reads=row["counts"]["READ"], fires=row["counts"]["FIRE"]))

    policies = protocol["arms"]+protocol["additional_references"]
    split_summaries, confusions = {}, {}
    for split in ("test", "ood"):
        split_summaries[split] = {policy:summarize_policy(
            [r for r in episode_rows if r["split"] == split and r["policy"] == policy],
            [r for r in decision_rows if r["split"] == split and r["policy"] == policy], protocol["seeds"])
            for policy in policies}
        confusions[split] = {}
        for seed in protocol["seeds"]:
            items = [item for item in observed_payloads[split].values() if item["seed"] == seed]
            confusions[split][str(seed)] = dict(union_across_policies=matrix_receipt(items, models[seed]["confusion"]),
                by_policy={policy:matrix_receipt([item for item in items if policy in item["policies"]],
                    models[seed]["confusion"]) for policy in policies})
    training_summary = dict(cells={}, controllers={})
    for family in ("ordinary", "analytic"):
        values = [row["cellfits"][family] for row in training.values()]
        training_summary["cells"][family] = dict(converged=sum(v["converged"] for v in values), fits=len(values),
            mean_physical_theta_change_l2=float(np.mean([v["physical_theta_change_l2"] for v in values])),
            mean_loss=float(np.mean([v["loss"] for v in values])),
            train_read_rows=[v["train_read_rows"] for v in values],
            iterations=[v["iterations"] for v in values], nfev=[v["nfev"] for v in values],
            terminations=[v["termination"] for v in values])
    for arm in protocol["arms"]:
        values = [row["controllers"][arm] for row in training.values()]
        training_summary["controllers"][arm] = dict(
            mean_selected_validation_regret=float(np.mean([v["selected_validation_regret"] for v in values])),
            selected_validation_regrets=[v["selected_validation_regret"] for v in values],
            selected_updates=[v["selected_update"] for v in values])
    if integrity["max_path_decomposition_error"] > 1e-9 or integrity["recomputed_fitted_dp_max_q_difference"] > 1e-9:
        raise ArithmeticError("Fitted teacher replay or path identity failed")
    if source_identity() != freeze["source"] or any(digest(out/path) != h for path,h in inputs.items()):
        raise ValueError("Original evidence/source changed during read-only diagnosis")
    report = dict(schema="hcsn.factorial.exploratory.posthoc.v1", created_at=datetime.now(timezone.utc).isoformat(),
        exploratory=True, used_for_training=False, used_for_checkpoint_selection=False, used_for_admission=False,
        scope="Frozen-model read-only diagnosis; no parameter fitting, filtering, content re-inference, or confirmation rerun",
        teacher="Same full future=True fitted Bellman law as frozen fitted_dp, recomputed at every actual state for all policies",
        regret_scope="On-policy action approximation loss under the TRAIN-fitted law. Myopic/fixed references were not trained to minimize this full-task target.",
        decomposition="Actual utility = initial fitted V - cumulative on-policy teacher regret + realized TD residual sum. Residual mixes finite-sample outcome noise with possible model mismatch; it does not by itself identify misspecification.",
        confusion_scope="Unique payload hashes among actually executed selective READs, deduplicated across policies within split. Actual first symbol comes from hash-verified archived bytes; stored decoder observations are reused. Not a census or unbiased sample of unread packets.",
        diagnostic_script_sha256=digest(Path(__file__)), frozen_source=freeze["source"], inputs_sha256=inputs,
        training=training, training_summary=training_summary, splits=split_summaries,
        observed_decoder_confusion=confusions, unique_observed_payloads=observed_payloads,
        episode_rows=episode_rows, decision_rows=decision_rows, integrity=integrity,
        costs=dict(diagnostic_cpu_seconds=time.process_time()-cpu, diagnostic_wall_seconds=time.perf_counter()-wall,
                   separate_from_training_and_confirmation=True, content_inference_calls=0,
                   timing_scope="Diagnosis computation, evidence reading and input-integrity verification before final report serialization"))
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with destination.open("xb") as target:
        target.write(gzip.compress(encoded, mtime=0))
    print(json.dumps(dict(output=str(destination), sha256=digest(destination), bytes=destination.stat().st_size,
        costs=report["costs"], integrity=integrity, training_summary=training_summary,
        policy_summary={split:{policy:{**summary["seed_mean"], "mean_decision_teacher_regret":summary["mean_decision_teacher_regret"],
            "suboptimal_STOP":summary["suboptimal_STOP"], "premature_FIRE":summary["premature_FIRE"],
            "SKIP_when_READ_optimal":summary["SKIP_when_READ_optimal"], "teacher_optimal_decisions":summary["teacher_optimal_decisions"],
            "decisions":summary["decisions"]} for policy,summary in split_summaries[split].items()}
            for split in split_summaries},
        confusion_union={split:{seed:receipt["union_across_policies"] for seed,receipt in byseed.items()}
            for split,byseed in confusions.items()}), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
