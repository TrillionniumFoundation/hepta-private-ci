"""Pure stdlib V7 audit fixtures; no neural experiment is executed here."""
from collections import Counter
import copy
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import struct
import tempfile
import unittest

from binding_review import _digest, _id, audit_scores
from retention_v7_review import (ARMS, STREAMS, audit_plan, audit_teacher,
    audit_training, constants, joint_gate, natural_metrics, replay_losses)


def hashed(value):
    return sha256(str(value).encode()).hexdigest()


def cases(groups=4, seed=41):
    """Handwritten independently parseable ownership/storage worlds."""
    result = []
    for group in range(groups):
        for world in (0, 1):
            owners = (f"Ada{group}", f"Ben{group}") if not world else (f"Ben{group}", f"Ada{group}")
            facts = [f"The coin{seed}_{group} belongs to {owners[0]}.",
                     f"The bead{seed}_{group} belongs to {owners[1]}.",
                     f"Ada{group} stores all their possessions in the blue box.",
                     f"Ben{group} stores all their possessions in the green box."]
            for answer in (0, 1):
                result.append(dict(source_split="train", paragraph_id=f"binding-fixture/{seed}/{group}/world-{world}",
                    question_id="0", answer_id=str(answer), facts=facts,
                    question=f"Where is the coin{seed}_{group} stored?", candidate=f"The {('blue', 'green')[answer]} box.",
                    label=int(answer == world), source_hash=sha256("\n".join(facts).encode()).hexdigest(),
                    sentence_ids=[1, 2, 3, 4], evidence_sentence_indices=[1, 3 + world],
                    segmentation="synthetic-ownership-storage-v1"))
    return result


def group_schedule(rows, updates, seed):
    """Fixture scheduler: groups remain intact, epoch order is separately seeded."""
    groups = {}
    for index, row in enumerate(rows):
        groups.setdefault(row["paragraph_id"].rsplit("/world-", 1)[0], []).append(index)
    groups = list(groups.values())
    rng, batches = random.Random(seed), []
    while len(batches) < updates:
        order = list(range(len(groups)))
        rng.shuffle(order)
        for start in range(0, len(order), 4):
            batches.append([index for group in order[start:start + 4] for index in groups[group]])
            if len(batches) == updates:
                break
    return batches


def plan_fixture(natural, old, augmentation, updates=2, seed=41):
    rng = random.Random(f"hepta-binding-natural-v5/{seed}")
    plan = dict(schema="hepta.binding.continuation-plan.v1", seed=seed, updates=updates, batch_size=16,
        logical_update_order=list(STREAMS), natural_batches=[rng.sample(range(len(natural)), 16) for _ in range(updates)],
        binding_batches=group_schedule(old, updates, seed), retention_schema="hepta.retention.plan.v7",
        stream_order=list(STREAMS), arms=list(ARMS), augmentation_seed=seed ^ 0x713,
        augmentation_batches=group_schedule(augmentation, updates, seed ^ 0x713), synthetic_pair_weight=.5,
        anchored_retention_weight=1., learning_rates={arm: .0001 if arm == "low_lr" else .001 for arm in ARMS})
    for prefix, rows in (("natural", natural), ("binding", old), ("augmentation", augmentation)):
        plan[prefix + "_case_ids"] = [_id(row) for row in rows]
        plan[prefix + "_targets"] = [row["label"] for row in rows]
        plan[prefix + "_source_groups"] = [row["source_hash"] for row in rows]
    plan["plan_sha256"] = _digest(plan)
    return plan


def teacher_fixture(folder, old):
    values = [[float(index), float(index + 1)] for index in range(len(old))]
    raw = b"".join(struct.pack("<2f", *row) for row in values)
    (folder / "teacher-logits.bin").write_bytes(raw)
    core = dict(seed=41, execution_parameter_sha256=hashed("typed-execution"),
        training_parameter_sha256=hashed("legacy-training"), file_sha256=hashed("zip-file"))
    cache = {name: hashed(name) for name in ("metadata.json", "tokens.pt")}
    ids = [_id(row) for row in old]
    teacher = dict(schema="hepta.retention.teacher.v7", raw_file="teacher-logits.bin", dtype="torch.float32",
        shape=[len(old), 2], raw_tensor_bytes=len(raw), raw_file_sha256=sha256(raw).hexdigest(),
        raw_logits_sha256=sha256(raw).hexdigest(), logits=values, case_ids=ids,
        public_source_sha256=[sha256("\n".join(("[QUESTION]", r["question"], "[CANDIDATE]", r["candidate"], "[PASSAGE]", *r["facts"])).encode()).hexdigest() for r in old],
        feature_cache_files_sha256=cache, model_execution_parameter_sha256=core["execution_parameter_sha256"],
        model_training_parameter_sha256=core["training_parameter_sha256"], warmup_weight_file_sha256=core["file_sha256"],
        teacher_frozen=True, labels_entered_model=False, inference_feature_arguments=6,
        used_by="anchored_retention_loss_only", common_preparation_not_recharged_per_arm=True,
        batches=[dict(case_ids=ids[i:i + 16], cpu_ns=2, wall_ns=3) for i in range(0, len(old), 16)],
        phase_cost=dict(cpu_ns=100, wall_ns=200))
    return teacher, core, cache


