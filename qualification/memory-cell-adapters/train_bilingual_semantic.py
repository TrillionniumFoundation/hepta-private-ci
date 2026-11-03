"""Single bounded bilingual fit, then one sealed old/new held comparison.

Artifacts use the existing v2 semantic-head contract. No owner selection,
source-cut validation, effect authorization, or production gate is changed.
"""
import argparse
import copy
import json
from pathlib import Path
import resource
import signal
import time
import warnings

STARTED = time.perf_counter()

import numpy as np

from bilingual_semantic_protocol import SCHEMA, source_pins, weight_digest
from semantic_protocol import ENCODER_DIGEST, INTENTS, SHAPES, bounded_address, canonical, digest, gold, hypothesis, route
from train_semantic_router import encode_rows, encoder_from


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value))


def pinned(directory, protocol, name):
    raw = (directory / name).read_bytes()
    expected = protocol["files"][name]
    if len(raw) != expected["bytes"] or digest(raw) != expected["sha256"]:
        raise ValueError("frozen input changed: " + name)
    return json.loads(raw)


def protocol_from(args):
    raw = args.protocol.read_bytes()
    protocol = json.loads(raw)
    if digest(raw) != args.protocol_sha256 or protocol["schema"] != SCHEMA or protocol["source_sha256"] != source_pins():
        raise ValueError("protocol or executed source pin changed")
    return protocol


class Budget:
    def __init__(self, output, limits, stage):
        self.output, self.limits, self.stage = output, limits, stage

    def __enter__(self):
        self.cpu, self.wall = time.process_time(), time.perf_counter()
        self.old_cpu = signal.signal(signal.SIGPROF, self.expired)
        self.old_wall = signal.signal(signal.SIGALRM, self.expired)
        remaining_cpu = self.limits["cpu_budget_seconds"] - self.cpu
        remaining_wall = self.limits["wall_budget_seconds"] - (self.wall - STARTED)
        if min(remaining_cpu, remaining_wall) <= 0:
            raise TimeoutError("budget exhausted during process setup")
        signal.setitimer(signal.ITIMER_PROF, remaining_cpu)
        signal.setitimer(signal.ITIMER_REAL, remaining_wall)
        return self

    def expired(self, number, frame):
        raise TimeoutError("frozen process CPU or wall budget exhausted")

    def receipt(self):
        return {"stage":self.stage, "process_cpu_seconds":time.process_time(),
                "stage_cpu_seconds":time.process_time()-self.cpu, "process_wall_seconds":time.perf_counter()-STARTED,
                "stage_wall_seconds":time.perf_counter()-self.wall,
                "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "limits":self.limits, "automatic_retries":0,
                "cost_boundary":"whole process CPU includes imports, encoder load/work, head work and serialization; outer Runtime startup is separate"}

    def __exit__(self, kind, error, traceback):
        signal.setitimer(signal.ITIMER_PROF, 0); signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGPROF, self.old_cpu); signal.signal(signal.SIGALRM, self.old_wall)
        result = self.receipt()
        result["status"] = "completed" if error is None else "failed"
        if error is not None:
            result["error"] = repr(error)
        write(self.output / "PROCESS.json", result)
        return False


def from_scores(model, rows, scores, threshold, margin, declarations=None):
    predictions = []
    if declarations is None:
        declarations = [bounded_address(row["text"], model["aliases"], model["query_templates"]) for row in rows]
    for declared, (winner, score, gap) in zip(declarations, scores, strict=True):
        if declared is None or winner == 3 or score < float(np.float32(threshold)) or gap < float(np.float32(margin)):
            predictions.append(None); continue
        predicted = {**declared, "operation":("semantic", "procedure", "apply")[winner]}
        predictions.append(predicted if predicted == declared else None)
    return predictions


def counts(rows, predictions):
    result = {"total":len(rows), "known":0, "known_correct":0, "known_wrong":0,
              "unknown":0, "unknown_false_accept":0, "abstained":0, "correct":0}
    for row, predicted in zip(rows, predictions, strict=True):
        known = row["role"] != "unknown"
        result["known"] += known; result["unknown"] += not known
        result["known_correct"] += known and predicted == gold(row)
        result["known_wrong"] += known and predicted is not None and predicted != gold(row)
        result["unknown_false_accept"] += not known and predicted is not None
        result["abstained"] += predicted is None
        result["correct"] += predicted == gold(row)
    return result


