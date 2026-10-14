"""Hermetic soundness, exact budget, and full candidate census; no task efficacy claim."""

from fractions import Fraction
from itertools import combinations_with_replacement
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_canonical_generation import canonical_successors
from system2_canonical_trial import BUDGETS, evaluate, run, solve_one, tasks
from system2_resumable_search import SearchSession
from system2_verified_search import digest, state_key, successors, verify


def counts():
    return dict(pair_checks=0, pair_skips=0, symmetry_skips=0, emitted=0)


class GenerationTests(unittest.TestCase):
    def test_all_local_numeric_successors_preserved_with_duplicates(self):
        for size in (2, 3, 4):
            for values in combinations_with_replacement(range(4), size):
                terms = tuple(
                    (Fraction(v), ("n" + str(i),)) for i, v in enumerate(values)
                )
                before = {state_key(c) for c in successors(terms)}
                after = {state_key(c) for c in canonical_successors(terms, counts())}
                self.assertEqual(before, after)

    def test_counters_are_real_and_symmetric_duplicates_not_generated(self):
        terms = tuple((Fraction(2), ("n" + str(i),)) for i in range(4))
        c = counts()
        children = list(canonical_successors(terms, c))
        self.assertEqual(c["pair_checks"], 6)
        self.assertEqual(c["pair_skips"], 5)
        self.assertEqual(c["symmetry_skips"], 2)
        self.assertEqual(c["emitted"], len(children))
        self.assertEqual(len(children), 4)

    def test_generator_refuses_missing_counters(self):
        with self.assertRaises(ValueError):
            list(canonical_successors(((Fraction(2), ()), (Fraction(2), ())), {}))

    def test_default_search_equals_unchanged_existing_reference(self):
        for n in ((1, 2, 3, 4), (1, 3, 4, 6), (4, 4, 4, 4), (6, 6, 7, 9)):
            for budget in BUDGETS:
                self.assertEqual(
                    solve_one(n, budget, "reference")["costs"]["generated_successors"],
                    SearchSession(n, 24, "heuristic_search").advance(budget)["costs"][
                        "generated_successors"
                    ],
                )

    def test_resumption_retains_same_canonical_proof(self):
        for n in ((1, 2, 3, 4), (1, 3, 4, 6), (4, 4, 4, 4), (6, 6, 7, 9)):
            for budget in BUDGETS:
                r = solve_one(n, budget, "canonical_pair")
                if r["found"]:
                    self.assertTrue(verify(n, 24, r["proof"]))
                self.assertLessEqual(r["costs"]["generated_successors"], budget)
                self.assertEqual(
                    r["generation_filter"]["emitted"],
                    r["costs"]["generated_successors"],
                )

    def test_unknown_generator_profiles_fail_closed(self):
        for profile in ("canonical", "none", "", None, 0):
            with self.assertRaises(ValueError):
                SearchSession(
                    (1, 2, 3, 4), 24, "heuristic_search", generation_profile=profile
                )

    def test_fixed_new_cohort_disjoint_without_oracle(self):
        groups = tasks()
        self.assertEqual(list(map(len, groups.values())), [204, 48])
        self.assertFalse(set(groups["previous_204"]) & set(groups["next_48_tasks"]))
        all_ids = [digest(n) for x in groups.values() for n in x]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_real_runner_seals_and_keeps_full_counts(self):
        small = {"previous_204": [(1, 2, 3, 4)], "next_48_tasks": [(1, 1, 1, 1)]}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("system2_canonical_trial.tasks", return_value=small),
        ):
            result = run(Path(tmp) / "run", "a" * 40)
            self.assertEqual(
                (result["planned"], result["recorded"], result["failed"]), (8, 8, 0)
            )
            data = (Path(tmp) / "run" / "prediction-seal.json").read_text()
            self.assertIn('"posthoc_analysis_started": false', data)
            rows = [
                json.loads(x)
                for x in (Path(tmp) / "run" / "predictions.jsonl")
                .read_text()
                .splitlines()
            ]
            with self.assertRaises(ValueError):
                evaluate(rows[:-1], small)
            with self.assertRaises(ValueError):
                evaluate(rows + rows[:1], small)
            rows[0]["status"] = "failed"
            rows[0].pop("found", None)
            summary = evaluate(rows, small)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["recorded"], 8)

    def test_failed_full_trial_is_retained_not_replaced(self):
        small = {"previous_204": [(1, 2, 3, 4)], "next_48_tasks": [(1, 1, 1, 1)]}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("system2_canonical_trial.tasks", return_value=small),
            patch(
                "system2_canonical_trial.solve_one",
                side_effect=RuntimeError("injected"),
            ),
        ):
            out = Path(tmp) / "failed"
            with self.assertRaises(RuntimeError):
                run(out, "b" * 40)
            rows = (out / "predictions.jsonl").read_text().splitlines()
            self.assertEqual(len(rows), 8)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["failed"], 8)

    def test_fractional_negative_states_and_complete_reachability(self):
        # Exact Fraction checks also cover values produced inside a search tree.
        values = (
            Fraction(-2),
            Fraction(-1),
            Fraction(0),
            Fraction(1, 2),
            Fraction(1),
            Fraction(3, 2),
            Fraction(2),
        )
        examined = reference_generated = canonical_generated = 0
        for size in (2, 3, 4):
            for numbers in combinations_with_replacement(values, size):
                terms = tuple((v, ("n" + str(i),)) for i, v in enumerate(numbers))
                old = list(successors(terms))
                stats = counts()
                new = list(canonical_successors(terms, stats))
                self.assertEqual(
                    {state_key(c) for c in old}, {state_key(c) for c in new}
                )
                self.assertEqual(stats["emitted"], len(new))
                for child in new:
                    leaves = sorted(
                        token
                        for _, proof in child
                        for token in proof
                        if isinstance(token, str) and token.startswith("n")
                    )
                    self.assertEqual(leaves, ["n" + str(i) for i in range(size)])
                examined += 1
                reference_generated += len(old)
                canonical_generated += len(new)
        self.assertEqual(examined, 322)
        self.assertLess(canonical_generated, reference_generated * 0.7)

        # A full legal completion is preserved by induction on state size;
        # check selected mixed-sign/noninteger trajectories directly as well.
        def reaches(numbers, generator):
            memo = {}

            def walk(state):
                if state in memo:
                    return memo[state]
                if len(state) == 1:
                    return state[0] == 24
                terms = tuple((v, ("n" + str(i),)) for i, v in enumerate(state))
                children = (
                    successors(terms)
                    if generator == "reference"
                    else canonical_successors(terms, counts())
                )
                result = any(walk(state_key(child)) for child in children)
                memo[state] = result
                return result

            return walk(tuple(sorted(Fraction(v) for v in numbers)))

        examples = (
            (1, 3, 4, 6),
            (1, 2, 3, 4),
            (2, 2, 2, 2),
            (0, 1, 2, 3),
            (Fraction(1, 2), Fraction(3, 2), 2, 3),
            (-2, -1, 0, 2),
        )
        for numbers in examples:
            self.assertEqual(
                reaches(numbers, "reference"), reaches(numbers, "canonical_pair")
            )


if __name__ == "__main__":
    unittest.main()
