"""Pinned API migration observations preserve their historical predecessor."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import native_source_bindings as bindings


class NativeObservationUpdateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "native/demo/lib.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub struct Legacy;\n", encoding="utf-8")
        registry = self.root / "docs/modules/SOURCE_BINDINGS.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps(
                {"bindings": [{"module": "demo", "declaredRoots": ["native/demo"]}]}
            ),
            encoding="utf-8",
        )
        bindings.git(self.root, "init", "-q")
        self.commit()
        self.history = [
            {
                "module": "demo",
                "path": "native/demo/lib.rs",
                "blobSha": bindings.git_blob(self.source.read_bytes()),
                "exports": ["Legacy"],
            }
        ]
        self.source.write_text("pub struct Current;\n", encoding="utf-8")
        self.commit()
        self.updates = {
            "schema": "hepta.native-source-observation-updates.v1",
            "schemaVersion": 1,
            "sourceSnapshot": bindings.git(self.root, "rev-parse", "HEAD")
            .decode()
            .strip(),
            "sourceTree": bindings.git(self.root, "rev-parse", "HEAD^{tree}")
            .decode()
            .strip(),
            "evidenceClass": "source_observation_only",
            "consumerCallsitesProved": False,
            "productExecutionProved": False,
            "observations": [
                {
                    "module": "demo",
                    "path": "native/demo/lib.rs",
                    "blobSha": bindings.git_blob(self.source.read_bytes()),
                    "exports": ["Current"],
                    "supersedes": deepcopy(self.history[0]),
                }
            ],
        }

    def commit(self):
        bindings.git(self.root, "add", ".")
        bindings.git(
            self.root,
            "-c",
            "user.name=Binding Test",
            "-c",
            "user.email=binding-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )

    def apply(self, updates):
        return bindings.apply_observation_updates(self.root, self.history, updates)

    def test_explicit_api_migration_retains_history_and_binds_current_source(self):
        original = deepcopy(self.history)
        with self.assertRaisesRegex(bindings.BindingError, "missing native symbols"):
            bindings.observe_native_bindings(self.root, self.history, ["demo"])
        rows = self.apply(self.updates)
        actual = bindings.observe_native_bindings(self.root, rows, ["demo"])
        self.assertEqual(self.history, original)
        self.assertEqual(self.updates["observations"][0]["supersedes"], original[0])
        self.assertEqual(
            actual["observations"],
            [
                {
                    **rows[0],
                    "historicalBlobSha": rows[0]["blobSha"],
                }
            ],
        )
        self.assertFalse(actual["productExecutionProved"])
        self.source.write_text(
            "// pub struct Current;\npub struct Later;\n", encoding="utf-8"
        )
        self.commit()
        with self.assertRaisesRegex(bindings.BindingError, "missing native symbols"):
            bindings.observe_native_bindings(self.root, rows, ["demo"])

    def test_source_tree_blob_and_symbols_cannot_be_forged(self):
        for field, value in (
            ("sourceTree", "0" * 40),
            ("blobSha", "0" * 40),
            ("exports", ["Legacy"]),
        ):
            with self.subTest(field=field):
                updated = deepcopy(self.updates)
                target = (
                    updated if field == "sourceTree" else updated["observations"][0]
                )
                target[field] = value
                with self.assertRaisesRegex(bindings.BindingError, "source.*mismatch"):
                    self.apply(updated)

    def test_only_known_unique_exact_predecessors_can_be_updated(self):
        for change in ("unknown", "duplicate", "predecessor", "path"):
            with self.subTest(change=change):
                updated = deepcopy(self.updates)
                row = updated["observations"][0]
                if change == "unknown":
                    row["module"] = "unknown"
                elif change == "duplicate":
                    updated["observations"].append(deepcopy(row))
                elif change == "predecessor":
                    row["supersedes"]["exports"] = ["NeverObserved"]
                else:
                    row["path"] = "native/other/lib.rs"
                with self.assertRaises(bindings.BindingError):
                    self.apply(updated)

    def test_update_never_promotes_source_to_product_evidence(self):
        for flag in ("consumerCallsitesProved", "productExecutionProved"):
            for value in (True, None, 0, "false"):
                with self.subTest(flag=flag, value=value):
                    updated = deepcopy(self.updates)
                    if value is None:
                        del updated[flag]
                    else:
                        updated[flag] = value
                    with self.assertRaisesRegex(
                        bindings.BindingError, "update document"
                    ):
                        self.apply(updated)
