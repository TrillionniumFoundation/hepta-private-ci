#!/usr/bin/env python3
"""Synthetic command-owner boundary tests; no native execution or cost evidence."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.dont_write_bytecode = True
import run_w1_false_trace_reuse_v1 as runner


class ExecutionBoundaryTests(unittest.TestCase):
    def observe(self, *, before=None, after=None, environment=None, machine="x86_64",
                elf=62, campaign_exit=0, campaign_timeout=False, failed_command=None,
                compiler_release="1.95.0", compiler_host="x86_64-unknown-linux-gnu",
                reader_error=None, alerts=None,
                configuration=None, configuration_place="home", change_configuration=None,
                copy_mismatch=False, change_copy_during_campaign=False,
                change_binary_during_campaign=False, mode=None, shard_exits=None,
                shard_timeouts=(), capture_error_shards=(), shard_reader_error=None,
                wrong_shard_selection=None, grid_reader_error=None, local=True):
        with tempfile.TemporaryDirectory(prefix="false-reuse-v1-owner-test-") as directory:
            root = Path(directory)
            output, target = root / "receipt", root / "target"
            output.mkdir()
            checkout, cargo_home = root / "checkout", root / "cargo-home"
            checkout.mkdir()
            cargo_home.mkdir()
            config_dir = {"home": cargo_home, "checkout": checkout / ".cargo",
                          "ancestor": root / ".cargo"}[configuration_place]
            config_file = config_dir / "config.toml"
            if configuration is not None:
                config_dir.mkdir(exist_ok=True)
                config_file.write_text(configuration)
            commands = []
            example = (runner.LEGAL_V3_EXAMPLE if mode == "legal-strategy-v3" else
                runner.LEGAL_EXAMPLE if mode in ("legal-strategy", "legal-strategy-v2") else runner.EXAMPLE)
            native = target / "x86_64-unknown-linux-gnu/release/examples" / example
            source = {"source_state": "committed-clean", "commit": "a" * 40}

            classes = ("full-rank-field", "zero", "continuity-maintenance-v1",
                "one-zero-left-rank-one", "one-zero-right-rank-one")
            selections = [{"class": name, "target_index": target, "reuse_winners": horizon}
                for name in classes for target in (0, 1) for horizon in (1, 8, 64)]

            def analyze_shard(path):
                index = int(path.stem.split("-")[-1])
                if index == shard_reader_error:
                    raise ValueError("synthetic malformed shard records")
                selection = dict(selections[index])
                if index == wrong_shard_selection:
                    selection["reuse_winners"] = 999
                return {"selection": selection, "semantic_alerts": alerts or []}

            def analyze_grid(paths):
                self.assertEqual([path.name for path in paths],
                    [f"campaign-{index:02d}.stdout" for index in range(30)])
                if grid_reader_error is not None:
                    raise grid_reader_error
                return {"semantic_alerts": alerts or [], "synthetic_paths_seen": [path.name for path in paths]}

            legal_reader = SimpleNamespace(CLASSES=classes, TARGETS=("7f" + "ff" * 31, "07" + "ff" * 31),
                HORIZONS=(1, 8, 64),
                SELECTOR=("--legal-strategy-v3" if mode == "legal-strategy-v3" else
                    "--legal-strategy-v2" if mode == "legal-strategy-v2" else "--legal-strategy-v1"),
                FALSE_FLAGS={key: value for key, value in runner.FALSE_FLAGS.items()
                             if key != "valid_proof_acquisition_used"},
                analyze_shard=analyze_shard, analyze=analyze_grid)

            def capture(command, destination, name, *, timeout, cwd):
                self.assertEqual(cwd, checkout)
                commands.append(command)
                stdout, stderr = destination / (name + ".stdout"), destination / (name + ".stderr")
                stdout.write_text("synthetic boundary fixture\n")
                stderr.write_text("")
                campaign = name == "campaign" or name.startswith("campaign-")
                index = int(name.split("-")[-1]) if name.startswith("campaign-") else None
                if name == "rustc":
                    stdout.write_text("rustc\nrelease: " + compiler_release + "\nhost: " + compiler_host + "\n")
                if name == "build":
                    native.parent.mkdir(parents=True)
                    native.write_bytes(b"\x7fELF\x02\x01" + bytes(12) + elf.to_bytes(2, "little"))
                    if change_configuration is not None:
                        config_dir.mkdir(exist_ok=True)
                        config_file.write_text(change_configuration)
                if campaign and change_copy_during_campaign:
                    (destination / example).write_bytes(b"changed retained binary during campaign")
                if campaign and change_binary_during_campaign:
                    native.write_bytes(b"changed executed binary during campaign")
                if index is not None and index in capture_error_shards:
                    raise OSError("synthetic capture failure after opening raw logs")
                exit_code = (1 if name == failed_command else
                    (shard_exits or {}).get(index, campaign_exit) if campaign else 0)
                return {"command": command, "exit_code": exit_code,
                    "timed_out": campaign and (campaign_timeout or index in shard_timeouts), "timeout_seconds": timeout,
                    "stdout": stdout.name, "stderr": stderr.name}

            actual_copy = runner.shutil.copyfile

            def copy(source, destination):
                if str(source) == "/proc/cpuinfo":
                    Path(destination).write_text("synthetic CPU identity, not hardware evidence\n")
                    return destination
                copied = actual_copy(source, destination)
                if copy_mismatch and Path(destination) == output / example:
                    Path(destination).write_bytes(b"mismatched retained binary copy")
                return copied

            env = {"CARGO_TARGET_DIR": str(target), "CARGO_HOME": str(cargo_home),
                   **(environment or {})}
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(sys, "argv", ["runner", "--arch", "x64"] + (["--local"] if local else [])
                     + (["--" + mode] if mode is not None else [])), \
                 mock.patch.object(runner, "receipt_root", return_value=output) as receipts, \
                 mock.patch.object(runner, "ROOT", checkout), \
                 mock.patch.object(runner, "source", side_effect=[before or source, after or source]), \
                 mock.patch.object(runner.platform, "system", return_value="Linux"), \
                 mock.patch.object(runner.platform, "machine", return_value=machine), \
                 mock.patch.object(runner, "capture", side_effect=capture), \
                 mock.patch.object(runner.shutil, "copyfile", side_effect=copy), \
                 mock.patch.object(runner, "analyze", side_effect=reader_error,
                    return_value={"semantic_alerts": alerts or []}) as original_reader, \
                 mock.patch.object(runner, "legal_strategy_reader", return_value=legal_reader) as versioned_reader, \
                 mock.patch.object(runner, "legal_strategy_v3_reader", return_value=legal_reader) as factorial_reader, \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = runner.main()
                receipts.assert_called_once_with("w1-legal-strategy-v3" if mode == "legal-strategy-v3" else
                    "w1-legal-strategy-v2" if mode == "legal-strategy-v2" else
                    "w1-legal-strategy-v1" if mode == "legal-strategy" else
                    "w1-full-limb-reuse-v1" if mode == "full-limb" else "w1-false-trace-reuse-v1")
                if mode in ("legal-strategy", "legal-strategy-v2"):
                    versioned_reader.assert_called_once_with("v2" if mode == "legal-strategy-v2" else "v1")
                else:
                    versioned_reader.assert_not_called()
                if mode == "legal-strategy-v3":
                    factorial_reader.assert_called_once_with()
                else:
                    factorial_reader.assert_not_called()
                if original_reader.called:
                    expected = {"full_limb": True} if mode == "full-limb" else {}
                    self.assertEqual(original_reader.call_args.kwargs, expected)
            return code, json.loads((output / "manifest.json").read_text()), commands

    def test_explicit_original_release_command_and_selector_are_retained(self):
        code, report, commands = self.observe()
        self.assertEqual(code, 0)
        self.assertEqual(report["execution_context"], "local-native-preflight")
        self.assertEqual(report["schema"], "trnm-w1-false-trace-reuse-execution-v1")
        self.assertTrue(report["default_release_configuration_checked"])
        self.assertIn(["cargo", "+1.95.0", "build", "--locked", "--release", "--manifest-path",
            "trillionnium/Cargo.toml", "--target", "x86_64-unknown-linux-gnu", "-p", "trnm-pon-node",
            "--example", runner.EXAMPLE], commands)
        self.assertEqual(commands[-1][-1], "--false-trace-actual-reuse-v1")
        self.assertFalse(report["source_changed"])
        self.assertEqual({report[key] for key in (
            "binary_sha256_before", "binary_sha256_after",
            "retained_binary_sha256_before", "retained_binary_sha256_after")},
            {report["artifact_sha256"][runner.EXAMPLE]})
        for flag in runner.FALSE_FLAGS:
            self.assertIs(report[flag], False)

    def test_mismatched_retained_binary_is_refused_before_campaign(self):
        code, report, commands = self.observe(copy_mismatch=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 4)
        self.assertNotEqual(commands[-1][-1], runner.SELECTOR)
        self.assertNotIn("reader", report)
        self.assertNotEqual(report["retained_binary_sha256_before"], report["binary_sha256_before"])
        self.assertEqual(report["retained_binary_sha256_before"], report["artifact_sha256"][runner.EXAMPLE])
        self.assertIn("retained binary copy differs", report["error"])

    def test_retained_binary_change_during_campaign_is_refused(self):
        code, report, commands = self.observe(change_copy_during_campaign=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(commands[-1][-1], runner.SELECTOR)
        self.assertEqual(report["binary_sha256_before"], report["binary_sha256_after"])
        self.assertEqual(report["retained_binary_sha256_before"], report["binary_sha256_before"])
        self.assertNotEqual(report["retained_binary_sha256_after"], report["binary_sha256_before"])
        self.assertEqual(report["retained_binary_sha256_after"], report["artifact_sha256"][runner.EXAMPLE])
        self.assertIn("retained binary copy changed", report["error"])

    def test_local_mode_cannot_bypass_dirty_source(self):
        code, report, commands = self.observe(before={"source_state": "dirty-candidate"})
        self.assertNotEqual(code, 0)
        self.assertEqual(commands, [])
        self.assertIn("committed source", report["error"])

    def test_test_build_codegen_override_cannot_be_promoted_to_release(self):
        code, report, commands = self.observe(environment={"CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "64"})
        self.assertNotEqual(code, 0)
        self.assertEqual(commands, [])
        self.assertIn("forbids overrides", report["error"])

    def test_requested_architecture_cannot_replace_observed_machine(self):
        code, _, commands = self.observe(machine="aarch64")
        self.assertNotEqual(code, 0)
        self.assertEqual(commands, [])

    def test_wrong_elf_is_refused_before_campaign(self):
        code, report, commands = self.observe(elf=183)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 4)
        self.assertIn("ELF architecture", report["error"])

    def test_nonzero_native_campaign_is_retained(self):
        code, report, _ = self.observe(campaign_exit=1)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["observations"][-1]["exit_code"], 1)

    def test_zero_or_incomplete_reader_observation_cannot_pass(self):
        code, report, _ = self.observe(reader_error=ValueError("fixed 4-path/9-class false-trace reuse grid incomplete"))
        self.assertNotEqual(code, 0)
        self.assertIn("grid incomplete", report["error"])

    def test_source_change_after_complete_run_still_fails(self):
        code, report, _ = self.observe(after={"source_state": "committed-clean", "commit": "b" * 40})
        self.assertNotEqual(code, 0)
        self.assertTrue(report["source_changed"])

    def test_native_disagreement_cannot_pass_execution_owner(self):
        code, report, _ = self.observe(alerts=[{"outcome": "Product"}])
        self.assertNotEqual(code, 0)
        self.assertEqual(report["reader"]["semantic_alerts"], [{"outcome": "Product"}])

    def test_cargo_aliases_cannot_hide_compiler_flags_or_wrappers_from_rustc_probe(self):
        for name, value in {
            "CARGO_BUILD_RUSTFLAGS": "-C opt-level=0",
            "CARGO_BUILD_RUSTC": "/synthetic/compiler",
            "CARGO_BUILD_RUSTC_WRAPPER": "/synthetic/wrapper",
            "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER": "/synthetic/workspace-wrapper",
            "CARGO_INCREMENTAL": "1", "CARGO_BUILD_INCREMENTAL": "true",
            "CARGO_BUILD_TARGET": "aarch64-unknown-linux-gnu",
        }.items():
            with self.subTest(name=name):
                code, report, commands = self.observe(environment={name: value})
                self.assertNotEqual(code, 0)
                self.assertEqual(commands, [])
                self.assertEqual(report["build_environment_overrides"], {name: value})
                self.assertFalse(report["default_release_configuration_checked"])

    def test_worktree_ancestor_and_cargo_home_codegen_configuration_are_refused(self):
        for place in ("home", "checkout", "ancestor"):
            with self.subTest(place=place):
                code, report, commands = self.observe(configuration_place=place,
                    configuration='[build]\nrustflags = ["-C", "opt-level=0"]\n')
                self.assertNotEqual(code, 0)
                self.assertEqual(commands, [])
                self.assertTrue(report["cargo_configuration_before"]["violations"])
                self.assertFalse(report["default_release_configuration_checked"])

    def test_release_profile_target_env_and_include_are_not_unrecorded_inputs(self):
        for configuration in (
            '[profile.release]\nopt-level = 0\n',
            '[target.x86_64-unknown-linux-gnu]\nrustflags = ["--cfg", "unchecked"]\n',
            '[env]\nRUSTC_BOOTSTRAP = "1"\n',
            'include = ["unobserved.toml"]\n',
            '[build]\nrustc-wrapper = "/synthetic/wrapper"\n',
        ):
            with self.subTest(configuration=configuration):
                code, report, commands = self.observe(configuration=configuration)
                self.assertNotEqual(code, 0)
                self.assertEqual(commands, [])
                self.assertIn("configuration", report["error"])

    def test_verified_vendor_cache_and_job_settings_remain_usable_and_hashed(self):
        configuration = ('[source.crates-io]\nreplace-with = "verified-vendor"\n'
            '[source.verified-vendor]\ndirectory = "/verified/vendor"\n'
            '[build]\njobs = 2\n[net]\noffline = true\n')
        code, report, _ = self.observe(configuration=configuration,
                                      environment={"CARGO_BUILD_JOBS": "2"})
        self.assertEqual(code, 0)
        self.assertEqual(report["build_environment_overrides"], {})
        self.assertTrue(report["default_release_configuration_checked"])
        present = [row for row in report["cargo_configuration_before"]["files"]
                   if row["state"] == "regular"]
        self.assertEqual(len(present), 1)
        self.assertEqual(present[0]["bytes"], len(configuration))
        self.assertEqual(report["cargo_configuration_before"], report["cargo_configuration_after"])

    def test_changed_neutral_configuration_still_invalidates_the_original_input_epoch(self):
        code, report, _ = self.observe(configuration='[build]\njobs = 2\n',
                                      change_configuration='[build]\njobs = 3\n')
        self.assertNotEqual(code, 0)
        self.assertTrue(report["cargo_configuration_changed"])
        self.assertFalse(report["default_release_configuration_checked"])
        self.assertIn("changed", report["cargo_configuration_error"])

    def test_new_configuration_after_start_cannot_escape_absent_path_inventory(self):
        code, report, _ = self.observe(change_configuration='[build]\njobs = 2\n')
        self.assertNotEqual(code, 0)
        self.assertTrue(report["cargo_configuration_changed"])

    def test_invalid_configuration_never_copies_credentials_into_the_receipt(self):
        secret = "synthetic-credential-do-not-retain"
        code, report, commands = self.observe(configuration='[registry]\ntoken = "' + secret)
        self.assertNotEqual(code, 0)
        self.assertEqual(commands, [])
        self.assertNotIn(secret, json.dumps(report))


    def test_zero_exit_timed_out_campaign_is_still_a_failed_observation(self):
        code, report, _ = self.observe(campaign_timeout=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["observations"][-1]["exit_code"], 0)
        self.assertTrue(report["observations"][-1]["timed_out"])
        self.assertNotIn("reader", report)

    def test_original_timeout_contract_is_not_enlarged_for_the_new_campaign(self):
        code, report, _ = self.observe()
        self.assertEqual(code, 0)
        self.assertEqual([item["timeout_seconds"] for item in report["observations"]],
                         [30, 30, 30, 900, 300])

    def test_compiler_claimed_version_and_host_must_match_the_original_contract(self):
        for fields in ({"compiler_release": "1.94.0"}, {"compiler_host": "aarch64-unknown-linux-gnu"}):
            with self.subTest(fields=fields):
                code, report, commands = self.observe(**fields)
                self.assertNotEqual(code, 0)
                self.assertEqual(len(commands), 3)
                self.assertIn("actual compiler", report["error"])

    def test_identity_and_build_failure_cannot_be_relabelled_as_campaign_success(self):
        for command in ("uname", "rustc", "cargo", "build"):
            with self.subTest(command=command):
                code, report, commands = self.observe(failed_command=command)
                self.assertNotEqual(code, 0)
                self.assertEqual(report["observations"][-1]["exit_code"], 1)
                self.assertNotIn("reader", report)
                self.assertNotEqual(commands[-1][-1], runner.SELECTOR)

    def test_source_observation_failure_after_run_still_fails(self):
        code, report, _ = self.observe(after=ValueError("source bytes unavailable"))
        self.assertNotEqual(code, 0)
        self.assertTrue(report["source_changed"])
        self.assertEqual(report["source_after"], {"error": "source bytes unavailable"})

    def test_hosted_run_requires_explicit_expected_source_before_native_commands(self):
        code, report, commands = self.observe(local=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(commands, [])
        self.assertIn("requires explicit TRNM_EXPECTED_SOURCE_SHA", report["error"])
        self.assertIsNone(report["expected_source_commit"])

    def test_supplied_expected_source_must_be_canonical_even_in_local_mode(self):
        for expected in ("", "a" * 39, "a" * 41, "A" * 40, "g" * 40, " " + "a" * 40):
            with self.subTest(expected=expected):
                code, report, commands = self.observe(environment={"TRNM_EXPECTED_SOURCE_SHA": expected})
                self.assertNotEqual(code, 0)
                self.assertEqual(commands, [])
                self.assertIn("40 lowercase hexadecimal", report["error"])
                self.assertIsNone(report["expected_source_commit"])

    def test_clean_other_commit_cannot_replace_explicit_expected_source(self):
        for local in (True, False):
            with self.subTest(local=local):
                code, report, commands = self.observe(local=local,
                    environment={"TRNM_EXPECTED_SOURCE_SHA": "b" * 40})
                self.assertNotEqual(code, 0)
                self.assertEqual(commands, [])
                self.assertIn("does not match explicit expected source", report["error"])
                self.assertEqual(report["expected_source_commit"], "b" * 40)

    def test_local_expected_source_is_optional_but_supplied_match_is_retained(self):
        for expected in (None, "a" * 40):
            with self.subTest(expected=expected):
                code, report, _ = self.observe(environment={} if expected is None else
                    {"TRNM_EXPECTED_SOURCE_SHA": expected})
                self.assertEqual(code, 0)
                self.assertEqual(report["expected_source_commit"], expected)

    def test_hosted_expected_source_match_still_requires_real_hosted_context(self):
        spec = runner.ARCHITECTURES["x64"]
        code, report, _ = self.observe(local=False, environment={
            "TRNM_EXPECTED_SOURCE_SHA": "a" * 40,
            "TRNM_COST_RUNNER_LABEL": spec["runner"], "RUNNER_ARCH": spec["runner_arch"],
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"})
        self.assertEqual(code, 0)
        self.assertEqual(report["execution_context"], "github-hosted")
        self.assertEqual(report["expected_source_commit"], "a" * 40)
        code, report, commands = self.observe(local=False,
            environment={"TRNM_EXPECTED_SOURCE_SHA": "a" * 40})
        self.assertNotEqual(code, 0)
        self.assertEqual(commands, [])
        self.assertIn("hosted runner context", report["error"])

    def test_full_limb_mode_keeps_original_binary_but_uses_separate_explicit_contract(self):
        code, report, commands = self.observe(mode="full-limb")
        self.assertEqual(code, 0)
        self.assertEqual(report["schema"], "trnm-w1-full-limb-reuse-execution-v1")
        self.assertEqual(commands[-2][-1], runner.EXAMPLE)
        self.assertEqual(commands[-1][-1], "--false-trace-full-limb-v1")
        self.assertEqual([item["timeout_seconds"] for item in report["observations"]],
                         [30, 30, 30, 900, 300])
        for flag in runner.FALSE_FLAGS:
            self.assertIs(report[flag], False)

    def test_legal_mode_captures_all_thirty_fixed_shards_and_complete_grid(self):
        code, report, commands = self.observe(mode="legal-strategy")
        self.assertEqual(code, 0)
        self.assertEqual(report["schema"], "trnm-w1-legal-strategy-execution-v1")
        self.assertEqual(commands[3][-1], runner.LEGAL_EXAMPLE)
        self.assertEqual(len(report["shards"]), 30)
        self.assertEqual(len(report["observations"]), 34)
        self.assertEqual(len(report["reader"]["synthetic_paths_seen"]), 30)
        self.assertNotIn("valid_proof_acquisition_used", report)
        self.assertEqual({row["result"] for row in report["shards"]}, {"PASS"})
        for index, (command, row) in enumerate(zip(commands[4:], report["shards"])):
            selection = row["configuration"]
            self.assertEqual(command[1:], ["--legal-strategy-v1", "--class", selection["class"],
                "--target-index", str(selection["target_index"]),
                "--reuse-winners", str(selection["reuse_winners"])])
            self.assertEqual(row["observation"]["timeout_seconds"], 300)
            for extension in ("stdout", "stderr"):
                self.assertIn(f"campaign-{index:02d}.{extension}", report["artifact_sha256"])
        self.assertEqual({report[key] for key in (
            "binary_sha256_before", "binary_sha256_after",
            "retained_binary_sha256_before", "retained_binary_sha256_after")},
            {report["artifact_sha256"][runner.LEGAL_EXAMPLE]})

    def test_v2_captures_all_thirty_shards_with_original_limits_and_separate_identity(self):
        code, report, commands = self.observe(mode="legal-strategy-v2")
        self.assertEqual(code, 0)
        self.assertEqual(report["schema"], "trnm-w1-legal-strategy-execution-v2")
        self.assertEqual(commands[3][-1], runner.LEGAL_EXAMPLE)
        self.assertEqual([row["timeout_seconds"] for row in report["observations"]],
                         [30, 30, 30, 900] + [300] * 30)
        self.assertEqual(len(report["planned_shards"]), 30)
        self.assertEqual(len(report["reader"]["synthetic_paths_seen"]), 30)
        self.assertEqual({row["result"] for row in report["shards"]}, {"PASS"})
        for command, row in zip(commands[4:], report["shards"]):
            selected = row["configuration"]
            self.assertEqual(command[1:], ["--legal-strategy-v2", "--class", selected["class"],
                "--target-index", str(selected["target_index"]),
                "--reuse-winners", str(selected["reuse_winners"])])
        self.assertNotIn("valid_proof_acquisition_used", report)
        for flag in ("hardness_accepted", "work_profile_qualified", "resource_fairness_qualified",
                     "public_service_measured", "production_activation"):
            self.assertIs(report[flag], False)
        self.assertEqual({report[key] for key in ("binary_sha256_before", "binary_sha256_after",
            "retained_binary_sha256_before", "retained_binary_sha256_after")},
            {report["artifact_sha256"][runner.LEGAL_EXAMPLE]})

    def test_v2_failure_timeout_or_missing_records_never_shorten_grid(self):
        for fields in ({"shard_exits": {0: 7}}, {"shard_exits": {29: 7}},
                {"shard_timeouts": (14,)}, {"capture_error_shards": (0, 29)},
                {"shard_reader_error": 29}, {"wrong_shard_selection": 0},
                {"grid_reader_error": ValueError("synthetic incomplete eight-sample grid")},
                {"alerts": [{"sample": 7, "outcome": "Transcript"}]}):
            with self.subTest(fields=fields):
                code, report, commands = self.observe(mode="legal-strategy-v2", **fields)
                self.assertNotEqual(code, 0)
                self.assertEqual(report["schema"], "trnm-w1-legal-strategy-execution-v2")
                self.assertEqual(len(commands), 34)
                self.assertEqual(len(report["shards"]), 30)
                self.assertEqual(report["result"], "FAIL")

    def test_actual_reader_loader_versions_do_not_change_v1_globals(self):
        original = runner.legal_strategy_reader()
        new = runner.legal_strategy_reader("v2")
        self.assertEqual((original.SAMPLES, new.SAMPLES), (2, 8))
        self.assertEqual((original.SELECTOR, new.SELECTOR),
                         ("--legal-strategy-v1", "--legal-strategy-v2"))
        self.assertIs(runner.legal_strategy_reader("v1"), original)
        with self.assertRaisesRegex(ValueError, "fixed legal strategy version"):
            runner.legal_strategy_reader("v3")

    def test_v2_is_mutually_exclusive_with_both_existing_modes(self):
        for other in ("--legal-strategy", "--full-limb"):
            with mock.patch.object(sys, "argv", ["runner", "--arch", "x64", "--local",
                    "--legal-strategy-v2", other]), mock.patch.object(runner, "receipt_root") as receipts, \
                    mock.patch.object(runner, "capture") as capture, redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                runner.main()
            self.assertEqual(error.exception.code, 2)
            receipts.assert_not_called()
            capture.assert_not_called()

    def test_legal_first_middle_or_last_native_failure_cannot_be_dropped(self):
        for index in (0, 14, 29):
            with self.subTest(index=index):
                code, report, commands = self.observe(mode="legal-strategy", shard_exits={index: 7})
                self.assertNotEqual(code, 0)
                self.assertEqual(len(commands), 34)
                self.assertEqual(len(report["shards"]), 30)
                self.assertEqual([i for i, row in enumerate(report["shards"]) if row["result"] == "FAIL"], [index])
                self.assertEqual(report["shards"][index]["observation"]["exit_code"], 7)
                self.assertEqual(len(report["reader"]["synthetic_paths_seen"]), 30)
                self.assertEqual(report["binary_sha256_after"], report["binary_sha256_before"])
                self.assertIn("complete-grid checks failed", report["error"])

    def test_all_thirty_failed_native_shards_remain_failed_even_if_reader_returns_consistency(self):
        code, report, commands = self.observe(mode="legal-strategy", campaign_exit=1)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 34)
        self.assertEqual(len(report["shards"]), 30)
        self.assertEqual({row["result"] for row in report["shards"]}, {"FAIL"})
        self.assertEqual({row["observation"]["exit_code"] for row in report["shards"]}, {1})
        self.assertEqual(len(report["reader"]["synthetic_paths_seen"]), 30)

    def test_legal_last_timeout_at_zero_exit_is_not_a_successful_prefix(self):
        code, report, commands = self.observe(mode="legal-strategy", shard_timeouts=(29,))
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 34)
        self.assertEqual(report["shards"][-1]["result"], "FAIL")
        self.assertEqual(report["shards"][-1]["observation"]["exit_code"], 0)
        self.assertTrue(report["shards"][-1]["observation"]["timed_out"])
        self.assertEqual(report["shards"][-1]["observation"]["timeout_seconds"], 300)

    def test_legal_capture_error_retains_logs_without_fabricating_an_exit_and_continues(self):
        code, report, commands = self.observe(mode="legal-strategy", capture_error_shards=(0, 29))
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 34)
        self.assertEqual(len(report["shards"]), 30)
        self.assertEqual(len(report["observations"]), 32)
        for index in (0, 29):
            row = report["shards"][index]
            self.assertEqual(row["result"], "FAIL")
            self.assertIn("capture_error", row)
            self.assertNotIn("observation", row)
            self.assertIn(f"campaign-{index:02d}.stdout", report["artifact_sha256"])
            self.assertIn(f"campaign-{index:02d}.stderr", report["artifact_sha256"])

    def test_legal_incomplete_or_mislabeled_shard_records_cannot_pass_after_all_commands(self):
        for fields in ({"shard_reader_error": 0}, {"shard_reader_error": 29},
                       {"wrong_shard_selection": 0}, {"wrong_shard_selection": 29}):
            with self.subTest(fields=fields):
                code, report, commands = self.observe(mode="legal-strategy", **fields)
                self.assertNotEqual(code, 0)
                self.assertEqual(len(commands), 34)
                self.assertEqual(len(report["shards"]), 30)
                self.assertEqual(sum(row["result"] == "FAIL" for row in report["shards"]), 1)

    def test_legal_complete_grid_reader_failure_overrides_individual_shard_success(self):
        code, report, commands = self.observe(mode="legal-strategy",
            grid_reader_error=ValueError("synthetic duplicate or incomplete full grid"))
        self.assertNotEqual(code, 0)
        self.assertEqual(len(commands), 34)
        self.assertEqual({row["result"] for row in report["shards"]}, {"PASS"})
        self.assertIn("incomplete full grid", report["reader_error"])
        self.assertNotIn("reader", report)

    def test_legal_native_verifier_disagreement_remains_an_explicit_failure(self):
        code, report, _ = self.observe(mode="legal-strategy", alerts=[{"outcome": "Transcript"}])
        self.assertNotEqual(code, 0)
        self.assertEqual(len(report["shards"]), 30)
        self.assertEqual(report["reader"]["semantic_alerts"], [{"outcome": "Transcript"}])
        self.assertIn("verifier disagreement", report["reader_error"])

    def test_separate_modes_preserve_source_binary_and_retained_copy_guards(self):
        for mode in ("legal-strategy", "legal-strategy-v2", "legal-strategy-v3", "full-limb"):
            for fields in ({"after": {"source_state": "committed-clean", "commit": "b" * 40}},
                           {"change_binary_during_campaign": True},
                           {"change_copy_during_campaign": True}):
                with self.subTest(mode=mode, fields=fields):
                    code, report, commands = self.observe(mode=mode, **fields)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(len(commands), 5 if mode == "full-limb" else 34)
                    self.assertEqual(report["result"], "FAIL")
                    if "after" in fields:
                        self.assertTrue(report["source_changed"])
                    else:
                        self.assertIn("binary", report["error"])

    def test_separate_modes_cannot_bypass_original_early_guards(self):
        for mode in ("legal-strategy", "legal-strategy-v2", "legal-strategy-v3", "full-limb"):
            for fields in ({"before": {"source_state": "dirty-candidate"}},
                           {"environment": {"TRNM_EXPECTED_SOURCE_SHA": "b" * 40}},
                           {"environment": {"RUSTFLAGS": "-C opt-level=0"}},
                           {"configuration": '[build]\nrustc-wrapper="/synthetic/wrapper"\n'},
                           {"local": False}, {"machine": "aarch64"}):
                with self.subTest(mode=mode, fields=fields):
                    code, report, commands = self.observe(mode=mode, **fields)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(commands, [])
                    self.assertNotIn("shards", report)
                    self.assertNotIn("reader", report)

    def test_separate_modes_cannot_bypass_original_elf_or_copy_guards(self):
        for mode in ("legal-strategy", "legal-strategy-v2", "legal-strategy-v3", "full-limb"):
            for fields in ({"elf": 183}, {"copy_mismatch": True}):
                with self.subTest(mode=mode, fields=fields):
                    code, report, commands = self.observe(mode=mode, **fields)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(len(commands), 4)
                    self.assertNotIn("shards", report)
                    self.assertNotIn("reader", report)

    def test_separate_modes_are_mutually_exclusive_before_any_receipt_or_command(self):
        for modes in (("--legal-strategy", "--full-limb"),
                      ("--legal-strategy-v3", "--full-limb"),
                      ("--legal-strategy", "--legal-strategy-v3"),
                      ("--legal-strategy-v2", "--legal-strategy-v3")):
            with self.subTest(modes=modes), \
                 mock.patch.object(sys, "argv", ["runner", "--arch", "x64", "--local", *modes]), \
                 mock.patch.object(runner, "receipt_root") as receipts, \
                 mock.patch.object(runner, "capture") as capture, \
                 redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.main()
            self.assertEqual(error.exception.code, 2)
            receipts.assert_not_called()
            capture.assert_not_called()

    def test_factorial_v3_has_separate_example_schema_and_all_original_budget_shards(self):
        code, report, commands = self.observe(mode="legal-strategy-v3")
        self.assertEqual(code, 0)
        self.assertEqual(report["schema"], "trnm-w1-legal-strategy-execution-v3")
        self.assertEqual(commands[3][-1], runner.LEGAL_V3_EXAMPLE)
        self.assertEqual(len(report["shards"]), 30)
        self.assertEqual(len(report["observations"]), 34)
        self.assertEqual(len(report["reader"]["synthetic_paths_seen"]), 30)
        self.assertEqual([item["timeout_seconds"] for item in report["observations"]],
                         [30, 30, 30, 900] + [300] * 30)
        self.assertEqual({row["result"] for row in report["shards"]}, {"PASS"})
        self.assertNotIn("valid_proof_acquisition_used", report)
        for command, row in zip(commands[4:], report["shards"]):
            selection = row["configuration"]
            self.assertEqual(command[1:], ["--legal-strategy-v3", "--class", selection["class"],
                "--target-index", str(selection["target_index"]),
                "--reuse-winners", str(selection["reuse_winners"])])
        self.assertEqual({report[key] for key in (
            "binary_sha256_before", "binary_sha256_after",
            "retained_binary_sha256_before", "retained_binary_sha256_after")},
            {report["artifact_sha256"][runner.LEGAL_V3_EXAMPLE]})
        for flag in ("hardness_accepted", "work_profile_qualified", "public_network_ready",
                     "production_activation"):
            self.assertIs(report[flag], False)

    def test_factorial_reader_does_not_reinterpret_retained_two_sample_v1_contract(self):
        historical = runner.legal_strategy_reader()
        eight_sample = runner.legal_strategy_reader("v2")
        factorial = runner.legal_strategy_v3_reader()
        self.assertIsNot(historical, factorial)
        self.assertEqual((historical.SELECTOR, historical.SAMPLES), ("--legal-strategy-v1", 2))
        self.assertEqual((eight_sample.SELECTOR, eight_sample.SAMPLES), ("--legal-strategy-v2", 8))
        self.assertEqual((factorial.SELECTOR, factorial.SAMPLES), ("--legal-strategy-v3", 8))
        self.assertNotEqual(historical.SCHEMA, factorial.SCHEMA)
        self.assertNotEqual(eight_sample.SCHEMA, factorial.SCHEMA)
        self.assertEqual(historical.STRATEGIES, eight_sample.STRATEGIES)
        self.assertEqual((len(eight_sample.STRATEGIES), len(factorial.STRATEGIES)), (2, 4))
        self.assertEqual(runner.LEGAL_EXAMPLE, "pon_w1_legal_strategy_v1")
        self.assertEqual(runner.LEGAL_V3_EXAMPLE, "pon_w1_legal_strategy_v3")

    def test_factorial_v3_attempts_all_shards_and_cannot_accept_a_successful_prefix(self):
        cases = [{"shard_exits": {index: 7}} for index in (0, 14, 29)]
        cases += [{"shard_timeouts": (index,)} for index in (0, 14, 29)]
        cases += [{"capture_error_shards": (0, 29)}, {"campaign_exit": 1}]
        for fields in cases:
            with self.subTest(fields=fields):
                code, report, commands = self.observe(mode="legal-strategy-v3", **fields)
                self.assertNotEqual(code, 0)
                self.assertEqual(len(commands), 34)
                self.assertEqual(len(report["shards"]), 30)
                self.assertEqual(len(report["reader"]["synthetic_paths_seen"]), 30)
                self.assertIn("complete-grid checks failed", report["error"])
                failed = [index for index, row in enumerate(report["shards"]) if row["result"] == "FAIL"]
                expected = (list(range(30)) if "campaign_exit" in fields else
                    list(fields.get("shard_exits", fields.get("shard_timeouts", fields.get("capture_error_shards", ())))))
                self.assertEqual(failed, expected)
                for index in failed:
                    row = report["shards"][index]
                    for extension in ("stdout", "stderr"):
                        self.assertIn(f"campaign-{index:02d}.{extension}", report["artifact_sha256"])
                    if index in fields.get("capture_error_shards", ()):
                        self.assertIn("capture_error", row)
                        self.assertNotIn("observation", row)
                    elif index in fields.get("shard_timeouts", ()):
                        self.assertEqual(row["observation"]["exit_code"], 0)
                        self.assertTrue(row["observation"]["timed_out"])

    def test_factorial_v3_reader_failures_or_semantic_alerts_remain_failures(self):
        for fields in ({"shard_reader_error": 0}, {"shard_reader_error": 29},
                       {"wrong_shard_selection": 0}, {"wrong_shard_selection": 29},
                       {"grid_reader_error": ValueError("incomplete factorial grid")},
                       {"alerts": [{"outcome": "Product"}]}):
            with self.subTest(fields=fields):
                code, report, commands = self.observe(mode="legal-strategy-v3", **fields)
                self.assertNotEqual(code, 0)
                self.assertEqual(len(commands), 34)
                self.assertEqual(len(report["shards"]), 30)
                self.assertEqual(report["result"], "FAIL")
                self.assertEqual(report["binary_sha256_before"], report["binary_sha256_after"])


if __name__ == "__main__":
    unittest.main()
