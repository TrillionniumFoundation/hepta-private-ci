"""Normal + optimized Python, including actual local AOT C execution."""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
import random
import tempfile
import unittest

from fabric import (
    Choice, Denied, Edge, FiniteNdu, Head,
    Observation, LIMIT, Q24, StemBank, StemSpec, certify_scalar_contraction,
    make_synthetic_encoder, physical_shadow_bench, q24_dot, round_q24,
    sha, synthetic_head,
)
from native import CellProgram, NativeMotorShadow, compile_reviewed_source


STEM = sha(b"frozen mathematical candidate")
SPEC = StemSpec(STEM, sha(b"prep"), sha(b"q24"), 16, 7, 2)
RAW = b"textual question plus options and task context"
OBS = Observation(RAW, "principal-a", "test", "text", 7, 2, 1_000_000, sha(RAW))


def graph():
    term = {"done": F(0), "good": F(1), "bad": F(-1)}
    g = {
        "start": (
            Choice("stop", 1, (Edge(F(1), F(0), "done"),)),
            Choice("probe", 1, (Edge(F(1, 2), F(0), "good"), Edge(F(1, 2), F(0), "bad"))),
            Choice("direct", 1, (Edge(F(1), F(1, 4), "done"),)),
        )
    }
    return g, term


class StemTests(unittest.TestCase):
    def test_real_one_encoder_forward_many_heads(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        for i in range(256):
            feature = bank.borrow(OBS, now_ns=99, allowed=True)
            self.assertIsInstance(synthetic_head(i, STEM, 16).evaluate(feature), int)
        self.assertEqual(bank.forward_calls, 1)
        self.assertEqual(bank.cache_hits, 255)

    def test_revoke_cache_hit(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        bank.borrow(OBS, 99, allowed=True)
        with self.assertRaises(Denied):
            bank.borrow(OBS, 99, allowed=False)
        self.assertEqual(bank.forward_calls, 1)

    def test_cross_principal_no_cache_reuse(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        bank.borrow(OBS, 99, allowed=True)
        bank.borrow(replace(OBS, principal="principal-b"), 99, allowed=True)
        self.assertEqual(bank.forward_calls, 2)

    def test_cross_purpose_no_cache_reuse(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        bank.borrow(OBS, 99, allowed=True)
        bank.borrow(replace(OBS, purpose="other"), 99, allowed=True)
        self.assertEqual(bank.forward_calls, 2)

    def test_cross_modality_no_cache_reuse(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        bank.borrow(OBS, 99, allowed=True)
        bank.borrow(replace(OBS, modality="image"), 99, allowed=True)
        self.assertEqual(bank.forward_calls, 2)

    def test_wrong_generation_epoch(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        for bad in (replace(OBS, generation=8), replace(OBS, epoch=3)):
            with self.subTest(bad=bad):
                with self.assertRaises(Denied):
                    bank.borrow(bad, 99, allowed=True)
        self.assertEqual(bank.forward_calls, 0)

    def test_wrong_digest_and_content(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        for bad in (replace(OBS, payload=b"changed"), replace(OBS, declared_source_digest="X" * 64)):
            with self.subTest(bad=bad):
                with self.assertRaises(Denied):
                    bank.borrow(bad, 99, allowed=True)

    def test_expiry_refuses_even_cached_feature(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        bank.borrow(OBS, 99, allowed=True)
        with self.assertRaises(Denied):
            bank.borrow(OBS, OBS.expiry_ns, allowed=True)

    def test_encoder_wrong_width_noncanonical(self):
        for result in [(0,), tuple(float("nan") for _ in range(16)), tuple(True for _ in range(16)), tuple(9 * Q24 for _ in range(16))]:
            with self.subTest(result=result):
                bank = StemBank(SPEC, lambda _: result)
                with self.assertRaises(Denied):
                    bank.borrow(OBS, 99, allowed=True)
                self.assertEqual(bank.forward_calls, 0)

    def test_head_identity_is_mandatory(self):
        bank = StemBank(SPEC, make_synthetic_encoder(16))
        feature = bank.borrow(OBS, 99, allowed=True)
        with self.assertRaises(Denied):
            Head("cell", sha(b"wrong"), (0,) * 16).evaluate(feature)

    def test_bench_has_all_real_head_calls(self):
        out = physical_shadow_bench(64, 4)
        self.assertEqual(out["unique_encoder_forwards"], 1)
        self.assertEqual(out["cache_borrows"], 64 * 4 - 1)
        self.assertEqual(out["actual_head_calls"], 64 * 4)
        self.assertEqual(out["authority"], "DENY_ALL")


class NduTests(unittest.TestCase):
    def test_expected_values_and_stop(self):
        g, t = graph()
        d = FiniteNdu(g, t).choose("start", 2)
        self.assertEqual(d.action, "direct")
        self.assertEqual(d.value, F(1, 4))
        self.assertEqual(dict(d.all_values)["probe"], F(0))

    def test_stop_wins_negative_tasks(self):
        g, t = graph()
        g["start"] = (
            Choice("stop", 1, (Edge(F(1), F(0), "done"),)),
            Choice("risky", 1, (Edge(F(1), F(-1), "done"),)),
        )
        self.assertEqual(FiniteNdu(g, t).choose("start", 1).action, "stop")

    def test_short_horizon_future_reward(self):
        g = {
            "s": (Choice("stop", 1, (Edge(F(1), F(0), "done"),)),
                  Choice("invest", 1, (Edge(F(1), F(0), "after"),))),
            "after": (Choice("stop", 1, (Edge(F(1), F(0), "done"),)),
                      Choice("complete", 1, (Edge(F(1), F(2), "done"),))),
        }
        d = FiniteNdu(g, {"done": F(0)}, max_depth=2).choose("s", 2)
        self.assertEqual((d.action, d.value), ("invest", F(2)))
        self.assertEqual(FiniteNdu(g, {"done": F(0)}, max_depth=1).choose("s", 2).action, "stop")

    def test_hard_budget_keeps_stop(self):
        g, t = graph()
        g["start"] = (g["start"][0], Choice("large", 15, (Edge(F(1), F(99), "done"),)))
        self.assertEqual(FiniteNdu(g, t).choose("start", 1).action, "stop")

    def test_bad_probability_rejected(self):
        g, t = graph()
        g["start"] = (g["start"][0], Choice("bad", 1, (Edge(F(3, 4), F(1), "good"),)))
        with self.assertRaises(Denied):
            FiniteNdu(g, t)

    def test_stop_cannot_hide_continuation(self):
        g, t = graph()
        g["start"] = (Choice("stop", 1, (Edge(F(1), F(0), "start"),)),)
        with self.assertRaises(Denied):
            FiniteNdu(g, t)

    def test_scope_of_contraction_certificate(self):
        cert = certify_scalar_contraction(fixed_reward=F(1, 4), q=F(1, 2))
        self.assertLessEqual(abs(cert.approximation - F(1, 2)), cert.error_bound)
        self.assertLessEqual(cert.error_bound, F(1, 1 << 20))
        self.assertLessEqual(cert.iterations, 64)

    def test_invalid_contraction_rejected(self):
        for q in (F(3, 4), F(1), F(-1)):
            with self.subTest(q=q):
                with self.assertRaises(Denied):
                    certify_scalar_contraction(fixed_reward=F(1), q=q)

    def test_exhaustion_not_called_success(self):
        with self.assertRaises(Denied):
            certify_scalar_contraction(fixed_reward=F(1), q=F(1, 2), max_steps=1)


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="hepta-cell-p0-")
        cls.path = Path(cls.tmp.name)
        cls.bin = cls.path / "kernel.so"
        cls.record = compile_reviewed_source(Path(__file__).with_name("q24_native.c"), cls.bin)
        cls.worker = NativeMotorShadow(cls.bin, cls.record["binary_sha256"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def program(self):
        return CellProgram(sha(b"original observation"), STEM, 7, "PURE_Q24_DOT16")

    def test_aot_actual_cpu_and_parity(self):
        features = (Q24, -Q24, Q24 // 2)
        weights = (Q24, Q24, Q24)
        receipt = self.worker.run(self.program(), features, weights)
        self.assertEqual(receipt.numeric_result, q24_dot(features, weights))
        self.assertEqual(receipt.authority, "DENY_ALL")

    def test_randomized_bit_exact_python_vs_c(self):
        rng = random.Random(3331)
        for _ in range(500):
            n = rng.randint(1, 16)
            a = tuple(rng.randint(-LIMIT, LIMIT) for _ in range(n))
            b = tuple(rng.randint(-LIMIT, LIMIT) for _ in range(n))
            self.assertEqual(self.worker.run(self.program(), a, b).numeric_result, q24_dot(a, b))

    def test_round_to_even_halfway(self):
        self.assertEqual(round_q24(Q24 // 2), 0)
        self.assertEqual(round_q24(3 * Q24 // 2), 2)
        self.assertEqual(round_q24(-3 * Q24 // 2), -2)
        self.assertEqual(self.worker.run(self.program(), (Q24 // 2,), (1,)).numeric_result, 0)

    def test_effect_proposal_denied(self):
        for bad in (replace(self.program(), requested_effect=True),
                    replace(self.program(), opcode="CLICK_UI"),
                    replace(self.program(), generation=0)):
            with self.subTest(bad=bad):
                with self.assertRaises(Denied):
                    self.worker.run(bad, (Q24,), (Q24,))

    def test_input_tamper_rejected(self):
        with self.assertRaises(Denied):
            self.worker.run(self.program(), (9 * Q24,), (Q24,))

    def test_fake_native_hash_rejected(self):
        with self.assertRaises(Denied):
            NativeMotorShadow(self.bin, sha(b"fake"))

    def test_native_binary_cannot_be_compiled_over_existing_path(self):
        with self.assertRaises(Denied):
            compile_reviewed_source(Path(__file__).with_name("q24_native.c"), self.bin)

    def test_source_replacement_rejected(self):
        with self.assertRaises(Denied):
            compile_reviewed_source(Path(__file__).with_name("fabric.py"), self.path / "bad.so")


if __name__ == "__main__":
    unittest.main()
