"""Adversarial source-only + genuine synthetic-vector CPU Head tests.

No original source/model data are loaded by this suite. This cannot qualify
natural reasoning, NDU gain, or physical pretrained Encoder savings.
"""
from __future__ import annotations

import dataclasses
from fractions import Fraction as Q
import hashlib
import math
import unittest

from feature_bus import Borrow, Denied as BusDenied, Scope, SharedFeatureBus
from circuit_ndu import Denied as CircuitDenied, EvidenceCircuit, Fact, Objective, rat
from physical_fanout import ACTIVE, PER_HEAD, SIZES, WIDTH, head_scores, head_scores_tensor, make_heads
from review_fanout import review, Denied as ReviewDenied

S = hashlib.sha256(b"test-only synthetic digest").hexdigest()
T = hashlib.sha256(b"other synthetic source digest").hexdigest()


def scope(**kw):
    v = dict(principal="p1", purpose="test", generation=1, epoch=0,
             revocation=S, model_sha=S, preprocess_sha=S)
    v.update(kw)
    return Scope(**v)


def fact(fid, src, rel, dst, fee="1/20", risk="0"):
    return Fact(fid, S, src, rel, dst, fee, risk)


def graph(hops=3, fee="1/20", extra=()):
    names = ["n" + str(i) for i in range(hops+1)]
    relations = tuple("r" + str(i) for i in range(hops))
    path = [fact("f" + str(i), names[i], relations[i], names[i+1], fee) for i in range(hops)]
    return EvidenceCircuit(Objective(names[0], names[-1], relations, "1", "1", "0"),
                           tuple(path) + tuple(extra))


class FanoutTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.auth = []
        def encoder(data, modality):
            self.calls.append((data, modality))
            return (float(len(data)) / 8, 0.5, -0.25)
        def allowed(b):
            self.auth.append(b.cell_id)
            return b.approved_use == "read"
        self.bus = SharedFeatureBus(3, encoder, allowed)

    def test_shared_4096_actual_callback_32_not_fake_pretrained(self):
        reqs = [Borrow(scope(), "text", ("source%d" % (i % 32)).encode(),
                       "cell:%d" % i, "read") for i in range(4096)]
        out = self.bus.fanout(reqs)
        self.assertEqual((len(out), self.bus.borrow_count, self.bus.physical_calls,
                          self.bus.resident_features, len(self.auth)), (4096, 4096, 32, 32, 8192))
        self.assertEqual(sum(x.cache_hit for x in out), 4064)
        self.assertEqual([x.key for x in out[:32]], [x.key for x in out[32:64]])

    def test_same_bytes_different_fences_never_share(self):
        cases = [scope(), scope(principal="p2"), scope(purpose="diff"),
                 scope(generation=2), scope(epoch=1), scope(revocation=T),
                 scope(model_sha=T), scope(preprocess_sha=T)]
        borrows = [Borrow(v, "text", b"text", "cell:1", "read") for v in cases]
        self.assertEqual(len({x.key for x in self.bus.fanout(borrows)}), len(cases))
        self.assertEqual(self.bus.physical_calls, len(cases))

    def test_modality_not_alias(self):
        inputs = [Borrow(scope(), v, b"input", "cell:1", "read") for v in
                  ("text", "image", "audio", "video")]
        self.assertEqual(self.bus.physical_calls, 0)
        self.bus.fanout(inputs)
        self.assertEqual(self.bus.physical_calls, 4)

    def test_revocation_during_encoder_forward_blocks_publication(self):
        granted = {"current": True}
        def encode(data, modality):
            granted["current"] = False
            return (0., 0., 0.)
        bus = SharedFeatureBus(3, encode, lambda b: granted["current"])
        with self.assertRaises(BusDenied):
            bus.fanout([Borrow(scope(), "text", b"one", "cell:x", "read")])
        self.assertEqual((bus.resident_features, bus.borrow_count), (0, 0))

    def test_cached_hit_still_revoked(self):
        b = Borrow(scope(), "text", b"a", "cell:1", "read")
        self.bus.fanout([b])
        with self.assertRaises(BusDenied):
            self.bus.fanout([dataclasses.replace(b, approved_use="revoke")])
        self.assertEqual(self.bus.physical_calls, 1)
        self.assertEqual(self.bus.borrow_count, 1)

    def test_preflight_denies_before_any_compute(self):
        okay = Borrow(scope(), "text", b"a", "cell:1", "read")
        wrong = Borrow(scope(), "text", b"a", "cell:2", "bad")
        with self.assertRaises(BusDenied):
            self.bus.fanout([okay, wrong])
        self.assertEqual((self.bus.physical_calls, self.bus.borrow_count), (0, 0))

    def test_invalid_shapes_and_nan_denied(self):
        for answer in ((float("nan"), 0., 0.), (10., 0., 0.), (0.,), [0., 0., 0.]):
            self.bus._encode = lambda _data, _modality, a=answer: a
            with self.assertRaises(BusDenied):
                self.bus.fanout([Borrow(scope(), "text", b"input", "cell:1", "read")])

    def test_real_batch_interface_is_single_group_with_32_features(self):
        calls = []
        def encode_batch(items):
            calls.append(len(items))
            return [(0.25, 0.5, 0.75) for _ in items]
        bus = SharedFeatureBus(3, self.bus._encode, lambda b: True,
                               batch_encode=encode_batch)
        rs = [Borrow(scope(), "text", ("case"+str(i % 32)).encode(),
                     "cell:"+str(i), "read") for i in range(256)]
        result = bus.fanout(rs)
        self.assertEqual((calls, bus.physical_calls, bus.borrow_count,
                          sum(r.cache_hit for r in result)), ([32], 32, 256, 224))

    def test_failed_batch_is_atomic(self):
        bus = SharedFeatureBus(3, self.bus._encode, lambda b: True,
                               batch_encode=lambda xs: [(1.0, 2.0, 3.0), (float("nan"), 1., 0.)])
        with self.assertRaises(BusDenied):
            bus.fanout([Borrow(scope(), "text", bytes([i]), "cell:x", "read") for i in (1, 2)])
        self.assertEqual((bus.resident_features, bus.borrow_count, bus.physical_calls), (0, 0, 0))

    def test_invalid_user_inputs_denied(self):
        for mutated in (Borrow(scope(generation=True), "text", b"a", "c", "read"),
                        Borrow(scope(), "unknown", b"a", "c", "read"),
                        Borrow(scope(), "text", b"", "c", "read"),
                        Borrow(scope(), "text", b"a", "white space", "read")):
            with self.assertRaises(BusDenied):
                self.bus.fanout([mutated])

    def test_cache_limit_and_invalidation(self):
        b = Borrow(scope(), "text", b"data", "cell:1", "read")
        self.bus.fanout([b])
        self.bus.invalidate()
        self.bus.fanout([b])
        self.assertEqual((self.bus.physical_calls, self.bus.resident_features), (2, 1))
        oversized = [Borrow(scope(), "text", str(i).encode(), "cell:x", "read")
                     for i in range(1025)]
        with self.assertRaises(BusDenied):
            self.bus.fanout(oversized)


