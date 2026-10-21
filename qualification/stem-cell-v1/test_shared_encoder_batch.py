import unittest
import importlib.util
from dataclasses import replace
from types import SimpleNamespace

from shared_encoder_batch import (
    FeatureRequest, FrozenFeature, FrozenLocalHfBackend, SharedStemEngine, digest_text,
)


D = lambda c: c * 64


class FakeBackend:
    simulated = True
    encoder_digest = D("a")
    preprocessor_digest = D("b")
    runtime_digest = D("c")

    def __init__(self, width=384, fail=None):
        self.calls = []
        self.width = width
        self.fail = fail

    def encode_many(self, texts, mode):
        self.calls.append((tuple(texts), mode))
        if self.fail == "wrong_count":
            return []
        if self.fail == "invalid_number":
            return [None] * len(texts)
        return [FrozenFeature.from_values([len(t) / 100.0] * self.width, 2, mode) for t in texts]


def req(number=1, text="identical input", scope="1", generation=1,
        frontier="2", encoder="a", preprocessor="b", runtime="c", mode="mean"):
    return FeatureRequest(
        f"request.{number}", f"cell.{number}", D(scope), generation,
        D(frontier), D(encoder), D(preprocessor), D(runtime), digest_text(text), text, mode,
    )


class BatchTests(unittest.TestCase):
    def test_one_encoder_invocation_shared_by_multiple_cells_in_one_scope(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        result = engine.run([req(1), req(2), req(3)])
        self.assertEqual((result.distinct_inputs, result.backend_calls, result.backend_batch_widths), (1, 1, (1,)))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len({r.feature_digest for r in result.receipts}), 1)
        self.assertFalse(result.production_authorized)
        self.assertTrue(result.simulated)
        self.assertTrue(all(r.native_q24_compatible_width for r in result.receipts))
        self.assertEqual(result.cache_hits, 0)
        self.assertEqual(engine.run([req(4)]).cache_hits, 1)
        self.assertEqual(len(backend.calls), 1)

    def test_distinct_inputs_are_one_backend_batch_without_sequential_calls(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        x = engine.run([req(1, "one"), req(2, "four"), req(3, "three")])
        self.assertEqual((x.distinct_inputs, x.backend_calls, x.backend_batch_widths), (3, 1, (3,)))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len({r.feature_digest for r in x.receipts}), 3)
        self.assertGreaterEqual(x.elapsed_ns, 0)

    def test_scope_mixing_denied_without_ever_calling_backend(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, scope="3")])
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, generation=2)])
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, frontier="4")])
        with self.assertRaisesRegex(ValueError, "mixed scope"):
            engine.run([req(1), req(2, mode="landmark8")])
        self.assertEqual(backend.calls, [])

    def test_distinct_scope_generation_and_revocation_frontier_cache_keys(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        engine.run([req(1)])
        engine.run([req(2, scope="3")])
        engine.run([req(3, generation=2)])
        engine.run([req(4, frontier="4")])
        self.assertEqual(len(backend.calls), 4)
        engine.cache.invalidate_generation(D("1"), 2)
        engine.cache.invalidate_scope(D("3"))
        self.assertEqual(engine.run([req(5, generation=2)]).cache_hits, 1)
        self.assertEqual(engine.run([req(6)]).cache_hits, 0)

    def test_revoked_or_changed_weights_and_malformed_requests_rejected(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        for case in [req(1, encoder="d"), req(1, preprocessor="d"), req(1, runtime="d")]:
            with self.assertRaises(ValueError):
                engine.run([case])
        invalid_digest = req(7).__dict__.copy()
        invalid_digest["input_digest"] = D("f")
        with self.assertRaisesRegex(ValueError, "input content digest mismatch"):
            engine.run([FeatureRequest(**invalid_digest)])
        with self.assertRaisesRegex(ValueError, "duplicate request_id"):
            engine.run([req(1), req(1)])
        self.assertEqual(backend.calls, [])

    def test_backend_wrong_count_or_nonfinite_refused_without_cache_poison(self):
        for kind in ("wrong_count", "invalid_number"):
            backend = FakeBackend(fail=kind)
            engine = SharedStemEngine(backend)
            with self.assertRaises(ValueError):
                engine.run([req(1)])
            self.assertEqual(engine.cache.size_bytes, 0)

    def test_backend_cannot_cache_forged_float32_or_wrong_feature_digest(self):
        base = FrozenFeature.from_values([0.25, 0.5], 2, "mean")
        forged = (
            replace(base, feature_digest=D("f")),
            replace(base, values=(0.25, float("nan"))),
            replace(base, values=(0.250000001, 0.5)),
            replace(base, values=[0.25, 0.5]),
            replace(base, token_count=True),
            replace(base, token_count=8193),
        )

        class InjectedBackend(FakeBackend):
            def __init__(self, bad):
                super().__init__(width=2)
                self.bad = bad

            def encode_many(self, texts, mode):
                good = super().encode_many(texts, mode)
                return [good[0], self.bad]

        for corrupted in forged:
            backend = InjectedBackend(corrupted)
            engine = SharedStemEngine(backend, max_cache_bytes=64 * 1024)
            with self.assertRaisesRegex(
                    ValueError, "feature|encoded"):
                engine.run([req(1, "safe input"), req(2, "bad input")])
            self.assertEqual(engine.cache.size_bytes, 0)
            self.assertEqual(len(engine.cache._entries), 0)
            self.assertEqual(len(backend.calls), 1)
            # After rejecting the whole backend response, a correct retry
            # must re-execute both inputs rather than reuse any partial cache.
            valid_backend = FakeBackend(width=2)
            engine.backend = valid_backend
            result = engine.run([req(3, "safe input"), req(4, "bad input")])
            self.assertEqual(result.backend_batch_widths, (2,))
            self.assertEqual(result.cache_hits, 0)
            self.assertEqual(len(valid_backend.calls), 1)

    def test_cache_put_validates_before_overwriting_a_good_feature(self):
        from shared_encoder_batch import ScopedFeatureCache

        cache = ScopedFeatureCache(64 * 1024)
        key = req(1, "signed-view").cache_key()
        good = FrozenFeature.from_values([0.25, -0.5], 2, "mean")
        cache.put(key, good)
        original_size = cache.size_bytes
        for bogus in (
                replace(good, feature_digest=D("b")),
                replace(good, values=(0.25, float("inf"))),
                replace(good, token_count=0),
                replace(good, values=(0.2500000001, -0.5))):
            with self.assertRaisesRegex(ValueError, "feature|encoded"):
                cache.put(key, bogus)
            self.assertIs(cache.get(key), good)
            self.assertEqual(cache.size_bytes, original_size)
        different = FrozenFeature.from_values([0.25, 0.75], 2, "mean")
        with self.assertRaisesRegex(ValueError, "identical scoped cache key"):
            cache.put(key, different)
        self.assertIs(cache.get(key), good)
        self.assertEqual(cache.size_bytes, original_size)

    def test_cache_batch_conflict_is_prevalidated_before_first_member_insert(self):
        from shared_encoder_batch import ScopedFeatureCache

        cache = ScopedFeatureCache(128 * 1024)
        alpha = req(1, "alpha").cache_key()
        beta = req(2, "beta").cache_key()
        verified_alpha = FrozenFeature.from_values([0.25] * 8, 2, "mean")
        verified_beta = FrozenFeature.from_values([0.5] * 8, 2, "mean")
        prior_beta = FrozenFeature.from_values([0.75] * 8, 2, "mean")
        cache.put(beta, prior_beta)
        before = (cache.size_bytes, cache.evictions, tuple(cache._entries))
        with self.assertRaisesRegex(ValueError, "different feature content"):
            cache.put_many(((alpha, verified_alpha), (beta, verified_beta)))
        self.assertEqual(
            (cache.size_bytes, cache.evictions, tuple(cache._entries)), before)
        self.assertIsNone(cache.get(alpha))
        self.assertIs(cache.get(beta), prior_beta)

    def test_reentrant_backend_cache_conflict_cannot_publish_first_new_feature(self):
        # A backend callback may complete with valid tensor shapes after a
        # second owner introduced a conflicting key between preflight and the
        # cache publication boundary. Reject the entire new insertion batch.
        class ReentrantBackend(FakeBackend):
            def encode_many(self, texts, mode):
                result = super().encode_many(texts, mode)
                self.inject_into.put(
                    req(2, "beta").cache_key(),
                    FrozenFeature.from_values([0.75] * self.width, 2, mode))
                return result

        backend = ReentrantBackend(width=8)
        engine = SharedStemEngine(backend, max_cache_bytes=128 * 1024)
        backend.inject_into = engine.cache
        with self.assertRaisesRegex(ValueError, "different feature content"):
            engine.run([req(1, "alpha"), req(2, "beta")])
        self.assertIsNone(engine.cache.get(req(1, "alpha").cache_key()))
        self.assertIsNotNone(engine.cache.get(req(2, "beta").cache_key()))
        self.assertEqual(len(backend.calls), 1)
        # A rejected invocation did not silently publish the first result.
        # A later retry must recompute alpha rather than claim a cache hit.
        backend.inject_into = type("NoopCache", (), {"put": lambda self, *_: None})()
        result = engine.run([req(3, "alpha")])
        self.assertEqual(result.backend_calls, 1)
        self.assertEqual(result.cache_hits, 0)


    def test_feature_tokens_and_scalar_type_are_strictly_bounded(self):
        for tokens in (True, -1, 0, 8193):
            with self.assertRaisesRegex(ValueError, "shape"):
                FrozenFeature.from_values([0.25], tokens, "mean")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            FrozenFeature.from_values([True], 2, "mean")
        with self.assertRaisesRegex(ValueError, "representation"):
            FrozenFeature.from_values([0.25], 2, 1)
        legitimate = FrozenFeature.from_values([0.25], 8192, "mean")
        legitimate.verify_integrity()

    def test_boxed_python_float_cache_does_not_claim_raw_f32_budget(self):
        from shared_encoder_batch import ScopedFeatureCache

        key = req(1, "cache-test").cache_key()
        value = FrozenFeature.from_values([0.25] * 768, 20, "mean")
        payload_bytes = 768 * 4
        cache = ScopedFeatureCache(payload_bytes)
        cache.put(key, value)
        self.assertIsNone(cache.get(key))
        self.assertEqual(cache.size_bytes, 0)
        # Admission to a sufficiently large cache must charge key, object,
        # Python float storage and a conservative bookkeeping allowance.
        cache = ScopedFeatureCache(128 * 1024)
        cache.put(key, value)
        self.assertIs(cache.get(key), value)
        self.assertGreater(cache.size_bytes, payload_bytes)
        self.assertLessEqual(cache.size_bytes, cache.maximum_bytes)
        cache.invalidate_scope(req(1).scope_digest)
        self.assertEqual(cache.size_bytes, 0)

    def test_cache_eviction_is_bounded(self):
        backend = FakeBackend(width=8)
        engine = SharedStemEngine(backend, max_cache_bytes=3000)
        engine.run([req(1, "alpha")])
        engine.run([req(2, "beta")])
        self.assertGreater(engine.cache.size_bytes, 8 * 4)
        self.assertLessEqual(engine.cache.size_bytes, 3000)
        self.assertGreaterEqual(engine.cache.evictions, 1)
        engine.run([req(3, "alpha")])
        self.assertEqual(len(backend.calls), 3)

    def test_backend_identity_change_during_encode_rejects_cache_publication(self):
        # A mutable backend may be hot-swapped after request preflight, yet
        # return well-formed features from a different checkpoint. Reject the
        # entire batch rather than caching those vectors under the old model.
        class ChangingBackend(FakeBackend):
            def encode_many(self, texts, mode):
                values = super().encode_many(texts, mode)
                self.encoder_digest = D("e")
                return values

        backend = ChangingBackend(width=8)
        engine = SharedStemEngine(backend)
        with self.assertRaisesRegex(ValueError, "backend identity changed"):
            engine.run([req(1, "state A"), req(2, "state B")])
        self.assertEqual(engine.cache.size_bytes, 0)
        self.assertEqual(len(engine.cache._entries), 0)
        # Even the old checkpoint's cached results must never be relabeled to
        # the new backend tuple by merely submitting a new request.
        with self.assertRaisesRegex(ValueError, "unselected or changed"):
            engine.run([req(3, "state A")])

    def test_cache_hit_evicted_by_same_batch_miss_remains_valid(self):
        # One entry fits, but inserting a new miss necessarily evicts the
        # already-hit feature before the batch assembles its receipts. The
        # immutable hit must remain readable for this invocation only.
        from cache_accounting import estimated_python_cache_entry_bytes

        for repeated_hits in (1, 2):
            with self.subTest(repeated_hits=repeated_hits):
                backend = FakeBackend(width=8)
                old = req(1, "cached-alpha")
                new = req(2, "uncached-beta")
                old_feature = FrozenFeature.from_values(
                    [len(old.text) / 100.0] * 8, 2, "mean")
                new_feature = FrozenFeature.from_values(
                    [len(new.text) / 100.0] * 8, 2, "mean")
                limit = max(
                    estimated_python_cache_entry_bytes(
                        old.cache_key(), old_feature, old_feature.values),
                    estimated_python_cache_entry_bytes(
                        new.cache_key(), new_feature, new_feature.values),
                )
                engine = SharedStemEngine(backend, max_cache_bytes=limit)
                engine.run([old])
                self.assertIsNotNone(engine.cache.get(old.cache_key()))

                joined = [req(3, "cached-alpha"), new]
                if repeated_hits == 2:
                    joined.append(req(4, "cached-alpha"))
                observed, features = engine.run(joined, return_features=True)
                self.assertEqual(observed.cache_hits, repeated_hits)
                self.assertEqual(observed.distinct_inputs, 1)
                self.assertEqual(observed.backend_batch_widths, (1,))
                self.assertEqual(len(backend.calls), 2)
                self.assertEqual(len(features), len(joined))
                self.assertEqual(features[0].feature_digest, old_feature.feature_digest)
                self.assertEqual(features[1].feature_digest, new_feature.feature_digest)
                if repeated_hits == 2:
                    self.assertEqual(features[2].feature_digest, old_feature.feature_digest)
                # Capacity is real: the hit survives only in this invocation's
                # immutable ref, not as an unbounded resurrected cache entry.
                self.assertIsNone(engine.cache.get(old.cache_key()))
                self.assertLessEqual(engine.cache.size_bytes, limit)
                self.assertEqual(
                    [r.feature_digest for r in observed.receipts],
                    [f.feature_digest for f in features],
                )

    def test_large_vector_is_never_silently_represented_as_native_512(self):
        backend = FakeBackend(width=768)
        engine = SharedStemEngine(backend)
        result = engine.run([req(1)])
        self.assertEqual(result.receipts[0].feature_width, 768)
        self.assertFalse(result.receipts[0].native_q24_compatible_width)

    def test_4096_logical_cells_are_bounded_batches_not_4096_encoder_invocations(self):
        backend = FakeBackend(width=8)
        engine = SharedStemEngine(backend, max_cache_bytes=4096)
        all_receipts = []
        counts = []
        for base in range(0, 4096, 32):
            observation = engine.run([req(base + i + 1) for i in range(32)])
            all_receipts.extend(observation.receipts)
            counts.append(observation.backend_calls)
        self.assertEqual(len(all_receipts), 4096)
        self.assertEqual(sum(counts), 1)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(len({r.feature_digest for r in all_receipts}), 1)
        self.assertTrue(all(r.status == "shadow_only_not_authorized" for r in all_receipts))

    def test_frozen_feature_digest_is_float32_canonical(self):
        f = FrozenFeature.from_values([0.1, 0.2], 4, "mean")
        self.assertEqual(len(f.feature_digest), 64)
        self.assertEqual(f.values[0], 0.10000000149011612)
        with self.assertRaises(ValueError):
            FrozenFeature.from_values([float("nan")], 1, "mean")

    def test_no_raw_text_in_receipts_or_cache_values(self):
        phrase = "private to one scope: quince"
        engine = SharedStemEngine(FakeBackend())
        out = engine.run([req(1, text=phrase)])
        self.assertNotIn(phrase, repr(out))
        self.assertNotIn(phrase, repr(engine.cache._entries))

    def test_runtime_digest_is_part_of_cache_and_batch_identity(self):
        backend = FakeBackend()
        engine = SharedStemEngine(backend)
        a = engine.run([req(1)])
        with self.assertRaisesRegex(ValueError, "unselected or changed model"):
            engine.run([req(2, runtime="d")])
        b = engine.run([req(3)])
        self.assertNotEqual(a.batch_identity, b.batch_identity)
        self.assertEqual(b.cache_hits, 1)


    def test_optional_ephemeral_values_preserve_no_cache_and_receipt_only_api(self):
        engine = SharedStemEngine(FakeBackend(width=768), max_cache_bytes=0)
        standard = engine.run([req(1, "one")])
        self.assertFalse(hasattr(standard, "features"))
        observation, features = engine.run([
            req(2, "one"), req(3, "three"), req(4, "one")
        ], return_features=True)
        self.assertEqual(len(features), 3)
        self.assertEqual(features[0].feature_digest, features[2].feature_digest)
        self.assertEqual(observation.backend_batch_widths, (2,))
        self.assertEqual(engine.cache.size_bytes, 0)
        self.assertTrue(all(r.status == "shadow_only_not_authorized" for r in observation.receipts))

    def test_real_shared_engine_projection_binds_full_768_without_truncation(self):
        from stem_projection import Q, LowRankProjectionQ24, ProjectedStemEngine
        backend = FakeBackend(width=768)
        encoder = SharedStemEngine(backend, max_cache_bytes=0)
        a = [0] * 768
        a[-1] = Q
        projection = LowRankProjectionQ24(
            D("a"), D("b"), D("c"), D("d"), "mean", 768, 2, 1,
            tuple(a), (Q, 0), (0, 0),
        )
        bridge = ProjectedStemEngine(encoder, projection, maximum_projection_cache_bytes=4096)
        result = bridge.run([req(1, "one"), req(2, "one")])
        self.assertEqual(result.encoder_observation.backend_batch_widths, (1,))
        self.assertEqual(len(result.refs), 2)
        self.assertEqual(result.refs[0].vector_q24[0], result.refs[1].vector_q24[0])
        self.assertGreater(result.refs[0].vector_q24[0], 0)
        self.assertFalse(result.production_authorized)
        self.assertEqual(bridge.run([req(3, "one")]).projection_cache_hits, 1)


@unittest.skipUnless(importlib.util.find_spec("torch") is not None, "torch optional")
class RealTorchBatchPathTests(unittest.TestCase):
    def test_local_hf_checkpoint_requires_all_materialized_safetensors(self):
        import sys
        import tempfile
        from pathlib import Path
        from types import ModuleType
        import torch
        from model_runner import snapshot_digest

        class FakeEncoder(torch.nn.Module):
            def __init__(self, value):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.tensor([value]))

        class FakeReader:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def keys(self):
                return ["weight"]

            def get_tensor(self, key):
                if key != "weight":
                    raise ValueError("wrong checkpoint tensor")
                return torch.tensor([0.5])

        clean = {"missing_keys": [], "unexpected_keys": [],
                 "mismatched_keys": [], "error_msgs": []}
        state = {"model_weight": 0.5, "report": clean, "give_report": True,
                 "tamper_during_load": False}

        def local_model(*_args, **kwargs):
            self.assertTrue(kwargs["local_files_only"])
            self.assertFalse(kwargs["trust_remote_code"])
            self.assertTrue(kwargs["use_safetensors"])
            self.assertTrue(kwargs["output_loading_info"])
            obj = FakeEncoder(state["model_weight"])
            if state["tamper_during_load"]:
                (folder / "config.json").write_text('{"changed_during_load": true}')
            if state["give_report"]:
                return obj, state["report"]
            return obj

        fake_transformers = ModuleType("transformers")
        fake_transformers.AutoTokenizer = SimpleNamespace(
            from_pretrained=lambda *a, **kw: object())
        fake_transformers.AutoModel = SimpleNamespace(from_pretrained=local_model)
        fake_safetensors = ModuleType("safetensors")
        fake_safetensors.safe_open = lambda *_a, **_kw: FakeReader()
        replacements = {
            "transformers": fake_transformers,
            "safetensors": fake_safetensors,
        }
        missing = object()
        old = {key: sys.modules.get(key, missing) for key in replacements}
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "config.json").write_text('{"synthetic":true}')
            (folder / "model.safetensors").write_bytes(
                b"fake tensor bytes not a real pretrained model")
            params = dict(
                expected_snapshot_digest=snapshot_digest(folder),
                preprocessor_digest=D("b"), runtime_digest=D("c"),
                max_tokens=64, device="cpu",
            )
            try:
                sys.modules.update(replacements)
                backend = FrozenLocalHfBackend(folder, **params)
                self.assertTrue(backend.verified_loading["complete"])
                self.assertTrue(backend.verified_materialization["complete"])
                self.assertEqual(backend.verified_materialization["tensor_count"], 1)
                self.assertFalse(backend.model.weight.requires_grad)
                state["report"] = {**clean, "missing_keys": ["weight"]}
                with self.assertRaisesRegex(ValueError, "partially initialized"):
                    FrozenLocalHfBackend(folder, **params)
                state["report"] = clean
                state["model_weight"] = 0.75
                with self.assertRaisesRegex(ValueError, "differs from pinned"):
                    FrozenLocalHfBackend(folder, **params)
                state["model_weight"] = 0.5
                state["give_report"] = False
                with self.assertRaisesRegex(ValueError, "complete HF loading report"):
                    FrozenLocalHfBackend(folder, **params)
                state["give_report"] = True
                state["tamper_during_load"] = True
                with self.assertRaisesRegex(ValueError, "snapshot changed during"):
                    FrozenLocalHfBackend(folder, **params)
            finally:
                for key, value in old.items():
                    if value is missing:
                        sys.modules.pop(key, None)
                    else:
                        sys.modules[key] = value

    def make_backend(self, *, left_padding=False):
        import torch

        class SyntheticTokenizer:
            def __call__(self, texts, *, return_tensors, padding, truncation):
                assert return_tensors == "pt" and padding and not truncation
                rows = [[int(v) for v in text.split()] for text in texts]
                width = max(len(row) for row in rows)
                if left_padding:
                    ids = [[0] * (width - len(row)) + row for row in rows]
                    masks = [[0] * (width - len(row)) + [1] * len(row) for row in rows]
                else:
                    ids = [row + [0] * (width - len(row)) for row in rows]
                    masks = [[1] * len(row) + [0] * (width - len(row)) for row in rows]
                return {
                    "input_ids": torch.tensor(ids),
                    "attention_mask": torch.tensor(masks),
                }

        class SyntheticModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.lookup = torch.nn.Embedding(32, 4)
                self.calls = 0

            def forward(self, input_ids, attention_mask):
                self.calls += 1
                return SimpleNamespace(last_hidden_state=self.lookup(input_ids))

        fake = FrozenLocalHfBackend.__new__(FrozenLocalHfBackend)
        fake.encoder_digest = D("a")
        fake.preprocessor_digest = D("b")
        fake.runtime_digest = D("c")
        fake.torch = torch
        fake.tokenizer = SyntheticTokenizer()
        fake.model = SyntheticModel().eval()
        fake.device = "cpu"
        fake.max_tokens = 8
        fake.invocations = 0
        # No snapshot exists here: injected weights are synthetic test fixtures.
        fake.simulated = True
        return fake

    def test_padded_32_request_resource_ceiling_refuses_before_forward(self):
        # 32 separate cases each meet the 8192-token per-item ceiling,
        # but their 32*1025 padded activation footprint is deliberately
        # larger than the bounded research batch budget.
        backend = self.make_backend()
        backend.max_tokens = 8192
        requests = [
            req(i, "1 " * 1024 + str(i))
            for i in range(1, 33)
        ]
        with self.assertRaisesRegex(ValueError, "padded token resource envelope"):
            SharedStemEngine(backend, max_cache_bytes=0).run(requests)
        self.assertEqual(backend.invocations, 0)
        self.assertEqual(backend.model.calls, 0)

    def test_torch_forward_is_one_actual_batched_tensor_operation(self):
        model = self.make_backend()
        engine = SharedStemEngine(model)
        result = engine.run([req(1, "1 2"), req(2, "3 4 5"), req(3, "1 2")])
        self.assertEqual(model.model.calls, 1)
        self.assertEqual(model.invocations, 1)
        self.assertEqual((result.distinct_inputs, result.backend_batch_widths), (2, (2,)))
        self.assertFalse(result.production_authorized)
        self.assertTrue(result.simulated)
        self.assertEqual(result.receipts[0].feature_digest, result.receipts[2].feature_digest)
        self.assertNotEqual(result.receipts[0].feature_digest, result.receipts[1].feature_digest)

    def test_real_torch_forward_feeds_versioned_q24_projection(self):
        # Torch executes an actual tensor batch over synthetic local weights.
        # This is not evidence of a downloaded or audited pretrained Encoder.
        from stem_projection import Q, LowRankProjectionQ24, ProjectedStemEngine
        model = self.make_backend()
        engine = SharedStemEngine(model, max_cache_bytes=0)
        projector = LowRankProjectionQ24(
            D("a"), D("b"), D("c"), D("d"), "mean",
            4, 2, 1, (0, 0, 0, Q), (Q, Q), (0, 0),
        )
        bridge = ProjectedStemEngine(engine, projector)
        result = bridge.run([
            req(1, "1 2"), req(2, "3 4 5"), req(3, "1 2"),
        ])
        self.assertEqual(model.model.calls, 1)
        self.assertEqual(result.encoder_observation.backend_batch_widths, (2,))
        self.assertEqual(len(result.refs), 3)
        self.assertEqual(len(result.refs[0].vector_q24), 2)
        self.assertEqual(result.refs[0].vector_q24, result.refs[2].vector_q24)
        self.assertEqual(result.refs[0].projected_input_digest,
                         result.refs[2].projected_input_digest)
        self.assertFalse(result.production_authorized)

    def test_left_padded_batch_matches_unpadded_solo(self):
        model = self.make_backend(left_padding=True)
        batched = SharedStemEngine(model).run([
            req(1, "1 2"), req(2, "3 4 5"),
        ])
        single = SharedStemEngine(model, max_cache_bytes=0).run([
            req(3, "1 2"),
        ])
        self.assertEqual(
            batched.receipts[0].feature_digest,
            single.receipts[0].feature_digest,
        )
        self.assertEqual(model.invocations, 2)

    def test_torch_landmarks_and_frozen_token_cap(self):
        model = self.make_backend()
        engine = SharedStemEngine(model)
        result = engine.run([req(1, "1 2", mode="landmark8")])
        self.assertEqual(result.receipts[0].feature_width, 32)
        with self.assertRaisesRegex(ValueError, "token capacity"):
            engine.run([req(2, "1 2 3 4 5 6 7 8 9")])
        self.assertEqual(model.invocations, 1)


if __name__ == "__main__":
    unittest.main()
