"""Deterministic fixtures test mechanics only; not native-model efficacy."""

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import torch
from torch import nn

from system2_ablation import (
    ARMS,
    BudgetExceeded,
    Continuation,
    Limits,
    Meter,
    Profile,
    census,
    choose_set,
    digest,
    execute_matrix,
    model_digest,
    train_continuation,
)
from finite_tree_bsde import conditional_z, recursive_utility, solve_path


@dataclass(frozen=True)
class FixtureFeatures:
    paired: torch.Tensor
    frozen_scores: torch.Tensor
    question_id: str = "test-q"
    family: str = "test-family"
    encoder_identity: str = "fixture-not-a-pretrained-model"
    pool_digest: str = "fixture-pool"
    roots: frozenset = frozenset({"fixture-root"})

    @property
    def candidate_ids(self):
        return tuple(f"c{i}" for i in range(len(self.paired)))

    def validate(self, dimension):
        if (
            self.paired.ndim != 2
            or self.paired.shape[1] != dimension
            or self.frozen_scores.shape != (len(self.paired),)
            or not torch.isfinite(self.paired).all()
            or not torch.isfinite(self.frozen_scores).all()
        ):
            raise ValueError("fixture shape")

    def seal(self):
        return digest(
            (self.question_id, self.paired.tolist(), self.frozen_scores.tolist())
        )


class FixtureHead(nn.Module):
    """Only used for hermetic mechanics; native runner uses existing StemHead."""

    def __init__(self):
        super().__init__()
        self.shift = nn.Parameter(torch.zeros(1))
        self.roots = set()

    def forward(self, f):
        return torch.cat((f.frozen_scores + self.shift, self.shift))


def fixture(seed=719, qid="test-q", family="test-family"):
    g = torch.Generator().manual_seed(seed)
    return FixtureFeatures(
        torch.randn(3, 4, generator=g),
        torch.randn(3, generator=g),
        question_id=qid,
        family=family,
    )


def model():
    m = Continuation(4, hidden=4)
    m.encoder_identity = "fixture-not-a-pretrained-model"
    return m


class NumericTests(unittest.TestCase):
    def test_native_recursive_real_golden(self):
        values = recursive_utility([0.5, 0.25], [0.8, 0.8], 1)
        for a, b in zip(values, [1.34, 1.05, 1]):
            self.assertAlmostEqual(a, b)

    def test_centering_and_nonidentity_covariance(self):
        m = torch.tensor([[3.0, 4.0], [3.0, -2.0], [-1.0, 4.0], [-1.0, -2.0]])
        y = 3 * m[:, 0] - m[:, 1] + 7
        z, residual = conditional_z(m, y, torch.full((4,), 0.25))
        self.assertTrue(
            torch.allclose(z, torch.tensor([3.0, -1.0], dtype=torch.double))
        )
        self.assertLess(residual, 1e-12)

    def test_singular_covariance_rejected(self):
        with self.assertRaises(ValueError):
            conditional_z(torch.ones(4, 2), torch.ones(4), torch.full((4,), 0.25))

    def test_chance_nodes_use_mean_not_lucky_branch(self):
        p = Profile(
            horizon=0.2,
            sigma=0.1,
            coupling=0,
            rho=0,
            risk=0,
            cost=0,
            damping=1,
            tolerance=1e-6,
        )
        out = solve_path(
            torch.zeros(1, 1),
            torch.zeros(1),
            lambda h, a: h,
            lambda h: h[0] + 1,
            p,
            lambda *_: None,
        )
        self.assertAlmostEqual(out.value, 1.0, places=6)
        self.assertTrue(out.converged)
        self.assertAlmostEqual(out.z_max, 0.1, places=5)

    def test_zero_noise_matches_deterministic_profile(self):
        p = Profile(
            horizon=0.3, sigma=0, coupling=0, risk=0, damping=1, rho=0.1, cost=0.02
        )
        out = solve_path(
            torch.zeros(3, 1),
            torch.zeros(1),
            lambda h, a: h,
            lambda h: h[0] * 0 + 1,
            p,
            lambda *_: None,
        )
        dt = 0.1
        expected = recursive_utility(
            [-0.02 * dt / (1 + 0.1 * dt)] * 3, [1 / (1 + 0.1 * dt)] * 3, 1.0
        )[0]
        self.assertAlmostEqual(out.value, expected, places=7)
        self.assertEqual(out.z_max, 0)
        self.assertTrue(out.converged)

    def test_wrong_boundary_terminal_success_not_global_success(self):
        p = Profile(horizon=0.3, sigma=0.05, coupling=0.05, cost=0.2, damping=1)
        args = (
            torch.zeros(3, 1),
            torch.zeros(1),
            lambda h, a: h,
            lambda h: h[0] * 0 + 1,
            p,
            lambda *_: None,
        )
        good, bad = solve_path(*args), solve_path(*args, wrong_boundary=True)
        self.assertTrue(good.converged)
        self.assertEqual(bad.terminal_residual, 0)
        self.assertGreater(bad.backward_residual, 0.01)
        self.assertFalse(bad.converged)

    def test_nonconvergence_remains_failure(self):
        p = Profile(iterations=1, damping=0.1)
        out = solve_path(
            torch.zeros(2, 1),
            torch.zeros(1),
            lambda h, a: h,
            lambda h: h[0] * 0 + 1,
            p,
            lambda *_: None,
        )
        self.assertFalse(out.converged)

    def test_profile_rejects_nonfinite_or_unbounded(self):
        for kwargs in (
            {"horizon": 0},
            {"sigma": float("nan")},
            {"iterations": 100},
            {"rho": -1},
        ):
            with self.assertRaises(ValueError):
                Profile(**kwargs).validate()


