"""Exercise reviewed bytes, real Git and controlled metadata; no native qualification."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

import ndu_port_candidate_common as common
import ndu_port_candidate_common as dependency
from ndu_port_integration_test_support import git


ROOT = Path(__file__).resolve().parents[1]


class DependencyAmendmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        amendment = json.loads((ROOT / dependency.DEPENDENCY_AMENDMENT).read_bytes())
        manifest = json.loads((ROOT / common.INTEGRATION).read_bytes())
        recipe = json.loads((ROOT / common.RECIPE).read_bytes())
        formatting = json.loads((ROOT / common.SOURCE_AMENDMENT).read_bytes())
        names = {
            dependency.DEPENDENCY_AMENDMENT,
            *amendment["parents"],
            *amendment["proofs"],
            *manifest["files"],
            *dependency.added_dependency_files(amendment),
            *formatting["changes"],
            *common.POLICIES,
            recipe["patch_path"],
            recipe["matrix_baseline"]["fixture_patch_path"],
            *(item["path"] for item in recipe["aws_qualification"]["resources"].values()),
        }
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Source guard fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "add", "--", *sorted(names))
        git(self.root, "commit", "-qm", "Reviewed byte fixture; no native qualification")
        self.recipe = common.load_recipe(self.root)
        self.amendment = amendment

    def runner(self):
        return common.Recorder(self.root, self.base / "evidence", "source-guard-test")

    def verify(self, record=None, artifact=None):
        return common.verify_integrated_source(
            self.runner(), self.recipe, record, artifact
        )

    def test_exact_product_binds_all_319_files_without_changing_old_records(self):
        original = common.describe(self.root, self.amendment["parents"])
        manifest, binding, tree = self.verify()
        self.assertEqual(len(manifest["files"]), 319)
        self.assertEqual(manifest["files"], common.describe(self.root, manifest["files"]))
        self.assertEqual(binding["dependency_amendment"]["sha256"], dependency.AMENDMENT_SHA256)
        self.assertEqual(common.describe(self.root, self.amendment["parents"]), original)
        self.assertEqual(tree, git(self.root, "rev-parse", "HEAD^{tree}").decode().strip())
        self.assertEqual(git(self.root, "status", "--porcelain"), b"")

    def test_the_common_guard_still_loads_with_only_the_isolated_standard_library(self):
        script = (
            "import json,pathlib,sys,types; "
            "p=pathlib.Path(sys.argv[1]); "
            "m=types.ModuleType('hepta_bound_port_guard'); m.__file__=str(p); "
            "exec(compile(p.read_bytes(),str(p),'exec',dont_inherit=True),m.__dict__); "
            "root=pathlib.Path(sys.argv[2]); "
            "recipe=m.load_recipe(root); a=m.load_dependency_amendment(root,recipe); "
            "assert len(m.added_dependency_files(a))==284; "
            "print('isolated standard-library guard passed; no native qualification')"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", script,
             str(ROOT / "scripts/ndu_port_candidate_common.py"), str(self.root)],
            cwd=self.base, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("isolated standard-library guard passed", result.stdout)

    def test_missing_or_self_resealed_amendment_is_not_a_legacy_bypass(self):
        path = self.root / dependency.DEPENDENCY_AMENDMENT
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "reviewed origin"):
            self.verify()
        path.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(ValueError, "fixed review seal"):
            dependency.load_dependency_amendment(self.root, self.recipe)

    def test_original_parent_and_proof_bytes_are_immutable(self):
        for name in [*self.amendment["parents"], *self.amendment["proofs"]]:
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaises(ValueError):
                    dependency.load_dependency_amendment(self.root, self.recipe)
                path.write_bytes(raw)

    def test_each_existing_file_rejects_unregistered_drift(self):
        for name in dependency.DEPENDENCY_CHANGED:
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaisesRegex(ValueError, "source or lock identity"):
                    dependency.load_dependency_amendment(self.root, self.recipe)
                path.write_bytes(raw)

    def test_each_vendor_rejects_mutation_extra_file_missing_license_and_symlink(self):
        for directory in self.amendment["vendor_dirs"]:
            with self.subTest(directory=directory):
                folder = self.root / directory
                manifest = folder / "Cargo.toml"
                raw = manifest.read_bytes()
                manifest.write_bytes(raw + b"\n")
                with self.assertRaisesRegex(ValueError, "vendor inventory"):
                    dependency.load_dependency_amendment(self.root, self.recipe)
                manifest.write_bytes(raw)
                extra = folder / "unreviewed.rs"
                extra.write_text("unreviewed source\n")
                with self.assertRaisesRegex(ValueError, "vendor inventory"):
                    dependency.load_dependency_amendment(self.root, self.recipe)
                extra.unlink()
                license_path = next(p for p in folder.rglob("*") if p.is_file() and p.name.startswith("LICENSE"))
                original = license_path.read_bytes()
                license_path.unlink()
                with self.assertRaisesRegex(ValueError, "vendor inventory"):
                    dependency.load_dependency_amendment(self.root, self.recipe)
                license_path.symlink_to(manifest)
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    dependency.load_dependency_amendment(self.root, self.recipe)
                license_path.unlink()
                license_path.write_bytes(original)

    def test_vendor_mode_and_git_index_are_part_of_the_binding(self):
        executable = next(n for n, m in self.amendment["vendor_modes"].items() if m == "100755")
        path = self.root / executable
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "executable mode"):
            dependency.load_dependency_amendment(self.root, self.recipe)
        path.chmod(0o755)
        replacement = self.base / "index-only"
        replacement.write_text("unreviewed staged file\n")
        blob = git(self.root, "hash-object", "-w", str(replacement)).decode().strip()
        git(self.root, "update-index", "--cacheinfo", f"100755,{blob},{executable}")
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            self.verify()

    def metadata(self):
        packages = []
        for expected in self.amendment["path_packages"]:
            packages.append({
                "name": expected["name"], "version": expected["version"],
                "id": expected["name"] + "@" + expected["version"],
                "source": None,
                "manifest_path": str(self.root / expected["manifest_path"]),
            })
        return {
            "workspace_root": str(self.root / "codex-rs"),
            "packages": packages,
            "resolve": {"nodes": [{"id": p["id"]} for p in packages]},
        }

    def test_graph_guards_all_five_including_hyper_and_the_preserved_edge(self):
        locked = tomllib.loads((self.root / "codex-rs/Cargo.lock").read_text())["package"]
        metadata = self.metadata()
        dependency.verify_dependency_graph(self.root, self.recipe, metadata, locked)
        for name in dependency.DEPENDENCY_CRATES:
            with self.subTest(crate=name):
                altered = copy.deepcopy(metadata)
                p = next(p for p in altered["packages"] if p["name"] == name)
                p["source"] = "registry+https://github.com/rust-lang/crates.io-index"
                with self.assertRaisesRegex(ValueError, "five exact path crates"):
                    dependency.verify_dependency_graph(self.root, self.recipe, altered, locked)
                p["source"] = None
                p["manifest_path"] = str(self.base / "outside/Cargo.toml")
                with self.assertRaisesRegex(ValueError, "outside the producer"):
                    dependency.verify_dependency_graph(self.root, self.recipe, altered, locked)
        for area in ("lock", "metadata"):
            with self.subTest(pin_in=area):
                altered_lock, altered_metadata = copy.deepcopy(locked), copy.deepcopy(metadata)
                target = altered_lock if area == "lock" else altered_metadata["packages"]
                target.append({"name": "pin-utils", "version": "0.1.0"})
                with self.assertRaisesRegex(ValueError, "still contains pin-utils"):
                    dependency.verify_dependency_graph(self.root, self.recipe, altered_metadata, altered_lock)
        altered_lock = copy.deepcopy(locked)
        supervisor = next(p for p in altered_lock if p["name"] == "codex-hepta-supervisor")
        supervisor["dependencies"].remove("codex-utils-cargo-bin")
        with self.assertRaisesRegex(ValueError, "supervisor edge"):
            dependency.verify_dependency_graph(self.root, self.recipe, metadata, altered_lock)

    def test_amendment_transport_and_resealed_result_cannot_change_the_binding(self):
        manifest, binding, tree = self.verify()
        shutil.rmtree(self.base / "evidence")
        artifact = self.base / "artifact"
        artifact.mkdir()
        for source, target in ((common.INTEGRATION, "integration.json"), (common.SOURCE_AMENDMENT, "source-amendment.json"), (dependency.DEPENDENCY_AMENDMENT, "dependency-amendment.json")):
            shutil.copyfile(self.root / source, artifact / target)
        (artifact / "candidate.patch").write_bytes(b"")
        record = {
            "source_mode": "integrated", "integration": binding,
            "source_tree": tree, "files": manifest["files"],
            "policy_inputs": manifest["policy_inputs"], "changed_paths": [],
            "artifacts": common.describe(artifact, ("candidate.patch", "integration.json", "source-amendment.json", "dependency-amendment.json")),
        }
        self.verify(record, artifact)
        shutil.rmtree(self.base / "evidence")
        path = artifact / "dependency-amendment.json"
        path.write_bytes(path.read_bytes() + b"\n")
        record["artifacts"].update(common.describe(artifact, (path.name,)))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)

    def test_consumer_rejects_a_resealed_vendor_snapshot(self):
        manifest, binding, tree = self.verify()
        shutil.rmtree(self.base / "evidence")
        artifact = self.base / "artifact"
        artifact.mkdir()
        common.copy_files(self.root, artifact / "files", manifest["files"])
        for source, target in (
            (common.INTEGRATION, "integration.json"),
            (common.SOURCE_AMENDMENT, "source-amendment.json"),
            (dependency.DEPENDENCY_AMENDMENT, "dependency-amendment.json"),
            (self.recipe["patch_path"], "source.patch"),
        ):
            shutil.copyfile(self.root / source, artifact / target)
        (artifact / "candidate.patch").write_bytes(b"")
        record = {
            "schema": common.SCHEMA, "status": "candidate_generated",
            "source_commit": git(self.root, "rev-parse", "HEAD").decode().strip(),
            "source_mode": "integrated", "integration": binding,
            "source_tree": tree, "files": manifest["files"],
            "policy_inputs": manifest["policy_inputs"], "changed_paths": [],
            "original_dependency_policy_unchanged": True,
            "recipe_sha256": common.checksum(self.root / common.RECIPE),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "artifacts": common.describe(artifact, (
                "candidate.patch", "source.patch", "integration.json",
                "source-amendment.json", "dependency-amendment.json",
            )),
        }
        result = artifact / "RESULT.json"
        result.write_text(json.dumps(record))
        runner = self.runner()
        common.load_candidate(runner, artifact, common.checksum(result), record["source_commit"])
        name = next(iter(dependency.added_dependency_files(self.amendment)))
        file = artifact / "files" / name
        file.write_bytes(file.read_bytes() + b"\n")
        record["files"][name] = common.describe(artifact / "files", (name,))[name]
        result.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            common.load_candidate(runner, artifact, common.checksum(result), record["source_commit"])


if __name__ == "__main__":
    unittest.main()
