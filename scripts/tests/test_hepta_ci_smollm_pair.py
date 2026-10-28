"""Static wiring and rejection controls; never execute a model or native test."""

import copy
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import textwrap
import tomllib
import unittest
from unittest.mock import patch

from scripts import hepta_ci_smollm_common as pair
from scripts import hepta_ci_smollm_readback as reader
from scripts import hepta_ci_smollm_resources as resources
from scripts import hepta_ci_smollm_cell as cell

WORKFLOW = pair.ROOT / ".github/workflows/hepta-pon-native-pair.yml"
CELL_WORKFLOW = pair.ROOT / ".github/workflows/hepta-cell-smollm.yml"
NEXTTEST = pair.ROOT / "codex-rs/.config/nextest.toml"
START = "      - name: Prepare fixed public SmolLM material and three original CPU training generations\n"
END = (
    "      - name: Require actual ranker and independent selection lifetime controls\n"
)


def check_wiring(workflow, config):
    profile = tomllib.loads(config)["profile"][pair.PROFILE]
    expected = (
        f"(package(=codex-hepta-infer-worker-host) & test(={pair.NATIVE})) "
        f"| (package(=codex-hepta-agentd) & binary(=neural_comparison_native) & test(={pair.COMPARISON}))"
    )
    pair.require(
        set(profile) == {"retries", "test-threads", "slow-timeout", "default-filter"},
        "profile scope",
    )
    pair.require(
        profile["retries"] == 0 and profile["test-threads"] == 1,
        "zero retry and serialization",
    )
    pair.require(
        profile["slow-timeout"] == {"period": "60s", "terminate-after": 15},
        "bounded first harness budget",
    )
    pair.require(
        " ".join(profile["default-filter"].split()) == expected,
        "exact two-selector profile",
    )
    block = workflow.split(START, 1)[1].split(END, 1)[0]
    pair.require(
        block.count("scripts/hepta_ci_smollm_pair.py prepare") == 1,
        "one preparation dispatch",
    )
    pair.require(
        block.count("scripts/hepta_ci_smollm_pair.py verify") == 1,
        "original readback required",
    )
    pair.require(
        block.count("steps.smollm_prepare.outcome == 'success'") == 4,
        "prepared input gating",
    )
    pair.require(
        block.count("matrix.runner == 'ubuntu-24.04'") == 5, "declared x86 lane only"
    )
    pair.require(
        "continue-on-error" not in block and "|| true" not in block,
        "no success fallback",
    )
    selected = [line.strip() for line in block.splitlines() if " -- just test " in line]
    pair.require(
        len(selected) == 3, "material and both original native dispatches required"
    )
    for line, kind in zip(selected, ("material", "native", "comparison")):
        pair.require("--minimum-tests 1 --" in line, "nonempty actual test observation")
        pair.require(
            shlex.split(line.split(" -- ", 1)[1]) == pair.command(kind),
            "exact native command",
        )
    pair.require(
        "python3 -m unittest -v scripts.tests.test_hepta_ci_smollm_pair" in workflow,
        "reader must run in CI",
    )
    material = tomllib.loads(config)["profile"]["smollm-material"]
    pair.require(
        material
        == {
            "retries": 0,
            "test-threads": 1,
            "slow-timeout": {"period": "60s", "terminate-after": 15},
            "default-filter": "package(=codex-hepta-agentd) & binary(=neural_artifact_native) "
            + f"& test(={pair.MATERIAL})",
        },
        "original material owner scope",
    )
    pair.require(
        "-p trnm-data-availability --bin trnm-cell" in block
        and 'export HEPTA_PON_CELL_SHA256="$(sha256sum "$HEPTA_PON_CELL_BINARY"'
        in block,
        "actual paired Cell executable and digest required",
    )
    return block