class ProtocolTests(unittest.TestCase):
    def test_budget_failure_is_charged(self):
        m = Meter(Limits(operations=1))
        with self.assertRaises(BudgetExceeded):
            m.charge("critic", 2)
        self.assertEqual(m.receipt()["attempted_operations"]["critic"], 2)

    def test_complete_eight_arm_census(self):
        records = execute_matrix(
            fixture(),
            {k: FixtureHead() for k in ("linear", "gated")},
            model(),
            lambda selected: (str(selected), {"fixture": True}),
            limits=Limits(candidates=2, evidence=2),
        )
        report = census(records, ["test-q"])
        self.assertEqual(report["recorded"], 8)
        self.assertEqual(report["failed"], 0)
        self.assertFalse(report["equal_observed_cost"])
        for row in records:
            self.assertEqual(row["cost"]["attempted_operations"]["reader_calls"], 1)

    def test_failed_reader_kept_in_denominator(self):
        def bad(_):
            raise RuntimeError("reader failure")

        records = execute_matrix(
            fixture(),
            {k: FixtureHead() for k in ("linear", "gated")},
            model(),
            bad,
            limits=Limits(candidates=2, evidence=2),
        )
        self.assertEqual(census(records, ["test-q"])["failed"], 8)
        self.assertTrue(
            all(r["cost"]["attempted_operations"]["reader_calls"] == 1 for r in records)
        )

    def test_census_missing_duplicate_and_invalid_status(self):
        records = [{"question_id": "q", "arm": a, "status": "failed"} for a in ARMS]
        for bad in (
            records[:-1],
            records + records[:1],
            records[:-1] + [{**records[-1], "status": "skip"}],
        ):
            with self.assertRaises(ValueError):
                census(bad, ["q"])

    def test_revoked_training_lineage_rejected(self):
        m = model()
        m.roots = frozenset({"withdrawn-training-root"})
        with self.assertRaises(ValueError):
            choose_set(
                "fbsde_stochastic", fixture(), {}, m, Meter(Limits()), revoked=m.roots
            )

    def test_encoder_identity_cannot_drift(self):
        m = model()
        m.encoder_identity = "other-version"
        with self.assertRaises(ValueError):
            choose_set("fbsde_stochastic", fixture(), {}, m, Meter(Limits()))

    def test_eval_parameters_immutable(self):
        m = model()
        before = model_digest(m)
        choose_set(
            "fbsde_stochastic",
            fixture(),
            {},
            m,
            Meter(Limits(candidates=2, evidence=2)),
        )
        self.assertEqual(before, model_digest(m))

    def test_admission_precedes_training(self):
        f, m = fixture(), model()
        before = model_digest(m)
        cut = SimpleNamespace(
            admission_digest="admitted",
            question_ids={"another-q"},
            families={f.family},
            allowed_roots=f.roots,
            forbidden_roots=set(),
        )
        with self.assertRaises(ValueError):
            train_continuation(
                m, [SimpleNamespace(features=f, positive_indices=(0,))], cut
            )
        self.assertEqual(before, model_digest(m))

    def test_actual_gradient_updates_and_training_cost(self):
        f, m = fixture(), model()
        cut = SimpleNamespace(
            admission_digest="admitted-fixture",
            question_ids={f.question_id},
            families={f.family},
            allowed_roots=f.roots,
            forbidden_roots=set(),
        )
        receipt = train_continuation(
            m, [SimpleNamespace(features=f, positive_indices=(0,))], cut, steps=16
        )
        self.assertNotEqual(receipt["before"], receipt["after"])
        self.assertEqual(receipt["updates"], 16)
        self.assertGreater(
            receipt["costs"]["attempted_operations"]["training_pairs"], 0
        )

    def test_training_failure_quarantines(self):
        f, m = fixture(), model()
        cut = SimpleNamespace(
            admission_digest="admitted-fixture",
            question_ids={f.question_id},
            families={f.family},
            allowed_roots=f.roots,
            forbidden_roots=set(),
        )
        with self.assertRaises(BudgetExceeded):
            train_continuation(
                m,
                [SimpleNamespace(features=f, positive_indices=(0,))],
                cut,
                pair_ceiling=1,
            )
        self.assertTrue(m.quarantined)

    def test_frozen_baseline_does_not_need_a_trained_continuation(self):
        m = Continuation(4, hidden=4)
        m.quarantined = True
        selected, _ = choose_set("rag", fixture(), {}, m, Meter(Limits()))
        self.assertEqual(len(selected), 3)

    def test_no_candidate_is_empty_evidence(self):
        f = FixtureFeatures(torch.empty(0, 4), torch.empty(0))
        selected, _ = choose_set("rag", f, {}, model(), Meter(Limits()))
        self.assertEqual(selected, ())


