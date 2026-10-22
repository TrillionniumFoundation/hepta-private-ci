import unittest

from run_bazel_with_buildbuddy import bazel_command


class MacosLocalCiTest(unittest.TestCase):
    def test_keyless_ci_keeps_resource_config_without_remote_execution(self):
        command = bazel_command(
            "--output_user_root=/owned/output",
            "test",
            "--config=ci-macos",
            "--",
            "//...",
            "-//third_party/v8:all",
            env={"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"},
        )
        self.assertEqual(
            command,
            [
                "bazel",
                "--noexperimental_remote_repo_contents_cache",
                "--output_user_root=/owned/output",
                "test",
                "--config=ci-bazel",
                "--strategy=TestRunner=darwin-sandbox,local",
                "--",
                "//...",
                "-//third_party/v8:all",
            ],
        )

    def test_explicit_build_options_follow_defaults_and_target_payload_is_exact(self):
        caller = [
            "build",
            "--config=ci-macos",
            "--disk_cache=/caller/cache",
            "--strategy=TestRunner=local",
            "--@rules_rust//rust/settings:extra_rustc_flag=-Cdebuginfo=1",
            "--",
            "//example:target",
            "--config=ci-macos",
        ]
        result = bazel_command(
            *caller, env={"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"}
        )
        self.assertEqual(result[5:], caller[2:])
        self.assertEqual(
            result[3:5],
            ["--config=ci-bazel", "--strategy=TestRunner=darwin-sandbox,local"],
        )

    def test_local_or_other_platform_calls_do_not_gain_ci_defaults(self):
        for env in (
            {},
            {"RUNNER_OS": "macOS"},
            {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"},
        ):
            with self.subTest(env=env):
                result = bazel_command(
                    "build", "--config=ci-macos", "--", "//...", env=env
                )
                self.assertNotIn("--config=ci-bazel", result)
                self.assertNotIn("--strategy=TestRunner=darwin-sandbox,local", result)
                self.assertEqual(result[-2:], ["--", "//..."])

    def test_query_and_application_arguments_do_not_gain_ci_defaults(self):
        env = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"}
        for args in (
            ("query", "--config=ci-macos", "//..."),
            ("run", "//example:target", "--", "--config=ci-macos"),
        ):
            with self.subTest(args=args):
                self.assertNotIn("--config=ci-bazel", bazel_command(*args, env=env))

    def test_authenticated_ci_keeps_original_remote_configuration(self):
        result = bazel_command(
            "test",
            "--config=ci-macos",
            "--",
            "//...",
            env={
                "GITHUB_ACTIONS": "true",
                "RUNNER_OS": "macOS",
                "BUILDBUDDY_API_KEY": "test-key",
            },
        )
        self.assertIn("--config=buildbuddy-generic-rbe", result)
        self.assertIn("--config=ci-macos", result)
        self.assertNotIn("--config=ci-bazel", result)


if __name__ == "__main__":
    unittest.main()
