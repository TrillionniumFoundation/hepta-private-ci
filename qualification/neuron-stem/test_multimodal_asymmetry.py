"""Offline asymmetry tests; no weights, media decoding or fabricated scores."""
import unittest

from jina_v5_multimodal import paired_ranking


class CrossModalRetrievalDirectionTests(unittest.TestCase):
    @staticmethod
    def cases():
        # Deliberately asymmetric pairs. These are only a routing fixture,
        # not actual Jina model quality or observed cross-modal capability.
        def item(case_id, media, text):
            return {
                "case_id": case_id, "scope_id": "scope.1", "split": "test",
                "modality": "image", "media_sha256": "a" * 64,
                "media_vector": media, "text_vector": text,
                "media_wall_ms": 1.0, "text_wall_ms": 2.0,
                "rss_bytes": 4096,
            }
        return [
            item("a", (1., 0.), (1., 0.)),
            item("b", (.7, .7), (-.5, .86)),
        ]

    def test_query_document_direction_changes_pair_ranking(self):
        data = self.cases()
        media_query = paired_ranking(data, direction="media-to-text")
        text_query = paired_ranking(data, direction="text-to-media")
        self.assertEqual(len(media_query), 2)
        self.assertEqual(len(text_query), 2)
        self.assertEqual([x["recall_at_1"] for x in media_query], [1, 0])
        self.assertEqual([x["recall_at_1"] for x in text_query], [1, 1])
        self.assertTrue(all(x["retrieval_direction"] == "media-to-text"
                            for x in media_query))
        self.assertTrue(all(x["retrieval_direction"] == "text-to-media"
                            for x in text_query))

    def test_unknown_or_mixed_direction_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            paired_ranking(self.cases(), direction="document-to-document")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            paired_ranking(self.cases(), direction=None)

    def test_insufficient_ranking_negatives_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            paired_ranking(self.cases()[:1])


if __name__ == "__main__":
    unittest.main()
