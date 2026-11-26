"""Mechanics fixtures, never pretrained-task or production benefit evidence."""

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import torch

from selector_head import Features, Supervision, TrainingCut
from stem_cell import StemHead, clone_features, route_text, sha256
from stem_cell_cache import SharedFeatureCache


def features(q="train", root="root", identity="encoder-v1"):
    return Features(
        q,
        "family",
        identity,
        "pool",
        ("a", "b"),
        frozenset({root}),
        torch.tensor([[1.0, 0.5, 0.0, 0.0], [-1.0, -0.5, 0.0, 0.0]]),
        torch.tensor([0.2, 0.5]),
    )


def training_cut():
    return TrainingCut(
        frozenset({"train", "second"}),
        frozenset({"family"}),
        frozenset({"root"}),
        frozenset({"held-out"}),
        "admission",
    )


def restore(head):
    payload = head.export()
    return StemHead.restore(
        payload,
        expected_sha256=sha256(payload),
        encoder_identity=head.encoder_identity,
        allowed_roots={"root"},
        revoked=set(),
    )


class HeadTests(unittest.TestCase):
    def setUp(self):
        self.row = Supervision(features(), (0,))

    def test_linear_reduces_actual_loss(self):
        head = StemHead(4, "encoder-v1", kind="linear")
        receipt = head.fit((self.row,), training_cut(), revoked=set(), steps=64)
        self.assertLess(receipt["loss_last"], receipt["loss_first"])
        self.assertEqual(
            head.decide(features("unseen", "held-out"), revoked=set())[0], 0
        )

    def test_gated_reduces_actual_loss(self):
        head = StemHead(4, "encoder-v1", kind="gated")
        receipt = head.fit((self.row,), training_cut(), revoked=set(), steps=64)
        self.assertLess(receipt["loss_last"], receipt["loss_first"])
        self.assertEqual(
            head.decide(features("unseen", "held-out"), revoked=set())[0], 0
        )

    def test_prototype_accumulates_without_recounting_replay(self):
        head = StemHead(4, "encoder-v1", kind="prototype")
        head.fit((self.row,), training_cut(), revoked=set())
        second = Supervision(features("second"), (0,))
        head.fit((self.row, second), training_cut(), revoked=set())
        self.assertEqual(head.counts.tolist(), [2.0, 2.0])
        self.assertEqual(head.seen, {"train", "second"})

    def test_all_kinds_reload_identically(self):
        for kind in ("linear", "prototype", "gated"):
            with self.subTest(kind=kind):
                head = StemHead(4, "encoder-v1", kind=kind)
                head.fit((self.row,), training_cut(), revoked=set(), steps=16)
                loaded = restore(head)
                self.assertEqual(head.export(), loaded.export())
                self.assertEqual(
                    head.decide(features(), revoked=set()),
                    loaded.decide(features(), revoked=set()),
                )

    def test_resume_is_exact_not_reinitialization(self):
        uninterrupted = StemHead(4, "encoder-v1")
        uninterrupted.fit((self.row,), training_cut(), revoked=set(), steps=16)
        loaded = restore(uninterrupted)
        for head in (loaded, uninterrupted):
            head.fit((self.row,), training_cut(), revoked=set(), steps=16)
        self.assertEqual(loaded.export(), uninterrupted.export())
        self.assertEqual(loaded.steps, 32)

    def test_training_one_cell_leaves_other_unchanged(self):
        a, b = StemHead(4, "encoder-v1"), StemHead(4, "encoder-v1")
        before = b.export()
        a.fit((self.row,), training_cut(), revoked=set(), steps=16)
        self.assertEqual(b.export(), before)
        self.assertNotEqual(a.export(), before)

    def test_cumulative_budget_cannot_restart_on_restore(self):
        head = StemHead(4, "encoder-v1")
        head.fit((self.row,), training_cut(), revoked=set(), steps=4, pair_ceiling=8)
        head = restore(head)
        with self.assertRaises(ValueError):
            head.fit(
                (self.row,), training_cut(), revoked=set(), steps=4, pair_ceiling=8
            )
        self.assertTrue(head.quarantined)

    def test_validate_entire_training_set_before_mutation(self):
        for bad in (
            replace(self.row, features=features("test", "held-out")),
            replace(self.row, positive_indices=(5,)),
            replace(self.row, positive_indices=(True,)),
        ):
            head = StemHead(4, "encoder-v1")
            before = head.export()
            with self.assertRaises(ValueError):
                head.fit((self.row, bad), training_cut(), revoked=set())
            self.assertEqual(head.export(), before)

    def test_duplicate_training_row_rejected(self):
        head = StemHead(4, "encoder-v1")
        with self.assertRaises(ValueError):
            head.fit((self.row, self.row), training_cut(), revoked=set())

    def test_feature_identity_and_finiteness(self):
        head = StemHead(4, "encoder-v1")
        for batch in (
            features(identity="encoder-v2"),
            replace(features(), paired=torch.full((2, 4), float("nan"))),
            replace(features(), paired=torch.zeros(2, 3)),
            replace(features(), pool_digest=""),
        ):
            with self.assertRaises(ValueError):
                head.decide(batch, revoked=set())

    def test_revoked_training_root_blocks_old_snapshot(self):
        head = StemHead(4, "encoder-v1")
        head.fit((self.row,), training_cut(), revoked=set(), steps=4)
        blob = head.export()
        with self.assertRaises(ValueError):
            StemHead.restore(
                blob,
                expected_sha256=sha256(blob),
                encoder_identity="encoder-v1",
                allowed_roots={"root"},
                revoked={"root"},
            )
        with self.assertRaises(ValueError):
            head.decide(features("new", "other"), revoked={"root"})

    def test_no_cross_encoder_artifact_reuse(self):
        blob = StemHead(4, "encoder-v1").export()
        with self.assertRaises(ValueError):
            StemHead.restore(
                blob,
                expected_sha256=sha256(blob),
                encoder_identity="encoder-v2",
                allowed_roots=set(),
                revoked=set(),
            )

    def test_hash_shape_and_false_acceptance_are_enforced(self):
        head = StemHead(4, "encoder-v1")
        original = json.loads(head.export())
        for field, value in (
            ("production_accepted", True),
            ("steps", -1),
            ("state", {}),
            ("roots", ["unauthorized"]),
        ):
            obj = dict(original)
            obj[field] = value
            blob = json.dumps(obj).encode()
            with self.assertRaises(ValueError):
                StemHead.restore(
                    blob,
                    expected_sha256=sha256(blob),
                    encoder_identity="encoder-v1",
                    allowed_roots=set(),
                    revoked=set(),
                )

    def test_duplicate_json_key_rejected(self):
        blob = b'{"schema":1,"schema":2}'
        with self.assertRaises(ValueError):
            StemHead.restore(
                blob,
                expected_sha256=sha256(blob),
                encoder_identity="encoder-v1",
                allowed_roots=set(),
                revoked=set(),
            )

    def test_empty_pool_abstains(self):
        batch = replace(
            features(),
            candidate_ids=(),
            paired=torch.empty(0, 4),
            frozen_scores=torch.empty(0),
        )
        self.assertEqual(
            StemHead(4, "encoder-v1").decide(batch, revoked=set()), (None, [0.0])
        )

    def test_feature_copy_does_not_mutate_source(self):
        original = features()
        clone_features(original).paired.fill_(0)
        self.assertNotEqual(original.paired.abs().sum().item(), 0)

    def test_artifact_only_fresh_process(self):
        head = StemHead(4, "encoder-v1")
        head.fit((self.row,), training_cut(), revoked=set(), steps=8)
        code = (
            "import sys; from stem_cell import StemHead,sha256; "
            "b=sys.stdin.buffer.read(); "
            "h=StemHead.restore(b,expected_sha256=sha256(b),encoder_identity='encoder-v1',"
            "allowed_roots={'root'},revoked=set()); print(sha256(h.export()))"
        )
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent))
        result = subprocess.run(
            [sys.executable, "-c", code],
            input=head.export(),
            capture_output=True,
            check=True,
            timeout=45,
            env=env,
        )
        self.assertEqual(result.stdout.decode().strip(), sha256(head.export()))

    def test_route_uses_only_observable_text(self):
        self.assertEqual(route_text("When was the last meeting?"), "temporal")
        self.assertEqual(route_text("What is the project name?"), "general")


