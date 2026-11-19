"""Research-only exact Fraction and adversarial action-gap tests.

The local independent protocol fixture is *not* the original E12 code. The
hosted workflow additionally executes the exact inherited E12 independent
reviewer in a distinct job, with the original registered source.
"""
import json
import sys
import tempfile
import types
import unittest
from dataclasses import asdict, replace
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import patch

import e12_action_gap as gap
import e12_action_gap_study as study


# Independent path-dictionary expression of the same registered finite law;
# this does not call the main tree_map or any original E12 code.
def reference_map(law, guess):
    p = law.parameters()
    keys = [tuple((1 if (k >> (d - 1 - j)) & 1 else -1)
                  for j in range(d)) for d in range(law.depth) for k in range(1 << d)]
    states = {(): p["x0"]}
    for key, y in zip(keys, guess):
        mid = states[key] + p["a"] * p["h"] * (
            Q(y.numerator * y.denominator, y.numerator**2 + y.denominator**2))
        states[key + (-1,)] = mid - p["sigma"] * p["s"]
        states[key + (1,)] = mid + p["sigma"] * p["s"]
    utility = {key: p["g"] * x / (1 + x*x) for key, x in states.items()
               if len(key) == law.depth}
    for key in reversed(keys):
        xl = key + (-1,)
        xr = key + (1,)
        x = states[key]
        utility[key] = ((utility[xl] + utility[xr]) / 2 +
                        p["beta"] * p["h"] * x/(1+x*x)) / (1+p["lam"]*p["h"])
    return tuple(utility[k] for k in keys)


class TestLocalGlobalGap(unittest.TestCase):
    def test_registered_tree_vs_independent_dictionary(self):
        for depth in (1, 2, 3):
            for a in ("0", "1/3"):
                law = gap.Law(depth, "71/128", a)
                n = (1 << depth) - 1
                for v in (Q(0), Q(1, 8), Q(-1, 16)):
                    x = (v,) * n
                    self.assertEqual(gap.tree_map(law, x), reference_map(law, x))

    def test_q16_interval_is_outward(self):
        for x in (Q(1, 7), Q(1, 3), Q(0), Q(1, 200000)):
            self.assertGreaterEqual(gap.round_up_nonnegative(x), x)
            self.assertLess(gap.round_up_nonnegative(x)-x, Q(1, 1 << gap.BITS))
        self.assertEqual(gap.round_even(Q(-1, 2)), Q(-1, 2))
        self.assertEqual(gap.round_even(Q(1, 2**17)), Q(0))
        with self.assertRaises(ValueError):
            gap.round_up_nonnegative(Q(-1))

    def test_certified_action_not_same_as_cheap_one_map(self):
        acts = gap.make_actions("37/128", 1)
        decision = gap.evaluate_actions(acts)
        self.assertEqual(decision.selected, "coupled")
        self.assertEqual(decision.cheap_one_map, "direct")
        self.assertEqual(decision.authority, "DENY_ALL")
        self.assertFalse(decision.natural_task_gain_proven)
        self.assertEqual(decision.forward_cell_calls, decision.map_evals)
        for a in acts:
            last = decision.snapshots[a.name][-1]
            self.assertLessEqual(gap.rational(last.lower), gap.rational(last.upper))

    def test_no_oracle_or_external_import_in_proposer(self):
        with patch.object(sys.modules[__name__].gap, "tree_map", wraps=gap.tree_map) as called:
            decision = gap.evaluate_actions(gap.make_actions("79/128", 3))
            self.assertEqual(called.call_count, decision.map_evals)
            self.assertGreater(decision.map_evals, 2)

    def test_budget_ties_and_nonpromotion(self):
        a = gap.make_actions("79/128", 3)
        d = gap.evaluate_actions(a, max_maps=2)
        self.assertEqual(d.reason, "HOLD_UNRESOLVED")
        self.assertIsNone(d.selected)
        self.assertFalse(d.production_accepted)
        with self.assertRaises(ValueError):
            gap.evaluate_actions(a, max_maps=1)

    def test_bad_laws_and_invalid_policy(self):
        for a in ("01/3", "-1/3", "1/0", "2", "1/9999999999999999999999999999999999999"):
            with self.assertRaises((ValueError, ZeroDivisionError)):
                gap.Law(3, "1", a).parameters()
        good = gap.make_actions("1", 1)
        with self.assertRaises(ValueError):
            gap.evaluate_actions((good[1], good[0]))
        with self.assertRaises(ValueError):
            gap.evaluate_actions((good[0], replace(good[1], penalty="0")))
        with self.assertRaises(ValueError):
            gap.evaluate_actions(good, initial={"direct": (Q(0),)})
        with self.assertRaises(ValueError):
            gap.tree_map(good[0].law, (Q(0), Q(0)))

    def test_outcome_bound_contains_exact_fixed_point(self):
        for depth in (1, 2, 3):
            for a in gap.make_actions("117/128", depth):
                n = (1 << depth) - 1
                curr = (Q(0),) * n
                for _ in range(12):
                    mapped = reference_map(a.law, curr)
                    M = a.law.parameters()["M"]
                    curr = tuple(max(-M, min(M, gap.round_even(z))) for z in mapped)
                snap = gap.snapshot(a, curr)
                precise = reference_map(a.law, curr)[0] - a.check()
                # Canonical full-tree residual is a rigorous bound around guess.
                self.assertLessEqual(gap.rational(snap.lower), precise)
                self.assertGreaterEqual(gap.rational(snap.upper), precise)


