"""Real-checkpoint integration checks; set HEPTA_NDU_MODEL_DIR and OBSERVATIONS.

No downloaded checkpoint is replaced by a fake when those inputs are absent.
"""

import json
import os
from pathlib import Path
import unittest

import torch

from backend import FlorenceBackend


class BackendIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model = os.environ.get("HEPTA_NDU_MODEL_DIR")
        observations = os.environ.get("HEPTA_NDU_OBSERVATIONS")
        if not model or not observations:
            raise unittest.SkipTest("real model and observation paths must be supplied")
        cls.backend = FlorenceBackend(model, threads=4)
        cls.observation = json.loads(Path(observations).read_text().splitlines()[0])
        cls.encoded = cls.backend.encode(cls.observation)

    def test_cached_greedy_matches_transformers_generation(self):
        result = self.backend.generate(self.encoded, max_new_tokens=16)
        with torch.no_grad():
            native = self.backend.model.generate(
                encoder_outputs=self.encoded.encoder_outputs,
                attention_mask=self.encoded.attention_mask,
                max_new_tokens=16, num_beams=1, do_sample=False,
            )
        self.assertEqual(result["tokens"], native[0].tolist())
        self.assertEqual(result["costs"]["actual_checkpoints"], 0)
        self.assertGreater(result["costs"]["charged_seconds"], self.encoded.costs["encoder_seconds"])

    def test_modifier_changes_selection_and_causal_prefix(self):
        prefixes = []
        alternative = []

        def modifier(state):
            prefixes.append(state["token_ids"])
            delta = torch.zeros_like(state["logits"])
            if state["step"] == 1:
                token = int(torch.topk(state["logits"], 2).indices[1])
                alternative.append(token)
                delta[token] = state["logits"].max() - state["logits"][token] + 10
            return {"delta": delta, "weights": [1.0, 0.0, 0.0, 0.0], "action": 0}

        result = self.backend.generate(self.encoded, modifier=modifier, max_new_tokens=16)
        self.assertEqual(result["tokens"][2], alternative[0])
        self.assertTrue(result["controls"][1]["argmax_changed"])
        self.assertEqual(prefixes, [result["tokens"][:index + 1] for index in range(len(prefixes))])
        self.assertGreater(result["costs"]["modifier_seconds"], 0)
        self.assertLessEqual(result["costs"]["actual_checkpoints"], 4)

    def test_teacher_prefixes_align_with_cached_hidden_states(self):
        target = self.observation["target_category"] + "<loc_100><loc_200><loc_700><loc_800>"
        subset = [self.backend.eos_token_id] + self.backend.location_token_ids
        features = self.backend.teacher_forced_features(self.encoded, target, token_subset=subset)
        prefixes = features["decoder_prefixes"]
        self.assertEqual(prefixes[0], [self.backend.start_token_id])
        self.assertEqual(prefixes[-1][1:], features["target_ids"][:-1].tolist())
        self.assertEqual(tuple(features["logits"].shape), (len(prefixes), len(subset)))
        past = None
        with torch.no_grad():
            for index, prefix in enumerate(prefixes):
                output = self.backend.model.model.language_model.decoder(
                    input_ids=torch.tensor([[prefix[-1]]]),
                    encoder_hidden_states=self.encoded.encoder_outputs.last_hidden_state,
                    encoder_attention_mask=self.encoded.attention_mask,
                    past_key_values=past, use_cache=True, return_dict=True,
                )
                past = output.past_key_values
                torch.testing.assert_close(output.last_hidden_state[0, -1], features["hidden"][index], atol=2e-5, rtol=2e-5)
            logits = self.backend.model.lm_head(features["hidden"])
            torch.testing.assert_close(features["logits"], logits[:, subset])
            torch.testing.assert_close(features["full_logsumexp"], torch.logsumexp(logits, -1))

    def test_reference_leak_and_image_tamper_are_rejected(self):
        with self.assertRaises(ValueError):
            self.backend.encode({**self.observation, "reference_boxes": [[0, 0, 1, 1]]})
        with self.assertRaises(ValueError):
            self.backend.encode({**self.observation, "image_sha256": "0" * 64})

    def test_encoder_budget_is_charged_before_decoding(self):
        result = self.backend.generate(
            self.encoded, max_wall_seconds=self.encoded.costs["encoder_seconds"] / 2
        )
        self.assertEqual(result["termination"], "budget")
        self.assertEqual(result["tokens"], [self.backend.start_token_id])
        self.assertEqual(result["costs"]["decoder_forward_calls"], 0)
        self.assertEqual(result["boxes"], [])

    @classmethod
    def tearDownClass(cls):
        receipt = cls.backend.frozen_receipt()
        if not receipt["frozen_unchanged"] or receipt["trainable_parameters"]:
            raise AssertionError("frozen model changed during integration checks")


if __name__ == "__main__":
    unittest.main()
