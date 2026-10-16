"""Source-only strict receipt tests. All workload values here are synthetic fixtures."""


import json
from pathlib import Path
import tempfile
import unittest

from native_compute_receipt import AuditError, load_original, make_receipt, no_duplicate_keys


HEAD = "a" * 40


def sample(count):
    stats = lambda setup: {"setup_ns": setup, "p50_ns": 10, "p95_ns": 20, "p99_ns": 30}
    return {
        "schema": "hepta.nativecell.cpu-local-vs-ipc.v1",
        "measured_calls_per_repetition": count,
        "warmup_calls": 16, "repetitions_per_arm": 2,
        "input_frame_bytes": 256, "result_frame_bytes": 64,
        "kernel": "compiled-q24-dot16",
        "in_process": [stats(0), stats(0)],
        "two_process": [stats(100), stats(200)],
        "same_original_input_and_kernel": True,
        "all_original_outputs_match": True,
        "separate_processes": True,
        "mcp_comparison": False,
        "os_ui_effect": False,
        "model_executed": False,
        "jit_or_executable_memory": False,
        "peer_authentication_verified": False,
        "production_authorized": False,
    }


class TestNativeComputeReceipt(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, row):
        path = self.root / name
        path.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
        return path

    def test_good_strict_smoke_and_full_and_no_positive_claims(self):
        a = self.write("smoke.json", sample(64))
        b = self.write("full.json", sample(1024))
        source = self.root / "original.rs"
        source.write_text("// fixture only\n", encoding="utf-8")
        receipt = make_receipt(a, b, source, HEAD, "x86_64")
        self.assertFalse(receipt["production_authorized"])
        self.assertFalse(receipt["host_cryptographically_attested"])
        self.assertFalse(receipt["mcp_or_external_computer_use_compared"])
        self.assertEqual(list(receipt["arms"]), ["smoke_64", "full_1024"])

    def test_rejects_duplicate_json_keys(self):
        path = self.root / "dup.json"
        path.write_text('{"schema": "x", "schema": "y"}', encoding="utf-8")
        with self.assertRaises(AuditError):
            load_original(path, 64)
        with self.assertRaises(AuditError):
            no_duplicate_keys([("nested", 1), ("nested", 2)])

    def test_rejects_nan_and_infinity(self):
        for raw in ('{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}'):
            path = self.root / "nonfinite.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(AuditError):
                load_original(path, 64)

    def test_rejects_count_and_schema_drift(self):
        for field, replacement in (("schema", "other"), ("measured_calls_per_repetition", 32),
                                   ("result_frame_bytes", 32), ("kernel", "jit")):
            row = sample(64)
            row[field] = replacement
            with self.subTest(field=field), self.assertRaises(AuditError):
                load_original(self.write("drift.json", row), 64)

    def test_rejects_false_proof_and_unauthorized_effect_claims(self):
        for field, replacement in (("all_original_outputs_match", False),
                                   ("same_original_input_and_kernel", False),
                                   ("production_authorized", True),
                                   ("os_ui_effect", True),
                                   ("mcp_comparison", True),
                                   ("model_executed", True),
                                   ("peer_authentication_verified", True),
                                   ("jit_or_executable_memory", True)):
            row = sample(64)
            row[field] = replacement
            with self.subTest(field=field), self.assertRaises(AuditError):
                load_original(self.write("flags.json", row), 64)

    def test_rejects_missing_or_fake_repetition(self):
        for runs in ([], [sample(64)["in_process"][0]], "not-a-list"):
            row = sample(64)
            row["in_process"] = runs
            with self.subTest(runs=runs), self.assertRaises(AuditError):
                load_original(self.write("repetition.json", row), 64)

    def test_rejects_bad_timings_and_boolean_pretending_int(self):
        for invalid in (True, -1, 0, 3.1):
            row = sample(64)
            row["two_process"][0]["p95_ns"] = invalid
            with self.subTest(value=invalid), self.assertRaises(AuditError):
                load_original(self.write("timing.json", row), 64)
        row = sample(64)
        row["in_process"][0]["setup_ns"] = 30
        with self.assertRaises(AuditError):
            load_original(self.write("local-setup.json", row), 64)
        row = sample(64)
        row["two_process"][0]["setup_ns"] = 0
        with self.assertRaises(AuditError):
            load_original(self.write("remote-setup.json", row), 64)

    def test_symlinks_and_missing_files_are_not_original_results(self):
        valid = self.write("actual.json", sample(64))
        link = self.root / "link.json"
        link.symlink_to(valid)
        with self.assertRaises((OSError, AuditError)):
            load_original(link, 64)
        with self.assertRaises((OSError, AuditError)):
            load_original(self.root / "absent.json", 64)

    def test_refuses_wrong_head_architecture_and_source(self):
        a = self.write("s.json", sample(64))
        b = self.write("f.json", sample(1024))
        src = self.write("code.rs", {"not": "actual-source"})
        for head, arch in (("short", "x86_64"), (HEAD, "gpu")):
            with self.subTest(head=head, arch=arch), self.assertRaises(AuditError):
                make_receipt(a, b, src, head, arch)
        with self.assertRaises((AuditError, OSError)):
            make_receipt(a, b, self.root / "unknown.rs", HEAD, "x86_64")

    def test_refuses_extra_keys_wrong_types_and_noncanonical_nulls(self):
        for key, value in (("sneaky", 1), ("production_authorized", None),
                           ("measured_calls_per_repetition", True)):
            row = sample(64)
            row[key] = value
            with self.subTest(key=key), self.assertRaises(AuditError):
                load_original(self.write("unknown.json", row), 64)

    def test_refuses_oversized_input(self):
        path = self.root / "large.json"
        path.write_bytes(b"x" * (131_072 + 1))
        with self.assertRaises(AuditError):
            load_original(path, 64)


if __name__ == "__main__":
    unittest.main()
