"""Actual pre-forward Gemma2 token contract, mock tokenizer only (NO weights)."""
from __future__ import annotations
import unittest
from e3_gemma2_native_budget import NativeBudgetError, original_native_input_preflight


class T:
    def __init__(self, *, override=None, scale=1, prompts=None, default=None):
        self.tokenizer = self
        self.prompts = {} if prompts is None else prompts
        self.default_prompt_name = default
        self.override, self.scale = override, scale
        self.calls = []
    def __call__(self, text, *, truncation, add_special_tokens):
        self.calls.append((text, truncation, add_special_tokens))
        if self.override is not None:
            return self.override
        return {"input_ids": list(range(len(text) * self.scale + 2))}


def inputs(text="question"):
    plain = ["query: " + text, "query: " + text + " two"]
    joint = [{"text": v, "image": f"/root/{i:064x}"} for i, v in enumerate(plain)]
    image = [{"image": v["image"]} for v in joint]
    choices = ["passage: Choice " + str(i) for i in range(8)]
    return plain, joint, image, choices


class FullNativeInputBudget(unittest.TestCase):
    def test_real_tokenizer_called_before_model_forward(self):
        mock = T()
        r = original_native_input_preflight(mock, *inputs())
        self.assertEqual(len(mock.calls), 10)
        self.assertTrue(all(x[1] is False and x[2] is True for x in mock.calls))
        self.assertTrue(r["complete_text_tokenizer_truncation_disabled"])
        self.assertFalse(r["actual_model_image_token_count_attested"])
        self.assertEqual(r["authority"], "DENY_ALL")

    def test_registered_default_prompt_included_in_tokenization(self):
        mock = T(prompts={"Classification": "Classify this: "}, default="Classification")
        original_native_input_preflight(mock, *inputs())
        self.assertTrue(all(x[0].startswith("Classify this: ") for x in mock.calls))

    def test_reject_unknown_implicit_default_prompt(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(default="Unknown"), *inputs())

    def test_reject_malicious_nonstring_prompt(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(prompts={"Classification": 4}, default="Classification"), *inputs())

    def test_reject_missing_actual_tokenizer(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(object(), *inputs())

    def test_reject_unknown_source_length(self):
        plain,joint,image,choices=inputs()
        choices.pop()
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(),plain,joint,image,choices)

    def test_reject_joint_text_mutation(self):
        plain,joint,image,choices=inputs()
        joint[0]["text"]="not the same question"
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(),plain,joint,image,choices)

    def test_reject_joint_image_mutation(self):
        plain,joint,image,choices=inputs()
        joint[0]["image"]="/root/another.jpg"
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(),plain,joint,image,choices)

    def test_reject_extra_modality_field(self):
        plain,joint,image,choices=inputs()
        joint[0]["audio"]="hidden.wav"
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(),plain,joint,image,choices)

    def test_reject_nonstring_text(self):
        plain,joint,image,choices=inputs()
        plain[0]=None
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(),plain,joint,image,choices)

    def test_reject_oversized_text(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(),*inputs("x"*33000))

    def test_reject_hidden_joint_truncation_before_plain_cap(self):
        # 2000 chars*4 tokens is under 8192-128, but is above 8192-408
        with self.assertRaisesRegex(NativeBudgetError,"joint text/image"):
            original_native_input_preflight(T(scale=4),*inputs("x"*1970))

    def test_reject_plain_text_over_model_window(self):
        with self.assertRaisesRegex(NativeBudgetError,"original plain text"):
            original_native_input_preflight(T(),*inputs("y"*8200))

    def test_reject_choice_text_over_model_window(self):
        plain,joint,image,choices=inputs()
        choices[0]="x"*8200
        with self.assertRaisesRegex(NativeBudgetError,"choice text"):
            original_native_input_preflight(T(),plain,joint,image,choices)

    def test_reject_non_flat_tokens(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(override={"input_ids": [[1,2]]}),*inputs())

    def test_reject_bool_token_id(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(override={"input_ids": [True,2]}),*inputs())

    def test_reject_missing_input_ids(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(override={}),*inputs())

    def test_reject_unsafe_negative_token_id(self):
        with self.assertRaises(NativeBudgetError):
            original_native_input_preflight(T(override={"input_ids": [-1,2]}),*inputs())


if __name__ == "__main__":
    unittest.main()