@dataclass(frozen=True)
class Query:
    identity: str = "train"
    content: str = "query"
    scope: str = "scope"


class Window:
    def __init__(self, name):
        self.name = name

    def identity(self):
        return self.name


class Pool:
    windows = (Window("a"), Window("b"))

    def seal(self):
        return "pool"

    def revalidate(self, query, revoked):
        if query.scope != "scope" or "root" in revoked:
            raise ValueError("denied current source scope")


class Encoder:
    identity = "encoder-v1"
    dimension = 4

    def __init__(self):
        self.calls = 0

    def encode(self, query, family, pool, *, revoked):
        self.calls += 1
        return replace(
            features(query.identity, identity=self.identity), family=family
        ), {"seconds": 0.01}


class CacheTests(unittest.TestCase):
    def test_many_heads_share_one_encoding_without_writable_aliases(self):
        encoder = Encoder()
        cache = SharedFeatureCache(encoder)
        first, _ = cache.encode(Query(), "family", Pool(), revoked=set())
        first.paired.fill_(0)
        for _ in range(8):
            batch, receipt = cache.encode(Query(), "family", Pool(), revoked=set())
            self.assertEqual(batch.paired.tolist(), features().paired.tolist())
            self.assertTrue(receipt["cache_hit"])
            self.assertEqual(receipt["incremental_encoder_seconds"], 0)
        self.assertEqual(encoder.calls, 1)

    def test_cache_hit_never_bypasses_revocation_or_scope(self):
        cache = SharedFeatureCache(Encoder())
        cache.encode(Query(), "family", Pool(), revoked=set())
        for query, revoked in ((Query(), {"root"}), (Query(scope="other"), set())):
            with self.assertRaises(ValueError):
                cache.encode(query, "family", Pool(), revoked=revoked)

    def test_same_dimension_new_model_is_cache_miss(self):
        encoder = Encoder()
        cache = SharedFeatureCache(encoder)
        cache.encode(Query(), "family", Pool(), revoked=set())
        encoder.identity = "encoder-v2"
        batch, receipt = cache.encode(Query(), "family", Pool(), revoked=set())
        self.assertFalse(receipt["cache_hit"])
        self.assertEqual(batch.encoder_identity, "encoder-v2")
        self.assertEqual(encoder.calls, 2)

    def test_cache_hard_bound_and_query_change(self):
        encoder = Encoder()
        cache = SharedFeatureCache(encoder, maximum_bytes=1)
        cache.encode(Query(), "family", Pool(), revoked=set())
        cache.encode(Query(content="different"), "family", Pool(), revoked=set())
        self.assertEqual(cache.bytes, 0)
        self.assertEqual(encoder.calls, 2)


if __name__ == "__main__":
    unittest.main()