class CircuitTests(unittest.TestCase):
    def test_3_hop_exact_ordinary_ndu_parity(self):
        r = graph().compare_same_profile()
        self.assertEqual(r["proof"], ["f0", "f1", "f2"])
        self.assertEqual(r["ndu_value"], r["ordinary_value"])
        self.assertTrue(r["success"])
        self.assertFalse(r["pretrained_reasoning_verified"])
        self.assertEqual(r["disposition"], "HOLD_NO_GO")

    def test_6_hop(self):
        r = graph(6).compare_same_profile()
        self.assertEqual(r["hops"], 6)
        self.assertTrue(r["success"])

    def test_dangerous_branch_refused_by_risk(self):
        f = fact("alt", "n0", "r0", "bad", "0", "1")
        c = graph(extra=(f,))
        c.objective = dataclasses.replace(c.objective, max_risk="0")
        self.assertEqual(c.compare_same_profile()["proof"], ["f0", "f1", "f2"])

    def test_wrong_end_abstain(self):
        c = graph()
        c.objective = dataclasses.replace(c.objective, end="unexpected")
        r = c.compare_same_profile()
        self.assertEqual(r["proof"], [])
        self.assertFalse(r["success"])

    def test_expensive_steps_are_not_automatically_reasoning_win(self):
        c = graph(3, fee="1")
        self.assertEqual(c.compare_same_profile()["proof"], [])

    def test_source_digest_is_not_ground_truth(self):
        c = graph()
        r = c.compare_same_profile()
        self.assertTrue(r["success"])
        # A digest demonstrates binding to declared evidence only; model/human
        # truth verification is not part of this finite deterministic fixture.
        self.assertEqual(r["source_digests"], [S, S, S])

    def test_all_branches_enumerated_same_objective(self):
        others = tuple(fact("alt"+str(i), "n"+str(i), "r"+str(i),
                            "branch"+str(i), "1/10") for i in range(5))
        for depth in range(2, 7):
            c = graph(depth, extra=others[:depth])
            self.assertEqual(c.ndu_backward(), c.ordinary_reference())

    def test_illegal_and_stale_edges_rejected(self):
        c = graph()
        with self.assertRaises(CircuitDenied):
            c.validate_path(("f2",))
        with self.assertRaises(CircuitDenied):
            c.validate_path(("not_registered",))
        with self.assertRaises(CircuitDenied):
            EvidenceCircuit(c.objective, c.facts + (c.facts[0],))

    def test_malformed_preference_and_goal_denied(self):
        for p in ("-0.1", "1.2", "NaN", "1/0", "1/10000001"):
            with self.assertRaises(CircuitDenied):
                graph().objective.__class__("a", "b", ("r1", "r2"), "1", "1", p).verify_shape()
        with self.assertRaises(CircuitDenied):
            EvidenceCircuit(Objective("a", "b", ("one",), "1", "1", "0"), (fact("f", "a", "one", "b"),))

    def test_nonfinite_or_wrong_fact_denied(self):
        for x in ("-1", "NaN", "1/0", "1.4"):
            with self.assertRaises(CircuitDenied):
                EvidenceCircuit(graph().objective, (fact("x", "a", "r0", "b", fee=x),))
        with self.assertRaises(CircuitDenied):
            EvidenceCircuit(graph().objective, (dataclasses.replace(fact("x", "a", "r0", "b"), source_sha="abc"),))


class PhysicalHeadTests(unittest.TestCase):
    def test_actual_torch_head_allocation_forward(self):
        import torch
        torch.set_num_threads(2)
        data = [[(j % 13) * 0.001 for j in range(WIDTH)] for _ in range(ACTIVE)]
        small = make_heads(64)
        medium = make_heads(256)
        self.assertEqual(sum(x.numel() for x in small.values()), 64 * PER_HEAD)
        self.assertEqual(sum(x.numel() * x.element_size() for x in medium.values()), 256 * PER_HEAD * 4)
        self.assertEqual(head_scores(small, data), head_scores(medium, data))
        small["out"][0][1] = 1.
        self.assertNotEqual(head_scores(small, data), head_scores(medium, data))

    def test_actual_sgd_updates_only_active_cell_head(self):
        import torch
        torch.set_num_threads(2)
        bank = make_heads(64)
        p = torch.nn.Parameter(bank["out"].clone())
        bank["out"] = p
        before = p.detach().clone()
        optimizer = torch.optim.SGD([p], lr=0.1)
        x = torch.ones((ACTIVE, WIDTH), dtype=torch.float32)
        optimizer.zero_grad()
        loss = (head_scores_tensor(bank, x) - 1).square().mean()
        loss.backward()
        optimizer.step()
        self.assertTrue(torch.equal(p.detach()[ACTIVE:], before[ACTIVE:]))
        self.assertFalse(torch.equal(p.detach()[:ACTIVE], before[:ACTIVE]))

    def test_head_rejects_nan(self):
        bank = make_heads(64)
        with self.assertRaises(BusDenied):
            head_scores(bank, [[float("nan")] * WIDTH for _ in range(ACTIVE)])


