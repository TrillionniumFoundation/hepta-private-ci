"""Independent prepared-data/model review before any Round 4 confirmation.

This verifier does not regenerate confirmation observations, train models, or
select replacement parameters. It independently checks prepared identities,
objective changes, selected candidates, and dense conditioning references.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import expit

from .. import learners, task
from ..runtime import digest as document_digest
from . import calibration, calibration_study, freeze, math_validation, runtime_study
from .runtime_codec import Encoder, MODES


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


class Review:
    def __init__(self):
        self.checks = 0
        self.failures = []
        self.maximum_errors = {}

    def require(self, condition, label):
        self.checks += 1
        if not condition:
            self.failures.append(label)

    def close(self, actual, expected, tolerance, label):
        a, b = np.asarray(actual), np.asarray(expected)
        if a.shape != b.shape:
            self.require(False, label+": shape")
            return
        equal = a == b
        finite = np.isfinite(a) & np.isfinite(b)
        valid = bool(np.all(finite | equal))
        error = float(np.max(np.where(finite, abs(np.where(finite, a, 0)-np.where(finite, b, 0)), 0))) if a.size else 0.0
        self.maximum_errors[label.split(":")[0]] = max(error, self.maximum_errors.get(label.split(":")[0], 0.0))
        self.require(valid and error <= tolerance, label)


def fit_loss(parameters, datasets):
    rows = [task.combine_training(data) for data in datasets]
    history = {key: np.concatenate([row[0][key] for row in rows]) for key in rows[0][0]}
    target = np.concatenate([row[1] for row in rows])
    mean, variance = learners.predict({"kind": "filter", "parameters": parameters}, history)
    return float((.5*(np.log(2*np.pi*variance)+(target-mean)**2/variance)).mean())


def review_fit(book, fit, datasets, label):
    initial, final = fit["initial_parameters"], fit["final_parameters"]
    book.require(fit["dataset_digests"] == [task.dataset_digest(data) for data in datasets], label+": data binding")
    book.require(fit["training_trajectories"] == sum(len(data["ids"]) for data in datasets), label+": label count")
    book.require(all(data["split"] in ("train", "retention_train") for data in datasets), label+": fit split")
    book.require(np.linalg.norm(np.asarray(final)-initial) > 0, label+": dynamics changed")
    before, after = fit_loss(initial, datasets), fit_loss(final, datasets)
    book.close(fit["objective_trace"][0], before, 2e-11, "component_initial_objective:"+label)
    book.require(after <= before+1e-8, label+": optimized training objective")


def verify_candidate_scores(book, checkpoint, datasets, contexts, label):
    """Recompute every retained development score from its actual target rows."""
    models, selections = checkpoint["models"], checkpoint["selection"]
    targets = [task.targets(datasets[name])[:, 1:] for name in ("OLD_DEV", "NEW_DEV")]
    histories = [task.history(datasets[name]) for name in ("OLD_DEV", "NEW_DEV")]
    caches = {count: [calibration.component_cache(models["mixture_context" if count else "mixture_zero"], history, contexts[name])
                     for name, history in zip(("OLD_DEV", "NEW_DEV"), histories)] for count in (0, 8)}
    anchor_means, anchor_variances = learners.predict(models["frozen"]["anchor"], histories[0])
    anchor_loss = .5*(np.log(2*np.pi*anchor_variances[:, 1:])+(targets[0]-anchor_means[:, 1:])**2/anchor_variances[:, 1:])
    for arm, selection in selections.items():
        for candidate in selection["candidates"]:
            losses = []
            for index, target in enumerate(targets):
                if arm == "replay":
                    strength = candidate["strength"]
                    parameters = ((1-strength)*np.asarray(models["frozen"]["anchor"]["parameters"])
                                  +strength*np.asarray(checkpoint["replay_state"]["parameters"]))
                    m, v = learners.predict({"kind": "filter", "parameters": parameters}, histories[index])
                    loss = .5*(np.log(2*np.pi*v[:, 1:])+(target-m[:, 1:])**2/v[:, 1:])
                else:
                    cache = caches[models[arm]["context_count"]][index]
                    m, v = cache["means"][:, 1:], cache["variances"][:, 1:]
                    prior = candidate["prior"]
                    if prior == 0:
                        logw = np.tile([0., -np.inf], (len(target), 1))
                    elif prior == 1:
                        logw = np.tile([-np.inf, 0.], (len(target), 1))
                    else:
                        evidence = cache["query_log_likelihoods"]+cache["context_log_likelihoods"]
                        logits = np.log(prior)-np.log1p(-prior)+evidence[:, 1]-evidence[:, 0]
                        logw = np.column_stack((-np.logaddexp(0., logits), -np.logaddexp(0., -logits)))
                    if models[arm]["projection"]:
                        w = np.exp(logw)[:, None, :]
                        mean = (w*m).sum(-1)
                        variance = (w*(v+(m-mean[..., None])**2)).sum(-1)
                        loss = .5*(np.log(2*np.pi*variance)+(target-mean)**2/variance)
                    else:
                        components = logw[:, None, :]-.5*(np.log(2*np.pi*v)+(target[..., None]-m)**2/v)
                        loss = -np.logaddexp(components[..., 0], components[..., 1])
                losses.append(loss)
            delta = (losses[0]-anchor_loss).mean(1)
            old_mean, se = float(delta.mean()), float(delta.std(ddof=1)/np.sqrt(len(delta)))
            book.close(candidate["old_nll_change"], old_mean, 2e-11, "candidate_old_nll:"+label+"/"+arm)
            book.close(candidate["old_upper_heuristic"], old_mean+1.645*se, 2e-11, "candidate_old_guard:"+label+"/"+arm)
            book.close(candidate["new_nll"], float(losses[1].mean()), 2e-11, "candidate_new_nll:"+label+"/"+arm)


def verify_calibration(book, run_dir):
    root = run_dir/"calibration_prepared"
    prepared = read(root/"PREPARED.json")
    registration = calibration_study.registration()
    book.require(prepared["registration"] == registration, "calibration registration exact")
    book.require(prepared["holdouts_constructed"] is False, "calibration no holdouts")
    for relative, expected in prepared["source_sha256"].items():
        book.require(sha(freeze.REPO/relative) == expected, "prepared calibration source:"+relative)
    for relative, expected in prepared["artifacts_sha256"].items():
        book.require(sha(root/relative) == expected, "prepared calibration artifact:"+relative)
    all_seed_values = set()
    expected_paths = {"PREPARED.json", *prepared["artifacts_sha256"]}
    actual_paths = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    book.require(expected_paths == actual_paths, "calibration complete prepared inventory")
    checkpoint_count, selected_candidates, prior_fits = 0, 0, 0
    for seed in registration["seeds"]:
        directory = root/f"seed_{seed}"
        original = calibration_study.load(directory/"ORIGINAL_TRAIN.npz")
        retained = calibration_study.subset(original, registration["replay_rows"])
        anchor = read(directory/"ANCHOR.json")
        review_fit(book, anchor["fit"], [original], f"anchor seed{seed}")
        original_seed = calibration_study.data_seed(registration, seed, 99, 1)
        book.require(int(original["seed"]) == original_seed and original["split"] == "train", "original train seed/split")
        all_seed_values.update((original_seed, original_seed+50))
        previous = None
        for window, environment in enumerate(registration["windows"]):
            prefix = f"window_{window:02d}"
            path = directory/(prefix+"_CHECKPOINT.json")
            checkpoint = read(path)
            label = f"seed{seed}/window{window}"
            book.require(checkpoint["previous_checkpoint_sha256"] == previous, label+": checkpoint chain")
            previous = sha(path)
            book.require(checkpoint["holdout_used"] is False and checkpoint["query_time_hidden_regime_input"] is False,
                         label+": no hidden confirmation fields")
            book.require(set(checkpoint["models"]) == set(calibration_study.ARMS), label+": complete arms")
            datasets, contexts = {}, {}
            for name, code in (("TRAIN", 1), ("OLD_DEV", 2), ("NEW_DEV", 3)):
                datasets[name] = calibration_study.load(directory/(prefix+"_"+name+".npz"))
                contexts[name] = calibration_study.load(directory/(prefix+"_"+name+"_CONTEXT.npz"))
                expected = calibration_study.data_seed(registration, seed, window, code)
                book.require(datasets[name]["seed"] == expected, label+": seed "+name)
                all_seed_values.update((expected, expected+50))
                book.require(set(contexts[name]) == {"obs", "times", "mask", "occupied", "obs_var"},
                             label+": public-only context "+name)
                book.require(len(contexts[name]["obs"]) == 8*len(datasets[name]["ids"]), label+": context budget "+name)
                book.require(datasets[name]["law"] == ("gaussian" if name == "OLD_DEV" else environment), label+": environment "+name)
            for kind, data in (("online", [datasets["TRAIN"]]), ("replay", [retained, datasets["TRAIN"]])):
                fit = checkpoint["component_training"][kind]
                review_fit(book, fit, data, label+"/"+kind)
                book.close(checkpoint[kind+"_state"]["parameters"], fit["final_parameters"], 0,
                           "component_checkpoint_parameters:"+label+"/"+kind)
            for arm, selection in checkpoint["selection"].items():
                candidates = selection["candidates"]
                book.require(len(candidates) == 21, label+": candidate count "+arm)
                eligible = [i for i, candidate in enumerate(candidates) if candidate["old_upper_heuristic"] <= .02]
                chosen = min(eligible, key=lambda i: (candidates[i]["new_nll"], i))
                book.require(chosen == selection["selected_index"], label+": deterministic selected candidate "+arm)
                book.require(selection["development_labelled_queries"] == 512, label+": full development budget "+arm)
                for candidate in candidates:
                    book.require(candidate["eligible"] == (candidate["old_upper_heuristic"] <= .02), label+": eligibility "+arm)
                if arm != "replay":
                    book.close(checkpoint["models"][arm]["prior"], candidates[chosen]["prior"], 0,
                               "selected_prior:"+label+"/"+arm)
                selected_candidates += len(candidates)
            for arm, fit in checkpoint["prior_training"].items():
                book.require(fit["training_trajectories"] == 512, label+": prior fit labels "+arm)
                book.require(fit["dataset_digests"] == [task.dataset_digest(retained), task.dataset_digest(datasets["TRAIN"])],
                             label+": prior training bindings "+arm)
                book.close(abs(np.log(fit["fitted_prior"])-np.log1p(-fit["fitted_prior"])), fit["prior_logit_change"],
                           2e-12, "prior_changed_parameter:"+label+"/"+arm)
                book.require(fit["objective_trace"][0]["prior_logit"] == 0.0, label+": prior initial iterate "+arm)
                prior_fits += 1
            verify_candidate_scores(book, checkpoint, datasets, contexts, label)
            models = checkpoint["models"]
            book.require(models["mixture_context"] == models["mixture_classical"], label+": classical identical parameters")
            book.require(models["mixture_q24"] == models["mixture_q24_classical"], label+": Q24 classical identical parameters")
            book.require({**models["mixture_context"], "projection": True} == models["same_weight_moment"], label+": moment ablation only")
            book.require({**models["mixture_context"], "parameter_q24": True} == models["mixture_q24"], label+": Q24 ablation only")
            query = task.history(calibration_study.subset(datasets["NEW_DEV"], 4))
            context = {key: value[:32] for key, value in contexts["NEW_DEV"].items()}
            model = models["mixture_context"]
            actual = calibration.predict_distribution(model, query, context)
            references, context_evidence = [], []
            for component in (model["anchor"], model["adaptive"]):
                references.append(math_validation.dense_component(query, component["parameters"]))
                context_evidence.append(math_validation.dense_component(context, component["parameters"])[2].reshape(4, 8).sum(1))
            book.close(actual["means"], np.stack([ref[0] for ref in references], -1), 2e-11,
                       "prepared_dense_means:"+label)
            book.close(actual["variances"], np.stack([ref[1] for ref in references], -1), 2e-11,
                       "prepared_dense_variances:"+label)
            p = model["prior"]
            if p in (0., 1.):
                expected = np.full(4, p)
            else:
                expected = expit(np.log(p)-np.log1p(-p)+references[1][2]-references[0][2]
                                 +context_evidence[1]-context_evidence[0])
            book.close(actual["weights"][:, 1], expected, 2e-11, "prepared_dense_context_weights:"+label)
            checkpoint_count += 1
    confirmation_seed_values = set()
    for seed in registration["seeds"]:
        for window, code in [(99, 5), *[(window, 4) for window in range(12)]]:
            number = calibration_study.data_seed(registration, seed, window, code, True)
            confirmation_seed_values.update((number, number+50))
    book.require(all_seed_values.isdisjoint(confirmation_seed_values), "calibration train/confirmation seed identities disjoint")
    book.require(checkpoint_count == 60 and prior_fits == 240 and selected_candidates == 6300,
                 "complete sixty-window preparation")
    return {"checkpoints": checkpoint_count, "prior_fits": prior_fits, "development_candidates": selected_candidates,
            "prepared_artifacts": len(prepared["artifacts_sha256"]), "train_context_seed_identities": len(all_seed_values),
            "confirmation_seed_identities_checked_without_generation": len(confirmation_seed_values),
            "prepared_sha256": sha(root/"PREPARED.json")}


def verify_runtime_receipts(book, run_dir):
    root = run_dir/"runtime_prepared"
    reviews = []
    native_receipt = read(run_dir/"native/BUILD_RECEIPT.json")
    binary_hash = sha(run_dir/"native/analytic_event")
    book.require(native_receipt["binary_sha256"] == binary_hash, "native reused binary exact build receipt")
    for seed in runtime_study.REGISTRATION["seeds"]:
        directory = root/f"seed_{seed}"
        receipt, model = read(directory/"TRAINING_RECEIPT.json"), read(directory/"MODELS.json")
        book.require(receipt["model_file_sha256"] == sha(directory/"MODELS.json"), "runtime model identity")
        book.require(receipt["training_rows_sha256"] == sha(directory/"TRAINING_ROWS.json.gz"), "runtime training rows identity")
        book.require(receipt["train_rows"] == 256 and receipt["development_rows"] == 128, "runtime registered fit/development sizes")
        book.require(receipt["prior_confirmation_used"] is False, "runtime prior confirmation not fitted")
        book.require(model["native_binary_sha256"] == binary_hash, "runtime model native binding")
        book.require(receipt["dynamics"]["prior_parameters_changed"] is True, "runtime learned mixture parameters changed")
        for arm, fit in receipt["fits"].items():
            chosen = max(fit["candidates"], key=lambda item: (item["development_utility"], item["l2"], -abs(item["offset"])))
            book.require(len(fit["candidates"]) == 15, "runtime candidate count:"+arm)
            book.require(model["heads"][arm] == {key: chosen[key] for key in ("weights", "offset", "l2")},
                         "runtime selected readout:"+arm)
            book.require(fit["parameter_l2_change"] > 0, "runtime readout trained:"+arm)
        for split in ("train", "development"):
            record = receipt["training_archive" if split == "train" else "development_archive"]
            book.require(record["sha256"] == sha(directory/(split+".zip")), "runtime actual archive binding:"+split)
            book.require(record["manifest_sha256"] == sha(directory/(split+".manifest.json")), "runtime member inventory binding:"+split)
        reviews.append({"seed": seed, "model_sha256": sha(directory/"MODELS.json"),
                        "training_receipt_sha256": sha(directory/"TRAINING_RECEIPT.json")})
    return {"seeds": reviews, "prepared_readout_heads": 15, "selected_development_candidates": 225,
            "native_binary_sha256": binary_hash,
            "native_reexecution_scope": "Separate runtime_prepare_review.py receipt required below"}


def verify_bridge(book, run_dir):
    checked = 0
    hashes = {}
    for seed in runtime_study.REGISTRATION["seeds"]:
        path = run_dir/"runtime_bridge_prepared"/f"seed_{seed}.json"
        bridge = read(path)
        hashes[str(path.relative_to(run_dir))] = sha(path)
        for relative, expected in bridge["source_files"].items():
            book.require(sha(run_dir/relative) == expected, "bridge original source artifact:"+relative)
        root = run_dir/"calibration_prepared"/f"seed_{seed}"
        model = read(root/"window_01_CHECKPOINT.json")["models"]["mixture_context"]
        data = calibration_study.load(root/"window_01_NEW_DEV.npz")
        context = calibration_study.load(root/"window_01_NEW_DEV_CONTEXT.npz")
        history = task.history(data)
        distribution = calibration.predict_distribution(model, history, context)
        book.require(bridge["model_sha256"] == document_digest(model), "bridge original selected model")
        book.require(len(bridge["queries"]) == 10, "bridge registered case count")
        for query in bridge["queries"]:
            row = query["row"]
            expected = {"history": {key: history[key][row:row+1].tolist() for key in ("obs", "times", "mask", "occupied", "obs_var")},
                        "context": {key: context[key][8*row:8*(row+1)].tolist() for key in ("obs", "times", "mask", "occupied", "obs_var")},
                        "physical_horizon": 1.0}
            book.require(query["conditioning"] == expected, "bridge actual public conditioning")
            book.require(query["conditioning_sha256"] == document_digest(expected), "bridge public history hash")
            book.require(query["query_id"] == str(data["ids"][row]), "bridge deterministic source query identity")
            book.require(query["physical_horizon"] == 1.0, "bridge terminal physical horizon")
            book.require(query["law"] == calibration.law_at(distribution, row, 2), "bridge exact forecast law")
            for mode in MODES:
                packet = Encoder(mode).encode(query["law"], 1, 1.0)
                book.require(len(packet) > 24, "bridge common transport eligible:"+mode)
            checked += 1
    return {"development_queries": checked, "native_execution_in_this_review": False,
            "physical_horizon": 1.0, "artifacts_sha256": hashes,
            "native_bridge_qualification_requires_postfreeze_actual_calls": True}


def run_review(run_dir, runtime_review):
    started = time.perf_counter_ns()
    run_dir = Path(run_dir).resolve()
    book = Review()
    protocol = read(freeze.PROJECT/"PROTOCOL.json")
    source_before = {name: sha(path) for name, path in freeze.scientific_sources().items()}
    book.require(not any((run_dir/name).exists() for name in freeze.CONFIRMATION), "no confirmation exists before review")
    previous = freeze.verify_old_sources()
    book.require(protocol["calibration"] == calibration_study.registration(), "protocol calibration matches executable registration")
    book.require(protocol["runtime_feedback"] == runtime_study.REGISTRATION, "protocol runtime matches executable registration")
    mathematical = math_validation.run_checks()
    book.require(mathematical["all_checks_pass"], "independent arithmetic checks")
    calibration_result = verify_calibration(book, run_dir)
    runtime_result = verify_runtime_receipts(book, run_dir)
    bridge_result = verify_bridge(book, run_dir)
    actual_runtime_review = read(runtime_review)
    book.require(actual_runtime_review.get("passed") is True or actual_runtime_review.get("pass") is True,
                 "all-native prepared replay and deterministic retraining independent receipt")
    book.require(actual_runtime_review["seeds"] == runtime_study.REGISTRATION["seeds"],
                 "prepared native replay covers all registered seeds")
    for scope in actual_runtime_review["scopes"]:
        book.require(scope["passed"] is True, "prepared native replay scope passed")
        book.require(scope["model_sha256"] == sha(run_dir/"runtime_prepared"/f"seed_{scope['seed']}"/"MODELS.json"),
                     "prepared native replay binds exact selected model")
        for name, expected in scope["current_core_source_sha256"].items():
            book.require(sha(freeze.PROJECT/name) == expected, "prepared native replay current source:"+name)
    calibration_review_path = run_dir/"reviews/CALIBRATION_PREPARE_REVIEW.json"
    calibration_review = read(calibration_review_path)
    book.require(calibration_review.get("passed") is True or calibration_review.get("pass") is True,
                 "all-row independent dense calibration prepared review")
    book.require(calibration_review["prepared_sha256"] == calibration_result["prepared_sha256"],
                 "dense calibration review exact prepared binding")
    book.require(calibration_review["reviewer_source_sha256"] == sha(freeze.PROJECT/"evidence/review_calibration.py"),
                 "dense calibration review exact checker source")
    source_after = {name: sha(path) for name, path in freeze.scientific_sources().items()}
    book.require(source_before == source_after, "sources unchanged throughout independent prefreeze review")
    return {"schema": "hepta.analytic-event.round4.prefreeze-review.v1", "passed": not book.failures,
            "checks": book.checks, "failures": book.failures, "maximum_errors": book.maximum_errors,
            "created_utc": datetime.now(timezone.utc).isoformat(), "wall_ns": time.perf_counter_ns()-started,
            "prior_sources": previous, "source_sha256": source_after,
            "math_reference": mathematical, "calibration": calibration_result, "runtime": runtime_result,
            "calibration_runtime_bridge": bridge_result,
            "runtime_prepared_replay_receipt": {"path": str(Path(runtime_review).resolve()), "sha256": sha(runtime_review)},
            "dense_calibration_prepared_review_receipt": {"path": str(calibration_review_path), "sha256": sha(calibration_review_path)},
            "confirmation_generated": False, "scientific_acceptance_claimed": False,
            "known_numeric_approximation": "GH64 continuation diagnostic remains separate from exact arithmetic checks"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--runtime-review", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_review(args.run_dir, args.runtime_review)
    output = args.output or args.run_dir/"validation/PREFREEZE_REVIEW.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"], "failures": result["failures"],
                      "path": str(output), "sha256": sha(output)}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