def groups(rows, predictions):
    result = {"all":counts(rows, predictions)}
    for field in ("language", "role", "family"):
        for value in sorted({row[field] for row in rows}):
            selected = [(row, predicted) for row, predicted in zip(rows, predictions, strict=True) if row[field] == value]
            result[field + ":" + value] = counts([row for row, _ in selected], [predicted for _, predicted in selected])
    return result


def fit(args, protocol):
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from threadpoolctl import threadpool_limits

    directory = args.protocol.parent
    train = pinned(directory, protocol, "train.json")
    dev = pinned(directory, protocol, "development.json")
    baseline = pinned(directory, protocol, "baseline-expanded.json")
    if weight_digest(baseline) != protocol["baseline_weights_sha256"]:
        raise ValueError("expanded baseline weights differ")
    # held.json is deliberately not opened by this command, even for hashing.
    encoder = encoder_from(args)
    x, truncated = encode_rows(encoder, train)
    development_x, development_truncated = encode_rows(encoder, dev)
    if any(truncated) or any(development_truncated):
        raise ValueError("fitting text exceeds the existing tokenizer profile")
    model = copy.deepcopy(baseline)
    model["training_digest"] = protocol["files"]["train.json"]["sha256"]
    model["calibration_digest"] = protocol["files"]["development.json"]["sha256"]
    labels = [row["intent"] for row in train]
    shapes = [SHAPES[INTENTS.index(row["role"])] if row["role"] != "unknown" else "unsupported" for row in train]
    fits = []
    for name, targets, order in (("intent", labels, INTENTS), ("shape", shapes, SHAPES)):
        if set(targets) != set(order):
            raise ValueError("every existing head class needs training evidence")
        spec = protocol["fit"]
        learner = LogisticRegression(C=spec["C"], class_weight="balanced", max_iter=spec["max_iter"],
                                     solver="lbfgs", random_state=spec["seed"], tol=spec["tol"])
        began, cpu = time.perf_counter(), time.process_time()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=spec["threads"]):
            warnings.simplefilter("always")
            learner.fit(x.astype(np.float64), targets)
        if any(issubclass(item.category, ConvergenceWarning) for item in caught):
            raise ValueError("bounded head fit did not converge; no automatic retry")
        positions = [list(learner.classes_).index(label) for label in order]
        model[name + "_weights"] = learner.coef_[positions].astype(np.float32).tolist()
        model[name + "_bias"] = learner.intercept_[positions].astype(np.float32).tolist()
        fits.append({"head":name, "iterations":learner.n_iter_.tolist(), "rows":len(train),
                     "cpu_seconds":time.process_time()-cpu, "wall_seconds":time.perf_counter()-began,
                     "warnings":[str(item.message) for item in caught]})
    scores = [hypothesis(model, feature) for feature in development_x]
    declarations = [bounded_address(row["text"], model["aliases"], model["query_templates"]) for row in dev]
    fixed = from_scores(model, dev, scores, baseline["threshold"], baseline["minimum_margin"], declarations)
    trials = []
    for threshold in protocol["calibration"]["thresholds"]:
        for margin in protocol["calibration"]["margins"]:
            predicted = from_scores(model, dev, scores, threshold, margin, declarations)
            trials.append({"threshold":threshold, "minimum_margin":margin, **counts(dev, predicted)})
    eligible = [row for row in trials if row["unknown_false_accept"] == 0 and row["known_wrong"] == 0]
    selected = max(eligible, key=lambda row:(row["known_correct"], row["threshold"], row["minimum_margin"]))
    model.update({key:selected[key] for key in ("threshold", "minimum_margin")})
    predicted = from_scores(model, dev, scores, model["threshold"], model["minimum_margin"], declarations)
    # Verify the cached-score calibration uses the unchanged reference router.
    if predicted != [route(model, row["text"], feature) for row, feature in zip(dev, development_x, strict=True)]:
        raise ValueError("calibration and existing reference router differ")
    raw_model = canonical(model)
    (args.output / "semantic-router.json").write_bytes(raw_model)
    np.savez_compressed(args.output / "fitting-features.npz", training=x, development=development_x)
    receipt = {"schema":"hepta.memory.inventory-semantic-bilingual-fit.v1", "model_sha256":digest(raw_model),
        "protocol_sha256":args.protocol_sha256, "training_sha256":model["training_digest"],
        "calibration_sha256":model["calibration_digest"], "encoder":encoder.receipt(), "heads":fits,
        "training_rows":len(train), "development_rows":len(dev), "historical_known_replay_rows":protocol["historical_known_replay_rows"],
        "selected":selected, "development":groups(dev, predicted), "fixed_old_threshold_development":groups(dev, fixed),
        "old_threshold":baseline["threshold"], "old_minimum_margin":baseline["minimum_margin"], "grid":trials,
        "selection_used_held":False, "held_file_opened":False, "historical_480_used_for_calibration":False,
        "source_sha256":source_pins(), "learned_f32_parameters":sum(len(row) for name in ("intent", "shape") for row in model[name + "_weights"])
                                  + sum(len(model[name + "_bias"]) for name in ("intent", "shape")),
        "serialized_bytes":len(raw_model), "candidate_authority":"none; existing native and owner qualification required"}
    write(args.output / "FIT.json", receipt)
    write(args.output / "CANDIDATE.json", {"schema":"hepta.memory.inventory-semantic-bilingual-candidate.v1",
          "model_sha256":digest(raw_model), "fit_sha256":digest((args.output / "FIT.json").read_bytes()),
          "protocol_sha256":args.protocol_sha256, "sealed_before_held_open":True, "production_selected":False})
    print(json.dumps({"model_sha256":digest(raw_model), "selected":selected, "fixed_old_threshold":counts(dev, fixed)}), flush=True)


