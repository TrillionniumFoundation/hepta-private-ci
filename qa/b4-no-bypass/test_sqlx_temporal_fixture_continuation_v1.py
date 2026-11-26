"""Finite data controls for the fixture-only continuation; no Cargo invocation."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import hepta_sqlx_temporal_fixture_continuation_contract_v1 as continuation
import hepta_sqlx_temporal_lock_contract_v1 as lock_contract


class FixtureContinuationDataTests(unittest.TestCase):
    def budget(self):
        return {
            "checkout_seconds": 60,
            "tool_preparation_seconds": 120,
            "generation_seconds": 840,
            "whole_job_seconds": 1200,
        }

    def review(self):
        return json.loads(
            (
                ROOT
                / "qualification"
                / "sqlx_temporal_partial_main_reuse_acceptance_v1.json"
            ).read_bytes()
        )

    def command_rows(self):
        cargo, work = ["/tool/cargo", "+1.96.0"], Path("/candidate")
        main = str(work / "codex-rs/Cargo.toml")
        default = str(work / "qualification/sqlx_temporal_default_v1/Cargo.toml")
        compatibility = str(
            work / "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.toml"
        )
        commands = (
            (
                "main-cache-fetch-locked-once",
                ["fetch", "--locked", "--manifest-path", main],
            ),
            (
                "default-seeded-update-workspace-offline-once",
                ["update", "--workspace", "--offline", "--manifest-path", default],
            ),
            (
                "default-locked-filtered-graph-offline-once",
                [
                    "metadata",
                    "--manifest-path",
                    default,
                    "--locked",
                    "--offline",
                    "--filter-platform",
                    "aarch64-unknown-linux-gnu",
                    "--format-version",
                    "1",
                ],
            ),
            (
                "compatibility-seeded-update-workspace-offline-once",
                [
                    "update",
                    "--workspace",
                    "--offline",
                    "--manifest-path",
                    compatibility,
                ],
            ),
            (
                "compatibility-locked-filtered-graph-offline-once",
                [
                    "metadata",
                    "--manifest-path",
                    compatibility,
                    "--locked",
                    "--offline",
                    "--filter-platform",
                    "aarch64-unknown-linux-gnu",
                    "--format-version",
                    "1",
                ],
            ),
        )
        return (
            cargo,
            work,
            [
                {
                    "label": label,
                    "argv": cargo + argv,
                    "elapsed_seconds": 1.0,
                    "execution": {
                        "returncode": 0,
                        "timed_out": False,
                        "output_limit_exceeded": False,
                    },
                }
                for label, argv in commands
            ],
        )

    def peer(self):
        spec = {
            "native_peer_expected_activated": False,
            "branch": "reviewed",
            "source_delta_paths": ["a", "b"],
        }
        peer = {
            "schema": "hepta.chrono-hooks-cli-native-reconstruction-inputs.v2",
            "activated": False,
            "activation_blockers": ["not activated"],
            "parent": continuation.PARENT,
            "proposed_parent": continuation.PARENT,
            "branch": "reviewed",
            "publication_paths": ["a", "b"],
            "lock_generation_source": continuation.PARENT,
            "lock_acceptance_review_sha256": continuation.REUSE_SHA,
            "native_cap_seconds": 2400,
            "whole_job_cap_seconds": 3600,
            "exact_count": 48,
            "new_count": 33,
            "retained_count": 15,
            "roster_sha256": "573a66ecb204d62424187681155d1024e0608a57d22d3301c63b813ab93be09d",
            "tooling": {
                "rust": "1.96.0",
                "cargo": "1.96.0",
                "nextest": "0.9.103",
                "just": "1.51.0",
                "runner": "ubuntu-24.04-arm",
                "version_command_cap_seconds": 5,
                "retries": 0,
                "test_threads": 1,
            },
        }
        return peer, spec

    def test_remaining_budget_accepts_bounded_continuation(self):
        remaining = continuation.validate_budget(self.budget(), continuation.SPENT)
        self.assertAlmostEqual(remaining["generation_seconds"], 849.187947358)
        self.assertEqual(remaining["whole_job_seconds"], 1222)

    def test_generation_budget_cannot_reset_to_nine_hundred(self):
        budget = self.budget()
        budget["generation_seconds"] = 900
        with self.assertRaisesRegex(
            ValueError, "remaining original allowance: generation"
        ):
            continuation.validate_budget(budget, continuation.SPENT)

    def test_whole_job_budget_cannot_reset_to_thirteen_twenty(self):
        budget = self.budget()
        budget["whole_job_seconds"] = 1320
        with self.assertRaisesRegex(ValueError, "remaining original allowance: whole"):
            continuation.validate_budget(budget, continuation.SPENT)

    def test_nonfinite_or_boolean_budget_is_refused(self):
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value):
                budget = self.budget()
                budget["generation_seconds"] = value
                with self.assertRaisesRegex(
                    ValueError, "remaining original allowance: generation"
                ):
                    continuation.validate_budget(budget, continuation.SPENT)

    def test_original_failure_cost_cannot_be_removed(self):
        spent = dict(continuation.SPENT)
        spent["generation_seconds"] = 0
        with self.assertRaisesRegex(ValueError, "spent original phase costs"):
            continuation.validate_budget(self.budget(), spent)

    def test_collection_allowance_is_required(self):
        budget = self.budget()
        budget["whole_job_seconds"] = 1100
        with self.assertRaisesRegex(ValueError, "collection and upload"):
            continuation.validate_budget(budget, continuation.SPENT)

    def test_original_failure_is_retained_in_valid_reuse(self):
        result = continuation.validate_reuse(self.review())
        self.assertEqual(result["original_complete_job_seconds"], 98)
        self.assertEqual(result["original_queue_seconds"], 4120)

    def test_reuse_cannot_be_promoted_to_execution(self):
        review = self.review()
        review["execution_authorization"] = True
        with self.assertRaisesRegex(ValueError, "widened into execution"):
            continuation.validate_reuse(review)

    def test_failed_original_cannot_be_relabelled_success(self):
        review = self.review()
        review["origin"]["original_generation_status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "failed attempt identity"):
            continuation.validate_reuse(review)

    def test_exact_five_unfinished_commands_are_accepted(self):
        cargo, work, rows = self.command_rows()
        result = continuation.validate_completed_commands(
            rows, continuation.command_plan(cargo, work), cargo
        )
        self.assertEqual(
            [row["label"] for row in result], [row["label"] for row in rows]
        )

    def test_generate_lockfile_cannot_replace_seeded_update(self):
        cargo, work, rows = self.command_rows()
        rows[1]["argv"][2] = "generate-lockfile"
        with self.assertRaisesRegex(ValueError, "identity or order"):
            continuation.validate_completed_commands(
                rows, continuation.command_plan(cargo, work), cargo
            )

    def test_workspace_keep_flag_and_locked_fetch_are_required(self):
        for index, flag in ((0, "--locked"), (1, "--workspace"), (3, "--offline")):
            with self.subTest(index=index, flag=flag):
                cargo, work, rows = self.command_rows()
                rows[index]["argv"].remove(flag)
                with self.assertRaisesRegex(ValueError, "identity or order"):
                    continuation.validate_completed_commands(
                        rows, continuation.command_plan(cargo, work), cargo
                    )

    def test_repeated_fetch_is_refused(self):
        cargo, work, rows = self.command_rows()
        rows.insert(1, copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError, "command count"):
            continuation.validate_completed_commands(
                rows, continuation.command_plan(cargo, work), cargo
            )

    def test_actual_command_overrun_is_refused(self):
        cargo, work, rows = self.command_rows()
        rows[1]["elapsed_seconds"] = 60.01
        with self.assertRaisesRegex(ValueError, "exceeded its cap"):
            continuation.validate_completed_commands(
                rows, continuation.command_plan(cargo, work), cargo
            )

    def test_fixture_seed_is_a_create_only_independent_copy(self):
        raw = b"reviewed seed bytes\n"
        expected = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            main, fixture = root / "main.lock", root / "fixture.lock"
            main.write_bytes(raw)
            continuation.copy_seed(main.read_bytes(), fixture, expected)
            self.assertEqual(fixture.read_bytes(), raw)
            self.assertNotEqual(main.stat().st_ino, fixture.stat().st_ino)
            with self.assertRaises(FileExistsError):
                continuation.copy_seed(raw, fixture, expected)
            fixture.write_bytes(b"fixture independent postimage")
            self.assertEqual(main.read_bytes(), raw)

    def test_wrong_seed_is_refused_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory).resolve() / "fixture.lock"
            with self.assertRaisesRegex(ValueError, "exact accepted main lock"):
                continuation.copy_seed(
                    b"wrong",
                    destination,
                    {"bytes": 8, "sha256": hashlib.sha256(b"accepted").hexdigest()},
                )
            self.assertFalse(destination.exists())

    def test_rust_body_change_keeps_resolution_inputs_equal(self):
        parent = {
            "crate/Cargo.toml": {"git_blob": "a", "mode": "100644"},
            "crate/src/lib.rs": {"git_blob": "b", "mode": "100644"},
        }
        current = copy.deepcopy(parent)
        current["crate/src/lib.rs"]["git_blob"] = "c"
        current["crate/src/new_module.rs"] = {"git_blob": "d", "mode": "100644"}
        observed = continuation.validate_manifest_equivalence(parent, current)
        self.assertEqual(observed["automatic_target_paths"], ["crate/src/lib.rs"])

    def test_manifest_change_and_new_automatic_target_are_refused(self):
        parent = {
            "crate/Cargo.toml": {"git_blob": "a", "mode": "100644"},
            "crate/src/lib.rs": {"git_blob": "b", "mode": "100644"},
        }
        current = copy.deepcopy(parent)
        current["crate/Cargo.toml"]["git_blob"] = "c"
        with self.assertRaisesRegex(ValueError, "manifests, configuration"):
            continuation.validate_manifest_equivalence(parent, current)
        current = {
            **parent,
            "crate/src/bin/new.rs": {"git_blob": "e", "mode": "100644"},
        }
        with self.assertRaisesRegex(ValueError, "target inventory"):
            continuation.validate_manifest_equivalence(parent, current)

    def test_peer_branch_activation_and_caps_are_exact(self):
        peer, spec = self.peer()
        continuation.validate_peer(peer, spec)
        for key, value, reason in (
            ("branch", "foreign", "source identity"),
            ("activated", True, "activation differs"),
            ("native_cap_seconds", 2401, "controls, toolchain or cap"),
        ):
            with self.subTest(key=key):
                changed = {**peer, key: value}
                with self.assertRaisesRegex(ValueError, reason):
                    continuation.validate_peer(changed, spec)

    def test_peer_blockers_cannot_claim_active_while_blocked(self):
        peer, spec = self.peer()
        peer["activated"] = spec["native_peer_expected_activated"] = True
        with self.assertRaisesRegex(ValueError, "activation and blockers"):
            continuation.validate_peer(peer, spec)

    def test_explicit_chrono_relation_uses_original_edge_ceiling(self):
        original = tomllib.loads("""
version = 4
[[package]]
name = "sqlx-sqlite"
version = "0.9.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
dependencies = ["chrono"]
[[package]]
name = "chrono"
version = "0.4.45"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
""")
        seed = copy.deepcopy(original)
        seed["package"][0]["dependencies"] = []
        fixture = copy.deepcopy(original)
        fixture["package"].append(
            {
                "name": "fixture",
                "version": "0.0.0",
                "dependencies": ["sqlx-sqlite", "chrono"],
            }
        )
        observed = lock_contract.lock_relation(original, fixture, "fixture")
        self.assertTrue(observed["registry_versions_and_checksums_reused"])
        with self.assertRaisesRegex(
            ValueError, "different dependency version or source"
        ):
            lock_contract.lock_relation(seed, fixture, "fixture")


if __name__ == "__main__":
    unittest.main()
