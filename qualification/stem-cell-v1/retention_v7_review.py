"""Independent stdlib replay of V7 plans, raw-logit losses and qualifications.

No trainer, data generator, runtime scorer or Torch is imported. Recorded losses
are replayed numerically, not by neural reexecution; gradients/times are checked
for internal consistency and are not authenticated hardware observations.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import struct

from binding_review import _check, _cost, _digest, _group_batches, _groups, _id, audit_scores

ARMS = ("repeat", "diverse", "anchored", "low_lr")
STREAMS = ("natural", "transfer", "retention")


def same(actual, expected, message, *, atol=2e-6, rtol=2e-5):
    _check(type(actual) in (int, float) and math.isfinite(actual)
           and math.isclose(actual, expected, abs_tol=atol, rel_tol=rtol), message)


def fp32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def logits_matrix(values, count):
    _check(isinstance(values, list) and len(values) == count and all(isinstance(row, list) and len(row) == 2
           and all(type(v) in (int, float) and math.isfinite(v) and fp32(v) == v for v in row) for row in values),
           "complete finite raw FP32 binary logits required")
    return values


def softplus(value):
    return max(value, 0.) + math.log1p(math.exp(-abs(value)))


def replay_losses(logits, rows, *, paired=False, teacher=None):
    """Stable logit CE, once-only world margin and FP32-centered teacher MSE."""
    logits_matrix(logits, len(rows))
    ce = sum(softplus((1 - 2 * row["label"]) * (z[1] - z[0])) for z, row in zip(logits, rows)) / len(rows)
    pair = 0.
    if paired:
        _, groups = _groups(rows)
        values = []
        for members in groups.values():
            for answer in ("0", "1"):
                a = next(i for world, row, i, *_ in members if world == "0" and row["answer_id"] == answer)
                b = next(i for world, row, i, *_ in members if world == "1" and row["answer_id"] == answer)
                left, right = fp32(logits[a][1] - logits[a][0]), fp32(logits[b][1] - logits[b][0])
                difference = fp32(left - right) * (2 * rows[a]["label"] - 1)
                values.append(softplus(fp32(1. - difference)))
        pair = sum(values) / len(values)
    mse = 0.
    if teacher is not None:
        logits_matrix(teacher, len(rows))
        squares = []
        for student, target in zip(logits, teacher):
            means = [fp32(fp32(sum(z)) * .5) for z in (student, target)]
            for index in (0, 1):
                difference = fp32(fp32(student[index] - means[0]) - fp32(target[index] - means[1]))
                squares.append(fp32(difference * difference))
        mse = sum(squares) / len(squares)
    return dict(binary_cross_entropy=ce, pair_loss=pair, anchor_mse=mse)


def audit_plan(plan, natural, old, augmentation, *, updates=500):
    """Regenerate every arm's common streams without importing the trainer."""
    _check(plan["updates"] == updates and plan["batch_size"] == 16 and type(plan["seed"]) is int,
           "registered complete plan budget required")
    seed = plan["seed"]
    rng = random.Random(f"hepta-binding-natural-v5/{seed}")
    expected = dict(schema="hepta.binding.continuation-plan.v1", seed=seed, updates=updates, batch_size=16,
        logical_update_order=list(STREAMS), natural_batches=[rng.sample(range(len(natural)), 16) for _ in range(updates)],
        binding_batches=_group_batches(old, updates, 16, seed), retention_schema="hepta.retention.plan.v7",
        stream_order=list(STREAMS), arms=list(ARMS), augmentation_seed=seed ^ 0x713,
        augmentation_batches=_group_batches(augmentation, updates, 16, seed ^ 0x713),
        synthetic_pair_weight=.5, anchored_retention_weight=1.,
        learning_rates={arm: .0001 if arm == "low_lr" else .001 for arm in ARMS})
    for prefix, rows in (("natural", natural), ("binding", old), ("augmentation", augmentation)):
        _check(all(row["source_split"] == "train" for row in rows), "only training rows may enter the plan")
        expected[prefix + "_case_ids"] = [_id(row) for row in rows]
        expected[prefix + "_targets"] = [row["label"] for row in rows]
        expected[prefix + "_source_groups"] = [row["source_hash"] for row in rows]
    expected["plan_sha256"] = _digest(expected)
    _check(plan == expected, "V7 plan differs from exact row identities and deterministic sampling")
    return dict(passed=True, plan_sha256=plan["plan_sha256"], logical_updates=updates,
                natural_sequence_sha256=_digest(plan["natural_batches"]),
                old_sequence_sha256=_digest(plan["binding_batches"]), augmentation_sequence_sha256=_digest(plan["augmentation_batches"]))