class ReviewerTests(unittest.TestCase):
    def fixture(self):
        held = [{"case_id": "heldout:" + hashlib.sha256(str(i).encode()).hexdigest(),
                 "source_sha256": hashlib.sha256(str(i).encode()).hexdigest(),
                 "text": str(i)} for i in range(32)]
        source = {"schema": "hepta.stem.optimal.original-source.v1",
                  "heldout_labels_excluded": True, "production_authorized": False,
                  "heldout": held, "source_plan_sha256": S}
        manifest = {"candidates": {"granite97": {"repo": "original/granite97", "revision": "0" * 40,
                                                     "weight_sha256": T}}, "research_only": True,
                    "production_authorized": False, "precision": "float32_cpu",
                    "preprocessing": "tokenizer_native_trunc128_masked_mean_l2"}
        cohorts = [{"fleet_size": n, "active_heads": 32, "logical_borrows": n,
                    "unique_inputs": 32, "distinct_encoded_inputs": 32,
                    "physical_encoder_batches": 2, "physical_encoder_sequences": 32,
                    "head_scalars": n * PER_HEAD, "head_weight_bytes_fp32": n * PER_HEAD * 4,
                    "metadata_circuit_parity_count": 32,
                    "head_output_sha256": S, "scoped_feature_digest": T,
                    "cohort_wall_seconds": 5., "cohort_cpu_seconds": 3.,
                    "feature_wall_seconds": 4., "maxrss_bytes_process": 2000000} for n in SIZES]
        receipt = {"schema": "hepta.hdsi.granite97-fanout-unattested.v1",
                   "parent_source_plan_sha256": S,
                   "model_repo": "original/granite97", "model_revision": "0" * 40,
                   "model_sha256": T, "candidate": "granite97",
                   "source_case_ids": [r["case_id"] for r in held],
                   "source_digest_ids": [r["source_sha256"] for r in held],
                   "source_feature_keys": [hashlib.sha256(b"hepta.hdsi.feature.v1\0" +
                       __import__("json").dumps({"scope": {
                           "principal":"original-public-test", "purpose":"hdsi-shadow",
                           "generation":1, "epoch":0,
                           "revocation":hashlib.sha256(b"hdsi-study-revocation-unattested").hexdigest(),
                           "model_sha":T, "preprocess_sha":hashlib.sha256(
                               b"tokenizer_native_trunc128_masked_mean_l2").hexdigest()},
                           "modality":"text", "payload_sha256":r["source_sha256"]},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
                                           for r in held],
                   "cohorts": cohorts, "total_wall_seconds": 25.,
                   "total_cpu_seconds": 20., "model_download_load_wall_seconds": 1.,
                   "host_attested": False, "stem_winner_verified": False,
                   "ndu_task_lift_verified": False, "natural_reasoning_verified": False,
                   "future_holdout_verified": False, "production_authorized": False,
                   "disposition": "HOLD_NO_GO"}
        return source, manifest, receipt

    def test_4_size_no_go_with_synthetic_receipt(self):
        s, m, r = self.fixture()
        out = review(s, m, r)
        self.assertEqual([x["fleet"] for x in out["scale_panel"]], list(SIZES))
        self.assertFalse(out["pretrained_model_forward_attested"])

    def test_wrong_tampered_costs_or_production_claim_rejected(self):
        import copy
        for changes in (lambda r: r["cohorts"][3].update(physical_encoder_batches=0),
                        lambda r: r["cohorts"][2].update(head_scalars=1),
                        lambda r: r.update(production_authorized=True),
                        lambda r: r.update(disposition="PASS"),
                        lambda r: r["cohorts"][0].update(feature_wall_seconds=100.0),
                        lambda r: r.update(model_sha256=S),
                        lambda r: r["cohorts"][0].update(maxrss_bytes_process=-5),
                        lambda r: r["cohorts"][1].update(metadata_circuit_parity_count=0),
                        lambda r: r["source_feature_keys"].reverse()):
            s, m, r = copy.deepcopy(self.fixture())
            changes(r)
            with self.assertRaises(ReviewDenied):
                review(s, m, r)


if __name__ == "__main__":
    unittest.main()
