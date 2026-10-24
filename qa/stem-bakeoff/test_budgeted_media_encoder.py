"""Budget identity and native processor geometry; no fabricated quality evidence."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from budgeted_media_encoder import BudgetedMediaEncoder, configuration_value
from shared_feature_contract import SharedFeatureError


class BudgetedMediaTests(unittest.TestCase):
    def test_native_processor_reduces_actual_patch_budget(self):
        from transformers import Gemma4ImageProcessor
        picture = Image.fromarray(np.arange(3072, dtype=np.uint8).reshape(32, 32, 3))
        small = Gemma4ImageProcessor(max_soft_tokens=70)(picture, return_tensors="pt")
        large = Gemma4ImageProcessor(max_soft_tokens=280)(picture, return_tensors="pt")
        self.assertEqual(small["pixel_values"].shape[1], 70 * 9)
        self.assertEqual(large["pixel_values"].shape[1], 280 * 9)
        self.assertLess(int(small["num_soft_tokens_per_image"][0]), int(large["num_soft_tokens_per_image"][0]))

    def test_effective_processor_configuration_is_bound_and_mutation_visible(self):
        from transformers import Gemma4ImageProcessor
        encoder = BudgetedMediaEncoder.__new__(BudgetedMediaEncoder)
        encoder.vision_soft_tokens = 70
        encoder.owner = SimpleNamespace(_processor=SimpleNamespace(
            image_processor=Gemma4ImageProcessor(max_soft_tokens=70),
            feature_extractor=SimpleNamespace(to_dict=lambda: {"sampling_rate": 16000}),
            chat_template="fixed"))
        with patch("shared_feature_extract.SharedFeatureEncoder._configuration_digest", return_value="base"):
            initial = encoder._configuration_digest()
            encoder.owner._processor.image_processor.max_soft_tokens = 280
            self.assertNotEqual(initial, encoder._configuration_digest())
            encoder.owner._processor.image_processor.max_soft_tokens = 70
            self.assertEqual(initial, encoder._configuration_digest())
            encoder.owner._processor.audio_ms_per_token = 80
            self.assertNotEqual(initial, encoder._configuration_digest())
            del encoder.owner._processor.audio_ms_per_token
            encoder.owner._processor.chat_template = "changed"
            self.assertNotEqual(initial, encoder._configuration_digest())

    def test_unsupported_owner_or_budget_rejects_before_loading(self):
        with self.assertRaisesRegex(SharedFeatureError, "full EG2"):
            BudgetedMediaEncoder(SimpleNamespace(candidate="granite97m", profile="text"))
        with self.assertRaisesRegex(SharedFeatureError, "supported native"):
            BudgetedMediaEncoder(SimpleNamespace(candidate="embeddinggemma2_740m", profile="full"), vision_soft_tokens=1)

    def test_audio_dsp_arrays_bind_values_and_precision(self):
        filters = np.arange(8, dtype=np.float32).reshape(2, 4)
        original = configuration_value({"filters": filters})
        self.assertNotEqual(original, configuration_value({"filters": filters.astype(np.float64)}))
        filters[0, 0] = 1
        self.assertNotEqual(original, configuration_value({"filters": filters}))


if __name__ == "__main__":
    unittest.main()
