import unittest

from check_windows_private_state_acquisition import CREATION
from check_windows_private_state_acquisition import SUBSTITUTION
from check_windows_private_state_acquisition import check_result


def fixture(lane):
    failed = {"unchecked-create": CREATION, "path-check-open": SUBSTITUTION}.get(lane)
    lines = [
        f"PASS [ 0.1s] codex-utils-path {name}"
        if name != failed
        else f"FAIL [ 0.1s] codex-utils-path {name}"
        for name in (CREATION, SUBSTITUTION)
    ]
    lines.append(
        "Summary [ 0.2s] 2 tests run: "
        + ("1 passed, 1 failed" if failed else "2 passed")
        + ", 15 skipped"
    )
    lines.append(
        "PRIVATE_STATE_ACQUISITION creation denied=true created="
        + ("true" if lane == "unchecked-create" else "false")
    )
    lines.append(
        "PRIVATE_STATE_ACQUISITION substitution "
        + (
            "swapped=true denied=false redirected=true"
            if lane == "path-check-open"
            else "swapped=true denied=true redirected=false"
        )
    )
    return "\n".join(lines) + "\n"


class AcquisitionOracleTests(unittest.TestCase):
    def test_accepts_exact_fixed_outcomes(self):
        for lane in ("positive", "unchecked-create", "path-check-open"):
            with self.subTest(lane=lane):
                check_result(lane, 0 if lane == "positive" else 1, fixture(lane))
                check_result(
                    lane,
                    0 if lane == "positive" else 1,
                    fixture(lane).replace("\n", "\r\n"),
                )

    def test_rejects_compile_failure_or_timeout_as_negative(self):
        for output in ("error[E0308]: compiler failed\n", "test timed out\n", ""):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                check_result("unchecked-create", 1, output)

    def test_rejects_missing_wrong_or_duplicate_evidence(self):
        for lane in ("positive", "unchecked-create", "path-check-open"):
            output = fixture(lane)
            changes = (
                output.replace(CREATION, "wrong_test"),
                output.replace("2 tests run", "1 tests run"),
                output.replace("swapped=true", "swapped=false"),
                output.replace("created=true", "created=false")
                if lane == "unchecked-create"
                else output.replace("denied=true", "denied=false"),
                "\n".join(
                    line for line in output.splitlines() if "Summary" not in line
                ),
                output + "PRIVATE_STATE_ACQUISITION creation denied=true created=false\n",
                output.replace("1 failed", "1 failed, 1 flaky"),
            )
            for changed in changes:
                if changed == output:
                    continue
                with self.subTest(lane=lane, changed=changed), self.assertRaises(RuntimeError):
                    check_result(lane, 0 if lane == "positive" else 1, changed)

    def test_rejects_inverted_command_exit(self):
        for lane in ("positive", "unchecked-create", "path-check-open"):
            with self.subTest(lane=lane), self.assertRaises(RuntimeError):
                check_result(lane, 1 if lane == "positive" else 0, fixture(lane))

    def test_rejects_unknown_negative_control(self):
        with self.assertRaises(RuntimeError):
            check_result("arbitrary-failure", 1, fixture("positive"))

    def test_rejects_signal_exit_even_after_matching_output(self):
        with self.assertRaises(RuntimeError):
            check_result("unchecked-create", -9, fixture("unchecked-create"))


if __name__ == "__main__":
    unittest.main()