def reference(model, model_sha, rows, features, truncated, query_sha, encoder_receipt):
    predictions = [route(model, row["text"], None if overflow else feature)
                   for row, feature, overflow in zip(rows, features, truncated, strict=True)]
    cases = [{"id":row["id"], "text":row["text"], "gold_route":gold(row), "reference_route":predicted,
              "features":[] if overflow else feature.tolist(), "truncated":overflow}
             for row, feature, overflow, predicted in zip(rows, features, truncated, predictions, strict=True)]
    return {"schema":"hepta.memory.inventory-semantic-python-reference.v1", "model_sha256":model_sha,
            "queries_sha256":query_sha, "encoder_digest":ENCODER_DIGEST, "rows":len(rows),
            "groups":groups(rows, predictions), "cases":cases, "encoder":encoder_receipt,
            "fit_or_calibration_updated":False}, predictions


def compare(args, protocol):
    candidate = json.loads((args.candidate / "CANDIDATE.json").read_bytes())
    raw_model = (args.candidate / "semantic-router.json").read_bytes()
    if candidate["protocol_sha256"] != args.protocol_sha256 or candidate["model_sha256"] != digest(raw_model) \
            or candidate["fit_sha256"] != digest((args.candidate / "FIT.json").read_bytes()) or not candidate["sealed_before_held_open"]:
        raise ValueError("candidate seal differs")
    model = json.loads(raw_model)
    baseline = pinned(args.protocol.parent, protocol, "baseline-expanded.json")
    if any(model[key] != baseline[key] for key in ("aliases", "query_templates", "encoder_digest", "feature_profile", "intent_labels", "shape_labels")):
        raise ValueError("old and new models do not share the declared capability/feature contract")
    # One attempt per sealed candidate, including failed attempts. This marker is
    # created before reading held bytes; a different output path cannot retry it.
    write(args.candidate / "HELD_STARTED.json", {"protocol_sha256":args.protocol_sha256,
          "candidate_model_sha256":digest(raw_model), "output":str(args.output), "wall_unix_seconds":time.time()})
    rows = pinned(args.protocol.parent, protocol, "held.json")
    encoder = encoder_from(args)
    features, truncated = encode_rows(encoder, rows)
    query_sha = protocol["files"]["held.json"]["sha256"]
    old, old_predictions = reference(baseline, protocol["files"]["baseline-expanded.json"]["sha256"], rows, features, truncated, query_sha, encoder.receipt())
    new, new_predictions = reference(model, digest(raw_model), rows, features, truncated, query_sha, encoder.receipt())
    write(args.output / "BASELINE_REFERENCE.json", old); write(args.output / "CANDIDATE_REFERENCE.json", new)
    specification = protocol["comparison"]
    total = new["groups"]["all"]
    accuracy = lambda value: value["known_correct"] / value["known"] if value["known"] else 0.
    checks = {"known_accuracy":accuracy(total) >= specification["known_accuracy_minimum"],
              "unknown_false_accept":total["unknown_false_accept"] <= specification["unknown_false_accept_maximum"],
              "known_wrong":total["known_wrong"] <= specification["known_wrong_maximum"], "no_truncation":not any(truncated)}
    checks.update({"language_" + language:accuracy(new["groups"]["language:" + language]) >= specification["language_accuracy_minimum"] for language in ("zh", "en")})
    checks.update({"operation_" + role:accuracy(new["groups"]["role:" + role]) >= specification["operation_accuracy_minimum"] for role in ("semantic", "skill", "compose")})
    report = {"schema":"hepta.memory.inventory-semantic-bilingual-comparison.v1", "protocol_sha256":args.protocol_sha256,
        "baseline_original_model_sha256":protocol["baseline_model_sha256"],
        "baseline_expanded_model_sha256":old["model_sha256"], "candidate_model_sha256":new["model_sha256"],
        "old":old["groups"], "new":new["groups"], "checks":checks, "language_gate_passed":all(checks.values()),
        "known_improved":sum(row["role"] != "unknown" and before != gold(row) and after == gold(row) for row, before, after in zip(rows, old_predictions, new_predictions, strict=True)),
        "known_regressed":sum(row["role"] != "unknown" and before == gold(row) and after != gold(row) for row, before, after in zip(rows, old_predictions, new_predictions, strict=True)),
        "held_encoded_once_shared_by_models":True, "held_evaluations_per_model":1, "held_used_for_selection":False,
        "original_480_is_candidate_generalization_evidence":False, "production_gate_modified":False,
        "full_cost_exact":False, "unobserved_costs":["historical encoder/base-model construction", "outer Runtime scheduling/startup"],
        "status":"ready for unchanged native parity and actual owner validation" if all(checks.values()) else "language gate failed; retain candidate and negative evidence without retuning this held set"}
    write(args.output / "RESULT.json", report)
    write(args.output / "PUBLICATION_CANDIDATE.json", {"schema":"hepta.memory.inventory-semantic-publication-candidate.v1",
        "model":str((args.candidate / "semantic-router.json").resolve()), "model_sha256":new["model_sha256"],
        "native_reference":str((args.output / "CANDIDATE_REFERENCE.json").resolve()), "language_gate_passed":all(checks.values()),
        "owner_path":"existing inventory_semantic_actual_owner_path; no memory-source cuts or effect authority changed",
        "production_selected":False, "native_parity_and_actual_owner_gate":"not evaluated by this Python command"})
    print(json.dumps({"old":old["groups"]["all"], "new":new["groups"]["all"], "checks":checks}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="mode", required=True)
    fitting = commands.add_parser("fit")
    comparison = commands.add_parser("compare"); comparison.add_argument("--candidate", type=Path, required=True)
    for command in (fitting, comparison):
        command.add_argument("--protocol", type=Path, required=True)
        command.add_argument("--protocol-sha256", required=True)
        command.add_argument("--encoder-source", type=Path, required=True)
        command.add_argument("--encoder-source-sha256", required=True)
        command.add_argument("--encoder", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = protocol_from(args)
    with Budget(args.output, protocol["fit" if args.mode == "fit" else "comparison"], args.mode):
        (fit if args.mode == "fit" else compare)(args, protocol)
