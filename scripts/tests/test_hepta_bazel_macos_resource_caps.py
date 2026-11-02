"""Fail-closed declaration regressions for hosted macOS Bazel resource caps.

These are structural tests, not a substitute for real on-host Bazel execution.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / ".github" / "scripts" / "run-bazel-ci.sh"
GUARD = 'if [[ "${RUNNER_OS:-}" == "macOS" && "${GITHUB_ACTIONS:-}" == "true" ]]; then'
CAPS = (
    "post_config_bazel_args+=(--jobs=24 --loading_phase_threads=8 --local_test_jobs=8)"
)


def validate_policy(source: str) -> None:
    """Reject unscoped, incomplete or test-filtering resource modifications."""
    assert source.count(GUARD) == 1, "resource cap must require hosted macOS"
    assert source.count(CAPS) == 1, "all three Bazel caps are mandatory"
    assert source.index("post_config_bazel_args=()") < source.index(GUARD)
    body = source.split(GUARD, 1)[1].split("\nfi\n", 1)[0]
    assert CAPS in body, "caps must be inside the hosted macOS guard"
    for forbidden in (
        "--test_tag_filters",
        "--test_filter",
        "--build_tag_filters",
        "CODEX_BAZEL_TEST_SKIP_FILTERS",
        "--flaky_test_attempts",
    ):
        assert forbidden not in body, f"cannot change test selection: {forbidden}"


class HostedMacosBazelResourceCapsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WRAPPER.read_text(encoding="utf-8")

    def test_exact_hosted_macos_policy_is_present(self) -> None:
        validate_policy(self.source)

    def test_unscoped_linux_or_missing_github_guard_is_rejected(self) -> None:
        for mutation in (
            GUARD.replace('"macOS"', '"Linux"'),
            GUARD.replace(' && "${GITHUB_ACTIONS:-}" == "true"', ""),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                validate_policy(self.source.replace(GUARD, mutation, 1))

    def test_missing_each_individual_cap_is_rejected(self) -> None:
        for flag in ("--jobs=24", "--loading_phase_threads=8", "--local_test_jobs=8"):
            with self.subTest(flag=flag), self.assertRaises(AssertionError):
                validate_policy(self.source.replace(flag, "", 1))

    def test_caps_outside_guard_are_rejected(self) -> None:
        with self.assertRaises(AssertionError):
            validate_policy(
                self.source.replace(CAPS, "", 1).replace(
                    "post_config_bazel_args=()", "post_config_bazel_args=()\n" + CAPS, 1
                )
            )

    def test_attempted_test_exclusion_is_rejected(self) -> None:
        with self.assertRaises(AssertionError):
            validate_policy(
                self.source.replace(
                    CAPS,
                    CAPS + "\n  post_config_bazel_args+=(--test_tag_filters=-native)",
                    1,
                )
            )


if __name__ == "__main__":
    unittest.main()
