"""Failure and provenance adversarial tests, NOT new model generations."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from reader_host_disposition import (
    ARMS,
    HOST_SCHEMA,
    RUN_SCHEMA,
    census,
    inspect,
    sealed,
    sha,
    strict_json,
)

SOURCE = "b" * 40


def host(*, eligible):
    return dict(
        schema=HOST_SCHEMA,
        policy="x86_64-original-qwen-torch2.5.1-cpu-bfloat16-eager",
        new_model_calls=0,
        production_accepted=False,
        host_eligible=eligible,
        cpu_models=["test-only-cpu"],
        machine="x86_64",
        all_cpus_bf16_accelerated=eligible,
        same_original_model_weights_required=True,
    )


def write_files(folder, *, gate=None, rows=None, run=None):
    folder.mkdir()
    files = {"checkout-commit.txt": (SOURCE + "\n").encode()}
    if gate is not None:
        files["host-gate.json"] = json.dumps(gate).encode()
    if rows is not None:
        files["raw-answers.jsonl"] = b"".join(
            json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows
        )
    if run is not None:
        files["run.json"] = json.dumps(run).encode()
    for filename, data in files.items():
        (folder / filename).write_bytes(data)
    manifest = "".join(
        f"{sha(data)}  ./{name}\n" for name, data in sorted(files.items())
    )
    (folder / "SHA256SUMS").write_text(manifest)
    return files


def rows():
    return [
        dict(
            question_id="one",
            arm=arm,
            status="succeeded",
            answer="a real model answer (fixture only)",
            receipt=dict(
                reader_identity="c" * 64,
                trainable_parameters=0,
                answer_postprocessed=False,
            ),
        )
        for arm in ARMS
    ]


def completed_run(raw, *, tier="qwen-3b", index=0):
    return dict(
        schema=RUN_SCHEMA,
        source_commit=SOURCE,
        tier=tier,
        case_index=index,
        raw_sha256=sha(raw),
        reader_identity="c" * 64,
        attempts=5,
        actual_successes=5,
        arms=list(ARMS),
        learned_parameters=0,
        target_labels_exposed=False,
        production_accepted=False,
    )


class HostDispositionTests(unittest.TestCase):
    def test_missing_shards_never_count_as_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = census(Path(tmp), expected_commit=SOURCE)
        self.assertEqual(report["originally_planned_model_calls"], 80)
        self.assertEqual(report["missing_shard_artifacts"], 16)
        self.assertEqual(report["observed_raw_attempt_rows"], 0)
        self.assertEqual(report["complete_original_journal_shards"], 0)
        self.assertIsNone(report["task_success_rate"])
        self.assertFalse(report["production_accepted"])

    def test_real_ineligible_cpu_is_not_reader_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "memory-reader-bottleneck-smol-1.7b-0"
            write_files(folder, gate=host(eligible=False))
            report = census(root, expected_commit=SOURCE)
        self.assertEqual(report["ineligible_hardware_shards"], 1)
        self.assertEqual(report["observed_raw_succeeded_rows"], 0)
        self.assertEqual(report["missing_shard_artifacts"], 15)
        self.assertFalse(report["entire_generation_census_complete"])

    def test_unknown_host_is_not_claimed_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "memory-reader-bottleneck-qwen-3b-1"
            write_files(folder)
            result = inspect(folder, "qwen-3b", 1, expected_commit=SOURCE)
        self.assertIsNone(result["host_eligible"])
        self.assertEqual(result["outcome"], "host_receipt_missing")

    def test_positive_gate_must_match_actual_bf16_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "memory-reader-bottleneck-qwen-3b-1"
            record = host(eligible=True)
            record["all_cpus_bf16_accelerated"] = False
            write_files(folder, gate=record)
            with self.assertRaisesRegex(ValueError, "positive BF16"):
                inspect(folder, "qwen-3b", 1, expected_commit=SOURCE)

    def test_cannot_claim_inference_after_host_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "memory-reader-bottleneck-qwen-3b-1"
            write_files(folder, gate=host(eligible=False), rows=rows())
            with self.assertRaisesRegex(ValueError, "cannot claim"):
                inspect(folder, "qwen-3b", 1, expected_commit=SOURCE)

    def test_edited_original_journal_rejected_even_with_local_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "memory-reader-bottleneck-qwen-3b-0"
            write_files(folder, gate=host(eligible=True), rows=rows())
            raw = folder / "raw-answers.jsonl"
            raw.write_bytes(raw.read_bytes() + b"modified")
            with self.assertRaisesRegex(ValueError, "SHA256SUMS mismatch"):
                sealed(folder)

    def test_completed_originals_do_not_invent_semantic_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "memory-reader-bottleneck-qwen-3b-0"
            raw = b"".join(
                json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows()
            )
            files = write_files(
                folder,
                gate=host(eligible=True),
                rows=rows(),
                run=completed_run(raw),
            )
            self.assertEqual(files["raw-answers.jsonl"], raw)
            report = census(root, expected_commit=SOURCE)
        self.assertEqual(report["observed_raw_attempt_rows"], 5)
        self.assertEqual(report["observed_raw_succeeded_rows"], 5)
        self.assertEqual(report["complete_original_journal_shards"], 1)
        self.assertIsNone(report["reader_capacity_improvement"])
        self.assertFalse(report["independent_semantic_review"])
        self.assertFalse(report["entire_generation_census_complete"])

    def test_incomplete_partial_journal_is_not_complete_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "memory-reader-bottleneck-qwen-3b-0"
            partial = deepcopy(rows()[:2])
            partial[1] = dict(arm=ARMS[1], status="failed", error_type="Timeout")
            write_files(folder, gate=host(eligible=True), rows=partial)
            result = inspect(folder, "qwen-3b", 0, expected_commit=SOURCE)
        self.assertEqual(result["outcome"], "incomplete_original_journal")
        self.assertEqual(result["raw_attempt_rows"], 2)
        self.assertEqual(result["raw_success_rows"], 1)
        self.assertFalse(result["full_original_journal"])

    def test_checkout_and_extra_artifact_names_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "memory-reader-bottleneck-qwen-3b-0"
            write_files(folder, gate=host(eligible=False))
            (folder / "checkout-commit.txt").write_text("a" * 40 + "\n")
            with self.assertRaises(ValueError):
                inspect(folder, "qwen-3b", 0, expected_commit=SOURCE)
            (root / "memory-reader-bottleneck-qwen-3b-99").mkdir()
            with self.assertRaisesRegex(ValueError, "unregistered"):
                census(root, expected_commit=SOURCE)

    def test_duplicate_json_or_fake_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            strict_json(b'{"x":1,"x":2}')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "generating source"):
                census(Path(tmp), expected_commit="not-a-git-sha")


if __name__ == "__main__":
    unittest.main()
