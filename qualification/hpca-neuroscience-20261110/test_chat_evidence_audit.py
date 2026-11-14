import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import chat_evidence_audit as audit

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "chat-native-cpu-evidence-20261112" / "execution"


class EvidenceAdmission(unittest.TestCase):
    def setUp(self):
        self.result = (EVIDENCE / "RESULT.json").read_bytes()
        self.pre = (EVIDENCE / "PREEXECUTION.json").read_bytes()
        self.journal = (EVIDENCE / "ROWS.jsonl").read_bytes()
        self.plan = (ROOT / "HPCA_V2_OOD_PLAN.json").read_bytes()

    def mutated(self, change):
        result, pre = json.loads(self.result), json.loads(self.pre)
        journal = [json.loads(line) for line in self.journal.splitlines()]
        change(result, pre, journal)
        pre_bytes = json.dumps(pre).encode()
        journal_bytes = b"".join(json.dumps(r).encode() + b"\n" for r in journal)
        result["preexecution_sha256"] = audit.digest(pre_bytes)
        result["journal_sha256"] = audit.digest(journal_bytes)
        return json.dumps(result).encode(), pre_bytes, journal_bytes

    def rejects(self, change, reason):
        with self.assertRaisesRegex(audit.AuditError, reason):
            audit.audit(*self.mutated(change), self.plan)

    def test_complete_original_bytes(self):
        report = audit.audit(self.result, self.pre, self.journal, self.plan)
        self.assertEqual(report["summary"], {
            "n": 24, "valid": 12, "correct": 6, "first_eos": 0, "independent_future": 0})
        self.assertEqual(report["journal_events"], 49)
        self.assertEqual(report["new_model_inferences"], 0)

    def test_mixed_run_ids_with_consistent_rehash_rejected(self):
        self.rejects(lambda r, p, j: j[11].update(run_id="f"*32), "mixed journal")

    def test_reordered_events_preserve_legacy_grouped_lists_but_fail_adjacency(self):
        def change(result, pre, journal):
            # Same ordered started/completed subsequences accepted by old audit.
            journal[1], journal[2] = journal[2], journal[1]
            for index, record in enumerate(journal):
                record["sequence"] = index
            self.assertEqual([x["task_id"] for x in journal if x["kind"] == "attempt_started"],
                             [x["id"] for x in result["rows"]])
            self.assertEqual([x["row"] for x in journal if x["kind"] == "row_completed"],
                             result["rows"])
        self.rejects(change, "adjacent row completion")

    def test_integer_row_flag_is_not_boolean(self):
        def change(result, pre, journal):
            result["rows"][0]["valid"] = 0
            journal[1]["row"]["valid"] = 0
        self.rejects(change, "row flag")

    def test_boolean_summary_is_not_integer_count(self):
        self.rejects(lambda r, p, j: r["summary"].update(first_eos=False), "summary arithmetic")

    def test_boolean_token_is_not_token_id(self):
        def change(result, pre, journal):
            result["rows"][0]["tokens"][0] = True
            journal[1]["row"]["tokens"][0] = True
        self.rejects(change, "generated token")

    def test_negative_or_nonfinite_cost_rejected(self):
        for value in (-0.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                def change(result, pre, journal):
                    result["rows"][0]["inference_wall_seconds"] = value
                    journal[1]["row"]["inference_wall_seconds"] = value
                self.rejects(change, "time|non-finite")

    def test_duplicate_nested_keys_and_overflow_are_rejected(self):
        for data in (b'{"x":{"a":1,"a":2}}', b'{"x":1e999}', b'{"x":NaN}'):
            with self.subTest(data=data), self.assertRaises(audit.AuditError):
                audit.strict_json(data)

    def test_frozen_truth_cannot_be_changed_with_self_consistent_flags(self):
        def change(result, pre, journal):
            row = result["rows"][0]
            row["truth"] = "no"
            journal[1]["row"] = copy.deepcopy(row)
        self.rejects(change, "frozen truth")

    def test_self_consistently_rehashed_source_manifest_is_not_origin_binding(self):
        self.rejects(lambda r, p, j: p["sources"].update(
            {"chat_wrapper_probe.py": "f"*64}), "frozen source manifest")

    def test_all_generation_controls_and_runtime_are_frozen(self):
        self.rejects(lambda r, p, j: p["config"].update(repetition_penalty=10),
                     "complete generation configuration")
        self.rejects(lambda r, p, j: p["runtime"].update(cpu_threads=8), "frozen runtime")
        self.rejects(lambda r, p, j: p["prompts"][0]["input_ids"].append(99),
                     "frozen prompt token")
        self.rejects(lambda r, p, j: p["model"]["tokenizer.json"].update(sha256="f"*64),
                     "frozen model asset")

    def test_missing_terminal_row_and_sequence_alias_rejected(self):
        self.rejects(lambda r, p, j: j.pop(), "complete journal")
        self.rejects(lambda r, p, j: j[0].update(sequence=False), "journal sequence")

    def test_journal_row_equal_under_python_alias_is_rejected(self):
        self.rejects(lambda r, p, j: j[1]["row"].update(valid=0), "adjacent row completion")

    def test_frozen_original_archive_receipts_match(self):
        report = audit.audit(self.result, self.pre, self.journal, self.plan)
        self.assertIs(report["immutable_recorded_receipts"], True)
        self.assertEqual(
            {name: audit.digest(raw) for name, raw in (
                ("result", self.result), ("preexecution", self.pre),
                ("journal", self.journal))}, audit.ORIGINAL_RECEIPT_SHA256)

    def test_self_consistent_perfect_output_forgery_is_rejected(self):
        def change(result, pre, journal):
            # Forged text and parser flags, but unchanged real token IDs,
            # preexecution/model/source identities and valid task labels.
            for row in result["rows"]:
                row["text"] = "Yes." if row["truth"] == "yes" else "No."
                row["parsed"] = row["truth"]
                row["valid"] = True
                row["correct"] = True
            for i, row in enumerate(result["rows"]):
                journal[2 * i + 1]["row"] = copy.deepcopy(row)
            result["summary"]["valid"] = 24
            result["summary"]["correct"] = 24
        self.rejects(change, "immutable original result receipt")

    def test_self_consistent_cost_laundering_is_rejected(self):
        def change(result, pre, journal):
            # The old arithmetic audit has no immutable RESULT/JOURNAL anchor,
            # so a forged process row with rehashed journal was admissible.
            for i, row in enumerate(result["rows"]):
                row["inference_wall_seconds"] = 0.0
                journal[2 * i + 1]["row"] = copy.deepcopy(row)
        self.rejects(change, "immutable original result receipt")

    def test_cli_rejects_under_python_optimized_mode(self):
        triple = self.mutated(lambda r, p, j: j[11].update(run_id="f"*32))
        with tempfile.TemporaryDirectory() as directory:
            for name, data in zip(("RESULT.json", "PREEXECUTION.json", "ROWS.jsonl"), triple):
                (Path(directory) / name).write_bytes(data)
            process = subprocess.run([
                sys.executable, "-O", str(ROOT / "chat_evidence_audit.py"),
                "--evidence-dir", directory, "--source-dir", str(ROOT)],
                capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertIn("mixed journal run ids", process.stderr)
        self.assertEqual(process.stdout, "")

    def test_cli_original_checks_exact_source_bytes(self):
        process = subprocess.run([
            sys.executable, str(ROOT / "chat_evidence_audit.py"),
            "--evidence-dir", str(EVIDENCE), "--source-dir", str(ROOT)],
            capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["source_files_rechecked"], 6)
        self.assertEqual(report["model_bytes_recheck"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
