"""Synthetic tamper tests and public-input checks; no model inference occurs."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

import freegen_contract as contract
from real_freegen import check_previous

HERE = Path(__file__).parent


class RuntimeContractTests(unittest.TestCase):
    def config(self):
        result = {key: choices[0] for key, choices in contract.NEUTRAL.items()}
        result.update(do_sample=False, num_beams=1, max_new_tokens=8, use_cache=True,
                      eos_token_id=2, pad_token_id=2, bos_token_id=1)
        return result

    def test_neutral_greedy_configuration_accepts_native_special_ids(self):
        contract.check_generation_config(self.config(), 2, 1)

    def test_hidden_logit_and_stop_controls_are_rejected(self):
        for key, value in (("forced_bos_token_id", 42), ("forced_eos_token_id", 2),
                           ("suppress_tokens", [7]), ("begin_suppress_tokens", [8]),
                           ("sequence_bias", {"1": 3.0}), ("stop_strings", ["yes"]),
                           ("max_time", .001), ("min_new_tokens", 8),
                           ("no_repeat_ngram_size", 2), ("repetition_penalty", 1.2),
                           ("guidance_scale", 3.0), ("token_healing", True),
                           ("bad_words_ids", [[8]]), ("num_return_sequences", 2)):
            changed = self.config()
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                contract.check_generation_config(changed, 2, 1)

    def test_assistant_confidence_stopping_is_rejected(self):
        changed = self.config()
        changed["is_assistant"] = True
        changed["assistant_confidence_threshold"] = 0.4
        with self.assertRaisesRegex(ValueError, "is_assistant"):
            contract.check_generation_config(changed, 2, 1)

    def test_special_token_and_primary_decode_mutation_is_rejected(self):
        for key, value in (("bos_token_id", None), ("eos_token_id", 9),
                           ("pad_token_id", 0), ("do_sample", True),
                           ("num_beams", 2), ("max_new_tokens", 9)):
            changed = self.config()
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                contract.check_generation_config(changed, 2, 1)
        with self.assertRaisesRegex(ValueError, "EOS"):
            contract.check_generation_config(self.config(), None, 1)

    def test_model_settings_are_not_mutated_or_silently_sanitized(self):
        class Config:
            def __init__(self, data):
                self.data = data
            def update(self, **changes):
                self.data.update(changes)
            def to_dict(self):
                return self.data
            def get_generation_mode(self):
                return type("Mode", (), {"value": "greedy_search"})()
        tok = type("Tokenizer", (), {"eos_token_id": 2, "bos_token_id": 1})()
        poisoned = self.config()
        poisoned["suppress_tokens"] = [17]
        model = type("Model", (), {"generation_config": Config(poisoned)})()
        before = copy.deepcopy(poisoned)
        with self.assertRaisesRegex(ValueError, "suppress_tokens"):
            contract.resolve_generation_config(model, tok)
        self.assertEqual(model.generation_config.to_dict(), before)

    def test_full_assets_capture_added_and_mutated_tokenizer_generation_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, adapters = root / "model", root / "adapters"
            model.mkdir()
            (model / "config.json").write_text("{}")
            for seed in (11, 17, 23, 29):
                for arm in ("interleaved", "bursty"):
                    path = adapters / f"seed{seed}-{arm}-adapter"
                    path.mkdir(parents=True)
                    (path / "adapter_config.json").write_text("{}")
            initial = contract.asset_manifest(model, adapters)
            (model / "generation_config.json").write_text('{"forced_bos_token_id":9}')
            (model / "tokenizer_config.json").write_text('{"bos_token":"NEW"}')
            changed = contract.asset_manifest(model, adapters)
            self.assertNotEqual(changed, initial)
            self.assertEqual(set(changed["model"]),
                             {"config.json", "generation_config.json", "tokenizer_config.json"})
            (model / "tokenizer_config.json").write_text('{"bos_token":"OLD"}')
            self.assertNotEqual(contract.asset_manifest(model, adapters), changed)

    def test_missing_or_empty_adapter_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "empty asset directory"):
                contract.asset_manifest(root, root)

    def test_public_reference_is_checked_before_any_generation(self):
        tasks = json.loads((HERE / "HPCA_V2_OOD_PLAN.json").read_text())["tasks"]
        self.assertEqual(len(check_previous(HERE / "ACTUAL_OOD_FORWARD_RESULT.json", tasks)), 9)
        for key, value in (("question", "changed prompt"), ("truth", "no"),
                           ("family", "changed family")):
            changed = copy.deepcopy(tasks)
            changed[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "task changed"):
                check_previous(HERE / "ACTUAL_OOD_FORWARD_RESULT.json", changed)

    def test_changed_source_or_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.py"
            path.write_text("original")
            paths = {"runner": path}
            pins = contract.pin_files(paths)
            contract.require_file_pins(paths, pins)
            path.write_text("mutated")
            with self.assertRaisesRegex(ValueError, "frozen file bytes"):
                contract.require_file_pins(paths, pins)

    def test_changed_thread_budget_is_rejected_before_asset_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            for threads in (1, 8):
                args = [sys.executable, str(HERE / "real_freegen.py")]
                for key in ("plan", "archive", "previous", "model", "adapter-root", "out"):
                    args += ["--" + key, str(Path(tmp) / key)]
                args += ["--threads", str(threads)]
                result = subprocess.run(args, capture_output=True, text=True, timeout=10)
                with self.subTest(threads=threads):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("exactly 4 CPU threads", result.stderr)
                    self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_partial_journal_retains_rows_without_a_completion_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            journal = contract.RunJournal(path)
            journal.append("attempt_started", condition="base", task_id="t0")
            journal.append("row_completed", condition="base", row={"id": "t0", "parsed": None})
            journal.append("attempt_started", condition="base", task_id="t1")
            journal.close()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row["sequence"] for row in rows], [0, 1, 2])
            self.assertEqual({row["run_id"] for row in rows}, {journal.run_id})
            self.assertNotIn("rows_complete", [row["kind"] for row in rows])
            with self.assertRaises(FileExistsError):
                contract.RunJournal(path)

    def test_preexecution_record_cannot_be_overwritten_or_contain_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preexecution.json"
            original = {"planned_generations": 216, "independent_future_sources": "MISSING"}
            contract.write_json_exclusive(path, original)
            with self.assertRaises(FileExistsError):
                contract.write_json_exclusive(path, {"planned_generations": 1})
            self.assertEqual(json.loads(path.read_text()), original)
            with self.assertRaises(ValueError):
                contract.write_json_exclusive(Path(tmp) / "invalid.json", {"cost": float("nan")})


if __name__ == "__main__":
    unittest.main()