def training_fixture(arm="anchored"):
    natural, old, augmentation, updates = cases(seed=47), cases(), cases(groups=8, seed=53), 2
    plan = plan_fixture(natural, old, augmentation, updates)
    teacher = [[0., 0.] for _ in old]
    sources = sorted({r["source_hash"] for r in old})
    core = dict(seed=41, training_parameter_sha256=hashed("initial"), parameter_count=42562,
                training_source_groups=sources)
    receipt = dict(schema="hepta.retention.continuation.v7", arm=arm, status="completed", seed=41,
        requested_logical_updates=updates, completed_steps=updates, plan_sha256=plan["plan_sha256"],
        initial_model_sha256=core["training_parameter_sha256"], optimizer="Adam_foreach_false",
        learning_rate=plan["learning_rates"][arm], pair_weight=.5, anchor_weight=float(arm == "anchored"),
        depth=3, batch_size=16, stream_order=list(STREAMS), stopping_rule="fixed_budget_diagnostics_do_not_select",
        teacher_logits_sha256=sha256(b"\0" * len(old) * 8).hexdigest(), teacher_logits_shape=[len(old), 2],
        teacher_logits_dtype="torch.float32", teacher_calls_inside_fit=0, teacher_logits_unchanged=True,
        teacher_preparation_scope="external_once_per_seed_shared_all_arms_not_recharged_here",
        anchor_applies_only_to="retention", raw_step_logits_recorded=True,
        transfer_data_role="old_binding" if arm == "repeat" else "augmentation", updates=[], diagnostics=[],
        case_exposures={s: {} for s in STREAMS}, actual_total_exposures=updates * 48,
        parameter_count=42562, parameter_bytes=42562 * 4, frozen=True, original_model_unchanged=True,
        planned_stream_update_budgets_equal=True, actual_stream_update_counts_equal=True,
        strict_equal_compute=False, final_evaluation_authorized=False, cpu_ns=1000, wall_ns=2000,
        formula_flops=None, nested_costs_additive=False)
    for prefix in ("natural", "binding", "augmentation"):
        receipt[prefix + "_sequence_sha256"] = _digest(plan[prefix + "_batches"])
    transfer = "binding" if arm == "repeat" else "augmentation"
    receipt["transfer_sequence_sha256"] = _digest(plan[transfer + "_batches"])
    rows_by_role = dict(natural=natural, binding=old, augmentation=augmentation)
    exposure_counts = {s: Counter() for s in STREAMS}
    for cycle in range(updates):
        for stream in STREAMS:
            role = "natural" if stream == "natural" else "binding" if stream == "retention" else transfer
            indices = plan[role + "_batches"][cycle]
            selected = [rows_by_role[role][i] for i in indices]
            ids = [_id(row) for row in selected]
            pair_weight, anchor_weight = (.0 if stream == "natural" else .5), float(arm == "anchored" and stream == "retention")
            # Scores are +/-1, so each CE and every pair softplus margin are softplus(-1).
            ce = math.log1p(math.exp(-1.))
            pair, anchor = (0. if stream == "natural" else ce), (.25 if anchor_weight else 0.)
            receipt["updates"].append(dict(step=len(receipt["updates"]) + 1, logical_step=cycle + 1,
                stream=stream, data_role=role, indices=indices, case_ids=ids, sample_sha256=_digest(ids), exposures=16,
                logits=[[0., 1.] if row["label"] else [1., 0.] for row in selected], binary_cross_entropy=ce,
                pair_loss=pair, pair_weight=pair_weight, anchor_mse=anchor, anchor_weight=anchor_weight,
                total_loss=ce + pair_weight * pair + anchor_weight * anchor,
                depth=3, inference_feature_arguments=6, finite_gradients=True, finite_parameters_after_update=True,
                parameter_gradient_l2=.2, hop_state_gradient_l2=[.1, .2, .3],
                hop_state_saturation_fraction=[0., 0., 0.], hop_state_max_abs=[.1, .2, .3], cpu_ns=2, wall_ns=3))
            exposure_counts[stream].update(ids)
    for stream in STREAMS:
        receipt["completed_" + stream + "_updates"] = updates
        receipt["actual_" + stream + "_exposures"] = updates * 16
        receipt["case_exposures"][stream] = dict(exposure_counts[stream])
    for step in (0, updates):
        diagnostic = dict(logical_step=step, optimizer_steps=step * 3)
        for role, rows in (("binding", old), ("augmentation", augmentation)):
            probabilities = [.75 if r["label"] else .25 for r in rows]
            diagnostic[role] = dict(probabilities=probabilities, cpu_ns=2, wall_ns=3, **audit_scores(rows, probabilities))
        receipt["diagnostics"].append(diagnostic)
    receipt["training_source_groups"] = sorted(set(sources) | {r["source_hash"] for r in natural + old + ([] if arm == "repeat" else augmentation)})
    return receipt, plan, teacher, natural, old, augmentation, core


