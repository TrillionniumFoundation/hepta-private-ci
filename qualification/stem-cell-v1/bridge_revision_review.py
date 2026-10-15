"""Stdlib consistency audit of public V6 revision events and physical costs.

This replays recorded probabilities, feedback and accounting, never a network.
Opaque feature/state hashes cannot establish their unrecorded tensor values.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import re
import struct

from binding_review import _check, _cost, _digest, _id, audit_scores

MODES = ("real", "zero", "shuffle", "reset", "late_fusion", "verifier_only", "cheap_fixed1", "cheap_verifier")
ROLES = ("fresh_combinations", "fresh_vocabulary")
CALLS = ("reader_prepare", "reader_step", "verifier_prepare", "verifier_step")


def _hash(value):
    _check(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value), "typed SHA256 required")
    return value


def _number(value, minimum=0):
    _check(type(value) in (int, float) and math.isfinite(value) and value >= minimum, "finite numeric observation required")
    return value


def _probabilities(values):
    _check(isinstance(values, list) and len(values) == 2
           and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values)
           and math.isclose(sum(values), 1., abs_tol=2e-7), "finite normalized binary probabilities required")
    return int(values[1] > .5)


def feedback_hash(values):
    return sha256(str(("torch.float32", (4,))).encode() + struct.pack("<4f", *values)).hexdigest()


def permutation(case_ids, seed):
    rng = random.Random(_digest(dict(case_ids=list(case_ids), seed=seed, version="v5-feedback-shuffle")))
    indices = list(range(len(case_ids)))
    _check(len(indices) >= 2, "shuffle requires multiple public cases")
    for _ in range(10000):
        rng.shuffle(indices)
        if all(i != donor for i, donor in enumerate(indices)):
            return indices
    raise ValueError("public derangement bound exhausted")


def transitions(initial, final, rows, *, training=False):
    _check(len(initial) == len(final) == len(rows), "complete transition observations required")
    wrong = sum(p != row["label"] for p, row in zip(initial, rows))
    corrected = sum(a != row["label"] and b == row["label"] for a, b, row in zip(initial, final, rows))
    damaged = sum(a == row["label"] and b != row["label"] for a, b, row in zip(initial, final, rows))
    correct = len(rows) - wrong
    if training:
        return dict(exposure_trials=len(rows), initial_correct=correct, initial_wrong=wrong,
            wrong_to_correct=corrected, correct_to_wrong=damaged, net_corrections=corrected - damaged,
            final_correct=correct + corrected - damaged)
    return dict(initial_wrong=wrong, initial_correct=correct, corrected=corrected, damaged=damaged,
        net_corrected=corrected - damaged, wrong_to_correct_rate=corrected / wrong if wrong else None,
        initially_correct_retained_rate=(correct - damaged) / correct if correct else None)


def audit_calls(cost, mode, batch_size):
    expected = (["reader_prepare", "reader_step"] if mode == "cheap_fixed1" else
                ["verifier_prepare", "verifier_step"] if mode == "cheap_verifier" else
                ["reader_prepare", "reader_step", "verifier_prepare", "verifier_step", "reader_step", "verifier_step", "reader_step"])
    _check([r["component"] for r in cost["callbacks"]] == expected, "actual callback sequence differs from arm")
    _check(cost["calls"] == {name: expected.count(name) for name in CALLS}, "actual callback counters mismatch")
    outer, nested = _cost(cost), dict(cpu_ns=0, wall_ns=0)
    for row in cost["callbacks"]:
        child = _cost(row)
        for axis in nested:
            nested[axis] += child[axis]
    _check(all(outer[k] >= nested[k] for k in outer), "outer forward cost omits callbacks")
    _check(cost["physical_batch_size"] == batch_size and cost["formula_flops"] is None
           and cost["callback_costs_are_nested"] is True and cost["shared_encoder_included"] is False
           and cost["per_case_attribution"] == "singleton_only"
           and cost["external_shuffle_feedback_required"] is False, "physical cost scope or unsupported formula changed")
    return outer


def audit_events(events, observations, rows, model_sha, verifier_sha, mode, *, donors=None):
    """Rebuild every feedback row, donor and strict decision from public records."""
    size = len(rows)
    rounds = 0 if mode == "cheap_verifier" else 1 if mode == "cheap_fixed1" else 3
    _check(len(events) == rounds * size and len(observations) == (2 if rounds == 3 else 0), "missing/extra revision events")
    _check(all(len(batch) == size and all(isinstance(v, list) and len(v) == 4 for v in batch)
               for batch in observations), "verifier observation geometry mismatch")
    keys = {"step", "batch_row", "case_id", "source_sha256", "prediction", "probabilities", "state_sha256",
            "feedback", "feedback_sha256", "feedback_donor_batch_row", "feedback_donor_case_id",
            "reader_model_sha256", "verifier_model_sha256"}
    for hop in range(rounds):
        for index, row in enumerate(rows):
            event = events[hop * size + index]
            _check(set(event) == keys and event["step"] == hop + 1 and event["batch_row"] == index
                   and event["case_id"] == _id(row) and event["source_sha256"] == row["source_hash"], "event public row/step boundary mismatch")
            _check(event["reader_model_sha256"] == model_sha and event["verifier_model_sha256"] == verifier_sha,
                   "event frozen model binding mismatch")
            _hash(event["state_sha256"])
            _check(type(event["prediction"]) is int and event["prediction"] == _probabilities(event["probabilities"]), "event decision differs from strict saved probability")
            if hop == 0:
                _check(all(event[k] is None for k in ("feedback", "feedback_sha256", "feedback_donor_batch_row", "feedback_donor_case_id")), "initial proposal received feedback")
                continue
            expected = ([0., 0., 0., 0.] if mode in ("zero", "late_fusion", "verifier_only") else
                        observations[hop - 1][donors[index] if donors is not None else index])
            _check(isinstance(event["feedback"], list) and len(event["feedback"]) == 4
                   and all(type(v) in (int, float) and math.isfinite(v) for v in event["feedback"]), "typed finite feedback values required")
            _check(event["feedback"] == expected and event["feedback_sha256"] == feedback_hash(expected), "actual feedback/hash differs from observed or control feedback")
            _check(event["feedback_donor_batch_row"] == (donors[index] if donors is not None else None)
                   and event["feedback_donor_case_id"] == (_id(rows[donors[index]]) if donors is not None else None), "shuffle donor binding mismatch")
    for hop, batch in enumerate(observations):
        _check(len(batch) == size, "verifier observations do not cover the physical batch")
        for index, value in enumerate(batch):
            _check(all(type(v) in (int, float) and math.isfinite(v) for v in value)
                   and value[2] in (0., 1.) and value[3] == 1., "public verifier status fields invalid")
            prediction = _probabilities(value[:2])
            _check(value[2] == float(prediction == events[hop * size + index]["prediction"]), "verifier agreement used an inconsistent candidate")
            if hop:
                _check(value[:2] == observations[0][index][:2], "unconditioned frozen verifier changed probabilities between calls")
    return dict(initial=[e["prediction"] for e in events[:size]],
                initial_state_sha256s=[e["state_sha256"] for e in events[:size]],
                final=[e["prediction"] for e in events[-size:]] if events else [],
                initial_probabilities=[e["probabilities"] for e in events[:size]],
                final_probabilities=[e["probabilities"] for e in events[-size:]] if events else [])


def audit_execution(result, rows, model_sha, verifier, mode, seed):
    _check(result["schema"] == "hepta.revision-execution.v1" and result["mode"] == mode
           and result["prediction_rule"] == "raw_probability_strictly_greater_than_0.5"
           and result["labels_read"] is False and result["verifier_synthetic_trained"] is False
           and result["verifier_acceptance_is_semantic_truth"] is False, "execution protocol changed")
    _check(result["reader_model_sha256"] == model_sha and result["verifier_model_sha256"] == verifier["model_sha256"]
           and result["verifier_artifact_sha256"] == verifier["file_sha256"]
           and result["verifier_provenance_sha256"] == _digest(verifier), "execution artifact/provenance mismatch")
    _check(len(result["input_feature_sha256s"]) == 6, "six public tensor hashes required")
    for value in result["input_feature_sha256s"]:
        _hash(value)
    donors = permutation([_id(r) for r in rows], seed) if mode == "shuffle" else None
    _check(result["shuffle_indices"] == donors and result["shuffle_uses_current_observations"] is (donors is not None)
           and result["external_feedback_sha256"] is None, "shuffle did not use the registered public-ID permutation")
    trace = audit_events(result["events"], result["verifier_observations"], rows, model_sha, verifier["model_sha256"], mode, donors=donors)
    _check(result["initial_proposals"] == result["events"][:len(rows)], "initial proposal was not retained verbatim")
    _check(len(result["probabilities"]) == len(rows) and result["predictions"] == [_probabilities(p) for p in result["probabilities"]], "output decisions differ from saved probabilities")
    if mode != "cheap_verifier":
        expected = trace["final_probabilities"]
        if mode == "verifier_only":
            expected = [v[:2] for v in result["verifier_observations"][-1]]
        elif mode == "late_fusion":
            _check(result["late_fusion_rule"] == "0.5_reader_probability_plus_0.5_last_verifier_probability", "late fusion rule changed")
            fp32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]
            expected = [[fp32(fp32(a + b) * .5) for a, b in zip(p, v[:2])]
                        for p, v in zip(expected, result["verifier_observations"][-1])]
        _check(result["probabilities"] == expected, "execution output is inconsistent with the recorded last proposal/verifier")
    trace.update(cost=audit_calls(result["cost"], mode, len(rows)), probabilities=result["probabilities"],
                 predictions=result["predictions"])
    return trace


def audit_revision_panel(rows, panel, manifest, verifier, *, seed, prefix):
    _check(panel["case_ids"] == [_id(r) for r in rows] and panel["labels_entered_model"] is False
           and panel["reader_model_sha256"] == manifest["execution_parameter_sha256"]
           and panel["verifier_model_sha256"] == verifier["model_sha256"], "panel row/model binding mismatch")
    mode, probabilities, predictions, initial = panel["mode"], [], [], []
    _check(mode in MODES, "unknown revision panel mode")
    costs, traces = dict(cpu_ns=0, wall_ns=0), []
    batches = panel["physical_batches"]
    _check(len(batches) == (len(rows) + 15) // 16, "missing or duplicated physical batches")
    for index, batch in enumerate(batches):
        selected = rows[index * 16:(index + 1) * 16]
        _check(batch["batch_id"] == f"{prefix}/{index}" and batch["case_ids"] == [_id(r) for r in selected], "physical batch membership/order mismatch")
        trace = audit_execution(batch["execution"], selected, manifest["execution_parameter_sha256"], verifier, mode, seed)
        _check(batch["shuffle_indices"] == batch["execution"]["shuffle_indices"], "batch shuffle provenance mismatch")
        prep = _cost(batch["feature_preparation"])
        for key in costs:
            costs[key] += prep[key] + trace["cost"][key]
        probabilities.extend(p[1] for p in trace["probabilities"])
        predictions.extend(trace["predictions"])
        initial.extend(trace["initial"])
        traces.append(trace)
    _check(panel["probabilities"] == probabilities and panel["predictions"] == predictions
           and panel["initial_predictions"] == initial, "panel aggregates differ from physical observations")
    expected_transition = transitions(initial, predictions, rows) if initial else None
    _check(panel["transitions"] == expected_transition, "initial-error correction/damage metrics mismatch")
    _check(all(panel["costs"][k] == costs[k] for k in costs)
           and panel["costs"]["batch_count"] == len(batches)
           and panel["costs"]["callback_costs_are_nested"] is True
           and panel["costs"]["scope"] == "physical_batch_public_feature_and_control_preparation_plus_execution_once"
           and panel["costs"]["formula_flops"] is None and panel["costs"]["individually_measured_case_latency"] is False,
           "physical panel cost omitted work or double-counted nested callbacks")
    return dict(passed=True, metrics=audit_scores(rows, probabilities, panel["metrics"]), costs=costs,
                transitions=expected_transition, traces=traces, mode=mode, physical_batches=len(batches))


def review_fresh(run, parts, models, verifiers):
    """Audit exactly 96 revision panels; called only after an explicit fresh request."""
    run, reports, costs, guarded = Path(run), {}, dict(cpu_ns=0, wall_ns=0), {}
    completion_path = run / "completion.json"
    completion_bytes = completion_path.read_bytes()
    completion = json.loads(completion_bytes)
    guarded[str(completion_path.resolve())] = sha256(completion_bytes).hexdigest()
    _check(completion["schema"] == "hepta.bridge.fresh-completion.v6"
           and completion["official_validation_scored"] is False
           and completion["repeated_seeds_are_new_examples"] is False, "fresh completion scope changed")
    _check(all(len(parts[role]) == 128 for role in ROLES), "both complete fresh domains required")
    for seed in (41, 47, 53):
        for arm in ("real", "zero"):
            model = models[(seed, arm)]
            for role in ROLES:
                paired = {}
                for mode in MODES:
                    prefix = f"{role}/revision-{arm}/{mode}"
                    path = run / f"seed-{seed}" / "fresh" / (prefix + ".json")
                    data = path.read_bytes()
                    guarded[str(path.resolve())] = sha256(data).hexdigest()
                    panel = json.loads(data)
                    _check(completion["summaries"][str(seed)][prefix]
                           == {key: panel[key] for key in ("metrics", "transitions", "costs")}, "completion summary differs from raw revision panel")
                    result = audit_revision_panel(parts[role], panel, model, verifiers[seed], seed=seed, prefix=prefix)
                    paired[mode] = result
                    for key in costs:
                        costs[key] += result["costs"][key]
                    reports[f"seed-{seed}/{prefix}"] = {k: v for k, v in result.items() if k != "traces"}
                for index in range(len(paired["real"]["traces"])):
                    reference = paired["cheap_fixed1"]["traces"][index]
                    for mode in MODES[:-1]:
                        current = paired[mode]["traces"][index]
                        _check(current["initial_probabilities"] == reference["probabilities"]
                               and current["initial_state_sha256s"] == reference["initial_state_sha256s"], "matched controls changed the first proposal/state")
                    _check(paired["cheap_verifier"]["traces"][index]["probabilities"]
                           == paired["verifier_only"]["traces"][index]["probabilities"], "cheap and matched verifier outputs disagree")
    _check(len(reports) == 96, "complete 96-panel coverage required")
    _check(all(sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in guarded.items()), "fresh audit inputs mutated")
    return dict(passed=True, panels=reports, panel_count=96, physical_costs_once=costs,
                inputs_sha256=guarded, independent_neural_execution=False,
                opaque_tensor_state_values_reconstructed=False, clocks_independently_authenticated=False)
