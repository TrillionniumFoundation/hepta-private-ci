"""Five label-free publisher-cohort attacks; no model inference or gold."""
from copy import deepcopy
import unittest

from experiments.shared_stem_cell import external_bbc_shift as b
from experiments.shared_stem_cell.bbc_source_attestation import attest


class SourceAttestationTests(unittest.TestCase):
    @staticmethod
    def texts():
        return [f"Extensive synthetic news report number {i:04d} with "
                f"sufficient article text for independent source tests"
                for i in range(256)]

    def test_replay_selection_records_digests_but_no_source_text_or_gold(self):
        texts = self.texts()
        rows = b.public_cohort(b.sample(texts))
        receipt = attest(texts, [], rows)
        self.assertEqual(receipt["selected_rows"], 128)
        self.assertEqual(receipt["full_text_column_rows"], 256)
        self.assertFalse(receipt["label_accessed"])
        self.assertFalse(receipt["production_accepted"])
        self.assertNotIn("Extensive synthetic", str(receipt))
        self.assertEqual(receipt["selected_index_sha256"], b.digest(b.canonical(rows)))

    def test_valid_rehashed_same_cell_reordering_still_rejects(self):
        texts = self.texts()
        rows = b.public_cohort(b.sample(texts))
        attacked = deepcopy(rows)
        attacked[0], attacked[2] = attacked[2], attacked[0]
        self.assertTrue(b.validate_public_cohort(attacked))
        with self.assertRaisesRegex(b.SourceError, "not selected from complete"):
            attest(texts, [], attacked)

    def test_alternative_legal_source_index_rejects_even_with_rehashed_cohort(self):
        texts = self.texts()
        original = b.public_cohort(b.sample(texts))
        selected = {r["source_index"] for r in original}
        other = next(i for i in range(len(texts)) if i not in selected)
        text = texts[other]
        attacked = deepcopy(original)
        attacked[0] = {
            "case_id": f"bbc-news:test:{other}", "source_index": other,
            "full_source_sha256": b.digest(text.encode()),
            "normalized_excerpt_sha256": b.digest(
                b.normalized(" ".join(text.split())[:b.PREFIX]).encode()),
            "cell": 0,
        }
        self.assertTrue(b.validate_public_cohort(attacked))
        with self.assertRaisesRegex(b.SourceError, "not selected from complete"):
            attest(texts, [], attacked)

    def test_changed_unselected_publisher_article_invalidates_original_receipt(self):
        texts = self.texts()
        rows = b.public_cohort(b.sample(texts))
        selected = {r["source_index"] for r in rows}
        other = next(i for i in range(len(texts)) if i not in selected)
        altered = texts[:]
        altered[other] += " An amended article changed the complete publisher data."
        with self.assertRaises(b.SourceError):
            attest(altered, [], rows)

    def test_original_source_exclusion_set_cannot_change_without_resampling(self):
        texts = self.texts()
        rows = b.public_cohort(b.sample(texts))
        self.assertTrue(attest(texts, [], rows))
        excluded = [texts[rows[0]["source_index"]]]
        with self.assertRaises(b.SourceError):
            attest(texts, excluded, rows)


if __name__ == "__main__":
    unittest.main()
