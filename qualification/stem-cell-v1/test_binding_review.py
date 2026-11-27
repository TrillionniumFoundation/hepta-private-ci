"""Mutation tests for the independent stdlib V5 auditor, without neural execution."""

import copy
from hashlib import sha256
import json
from pathlib import Path
import random
import tempfile
import unittest

from binding_protocol import binding_manifest, build_binding_protocol, score_binding_probabilities
from binding_review import (_digest, _group_batches, _id, _rows, audit_checkpoint,
    audit_continuation, audit_failure_receipt, audit_fresh_gate, audit_panel,
    audit_natural_panel, audit_protocol, audit_scores, audit_source_inventory, audit_warmup, review_bundle)


def update(cases, indices, step, *, stream=None, logical_step=None, pair_weight=.5):
    rows = _rows(cases)
    ids = [_id(rows[i]) for i in indices]
    record = dict(step=step, indices=indices, case_ids=ids, sample_sha256=_digest(ids),
        exposures=len(ids), binary_cross_entropy=.2, pair_loss=.3, pair_weight=pair_weight,
        total_loss=.2 + pair_weight * .3, parameter_gradient_l2=.4,
        inference_feature_arguments=6, cpu_ns=20, wall_ns=21)
    if stream is not None:
        record.update(stream=stream, logical_step=logical_step)
    return record


class BindingReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = build_binding_protocol()
        cls.cases = cls.parts["reader_train"]
        cls.probabilities = [.99 if c.label else .01 for c in cls.cases]
        cls.metrics = score_binding_probabilities(cls.cases, cls.probabilities)

    def warmup(self):
        rows = _rows(self.cases)
        batches = _group_batches(self.cases, 1, 16, 41)
        diagnostic = dict(self.metrics, n=128, binary_cross_entropy=self.metrics["probability_CE"],
                          probabilities=list(self.probabilities), cpu_ns=10, wall_ns=11)
        return dict(requested_steps=1, batch_size=16, seed=41, case_ids=[_id(r) for r in rows],
            case_ids_sha256=_digest([_id(r) for r in rows]), schedule_sha256=_digest(batches),
            updates=[update(self.cases, batches[0], 1)], completed_steps=1, actual_training_exposures=16,
            diagnostics=[dict(optimizer_step=1, binding=diagnostic)], train_gate_passed=True,
            status="train_gate_passed", training_source_groups=sorted({c.source_hash for c in self.cases}),
            model_sha256="a" * 64, parameter_count=3, cpu_ns=100, wall_ns=110)

    def panel(self):
        ids = [c.case_id for c in self.cases]
        return dict(case_ids=ids, labels_entered_model=False, probabilities=list(self.probabilities),
            metrics=dict(self.metrics), depth=3, model_execution_parameter_sha256="b" * 64,
            batches=[dict(batch_id=f"fixture/{i}", case_ids=ids[start:start + 16], steps=3,
                          proposal_steps=len(ids[start:start + 16]) * 3, cpu_ns=10, wall_ns=11)
                     for i, start in enumerate(range(0, len(ids), 16))])

    def continuation(self, arm="contrastive"):
        natural = list(self.parts["internal_tune"])
        binding, seed, updates = self.cases, 41, 2
        rng = random.Random(f"hepta-binding-natural-v5/{seed}")
        plan = dict(seed=seed, updates=updates, batch_size=16,
            natural_batches=[rng.sample(range(len(natural)), 16) for _ in range(updates)],
            binding_batches=_group_batches(binding, updates, 16, seed))
        for prefix, cases in (("natural", natural), ("binding", binding)):
            plan[prefix + "_case_ids"] = [c.case_id for c in cases]
            plan[prefix + "_targets"] = [c.label for c in cases]
            plan[prefix + "_source_groups"] = [c.source_hash for c in cases]
        plan["plan_sha256"] = _digest(plan)
        records = []
        for logical_step in range(1, updates + 1):
            for stream in (("natural",) if arm == "natural_only" else ("natural", "binding")):
                cases = natural if stream == "natural" else binding
                pair_weight = .5 if stream == "binding" and arm == "contrastive" else 0.
                records.append(update(cases, plan[stream + "_batches"][logical_step - 1], len(records) + 1,
                    stream=stream, logical_step=logical_step, pair_weight=pair_weight))
        binding_updates = 0 if arm == "natural_only" else updates
        receipt = dict(plan_sha256=plan["plan_sha256"], initial_model_sha256="a" * 64, arm=arm,
            status="completed", updates=records, completed_steps=updates,
            completed_natural_updates=updates, completed_binding_updates=binding_updates,
            actual_natural_exposures=updates * 16, actual_binding_exposures=binding_updates * 16,
            natural_sequence_sha256=_digest(plan["natural_batches"]),
            training_source_groups=sorted({c.source_hash for c in (*natural, *binding)}),
            diagnostics=[], cpu_ns=1000, wall_ns=1100)
        return receipt, plan, natural

    def test_independent_grammar_and_manifest_reject_label_and_membership_mutations(self):
        inventories = dict(dataset_files_sha256={"zip": "1" * 64}, source_files_sha256={"train": "2" * 64},
                           code_files_sha256={"runtime": "3" * 64})
        manifest = binding_manifest(self.parts, **inventories)
        self.assertTrue(audit_protocol(self.parts, manifest)["passed"])
        poisoned = {role: _rows(cases) for role, cases in self.parts.items()}
        poisoned["fresh_combinations"][0]["label"] ^= 1
        with self.assertRaisesRegex(ValueError, "truth"):
            audit_protocol(poisoned, manifest)
        changed = copy.deepcopy(manifest)
        changed["roles"]["verifier_fit"]["usage"] = "trained"
        with self.assertRaisesRegex(ValueError, "unused"):
            audit_protocol(self.parts, changed)
        changed = copy.deepcopy(manifest)
        changed["roles"]["reader_train"]["case_ids"] = []
        with self.assertRaisesRegex(ValueError, "membership"):
            audit_protocol(self.parts, changed)

    def test_scores_are_recomputed_without_using_a_pass_flag(self):
        metrics = audit_scores(self.cases, self.probabilities, self.metrics)
        self.assertAlmostEqual(metrics["probability_CE"], self.metrics["probability_CE"])
        wrong = dict(self.metrics, both_worlds_correct=.5, passed=True)
        with self.assertRaisesRegex(ValueError, "metric mismatch"):
            audit_scores(self.cases, self.probabilities, wrong)
        zeros = audit_scores(self.cases, [.5] * len(self.cases))
        self.assertEqual((zeros["accuracy"], zeros["both_worlds_correct"]), (.5, 0.))

    def test_saved_fp32_probabilities_do_not_reconstruct_logit_space_cross_entropy(self):
        # FP32 softmax can round a positive probability to one although its
        # negative-class logit loss remains finite. The two CE definitions must
        # remain separate rather than relaxing canonical probability_CE checks.
        probabilities = list(self.probabilities)
        negative = next(i for i, case in enumerate(self.cases) if not case.label)
        probabilities[negative] = 1.
        expected = audit_scores(self.cases, probabilities)
        logit_record = dict(n=128, accuracy=expected["accuracy"], binary_cross_entropy=.2)
        audited = audit_scores(self.cases, probabilities, logit_record)
        self.assertEqual(audited["probability_CE"], expected["probability_CE"])
        self.assertNotAlmostEqual(audited["probability_CE"], logit_record["binary_cross_entropy"])
        with self.assertRaisesRegex(ValueError, "metric mismatch: probability_CE"):
            audit_scores(self.cases, probabilities, dict(logit_record, probability_CE=.2))
        with self.assertRaisesRegex(ValueError, "logit-space CE"):
            audit_scores(self.cases, probabilities, dict(logit_record, binary_cross_entropy=float("nan")))

    def test_warmup_recounts_complete_updates_gate_and_nested_costs(self):
        receipt = self.warmup()
        report = audit_warmup(receipt, self.cases, self.metrics)
        self.assertTrue(report["qualified"])
        self.assertEqual(report["costs"]["outer"]["cpu_ns"], 100)
        self.assertEqual(report["costs"]["nested_decomposition"]["cpu_ns"], 30)
        for mutate, message in ((lambda r: r["updates"][0]["case_ids"].reverse(), "sampling"),
                                (lambda r: r.update(train_gate_passed=False), "pass flag"),
                                (lambda r: r.update(cpu_ns=25), "outer cost"),
                                (lambda r: r["updates"][0].update(inference_feature_arguments=7), "annotations")):
            changed = copy.deepcopy(receipt)
            mutate(changed)
            with self.assertRaisesRegex(ValueError, message):
                audit_warmup(changed, self.cases)

    def test_continuations_have_identical_natural_samples_despite_different_update_counts(self):
        reports = []
        for arm in ("natural_only", "replay", "contrastive"):
            receipt, plan, natural = self.continuation(arm)
            reports.append(audit_continuation(receipt, plan, natural, self.cases, self.warmup()))
        self.assertEqual(len({r["natural_sequence_sha256"] for r in reports}), 1)
        self.assertEqual([r["binding_updates"] for r in reports], [0, 2, 2])
        receipt, plan, natural = self.continuation()
        receipt["updates"][0]["indices"] = receipt["updates"][0]["indices"][::-1]
        with self.assertRaisesRegex(ValueError, "sampling"):
            audit_continuation(receipt, plan, natural, self.cases, self.warmup())
        receipt, plan, natural = self.continuation()
        plan["natural_case_ids"][0], plan["natural_case_ids"][1] = plan["natural_case_ids"][1], plan["natural_case_ids"][0]
        plan["plan_sha256"] = _digest({k: v for k, v in plan.items() if k != "plan_sha256"})
        receipt["plan_sha256"] = plan["plan_sha256"]
        with self.assertRaisesRegex(ValueError, "row binding"):
            audit_continuation(receipt, plan, natural, self.cases, self.warmup())

    def test_panel_recounts_each_physical_batch_once_and_rejects_duplication(self):
        panel = self.panel()
        result = audit_panel(self.cases, panel, {"execution_parameter_sha256": "b" * 64})
        self.assertEqual((result["physical_batches"], result["costs"]["cpu_ns"]), (8, 80))
        panel["batches"].append(panel["batches"][0])
        with self.assertRaisesRegex(ValueError, "physical batch"):
            audit_panel(self.cases, panel)

    def test_natural_internal_panel_uses_raw_probabilities_and_complete_physical_costs(self):
        cases = self.parts["internal_tune"]
        ids = [c.case_id for c in cases]
        panel = dict(case_ids=ids, probabilities=[.99 if c.label else .01 for c in cases],
            metrics=dict(candidates=64, questions=32, paragraphs=32, f1_a=1., exact_match=1., f1_m=1., accuracy=1.),
            threshold_selected=False, scope="old_training_source_internal_tune_not_fresh",
            model_execution_parameter_sha256="b" * 64,
            batches=[dict(batch_id=f"internal/{i}", case_ids=ids[start:start + 16], steps=3,
                          proposal_steps=48, cpu_ns=10, wall_ns=11) for i, start in enumerate(range(0, len(ids), 16))])
        report = audit_natural_panel(cases, panel, {"execution_parameter_sha256": "b" * 64})
        self.assertEqual((report["costs"]["cpu_ns"], report["metrics"]["exact_match"]), (40, 1.))
        changed = copy.deepcopy(panel)
        changed["probabilities"] = [.5] * len(cases)
        with self.assertRaisesRegex(ValueError, "natural metric"):
            audit_natural_panel(cases, changed)
        changed = copy.deepcopy(panel)
        changed["scope"] = "fresh"
        with self.assertRaisesRegex(ValueError, "scope"):
            audit_natural_panel(cases, changed)

    def test_checkpoint_bytes_and_source_provenance_are_bound_without_torch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            path.write_bytes(b"opaque fixture weights; not claimed as decoded tensors")
            receipt = self.warmup()
            manifest = dict(file=path.name, file_sha256=sha256(path.read_bytes()).hexdigest(),
                training_parameter_sha256="a" * 64, execution_parameter_sha256="b" * 64, parameter_count=3,
                training_source_groups=receipt["training_source_groups"], frozen_ns=100)
            report = audit_checkpoint(path, manifest, receipt)
            self.assertFalse(report["tensor_digest_independently_reconstructed"])
            receipt_path = Path(directory) / "model-training.json"
            receipt_path.write_text(json.dumps(receipt))
            manifest.update(training_receipt_file=receipt_path.name,
                            training_receipt_sha256=sha256(receipt_path.read_bytes()).hexdigest())
            self.assertTrue(audit_checkpoint(path, manifest, receipt)["passed"])
            receipt_path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "receipt byte hash"):
                audit_checkpoint(path, manifest)
            path.write_bytes(b"mutated weights")
            with self.assertRaisesRegex(ValueError, "byte hash"):
                audit_checkpoint(path, manifest)
            source = Path(directory) / "runtime.py"
            source.write_text("x = 1\n")
            source_hash = sha256(source.read_bytes()).hexdigest()
            self.assertTrue(audit_source_inventory(directory, {source.name: source_hash})["passed"])
            with self.assertRaisesRegex(ValueError, "source bytes"):
                audit_source_inventory(directory, {source.name: "0" * 64})

    def test_fresh_gate_rejects_missing_seed_retention_loss_and_early_start(self):
        warmups = [dict(seed=seed, metrics=self.metrics) for seed in (41, 47, 53)]
        retentions = copy.deepcopy(warmups)
        models = [dict(frozen_ns=90)]
        self.assertTrue(audit_fresh_gate(warmups, retentions, models, all_models_frozen_ns=100, fresh_started_ns=101)["passed"])
        with self.assertRaisesRegex(ValueError, "three"):
            audit_fresh_gate(warmups[:2], retentions, models, all_models_frozen_ns=100, fresh_started_ns=101)
        retentions[1]["metrics"]["both_worlds_correct"] = .9
        with self.assertRaisesRegex(ValueError, "retention"):
            audit_fresh_gate(warmups, retentions, models, all_models_frozen_ns=100, fresh_started_ns=101)
        with self.assertRaisesRegex(ValueError, "predates"):
            audit_fresh_gate(warmups, warmups, models, all_models_frozen_ns=100, fresh_started_ns=99)

    def test_failure_receipts_retain_partial_cost_and_never_qualify(self):
        receipt = dict(status="failed", error_type="FloatingPointError", error="nonfinite", cpu_ns=50, wall_ns=60,
            failed_attempt_time_included=True, updates=[dict(cpu_ns=20, wall_ns=21)], final_evaluation_authorized=False)
        report = audit_failure_receipt(receipt)
        self.assertFalse(report["qualified"])
        self.assertEqual(report["cost"]["cpu_ns"], 50)
        receipt["cpu_ns"] = 10
        with self.assertRaisesRegex(ValueError, "omits"):
            audit_failure_receipt(receipt)

    def test_index_counts_outer_and_physical_costs_once_even_with_path_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(name, value):
                (root / name).write_text(json.dumps(value))

            (root / "runtime.py").write_text("x = 1\n")
            runtime = {"runtime.py": sha256((root / "runtime.py").read_bytes()).hexdigest()}
            membership = binding_manifest(self.parts, dataset_files_sha256={"zip": "1" * 64},
                source_files_sha256={"train": "2" * 64}, code_files_sha256=runtime)
            write("design.json", dict(membership=membership, runtime_source_sha256=runtime))
            write("cases.json", {role: _rows(cases) for role, cases in self.parts.items()})
            receipt = self.warmup()
            write("warmup-training.json", receipt)
            (root / "warmup.pt").write_bytes(b"opaque fixture")
            model = dict(file="warmup.pt", file_sha256=sha256((root / "warmup.pt").read_bytes()).hexdigest(),
                training_parameter_sha256="a" * 64, execution_parameter_sha256="b" * 64,
                training_source_groups=receipt["training_source_groups"], parameter_count=3, frozen_ns=1)
            write("warmup-model.json", model)
            write("panel.json", self.panel())
            entry = dict(receipt="warmup-training.json", model="warmup-model.json", panel="panel.json")
            bundle = dict(cases="cases.json", design="design.json", code_dir=directory, warmups=[entry],
                          panels=[dict(role="reader_train", panel="panel.json", model="warmup-model.json")])
            report = review_bundle(bundle, root)
            self.assertEqual((report["fit_outer_cpu_ns_once"], report["panel_physical_cpu_ns_once"]), (100, 80))
            bundle["warmups"].append(dict(entry, receipt="./warmup-training.json"))
            with self.assertRaisesRegex(ValueError, "repeated fit"):
                review_bundle(bundle, root)


if __name__ == "__main__":
    unittest.main()
