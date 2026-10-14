"""SELECT inventory and paired-readout regressions; all examples are fixtures.

No fixture labels certify evidence sufficiency, and no model result is asserted.
The existing saved-model/reader tests run separately in the same required lane.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import five_causal_experiments as c
import reader_content_swap as control
import source_time_evidence as metadata
import select_content_inventory as inv


class Targets(dict):
    def __init__(self, values, forbidden):
        super().__init__(values)
        self.forbidden = set(forbidden)
        self.read = []

    def __getitem__(self, key):
        if key in self.forbidden:
            raise AssertionError("TRAIN/TEST target was accessed")
        self.read.append(key)
        return super().__getitem__(key)


def fixture():
    specs = [("qa0", "A", "select"), ("qa1", "A", "select"),
             ("qb0", "B", "select"), ("qb1", "B", "select"),
             ("qt", "T", "train"), ("qx", "X", "test")]
    queries = [SimpleNamespace(identity=qid, family="fam:" + fam, scope=fam,
                               content="Which fixture value for " + qid + "?") for qid, fam, _ in specs]
    partitions = {qid: p for qid, _, p in specs}
    documents = [SimpleNamespace(identity=fam + str(i), root="root:" + fam, scope=fam,
                  session="session1", observed_at="1 January 2023", content="fixture " + fam + str(i))
                 for fam in ("A", "B", "T", "X") for i in (1, 2, 3)]
    data = {"qa0": ("Alpha", ("A1", "A2")), "qa1": ("Gamma", ("A3",)),
            "qb0": ("Beta", ("B1",)), "qb1": ("Delta", ("B2", "B3")),
            "qt": ("Train", ("T1",)), "qx": ("Test", ("X1",))}
    targets = Targets({k: SimpleNamespace(answer=a, evidence=e, unanswerable=False, unresolved_evidence=())
                       for k, (a, e) in data.items()}, {"qt", "qx"})
    benchmark = SimpleNamespace(questions=queries, documents=documents, targets=targets,
        families={q.family: q.family for q in queries}, partition=lambda q: partitions[q.identity],
        history=lambda q: tuple(d for d in documents if d.scope == q.scope))
    return benchmark


def public_pair(benchmark, qid, support_ids):
    q = next(q for q in benchmark.questions if q.identity == qid)
    docs = {d.identity: d for d in benchmark.history(q)}
    request = {"question": q.content, "options": [], "evidence": [
        {"id": metadata.source_id(key), "modality": "text", "text": docs[key].content,
         "position": i, "asset_sha256": None} for i, key in enumerate(support_ids)]}
    dated, _ = metadata.project(request, benchmark.history(q), metadata.SOURCE_TIME)
    empty = dated | {"evidence": []}
    return [{"question_id": qid, "family": q.family, "split": benchmark.partition(q),
             "condition": condition, "request": r}
            for condition, r in (("support_only", dated), ("no_evidence", empty))]


def cases(benchmark):
    return public_pair(benchmark, "qa0", ("A1", "A2")) + public_pair(benchmark, "qb0", ("B1",))


class InventoryTests(unittest.TestCase):
    def test_original_subset_has_no_donors_but_full_select_pool_does(self):
        b = fixture()
        pool, _ = inv.collect_inventory(b)
        old = control.build_comparisons([r for r in pool if r["question_id"] in {c.digest("qa0"), c.digest("qb0")}])
        self.assertTrue(all(r["status"] == "unavailable_donor" for r in old))
        result = inv.build_plan(b, cases(b))
        self.assertEqual(result["coverage"]["paired_recipients"], 2)
        lookup = {r["question_id"]: r["donor_question_id"] for r in result["comparisons"]}
        self.assertEqual(lookup[c.digest("qa0")], c.digest("qb1"))
        self.assertEqual(lookup[c.digest("qb0")], c.digest("qa1"))

    def test_target_reads_are_select_only(self):
        b = fixture()
        inv.build_plan(b, cases(b) + public_pair(b, "qt", ("T1",)))
        self.assertEqual(set(b.targets.read), {"qa0", "qa1", "qb0", "qb1"})

    def test_all_pool_identities_enter_census_before_eligibility(self):
        b = fixture(); b.targets["qb1"].answer = None
        pool, ledger = inv.collect_inventory(b)
        self.assertEqual(ledger["selected_before_eligibility"], 4)
        self.assertEqual(len(pool), 3)
        row = next(r for r in ledger["rows"] if r["original_question_id"] == "qb1")
        self.assertFalse(row["eligible"])
        self.assertFalse(row["replacement_selected"])

    def test_missing_recipient_answer_retains_all_generation_conditions(self):
        b = fixture(); b.targets["qa0"].answer = None
        result = inv.build_plan(b, cases(b))
        self.assertEqual(len(result["public_cases"]), 6)
        rows = [r for r in result["public_cases"] if r["question_id"] == "qa0"]
        self.assertEqual(sum(r["request"] is None for r in rows), 1)
        self.assertTrue(next(r for r in rows if r["condition"] == "own_sources")["request"]["evidence"])
        self.assertEqual(result["coverage"]["missing_recipient_annotations"], 1)

    def test_no_cross_count_fallback(self):
        b = fixture(); b.targets["qb1"].evidence = ("B2",)
        result = inv.build_plan(b, cases(b))
        row = next(r for r in result["comparisons"] if r["question_id"] == c.digest("qa0"))
        self.assertEqual(row["status"], "unavailable_donor")
        self.assertFalse(inv.readiness(result, []) ["all_reference_bearing_ready"])

    def test_no_train_or_test_donor_fallback(self):
        b = fixture()
        for qid in ("qa1", "qb1"):
            b.targets[qid].answer = None
        result = inv.build_plan(b, cases(b))
        self.assertEqual(result["coverage"]["paired_recipients"], 0)
        self.assertNotIn("qt", b.targets.read)
        self.assertNotIn("qx", b.targets.read)

    def test_same_normalized_answer_does_not_qualify(self):
        b = fixture(); b.targets["qb1"].answer = " ALPHA "
        result = inv.build_plan(b, cases(b))
        self.assertEqual(next(x for x in result["comparisons"] if x["question_id"] == c.digest("qa0"))["status"], "unavailable_donor")

    def test_unresolved_support_not_repaired(self):
        b = fixture(); b.targets["qb1"].unresolved_evidence = ("missing",)
        pool, ledger = inv.collect_inventory(b)
        self.assertEqual(len(pool), 3)
        self.assertIn("missing_unresolved_or_out_of_bound_support", ledger["reasons"])

    def test_excess_source_count_not_truncated(self):
        b = fixture(); b.targets["qb1"].evidence = ("B1", "B2", "B3", "B4")
        _, ledger = inv.collect_inventory(b)
        row = next(r for r in ledger["rows"] if r["original_question_id"] == "qb1")
        self.assertEqual(row["support_count"], 4)
        self.assertFalse(row["eligible"])

    def test_donor_keeps_own_session_date_and_verbatim_body(self):
        b = fixture(); result = inv.build_plan(b, cases(b))
        row = next(r for r in result["comparisons"] if r["question_id"] == c.digest("qa0"))
        evidence = row["requests"]["donor_sources"]["evidence"]
        self.assertEqual([x["id"] for x in evidence], ["S1", "S2"])
        self.assertTrue(evidence[0]["text"].endswith("fixture B2"))
        self.assertIn('"1 January 2023"', evidence[0]["text"])
        self.assertEqual(row["requests"]["donor_sources"]["question"], row["requests"]["own_sources"]["question"])

    def test_public_input_contains_no_answers_or_pool_metadata(self):
        result = inv.build_plan(fixture(), cases(fixture()))
        for row in result["public_cases"]:
            self.assertEqual(set(row), {"question_id", "family", "split", "condition", "request"})
            if row["request"] is not None:
                c.validate_public(row["request"])
                self.assertEqual(set(row["request"]), {"question", "options", "evidence"})
                self.assertNotIn("answer_body", row["request"])

    def test_pool_and_pair_order_are_deterministic(self):
        b = fixture(); prior = cases(b)
        first = inv.build_plan(b, prior)
        b.questions = list(reversed(b.questions))
        second = inv.build_plan(b, list(reversed(prior)))
        self.assertEqual(first["pool"], second["pool"])
        self.assertEqual(first["comparisons"], second["comparisons"])
        self.assertEqual(first["public_cases"], second["public_cases"])

    def test_saved_inputs_are_not_modified(self):
        b = fixture(); prior = cases(b); original = deepcopy(prior)
        inv.build_plan(b, prior)
        self.assertEqual(prior, original)

    def test_changed_recipient_source_cannot_become_new_old_input(self):
        b = fixture(); prior = cases(b)
        prior[0]["request"]["evidence"][0]["text"] += " altered"
        with self.assertRaises(c.Invalid): inv.build_plan(b, prior)

    def test_duplicate_generation_condition_rejected(self):
        b = fixture(); prior = cases(b); prior.append(deepcopy(prior[0]))
        with self.assertRaises(c.Invalid): inv.build_plan(b, prior)

    def test_missing_empty_condition_rejected(self):
        b = fixture(); prior = cases(b)[:-1]
        with self.assertRaises(c.Invalid): inv.build_plan(b, prior)

    def test_test_generation_cannot_enter_new_study(self):
        b = fixture(); prior = cases(b) + public_pair(b, "qx", ("X1",))
        with self.assertRaises(c.Invalid): inv.build_plan(b, prior)

    def test_source_roots_cannot_cross_development_partitions(self):
        b = fixture(); b.documents[-1].root = "root:A"
        with self.assertRaisesRegex(c.Invalid, "root crosses"): inv.build_plan(b, cases(b))

    def test_source_scopes_cannot_cross_partitions(self):
        b = fixture(); b.questions[-1].scope = "A"
        with self.assertRaisesRegex(c.Invalid, "scope crosses"): inv.collect_inventory(b)

    def test_duplicate_source_identity_is_rejected(self):
        b = fixture(); b.documents.append(deepcopy(b.documents[0]))
        with self.assertRaises(c.Invalid): inv.collect_inventory(b)

    def test_missing_date_is_ineligible_not_invented(self):
        b = fixture()
        next(d for d in b.documents if d.identity == "B2").observed_at = ""
        _, ledger = inv.collect_inventory(b)
        row = next(r for r in ledger["rows"] if r["original_question_id"] == "qb1")
        self.assertFalse(row["eligible"])
        self.assertTrue(row["reason"].startswith("source_projection_invalid:"))

    def test_missing_compile_does_not_trigger_another_donor_search(self):
        b = fixture(); result = inv.build_plan(b, cases(b)); before = c.digest(result)
        check = inv.readiness(result, [c.digest("qa0")])
        self.assertFalse(check["all_reference_bearing_ready"])
        self.assertEqual(c.digest(result), before)

    def test_unknown_compiled_recipient_rejected(self):
        b = fixture(); result = inv.build_plan(b, cases(b))
        with self.assertRaises(c.Invalid): inv.readiness(result, [c.digest("unknown")])

    def test_complete_reference_coverage_is_not_semantic_qualification(self):
        b = fixture(); result = inv.build_plan(b, cases(b))
        check = inv.readiness(result, [r["question_id"] for r in result["comparisons"]])
        self.assertTrue(check["all_reference_bearing_ready"])
        self.assertFalse(check["reader_adequacy_established"])


class ReadoutTests(unittest.TestCase):
    def rows(self, values=(2.0, 4.0)):
        return [{"question_id": "q" + str(i), "family": "f" + str(i), "donor_question_id": "d" + str(i),
                 "status": "succeeded", "audit": {"difference_in_differences": value}}
                for i, value in enumerate(values)]

    def test_same_recipient_deltas(self):
        result = inv.paired_readout({"frozen_reader": self.rows(), "aligned_8": self.rows((3.0, 6.0))})[0]
        self.assertEqual(result["jointly_scored"], 2)
        self.assertEqual(result["mean_delta"], 1.5)
        self.assertEqual(result["family_macro_delta"], 1.5)
        self.assertIsNone(result["confidence_interval"])

    def test_unavailable_is_not_zero_effect(self):
        base = self.rows(); other = self.rows()
        for row in (base[0], other[0]):
            row.update(status="unavailable_recipient_annotation", audit=None)
        result = inv.paired_readout({"frozen_reader": base, "aligned_8": other})[0]
        self.assertEqual(result["planned_recipients"], 2)
        self.assertEqual(result["jointly_scored"], 1)
        self.assertEqual(result["missing_or_failed_ids"], ["q0"])

    def test_no_scored_pair_returns_null(self):
        rows = self.rows()
        for row in rows: row.update(status="failed", audit=None)
        result = inv.paired_readout({"frozen_reader": rows, "aligned_8": deepcopy(rows)})[0]
        self.assertIsNone(result["mean_delta"])
        self.assertIsNone(result["family_macro_delta"])

    def test_different_donor_cannot_be_paired(self):
        rows = self.rows(); rows[0]["donor_question_id"] = "other"
        with self.assertRaises(c.Invalid): inv.paired_readout({"frozen_reader": self.rows(), "aligned_8": rows})

    def test_different_denominators_rejected(self):
        with self.assertRaises(c.Invalid): inv.paired_readout({"frozen_reader": self.rows(), "aligned_8": self.rows()[:1]})

    def test_nonfinite_effect_rejected(self):
        with self.assertRaises(c.Invalid): inv.paired_readout({"frozen_reader": self.rows(), "aligned_8": self.rows((float("nan"), 1.0))})

    def test_direct_aligned_shuffled_comparison(self):
        result = inv.paired_readout({"shuffled_8": self.rows(), "aligned_8": self.rows((3.0, 1.0))}, "shuffled_8")[0]
        self.assertEqual(result["positive_deltas"], 1)
        self.assertEqual(result["negative_deltas"], 1)
        self.assertFalse(result["independent_confirmation"])


if __name__ == "__main__":
    unittest.main()
