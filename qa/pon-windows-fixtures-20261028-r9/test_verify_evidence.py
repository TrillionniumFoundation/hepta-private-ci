"""Static evidence controls only; no hook or native application is executed."""

import json
import unittest

import verify_evidence as check


class EvidenceControls(unittest.TestCase):
    def setUp(self):
        self.provenance = json.loads((check.QA / "provenance.json").read_text())
        name = "evidence/actual-merge-source.json.xz"
        self.packed = (check.QA / name).read_bytes()
        self.spec = self.provenance["archives"][name]
        frozen = json.loads(check.decode_archive(self.packed, self.spec))
        self.originals = {item["path"]: item["content"] for item in frozen["files"]}

    def test_real_original_bytes_and_all_failed_cases_are_retained(self):
        result = check.verify()
        self.assertEqual(result["actual_merge_source_files"], 15)
        self.assertEqual(
            result["original_failed_cases"]["3"]["unique_failed_cases"], 43
        )
        self.assertEqual(result["original_failed_cases"]["1"]["unique_failed_cases"], 6)
        self.assertFalse(result["native_tests_executed"])
        self.assertFalse(result["windows_blockers_closed"])

    def test_modified_compressed_original_is_rejected(self):
        changed = bytearray(self.packed)
        changed[len(changed) // 2] ^= 1
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            check.decode_archive(bytes(changed), self.spec)

    def test_truncation_and_inconsistent_decode_contract_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "size"):
            check.decode_archive(self.packed[:-1], self.spec)
        spec = {**self.spec, "decoded_bytes": self.spec["decoded_bytes"] - 1}
        with self.assertRaisesRegex(ValueError, "decoded original"):
            check.decode_archive(self.packed, spec)

    def test_a_timeout_increase_cannot_hide_in_the_observer_patch(self):
        fixture = (check.ROOT / check.FIXTURE).read_text()
        queue = (check.ROOT / check.QUEUE).read_text()
        changed = queue.replace("Duration::from_secs(10)", "Duration::from_secs(20)", 1)
        self.assertNotEqual(changed, queue)
        with self.assertRaisesRegex(ValueError, "assertion, timeout or script"):
            check.check_test_scope(self.originals, fixture, changed)

    def test_replaced_interpreter_and_success_exit_are_rejected(self):
        source = (check.ROOT / check.OBSERVER).read_text()
        with self.assertRaisesRegex(ValueError, "interpreter command"):
            check.check_observer(
                source.replace('format!("python3 {}"', 'format!("python {}"')
            )
        with self.assertRaises(ValueError):
            check.check_observer(
                source.replace('exit "$HEPTA_QUEUE_HOOK_EXIT"', "exit 0")
            )


if __name__ == "__main__":
    unittest.main()
