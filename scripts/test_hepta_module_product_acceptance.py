"""Module projection and Cargo membership acceptance in miniature workspaces.

The historical filename is retained for CI callers. Sentinel hosts prove only
projection independence, not real Agentd execution, safe writer handoff or
product throughput. Those boundaries have separate native integration tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_script(name: str):
    path = HERE / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest = load_script("hepta_module_manifest.py")
architecture = load_script("hepta_architecture_graph.py")
reachability = load_script("hepta_rust_reachability.py")
fixtures = load_script("test_hepta_module_manifest.py")


class ModuleProjectionAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "codex-rs").mkdir()
        (self.root / "docs/modules").mkdir(parents=True)
        (self.root / "docs/modules/registry.toml").write_text(
            fixtures.REGISTRY, encoding="utf-8"
        )
        (self.root / "docs/modules/SOURCE_BINDINGS.json").write_text(
            json.dumps({"schema": "hepta.module-source-binding.v2", "bindings": []}),
            encoding="utf-8",
        )
        (self.root / "codex-rs/Cargo.toml").write_text(
            '[workspace]\nmembers = ["hepta-*"]\nresolver = "2"\n\n'
            '[workspace.package]\nversion = "0.0.0"\nedition = "2024"\n'
            'license = "Apache-2.0"\n',
            encoding="utf-8",
        )
        self.write_package(
            "hepta-types", "codex-hepta-types", "pub struct StableType;\n"
        )
        platform = self.root / "docs/modules/platform.types"
        platform.mkdir()
        platform_manifest = fixtures.module_text(
            "platform.types", 0, "codex-rs/hepta-types"
        ).replace("compileLayer = 1", "compileLayer = 0")
        (platform / "module.toml").write_text(platform_manifest, encoding="utf-8")

        # Sentinels detect unexpected projection writes to unrelated fixture files.
        for relative in [
            "codex-rs/hepta-agentd/src/runtime.rs",
            "codex-rs/app-server/src/lib.rs",
        ]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("// immutable composition sentinel\n", encoding="utf-8")

        # The real workspace glob includes hepta-agentd. The miniature fixture
        # keeps that sentinel as an unrelated workspace package so Cargo can
        # resolve the same glob without making it a generated Hepta module.
        agentd = self.root / "codex-rs/hepta-agentd"
        (agentd / "Cargo.toml").write_text(
            '[package]\nname = "sentinel-agentd"\nversion = "0.0.0"\n'
            'edition = "2024"\n\n[lib]\npath = "src/lib.rs"\n',
            encoding="utf-8",
        )
        (agentd / "src/lib.rs").write_text("// sentinel crate\n", encoding="utf-8")

        self.run_command(["git", "init", "-q"])
        self.run_command(["git", "config", "user.email", "hepta-test@example.invalid"])
        self.run_command(["git", "config", "user.name", "Hepta test"])
        self.refresh()
        self.run_command(["git", "add", "-A"])
        self.run_command(["git", "commit", "-qm", "baseline"])
        self.baseline_cargo = (self.root / "codex-rs/Cargo.toml").read_bytes()
        self.baseline_agentd = (
            self.root / "codex-rs/hepta-agentd/src/runtime.rs"
        ).read_bytes()
        self.baseline_app_server = (
            self.root / "codex-rs/app-server/src/lib.rs"
        ).read_bytes()

    def run_command(
        self, command: list[str], **kwargs
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("CARGO_INCREMENTAL", "0")
        env["CARGO_HOME"] = str(self.root / ".cargo-home")
        env["CARGO_TARGET_DIR"] = str(self.root / "target")
        return subprocess.run(
            command,
            cwd=self.root,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )

    def write_package(self, directory: str, package: str, source: str) -> None:
        root = self.root / "codex-rs" / directory
        (root / "src").mkdir(parents=True)
        (root / "Cargo.toml").write_text(
            f'''[package]\nname = "{package}"\nversion.workspace = true\n'''
            """edition.workspace = true\nlicense.workspace = true\n\n"""
            """[lib]\npath = "src/lib.rs"\n""",
            encoding="utf-8",
        )
        (root / "src/lib.rs").write_text(source, encoding="utf-8")

    def refresh(self) -> None:
        changed = manifest.apply(False, self.root)
        self.assertIsInstance(changed, list)
        self.run_command(
            [
                "cargo",
                "generate-lockfile",
                "--manifest-path",
                str(self.root / "codex-rs/Cargo.toml"),
            ]
        )
        architecture.apply(self.root, check=False)

    def assert_hosts_untouched(self) -> None:
        self.assertEqual(
            (self.root / "codex-rs/Cargo.toml").read_bytes(), self.baseline_cargo
        )
        self.assertEqual(
            (self.root / "codex-rs/hepta-agentd/src/runtime.rs").read_bytes(),
            self.baseline_agentd,
        )
        self.assertEqual(
            (self.root / "codex-rs/app-server/src/lib.rs").read_bytes(),
            self.baseline_app_server,
        )

    def assert_reachable(self) -> None:
        metadata = reachability.cargo_metadata(self.root, Path("codex-rs/Cargo.toml"))
        report = reachability.scan(self.root, metadata)
        self.assertEqual(report["status"], "aligned", report)

    def test_stateless_leaf_add_compile_remove_has_no_host_or_projection_residue(
        self,
    ) -> None:
        self.write_package(
            "hepta-feature-sample",
            "codex-hepta-feature-sample",
            "use codex_hepta_types::StableType;\n"
            "pub fn stable_type() -> StableType { StableType }\n",
        )
        sample_cargo = self.root / "codex-rs/hepta-feature-sample/Cargo.toml"
        sample_cargo.write_text(
            sample_cargo.read_text(encoding="utf-8")
            + "\n[dependencies]\n"
            + 'codex-hepta-types = { path = "../hepta-types" }\n',
            encoding="utf-8",
        )
        module = self.root / "docs/modules/feature.sample"
        module.mkdir()
        (module / "module.toml").write_text(
            fixtures.module_text(
                "feature.sample",
                1,
                "codex-rs/hepta-feature-sample",
                ["platform.types"],
            ),
            encoding="utf-8",
        )
        self.refresh()
        self.run_command(["git", "add", "-A"])
        self.run_command(
            [
                "cargo",
                "check",
                "--locked",
                "--manifest-path",
                str(self.root / "codex-rs/Cargo.toml"),
                "-p",
                "codex-hepta-feature-sample",
            ]
        )
        self.assert_reachable()
        modules = json.loads(
            (self.root / "docs/modules/MODULES.json").read_text(encoding="utf-8")
        )
        matrix = json.loads(
            (self.root / "docs/modules/CI_MATRIX.json").read_text(encoding="utf-8")
        )
        graph = json.loads(
            (self.root / "docs/modules/COMPILE_GRAPH.json").read_text(encoding="utf-8")
        )
        self.assertIn("feature.sample", {row["id"] for row in modules["modules"]})
        self.assertIn(
            "codex-hepta-feature-sample",
            {row["packageName"] for row in matrix["packages"]},
        )
        self.assertIn(
            ("feature.sample", "platform.types"),
            {
                (row["fromModule"], row["toModule"])
                for row in graph["productionModuleEdges"]
            },
        )
        self.assert_hosts_untouched()
        changed = set(
            self.run_command(
                ["git", "diff", "--cached", "--name-only"]
            ).stdout.splitlines()
        )
        self.assertNotIn("codex-rs/Cargo.toml", changed)
        self.assertNotIn("codex-rs/hepta-agentd/src/runtime.rs", changed)
        self.assertNotIn("codex-rs/app-server/src/lib.rs", changed)
        self.run_command(["git", "commit", "-qm", "add leaf module"])

        shutil.rmtree(self.root / "codex-rs/hepta-feature-sample")
        shutil.rmtree(module)
        self.refresh()
        self.run_command(["git", "add", "-A"])
        self.assert_reachable()
        self.assert_hosts_untouched()
        for relative in [
            "docs/modules/MODULES.json",
            "docs/modules/CARGO_BINDINGS.json",
            "docs/modules/SOURCE_BINDINGS.json",
            "docs/modules/CI_MATRIX.json",
            "docs/modules/COMPILE_GRAPH.json",
            "codex-rs/Cargo.lock",
        ]:
            self.assertNotIn(
                "feature.sample",
                (self.root / relative).read_text(encoding="utf-8"),
                relative,
            )
            self.assertNotIn(
                "codex-hepta-feature-sample",
                (self.root / relative).read_text(encoding="utf-8"),
                relative,
            )
        self.assertNotIn(
            "codex-rs/Cargo.toml",
            set(
                self.run_command(
                    ["git", "diff", "--cached", "--name-only"]
                ).stdout.splitlines()
            ),
        )

    def test_catalog_growth_keeps_fixture_hosts_and_workspace_membership_stable(
        self,
    ) -> None:
        for index in range(40):
            directory = f"hepta-scale-{index:02d}"
            package = f"codex-hepta-scale-{index:02d}"
            module_id = f"scale.feature{index:02d}"
            self.write_package(
                directory,
                package,
                "use codex_hepta_types::StableType;\n"
                "pub fn stable_type() -> StableType { StableType }\n",
            )
            cargo = self.root / "codex-rs" / directory / "Cargo.toml"
            cargo.write_text(
                cargo.read_text(encoding="utf-8")
                + "\n[dependencies]\n"
                + 'codex-hepta-types = { path = "../hepta-types" }\n',
                encoding="utf-8",
            )
            module = self.root / "docs/modules" / module_id
            module.mkdir()
            (module / "module.toml").write_text(
                fixtures.module_text(
                    module_id,
                    index + 1,
                    f"codex-rs/{directory}",
                    ["platform.types"],
                ),
                encoding="utf-8",
            )

        self.refresh()
        modules = json.loads(
            (self.root / "docs/modules/MODULES.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(modules["modules"]), 41)
        self.assert_hosts_untouched()
        self.assert_reachable()


if __name__ == "__main__":
    unittest.main()
