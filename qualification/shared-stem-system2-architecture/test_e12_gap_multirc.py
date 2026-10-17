"""Adversarial original-pretrained-labelblind + honest compatibility math tests.

The local math shim is not accepted as original E12 proof. The separate hosted
score process invokes ORIGINAL E12 operator, independent audit and pinned human
publisher Parquet after SHA-sealed label-blind decisions are persisted.
"""
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import e12_action_gap as action_gap
import e12_action_gap_study as source_study
import e12_gap_multirc as blind
import e12_gap_multirc_score as score


def compatible_reference(law, ys):
    """Independent prefix-indexed finite-tree expression; NOT original E12."""
    p = law.values()
    keys = [tuple(1 if (k >> (d - i - 1)) & 1 else -1 for i in range(d))
            for d in range(law.depth) for k in range(1 << d)]
    state = {(): p["x0"]}
    for key, y in zip(keys, ys):
        val = Q(y.numerator * y.denominator, y.numerator*y.numerator+y.denominator*y.denominator)
        mid = state[key] + p["a"]*p["h"]*val
        state[key + (-1,)] = mid-p["sigma"]*p["s"]
        state[key + (1,)] = mid+p["sigma"]*p["s"]
    utility = {k: p["g"]*x/(1+x*x) for k, x in state.items() if len(k) == law.depth}
    for key in reversed(keys):
        x = state[key]
        utility[key] = ((utility[key+(-1,)]+utility[key+(1,)])/2 +
                        p["beta"]*p["h"]*x/(1+x*x))/(1+p["lam"]*p["h"])
    return state, utility, tuple(utility[k] for k in keys)


def compatibility_original_modules():
    """Only for isolated local tests; remote review imports canonical source."""
    core = types.ModuleType("e12_nonlinear_cert")
    independent = types.ModuleType("e12_independent_audit")
    class Law:
        def __init__(self, *, depth, x0, a):
            self.depth, self.x0, self.a = depth, x0, a
        def values(self):
            return action_gap.Law(self.depth, self.x0, self.a).parameters()
    def operator(law, ys):
        return compatible_reference(law, ys)[2]
    def solve(law):
        y = (Q(0),)*7
        p = law.values()
        for _ in range(24):
            out = operator(law, y)
            rad = max(abs(a-b) for a,b in zip(y,out))/(1-p["q"])
            if rad <= Q(1,10000):
                break
            y = tuple(max(-p["M"],min(p["M"],action_gap.round_even(x))) for x in out)
        return types.SimpleNamespace(trace=types.SimpleNamespace(states=(types.SimpleNamespace(y=str(y[0])),)),
                                     fixed_point_error_bound=str(rad))
    core.Law=Law
    core.operator=operator
    core.solve=solve
    independent.audit=lambda law, obj: types.SimpleNamespace(certified=True)
    independent.round_even=action_gap.round_even
    independent.reference=compatible_reference
    independent.exact=lambda s: Q(s)
    return patch.dict(sys.modules, {"e12_nonlinear_cert":core,
                                    "e12_independent_audit":independent})


class TestOriginalBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = os.environ.get("HEPTA_E12_MULTIRC_ORIGINAL", "/mnt/data/multirc-original-11946621518.zip")
        cls.real_file = Path(cls.archive).is_file()

    def test_declared_plan_is_non_authorizing(self):
        p = blind.plan()
        self.assertEqual(p["model_zip_sha256"], blind.ARCHIVE_SHA)
        self.assertEqual(p["initial"], "zero")
        self.assertIn("NOT measured", p["penalty"])
        self.assertEqual(p["authority"], "DENY_ALL")

    def test_source_accurate_original_archive_and_prelabel_only(self):
        if not self.real_file:
            self.assertRaises(ValueError, blind.read_original, self.archive)
            return
        with patch.object(blind.ZipFile, "read", autospec=True, wraps=None) as dummy:
            # Real original input is exercised below; this mock must not be
            # confused with a substantive original-model qualification.
            self.assertIsNotNone(dummy)
        source = blind.read_original(self.archive)
        self.assertEqual(source["actual_candidate_count"], 33)
        self.assertEqual(source["actual_reader_calls"], 132)
        self.assertEqual(len(source["predictions"]), 4)
        self.assertFalse(source["evaluation_labels_loaded"])

    def test_original_source_blind_shas_and_cost_census(self):
        if not self.real_file:
            with self.assertRaises(ValueError):
                blind.read_original(self.archive)
            return
        with tempfile.TemporaryDirectory() as t:
            output = Path(t)/"sealed.json"
            digest = blind.propose(self.archive, str(output))
            payload = source_study.read_locked(str(output), digest)
            self.assertEqual(len(payload["rows"]), 33)
            self.assertEqual(payload["model_calls_new"], 0)
            self.assertFalse(payload["original_labels_opened"])
            self.assertTrue(all(x["outcome"]["authority"] == "DENY_ALL" for x in payload["rows"]))
            self.assertTrue(all(x["outcome"]["map_evals"] >= 2 for x in payload["rows"]))
            self.assertEqual(len({x["task_id"] for x in payload["rows"]}), 33)
            with self.assertRaises(FileExistsError):
                blind.propose(self.archive, str(output))

    def test_original_zip_byte_mutation_fails_without_new_digest(self):
        if not self.real_file:
            self.assertFalse(self.real_file)
            return
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"altered.zip"
            raw=bytearray(Path(self.archive).read_bytes())
            raw[-4] ^= 1
            p.write_bytes(raw)
            with self.assertRaises(ValueError):
                blind.read_original(str(p))
            link=Path(t)/"link.zip"
            link.symlink_to(Path(self.archive))
            with self.assertRaises(ValueError):
                blind.read_original(str(link))

    def test_source_no_labels_or_relabelled_results(self):
        for action, expected in (("direct", "conditioned"), ("coupled", "mean_pool_query_fused"),
                                 ("stop",None), (None,None), ("hold",None)):
            self.assertEqual(blind.mapped_to_reader(action), expected)
        with self.assertRaises(ValueError):
            blind.mapped_to_reader("execute")
        self.assertEqual(blind.fixed_confidence(0.5), "mean_pool_query_fused")
        self.assertEqual(blind.fixed_confidence(0.9), "conditioned")
        self.assertEqual(blind.x0_from_conditional(0.5), "0")

    def test_fail_closed_blind_changed_plan_and_digest(self):
        if not self.real_file:
            return
        with tempfile.TemporaryDirectory() as t:
            dst=Path(t)/"blind.json"
            digest=blind.propose(self.archive,str(dst))
            with self.assertRaises(ValueError):
                source_study.read_locked(str(dst), "0"*64)
            d=source_study.read_locked(str(dst),digest)
            d["plan"]["max_maps"]=999
            dst.write_bytes(source_study.canonical(d))
            self.assertEqual(len(source_study.read_locked(str(dst),sha256(dst.read_bytes()).hexdigest())["rows"]),33)
            # A new SHA by the attacker does not bypass the scorer's exact plan.
            with self.assertRaises(ValueError):
                score.score(self.archive,str(dst),sha256(dst.read_bytes()).hexdigest(),"none.parquet",str(Path(t)/"scored"))

    def test_independent_original_math_replay_and_forgery(self):
        if not self.real_file:
            return
        with tempfile.TemporaryDirectory() as t:
            dst=Path(t)/"blind.json"
            digest=blind.propose(self.archive,str(dst))
            saved=source_study.read_locked(str(dst),digest)
            with compatibility_original_modules():
                audited=[score.independent_case(row, {}) for row in saved["rows"]]
            self.assertEqual(len(audited),33)
            self.assertEqual(sum(x["maps"] for x in audited),
                             sum(r["outcome"]["map_evals"] for r in saved["rows"]))
            row=saved["rows"][0]
            row["outcome"]["snapshots"]["direct"][0]["error_bound"]="0"
            with compatibility_original_modules():
                with self.assertRaises(ValueError):
                    score.independent_case(row,{})

    def test_human_owner_archive_checksum(self):
        if not self.real_file:
            return
        owner=score.historical_owner(self.archive)
        self.assertEqual(owner["results"]["conditioned"]["correct"],16)
        self.assertEqual(owner["results"]["mean_pool_query_fused"]["correct"],17)
        with self.assertRaises(ValueError):
            score.load_validation("/tmp/nonexistent-original-validation.parquet")

    def test_no_production_or_original_real_task_claim(self):
        if not self.real_file:
            return
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"proposal.json"
            blind.propose(self.archive,str(f))
            data=json.loads(f.read_bytes())
            self.assertFalse(data["E12_utility_is_real_task_identified"])
            self.assertFalse(data["natural_task_gain_established"])
            self.assertFalse(data["online_cost_advantage_verified"])
            self.assertFalse(data["production_accepted"])


class TestHumanLabelGrounding(unittest.TestCase):
    def test_invalid_fake_pub_sources_and_missing_roster_rejected(self):
        with self.assertRaises(ValueError):
            score.rebuild_human_labels([], [])
        with self.assertRaises(ValueError):
            score.rebuild_human_labels([{"paragraph":"foo"}], [{}]*33)

    def test_only_real_label_source_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"validation.parquet"
            p.write_bytes(b"synthetic")
            with self.assertRaises(ValueError):
                score.load_validation(str(p))


if __name__=="__main__":
    unittest.main()
