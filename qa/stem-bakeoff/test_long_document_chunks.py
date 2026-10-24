"""Native offsets, token conservation, overlap weighting and fail-closed caps."""

from dataclasses import FrozenInstanceError
import unittest

from long_document_chunks import ChunkPolicy, plan_document


def encoding(text, prefix=""):
    ids, offsets = ([7], [(0, len(prefix))]) if prefix else ([], [])
    ids += [100 + i for i in range(len(text))]
    offsets += [(len(prefix) + i, len(prefix) + i + 1) for i in range(len(text))]
    return {"input_ids": [1] + ids + [2], "offset_mapping": [(0, 0)] + offsets + [(0, 0)],
            "special_tokens_mask": [1] + [0] * len(ids) + [1]}


class LongDocumentChunkTests(unittest.TestCase):
    def test_unicode_tail_coverage_native_tokens_and_inverse_overlap_weights(self):
        text, prefix = "a😀中bcdefghijklmnopqrstuv尾", "P: "
        policy = ChunkPolicy(max_tokens=10, overlap_tokens=2)
        plan = plan_document(text, encoding(text, prefix), prefix=prefix, tokenizer_sha256="a" * 64, policy=policy)
        plan.verify()
        coverage = [0] * len(text)
        for chunk in plan.chunks:
            self.assertLessEqual(len(chunk.input_ids), 10)
            self.assertEqual(chunk.input_ids[:2], (1, 7))
            self.assertEqual(chunk.input_ids[-1], 2)
            self.assertEqual(chunk.input_ids[2:-1], tuple(100 + i for i in range(chunk.token_start, chunk.token_end)))
            self.assertEqual(text.encode()[chunk.byte_start:chunk.byte_end], text[chunk.char_start:chunk.char_end].encode())
            for i in range(chunk.token_start, chunk.token_end): coverage[i] += 1
        self.assertTrue(all(coverage))
        self.assertAlmostEqual(sum(chunk.weight for chunk in plan.chunks), len(text))
        for chunk in plan.chunks:
            self.assertAlmostEqual(chunk.weight, sum(1 / coverage[i] for i in range(chunk.token_start, chunk.token_end)))
        self.assertEqual(plan.chunks[-1].byte_end, len(text.encode()))
        with self.assertRaises(FrozenInstanceError): plan.content_tokens = 99
        object.__setattr__(plan, "content_tokens", 99)
        with self.assertRaisesRegex(ValueError, "changed"): plan.verify()

    def test_prefix_boundary_token_is_content_and_whitespace_spans_are_complete(self):
        text, prefix = "a   b  ", "P "
        raw = {"input_ids": [1, 7, 10, 11, 2], "offset_mapping": [(0, 0), (0, 1), (1, 3), (6, 7), (0, 0)],
               "special_tokens_mask": [1, 0, 0, 0, 1]}
        plan = plan_document(text, raw, prefix=prefix, tokenizer_sha256="a" * 64)
        self.assertEqual((plan.prefix_tokens, plan.content_tokens), (1, 2))
        self.assertEqual(plan.chunks[0].char_spans[2:4], ((0, 1), (4, 5)))
        self.assertEqual((plan.chunks[0].char_start, plan.chunks[0].char_end), (0, len(text)))

    def test_chunk_and_actual_prefix_limits_reject_instead_of_dropping_tail(self):
        for policy in (ChunkPolicy(max_tokens=8, overlap_tokens=2, max_chunks_per_source=1),
                       ChunkPolicy(max_tokens=8, overlap_tokens=5)):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                plan_document("abcdefghijk", encoding("abcdefghijk", "P"), prefix="P",
                              tokenizer_sha256="a" * 64, policy=policy)

    def test_missing_content_nonmonotone_offsets_and_internal_template_reject(self):
        for field, value in (("offset_mapping", [(0, 0), (1, 2), (0, 1), (0, 0)]),
                             ("special_tokens_mask", [0, 1, 0, 1]),
                             ("input_ids", [1, -2, 100, 2])):
            raw = encoding("ab"); raw[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                plan_document("ab", raw, prefix="", tokenizer_sha256="a" * 64)


if __name__ == "__main__":
    unittest.main()