class ReviewTests(unittest.TestCase):
    """Ephemeral fixture signatures are NOT real human reviews."""

    def setUp(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from datetime import datetime, timezone
        from system2_reader_controls import canonical

        self.key = Ed25519PrivateKey.generate()
        self.now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        self.review = dict(
            reviewer_id="unit-test-fixture-only",
            review_basis="external_review",
            claim="jointly_sufficient_and_each_requirement_necessary",
            query_digest="q",
            source_frontier="f",
            reviewed_at="2026-10-10T00:00:00Z",
        )
        self.envelope = {
            "review": self.review,
            "signature": base64.b64encode(
                self.key.sign(canonical(self.review))
            ).decode(),
        }
        self.registry = {
            "schema": "hepta.system2.review-trust.v1",
            "reviewers": {
                "unit-test-fixture-only": dict(
                    role="independent_human",
                    revoked=False,
                    valid_from="2026-01-01T00:00:00Z",
                    valid_until="2027-01-01T00:00:00Z",
                    public_key=base64.b64encode(
                        self.key.public_key().public_bytes(
                            Encoding.Raw, PublicFormat.Raw
                        )
                    ).decode(),
                )
            },
        }

    def verify(self, **kwargs):
        from system2_reader_controls import authenticate_review

        return authenticate_review(
            self.envelope,
            self.registry,
            query_digest="q",
            frontier="f",
            experiment_authors=kwargs.get("authors", set()),
            now=self.now,
        )

    def test_authenticated_fixture_is_not_semantic_truth(self):
        receipt = self.verify()
        self.assertTrue(receipt["authenticated_identity_under_supplied_registry"])
        self.assertFalse(receipt["semantic_truth_proven_by_signature"])

    def test_tampering_rejected(self):
        from cryptography.exceptions import InvalidSignature

        self.review["requirements"] = ["inserted-after-signing"]
        with self.assertRaises(InvalidSignature):
            self.verify()

    def test_author_cannot_self_certify(self):
        with self.assertRaises(ValueError):
            self.verify(authors={"unit-test-fixture-only"})

    def test_model_authored_or_untrusted_review_rejected(self):
        self.review["review_basis"] = "model_assisted_review"
        with self.assertRaises(ValueError):
            self.verify()

    def test_revocation_rejected(self):
        self.registry["reviewers"]["unit-test-fixture-only"]["revoked"] = True
        with self.assertRaises(ValueError):
            self.verify()

    def test_expiry_rejected(self):
        self.registry["reviewers"]["unit-test-fixture-only"]["valid_until"] = (
            "2026-02-01T00:00:00Z"
        )
        with self.assertRaises(ValueError):
            self.verify()

    def test_missing_controls_preserved(self):
        from system2_reader_controls import CONDITIONS, diagnostic_census

        records = [
            dict(question_id="q", condition=c, status="unavailable") for c in CONDITIONS
        ]
        result = diagnostic_census(records, ["q"])
        self.assertEqual(result["missing_or_failed"], 4)
        self.assertFalse(result["reader_adequacy_established"])

    def test_pinned_json_rejects_hash_mismatch_duplicate_keys(self):
        import hashlib
        from system2_reader_controls import load_pinned_json

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "p.json"
            raw = b'{"x":1,"x":2}'
            p.write_bytes(raw)
            with self.assertRaises(ValueError):
                load_pinned_json(p, hashlib.sha256(raw).hexdigest())
            with self.assertRaises(ValueError):
                load_pinned_json(p, "0" * 64)


if __name__ == "__main__":
    unittest.main()
