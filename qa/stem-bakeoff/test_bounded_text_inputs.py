import unittest

from bounded_text_inputs import matched_inputs, prepare_row, select_source_tokens


class NativeTokenizer:
    def __call__(self, text, **kwargs):
        body = [int(word) for word in text.split()]
        if kwargs.get("add_special_tokens"):
            return {"input_ids": [10000] + body + [10001],
                    "special_tokens_mask": [1] + [0] * len(body) + [1]}
        return {"input_ids": body}

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def prepare_for_model(self, ids, **kwargs):
        ids = [10000] + ids + [10001]
        return {"input_ids": ids, "attention_mask": [1] * len(ids)}


class BoundedInputTests(unittest.TestCase):
    def test_every_length_and_odd_budget_preserves_exact_cost(self):
        for length in (1, 2, 7, 14, 15, 16, 17, 190, 191, 192, 997):
            for budget in (8, 17, 192):
                source = list(range(length))
                selections = [select_source_tokens(source, max_tokens=budget,
                    special_tokens=2, policy=policy) for policy in ("prefix", "head_tail")]
                self.assertEqual(len(selections[0].source_positions), len(selections[1].source_positions))
                for selected in selections:
                    self.assertEqual(len(set(selected.source_positions)), selected.retained_source_tokens)
                    self.assertEqual(tuple(sorted(selected.source_positions)), selected.source_positions)
                    self.assertLessEqual(selected.retained_source_tokens + 2, budget)
                if length <= budget - 2:
                    self.assertEqual(selections[0].source_token_ids, selections[1].source_token_ids)
                else:
                    self.assertEqual(selections[1].source_positions[-1], length - 1)

    def test_gold_fields_and_label_changes_cannot_select_tokens(self):
        row = {"source_id": "issue-1", "source_version": "commit-1",
               "text": " ".join(map(str, range(60))), "label": 0, "patch": "sensitive target"}
        before = matched_inputs(NativeTokenizer(), [row], max_tokens=17)
        row.update(label=1, patch="changed target", hints="different")
        self.assertEqual(before, matched_inputs(NativeTokenizer(), [row], max_tokens=17))

    def test_native_ids_not_decoded_and_retokenized(self):
        row = {"source_id": "issue-1", "source_version": "commit-1", "text": " ".join(map(str, range(60)))}
        data, receipt = prepare_row(NativeTokenizer(), row, max_tokens=8, policy="head_tail")
        self.assertEqual(data["input_ids"], [10000, 0, 1, 2, 57, 58, 59, 10001])
        self.assertEqual(receipt["source_positions"], (0, 1, 2, 57, 58, 59))
        self.assertEqual(receipt["effective_model_tokens"], 8)

    def test_tokenizer_count_drift_rejected(self):
        class DriftingTokenizer(NativeTokenizer):
            def num_special_tokens_to_add(self, pair=False):
                return 1
        row = {"source_id": "issue-1", "source_version": "commit-1", "text": "1 2 3"}
        with self.assertRaisesRegex(ValueError, "special-token contract"):
            prepare_row(DriftingTokenizer(), row)

    def test_duplicate_identity_rejected(self):
        row = {"source_id": "issue-1", "source_version": "commit-1", "text": "1 2 3"}
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            matched_inputs(NativeTokenizer(), [row, row])


if __name__ == "__main__":
    unittest.main()
