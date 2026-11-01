"""Independent admission audit of frozen fits and complete native confirmation.

This evaluator never trains, selects, repairs or removes a candidate. Failures
are recorded in a create-only report. Publication proofs are supplied externally;
this program checks the identities and execution evidence available on disk.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np
import torch

from .independent_audit import _check, _numpy_representation, _reference_mask, _same_state
from .independent_audit import independent_paired_interval
from .model import FAMILIES, Policy, context_key, identity, registered_contexts
from .task import initial, public_features, successor

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected, label, tolerance=5e-12):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    _check(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), label + " shape/finite")
    error = float(np.max(np.abs(a-b))) if a.size else 0.
    _check(error <= tolerance, f"{label}: {error}")
    return error


def verify_sources(freeze):
    for relative, digest in freeze["source_sha256"].items():
        path = (REPO / relative).resolve()
        _check(path.is_relative_to(REPO), "source path escapes repository")
        _check(sha(path) == digest, "frozen source changed: " + relative)


def audit_models(freeze, training, protocol):
    expected = {(fit, family) for fit in protocol["fits"] for family in protocol["families"]}
    artifacts, policies, hashes, records, fits = {}, {}, {}, [], []
    for fit in protocol["fits"]:
        folder = training / f"fit_{fit}"
        datafile = folder / "data" / f"fit_{fit}_data.json"
        data, start, complete = read(datafile), read(folder/"models/STARTED.json"), read(folder/"models/COMPLETE.json")
        _check(sha(datafile) == freeze["training_data_sha256"][str(fit)] == start["data_sha256"] == complete["data_sha256"], "training data identity")
        _check(start["protocol"] == protocol and start["protocol_sha256"] == identity(protocol), "training protocol changed")
        _check(complete["confirmation_generated"] is False and start["confirmation_generated"] is False, "confirmation in training")
        _check(data["train"]["behavior_cell_independent"] and data["validation"]["behavior_cell_independent"], "cell-dependent behavior")
        _check(set(complete["models"]) == set(FAMILIES), "incomplete fit")
        for name, digest in complete["source_sha256"].items():
            _check(sha(HERE/name) == digest == start["source_sha256"][name], "training implementation identity")
        counts = np.zeros((2, 2), dtype=int)
        for item in data["calibration"]["rows"]:
            counts[item["symbol"], item["observation"]] += 1
        _check(int(counts.sum()) == protocol["calibration_count"], "calibration budget")
        _check(np.array_equal(counts.sum(axis=1), [protocol["calibration_count"]//2]*2), "calibration balance")
        close((counts+.5)/(counts.sum(axis=1, keepdims=True)+1), data["confusion"], "TRAIN confusion")
        for split in ("train", "validation"):
            _check(len(data[split]["episodes"]) == protocol[f"{split}_worlds"], "training world budget")
            _check(len(data[f"{split}_cohort"]["records"]) == protocol[f"{split}_worlds"], "training manifest count")
        rng, batch = np.random.default_rng(733000+fit), hashlib.sha256()
        for _ in range(protocol["updates"]):
            indices = rng.integers(0, len(data["train"]["rows"]), protocol["batch_states"])
            batch.update(indices.astype("<i8").tobytes())
        _check(batch.hexdigest() == complete["common_minibatch_sha256"], "actual registered minibatch plan")
        run_start, run_end = read(folder/"RUN_STARTED.json"), read(folder/"RUN_COMPLETE.json")
        duration = (datetime.fromisoformat(run_end["finished_at"])-datetime.fromisoformat(run_start["started_at"])).total_seconds()
        _check(duration > 0, "fit timestamp order")
        fits.append(dict(fit=fit, train_records=len(data["train"]["rows"]), validation_records=len(data["validation"]["rows"]),
                         calibration_count=int(counts.sum()), full_fit_wall_seconds=duration,
                         models_pipeline_timing=complete["total"], finished_at=run_end["finished_at"]))
    for record in freeze["models"]:
        encoded = (REPO/record["path"]).read_bytes()
        _check(hashlib.sha256(encoded).hexdigest() == record["sha256"], "encoded frozen model hash")
        raw = gzip.decompress(encoded)
        _check(hashlib.sha256(raw).hexdigest() == record["model_sha256"], "decoded frozen model hash")
        artifact = json.loads(raw)
        key = artifact["fit"], artifact["family"]
        _check(key in expected and key not in artifacts and key == (record["fit"], record["family"]), "model matrix/identity")
        fit, family = key
        folder = training/f"fit_{fit}"/"models"
        receipt, complete = read(folder/f"{family}_training.json"), read(folder/"COMPLETE.json")
        _check((folder/f"{family}.json").read_bytes() == raw, "published model differs from trained final model")
        _check(sha(folder/f"{family}_training.json") == complete["models"][family]["training_receipt"]["sha256"], "training receipt hash")
        _check(record["model_sha256"] == receipt["model"]["sha256"], "receipt model hash")
        _check(identity(artifact) == receipt["model_identity"], "artifact identity")
        _check(receipt["selected_update"] == protocol["updates"] and receipt["validation_used_for_selection"] is False, "selection/budget contract")
        _check([u["update"] for u in receipt["updates"]] == list(range(1, protocol["updates"]+1)), "missing optimizer updates")
        _check(receipt["initial_head_sha256"] == complete["common_initial_head_sha256"]
               and receipt["minibatch_sha256"] == complete["common_minibatch_sha256"], "unmatched initial head/minibatches")
        for update in receipt["updates"]:
            for name in ("loss", "gradient_norm_before_clip", "raw_gradient_before_clip", "raw_task_gradient_before_clip"):
                _check(np.isfinite(np.asarray(update[name], dtype=float)).all(), "nonfinite training record")
        policy = Policy(family, fit)
        _check(policy.head_identity() == receipt["initial_head_sha256"], "unregistered initial neural head")
        with torch.no_grad():
            for name, parameter in (("w1", policy.linear1.weight), ("b1", policy.linear1.bias),
                                    ("w2", policy.linear2.weight), ("b2", policy.linear2.bias)):
                parameter.copy_(torch.as_tensor(artifact["network"][name], dtype=torch.float64))
            if policy.cell is not None:
                policy.cell.raw.copy_(torch.as_tensor(artifact["kernel"]["raw"], dtype=torch.float64))
        _check(policy.head_identity() == receipt["final_head_sha256"], "trained final head differs")
        _check(policy.allocated_parameter_count == receipt["parameter_count_allocated"]
               and policy.effective_parameter_count == receipt["parameter_count_effective"], "parameter budget")
        maximum_table_error = 0.
        if policy.cell is not None:
            close(policy.cell.raw.detach(), receipt["final_raw"], "final raw", 0.)
            kernel = artifact["kernel"]
            _check(kernel["n_grid"] == 15 and kernel["n_states"] == 17, "finite state domain")
            rebuilt = policy.export()["kernel"]
            _check(kernel["mode"] == rebuilt["mode"] and kernel["feature_names"] == rebuilt["feature_names"], "kernel mode/feature identity")
            close(kernel["initial"], rebuilt["initial"], "initial finite distribution", 0.)
            close(list(kernel["physical"].values()), [rebuilt["physical"][k] for k in kernel["physical"]], "physical parameters")
            _check([context_key(c) for c in kernel["contexts"]] == [context_key(c) for c in registered_contexts()], "registered export contexts")
            for original, reconstructed in zip(kernel["contexts"], rebuilt["contexts"]):
                for field in ("transition", "features", "event_probability"):
                    maximum_table_error = max(maximum_table_error, close(original[field], reconstructed[field], "frozen export "+field))
            if family.startswith("ordinary_"):
                _check(kernel["raw"][4:] == [0., 0., 0.], "inactive ordinary parameters changed")
        else:
            _check(artifact["kernel"] is None, "raw-history model has a cell")
        artifacts[key], policies[key], hashes[key] = artifact, policy, record["model_sha256"]
        records.append(dict(fit=fit, family=family, encoded_bytes=len(encoded), decoded_bytes=len(raw),
                            model_sha256=record["model_sha256"], updates=len(receipt["updates"]),
                            maximum_rebuilt_table_error=maximum_table_error,
                            allocated_parameters=policy.allocated_parameter_count, effective_parameters=policy.effective_parameter_count,
                            raw_shift=receipt["raw_parameter_shift"], all_parameter_shift_l2=receipt["all_parameter_shift_l2"],
                            initial_validation_loss=receipt["initial_validation"]["loss"], final_validation_loss=receipt["final_validation"]["loss"],
                            training=receipt["training"], export_preparation=receipt["export_preparation"]))
    _check(set(artifacts) == expected, "incomplete 25-model matrix")
    return dict(models=records, fits=fits, total_optimizer_updates=sum(r["updates"] for r in records),
                matched_fit_controllers="One frozen model per fit/family, reused by fixed and value controllers",
                timing_limit="Fit timestamps cover full wall duration; models_pipeline_timing excludes earlier data preparation. Nested timer attributions are not additional costs."), artifacts, policies, hashes


def fixed_choice(state, legal, belief):
    submit = 4 + int(belief > .5)
    if max(belief, 1-belief) >= .8 or state["tick"] == 6 or (state["budget"] == 0 and state["pending"] is None):
        return submit
    return next((action for action in (3, 2, 1) if legal[action]), submit)


def native_check(row, public, policy, artifact, model_hash, label, injected_missing):
    episode, totals, branches = row["episode"], Counter(), Counter()
    output = episode["native_output"]
    _check(output["actual_native"] and not output["production_activation"] and output["authority"] == "DENY_ALL", "native identity/authority")
    _check(output["mode"] == "experiment" and output["forced_control"] is False, "qualification in confirmation")
    _check((output["fit"], output["family"], output["controller"]) == (row["fit"], row["family"], row["controller"]), "native candidate identity")
    identity_before = output["before"]["identity"]
    _check(identity_before == output["after"]["identity"] and identity_before["policy_sha256"] == model_hash, "frozen policy identity")
    _check(identity_before["seed"] == row["seed"] and identity_before["controller"] == row["controller"], "seed/controller identity")
    command = episode["command"]
    arguments = dict(zip(command[1::2], command[2::2]))
    _check(set(arguments) == {"--public", "--content-model", "--policy", "--controller", "--snapshot", "--seed", "--steps"}
           and len(command) == 15, "unexpected formal CLI input")
    _check(read(arguments["--public"]) == public and sha(arguments["--public"]) == identity_before["public_sha256"], "public file identity")
    _check(sha(arguments["--policy"]) == model_hash, "native policy file changed")
    _check(sha(arguments["--content-model"]) == identity_before["content_model_sha256"]
           == sha(REPO/"tools/hcsn/round9_20261031/native/fixtures/fullhx.json"), "pinned content model identity")
    _check(sha(arguments["--snapshot"]) == output["acknowledged_sha256"], "persisted acknowledged frontier")
    _check(read(arguments["--snapshot"]) == output["after"], "persisted task/cell/content/ledger differs")
    state = initial(public)
    _same_state(output["before"]["task"], state)
    cell = dict(index=7, rng_hex=f"{row['seed']:016x}", draws=0, events=0)
    _check(output["before"]["cell"] == cell, "initial cell/RNG")
    network = {k: np.asarray(v) for k, v in artifact["network"].items()}
    tables = {} if artifact["kernel"] is None else {context_key(c): c for c in artifact["kernel"]["contexts"]}
    maximum_error, initial_scores = 0., None
    _check(len(output["receipts"]) == len(episode["decisions"]), "native decision count")
    for index, receipt in enumerate(output["receipts"]):
        _same_state(receipt["before"], state)
        _check(not receipt["forced_control"] and receipt["mode"] == "experiment", "forced formal receipt")
        _check(receipt["sequence"] == index+1 and receipt["cell_before"] == cell, "receipt/cell sequence")
        pub = public_features(public, state)
        representation = _numpy_representation(policy, state)[0 if policy.cell is None else cell["index"]]
        score = network["w2"] @ np.tanh(network["w1"] @ np.r_[pub, representation]+network["b1"])+network["b2"]
        logit = float(score[6])
        belief = 1/(1+math.exp(-logit)) if logit >= 0 else math.exp(logit)/(1+math.exp(logit))
        maximum_error = max(maximum_error, close(pub, receipt["public_features"], "public input"),
                            close(representation, receipt["representation_features"], "independent representation"),
                            close(score[:6], receipt["q"], "independent native Q"), close(belief, receipt["belief"], "native belief"))
        if initial_scores is None:
            initial_scores = dict(state=state, cell=cell, q=receipt["q"], belief=receipt["belief"], public=pub.tolist())
        mask = _reference_mask(public, state)
        _check(receipt["legal"] == mask, "formal legal mask")
        fixed, value = fixed_choice(state, mask, belief), int(np.argmax(np.where(mask, score[:6], -np.inf)))
        branches[(fixed, value)] += 1
        action = receipt["action"]
        _check(action == (fixed if row["controller"] == "fixed" else value), "same-state controller route")
        pending = state["pending"]
        if action == 2:
            pending = dict(source_tick=state["tick"], due_tick=state["tick"]+public["read_delay"][state["tick"]])
        due = pending["source_tick"] if action not in (0, 4, 5) and pending is not None and pending["due_tick"] == state["tick"]+1 else None
        _check(receipt["due_source"] == due, "read-before-content ordering")
        audit = receipt["read_audit"]
        _check(len(receipt["attempted_packet_paths"]) == audit["open_attempts"] == int(due is not None), "due-only packet access")
        _check(len(receipt["opened_packet_paths"]) == audit["successful_opens"], "successful open count")
        _check(receipt["actual_content_calls"] == audit["model_executions"], "actual content execution count")
        if due is None:
            _check(audit == dict(open_attempts=0, successful_opens=0, bytes_read=0, model_executions=0), "unsolicited read")
        else:
            failure = bool(receipt["completion"].get("failure", False))
            _check(failure == injected_missing[due], "unexpected content failure")
            _check(audit["successful_opens"] == audit["model_executions"] == int(not failure), "failure/content call count")
            if not failure:
                _check(receipt["content"]["payload_sha256"] == public["packet_sha256"][due], "due content identity")
        next_cell = dict(cell)
        expected_event = False
        if action not in (0, 4, 5) and policy.cell is not None:
            table = tables[(public["duration"][state["tick"]], state["last_symbol"], state["last_reliability"])]
            mask64 = (1 << 64)-1
            rng = (int(cell["rng_hex"], 16)+0x9E3779B97F4A7C15) & mask64
            z = ((rng ^ (rng >> 30))*0xBF58476D1CE4E5B9) & mask64
            z = ((z ^ (z >> 27))*0x94D049BB133111EB) & mask64
            uniform = ((z ^ (z >> 31)) >> 11)*2.**-53
            position = min(int(np.searchsorted(np.cumsum(table["transition"][cell["index"]]), uniform, side="right")), 16)
            expected_event = cell["index"] < 15 <= position
            next_cell.update(index=position, rng_hex=f"{rng:016x}", draws=cell["draws"]+1, events=cell["events"]+int(expected_event))
            _check(receipt["draw"] is not None, "missing latent draw")
            _check(receipt["draw"]["before"] == cell["index"] and receipt["draw"]["after"] == position
                   and receipt["draw"]["event"] == expected_event, "draw receipt state/event")
            close(receipt["draw"]["uniform"], uniform, "independent SplitMix64 uniform", 0.)
            close(receipt["draw"]["probability_of_event"], table["event_probability"][cell["index"]], "event forecast")
        else:
            _check(receipt["draw"] is None, "unnecessary latent draw")
        _check(receipt["cell_after"] == next_cell and receipt["cell_event"] == expected_event, "complete hard cell/RNG successor")
        normalized = episode["decisions"][index]
        _check(normalized["native_receipt"] == receipt and normalized["action"] == action, "normalized/raw receipt identity")
        _same_state(normalized["before"], state)
        close(normalized["q"], receipt["q"], "normalized Q", 0.)
        close(normalized["belief"], receipt["belief"], "normalized belief", 0.)
        after = successor(public, state, action, receipt["completion"])
        _same_state(receipt["after"], after)
        close(receipt["charges"], after["charges"]-state["charges"], "incremental fee")
        close(receipt["duration"], after["elapsed"]-state["elapsed"], "elapsed interval")
        totals.update(audit)
        totals.update(receipt["costs"])
        totals.update({k: receipt[k] for k in ("checkpoint_bytes", "journal_bytes", "witness_bytes", "owner_nanos")})
        state, cell = after, next_cell
    _same_state(state, output["after"]["task"])
    _same_state(state, episode["final_state"])
    _check(state["terminal"] and cell == output["after"]["cell"], "terminal frontier")
    _check(output["persistence_bytes"] == output["initial_persistence_bytes"]+totals["checkpoint_bytes"]+totals["journal_bytes"]+totals["witness_bytes"], "persistence bytes")
    close(row["metrics"]["content_calls"], totals["model_executions"], "metric content calls", 0.)
    close(row["metrics"]["persistence_bytes"], output["persistence_bytes"], "metric persistence", 0.)
    for key in ("wall", "cpu"):
        close(row["metrics"][f"native_{key}_seconds"], output[f"{key}_nanos"]/1e9, "native clock attribution")
    totals.update({k: output[k] for k in ("artifact_load_nanos", "wall_nanos", "cpu_nanos", "initial_persistence_bytes", "persistence_bytes")})
    totals["external_wall_seconds"] += episode["wall_seconds"]
    totals["external_cpu_seconds"] += episode["cpu_seconds"]
    return maximum_error, initial_scores, totals, branches, output["source_digest"]


def audit_confirmation(root, freeze, training_report, artifacts, policies, hashes, protocol):
    start, summary, result_rows = read(root/"STARTED.json"), read(root/"SUMMARY.json"), read(root/"RESULTS.json")
    build = read(HERE/"evidence/NATIVE_BUILD.json")
    _check(start["binary_sha256"] == build["binary_sha256"] == sha(build["binary"]), "qualification/confirmation binary identity")
    _check(start["confirmation_worlds_preexisting"] is False, "confirmation existed before model freeze")
    _check(all(datetime.fromisoformat(f["finished_at"]) < datetime.fromisoformat(start["started_at"]) for f in training_report["fits"]), "confirmation precedes training completion")
    expected = {(fit, split, family, controller) for fit in protocol["fits"] for split in ("iid", "ood")
                for family in protocol["families"]+[protocol["reference_family"]] for controller in protocol["controllers"]}
    groups, identities, raw_rows, first, costs, branch_counts, source_digests = {}, set(), {}, {}, defaultdict(Counter), defaultdict(Counter), set()
    worlds, cohorts = {}, []
    for fit in protocol["fits"]:
        for split in ("iid", "ood"):
            cohort_file = root/f"cohort_{fit}_{split}.json"
            cohort = read(cohort_file)
            _check(len(cohort["records"]) == protocol[f"{split}_worlds"], "confirmation world budget")
            for relative, digest in cohort["files"].items():
                _check(sha(root/"worlds"/relative) == digest, "confirmation world hash")
            for item in cohort["records"]:
                folder = Path(item["folder"])
                worlds[(fit, split, item["id"])] = (read(folder/"public.json"), read(folder/"evaluator.json"))
            cohorts.append(dict(fit=fit, split=split, sha256=sha(cohort_file), packets=len(cohort["payload_sha256"])))
    maximum_score_error, native_count, binary_paths = 0., 0, set()
    for fit, split, family, controller in sorted(expected):
        path = root/"raw"/f"{fit}_{split}_{family}_{controller}.json.gz"
        rows = json.loads(gzip.decompress(path.read_bytes()))
        group = []
        for row in rows:
            key = row["fit"], row["split"], row["family"], row["controller"]
            full_key = key+(row["world"],)
            _check(key == (fit, split, family, controller) and full_key not in identities, "raw coverage/duplicate")
            _check(row["forced"] is False and not row.get("failure"), "forced/failed confirmation")
            identities.add(full_key)
            public, evaluator = worlds[(fit, split, row["world"])]
            state = row["episode"]["final_state"]
            _check(state["terminal"], "unterminated episode")
            reward = 0 if state["submitted"] is None else (1 if state["submitted"] == evaluator["label"] else -1)
            close(row["metrics"]["reward"], reward, "actual reward", 0.)
            close(row["metrics"]["utility"], reward-state["charges"], "actual utility")
            expected_outcome = dict(charges=state["charges"], elapsed=state["elapsed"],
                                    correct=float(state["submitted"] == evaluator["label"]), submitted=state["submitted"] is not None,
                                    reads_requested=3-state["budget"], reads_completed=len(state["history"]))
            for name, value in expected_outcome.items():
                close(row["metrics"][name], value, "actual outcome "+name)
            decisions = row["episode"]["decisions"]
            brier = math.fsum((d["belief"]-evaluator["label"])**2 for d in decisions)/len(decisions)
            q_error = math.fsum((d["q"][d["action"]]-(reward-state["charges"]+d["before"]["charges"]))**2 for d in decisions)/len(decisions)
            close(row["metrics"]["belief_brier"], brier, "actual belief calibration")
            close(row["metrics"]["selected_q_remaining_return_mse"], q_error, "remaining-return calibration")
            _check(all(math.isfinite(v) for v in row["metrics"].values() if isinstance(v, (int, float))), "nonfinite metric")
            if family != protocol["reference_family"]:
                binary_paths.add(row["episode"]["command"][0])
                error, initial_scores, totals, branches, digest = native_check(row, public, policies[(fit, family)], artifacts[(fit, family)], hashes[(fit, family)], evaluator["label"], evaluator["injected_missing"])
                maximum_score_error = max(maximum_score_error, error)
                native_count += 1
                source_digests.add(digest)
                first[(fit, split, family, row["world"], controller)] = initial_scores
                costs[(split, family, controller)].update(totals)
                branch_counts[(split, family, controller)].update(branches)
            raw_rows[full_key] = {k: v for k, v in row.items() if k != "episode"}
            group.append(raw_rows[full_key])
        _check(len(group) == protocol[f"{split}_worlds"], "raw group count")
        groups[(fit, split, family, controller)] = group
    _check(len(result_rows) == len(identities) == 4800 and native_count == 4000, "full evaluation budget")
    _check(source_digests == {build["source_digest"]}, "native source differs from qualified build")
    _check(all(sha(path) == build["binary_sha256"] for path in binary_paths), "formal command binary differs")
    seen = set()
    for row in result_rows:
        key = tuple(row[k] for k in ("fit", "split", "family", "controller", "world"))
        _check(key not in seen and raw_rows[key] == row, "RESULTS/raw identity")
        seen.add(key)
    for fit, split, family, controller in expected:
        reference = {(r["world"], r["seed"]) for r in groups[(fit, split, protocol["families"][0], "fixed")]}
        _check({(r["world"], r["seed"]) for r in groups[(fit, split, family, controller)]} == reference, "unpaired worlds/latent seeds")
    for key, a in first.items():
        if key[-1] == "fixed":
            _check(a == first[key[:-1]+("value",)], "controller initial information or frozen scores differ")
    fit_summary = {(r["fit"], r["split"], r["family"], r["controller"]): r for r in summary["fit_means"]}
    _check(set(fit_summary) == expected and len(summary["fit_means"]) == len(expected), "summary fit coverage")
    for key, rows in groups.items():
        _check(fit_summary[key]["count"] == len(rows), "summary fit count")
        for metric, value in fit_summary[key]["metrics"].items():
            close(value, math.fsum(r["metrics"][metric] for r in rows)/len(rows), "independent fit mean "+metric, 1e-10)
    for item in summary["aggregate"]:
        for metric, value in item["metrics"].items():
            values = [fit_summary[(fit, item["split"], item["family"], item["controller"])]["metrics"][metric] for fit in protocol["fits"]]
            close(value, math.fsum(values)/5, "independent aggregate "+metric, 1e-10)
    contrasts = []
    for contrast in protocol["primary_contrasts"]:
        positive, negative = contrast["positive"].split("/"), contrast["negative"].split("/")
        for split in ("iid", "ood"):
            pair = [[math.fsum(r["metrics"]["utility"] for r in groups[(fit, split, *arm)])/protocol[f"{split}_worlds"] for fit in protocol["fits"]] for arm in (positive, negative)]
            result = independent_paired_interval(*pair)
            reported = next(r for r in summary["primary_contrasts"] if r["name"] == contrast["name"] and r["split"] == split)
            close([reported["mean"], reported["lower"], reported["upper"]], [result["mean"], *result["interval"]], "fit-level adjusted interval")
            _check(reported["benefit_gate"] == result["superiority"], "practical utility gate")
            contrasts.append(dict(name=contrast["name"], split=split, **result))
    return dict(episodes=len(result_rows), native_episodes=native_count, fitted_reference_episodes=800,
                groups=len(groups), frozen_initial_controller_pairs=len(first)//2,
                maximum_independent_native_score_error=maximum_score_error, native_source_digests=sorted(source_digests),
                binary_sha256=build["binary_sha256"], qualified_build_sha256=sha(HERE/"evidence/NATIVE_BUILD.json"),
                cohorts=cohorts, primary_contrasts=contrasts,
                native_cost_totals=[dict(split=k[0], family=k[1], controller=k[2], **dict(v)) for k, v in sorted(costs.items())],
                same_state_control=[dict(split=k[0], family=k[1], executed_controller=k[2], decisions=sum(v.values()),
                                         recommendation_disagreements=sum(count for (a, b), count in v.items() if a != b),
                                         action_pairs=[dict(fixed=a, value=b, count=n) for (a, b), n in sorted(v.items())]) for k, v in sorted(branch_counts.items())],
                limits=["Counterfactual same-state recommendations are checked, not counterfactual realized returns.",
                        "Native internal clocks are nested within external process CPU/wall; do not add them.",
                        "Measured byte writes are not resident memory or energy measurements.",
                        "Five-fit Student t intervals are an approximation with low power."])


def audit_timing_replays(root, primary, protocol):
    records = []
    for fit in protocol["fits"]:
        timing = read(root/"logs"/f"fit_{fit}_process.json")
        _check(timing["returncode"] == 0 and timing["extra_independent_fits"] == 0, "failed or selected timing replay")
        _check(timing["primary_models_unchanged"] and len(timing["model_equality"]) == 5, "incomplete timing equality")
        for family in protocol["families"]:
            a = primary/f"fit_{fit}"/"models"/f"{family}.json"
            b = root/f"fit_{fit}"/"models"/f"{family}.json"
            _check(a.read_bytes() == b.read_bytes(), "timing replay changed fitted model")
            recorded = next(item for item in timing["model_equality"] if item["family"] == family)
            _check(recorded["byte_identical"] and recorded["primary_sha256"] == recorded["replay_sha256"] == sha(a), "replay hash claim")
        for name in ("wall_seconds", "user_cpu_seconds", "system_cpu_seconds", "total_cpu_seconds", "peak_rss_kib"):
            _check(math.isfinite(timing[name]) and timing[name] > 0, "invalid whole-process resource measurement")
        close(timing["total_cpu_seconds"], timing["user_cpu_seconds"]+timing["system_cpu_seconds"], "whole-process CPU sum")
        records.append(timing)
    return dict(records=records, byte_identical_models=25, additional_independent_fits=0,
                total_cpu_seconds=sum(r["total_cpu_seconds"] for r in records),
                scope="Separate deterministic whole-process timing replays; these are additional reproduction costs and not retroactive measurements of primary fits.")


def audit_trained_ack(hashes, protocol):
    path = HERE/"evidence/TRAINED_ACK_QUALIFICATION.json"
    report, build = read(path), read(HERE/"evidence/NATIVE_BUILD.json")
    _check(report["passed"] and report["every_action_autonomous"] and not report["forced_control"], "trained ACK qualification")
    _check(report["driver_sha256"] == sha(HERE/"native/trained_qualification.py"), "ACK audit driver identity")
    _check(report["binary_sha256"] == build["binary_sha256"] and report["source_digest"] == build["source_digest"], "ACK binary/source identity")
    _check({(r["fit"], r["family"]): r["sha256"] for r in report["models"]} == hashes, "ACK model freeze identity")
    outputs = {}
    for run in report["runs"]:
        folder = Path(run["output_directory"])
        _check(run["returncode"] == 0 and sha(folder/"stdout.json") == run["stdout_sha256"]
               and sha(folder/"stderr.txt") == run["stderr_sha256"], "ACK raw process evidence")
        output = read(folder/"stdout.json")
        key = output["fit"], output["family"], output["controller"], folder.name
        _check(key not in outputs and not output["forced_control"] and output["mode"] == "qualification", "ACK run scope")
        _check(output["before"]["identity"]["policy_sha256"] == hashes[key[:2]], "ACK raw weight identity")
        _check(output["external_ack_verified"] == run["resume"], "external ACK verification")
        outputs[key] = output
    expected = {(fit, family, controller) for fit in protocol["fits"] for family in protocol["families"] for controller in protocol["controllers"]}
    _check({(r["fit"], r["family"], r["controller"]) for r in report["cases"]} == expected
           and len(report["cases"]) == 50 and len(outputs) == 150, "ACK complete case matrix")
    logical_pair = ("schema", "identity", "sequence", "task", "cell", "content", "ledger")
    logical_receipt = ("sequence", "action", "forced_control", "mode", "before", "after", "public_features",
                       "representation_features", "q", "belief_logit", "belief", "legal", "cell_before", "cell_after",
                       "cell_event", "draw", "due_source", "completion", "content", "content_error", "read_audit", "actual_content_calls")
    for key in expected:
        full, first, resumed = [outputs[key+(part,)] for part in ("continuous", "split_first", "split_resumed")]
        _check(first["after"] == resumed["before"], "ACK exact restored frontier")
        _check(all(full["after"][name] == resumed["after"][name] for name in logical_pair), "continuous/resumed final logical equality")
        combined = first["receipts"]+resumed["receipts"]
        _check(len(combined) == len(full["receipts"]), "ACK receipt count")
        for a, b in zip(full["receipts"], combined):
            _check(all(a[name] == b[name] for name in logical_receipt), "continuous/resumed logical receipt equality")
    return dict(cases=50, actual_processes=150, model_hashes_matched=25,
                source_report_sha256=sha(path), classifications=report["classifications"],
                pending_dispositions=report["pending_dispositions"],
                scope="Separate validation-world recovery qualification; no added confirmation episodes or independent fits. Runtime checkpoint hashes/timers can differ between independent runs.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--model-freeze", type=Path, default=HERE/"MODEL_FREEZE.json")
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--timing-replays", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _check(not args.output.exists(), "audit report already exists")
    torch.set_num_threads(1)
    report = dict(schema="digital-read-before-independent-final-audit-v1", started_unix=time.time(),
                  auditor_sha256=sha(__file__), model_freeze_sha256=sha(args.model_freeze))
    try:
        freeze, protocol = read(args.model_freeze), read(HERE/"protocol.json")
        verify_sources(freeze)
        report["models"], artifacts, policies, hashes = audit_models(freeze, args.training, protocol)
        if args.confirmation:
            _check(read(args.confirmation/"STARTED.json")["model_freeze_sha256"] == report["model_freeze_sha256"], "confirmation model freeze identity")
            report["ack_recovery"] = audit_trained_ack(hashes, protocol)
            report["confirmation"] = audit_confirmation(args.confirmation, freeze, report["models"], artifacts, policies, hashes, protocol)
        if args.timing_replays:
            report["timing_replays"] = audit_timing_replays(args.timing_replays, args.training, protocol)
        verify_sources(freeze)
        _check(report["auditor_sha256"] == sha(__file__), "auditor changed during execution")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        report["finished_unix"] = time.time()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(dict(output=str(args.output), status=report["status"])))


if __name__ == "__main__":
    main()
