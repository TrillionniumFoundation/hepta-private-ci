"""Trusted exact-Fraction goal prefilter: full proof is still independent."""

from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_resumable_search import SearchSession
from system2_terminal_prefilter_trial import assert_pair, run
from system2_canonical_cpu import BUDGETS, PROFILES
from system2_verified_search import digest, state_key, successors, verify


def fixture(directory, groups, commit):
    directory.mkdir()
    records = []
    for group, tasks in groups.items():
        for n, budget, generation in itertools.product(tasks, BUDGETS, PROFILES):
            result = SearchSession(
                n, 24, "heuristic_search", generation_profile=generation
            ).advance(budget)
            records.append(
                dict(
                    group=group,
                    query_id=digest(n),
                    numbers=list(n),
                    budget=budget,
                    profile=generation,
                    found=result["found"],
                    proof=result["proof"],
                    costs=result["costs"],
                    generation_filter=result["generation_filter"],
                    status="completed",
                )
            )
    raw = "".join(json.dumps(x, sort_keys=True) + "\n" for x in records).encode()
    (directory / "predictions.jsonl").write_bytes(raw)
    (directory / "prediction-seal.json").write_text(
        json.dumps(
            dict(
                sha256=hashlib.sha256(raw).hexdigest(),
                rows=len(records),
                posthoc_analysis_started=False,
            )
        )
    )
    (directory / "plan.json").write_text(json.dumps(dict(source_commit=commit)))


class ExactTerminalTests(unittest.TestCase):
    def test_explicit_false_and_default_agree(self):
        n = (1, 3, 4, 6)
        old = SearchSession(n, 24, "heuristic_search").advance(1024)
        control = SearchSession(
            n, 24, "heuristic_search", terminal_prefilter=False
        ).advance(1024)
        for key in (
            "found",
            "proof",
            "costs",
            "generation_filter",
            "verification_skips",
        ):
            self.assertEqual(old[key], control[key])
        for bad in (None, 0, 1, "true"):
            with self.assertRaises(ValueError):
                SearchSession(n, 24, "heuristic_search", terminal_prefilter=bad)

    def test_exact_proof_work_and_generation_unchanged_for_both_generators(self):
        ns = (
            (1, 2, 3, 4),
            (1, 3, 4, 6),
            (4, 4, 4, 4),
            (2, 6, 8, 9),
            (1, 1, 1, 1),
            (6, 6, 7, 9),
            (3, 5, 6, 6),
        )
        for n in ns:
            for budget, generation in itertools.product(BUDGETS, PROFILES):
                old = SearchSession(
                    n, 24, "heuristic_search", generation_profile=generation
                ).advance(budget)
                new = SearchSession(
                    n,
                    24,
                    "heuristic_search",
                    generation_profile=generation,
                    terminal_prefilter=True,
                ).advance(budget)
                assert_pair(old, new, old)
                self.assertEqual(old["proof"], new["proof"])
                self.assertEqual(
                    old["costs"]["generated_successors"],
                    new["costs"]["generated_successors"],
                )
                if new["found"]:
                    self.assertTrue(verify(n, 24, new["proof"]))

    def test_partial_budget_resume_keeps_same_exact_proof(self):
        for generation in PROFILES:
            full = SearchSession(
                (1, 3, 4, 6),
                24,
                "heuristic_search",
                generation_profile=generation,
                terminal_prefilter=True,
            ).advance(1024)
            session = SearchSession(
                (1, 3, 4, 6),
                24,
                "heuristic_search",
                generation_profile=generation,
                terminal_prefilter=True,
            )
            earlier = session.advance(256)
            later = session.advance(1024)
            self.assertEqual(full["costs"], later["costs"])
            self.assertEqual(full["proof"], later["proof"])
            self.assertEqual(full["verification_skips"], later["verification_skips"])
            self.assertLessEqual(
                earlier["verification_skips"], later["verification_skips"]
            )

    def test_goal_value_does_not_bypass_independent_verifier(self):
        import system2_resumable_search as mod

        with patch.object(
            mod, "successors", side_effect=lambda _: iter([((Fraction(24), ("n0",)),)])
        ):
            r = SearchSession(
                (1, 2, 3, 4), 24, "heuristic_search", terminal_prefilter=True
            ).advance(32)
        self.assertFalse(r["found"])
        self.assertEqual(r["costs"]["verifier_calls"], 1)

    def test_all_reached_numeric_leaves_match_their_postfix_proofs(self):
        for n in itertools.combinations_with_replacement((1, 2, 3, 4), 4):
            initial = tuple((Fraction(v), ("n" + str(i),)) for i, v in enumerate(n))
            queue = [initial]
            seen = set()
            while queue:
                state = queue.pop()
                key = state_key(state)
                if key in seen:
                    continue
                seen.add(key)
                if len(state) > 1:
                    queue.extend(successors(state))
                else:
                    value, proof = state[0]
                    stack = []
                    for token in proof:
                        if token.startswith("n"):
                            stack.append(Fraction(n[int(token[1:])]))
                        else:
                            b, a = stack.pop(), stack.pop()
                            if token == "+":
                                stack.append(a + b)
                            elif token == "-":
                                stack.append(a - b)
                            elif token == "*":
                                stack.append(a * b)
                            else:
                                stack.append(a / b)
                    self.assertEqual(stack, [value])
                    if value == 24:
                        self.assertTrue(verify(n, 24, proof))

    def test_sealed_small_full_runner_and_failure_accounting(self):
        groups = dict(previous_204=[(1, 2, 3, 4)], next_48_tasks=[(4, 4, 4, 4)])
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root / "sealed", groups, "a" * 40)
            with patch("system2_terminal_prefilter_trial.cohorts", return_value=groups):
                ok = run(
                    root / "sealed", root / "out", source_commit="a" * 40, repeats=2
                )
                self.assertEqual(
                    (ok["planned"], ok["recorded"], ok["failed"]), (32, 32, 0)
                )
                self.assertTrue((root / "out" / "prediction-seal.json").exists())
                with self.assertRaises(ValueError):
                    run(
                        root / "sealed",
                        root / "wrong",
                        source_commit="b" * 40,
                        repeats=1,
                    )
                with patch(
                    "system2_terminal_prefilter_trial.timed",
                    side_effect=RuntimeError("injected"),
                ):
                    with self.assertRaises(RuntimeError):
                        run(
                            root / "sealed",
                            root / "failed",
                            source_commit="a" * 40,
                            repeats=1,
                        )
                failure = json.loads((root / "failed" / "run-failure.json").read_text())
                self.assertFalse(failure["complete"])
                self.assertTrue(failure["missing_work_not_imputed"])
                self.assertEqual(
                    len(
                        (root / "failed" / "predictions.jsonl").read_text().splitlines()
                    ),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
