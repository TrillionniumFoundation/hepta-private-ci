#!/usr/bin/env python3
"""Finite keyless-CI and bounded receipt controls, without running Bazel or V8."""

import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import unittest

import run_bazel_with_buildbuddy as wrapper
import v8_source_build_receipt as diagnostics

ROOT = Path(__file__).resolve().parents[2]


class KeylessMacosTests(unittest.TestCase):
    def test_actual_keyless_macos_preserves_base_and_exact_targets(self):
        args = [
            "test",
            "--config=ci-macos",
            "--test_verbose_timeout_warnings",
            "--",
            "//...",
            "-//third_party/v8:all",
        ]
        actual = wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "macOS"})
        self.assertEqual(actual, args)
        self.assertIsNone(wrapper.remote_config(args, {"RUNNER_OS": "macOS"}))

    def test_macos_does_not_preserve_other_remote_platform_configs(self):
        actual = wrapper.bazel_args_with_remote_config(
            [
                "test",
                "--config=ci-linux",
                "--config=ci-v8",
                "--config=ci-windows-cross",
                "--config=ci-macos",
                "--",
                "//...",
            ],
            {"RUNNER_OS": "macOS"},
        )
        self.assertEqual(actual, ["test", "--config=ci-macos", "--", "//..."])

    def test_non_macos_cannot_opt_into_macos_base(self):
        for os_name in ("Linux", "Windows", "", "macos"):
            with self.subTest(os_name=os_name):
                actual = wrapper.bazel_args_with_remote_config(
                    ["build", "--config=ci-macos", "//..."], {"RUNNER_OS": os_name}
                )
                self.assertNotIn("--config=ci-macos", actual)

    def test_keyed_macos_still_uses_generic_rbe_for_this_repository(self):
        actual = wrapper.bazel_args_with_remote_config(
            ["test", "--config=ci-macos", "--", "//..."],
            {
                "RUNNER_OS": "macOS",
                "BUILDBUDDY_API_KEY": "fixture-token",
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "TrillionniumFoundation/hepta-private-ci",
            },
        )
        self.assertEqual(
            actual,
            [
                "test",
                "--config=buildbuddy-generic-rbe",
                "--remote_header=x-buildbuddy-api-key=fixture-token",
                "--config=ci-macos",
                "--",
                "//...",
            ],
        )

    def test_actual_preserved_bazelrc_graph_is_endpoint_free(self):
        rules = {}
        for line in (ROOT / ".bazelrc").read_text().splitlines():
            fields = shlex.split(line, comments=True)
            if fields and fields[0].startswith("common:"):
                rules.setdefault(fields[0].split(":", 1)[1], []).extend(fields[1:])
        pending, visited, expanded = ["ci-macos"], set(), []
        while pending:
            config = pending.pop()
            self.assertNotIn(config, visited, "CI base graph must not cycle")
            visited.add(config)
            self.assertIn(config, rules)
            for arg in rules[config]:
                if arg.startswith("--config="):
                    pending.append(arg.split("=", 1)[1])
                else:
                    expanded.append(arg)
        self.assertEqual(visited, {"ci-macos", "ci-bazel", "ci"})
        self.assertIn(
            "--@rules_rust//rust/settings:extra_rustc_flag=-Cdebuginfo=0", expanded
        )
        self.assertIn(
            "--@rules_rust//rust/settings:extra_exec_rustc_flag=-Cdebuginfo=0", expanded
        )
        self.assertIn("--keep_going", expanded)
        self.assertIn("--strategy=TestRunner=darwin-sandbox,local", expanded)
        forbidden = {
            "--remote_cache",
            "--remote_executor",
            "--remote_header",
            "--remote_cache_header",
            "--remote_exec_header",
            "--bes_backend",
            "--bes_header",
            "--bes_results_url",
            "--experimental_remote_downloader",
            "--credential_helper",
            "--google_credentials",
        }
        self.assertFalse({a.split("=", 1)[0] for a in expanded} & forbidden)


class SourceBuildReceiptTests(unittest.TestCase):
    def observe(self, root, **changes):
        arguments = dict(
            target="x86_64-pc-windows-msvc",
            target_dir=str(root),
            cache_hit="false",
            phase="before",
            upstream_sha="5c15a6995c9bb4bacd3e341b59fff32c909c80bf",
            stats=root / "stats.txt",
        )
        arguments.update(changes)
        return diagnostics.receipt(**arguments)

    def test_real_owned_stats_file_and_directory_are_observations_only(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stats.txt").write_text("Compile requests 0\nCache hits 0\n")
            before = json.loads(self.observe(root))
            self.assertFalse(before["gn_out_directory_observed"])
            self.assertFalse(before["artifact_or_native_qualification"])
            (root / before["target"] / "release" / "gn_out").mkdir(parents=True)
            after = json.loads(self.observe(root, phase="after", cache_hit="true"))
            self.assertTrue(after["gn_out_directory_observed"])
            self.assertEqual(
                after["sccache_statistics"], "Compile requests 0\nCache hits 0\n"
            )
            self.assertLessEqual(
                len(json.dumps(after).encode()), diagnostics.MAX_RECEIPT_BYTES
            )

    def test_unknown_scope_identity_and_hit_reject_without_truncation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stats.txt").write_text("Compile requests 0\n")
            for change in (
                {"target": "unknown"},
                {"phase": "qualified"},
                {"cache_hit": "ready"},
                {"upstream_sha": "0" * 39},
                {"target_dir": "x" * 4097},
            ):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.observe(root, **change)

    def test_oversized_empty_invalid_and_expanding_stats_reject(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for raw in (
                b"",
                b"x" * (diagnostics.MAX_STATS_BYTES + 1),
                b"\xff",
                b"\x00" * diagnostics.MAX_STATS_BYTES,
            ):
                (root / "stats.txt").write_bytes(raw)
                with (
                    self.subTest(size=len(raw)),
                    self.assertRaises((ValueError, UnicodeDecodeError)),
                ):
                    self.observe(root)


if __name__ == "__main__":
    unittest.main()
