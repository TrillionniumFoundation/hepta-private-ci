from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta_module_manifest.py")
SPEC = importlib.util.spec_from_file_location("hepta_module_manifest", SCRIPT)
assert SPEC and SPEC.loader
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)


REGISTRY = """schema = "hepta.module-manifest-registry.v1"

[projection]
schema = "hepta.module-registry.v7"
schemaVersion = 7
documentClass = "canonical_registry"
authorityScope = "test"
planId = "test-plan"
planVersion = "1"

[defaults]
lifecycle = "existing_or_target"
runtimeAuthority = false
centralSynchronousRpcAllowed = false
crossOwnerDirectWriteAllowed = false

[rules]
oneModulePerPrimarySourceRoot = true

[authorityFlags]
runtimeAuthority = false
"""


def module_text(
    module_id: str, order: int, package: str | None, uses: list[str] | None = None
) -> str:
    uses = uses or []
    package_table = ""
    roots = ""
    root_binding_scalar = "rootBindings = []\n"
    evidence = "[]"
    if package:
        root_binding_scalar = ""
        roots = f'''\n[[rootBindings]]
path = "{package}"
mode = "exclusive"
'''
        evidence = f'["{package}"]'
        package_table = f'''\n[[cargoPackages]]
path = "{package}"
ciGroups = ["lifecycle"]
compileLayer = 1
'''
    return f'''schema = "hepta.module-manifest.v1"
order = {order}
id = "{module_id}"
plane = "domain"
kind = "service"
lifecycle = "target"
state = "stateless"
architectureRole = "functional_substrate"
writes = []
uses = {json.dumps(uses)}
owner = "owner"
deputy = "deputy"
denies = []
localHotPathCentralRpc = "not_applicable_or_bounded"
{root_binding_scalar}sourceStatus = "existing_bound"
source_root_present = true
production_implementation = false
sourceEvidenceRoots = {evidence}
missingDeclaredRoots = []
bootstrapWorkPackage = "TEST"
technicalDocument = "docs/modules/{module_id}/TECHNICAL.md"
documentationReady = true

[hotPathPolicy]
centralSynchronousRpcAllowed = false
boundedCachedControlInputAllowed = true
fallbackRequired = true

[publicSurfacePolicy]
typedContractsOnly = true
denyUnknownCriticalFields = true
rawModelOrSecretPayloadExportAllowed = false
{roots}{package_table}'''


class ModuleManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "docs/modules").mkdir(parents=True)
        (self.root / "docs/modules/registry.toml").write_text(
            REGISTRY, encoding="utf-8"
        )
        (self.root / "docs/modules/SOURCE_BINDINGS.json").write_text(
            json.dumps({"schema": "hepta.module-source-binding.v2", "bindings": []}),
            encoding="utf-8",
        )

    def add_module(
        self,
        module_id: str,
        order: int,
        package: str | None,
        uses: list[str] | None = None,
    ) -> None:
        directory = self.root / "docs/modules" / module_id
        directory.mkdir(parents=True)
        (directory / "module.toml").write_text(
            module_text(module_id, order, package, uses), encoding="utf-8"
        )
        if package:
            package_root = self.root / package
            package_root.mkdir(parents=True)
            package_name = "codex-hepta-" + package.rsplit("/", 1)[-1].removeprefix(
                "hepta-"
            )
            (package_root / "Cargo.toml").write_text(
                f'[package]\nname = "{package_name}"\nversion = "0.0.0"\nedition = "2024"\n',
                encoding="utf-8",
            )

    def projected(self) -> dict[str, dict]:
        rendered = manifest.projected_documents(self.root)
        return {path.name: json.loads(text) for path, text in rendered.items()}

    def test_stateless_module_add_and_remove_leave_no_projection_residue(self) -> None:
        self.add_module("platform.types", 0, None)
        self.add_module(
            "feature.sample", 1, "codex-rs/hepta-feature-sample", ["platform.types"]
        )
        added = self.projected()
        self.assertEqual(
            [row["id"] for row in added["MODULES.json"]["modules"]],
            ["platform.types", "feature.sample"],
        )
        self.assertEqual(
            added["CARGO_BINDINGS.json"]["bindings"],
            [
                {
                    "packagePath": "codex-rs/hepta-feature-sample",
                    "module": "feature.sample",
                }
            ],
        )
        self.assertEqual(
            added["CI_MATRIX.json"]["packages"][0]["ciGroups"], ["lifecycle"]
        )

        (self.root / "docs/modules/feature.sample/module.toml").unlink()
        import shutil

        shutil.rmtree(self.root / "codex-rs/hepta-feature-sample")
        removed = self.projected()
        self.assertEqual(
            [row["id"] for row in removed["MODULES.json"]["modules"]],
            ["platform.types"],
        )
        self.assertEqual(removed["CARGO_BINDINGS.json"]["bindings"], [])
        self.assertEqual(removed["CI_MATRIX.json"]["packages"], [])
        self.assertNotIn("feature.sample", json.dumps(removed, sort_keys=True))

    def test_editorial_source_interpretation_never_enters_machine_projections(
        self,
    ) -> None:
        self.add_module("platform.types", 0, None)
        manifest_path = self.root / "docs/modules/platform.types/module.toml"
        baseline = self.projected()
        for explanation in (
            "source exists but activation is separate",
            "a completely different editorial explanation",
        ):
            current = manifest_path.read_text()
            manifest_path.write_text(
                current.replace(
                    "\n[hotPathPolicy]",
                    f'\nsourceInterpretation = "{explanation}"\n\n[hotPathPolicy]',
                    1,
                ),
                encoding="utf-8",
            )
            projected = self.projected()
            self.assertEqual(projected, baseline)
            self.assertNotIn(
                "interpretation", projected["SOURCE_BINDINGS.json"]["bindings"][0]
            )
            lines = [
                line
                for line in manifest_path.read_text().splitlines()
                if not line.startswith("sourceInterpretation = ")
            ]
            manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_ordinary_projection_never_gates_on_prose_metrics(self) -> None:
        with mock.patch.object(manifest.subprocess, "run") as run:
            manifest.run_docs_projection(self.root, check=True)
        commands = [list(call.args[0]) for call in run.call_args_list]
        flattened = [" ".join(command) for command in commands]
        self.assertTrue(
            any("refresh-derived --check" in command for command in flattened)
        )
        self.assertTrue(
            any("hepta_module_doc_metadata.py" in command for command in flattened)
        )
        self.assertFalse(any("refresh-indexes" in command for command in flattened))
        self.assertFalse(any("--prose-metrics" in command for command in flattened))

        with mock.patch.object(manifest.subprocess, "run") as run:
            manifest.run_docs_projection(self.root, check=False)
        flattened = [" ".join(call.args[0]) for call in run.call_args_list]
        self.assertTrue(
            any(
                "hepta_module_doc_metadata.py --write" in command
                for command in flattened
            )
        )
        self.assertFalse(any("--prose-metrics" in command for command in flattened))

    def test_duplicate_package_ownership_is_rejected(self) -> None:
        package = "codex-rs/hepta-shared"
        self.add_module("first", 0, package)
        second = self.root / "docs/modules/second"
        second.mkdir(parents=True)
        (second / "module.toml").write_text(
            module_text("second", 1, package), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "owned by both"):
            manifest.load_manifests(self.root)


if __name__ == "__main__":
    unittest.main()
