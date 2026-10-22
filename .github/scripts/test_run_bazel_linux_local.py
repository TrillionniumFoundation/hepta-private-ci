import unittest

from run_bazel_with_buildbuddy import bazel_command


class LinuxLocalCiTest(unittest.TestCase):
    def test_keyless_ci_preserves_local_budget_without_remote_platform(self):
        result = bazel_command(
            "--output_user_root=/owned/output",
            "test",
            "--config=ci-linux",
            "--",
            "//...",
            "-//third_party/v8:all",
            env={"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"},
        )
        self.assertEqual(
            result,
            [
                "bazel",
                "--noexperimental_remote_repo_contents_cache",
                "--output_user_root=/owned/output",
                "test",
                "--config=ci-bazel",
                "--",
                "//...",
                "-//third_party/v8:all",
            ],
        )

    def test_explicit_caller_options_and_target_arguments_stay_in_order(self):
        caller = [
            "build",
            "--config=ci-linux",
            "--disk_cache=/caller/cache",
            "--@rules_rust//rust/settings:extra_rustc_flag=-Cdebuginfo=1",
            "--platforms=//:caller-platform",
            "--",
            "//example:target",
            "--config=ci-linux",
        ]
        result = bazel_command(
            *caller, env={"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"}
        )
        self.assertEqual(result[3], "--config=ci-bazel")
        self.assertEqual(result[4:], caller[2:])

    def test_local_or_different_runner_does_not_gain_linux_ci_defaults(self):
        for env in (
            {},
            {"RUNNER_OS": "Linux"},
            {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"},
        ):
            with self.subTest(env=env):
                result = bazel_command(
                    "build", "--config=ci-linux", "--", "//...", env=env
                )
                self.assertNotIn("--config=ci-bazel", result)
                self.assertEqual(result[-2:], ["--", "//..."])

    def test_query_and_application_payload_do_not_gain_linux_ci_defaults(self):
        env = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"}
        for args in (
            ("query", "--config=ci-linux", "//..."),
            ("run", "//example:target", "--", "--config=ci-linux"),
        ):
            with self.subTest(args=args):
                result = bazel_command(*args, env=env)
                self.assertNotIn("--config=ci-bazel", result)
                if "--" in args:
                    self.assertEqual(result[-2:], ["--", "--config=ci-linux"])

    def test_authenticated_ci_keeps_remote_configuration(self):
        result = bazel_command(
            "test",
            "--config=ci-linux",
            "--",
            "//...",
            env={
                "GITHUB_ACTIONS": "true",
                "RUNNER_OS": "Linux",
                "BUILDBUDDY_API_KEY": "test-key",
            },
        )
        self.assertIn("--config=buildbuddy-generic-rbe", result)
        self.assertIn("--config=ci-linux", result)
        self.assertNotIn("--config=ci-bazel", result)


if __name__ == "__main__":
    unittest.main()
