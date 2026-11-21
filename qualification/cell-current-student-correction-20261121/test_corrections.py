"""Offline integration checks over the exact retained A archives; no backend imports."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import comparison
import corrections
import learner

ROOT = Path(__file__).resolve().parents[2]


class Tokenizer:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        text = "".join(row["role"] + ":\n" + row["content"] + "<end>\n" for row in messages)
        return text + ("assistant:\n" if add_generation_prompt else "")

    def encode(self, text, add_special_tokens=False):
        return list(text.encode())


class CorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = corrections.assemble(ROOT)
        cls.reader = corrections.load_reader(ROOT)

    def test_actual_state_and_parent_lineage(self):
        pinned, members, _ = self.reader.read_inputs(ROOT)
        expected = {row["project_id"]: row["final_answer"] for row in pinned["prepared/DATASET.json"]}
        for mode, records in self.bundle["records"].items():
            for record in records:
                folder = record["current_failed_state"]["record"]
                request = json.loads(members[folder + "/REQUEST.json"])
                answer = json.loads(members[folder + "/OUTPUT.json"])
                feedback = json.loads(members[folder + "/FEEDBACK.json"])
                self.assertEqual(record["initial_messages"], request["task"]["messages"] +
                                 [{"role": "assistant", "content": answer["answer"]},
                                  {"role": "tool", "content": feedback["content"]}])
                self.assertEqual(record["observed_actor_model_digest"], answer["loaded_model_manifest_digest"])
                self.assertEqual(record["final_answer"], expected[record["project_id"]])
                self.assertNotEqual(record["final_answer"], answer["answer"])
        self.assertEqual(corrections.assemble(ROOT), self.bundle)

    def test_cross_actor_future_and_label_tampering_rejected(self):
        for field, value in (("observed_actor_model_digest", "common-P"),
                             ("split", "future"), ("observed_actions_are_targets", True)):
            with self.subTest(field=field):
                bundle = copy.deepcopy(self.bundle)
                row = bundle["records"]["native_feedback"][0]
                row[field] = value
                row.pop("record_digest")
                row["record_digest"] = corrections.digest(row)
                with self.assertRaises(ValueError):
                    corrections.verify_bundle(bundle)

    def test_modified_archive_is_rejected_before_training_assembly(self):
        real = Path.read_bytes

        def altered(path):
            raw = real(path)
            return raw + b"tamper" if path.name == "A-native_feedback.tar.gz" else raw

        with mock.patch.object(Path, "read_bytes", altered), self.assertRaisesRegex(ValueError, "archive bytes differ"):
            corrections.assemble(ROOT)

    def test_freeze_is_exclusive_and_source_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "prepared"
            frozen = corrections.freeze(ROOT, output)
            loaded, protocol = learner.inputs(output)
            self.assertEqual((loaded, protocol), (self.bundle, frozen))
            with self.assertRaises(FileExistsError):
                corrections.freeze(ROOT, output)
            modified = json.loads((output / "CORRECTIONS.json").read_bytes())
            modified["records"]["native_feedback"][0]["final_answer"] += "bad target"
            (output / "CORRECTIONS.json").write_text(json.dumps(modified))
            with self.assertRaisesRegex(ValueError, "record content changed"):
                learner.inputs(output)

    def test_single_target_comparison_is_explicitly_degenerate(self):
        for records in self.bundle["records"].values():
            with self.assertRaisesRegex(ValueError, "identical"):
                comparison.require_distinct_objectives(records)

    def test_interrupted_update_journal_preserves_uncertain_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "UPDATES.jsonl"
            events = [{"event": "UPDATE_STARTED", "step": 1},
                      {"event": "UPDATE_COMPLETED", "step": 1},
                      {"event": "UPDATE_STARTED", "step": 2}]
            path.write_bytes(b"".join(corrections.canonical(row) + b"\n" for row in events))
            self.assertEqual(learner.update_bounds(path, 8),
                             {"durably_completed_updates": 1, "possible_actual_update_upper_bound": 2,
                              "update_completion_uncertain": True, "journal_complete": True})
            with path.open("ab") as stream:
                stream.write(b'{"event":"UPDATE_COM')
            self.assertEqual(learner.update_bounds(path, 8),
                             {"durably_completed_updates": 1, "possible_actual_update_upper_bound": 8,
                              "update_completion_uncertain": True, "journal_complete": False})

    def test_encoding_masks_all_failed_prefixes(self):
        # Load the exact repository serializer; its unused dataset builder dependency is stubbed.
        path = ROOT / "scripts/cell_experiments/chat_protocol.py"
        spec = importlib.util.spec_from_file_location("encoder_test.chat_protocol", path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict("sys.modules", {"encoder_test.data": types.SimpleNamespace(build_sft_examples=None)}):
            spec.loader.exec_module(module)
        engine = types.SimpleNamespace(chat_protocol=module, partition_target=lambda row, maximum: [row])
        settings = {"sequence_tokens": 30000, "head_chunk_positions": 256}
        for records in self.bundle["records"].values():
            final = learner.encode_groups(engine, Tokenizer(), records, settings)
            self.assertEqual(final, learner.encode_groups(engine, Tokenizer(), records, settings, "all_actions"))
            for group, record in zip(final, records):
                turn = group[0]
                self.assertTrue(all(x == -100 for x in turn["labels"][:turn["prefix_tokens"]]))
                self.assertEqual(bytes(x for x in turn["labels"] if x != -100).decode(),
                                 record["final_answer"] + "<end>\n")
            with self.assertRaisesRegex(ValueError, "no truncation"):
                learner.encode_groups(engine, Tokenizer(), records, {**settings, "sequence_tokens": 1})


if __name__ == "__main__":
    unittest.main()