class RetentionV7ReviewTests(unittest.TestCase):
    def test_stable_logit_ce_survives_probability_saturation(self):
        rows = [dict(label=1), dict(label=0)]
        report = replay_losses([[100., -100.], [-100., 100.]], rows)
        self.assertAlmostEqual(report["binary_cross_entropy"], 200.)
        self.assertEqual(report["pair_loss"], 0.)
        self.assertEqual(report["anchor_mse"], 0.)

    def test_pair_margin_is_once_per_candidate_across_opposite_worlds(self):
        rows = cases(groups=1)
        logits = [[0., 1.] if r["label"] else [1., 0.] for r in rows]
        report = replay_losses(logits, rows, paired=True)
        expected = math.log1p(math.exp(-1.))
        self.assertAlmostEqual(report["binary_cross_entropy"], expected)
        self.assertAlmostEqual(report["pair_loss"], expected)
        wrong = replay_losses([[0., 0.]] * 4, rows, paired=True)
        self.assertAlmostEqual(wrong["pair_loss"], math.log1p(math.e))

    def test_centered_teacher_mse_discards_per_row_common_offset(self):
        rows = [dict(label=1), dict(label=0)]
        teacher = [[-2., 2.], [1., 3.]]
        student = [[98., 102.], [-9., -7.]]
        self.assertEqual(replay_losses(student, rows, teacher=teacher)["anchor_mse"], 0.)
        self.assertEqual(replay_losses([[0., 2.], [0., 2.]], rows, teacher=[[0., 0.], [0., 0.]])["anchor_mse"], 1.)

    def test_raw_logit_shape_nonfinite_and_non_fp32_values_rejected(self):
        for logits in ([[[0., 1., 2.]]], [[[0., float("nan")]]], [[[0., 0.1]]]):
            with self.subTest(logits=logits), self.assertRaisesRegex(ValueError, "raw FP32"):
                replay_losses(logits[0], [dict(label=1)])

    def test_natural_metrics_use_raw_strict_threshold_and_question_macro(self):
        rows = [dict(source_split="train", paragraph_id="p", question_id=q, label=y)
                for q, y in (("q1", 1), ("q1", 0), ("q2", 0), ("q2", 0))]
        report = natural_metrics(rows, [.5, .5, .5, .5])
        self.assertEqual(report["accuracy"], .75)
        self.assertEqual(report["f1_a"], 0.)
        self.assertAlmostEqual(report["f1_m"], 2 / 3)
        self.assertEqual(report["exact_match"], .5)
        self.assertEqual(report["questions"], 2)
        self.assertEqual(report["paragraphs"], 1)
        baseline = constants(rows)
        self.assertEqual(baseline["positive_prior"], .25)
        self.assertFalse(baseline["threshold_selected"])

    def test_joint_gate_requires_retention_relation_and_natural_simultaneously(self):
        baseline = dict(cases=128, groups=32, accuracy=1., both_worlds_correct=1., all_four_correct=1., probability_CE=.05)
        relation = dict(cases=64, paired_candidates=32, accuracy=.75, both_worlds_correct=.5)
        natural = dict(f1_m=.45, f1_a=.65, exact_match=.05, probability_CE=.6)
        start = dict(f1_a=.6)
        cheap = dict(always_negative=dict(f1_m=.3), always_positive=dict(f1_m=.4), prior_constant_CE=.7)
        old = dict(baseline, accuracy=.95, both_worlds_correct=.95)
        self.assertTrue(joint_gate(old, baseline, relation, natural, start, cheap)["passed"])
        variants = [("retention", lambda a, b, c: a.update(accuracy=.94)),
                    ("relation", lambda a, b, c: b.update(both_worlds_correct=.49)),
                    ("natural", lambda a, b, c: c.update(exact_match=.049))]
        for name, mutation in variants:
            a, b, c = copy.deepcopy((old, relation, natural))
            mutation(a, b, c)
            with self.subTest(panel=name):
                result = joint_gate(a, baseline, b, c, start, cheap)
                self.assertFalse(result["passed"])
                self.assertTrue(any(name in reason for reason in result["reasons"]))

    def test_plan_replays_independent_natural_and_augmentation_namespaces(self):
        natural, old, augmentation = cases(seed=47), cases(groups=8), cases(groups=8, seed=53)
        plan = plan_fixture(natural, old, augmentation)
        report = audit_plan(plan, natural, old, augmentation, updates=2)
        self.assertTrue(report["passed"])
        mutations = [lambda p: p.update(augmentation_seed=p["seed"]),
            lambda p: p["natural_batches"][0].reverse(), lambda p: p["augmentation_batches"][0].reverse(),
            lambda p: p["augmentation_targets"].__setitem__(0, 1 - p["augmentation_targets"][0])]
        for mutation in mutations:
            changed = copy.deepcopy(plan)
            mutation(changed)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "deterministic sampling"):
                audit_plan(changed, natural, old, augmentation, updates=2)

    def test_teacher_raw_bytes_row_order_and_dual_checkpoint_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, rows = Path(directory), cases()
            teacher, core, cache = teacher_fixture(folder, rows)
            values, report = audit_teacher(folder, teacher, rows, core, cache)
            self.assertEqual(values, teacher["logits"])
            self.assertEqual(report["preparation_cost_once"], dict(cpu_ns=100, wall_ns=200))
            mutations = [("row order", lambda t: t["case_ids"].reverse()),
                ("raw tensor", lambda t: t.update(raw_logits_sha256=hashed("wrong"))),
                ("digest encodings", lambda t: t.update(model_execution_parameter_sha256=core["training_parameter_sha256"])),
                ("feature/cache", lambda t: t["feature_cache_files_sha256"].update(**{"tokens.pt": hashed("wrong")})),
                ("outer cost", lambda t: t.update(phase_cost=dict(cpu_ns=0, wall_ns=0)))]
            for message, mutation in mutations:
                changed = copy.deepcopy(teacher)
                mutation(changed)
                with self.subTest(mutation=message), self.assertRaisesRegex(ValueError, message):
                    audit_teacher(folder, changed, rows, core, cache)

    def test_teacher_raw_file_mutation_is_detected_before_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, rows = Path(directory), cases()
            teacher, core, cache = teacher_fixture(folder, rows)
            raw = bytearray((folder / "teacher-logits.bin").read_bytes())
            raw[-1] ^= 1
            (folder / "teacher-logits.bin").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "byte SHA"):
                audit_teacher(folder, teacher, rows, core, cache)

    def test_complete_tiny_three_stream_fits_replay_for_all_four_arms(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                fixture = training_fixture(arm)
                report = audit_training(*fixture, arm, updates=2)
                self.assertTrue(report["passed"])
                self.assertEqual(report["optimizer_updates"], 6)
                self.assertEqual(report["total_exposures"], 96)
                self.assertEqual(report["shared_fit_cost_once"], dict(cpu_ns=1000, wall_ns=2000))
                self.assertEqual(report["nested_costs_not_added"], dict(cpu_ns=20, wall_ns=30))
                self.assertFalse(report["teacher_preparation_charged_in_fit"])

    def test_training_rejects_loss_schedule_teacher_exposure_source_and_cost_mutations(self):
        fixture = training_fixture()
        mutations = [lambda r: r["updates"][0].update(binary_cross_entropy=.1),
            lambda r: r["updates"][1].update(stream="retention"),
            lambda r: r["updates"][0].update(anchor_weight=1.),
            lambda r: r["updates"][2].update(anchor_mse=.5),
            lambda r: r.update(teacher_calls_inside_fit=1),
            lambda r: r.update(actual_total_exposures=95),
            lambda r: r["training_source_groups"].pop(),
            lambda r: r["updates"][0].update(hop_state_max_abs=[2., 0., 0.]),
            lambda r: r.update(cpu_ns=19), lambda r: r["diagnostics"].pop()]
        for mutation in mutations:
            receipt = copy.deepcopy(fixture[0])
            mutation(receipt)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_training(receipt, *fixture[1:], "anchored", updates=2)


if __name__ == "__main__":
    unittest.main()
