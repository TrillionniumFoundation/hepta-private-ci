import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("recovery_controls", Path(__file__).with_name("run.py"))
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


def output(lane):
    pin = "FAIL" if lane == "shared-source" else "PASS"
    snapshot = "FAIL" if lane == "skip-snapshot" else "PASS"
    counts = "2 passed" if lane == "positive" else "1 passed, 1 failed"
    denied = "false" if lane == "shared-source" else "true"
    rejected = "false" if lane == "skip-snapshot" else "true"
    assertion = "assertion failed: left != right" if lane == "shared-source" else "a retained handle does not excuse metadata drift"
    return (
        f"{pin} [0.01s] codex-state {CONTROL.PIN}\n"
        f"{snapshot} [0.01s] codex-state {CONTROL.SNAPSHOT}\n"
        f"WINDOWS_RECOVERY source_pin write_denied={denied} replace_denied={denied}\n"
        f"WINDOWS_RECOVERY metadata changed=true rejected={rejected}\n"
        f"{assertion}\nSummary [0.1s] 2 tests run: {counts}, 100 skipped\n"
    )


class Controls(unittest.TestCase):
    def test_exact_positive_and_two_failure_shapes(self):
        for lane in ("positive", "shared-source", "skip-snapshot"):
            with self.subTest(lane=lane):
                CONTROL.check_result(lane, 0 if lane == "positive" else 1, output(lane))

    def test_exit_and_compile_failures_never_qualify(self):
        for lane in ("positive", "shared-source", "skip-snapshot"):
            for code in (-9, 37, 101, 124):
                with self.subTest(lane=lane, code=code), self.assertRaises(RuntimeError):
                    CONTROL.check_result(lane, code, output(lane))
        with self.assertRaises(RuntimeError):
            CONTROL.check_result("shared-source", 1, "error[E0308]: mismatched types")

    def test_missing_wrong_or_extra_cases_never_qualify(self):
        valid = output("shared-source")
        for mutation in (
            valid.replace(CONTROL.PIN, "unrelated"),
            valid.replace("FAIL [0.01s]", "PASS [0.01s]"),
            valid + "PASS [0.01s] codex-state unexpected\n",
            valid.replace("2 tests run", "1 tests run"),
            valid + "Summary [0.1s] 2 tests run: 1 passed, 1 failed, 100 skipped\n",
        ):
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                CONTROL.check_result("shared-source", 1, mutation)

    def test_actual_attack_observation_and_expected_assertion_are_required(self):
        for lane in ("shared-source", "skip-snapshot"):
            valid = output(lane)
            for mutation in (
                valid.replace("WINDOWS_RECOVERY", "missing"),
                valid.replace("changed=true", "changed=false"),
                valid.replace("write_denied=false", "write_denied=true") if lane == "shared-source" else valid.replace("rejected=false", "rejected=true"),
                valid.replace("assertion failed: left != right", "other panic") if lane == "shared-source" else valid.replace("a retained handle does not excuse metadata drift", "other panic"),
            ):
                with self.subTest(lane=lane), self.assertRaises(RuntimeError):
                    CONTROL.check_result(lane, 1, mutation)


if __name__ == "__main__":
    unittest.main()
