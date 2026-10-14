"""Adversarial contract tests: real LoCoMo published sources, not mock model gains."""

import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from locomo_tiny_source_head_transfer import (
    FEATURES, PUB_SHA, choose8, features, loaded_public, original_zip,
    regular, sha, strict, tokens,
)
from locomo_tiny_source_head_balanced import (
    SCHEMA, SPLIT, schedule_six_families, seal,
)
from locomo_tiny_source_head_balanced_score import postseal_score


def groups():
    scopes = [f"locomo:conv-{n}" for n in range(6)]
    public = dict(splits={"train": [dict(scope=x) for x in scopes]})
    rows = []
    for index, scope in enumerate(scopes):
        for i in range(index + 1):
            rows.append((scope + "/doc" + str(i), "reconstructed", [[1.0] * 10]))
    return public, rows


class NativeLoCoMoHeadTransferTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in (b'{"id":1,"id":2}', b'{"score":NaN}', b'{"value":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                strict(raw)

    def test_source_question_text_is_bounded_and_nonempty(self):
        with self.assertRaises(ValueError):
            tokens("x" * 100001)
        self.assertEqual(tokens("What music does John like?"), ("music", "john", "like"))

    def test_ten_features_are_finite_and_lexical_relevance_is_not_inverted(self):
        a = features("John plays jazz", "John plays jazz in town", {"jazz": 1.8}, 0.5)
        b = features("John plays jazz", "Caroline writes a letter", {"jazz": 1.8}, 0.5)
        self.assertEqual(len(a), len(FEATURES))
        self.assertTrue(all(math.isfinite(x) for x in a + b))
        self.assertGreater(a[0], b[0])
        self.assertGreater(a[3], b[3])

    def test_all_six_real_training_families_get_exactly_32_steps(self):
        public, rows = groups()
        steps, counts = schedule_six_families(public, rows)
        self.assertEqual(len(steps), 192)
        self.assertEqual(len(counts), 6)
        self.assertEqual(set(counts.values()), {32})
        self.assertEqual(sum(counts.values()), 192)
        self.assertEqual({f for f, _ in steps[:6]}, set(counts))

    def test_missing_actual_training_family_is_fail_closed(self):
        public, rows = groups()
        rows = [r for r in rows if not r[0].startswith("locomo:conv-5/")]
        with self.assertRaisesRegex(ValueError, "six actual disjoint"):
            schedule_six_families(public, rows)

    def test_tie_breaks_are_deterministic_and_select_eight_original_sources(self):
        corpus = {f"source-{i}": dict(content="same text in every passage") for i in range(10)}
        candidates = list(reversed(sorted(corpus)))
        winner = choose8("query", candidates, corpus, {}, [0.0] * 10)
        self.assertEqual(winner, sorted(corpus)[:8])
        self.assertEqual(len(set(winner)), 8)

    def test_wrong_external_public_zip_cannot_be_a_real_training_result(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "fake.zip"
            bad.write_bytes(b"not original published conversations")
            with self.assertRaisesRegex(ValueError, "immutable external ZIP SHA256"):
                original_zip(bad, PUB_SHA, ("population.json",))

    def test_symlink_and_oversized_json_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "actual.json"
            real.write_text("{}")
            link = root / "alias.json"
            link.symlink_to(real)
            with self.assertRaisesRegex(ValueError, "unbounded immutable"):
                regular(link)
            with self.assertRaisesRegex(ValueError, "unbounded immutable"):
                regular(real, limit=1)

    def test_before_gold_seal_requires_384_real_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            policy = root / "weights.json"
            public = root / "predictions.json"
            seal_path = root / "seal.json"
            fake = dict(schema=SCHEMA, total_gradient_updates=384,
                        original_benchmark_QA_labels_read=False)
            policy.write_bytes(json.dumps(fake).encode())
            public.write_bytes(json.dumps(dict(schema=SCHEMA, split=SPLIT,
                        source_only_before_annotated_target=True,
                        model_answer_calls=0, frozen_policy_sha256=sha(policy.read_bytes()),
                        predictions=[{}] * 64)).encode())
            accepted = seal(policy, public, seal_path)
            self.assertFalse(accepted["original_target_zip_opened"])
            self.assertEqual(accepted["source_only_gradient_updates"], 384)
            with self.assertRaises(FileExistsError):
                seal(policy, public, seal_path)

    def test_forged_update_count_rejected_before_seal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            weights = root / "weights.json"
            preds = root / "predictions.json"
            weights.write_text(json.dumps(dict(schema=SCHEMA,
                total_gradient_updates=192, original_benchmark_QA_labels_read=False)))
            preds.write_text(json.dumps(dict(schema=SCHEMA, split=SPLIT,
                source_only_before_annotated_target=True,
                model_answer_calls=0, frozen_policy_sha256=sha(weights.read_bytes()),
                predictions=[{}] * 64)))
            with self.assertRaisesRegex(ValueError, "not sealed"):
                seal(weights, preds, root / "seal.json")

    def test_grader_rejects_false_pre_target_sha_before_opening_gold(self):
        with self.assertRaisesRegex(ValueError, "SHA256 must be supplied"):
            postseal_score(
                Path("missing-public"), Path("missing-decisions"),
                Path("missing-weights"), Path("missing-predictions"),
                Path("missing-seal"), Path("missing-gold"),
                Path("missing-policy"), expected_preseal_sha="fake",
            )

    def test_published_original_census_if_actual_public_archives_present(self):
        public = os.environ.get("HEPTA_LOCOMO_SOURCE_ZIP")
        decision = os.environ.get("HEPTA_LOCOMO_DECISIONS_ZIP")
        if not public or not decision:
            self.skipTest("source artifact not present; test original ZIP in CI training")
        pop, docs, source_decisions = loaded_public(public, decision)
        self.assertEqual(len(docs), 5882)
        self.assertEqual(len(source_decisions), 480)
        self.assertEqual({k: len(v) for k, v in pop["splits"].items()},
                         {"train": 48, "selection": 16, "evaluation": 16})
        self.assertEqual(len({r["family_proxy_digest"] for r in pop["splits"]["train"]}), 6)


if __name__ == "__main__":
    unittest.main()