def audit_teacher(folder, teacher, old, core, cache_files):
    folder = Path(folder)
    _check(teacher["schema"] == "hepta.retention.teacher.v7" and teacher["raw_file"] == "teacher-logits.bin"
           and teacher["dtype"] == "torch.float32" and teacher["shape"] == [len(old), 2], "teacher schema/geometry changed")
    data = (folder / "teacher-logits.bin").read_bytes()
    _check(len(data) == teacher["raw_tensor_bytes"] == len(old) * 8
           and sha256(data).hexdigest() == teacher["raw_file_sha256"] == teacher["raw_logits_sha256"], "teacher file/raw tensor byte SHA mismatch")
    values = [list(pair) for pair in struct.iter_unpack("<2f", data)]
    logits_matrix(values, len(old))
    _check(teacher["logits"] == values and teacher["case_ids"] == [_id(row) for row in old], "teacher logits or old-row order mismatch")
    public = [sha256("\n".join(("[QUESTION]", r["question"], "[CANDIDATE]", r["candidate"], "[PASSAGE]", *r["facts"])).encode()).hexdigest() for r in old]
    _check(teacher["public_source_sha256"] == public and teacher["feature_cache_files_sha256"] == cache_files,
           "teacher public feature/cache binding mismatch")
    _check(teacher["model_execution_parameter_sha256"] == core["execution_parameter_sha256"]
           and teacher["model_training_parameter_sha256"] == core["training_parameter_sha256"]
           and teacher["warmup_weight_file_sha256"] == core["file_sha256"], "teacher initial checkpoint digest encodings mixed or changed")
    _check(teacher["teacher_frozen"] is True and teacher["labels_entered_model"] is False
           and teacher["inference_feature_arguments"] == 6 and teacher["used_by"] == "anchored_retention_loss_only"
           and teacher["common_preparation_not_recharged_per_arm"] is True, "frozen shared teacher boundary changed")
    _check(len(teacher["batches"]) == (len(old) + 15) // 16, "teacher physical batches missing/duplicated")
    nested = dict(cpu_ns=0, wall_ns=0)
    for index, batch in enumerate(teacher["batches"]):
        _check(batch["case_ids"] == teacher["case_ids"][index * 16:(index + 1) * 16], "teacher batch row identity mismatch")
        cost = _cost(batch)
        for axis in nested:
            nested[axis] += cost[axis]
    outer = _cost(teacher["phase_cost"])
    _check(all(outer[k] >= nested[k] for k in outer), "teacher outer cost below its disjoint physical batches")
    return values, dict(passed=True, rows=len(old), raw_logits_sha256=sha256(data).hexdigest(),
                        preparation_cost_once=outer, reused_by_four_arms=True, independent_teacher_neural_execution=False)


def audit_training(receipt, plan, teacher, natural, old, augmentation, core, arm, *, updates=500):
    audit_plan(plan, natural, old, augmentation, updates=updates)
    _check(arm in ARMS and receipt["schema"] == "hepta.retention.continuation.v7"
           and receipt["arm"] == arm and receipt["status"] == "completed"
           and receipt["completed_steps"] == receipt["requested_logical_updates"] == updates
           and receipt["plan_sha256"] == plan["plan_sha256"] and receipt["seed"] == plan["seed"] == core["seed"],
           "completed arm/plan/core identity mismatch")
    _check(receipt["initial_model_sha256"] == core["training_parameter_sha256"]
           and receipt["optimizer"] == "Adam_foreach_false" and receipt["learning_rate"] == plan["learning_rates"][arm]
           and receipt["pair_weight"] == .5 and receipt["anchor_weight"] == float(arm == "anchored")
           and receipt["depth"] == 3 and receipt["batch_size"] == 16 and receipt["stream_order"] == list(STREAMS)
           and receipt["stopping_rule"] == "fixed_budget_diagnostics_do_not_select", "fixed optimizer/loss/depth policy changed")
    raw_teacher = b"".join(struct.pack("<2f", *row) for row in teacher)
    _check(receipt["teacher_logits_sha256"] == sha256(raw_teacher).hexdigest()
           and receipt["teacher_logits_shape"] == [len(old), 2] and receipt["teacher_logits_dtype"] == "torch.float32"
           and receipt["teacher_calls_inside_fit"] == 0 and receipt["teacher_logits_unchanged"] is True
           and receipt["teacher_preparation_scope"] == "external_once_per_seed_shared_all_arms_not_recharged_here"
           and receipt["anchor_applies_only_to"] == "retention" and receipt["raw_step_logits_recorded"] is True,
           "teacher reuse/immutability/loss scope mismatch")
    prefixes = {"natural": natural, "binding": old, "augmentation": augmentation}
    for prefix in prefixes:
        _check(receipt[prefix + "_sequence_sha256"] == _digest(plan[prefix + "_batches"]), "source stream sequence SHA mismatch")
    transfer = "binding" if arm == "repeat" else "augmentation"
    _check(receipt["transfer_sequence_sha256"] == _digest(plan[transfer + "_batches"])
           and receipt["transfer_data_role"] == ("old_binding" if arm == "repeat" else "augmentation"), "transfer arm data mismatch")
    _check(len(receipt["updates"]) == updates * 3, "missing or extra optimizer updates")
    exposures = {stream: Counter() for stream in STREAMS}
    nested, maxima = dict(cpu_ns=0, wall_ns=0), dict(CE=0., pair=0., anchor=0., total=0.)
    for index, row in enumerate(receipt["updates"]):
        cycle, stream = index // 3, STREAMS[index % 3]
        prefix = "natural" if stream == "natural" else "binding" if stream == "retention" else transfer
        indices = plan[prefix + "_batches"][cycle]
        selected = [prefixes[prefix][i] for i in indices]
        ids = [_id(item) for item in selected]
        _check(row["step"] == index + 1 and row["logical_step"] == cycle + 1 and row["stream"] == stream
               and row["data_role"] == prefix and row["indices"] == indices and row["case_ids"] == ids
               and row["sample_sha256"] == _digest(ids) and row["exposures"] == 16, "executed three-stream sampling differs from plan")
        anchor_weight = float(arm == "anchored" and stream == "retention")
        pair_weight = 0. if stream == "natural" else .5
        losses = replay_losses(row["logits"], selected, paired=stream != "natural",
                               teacher=[teacher[i] for i in indices] if anchor_weight else None)
        for field, key in (("binary_cross_entropy", "CE"), ("pair_loss", "pair"), ("anchor_mse", "anchor")):
            same(row[field], losses[field], "raw-logit loss replay mismatch: " + field)
            maxima[key] = max(maxima[key], abs(row[field] - losses[field]))
        _check(row["pair_weight"] == pair_weight and row["anchor_weight"] == anchor_weight, "anchor/pair applied to an unregistered stream")
        total = losses["binary_cross_entropy"] + pair_weight * losses["pair_loss"] + anchor_weight * losses["anchor_mse"]
        same(row["total_loss"], total, "raw-logit total objective replay mismatch")
        maxima["total"] = max(maxima["total"], abs(row["total_loss"] - total))
        _check(row["depth"] == 3 and row["inference_feature_arguments"] == 6
               and row["finite_gradients"] is True and row["finite_parameters_after_update"] is True,
               "public argument/depth or finite gradient boundary changed")
        for key in ("hop_state_gradient_l2", "hop_state_saturation_fraction", "hop_state_max_abs"):
            _check(len(row[key]) == 3 and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in row[key]), "incomplete/nonfinite recurrent gradient/state observation")
        _check(all(v <= 1. for v in row["hop_state_saturation_fraction"])
               and all(v <= 1.000001 for v in row["hop_state_max_abs"]), "state bounds violated")
        _check(type(row["parameter_gradient_l2"]) in (int, float) and math.isfinite(row["parameter_gradient_l2"])
               and row["parameter_gradient_l2"] >= 0, "finite parameter gradient norm required")
        cost = _cost(row)
        for axis in nested:
            nested[axis] += cost[axis]
        exposures[stream].update(ids)
    grid = list(range(0, updates + 1, 100))
    if grid[-1] != updates:
        grid.append(updates)
    _check([d["logical_step"] for d in receipt["diagnostics"]] == grid, "fixed diagnostic grid changed")
    for diagnostic in receipt["diagnostics"]:
        _check(diagnostic["optimizer_steps"] == diagnostic["logical_step"] * 3, "diagnostic optimizer position mismatch")
        for role, rows in (("binding", old), ("augmentation", augmentation)):
            report = diagnostic[role]
            audit_scores(rows, report["probabilities"], report)
            cost = _cost(report)
            for axis in nested:
                nested[axis] += cost[axis]
    for stream in STREAMS:
        _check(receipt["completed_" + stream + "_updates"] == updates
               and receipt["actual_" + stream + "_exposures"] == updates * 16
               and receipt["case_exposures"][stream] == dict(exposures[stream]), "stream exposure accounting mismatch")
    sources = set(core["training_source_groups"]) | {r["source_hash"] for r in natural + old}
    if arm != "repeat":
        sources.update(r["source_hash"] for r in augmentation)
    _check(receipt["training_source_groups"] == sorted(sources) and receipt["actual_total_exposures"] == updates * 48
           and receipt["parameter_count"] == core["parameter_count"] == 42562 and receipt["parameter_bytes"] == 42562 * 4
           and receipt["frozen"] is True and receipt["original_model_unchanged"] is True
           and receipt["planned_stream_update_budgets_equal"] is True and receipt["actual_stream_update_counts_equal"] is True
           and receipt["strict_equal_compute"] is False and receipt["final_evaluation_authorized"] is False,
           "final freeze/parameters/training-source scope mismatch")
    outer = _cost(receipt)
    _check(all(outer[k] >= nested[k] for k in outer) and receipt["formula_flops"] is None
           and receipt["nested_costs_additive"] is False, "fit outer cost omits work or adds nested costs")
    return dict(passed=True, arm=arm, optimizer_updates=updates * 3, total_exposures=updates * 48,
        unique_training_cases={s: len(v) for s, v in exposures.items()}, replay_max_absolute_errors=maxima,
        shared_fit_cost_once=outer, nested_costs_not_added=nested, teacher_preparation_charged_in_fit=False,
        numerical_replay_tolerance=dict(absolute=2e-6, relative=2e-5), independent_neural_execution=False)


