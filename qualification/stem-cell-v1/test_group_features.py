"""Feature identity, immutable payload and recurrent workspace boundaries."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import importlib.util
import unittest

from group_features import BoundedWorkspace, FeatureCache, FeatureIdentity, FeatureSnapshotV2, content_digest


def identity(**updates):
    result = FeatureIdentity("episode-1", 0, "weights-commit-7c83",
                             content_digest(b"tokenizer bytes"), content_digest(b"preprocess v1"),
                             content_digest(b"source bytes"), "text")
    return replace(result, **updates)


def snapshot(ref=None, **updates):
    values = {"identity": ref or identity(), "tokens": [[0.1, 0.2], [0.3, 0.4]], "mask": [1, 0]}
    values.update(updates)
    return FeatureSnapshotV2(**values)


class GroupFeaturesTests(unittest.TestCase):
    def test_immutable_and_digest_covers_actual_payload(self):
        tokens, mask, positions, times = [[1.0, -0.0]], [1], [[2, 3]], [0.5]
        value = snapshot(tokens=tokens, mask=mask, positions=positions, timestamps=times)
        tokens[0][0], mask[0], positions[0][0], times[0] = 99, 0, 99, 99
        self.assertEqual((value.tokens, value.mask, value.positions, value.timestamps),
                         (((1.0, -0.0),), (True,), ((2.0, 3.0),), (0.5,)))
        with self.assertRaises(FrozenInstanceError):
            value.tokens = ()
        with self.assertRaises(TypeError):
            value.tokens[0][0] = 9
        equivalent = snapshot(tokens=[[1, -0.0]], mask=[True], positions=[[2, 3]], timestamps=[0.5])
        self.assertEqual(value, equivalent)
        for changed in (snapshot(tokens=[[1, 0.0]], mask=[1], positions=[[2, 3]], timestamps=[0.5]),
                        snapshot(tokens=[[1, -0.0]], mask=[1], positions=[[2, 4]], timestamps=[0.5]),
                        snapshot(tokens=[[1, -0.0]], mask=[1], positions=[[2, 3]], timestamps=[0.6])):
            self.assertNotEqual(value.digest, changed.digest)

    def test_invalid_shapes_values_and_coordinates(self):
        invalid = [{"tokens": []}, {"tokens": [[1], [1, 2]]}, {"tokens": [[1] * 513], "mask": [1]},
                   {"tokens": [[1]] * 257, "mask": [1] * 257}, {"tokens": [[float("nan")], [1]]},
                   {"tokens": [[float("inf")], [1]]}, {"mask": [1]}, {"mask": [0, 0]},
                   {"mask": [1, 2]}, {"positions": [[1]]}, {"positions": [[1.5], [2]]},
                   {"positions": [[-1], [2]]}, {"timestamps": [1, 0]},
                   {"timestamps": [0, float("nan")]}, {"timestamps": [0, float("inf")]}]
        for updates in invalid:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                snapshot(**updates)

    def test_cache_exact_identity_and_scope(self):
        cache, count = FeatureCache("episode-1", 0), [0]
        def encode():
            count[0] += 1
            return snapshot()
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: cache.get_or_encode(identity(), encode), range(16)))
        self.assertEqual(count[0], 1)
        self.assertTrue(all(value is values[0] for value in values))
        self.assertEqual(cache.nbytes, values[0].nbytes)
        for ref in (identity(scope="episode-2"), identity(generation=1)):
            with self.assertRaises(ValueError):
                cache.get_or_encode(ref, encode)
        self.assertEqual(count[0], 1)
        for changes in ({"source_digest": content_digest(b"new input")},
                        {"preprocess_digest": content_digest(b"new preprocess")},
                        {"tokenizer_digest": content_digest(b"new tokenizer")},
                        {"model_revision": "new pinned revision"}, {"modality": "image"}):
            ref = identity(**changes)
            self.assertIs(cache.get_or_encode(ref, lambda: snapshot(ref)).identity, ref)

    def test_cache_capacity_and_factory_binding(self):
        ref = identity(source_digest=content_digest(b"another input"))
        cache = FeatureCache("episode-1", 0, max_entries=1)
        cache.get_or_encode(identity(), snapshot)
        with self.assertRaises(ValueError):
            cache.get_or_encode(ref, lambda: snapshot(ref))
        for cache in (FeatureCache("episode-1", 0, max_bytes=1), FeatureCache("episode-1", 0)):
            with self.assertRaises(ValueError):
                cache.get_or_encode(ref, snapshot)
        with self.assertRaises(ValueError):
            FeatureCache("episode-1", 0, max_bytes=1).get_or_encode(identity(), snapshot)
        for changes in ({"source_digest": "label"}, {"generation": -1}, {"scope": ""}):
            with self.assertRaises(ValueError):
                identity(**changes)

    def test_workspace_steps_scope_memory_and_atomic_failure(self):
        work = BoundedWorkspace("episode-1", 0, slots=2, width=2, max_steps=2, max_bytes=32)
        source = [[1, 2], [3, 4]]
        expected = work.write(1, source, scope="episode-1", generation=0)
        source[0][0] = 999
        self.assertEqual(work.state, ((1.0, 2.0), (3.0, 4.0)))
        self.assertEqual(work.nbytes, 32)
        for step, rows, scope, generation in ((1, [[1, 2]], "episode-1", 0),
                                             (2, [[1, 2]], "episode-2", 0),
                                             (2, [[1, 2]], "episode-1", 1),
                                             (2, [[1]], "episode-1", 0),
                                             (2, [[1, float("nan")]], "episode-1", 0)):
            with self.assertRaises(ValueError):
                work.write(step, rows, scope=scope, generation=generation)
            self.assertEqual((work.state, work.step), (expected, 1))
        work.write(2, [[5, 6]], scope="episode-1", generation=0)
        with self.assertRaises(ValueError):
            work.write(3, [[7, 8]], scope="episode-1", generation=0)
        with self.assertRaises(ValueError):
            BoundedWorkspace("episode-1", 0, slots=2, width=2, max_bytes=31)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "optional torch runtime unavailable")
    def test_tensor_is_detached_cloned_and_graph_free(self):
        import torch
        tokens = torch.tensor([[1.0, 2.0]], requires_grad=True)
        value = snapshot(tokens=tokens, mask=torch.tensor([1]))
        with torch.no_grad():
            tokens.fill_(99)
        self.assertEqual(value.tokens, ((1.0, 2.0),))
        self.assertFalse(hasattr(value.tokens, "grad_fn"))


if __name__ == "__main__":
    unittest.main()
