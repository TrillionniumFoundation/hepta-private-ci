import json
import tempfile
import unittest
from pathlib import Path

from peft import LoraConfig, get_peft_model
from transformers import BertConfig, BertForSequenceClassification

from pretrained import _canonical_saved_adapter_config
from tensor_contract import canonical_config


class PretrainedConfigTests(unittest.TestCase):
    def test_peft_save_auto_mapping_is_pinned_exactly(self):
        # RelevanceRanker deliberately leaves task_type unset so PEFT keeps the
        # existing classifier head frozen. PEFT 0.17.1 adds auto_mapping only
        # when serializing that config; the reader must pin that stable output.
        base = BertForSequenceClassification(
            BertConfig(
                hidden_size=32,
                intermediate_size=64,
                num_attention_heads=4,
                num_hidden_layers=1,
                num_labels=1,
            )
        )
        model = get_peft_model(
            base,
            LoraConfig(
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=["query", "value"],
                bias="none",
            ),
        )
        with tempfile.TemporaryDirectory() as name:
            destination = Path(name)
            model.save_pretrained(destination, safe_serialization=True)
            actual = json.loads((destination / "adapter_config.json").read_text())
        self.assertIn("auto_mapping", actual)
        self.assertEqual(
            canonical_config(actual),
            _canonical_saved_adapter_config(model, inference_mode=True),
        )


if __name__ == "__main__":
    unittest.main()