class TestSealedStudy(unittest.TestCase):
    def test_real_blind_proposer_zero_and_source_binding(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sealed.json"
            digest = study.propose(str(p))
            data = study.read_locked(str(p), digest)
            self.assertEqual(len(data["cases"]), 18)
            self.assertFalse(data["natural_reasoning_gain_verified"])
            self.assertTrue(all(c["outcome"]["authority"] == "DENY_ALL"
                                for c in data["cases"]))
            with self.assertRaises(FileExistsError):
                study.propose(str(p))
            with self.assertRaises(ValueError):
                study.read_locked(str(p), "0" * 64)
            data["cases"][0]["outcome"]["map_evals"] = 0
            p.write_bytes(study.canonical(data))
            self.assertEqual(study.read_locked(str(p), study.sha256(p.read_bytes()).hexdigest()), data)

    def test_strict_tamper_and_unknowns(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            digest = study.write_once(str(p), {"a": 1})
            self.assertEqual(study.read_locked(str(p), digest), {"a": 1})
            p.unlink()
            p.write_bytes(b'{"a":1,"a":2}\n')
            with self.assertRaises(ValueError):
                study.read_locked(str(p), study.sha256(p.read_bytes()).hexdigest())
            p.unlink()
            p.symlink_to(Path(d) / "target")
            with self.assertRaises(ValueError):
                study.write_once(str(p), {"x": 1})

    def test_wrong_source_proposal_and_training_identity(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                study.propose(str(Path(d) / "unused"), training="model", training_sha="")
            with self.assertRaises(ValueError):
                study.review(str(Path(d) / "missing"), "0" * 64,
                             str(Path(d) / "out"))


if __name__ == "__main__":
    unittest.main()


class TestLocalCompatibilityReviewer(unittest.TestCase):
    """Synthetic compatibility modules exercise the review protocol LOCALLY.

    The exact original E12 oracle is only executed by the read-only hosted CI.
    """

    def test_original_style_protocol_replay_and_reject_forgery(self):
        class CompatLaw:
            def __init__(self, *, depth, x0, a):
                self.law = gap.Law(depth, x0, a)
            def values(self):
                return self.law.parameters()

        def operator(law, ys):
            return reference_map(law.law, ys)

        def original_round(value, bits):
            z = value * (1 << bits)
            floor = z.numerator // z.denominator
            frac = z - floor
            if frac > Q(1, 2) or (frac == Q(1, 2) and floor % 2):
                floor += 1
            return Q(floor, 1 << bits)

        def solve(law):
            n = (1 << law.law.depth) - 1
            state = (Q(0),) * n
            for _ in range(24):
                mapped = operator(law, state)
                error = max(abs(a-b) for a, b in zip(state, mapped)) / (
                    1-law.values()["q"])
                if error <= Q(1, 10000):
                    return types.SimpleNamespace(
                        trace=types.SimpleNamespace(states=(types.SimpleNamespace(y=str(state[0])),)),
                        fixed_point_error_bound=str(error))
                state = tuple(original_round(v, 16) for v in mapped)
            raise ValueError("compat reference exhausted")

        e12 = types.ModuleType("e12_nonlinear_cert")
        e12.Law = CompatLaw
        e12.operator = operator
        e12.solve = solve
        audit = types.ModuleType("e12_independent_audit")
        audit.audit = lambda law, s: types.SimpleNamespace(certified=True)
        audit.exact = lambda v: Q(v)
        audit.round_even = original_round
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, {
            "e12_nonlinear_cert": e12, "e12_independent_audit": audit,
        }):
            p = Path(d) / "proposal.json"
            digest = study.propose(str(p))
            out = Path(d) / "independently-reviewed.json"
            score_sha = study.review(str(p), digest, str(out))
            reviewed = study.read_locked(str(out), score_sha)
            self.assertEqual(reviewed["cases"], 18)
            self.assertEqual(reviewed["certified"], 18)
            self.assertEqual(reviewed["matches_reference"], 18)
            self.assertEqual(reviewed["cheap_disagreements"], 8)
            self.assertFalse(reviewed["natural_reasoning_gain_verified"])
            # An attacker who can recompute the outer SHA still cannot forge
            # a smaller numerical interval or fake an E12-action certificate.
            data = study.read_locked(str(p), digest)
            data["cases"][0]["outcome"]["snapshots"]["direct"][0]["error_bound"] = "0"
            other = Path(d) / "forged.json"
            forged_sha = study.write_once(str(other), data)
            with self.assertRaises(ValueError):
                study.review(str(other), forged_sha, str(Path(d) / "should_not_exist.json"))
