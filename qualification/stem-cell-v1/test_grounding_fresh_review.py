"""Synthetic stdlib fixtures; no actual holdout observations or neural execution."""
import copy
from dataclasses import asdict
import json
import re
import statistics
import unittest

from binding_protocol import build_binding_protocol
from binding_review import _id, audit_scores
from grounding_fresh_review import (ARMS, ROLES, SEEDS, _auxiliary, _panel,
    audit_fresh_cases, audit_latency, chronology, seed_gate)
from grounding_protocol import build_grounding_protocol, grounding_manifest
from grounding_span_review import audit_span_targets
from grounding_spans import make_grounding_targets
from retention_data import build_augmentation
from token_protocol import build_binding_cases


class Tokenizer:
    is_fast = True

    def __call__(self, text, **kwargs):
        spans = [m.span() for m in re.finditer(r"[A-Za-z]+|[^\w\s]", text)]
        return dict(input_ids=list(range(1, len(spans)+1)), offset_mapping=spans)


class GroundingFreshReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        historical = build_binding_protocol(seed=41)
        augmentation, _ = build_augmentation(historical)
        parts = build_grounding_protocol(historical, augmentation)
        serial = lambda value: json.loads(json.dumps(value))
        cls.parts = {r: serial([asdict(c) for c in cs]) for r, cs in parts.items()}
        cls.manifest = grounding_manifest(parts, historical, augmentation)
        cls.historical = {r: serial([asdict(c) for c in cs]) for r, cs in historical.items()}
        cls.augmentation = serial([asdict(c) for c in augmentation])
        cls.old_final = serial([asdict(c) for c in build_binding_cases("final", groups=32, seed=41)])
        cls.partial_final = [{k: r[k] for k in ("candidate", "facts", "label", "paragraph_id", "question", "segmentation", "source_hash")}
                             | dict(case_id=_id(r)) for r in cls.old_final]
        cls.rows = cls.parts[ROLES[0]]
        cls.model = dict(execution_parameter_sha256="a"*64, frozen_ns=5)
        cls.p = [.9 if r["label"] else .1 for r in cls.rows]

    def membership(self, parts=None, manifest=None):
        return audit_fresh_cases(parts or self.parts, manifest or self.manifest,
                                self.historical, self.augmentation, self.old_final)

    def test_membership_independent_grammar_and_historical_exclusions(self):
        self.assertTrue(self.membership()["passed"])
        for name in ("excluded_source_keys_sha256", "excluded_semantic_tasks_sha256"):
            changed = copy.deepcopy(self.manifest); changed[name] = "0"*64
            with self.assertRaises(ValueError): self.membership(manifest=changed)
        changed = copy.deepcopy(self.parts); changed[ROLES[0]][0]["label"] ^= 1
        with self.assertRaisesRegex(ValueError, "truth"): self.membership(parts=changed)

    def test_missing_world_and_source_hash_mutations_fail(self):
        changed = copy.deepcopy(self.parts); changed[ROLES[0]].pop()
        with self.assertRaises(ValueError): self.membership(parts=changed)
        changed = copy.deepcopy(self.parts); changed[ROLES[0]][0]["source_hash"] = "0"*64
        with self.assertRaisesRegex(ValueError, "source byte"): self.membership(parts=changed)

    def test_actual_legacy_partial_v4_schema_preserves_strong_exclusions(self):
        audit = lambda old: audit_fresh_cases(self.parts, self.manifest, self.historical, self.augmentation, old)
        self.assertEqual(audit(self.partial_final), audit(self.old_final))
        for identity in ("not-json", "{}", json.dumps(["validation", "wrong-paragraph", "0", "0"]),
                         json.dumps(["train", self.old_final[0]["paragraph_id"], "0", "0"]),
                         json.dumps(["validation", self.old_final[0]["paragraph_id"], 0, "0"])):
            changed = copy.deepcopy(self.partial_final); changed[0]["case_id"] = identity
            with self.assertRaisesRegex(ValueError, "legacy V4"): audit(changed)
        changed = copy.deepcopy(self.partial_final); changed[0]["facts"][0] += "changed"
        with self.assertRaisesRegex(ValueError, "exclusions"): audit(changed)

    def phases(self):
        models = {(s, a): self.model for s in SEEDS for a in ARMS}
        frozen = dict(manifests={f"seed-{s}/{a}/final-model.json": "b"*64 for s, a in models}, frozen_ns=10)
        return [frozen, dict(started_ns=20, retries_authorized=False, original_V5_fresh_opened=False),
            dict(encoding_started_ns=30, encoding_completed_ns=40),
            dict(completed_ns=50, actual_candidate_observations=3072, diagnostic_annotations_constructed=False,
                 selected_models_changed=False), dict(started_ns=60), dict(completed_ns=70), dict(completed_ns=80), models]

    def test_twelve_models_freeze_encoding_raw_targets_order(self):
        self.assertTrue(chronology(*self.phases())["passed"])
        for offset, key, value in ((2, "encoding_started_ns", 9), (4, "started_ns", 49),
                                   (4, "started_ns", 50), (1, "retries_authorized", True)):
            phases = self.phases(); phases[offset][key] = value
            with self.assertRaises(ValueError): chronology(*phases)

    def test_missing_twelfth_model_or_manifest_fails(self):
        for index in (0, 7):
            phases = self.phases()
            target = phases[0]["manifests"] if index == 0 else phases[7]
            target.pop(next(iter(target)))
            with self.assertRaisesRegex(ValueError, "twelve"): chronology(*phases)

    def panel(self):
        return dict(case_ids=[_id(r) for r in self.rows], probabilities=self.p,
            metrics=audit_scores(self.rows, self.p), model_execution_parameter_sha256="a"*64,
            depth=3, deleted=False, reset=False, labels_entered_model=False,
            batches=[dict(batch_id=str(i), case_ids=[_id(r) for r in self.rows[i*16:(i+1)*16]],
                steps=3, proposal_steps=48, cpu_ns=1, wall_ns=2) for i in range(8)])

    def test_panel_metrics_recomputed_including_strict_half_threshold(self):
        panel = self.panel(); self.assertEqual(_panel(self.rows, panel, self.model, raw=True)["metrics"]["accuracy"], 1.)
        panel["probabilities"] = [.5]*128; panel["metrics"] = audit_scores(self.rows, [.5]*128)
        self.assertEqual(_panel(self.rows, panel, self.model, raw=True)["metrics"]["both_worlds_correct"], 0.)
        panel["metrics"]["accuracy"] = 1.
        with self.assertRaisesRegex(ValueError, "metric"): _panel(self.rows, panel, self.model, raw=True)

    def test_physical_batch_coverage_and_cost_fail_closed(self):
        for name, value in (("batch_id", "0"), ("proposal_steps", 47), ("cpu_ns", -1)):
            panel = self.panel(); panel["batches"][1][name] = value
            with self.assertRaises(ValueError): _panel(self.rows, panel, self.model, raw=True)

    def test_gate_integer_boundaries_and_separate_two_domains(self):
        metrics = {r: dict(cases=128, groups=32, paired_candidates=64, accuracy=109/128, both_worlds_correct=48/64) for r in ROLES}
        self.assertTrue(seed_gate(metrics)["passed"])
        for patch in (dict(accuracy=108/128), dict(both_worlds_correct=47/64)):
            changed = copy.deepcopy(metrics); changed[ROLES[1]].update(patch)
            self.assertFalse(seed_gate(changed)["passed"])
        metrics[ROLES[0]]["accuracy"] = .85
        with self.assertRaisesRegex(ValueError, "integer"): seed_gate(metrics)

    def latency(self):
        results = {}
        for name, n in (("batch1", 1), ("batch2", 2)):
            measurements = [dict(cpu_ns=i, wall_ns=i+1) for i in range(1, 21)]
            summary = {k: dict(median_ns=statistics.median(r[k] for r in measurements),
                p95_ns=statistics.quantiles([r[k] for r in measurements], n=20, method="inclusive")[18]) for k in ("cpu_ns", "wall_ns")}
            results[name] = dict(raw_measurements=measurements, summary=summary, candidate_count=n,
                trace_group_work=dict(input_rows=n, unique_fact_groups=1, reused_rows=n-1), probabilities=[.2, .8][:n])
        return dict(schema="hepta.grounding.cached-latency.v9", case_ids=[_id(r) for r in self.rows[:2]],
            model_execution_parameter_sha256="a"*64, warmup_forwards_per_geometry=3, timed_forwards_per_geometry=20,
            extra_trace_forwards=2, separate_validation_forwards=2, total_model_forwards=50,
            device="cpu", dtype="torch.float32", thread_count=1, legacy_depth=3, graph_depth=2,
            encoder_included_in_timed_scope=False, end_to_end_product_latency=False, same_parameters_implies_equal_cost=False,
            timed_scope="forward_only_cached_features_including_graph_public_dedup",
            warmup_and_validation_included_in_complete_evaluation_process=True, results=results,
            separate_probabilities=[.2, .8], batch_vs_separate_max_probability_delta=0.,
            phase_cost=dict(cpu_ns=1000, wall_ns=1000), frontend_cost=dict(cpu_ns=10, wall_ns=10))

    def test_latency_raw_arrays_p95_dedup_and_disjoint_cost_floor(self):
        self.assertEqual(audit_latency(self.latency(), self.rows, self.model)["model_forwards"], 50)
        for key, value in (("phase_cost", dict(cpu_ns=1, wall_ns=1)), ("separate_probabilities", [.3, .8]),
                           ("total_model_forwards", 48)):
            changed = self.latency(); changed[key] = value
            with self.assertRaises(ValueError): audit_latency(changed, self.rows, self.model)
        changed = self.latency(); changed["results"]["batch2"]["summary"]["cpu_ns"]["p95_ns"] += 1
        with self.assertRaisesRegex(ValueError, "p95"): audit_latency(changed, self.rows, self.model)

    def test_frozen_span_offsets_and_annotation_phase_are_reconstructed(self):
        rows = self.rows[:4]; tokenizer = Tokenizer()
        tokens = {t: tokenizer(t)["input_ids"] for r in rows for t in (*r["facts"], r["question"], r["candidate"])}
        target = make_grounding_targets(rows, tokens, tokenizer, role="frozen_diagnostic")
        self.assertTrue(audit_span_targets(rows, target, tokens, role="frozen_diagnostic")["passed"])
        changed = copy.deepcopy(target); next(iter(changed["public_token_alignments"].values()))["offset_mapping"][0] = [-1, 1]
        with self.assertRaisesRegex(ValueError, "offset"): audit_span_targets(rows, changed, tokens, role="frozen_diagnostic")
        changed = copy.deepcopy(target); changed["role"] = "training"
        with self.assertRaises(ValueError): audit_span_targets(rows, changed, tokens, role="frozen_diagnostic")

    def test_auxiliary_predictions_must_exactly_equal_prior_raw_phase(self):
        observations = [dict(indices=list(range(i*16, (i+1)*16)), case_ids=[_id(r) for r in self.rows[i*16:(i+1)*16]],
            depth=3, graph_depth=2, graph_reset=False, physical_forward_calls=1, candidate_observations=16,
            labels_or_annotations_entered_forward=False, logits=[[0., 0.]]*16, probabilities=[.5]*16,
            cpu_ns=1, wall_ns=2) for i in range(8)]
        record = dict(exact_probabilities_equal_raw=True, used_for_training_or_selection=False,
            model_execution_parameter_sha256="a"*64, observations=observations)
        raw = dict(probabilities=[.5]*128, model_execution_parameter_sha256="a"*64)
        callback = lambda *a, **k: dict(passed=True)
        self.assertTrue(_auxiliary(self.rows, record, raw, {}, "grounded_chain", callback)["passed"])
        record["observations"][0]["probabilities"][0] = .50000001
        with self.assertRaisesRegex(ValueError, "exactly"): _auxiliary(self.rows, record, raw, {}, "grounded_chain", callback)


if __name__ == "__main__":
    unittest.main()
