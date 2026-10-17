"""Source-only Stem/MemoryCell research contracts (synthetic vectors are NOT pretrained)."""

from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest

import numpy as np

import associative_graph_causal as graph
from associative_cell import AssociativeCell, ReadQuery, sha256
from associative_text_bridge import PinnedTextProjection
import parametric_stem_reader as stem
from test_associative_graph_causal import public_fixture


class FakeFrozenEncoder:
    identity = "mock-encoder-is-not-pretrained-model"
    truncated_inputs = 0

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        result = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
            rng = np.random.default_rng(seed)
            vector = rng.normal(size=384).astype(np.float32)
            result.append(vector / np.linalg.norm(vector))
        return np.stack(result)


class ParametricStemMechanics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.section = public_fixture()["families"][0]
        cls.section["family"] = "conv-0"
        cls.mock = FakeFrozenEncoder()
        cls.projection = PinnedTextProjection(cls.mock, dimension=64, seed=stem.SEED)
        cls.docs, cls.embeddings, cls.parent, cls.child, cls.raw, cls.receipt = (
            stem.train_section(cls.section, cls.projection)
        )

    def test_source_lineage_and_small_real_sgd_step(self):
        self.assertEqual(self.receipt["train_examples"], 128)
        self.assertEqual(self.receipt["steps"], stem.STEPS)
        self.assertEqual(self.receipt["trainable_parameters"], 1024)
        self.assertEqual(self.parent.roots, set())
        self.assertEqual(len(self.child.roots), 128)
        self.assertGreater(self.receipt["tensor_delta_squared_norm"], 0)
        self.assertTrue(self.receipt["no_raw_examples_in_artifact"])
        self.assertFalse(self.receipt["production_accepted"])

    def test_no_heldout_question_is_training_input(self):
        changed = copy.deepcopy(self.section)
        changed["questions"][0]["text"] = "Gold reference answer is a secret key"
        _, _, _, cell, raw, _ = stem.train_section(changed, self.projection)
        self.assertEqual(raw, self.raw)
        self.assertEqual(sha256(raw), sha256(cell.export()))

    def test_cell_is_not_parameter_only_reader(self):
        query = ReadQuery(
            scope="conv-0",
            kind="semantic",
            encoder_identity=self.projection.identity,
            as_of=129,
            cue=tuple(float(v) for v in self.embeddings[0]),
        )
        result = self.child.read(query, revoked=frozenset())
        self.assertEqual(len(result), 64)
        self.assertTrue(np.isfinite(result).all())
        self.assertFalse(any(x in self.raw for x in (b"alpha beta", b"What did")))
        self.assertNotEqual(
            tuple(result), tuple(self.parent.read(query, revoked=frozenset()))
        )

    def test_revoke_source_does_not_resurrect_weights(self):
        root = self.docs[1]["id"]
        with self.assertRaises(ValueError):
            self.child.read(
                ReadQuery(
                    scope="conv-0",
                    kind="semantic",
                    encoder_identity=self.projection.identity,
                    as_of=129,
                    cue=tuple(float(v) for v in self.embeddings[0]),
                ),
                revoked={root},
            )
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                self.raw,
                expected_sha256=sha256(self.raw),
                encoder_identity=self.projection.identity,
                scope="conv-0",
                allowed_roots={d["id"] for d in self.docs},
                revoked={root},
            )

    def test_cross_scope_or_model_generation_denied(self):
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                self.raw,
                expected_sha256=sha256(self.raw),
                encoder_identity="wrong",
                scope="conv-0",
                allowed_roots={d["id"] for d in self.docs},
                revoked=set(),
            )
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                self.raw,
                expected_sha256=sha256(self.raw),
                encoder_identity=self.projection.identity,
                scope="conv-1",
                allowed_roots={d["id"] for d in self.docs},
                revoked=set(),
            )

    def test_tampered_tensor_or_digest_denied(self):
        tampered = json.loads(self.raw)
        tampered["state"]["up"][0][0] += 1
        raw = json.dumps(tampered).encode()
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                raw,
                expected_sha256=sha256(self.raw),
                encoder_identity=self.projection.identity,
                scope="conv-0",
                allowed_roots={d["id"] for d in self.docs},
                revoked=frozenset(),
            )

    def test_7_arm_equal_pool_and_wrong_split(self):
        rows, raw, receipt = stem.rank_section(self.section, self.projection)
        self.assertEqual(len(rows), 24)
        allowed = {d["id"] for d in self.docs}
        for item in rows:
            self.assertEqual(set(item["arms"]), set(stem.ARMS))
            for ranked in item["arms"].values():
                self.assertEqual(len(ranked), 8)
                self.assertEqual(len(set(ranked)), 8)
                self.assertTrue(set(ranked) <= allowed)

    def test_unbounded_or_mismatched_source_gate(self):
        bad = copy.deepcopy(self.section)
        bad["sources"][0]["id"] = bad["sources"][1]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            stem._pool(bad)
        too_small = copy.deepcopy(self.section)
        too_small["sources"] = too_small["sources"][:127]
        with self.assertRaises(ValueError):
            stem._pool(too_small)

    def test_create_only_rejects_second_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            graph.create_only(path, self.raw)
            with self.assertRaises(FileExistsError):
                graph.create_only(path, self.raw)


if __name__ == "__main__":
    unittest.main()
