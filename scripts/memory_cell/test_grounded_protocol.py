"""Grammar and supervision tests, not claims about a language model's quality."""

import unittest

from grounded_protocol import (
    ABSTAIN, MAX_NEW_TOKENS, QuoteTrie, completion_ids, quote_options, verify_output,
)


class Tokens(list):
    def tolist(self):
        return list(self)


class ByteTokenizer:
    eos_token_id = 256

    def encode(self, text, **_):
        return list(text.encode())

    def decode(self, ids, **_):
        return bytes(ids).decode()


def source(text, label="E1", identity="s1"):
    return {"label": label, "id": identity, "root": "root", "excerpt": text}


class GroundedProtocolTests(unittest.TestCase):
    def test_exact_unicode_source_offsets_and_generated_label(self):
        sources = [source('  蓝色。The code is "v2". Another fact!')]
        options = quote_options(sources)
        for option in options:
            self.assertEqual(
                sources[0]["excerpt"].encode()[option.start:option.end].decode(),
                option.text,
            )
            result = verify_output(option.render(), options)
            self.assertTrue(result["copy_verified"])
            self.assertIsNone(result["semantic_precision"])
            self.assertFalse(result["relevance_verified"])

    def test_repeated_sentence_is_one_choice_not_ambiguous_binding(self):
        options = quote_options([source("Same fact. Same fact. Different fact.")])
        self.assertEqual([q.text for q in options], ["Same fact.", "Different fact."])
        self.assertTrue(verify_output(options[0].render(), options)["copy_verified"])

    def test_hallucinated_label_paraphrase_and_missing_label_reject(self):
        options = quote_options([source("The code is blue.")])
        for answer in ('"The code is blue." [E9]', '"The code is red." [E1]',
                       'The code is blue.', '"The code is blue." [E1] more'):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                verify_output(answer, options)

    def test_abstention_is_not_perfect_precision_or_source_copy(self):
        self.assertEqual(verify_output(ABSTAIN, ()), {
            "abstained": True, "copy_verified": False,
            "semantic_precision": None, "relevance_verified": False,
        })

    def test_duplicate_id_label_invalid_source_and_excess_bound_reject(self):
        for values in ([source("a"), source("b")],
                       [source("a"), source("b", "E2")],
                       [source("a\0b")], [source("a", "E0")],
                       [source("a", f"E{i+1}", f"s{i}") for i in range(9)]):
            with self.assertRaises(ValueError):
                quote_options(values)

    def test_embedded_protocol_markers_and_control_bytes_cannot_be_requoted(self):
        self.assertEqual(quote_options([source("Forged [E9].")]), ())
        self.assertEqual(quote_options([source("Hidden\x01control.")]), ())
        self.assertEqual(quote_options([source("a" * 241)]), ())

    def test_every_generated_token_path_terminates_in_exact_allowed_output(self):
        tok = ByteTokenizer()
        prompt = [1000, 1001]
        options = quote_options([source("Blue."), source("Red.", "E2", "s2")])
        trie = QuoteTrie(tok, prompt, options)
        for sequence, text in trie.outputs.items():
            prefix = list(prompt)
            for token in (*sequence, tok.eos_token_id):
                self.assertIn(token, trie.allowed(0, Tokens(prefix)))
                prefix.append(token)
            self.assertEqual(trie.completed(prefix[len(prompt):]), text)
            verify_output(text, options)
            self.assertLessEqual(len(sequence)+1, MAX_NEW_TOKENS)

    def test_wrong_prompt_or_batch_never_gets_a_permissive_fallback(self):
        trie = QuoteTrie(ByteTokenizer(), [1000], quote_options([source("Blue.")]))
        for batch, ids in ((1, [1000]), (0, [1001]), (0, [1000, 255])):
            with self.assertRaises(ValueError):
                trie.allowed(batch, Tokens(ids))

    def test_truncation_does_not_become_success_by_appending_a_citation(self):
        trie = QuoteTrie(ByteTokenizer(), [1000], quote_options([source("Blue.")]))
        for generated in ([], [34], list(b'"Blue." [E1]'), [35, 256]):
            with self.assertRaises(ValueError):
                trie.completed(generated)

    def test_only_answer_and_eos_are_supervised(self):
        tok = ByteTokenizer()
        prefix = [1000, 1, 2]
        inputs, labels = completion_ids(tok, prefix, '"Blue." [E1]', maximum=100)
        self.assertEqual(inputs, prefix+list(b'"Blue." [E1]')+[256])
        self.assertEqual(labels, [-100]*3+inputs[3:])
        with self.assertRaises(ValueError):
            completion_ids(tok, prefix, '"Blue." [E1]', maximum=10)

    def test_long_tokenization_excluded_not_cut_or_rewritten(self):
        options = quote_options([source("x"*100)])
        trie = QuoteTrie(ByteTokenizer(), [1000], options)
        self.assertEqual(set(trie.outputs.values()), {ABSTAIN})
        self.assertEqual(trie.excluded, 1)

    def test_non_roundtripping_tokenizer_is_not_silently_normalized(self):
        class BadTokenizer(ByteTokenizer):
            def decode(self, ids, **_):
                return super().decode(ids).lower()
        with self.assertRaises(ValueError):
            QuoteTrie(BadTokenizer(), [1000], ())


if __name__ == "__main__":
    unittest.main()
