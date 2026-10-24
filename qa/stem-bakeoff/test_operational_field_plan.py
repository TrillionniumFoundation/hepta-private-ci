"""Actual native-tokenizer planning binds complete fields without a model."""

import json
from pathlib import Path
import tempfile
import unittest

from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from long_document_sources import canonical, sha
from operational_field_plan import create_plan, field_inputs, verify_plan
from operational_source_regions import ACTION_PREFIX
from test_operational_source_regions import DIFF, TEST_A, TEST_B


def fixture(root):
    tokenizer = root / "tokenizer"
    tokenizer.mkdir()
    native = Tokenizer(models.WordLevel({"[UNK]": 0, "[PAD]": 1, "value": 2, "old_name": 3,
        "new_name": 4, "test_a": 5, "test_b": 6, "unrelated": 7, "other": 8}, unk_token="[UNK]"))
    native.pre_tokenizer = pre_tokenizers.Whitespace()
    fast = PreTrainedTokenizerFast(tokenizer_object=native, unk_token="[UNK]", pad_token="[PAD]")
    fast.save_pretrained(tokenizer)
    (tokenizer / "config.json").write_bytes(canonical({"model_type": "bert", "vocab_size": 9}))
    (tokenizer / "special_tokens_map.json").write_bytes(canonical({"unk_token": "[UNK]", "pad_token": "[PAD]"}))
    rows = []
    for i, action in enumerate((TEST_A, TEST_B)):
        command, test = action.split("\n", 1)
        head = ACTION_PREFIX + DIFF + "\nACTION\n" + command + "\n"
        text = head + test
        rows.append({"source_id": "source-" + str(i), "text": text, "source_version": {"fixture": i},
            "input_template": "operational_single_action_v1", "labels": {"SECRET_OUTCOME": i},
            "repo": "UNUSED_PROJECT_ID", "split": "train", "provenance": {"role": "UNUSED_BUG_FIXED_ROLE"},
            "input_regions": {"change": [len(ACTION_PREFIX), len(ACTION_PREFIX) + len(DIFF)],
                              "action": [len(head), len(text)]},
            "text_utf8_sha256": sha(text.encode()), "text_utf8_bytes": len(text.encode())})
    dataset = root / "dataset.json"
    dataset.write_bytes(canonical({"rows": rows}))
    candidates = json.loads(Path(__file__).with_name("real_encoder_candidates.json").read_bytes())
    acquisition = root / "acquisition.json"
    acquisition.write_bytes(canonical({"candidate": "granite97m", "revision": candidates["granite97m"]["revision"],
        "repository": candidates["granite97m"]["repository"], "inventory_sha256": "b" * 64}))
    plan_root = root / "plan"
    plan = create_plan(dataset, tokenizer, acquisition, plan_root, dataset_sha256=sha(dataset.read_bytes()))
    return dataset, tokenizer, acquisition, plan_root, plan, sha((plan_root / "plan.json").read_bytes())


class FieldPlanTests(unittest.TestCase):
    def test_native_tokenizer_plan_deduplicates_exact_fields_and_keeps_row_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset, _, _, root, plan, pin = fixture(Path(directory))
            self.assertEqual((plan["row_count"], plan["logical_fields"], plan["unique_fields"],
                              plan["exact_field_cache_hits"]), (2, 4, 3, 1))
            self.assertEqual(plan["encoder_calls_during_planning"], 0)
            data, _, mapping, _ = verify_plan(dataset, root, pin)
            self.assertEqual([r["source_id"] for r in mapping], [r["source_id"] for r in data["rows"]])
            self.assertEqual(mapping[0]["field_ids"]["change"], mapping[1]["field_ids"]["change"])
            fields = json.loads((root / "field-dataset.json").read_bytes())
            self.assertTrue(all("SECRET" not in r["text"] and "UNUSED" not in r["text"] for r in fields["rows"]))
            self.assertTrue(all("labels" not in row for row in fields["rows"]))

    def test_metadata_cannot_change_clean_numeric_field_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset, _, _, _, _, _ = fixture(Path(directory))
            data = json.loads(dataset.read_bytes())
            before = field_inputs(data)[1]
            for row in data["rows"]:
                row["labels"], row["repo"], row["provenance"] = {"SECRET_OUTCOME": 999}, "other", {"observed": "failure"}
            self.assertEqual(field_inputs(data)[1], before)

    def test_stale_text_or_field_plan_is_rejected_before_native_export(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset, _, _, root, _, pin = fixture(Path(directory))
            dataset.write_bytes(dataset.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "dataset changed"):
                verify_plan(dataset, root, pin)
            with self.assertRaisesRegex(ValueError, "plan pin"):
                verify_plan(dataset, root, "f" * 64)


if __name__ == "__main__":
    unittest.main()
