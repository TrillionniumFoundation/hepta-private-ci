"""Deterministic mechanism tests; no pretrained encoders or capability claims."""

import hashlib
import struct
import unittest
from dataclasses import replace

from multimodal_bridge import (
    BoundedStemCache, ContractError, FeatureSnapshot, FrozenLinearBridge,
    ModalityFeature, SharedStemComposer,
)


def pin(label):
    return hashlib.sha256(label.encode()).hexdigest()


def aligned():
    # Both frozen sources represent the same toy class after a pinned projection.
    text = ModalityFeature.from_vector("text", pin("text-source"), pin("text-encoder"), (1.0, 0.0))
    image = ModalityFeature.from_vector("image", pin("image-source"), pin("image-encoder"), (0.0, 1.0))
    return image, text  # canonical lexical ordering


class MultimodalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.image_bridge = FrozenLinearBridge("image", ((0.0, 1.0), (1.0, 0.0)), (0.0, 0.0))
        self.text_bridge = FrozenLinearBridge("text", ((1.0, 0.0), (0.0, 1.0)), (0.0, 0.0))
        self.composer = SharedStemComposer(pin("stem"), pin("preprocessor"),
                                           (self.image_bridge, self.text_bridge))
        self.detail = aligned()
        self.key = self.composer.key("scope_A", 7, pin("fence_7"), self.detail)

    def snapshot(self):
        return self.composer.compose(self.key, self.detail)

    def test_cross_modal_projected_alignment_is_mechanism_only(self):
        snap = self.snapshot()
        self.assertEqual(snap.common_le_f32, struct.pack("<ff", 1.0, 0.0))
        self.assertEqual(snap.neuron_q24(), (1 << 24, 0))
        self.assertEqual(tuple(p.modality for p in snap.detail), ("image", "text"))
        self.assertNotEqual(self.image_bridge.sha256, self.text_bridge.sha256)

    def test_missing_modality_is_distinct_key_and_no_automatic_fallback(self):
        one = (self.detail[1],)
        key = self.composer.key("scope_A", 7, pin("fence_7"), one)
        self.assertNotEqual(key.input_sha256, self.key.input_sha256)
        self.assertEqual(self.composer.compose(key, one).neuron_q24(), (1 << 24, 0))
        with self.assertRaises(ContractError):
            self.composer.compose(self.key, one)

    def test_swapped_bridge_is_not_the_same_semantic_alignment(self):
        wrong = SharedStemComposer(pin("stem"), pin("preprocessor"),
                                   (FrozenLinearBridge(
                                       "image", ((1.0, 0.0), (0.0, 1.0)), (0.0, 0.0)), self.text_bridge))
        key = wrong.key("scope_A", 7, pin("fence_7"), self.detail)
        self.assertNotEqual(key.bridge_sha256, self.key.bridge_sha256)
        self.assertNotEqual(wrong.compose(key, self.detail).common_le_f32,
                            self.snapshot().common_le_f32)

    def test_scope_generation_fence_and_preprocessor_bind_all_outputs(self):
        # New scope/fence is valid ONLY as a distinct key; host final-use must
        # separately authorize it. Frozen preprocessor and source are not mutable.
        for field, value in (("scope", "scope_B"), ("generation", 8),
                             ("fence_sha256", pin("other-fence"))):
            changed = replace(self.key, **{field: value})
            with self.subTest(field=field):
                fresh = self.composer.compose(changed, self.detail)
                self.assertNotEqual(fresh.content_sha256, self.snapshot().content_sha256)
        with self.assertRaises(ContractError):
            self.composer.compose(replace(self.key,
                preprocessor_sha256=pin("other-preprocessor")), self.detail)
        changed = replace(self.detail[0], encoder_sha256=pin("new-image-encoder"))
        with self.assertRaises(ContractError):
            self.composer.compose(self.key, (changed, self.detail[1]))

    def test_projection_tamper_rejected(self):
        object.__setattr__(self.image_bridge, "bias", (1.0, 0.0))
        with self.assertRaises(ContractError):
            self.composer.compose(self.key, self.detail)

    def test_invalid_input_and_tensor_domain_fail_closed(self):
        with self.assertRaises(ContractError):
            ModalityFeature.from_vector("image", pin("x"), pin("y"), (float("nan"),))
        with self.assertRaises(ContractError):
            ModalityFeature("audio", pin("x"), pin("y"), struct.pack("<f", float("inf")))
        with self.assertRaises(ContractError):
            ModalityFeature.from_vector("video", pin("x"), pin("y"), (8.001,))
        with self.assertRaises(ContractError):
            ModalityFeature.from_vector("video", "0" * 64, pin("y"), (0.0,))
        with self.assertRaises(ContractError):
            self.composer.key("wrong scope", 7, pin("fence"), self.detail)
        with self.assertRaises(ContractError):
            FrozenLinearBridge("text", ((1.0, 0.0),), (0.0, 1.0))
        with self.assertRaises(ContractError):
            self.composer.key("scope_A", 7, pin("fence_7"), tuple(reversed(self.detail)))

    def test_snapshot_sidecars_are_immutable_and_sealed(self):
        snapshot = self.snapshot()
        view = snapshot.shared_view()
        self.assertTrue(view.readonly)
        self.assertIs(view.obj, snapshot.common_le_f32)
        with self.assertRaises(TypeError):
            view[0] = 42
        object.__setattr__(snapshot, "common_le_f32", struct.pack("<ff", 0.0, 1.0))
        with self.assertRaises(ContractError):
            snapshot.verify()

    def test_round_ties_even_and_negative_zero(self):
        feature = ModalityFeature.from_vector("text", pin("x"), pin("y"),
                                               (2**-25, -3 * 2**-25))
        one = SharedStemComposer(pin("stem"), pin("preprocessor"),
                                 (FrozenLinearBridge("text", ((1.0, 0.0), (0.0, 1.0)),
                                                     (0.0, 0.0)),))
        key = one.key("scope_A", 7, pin("fence_7"), (feature,))
        self.assertEqual(one.compose(key, (feature,)).neuron_q24(), (0, -2))

    def test_budget_bounded_and_duplicate_projection_rejected(self):
        with self.assertRaises(ContractError):
            SharedStemComposer(pin("s"), pin("p"), (self.text_bridge, self.text_bridge))
        with self.assertRaises(ContractError):
            ModalityFeature.from_vector("text", pin("x"), pin("y"), (0.0,) * 4097)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MultimodalBridgeTests()
        self.bridge.setUp()
        self.snapshot = self.bridge.snapshot()
        self.key = self.snapshot.key

    def test_four_thousand_cells_share_one_immutable_snapshot(self):
        cache = BoundedStemCache(4096)
        count = [0]
        def produce():
            count[0] += 1
            return self.snapshot
        def final(key):
            return key.scope == "scope_A" and key.generation == 7
        values = [cache.get(self.key, produce, final) for _ in range(4096)]
        self.assertTrue(all(x is values[0] for x in values))
        self.assertTrue(all(x.shared_view().obj is values[0].common_le_f32 for x in values))
        self.assertEqual((count[0], cache.producer_calls, cache.hits), (1, 1, 4095))
        self.assertEqual(cache.bytes, self.snapshot.charged_bytes)

    def test_cache_never_reuses_across_scope_or_generation(self):
        cache = BoundedStemCache(4096)
        cache.get(self.key, lambda: self.snapshot, lambda _: True)
        for field, value in (("scope", "scope_B"), ("generation", 8),
                             ("fence_sha256", pin("new-fence"))):
            alternate = replace(self.key, **{field: value})
            with self.subTest(field=field), self.assertRaises(ContractError):
                cache.get(alternate, lambda: self.snapshot, lambda _: True)
        self.assertEqual(cache.hits, 0)

    def test_final_use_is_rechecked_even_on_hits(self):
        cache = BoundedStemCache(4096)
        access = [True]
        calls = [0]
        def final(_):
            calls[0] += 1
            return access[0]
        cache.get(self.key, lambda: self.snapshot, final)
        access[0] = False
        with self.assertRaises(ContractError):
            cache.get(self.key, lambda: self.snapshot, final)
        access[0] = True
        def revoke_after_first_check(_):
            calls[0] += 1
            return calls[0] % 2 == 0
        with self.assertRaises(ContractError):
            cache.get(self.key, lambda: self.snapshot, revoke_after_first_check)
        self.assertEqual(cache.producer_calls, 1)

    def test_tampering_with_retained_snapshot_blocks_reuse(self):
        cache = BoundedStemCache(4096)
        cache.get(self.key, lambda: self.snapshot, lambda _: True)
        object.__setattr__(self.snapshot, "common_le_f32", struct.pack("<ff", 0.0, 1.0))
        with self.assertRaises(ContractError):
            cache.get(self.key, lambda: self.snapshot, lambda _: True)

    def test_bounded_eviction(self):
        capacity = self.snapshot.charged_bytes
        cache = BoundedStemCache(capacity)
        cache.get(self.key, lambda: self.snapshot, lambda _: True)
        another = replace(self.key, scope="scope_B")
        second = FeatureSnapshot(another, self.snapshot.common_le_f32, self.snapshot.detail)
        cache.get(another, lambda: second, lambda _: True)
        self.assertEqual((len(cache.items), cache.evictions, cache.bytes), (1, 1, capacity))
        cache.clear()
        self.assertEqual(cache.bytes, 0)


if __name__ == "__main__":
    unittest.main()
