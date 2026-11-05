#!/usr/bin/env python3
"""Synthetic reader controls; invented timings/verdicts are never native evidence."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pon_w1_legal_strategy_reader_v3 as reader

common = reader.common


def stamp(value):
    return dict(cpu_ns=value, wall_ns=value)


def row(kind, **fields):
    return dict(schema=reader.SCHEMA, kind=kind, **fields)


def fixture(name="zero", target_index=0, horizon=1, salt=0, exhausted=None):
    target = bytes.fromhex(reader.TARGETS[target_index])
    a, b, task, prefix = common.material(name)
    rows = [row("campaign", selector=reader.SELECTOR, **{"class": name}, target_index=target_index,
        target=target.hex(), reuse_winners=horizon, samples=reader.SAMPLES,
        attempt_budget=reader.ATTEMPT_BUDGET, seed=0, classes=list(reader.CLASSES),
        horizons=list(reader.HORIZONS), strategies=list(reader.STRATEGIES), paths=list(reader.PATHS),
        cases=list(reader.CASES), arithmetic=list(reader.ARITHMETIC), materialization=list(reader.MATERIALIZATION), material_setup=stamp(1000),
        clock="thread-cpu-and-monotonic-wall-ns", producer_timing_scope=reader.PRODUCER_SCOPE,
        verifier_timing_scope=reader.VERIFY_SCOPE, mutation_timing_scope=reader.MUTATION_SCOPE,
        evidence_timing_scope=reader.EVIDENCE_SCOPE,
        cross_horizon_challenges="same-prefix-not-independent",
        **reader.FALSE_FLAGS), row("material", **{"class": name},
        source="hash-generated-rank-checked" if name == "full-rank-field" else "synthetic-fixture",
        task=task.hex(), a_hex=a.hex(), b_hex=b.hex())]
    counts = dict.fromkeys(("cohort", "search", "candidate", "product_mutation", "verifier"), 0)

    def add(kind, **fields):
        counts[kind] += 1
        rows.append(row(kind, **fields))

    for sample in range(reader.SAMPLES):
        searches = []
        for index in range(horizon):
            attempts = []
            for nonce in range(reader.ATTEMPT_BUDGET):
                context = reader.challenge(task, target, sample, index, nonce)
                perturbation = 0
                while True:
                    trace = common.pon_hash(b"synthetic-reader-not-W1", context,
                        salt.to_bytes(8, "little"), perturbation.to_bytes(8, "little"))
                    ticket = common.pon_hash(b"ticket", context, trace)
                    if (sample, index) != exhausted or ticket > target:
                        break
                    perturbation += 1
                hit = ticket <= target
                proof = prefix + trace
                attempts.append(dict(nonce=nonce, challenge=context.hex(), trace=trace.hex(),
                    ticket=ticket.hex(), proof_sha256=common.sha(proof), target_hit=hit))
                if hit:
                    break
            winner = dict(challenge=context.hex(), proof_sha256=common.sha(proof)) if hit else None
            searches.append(dict(attempts=attempts, winner=winner, proof=proof if hit else None,
                timing=stamp(len(attempts) * 10 + 10)))
        for order in range(len(reader.STRATEGIES)):
            strategy = reader.STRATEGIES[(sample + target_index + order) % len(reader.STRATEGIES)]
            arithmetic, materialization = reader.factors(strategy)
            add("cohort", sample=sample, strategy=strategy, invocation_order=order, setup_calls=1,
                searches=horizon, arithmetic=arithmetic, materialization=materialization, setup=stamp(100),
                total=stamp(101 + sum(s["timing"]["cpu_ns"] for s in searches)))
            for index, searched in enumerate(searches):
                add("search", sample=sample, strategy=strategy, search_index=index, setup_calls=0,
                    timing=searched["timing"].copy(),
                    attempts=[dict(copy.deepcopy(t), proof_materialized=materialization == "every-attempt" or t["target_hit"]) for t in searched["attempts"]],
                    proof_materializations=len(searched["attempts"]) if materialization == "every-attempt" else int(searched["winner"] is not None),
                    serialized_proof_bytes=(len(searched["attempts"]) if materialization == "every-attempt" else int(searched["winner"] is not None)) * common.PROOF_BYTES,
                    evidence_timing=stamp(30),
                    status="target-hit-unverified" if searched["winner"] else "exhausted",
                    winner=copy.deepcopy(searched["winner"]))
                if searched["winner"] is None:
                    continue
                context = searched["winner"]["challenge"]
                if order == 0:
                    add("candidate", sample=sample, search_index=index, challenge=context,
                        proof_hex=searched["proof"].hex(), proof_sha256=common.sha(searched["proof"]))
                offset = common.PROOF_BYTES - 36
                before = int.from_bytes(searched["proof"][offset:offset + 4], "little")
                add("product_mutation", sample=sample, strategy=strategy, search_index=index,
                    source_proof_sha256=common.sha(searched["proof"]),
                    proof_sha256=common.sha(reader.product_last(searched["proof"])), offset=offset,
                    before=before, after=(before + 1) % common.Q, timing=stamp(20))
                for case in reader.CASES:
                    proof = searched["proof"] if case == "legal" else reader.product_last(searched["proof"])
                    for verify_order in range(len(reader.PATHS)):
                        path = reader.PATHS[(sample + order + index + verify_order) % len(reader.PATHS)]
                        add("verifier", sample=sample, strategy=strategy, search_index=index,
                            case=case, invocation_order=verify_order, path=path, challenge=context,
                            proof_sha256=common.sha(proof), outcome="Accepted" if case == "legal" else "Product",
                            timing=stamp(50))
    rows.append(row("end", **{kind + "_count": count for kind, count in counts.items()}, complete=True))
    return rows


class LegalStrategyReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="legal-strategy-reader-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def save(self, rows, name="synthetic.jsonl"):
        path = self.root / name
        with path.open("w") as output:
            for record in rows:
                output.write(json.dumps(record, separators=(",", ":")) + "\n")
        return path

    def first(self, rows, kind, **fields):
        return next(r for r in rows if r["kind"] == kind and all(r.get(k) == v for k, v in fields.items()))

    def mutate_fails(self, kind, field, value, message, **fields):
        rows = copy.deepcopy(self.original)
        self.first(rows, kind, **fields)[field] = value
        with self.assertRaisesRegex(ValueError, message):
            reader.analyze_shard(self.save(rows))

    def test_frozen_contract_has_thirty_shards_and_original_reuse_horizons(self):
        self.assertEqual(len(reader.CLASSES) * len(reader.TARGETS) * len(reader.HORIZONS), 30)
        self.assertEqual(reader.HORIZONS, (1, 8, 64))
        self.assertEqual(reader.SAMPLES, 8)
        self.assertEqual(reader.ATTEMPT_BUDGET, 4096)

    def test_shard_preserves_costs_verifiers_and_nonqualification(self):
        result = reader.analyze_shard(self.save(self.original))
        self.assertEqual(result["record_consistency"], "PASS")
        self.assertEqual(result["observation_coverage"], "one-complete-shard-only")
        self.assertEqual(result["qualification_status"], "HOLD")
        self.assertEqual(result["observed_complete_shards"], 1)
        self.assertEqual(result["required_complete_shards"], 30)
        self.assertEqual(result["selection"], {"class": "zero", "target_index": 0, "reuse_winners": 1})
        self.assertEqual(result["record_counts"]["verifier"], 256)
        self.assertEqual(result["semantic_alerts"], [])
        for key in (*reader.FALSE_FLAGS, "complete_fixed_grid", "w1_transcript_replayed", "native_execution_authenticated", "fastest_adversary_lower_bound"):
            self.assertIs(result[key], False)
        self.assertEqual(result["strategy_costs"][0]["actual_setup_calls"], 8)
        ratio = result["eager_transposed_over_lazy_full_limb_cpu"]
        self.assertEqual(ratio["numerator"], ratio["denominator"])

    def test_finite_rates_preserve_complete_sample_denominators_and_count_hits_once(self):
        for target_index, weight in ((0, 2), (1, 32)):
            source = fixture(target_index=target_index)
            report = reader.analyze_shard(self.save(source))
            self.assertEqual(report["required_target_weight"], weight)
            self.assertIs(report["rate_diagnostic_scope"]["native_chainwork_observed"], False)
            self.assertIsNone(report["rate_diagnostic_scope"]["network_work_share"])
            self.assertIsNone(report["rate_diagnostic_scope"]["confidence_bound"])
            for costs in report["strategy_costs"]:
                samples = costs["per_sample_denominators"]
                self.assertEqual([c["sample"] for c in samples], list(range(reader.SAMPLES)))
                for key in ("actual_setup_calls", "actual_searches", "attempts", "target_hits",
                            "exhausted_searches", "proof_materializations", "serialized_proof_bytes"):
                    self.assertEqual(sum(c[key] for c in samples), costs[key])
                for sample in samples:
                    original = self.first(source, "cohort", strategy=costs["strategy"], sample=sample["sample"])
                    self.assertEqual(sample["setup"], original["setup"])
                    self.assertEqual(sample["inclusive_cohort_total"], original["total"])
                rate = costs["rate_diagnostic"]
                cpu = sum(c["inclusive_cohort_total"]["cpu_ns"] for c in samples)
                self.assertEqual(cpu, costs["inclusive_cohort_total"]["cpu_ns"])
                self.assertEqual(rate["recorded_relation_valid_hits"], reader.SAMPLES)
                self.assertEqual(costs["native_outcome_counts"]["legal"]["Accepted"],
                                 len(reader.PATHS) * rate["recorded_relation_valid_hits"])
                self.assertEqual(rate["attempts_per_cpu_second"],
                                 dict(numerator=costs["attempts"] * 10**9, denominator=cpu))
                self.assertEqual(rate["recorded_relation_valid_hits_per_cpu_second"],
                                 dict(numerator=reader.SAMPLES * 10**9, denominator=cpu))
                self.assertEqual(rate["hypothetical_required_work_total"], reader.SAMPLES * weight)
                self.assertEqual(rate["hypothetical_required_work_per_cpu_second"],
                                 dict(numerator=reader.SAMPLES * weight * 10**9, denominator=cpu))

    def test_rate_is_exact_ratio_of_sums_with_the_slow_sample_retained(self):
        rows = copy.deepcopy(self.original)
        strategy = reader.STRATEGIES[0]
        slow = self.first(rows, "cohort", strategy=strategy, sample=0)
        slow["total"] = stamp(2**53 + 1)
        report = reader.analyze_shard(self.save(rows))
        costs = report["strategy_costs"][0]
        rate = costs["rate_diagnostic"]["recorded_relation_valid_hits_per_cpu_second"]
        expected_cpu = sum(r["total"]["cpu_ns"] for r in rows
                           if r["kind"] == "cohort" and r["strategy"] == strategy)
        self.assertEqual(rate, dict(numerator=reader.SAMPLES * 10**9, denominator=expected_cpu))
        self.assertEqual(costs["per_sample_denominators"][0]["inclusive_cohort_total"], stamp(2**53 + 1))
        sample_rates = [c["rate_diagnostic"]["recorded_relation_valid_hits_per_cpu_second"]
                        for c in costs["per_sample_denominators"]]
        mean_of_rates = sum(Fraction(r["numerator"], r["denominator"]) for r in sample_rates) / reader.SAMPLES
        self.assertNotEqual(Fraction(rate["numerator"], rate["denominator"]), mean_of_rates)

    def test_shared_material_and_separate_evidence_costs_are_not_silently_allocated(self):
        baseline = reader.analyze_shard(self.save(self.original))
        rows = copy.deepcopy(self.original)
        self.first(rows, "campaign")["material_setup"] = stamp(900000)
        for row in rows:
            if row["kind"] == "search":
                row["evidence_timing"] = stamp(800000)
        changed = reader.analyze_shard(self.save(rows))
        self.assertEqual(changed["material_setup"], stamp(900000))
        self.assertEqual(changed["rate_diagnostic_scope"]["denominator"], reader.PRODUCER_SCOPE)
        for before, after in zip(baseline["strategy_costs"], changed["strategy_costs"]):
            self.assertEqual(before["rate_diagnostic"], after["rate_diagnostic"])
            self.assertNotEqual(before["separate_attempt_evidence_total"], after["separate_attempt_evidence_total"])

    def test_factorial_cells_cannot_relabel_arithmetic_or_materialization(self):
        self.assertEqual([reader.factors(s) for s in reader.STRATEGIES], [
            ("transposed", "every-attempt"), ("transposed", "target-hit"),
            ("full-limb", "every-attempt"), ("full-limb", "target-hit")])
        self.mutate_fails("cohort", "arithmetic", "transposed", "factorial cell mismatch", strategy="lazy-full-limb")
        self.mutate_fails("cohort", "materialization", "every-attempt", "factorial cell mismatch", strategy="lazy-transposed")

    def test_missing_misses_and_changed_losing_proof_digest_reject(self):
        rows = copy.deepcopy(self.original)
        searched = next(r for r in rows if r["kind"] == "search" and len(r["attempts"]) > 1)
        searched["attempts"].pop(0)
        with self.assertRaisesRegex(ValueError, "nonconsecutive"):
            reader.analyze_shard(self.save(rows))
        rows = copy.deepcopy(self.original)
        self.first(rows, "search")["attempts"][0]["proof_sha256"] = "00" * 32
        with self.assertRaisesRegex(ValueError, "complete attempt proof"):
            reader.analyze_shard(self.save(rows))

    def test_full_exhaustion_retains_all_cost_and_no_imputed_winner(self):
        rows = fixture(exhausted=(0, 0))
        report = reader.analyze_shard(self.save(rows))
        for costs in report["strategy_costs"]:
            self.assertEqual(costs["exhausted_searches"], 1)
            self.assertEqual(costs["target_hits"], reader.SAMPLES - 1)
            self.assertGreaterEqual(costs["attempts"], reader.ATTEMPT_BUDGET + 1)
            sample = costs["per_sample_denominators"][0]
            self.assertEqual(sample["attempts"], reader.ATTEMPT_BUDGET)
            self.assertEqual(sample["exhausted_searches"], 1)
            self.assertEqual(sample["rate_diagnostic"]["recorded_relation_valid_hits"], 0)
            self.assertEqual(sample["rate_diagnostic"]["hypothetical_required_work_total"], 0)
            self.assertEqual(sample["rate_diagnostic"]["recorded_relation_valid_hits_per_cpu_second"],
                             dict(numerator=0, denominator=sample["inclusive_cohort_total"]["cpu_ns"]))
            rate = costs["rate_diagnostic"]["recorded_relation_valid_hits_per_cpu_second"]
            self.assertEqual(rate, dict(numerator=(reader.SAMPLES - 1) * 10**9,
                                       denominator=costs["inclusive_cohort_total"]["cpu_ns"]))
        searched = self.first(rows, "search", status="exhausted")
        searched["attempts"].pop()
        with self.assertRaisesRegex(ValueError, "exhaustion/misses incomplete"):
            reader.analyze_shard(self.save(rows))

    def test_all_actual_setups_and_nested_costs_are_required(self):
        self.mutate_fails("cohort", "setup_calls", 0, "one actual setup")
        self.mutate_fails("search", "setup_calls", 1, "hidden setup")
        self.mutate_fails("cohort", "total", stamp(1), "exceed inclusive total")
        for value in (None, 0, True):
            self.mutate_fails("cohort", "total", dict(cpu_ns=value, wall_ns=100), "positive measured|bounded nonnegative")

    def test_unexpected_legal_or_negative_verdict_stays_alert_and_null_ratio(self):
        for case, wrong in (("legal", "Transcript"), ("product-last", "Accepted")):
            rows = copy.deepcopy(self.original)
            self.first(rows, "verifier", case=case)["outcome"] = wrong
            report = reader.analyze_shard(self.save(rows))
            self.assertEqual(report["semantic_alerts"][0]["case"], case)
            self.assertIsNone(report["eager_transposed_over_lazy_full_limb_cpu"])
            self.assertTrue(all(r["cpu_per_observed_valid_winner"] is None for r in report["strategy_costs"]))
            # One shard alert prevents selecting an apparently unaffected arm
            # or sample as a valid-work-rate claim. Recorded attempts remain.
            for costs in report["strategy_costs"]:
                rates = [costs["rate_diagnostic"], *(c["rate_diagnostic"] for c in costs["per_sample_denominators"])]
                for rate in rates:
                    self.assertTrue(rate["valid_rates_suppressed_by_shard_alerts"])
                    self.assertIsNotNone(rate["attempts_per_cpu_second"])
                    for key in ("recorded_relation_valid_hits_per_cpu_second",
                                "hypothetical_required_work_total", "hypothetical_required_work_per_cpu_second"):
                        self.assertIsNone(rate[key])

    def test_complete_candidate_and_every_negative_verifier_are_required(self):
        for kind in ("candidate", "verifier"):
            rows = copy.deepcopy(self.original)
            rows.remove(self.first(rows, kind))
            with self.assertRaisesRegex(ValueError, "requires.*candidate|coverage|identity/rotation"):
                reader.analyze_shard(self.save(rows))
        self.mutate_fails("verifier", "proof_sha256", "00" * 32, "identity/rotation", case="product-last")

    def test_product_mutation_is_measured_separately_and_binds_last_canonical_word(self):
        report = reader.analyze_shard(self.save(self.original))
        for costs in report["strategy_costs"]:
            self.assertEqual(costs["separate_product_mutation_total"], stamp(20 * reader.SAMPLES))
        for field, value in (("offset", 4), ("before", 1), ("after", common.Q), ("source_proof_sha256", "00" * 32)):
            self.mutate_fails("product_mutation", field, value, "canonical final|bounded nonnegative")
        rows = copy.deepcopy(self.original)
        rows.remove(self.first(rows, "product_mutation"))
        with self.assertRaisesRegex(ValueError, "measured mutation"):
            reader.analyze_shard(self.save(rows))

    def test_fixed_scope_flags_and_grid_cannot_change(self):
        self.mutate_fails("campaign", "samples", 1, "fixed parameter")
        self.mutate_fails("campaign", "reuse_winners", 4, "fixed actual reuse")
        self.mutate_fails("campaign", "target", "ff" * 32, "fixed target")
        for flag in reader.FALSE_FLAGS:
            self.mutate_fails("campaign", flag, True, "qualification flag")

    def test_framing_duplicate_json_and_truncation_fail(self):
        path = self.save(self.original)
        raw = path.read_bytes()
        path.write_bytes(raw[:-1])
        with self.assertRaisesRegex(ValueError, "bounded complete"):
            reader.analyze_shard(path)
        path.write_bytes(raw.replace(b'"schema":', b'"schema":"duplicate","schema":', 1))
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            reader.analyze_shard(path)

    def test_complete_grid_counts_and_same_horizon_prefix_are_strict(self):
        # Reduce only the in-memory test contract. There is no shortened native
        # selector or reader CLI mode; these records are synthetic test fixtures.
        with patch.multiple(reader, CLASSES=("zero",), TARGETS=(reader.TARGETS[0],), HORIZONS=(1, 8)):
            paths = [self.save(fixture(horizon=h), f"h{h}.jsonl") for h in reader.HORIZONS]
            report = reader.analyze(paths)
            self.assertTrue(report["complete_fixed_grid"])
            self.assertEqual(report["observation_coverage"], "complete-fixed-factorial-grid")
            self.assertEqual(report["qualification_status"], "HOLD")
            self.assertTrue(report["policy_sample_count_satisfied"])
            self.assertFalse(report["work_profile_qualified"])
            self.assertEqual(report["unique_search_streams"], 8 * reader.SAMPLES)
            for shard in report["shards"]:
                self.assertEqual(shard["rate_diagnostic_scope"]["cross_horizon_aggregation"],
                                 "none-shared-search-prefixes-are-not-independent")
            self.assertNotIn("rate_diagnostic", report)
            with self.assertRaisesRegex(ValueError, "complete fixed shard grid"):
                reader.analyze(paths[:1])
            with self.assertRaisesRegex(ValueError, "duplicate/unknown shard"):
                reader.analyze([paths[0], paths[0]])
            changed = self.save(fixture(horizon=8, salt=1), "different-prefix.jsonl")
            with self.assertRaisesRegex(ValueError, "cross-horizon matched search prefix"):
                reader.analyze([paths[0], changed])


    def test_evidence_timing_and_actual_materializations_are_separate_and_required(self):
        result = reader.analyze_shard(self.save(self.original))
        for row in result["strategy_costs"]:
            self.assertEqual(row["separate_attempt_evidence_total"], stamp(30 * reader.SAMPLES))
            self.assertEqual(row["serialized_proof_bytes"], row["proof_materializations"] * common.PROOF_BYTES)
            if row["materialization"] == "target-hit":
                self.assertEqual(row["proof_materializations"], row["target_hits"])
            else:
                self.assertEqual(row["proof_materializations"], row["attempts"])
        self.mutate_fails("search", "proof_materializations", 0, "materialization accounting")
        self.mutate_fails("search", "serialized_proof_bytes", 0, "materialization accounting")
        self.mutate_fails("search", "evidence_timing", stamp(0), "positive measured")
        changed = copy.deepcopy(self.original)
        trial = self.first(changed, "search", strategy="eager-transposed")["attempts"][0]
        trial["proof_materialized"] = False
        with self.assertRaisesRegex(ValueError, "fixed cell"):
            reader.analyze_shard(self.save(changed))

    def test_factorial_effects_keep_both_simple_effects_and_interaction(self):
        rows = copy.deepcopy(self.original)
        extra = dict(zip(reader.STRATEGIES, (20, 10, 12, 4)))
        for row in rows:
            if row["kind"] == "cohort":
                row["total"] = {axis: value + extra[row["strategy"]] for axis, value in row["total"].items()}
        report = reader.analyze_shard(self.save(rows))
        expected = dict(lazy_minus_eager_transposed=-10, lazy_minus_eager_full_limb=-8,
            full_limb_minus_transposed_eager=-8, full_limb_minus_transposed_lazy=-6, interaction=2)
        self.assertEqual(report["factorial_cpu_differences_ns"], {k: v * reader.SAMPLES for k, v in expected.items()})
        for row in report["strategy_costs"]:
            self.assertEqual([c["sample"] for c in row["per_sample_cohort_totals"]], list(range(reader.SAMPLES)))

    def test_v1_remains_two_samples_and_v3_rejects_relabelled_old_schema(self):
        import pon_w1_legal_strategy_reader_v1 as legacy
        self.assertEqual(legacy.SAMPLES, 2)
        self.assertNotEqual(legacy.SCHEMA, reader.SCHEMA)
        old = copy.deepcopy(self.original)
        old[0]["schema"] = legacy.SCHEMA
        with self.assertRaisesRegex(ValueError, "explicit legal-strategy schema"):
            reader.analyze_shard(self.save(old))
        self.mutate_fails("campaign", "samples", 2, "fixed parameter")


if __name__ == "__main__":
    unittest.main()