def natural_metrics(rows, probabilities):
    _check(rows and len(rows) == len(probabilities) and all(type(p) in (int, float) and math.isfinite(p)
           and 0 <= p <= 1 for p in probabilities), "complete natural probabilities required")
    groups = defaultdict(list)
    for row, p in zip(rows, probabilities):
        groups[tuple(row[k] for k in ("source_split", "paragraph_id", "question_id"))].append((row["label"], int(p > .5)))
    def f1(pairs, label):
        denom = sum(y == label for y, _ in pairs) + sum(p == label for _, p in pairs)
        return 2 * sum(y == p == label for y, p in pairs) / denom if denom else 0.
    pairs = [(r["label"], int(p > .5)) for r, p in zip(rows, probabilities)]
    macro = [sum(f1(value, y) for y in {a for pair in value for a in pair}) /
             len({a for pair in value for a in pair}) for value in groups.values()]
    return dict(candidates=len(rows), questions=len(groups), paragraphs=len({(r["source_split"], r["paragraph_id"]) for r in rows}),
        f1_a=f1(pairs, 1), f1_m=sum(macro) / len(macro), exact_match=sum(all(y == p for y, p in v) for v in groups.values()) / len(groups),
        accuracy=sum(y == p for y, p in pairs) / len(pairs),
        probability_CE=-sum(math.log(max(1e-12, p if row["label"] else 1-p)) for row, p in zip(rows, probabilities)) / len(rows))


