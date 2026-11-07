"""Role controls use real bounded input files, not a model or training result."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_descendant_v2 as descendant
import hepta_smollm_runtime_roles_v1 as roles


class RuntimeRoleControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.current = self.root / "current"
        self.historical = self.root / "historical"
        self.current.mkdir()
        self.historical.mkdir()
        self.parent = self.root / "parent.json"
        self.descriptor = dict(
            schema="hepta-smollm-parent-material-v1",
            generation=1,
            contract=roles.CONTRACT,
        )
        self.parent.write_text(json.dumps(self.descriptor))
        self.snapshot = self.root / "snapshot.json"
        self.snapshot.write_text("{}")
        profile_root = (
            Path(__file__).resolve().parents[1]
            / "codex-rs/hepta-learning-artifacts/profiles"
        )
        self.config = dict(
            schema=roles.SCHEMA,
            python=str(Path(sys.executable).resolve()),
            chain=str(self.current),
            materials=str(self.root),
            parent=str(self.parent),
            parent_sha256=self.sha(self.parent),
            output=str(self.root / "native-output"),
            runtime_snapshot=str(self.snapshot),
            runtime_snapshot_sha256=self.sha(self.snapshot),
            material_runtime_bridge=dict(
                profile=roles.bridge.BRIDGE_PROFILE,
                material_plan=(
                    profile_root / "smollm2-public-initial-v2.plan.json"
                ).read_text(),
            ),
        )
        self.old_commit = "c96022b897c1235fdbdbfcfa32764403511c6aab"
        self.verification = dict(
            profile=roles.bridge.PROFILE,
            chain_commit=roles.bridge.CHAIN_COMMIT,
            chain_tree=roles.bridge.CHAIN_TREE,
            product_qualification=False,
        )
        self.verify = self.enterContext(
            patch.object(roles.execution, "verify", return_value=self.verification)
        )
        self.git = self.enterContext(
            patch.object(
                roles.execution,
                "git",
                side_effect=lambda *a, **k: (
                    self.old_commit if a[0] == "rev-parse" else ""
                ),
            )
        )
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def check(self, config=None, path=None):
        return roles.native_roles(
            config or self.config,
            self.historical if path is None else path,
            self.old_commit,
        )

    def test_legacy_role_is_unchanged_and_has_no_new_observation(self):
        old = dict(self.config, schema=roles.OLD_SCHEMA)
        del old["material_runtime_bridge"]
        self.assertEqual(
            roles.native_roles(old, None, self.old_commit), (self.current, None)
        )
        self.verify.assert_not_called()

    def test_legacy_cannot_smuggle_bridge_null_or_explicit_role(self):
        old = dict(self.config, schema=roles.OLD_SCHEMA)
        for value in (None, self.config["material_runtime_bridge"]):
            with self.subTest(value=value):
                old["material_runtime_bridge"] = value
                with self.assertRaisesRegex(ValueError, "legacy"):
                    roles.native_roles(old, None, self.old_commit)
        del old["material_runtime_bridge"]
        with self.assertRaisesRegex(ValueError, "legacy"):
            roles.native_roles(old, self.historical, self.old_commit)

    def test_new_role_checks_current_and_preserves_the_historical_path(self):
        actual, observation = self.check()
        self.assertEqual(actual, self.historical)
        self.assertEqual(observation["historical_chain"]["commit"], self.old_commit)
        self.assertEqual(
            observation["current_runtime"]["chain_commit"], roles.bridge.CHAIN_COMMIT
        )
        self.assertEqual(self.config["chain"], str(self.current))
        self.verify.assert_called_once_with(self.current, roles.bridge.PROFILE)
        self.assertFalse(observation["installation_authorized"])

    def test_new_role_missing_or_swapped_is_refused(self):
        with self.assertRaisesRegex(ValueError, "explicit retained"):
            roles.native_roles(self.config, None, self.old_commit)
        with self.assertRaisesRegex(ValueError, "cannot alias"):
            self.check(path=self.current)
        self.git.side_effect = lambda *a, **k: roles.bridge.CHAIN_COMMIT
        with self.assertRaisesRegex(ValueError, "exact historical"):
            self.check()

    def test_unknown_schema_or_added_field_is_never_an_old_fallback(self):
        for update in ({"schema": "future"}, {"unexpected": False}):
            with (
                self.subTest(update=update),
                self.assertRaisesRegex(ValueError, "closed versioned"),
            ):
                self.check(dict(self.config, **update))

    def test_complete_fixed_plan_cannot_be_rebound_by_a_new_hash(self):
        for field, value in (
            ("profile", "other"),
            (
                "material_plan",
                self.config["material_runtime_bridge"]["material_plan"] + " ",
            ),
        ):
            changed = copy.deepcopy(self.config)
            changed["material_runtime_bridge"][field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "fixed historical"),
            ):
                self.check(changed)

    def test_parent_contract_and_generation_are_actual_pinned_bytes(self):
        for update in ({"contract": "0" * 64}, {"generation": 0}, {"generation": True}):
            self.parent.write_text(json.dumps(dict(self.descriptor, **update)))
            changed = dict(self.config, parent_sha256=self.sha(self.parent))
            with (
                self.subTest(update=update),
                self.assertRaisesRegex(ValueError, "generation-one"),
            ):
                self.check(changed)

    def test_snapshot_and_parent_tamper_are_refused_without_rebinding(self):
        for path in (self.snapshot, self.parent):
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            try:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    self.check()
            finally:
                path.write_bytes(raw)

    def test_later_current_source_refusal_is_not_cached(self):
        self.check()
        self.verify.side_effect = ValueError("actual source changed")
        with self.assertRaisesRegex(ValueError, "actual source changed"):
            self.check()
        self.assertEqual(self.verify.call_count, 2)

    def test_symbolic_or_relative_source_role_is_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.historical, target_is_directory=True)
        for path in (alias, Path("historical")):
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(ValueError, "canonical"),
            ):
                self.check(path=path)

    def test_runtime_environment_needs_both_exact_explicit_fields(self):
        self.assertFalse(roles.selected_runtime())
        good = dict(
            HEPTA_RUNTIME_CHAIN_SHA=roles.bridge.CHAIN_COMMIT,
            HEPTA_RUNTIME_EXECUTION_PROFILE=roles.bridge.PROFILE,
        )
        with patch.dict(os.environ, good, clear=True):
            self.assertTrue(roles.selected_runtime())
        for environment in (
            {key: value for key, value in good.items() if key != omit} for omit in good
        ):
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValueError, "explicit fixed"):
                    roles.selected_runtime()

    def test_descendant_passes_only_the_checked_historical_chain_to_original_rounds(
        self,
    ):
        config_path = self.root / "native.json"
        config_path.write_text(json.dumps(self.config))
        readback_path = self.root / "ordinary.json"
        current = dict(head_digest="1", record_count=1, file_digest="2")
        readback_path.write_text(
            json.dumps(
                dict(
                    withdrawal_refused=False,
                    current_before=current,
                    current_after=current,
                    current=current,
                    parent=self.descriptor,
                )
            )
        )
        args = SimpleNamespace(
            native_input=config_path,
            ordinary_readback=readback_path,
            historical_chain=self.historical,
            output=self.root / "descendants",
        )

        class StopOriginalRound(Exception):
            pass

        with (
            patch.object(descendant.rounds, "CHAIN_COMMIT", self.old_commit),
            patch.object(
                descendant.rounds, "run", side_effect=StopOriginalRound
            ) as run,
        ):
            with self.assertRaises(StopOriginalRound):
                descendant.run(args)
        self.assertEqual(run.call_args.args[0].chain, self.historical)
        self.assertEqual(
            json.loads(config_path.read_bytes())["chain"], str(self.current)
        )


if __name__ == "__main__":
    unittest.main()