class WiringTests(unittest.TestCase):
    def test_parallel_cell_job_keeps_the_original_owners_and_both_exact_sources(self):
        original, isolated = WORKFLOW.read_text(), CELL_WORKFLOW.read_text()
        check_wiring(isolated, NEXTTEST.read_text())
        self.assertIn("runner: [ubuntu-24.04]\n", isolated)
        self.assertIn("lane: [source-head, base-merge]\n", isolated)
        self.assertIn("timeout-minutes: 60\n", isolated)
        self.assertIn("cancel-in-progress: false\n", isolated)
        self.assertNotIn("continue-on-error", isolated)

        def env(text):
            return text.split("    env:\n", 1)[1].split("    steps:\n", 1)[0]

        self.assertEqual(env(original), env(isolated))

        def steps(text):
            return re.findall(
                r"^      - [\s\S]*?(?=^      - |\Z)",
                text.split("    steps:\n", 1)[1].split("  windows-ledger:\n", 1)[0],
                flags=re.M,
            )

        original_steps = [step.rstrip() for step in steps(original)]
        self.assertEqual(isolated.count("      - uses: actions/checkout@"), 2)
        for step in steps(isolated):
            title = step.splitlines()[0]
            if (
                "Preserve exact tested source" not in title
                and "upload-artifact@" not in title
            ):
                self.assertIn(step.rstrip(), original_steps, title)
            if "        run: |\n" in step:
                shell = textwrap.dedent(step.split("        run: |\n", 1)[1])
                result = subprocess.run(
                    ["bash", "-n"], input=shell, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_workflow_and_shell_bodies_are_valid_without_execution(self):
        block = check_wiring(WORKFLOW.read_text(), NEXTTEST.read_text())
        for step in re.split(r"^      - name:", block, flags=re.M):
            if "        run: |\n" in step:
                shell = textwrap.dedent(step.split("        run: |\n", 1)[1])
                result = subprocess.run(
                    ["bash", "-n"], input=shell, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_profile_cannot_retry_expand_selectors_or_remove_watchdog(self):
        workflow, config = WORKFLOW.read_text(), NEXTTEST.read_text()
        original = config.split("[profile.smollm-pair]", 1)[1].split(
            "[test-groups.", 1
        )[0]
        for old, new in (
            ("retries = 0", "retries = 1"),
            ("test-threads = 1", "test-threads = 2"),
            ("terminate-after = 15", "terminate-after = 0"),
            (f"test(={pair.NATIVE})", "all()"),
            (f"test(={pair.COMPARISON})", "none()"),
        ):
            with self.subTest(new=new), self.assertRaises(ValueError):
                check_wiring(
                    workflow, config.replace(original, original.replace(old, new))
                )

    def test_workflow_cannot_skip_ignored_case_retry_or_ignore_failure(self):
        workflow, config = WORKFLOW.read_text(), NEXTTEST.read_text()
        original = workflow.split(START, 1)[1].split(END, 1)[0]
        changes = [
            ("--run-ignored only", ""),
            ("--retries 0", "--retries 1"),
            ("--minimum-tests 1", "--minimum-tests 0"),
            ("--no-capture", "--no-capture || true"),
            (
                "scripts/hepta_ci_smollm_pair.py verify",
                "scripts/hepta_ci_smollm_pair.py omitted",
            ),
            ("matrix.runner == 'ubuntu-24.04'", "matrix.runner == 'ubuntu-24.04-arm'"),
            ("steps.smollm_prepare.outcome == 'success'", "always()"),
        ]
        for old, new in changes:
            with self.subTest(new=new), self.assertRaises(ValueError):
                check_wiring(
                    workflow.replace(original, original.replace(old, new)), config
                )


class RejectionTests(unittest.TestCase):
    def test_cell_acquisition_cannot_use_warm_cache_omit_chunks_or_launder_budget(self):
        release = dict(release="a" * 64, cells=11, payload_bytes=10000, chunks=12)
        value = dict(
            release,
            cached_chunks=0,
            downloaded_chunks=12,
            connection_attempts=23,
            received_response_bytes=11000,
        )
        cell.acquisition_counts(value, release, 46, 12000)
        changes = [
            {"cached_chunks": 1},
            {"cached_chunks": False},
            {"downloaded_chunks": 11},
            {"connection_attempts": 0},
            {"connection_attempts": True},
            {"connection_attempts": 47},
            {"received_response_bytes": 12001},
            {"received_response_bytes": 0},
            {"cells": 10},
            {"release": "b" * 64},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                cell.acquisition_counts(dict(value, **change), release, 46, 12000)

    def test_cell_relocation_preserves_every_original_model_identity_field(self):
        original = dict(
            schema="original",
            generation=3,
            operation_id="training-3",
            directory="/source",
            contract="c",
            adapter="a",
            file_sha256="f",
        )
        target = Path("/consumer")
        relocated = dict(original, directory=str(target))
        cell.relocated_parent(original, relocated, target)
        for field in original:
            with self.subTest(field=field), self.assertRaises(ValueError):
                cell.relocated_parent(
                    original, dict(relocated, **{field: "foreign"}), target
                )

    def test_host_memory_cannot_hide_tighter_visible_enclosing_cgroup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, mount = root / "proc", root / "cgroup mount"
            proc.mkdir()
            leaf = mount / "lane"
            leaf.mkdir(parents=True)
            (proc / "cgroup").write_text("0::/job/lane\n")
            escaped_mount = str(mount).replace(" ", r"\040")
            (proc / "mountinfo").write_text(
                f"1 0 0:1 /job {escaped_mount} ro - cgroup2 cgroup2 rw\n"
                f"2 0 0:1 /job/lane {root}/nested-bind ro - cgroup2 cgroup2 rw\n"
            )
            for group, limit, current in (
                (leaf, "max", 1024),
                (mount, str(4 * 1024**3), 1024**3),
            ):
                (group / "memory.max").write_text(limit)
                (group / "memory.current").write_text(str(current))
            observation = resources.cgroup_memory(proc)
            self.assertEqual(observation["visible_finite_headroom_bytes"], 3 * 1024**3)
            self.assertEqual(observation["hidden_ancestor_limits"], "unknown")
            self.assertEqual(observation["visible_groups"][0]["memory.max"], "max")
            with patch.object(resources, "cgroup_memory", return_value=observation):
                snapshot = resources.resource_snapshot(root)
            snapshot.update(
                host_memavailable_bytes=128 * 1024**3, free_disk_bytes=32 * 1024**3
            )
            with self.assertRaisesRegex(ValueError, "cgroup headroom"):
                resources.require_provisioning(snapshot)
            self.assertIsNone(snapshot["effective_allocatable_memory_bytes"])
            self.assertFalse(snapshot["capacity_guaranteed"])

    def test_absent_or_malformed_cgroup_memory_remains_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "cgroup").write_text("5:memory:/legacy\n")
            (proc / "mountinfo").write_text("")
            observation = resources.cgroup_memory(proc)
            self.assertEqual(observation["status"], "unknown")
            self.assertIsNone(observation["visible_finite_headroom_bytes"])
            self.assertTrue(observation["errors"])
            (proc / "cgroup").write_text("0::/../../foreign\n")
            self.assertEqual(resources.cgroup_memory(proc)["visible_groups"], [])
            (proc / "cgroup").write_text("0::/\n")
            (proc / "mountinfo").write_text(
                f"1 0 0:1 / {proc} ro - cgroup2 cgroup2 rw\n"
            )
            (proc / "memory.max").write_text("not-a-limit")
            observation = resources.cgroup_memory(proc)
            self.assertEqual(observation["status"], "partial")
            self.assertIsNone(observation["visible_finite_headroom_bytes"])
            self.assertIsNone(observation["visible_groups"][0]["memory.max"])
            self.assertIsNone(observation["visible_groups"][0]["memory.current"])

    def test_duplicate_json_and_symlink_cannot_supply_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text('{"status":"failed","status":"passed"}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                pair.read(path)
            path.write_text('{"score":NaN}')
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                pair.read(path)
            link = path.with_name("alias.json")
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "regular file"):
                pair.read(link)

    def test_reported_scores_cannot_be_missing_boolean_or_outside_original_i64(self):
        for value in (None, [], [0], [0, 1, 2], [True, 0], [0.5, 0], [1 << 63, 0]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reader.scores(value)

    def test_synthetic_negative_records_cannot_escalate_or_duplicate_original_claims(
        self,
    ):
        # Parser fixtures only. No fixture is accepted as a native execution,
        # and this test does not create a successful native/provider receipt.
        value = dict.fromkeys(pair.DENIED, False)
        value.update(
            schema="negative-control",
            original_control_reopen_exact=True,
            terminal_unload_observed=True,
            original_final_use_claims=3,
            original_control_requests=["a", "b", "c"],
        )
        variants = [dict(value, **{key: True}) for key in pair.DENIED]
        variants += [
            dict(value, original_control_requests=["a", "a", "c"]),
            dict(value, original_control_requests="abc"),
            dict(value, terminal_unload_observed=False),
            dict(value, original_control_reopen_exact=False),
            dict(value, original_final_use_claims=True),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "negative.json"
            for index, item in enumerate(variants):
                path.write_text(json.dumps(item))
                with self.subTest(index=index), self.assertRaises(ValueError):
                    reader.original_result(path, "negative-control", 3)

    def test_failed_retried_foreign_or_empty_native_record_cannot_pass(self):
        source = {
            "source_sha": "1" * 40,
            "base_sha": "2" * 40,
            "tested_sha": "1" * 40,
            "tested_tree": "4" * 40,
            "lane": "source-head",
        }
        value = dict(
            source,
            status="passed",
            exit_code=0,
            command_exit_code=0,
            command=pair.command("native"),
            minimum_tests=1,
            observed_passed_tests=1,
            observed_failed_tests=0,
            timed_out=False,
            output_limit_exceeded=False,
            before={"commit": "1" * 40, "tree": "4" * 40, "dirty": False},
            after={"commit": "1" * 40, "tree": "4" * 40, "dirty": False},
            run_id="42",
            run_attempt="1",
            job="pair",
        )
        variants = [
            dict(value, status="running"),
            dict(value, observed_passed_tests=0),
            dict(value, observed_passed_tests=True),
            dict(value, observed_passed_tests=2),
            dict(value, command_exit_code=1),
            dict(value, timed_out=True),
            dict(value, run_attempt="2"),
            dict(value, source_sha="3" * 40),
        ]
        retry = copy.deepcopy(value)
        retry["command"][retry["command"].index("--retries") + 1] = "1"
        variants.append(retry)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                GITHUB_RUN_ID="42",
                GITHUB_RUN_ATTEMPT="1",
                GITHUB_JOB="pair",
            ),
        ):
            path = Path(directory) / "negative.json"
            for index, item in enumerate(variants):
                path.write_text(json.dumps(item))
                with self.subTest(index=index), self.assertRaises(ValueError):
                    reader.execution(path, "native", {"hepta": source})


if __name__ == "__main__":
    unittest.main()