def constants(rows):
    prior = sum(r["label"] for r in rows) / len(rows)
    return dict(positive_prior=prior, majority_class=int(prior > .5), prior_constant_CE=-prior * math.log(prior) - (1-prior) * math.log(1-prior),
        always_negative=natural_metrics(rows, [0.] * len(rows)), always_positive=natural_metrics(rows, [1.] * len(rows)),
        training_only=True, threshold_selected=False)


def joint_gate(old, baseline, relation, natural, start, baselines):
    _check(baseline["cases"] == old["cases"] == 128 and baseline["groups"] == old["groups"] == 32
           and baseline["accuracy"] == baseline["both_worlds_correct"] == baseline["all_four_correct"] == 1.
           and baseline["probability_CE"] <= .10 and relation["cases"] == 64 and relation["paired_candidates"] == 32,
           "complete qualified old warmup and internal relation panels required")
    retained = []
    for key in ("accuracy", "both_worlds_correct"):
        if old[key] + 1e-12 < .95:
            retained.append(key + "_below_0.95")
        if baseline[key] - old[key] > .05 + 1e-12:
            retained.append(key + "_drop_above_0.05")
    cheap = max(baselines[key]["f1_m"] for key in ("always_negative", "always_positive"))
    reasons = ["retention:" + reason for reason in retained]
    for passed, reason in ((relation["accuracy"] + 1e-12 >= .75, "relation_candidate_below_0.75"),
        (relation["both_worlds_correct"] + 1e-12 >= .50, "relation_pairs_below_0.50"),
        (natural["f1_m"] + 1e-12 >= cheap + .05, "natural_F1m_gain_below_0.05"),
        (natural["f1_a"] + 1e-12 >= start["f1_a"] + .05, "natural_F1a_gain_below_0.05"),
        (natural["exact_match"] + 1e-12 >= .05, "natural_EM_below_0.05"),
        (natural["probability_CE"] <= baselines["prior_constant_CE"] * .95 + 1e-12, "natural_CE_not_5percent_below_prior")):
        if not passed:
            reasons.append(reason)
    retention = dict(passed=not retained, reasons=retained, scope="complete_binding_train_retention_only",
                     natural_internal_tune_required_separately=True, fresh_selection=False)
    return dict(passed=not reasons, reasons=reasons, retention=retention,
        requirements=dict(relation_candidate=.75, relation_pairs=.50, natural_F1m_over_best_constant=.05,
                          natural_F1a_over_start=.05, natural_EM=.05, natural_CE_ratio_to_prior=.95),
        scope="V7_training_and_previously_exposed_internal_qualification", fresh_scores_used=False, generalization_established=False)


if __name__ == "__main__":
    import argparse
    from retention_v7_checkpoint_review import review

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "code", "natural-cases", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--stage", choices=("prepare", "training"), default="prepare")
    args = parser.parse_args()
    report = review(args.run, args.code, args.natural_cases, stage=args.stage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
