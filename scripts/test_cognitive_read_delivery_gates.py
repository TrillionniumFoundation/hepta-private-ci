from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from cognitive_read_delivery_gates import DELIVERY_GATES
from cognitive_read_delivery_gates import delivery_commands
from cognitive_read_delivery_gates import delivery_gate_passed
from cognitive_read_delivery_gates import delivery_log_problems


def example_log(label: str) -> str:
    _package, _target, binary, cases = DELIVERY_GATES[label]
    rows = "\n".join(f"PASS [ 0.002s] {binary} {case}" for case in cases)
    return f"{rows}\nSummary [0.020s] {len(cases)} tests run: {len(cases)} passed, 0 skipped\n"


class CognitiveDeliveryGateTests(unittest.TestCase):
    def test_four_gates_cover_eleven_distinct_cases(self) -> None:
        self.assertEqual(len(DELIVERY_GATES), 4)
        cases = [case for spec in DELIVERY_GATES.values() for case in spec[3]]
        self.assertEqual(len(cases), 11)
        self.assertEqual(len(set(cases)), 11)

    def test_commands_are_exact_locked_and_read_only(self) -> None:
        for label, command in delivery_commands().items():
            self.assertEqual(command[:3], ["just", "test", "--locked"])
            self.assertIn("--no-tests=fail", command)
            for case in DELIVERY_GATES[label][3]:
                self.assertIn(f"test(={case})", command[-1])
            self.assertNotIn("--features", command)
            self.assertNotIn("--ignored", command)
        self.assertIn("--test", delivery_commands()["delivery-join-tests"])

    def test_actual_pass_rows_and_counts_are_required(self) -> None:
        for label in DELIVERY_GATES:
            self.assertEqual(delivery_log_problems(label, example_log(label)), [])
            self.assertTrue(delivery_log_problems(label, ""))
            self.assertTrue(delivery_log_problems(label, "\n".join(DELIVERY_GATES[label][3])))

    def test_wrong_binary_and_leaf_name_do_not_prove_case(self) -> None:
        for label, spec in DELIVERY_GATES.items():
            body = example_log(label)
            self.assertTrue(delivery_log_problems(label, body.replace(spec[2], "wrong-binary")))
            self.assertTrue(delivery_log_problems(label, body.replace(spec[3][0], spec[3][0].split("::")[-1])))

    def test_zero_or_extra_summary_count_is_rejected(self) -> None:
        for label, spec in DELIVERY_GATES.items():
            body = example_log(label)
            for count in (0, len(spec[3]) + 1):
                changed = body.replace(f"{len(spec[3])} tests run", f"{count} tests run")
                self.assertTrue(delivery_log_problems(label, changed))

    def test_ansi_and_rust_library_binary_spelling_are_supported(self) -> None:
        for label, spec in DELIVERY_GATES.items():
            body = example_log(label).replace(spec[2], spec[2].replace("-", "_"))
            body = body.replace("PASS", "\x1b[32mPASS\x1b[0m")
            self.assertEqual(delivery_log_problems(label, body), [])

    def test_missing_case_is_not_hidden_by_positive_count(self) -> None:
        label = "native-delivery-tests"
        body = example_log(label)
        body = "\n".join(body.splitlines()[1:])
        self.assertTrue(delivery_log_problems(label, body))

    def test_missing_or_failed_command_cannot_report_passed(self) -> None:
        label = "delivery-join-tests"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(delivery_gate_passed(root, label))
            (root / f"{label}.command.json").write_text(json.dumps(delivery_commands()[label]))
            (root / f"{label}.log").write_text(example_log(label))
            code = root / f"{label}.exit-code"
            code.write_text("1\n")
            self.assertFalse(delivery_gate_passed(root, label))
            code.write_text("0\n")
            self.assertTrue(delivery_gate_passed(root, label))

    def test_command_drift_or_unproved_case_cannot_report_passed(self) -> None:
        label = "publication-fence-tests"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / f"{label}.command.json"
            log = root / f"{label}.log"
            (root / f"{label}.exit-code").write_text("0\n")
            log.write_text(example_log(label))
            command.write_text(json.dumps(["echo", "PASS"]))
            self.assertFalse(delivery_gate_passed(root, label))
            command.write_text(json.dumps(delivery_commands()[label]))
            log.write_text("PASS was mentioned in source\n1 tests run\n")
            self.assertFalse(delivery_gate_passed(root, label))

    def test_symlinked_evidence_is_rejected(self) -> None:
        label = "delivery-preparation-tests"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / f"{label}.command.json").write_text(json.dumps(delivery_commands()[label]))
            (root / f"{label}.exit-code").write_text("0\n")
            target = root / "another-candidate.log"
            target.write_text(example_log(label))
            (root / f"{label}.log").symlink_to(target)
            self.assertFalse(delivery_gate_passed(root, label))


if __name__ == "__main__":
    unittest.main()
