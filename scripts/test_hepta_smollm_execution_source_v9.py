"""A new source identity requires new evidence even when execution bytes match."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch

import hepta_neural_evidence_diverse_v3 as evidence
import hepta_neural_study_diverse_v3 as study
import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v1 as original


class ExecutionSourceV9Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.v8 = execution.checked_manifest(execution.PROFILE_V8)
        self.historical = {
            p.name: p.read_bytes()
            for p in self.fixture.profiles.iterdir()
            if p.name != execution.MANIFEST_NAME_V9
        }
        # Change only source-control metadata, outside the execution closure.
        # Equal execution bytes cannot transfer the previous source's evidence.
        metadata = self.fixture.chain / ".github/workflows/source-identity.yml"
        metadata.parent.mkdir(parents=True)
        metadata.write_text("observed_controls: 9\n")
        self.fixture.git("add", ".github")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = dict(
            self.v8,
            profile=execution.PROFILE_V9,
            chain_commit=self.head,
            chain_tree=self.tree,
        )
        self.path = self.fixture.profiles / execution.MANIFEST_NAME_V9
        self.path.write_text(json.dumps(self.manifest))
        for name, value in (
            ("CHAIN_COMMIT_V9", self.head),
            ("CHAIN_TREE_V9", self.tree),
            ("MANIFEST_SHA256_V9", execution.digest(self.path.read_bytes())),
        ):
            self.enterContext(patch.object(execution, name, value))

    def pins(self):
        return dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V8=self.v8["chain_commit"],
            CHAIN_TREE_V8=self.v8["chain_tree"],
            MANIFEST_SHA256_V8=execution.MANIFEST_SHA256_V8,
            CHAIN_COMMIT_V9=self.head,
            CHAIN_TREE_V9=self.tree,
            MANIFEST_SHA256_V9=execution.MANIFEST_SHA256_V9,
        )

    def repositories(self):
        return {
            name: {"identity": {"commit": self.head, "tree": self.tree}}
            for name in evidence.REPOSITORIES
        }

    def test_current_and_historical_v8_verify_only_their_own_source(self):
        current = execution.verify(self.fixture.chain, execution.PROFILE_V9)
        self.assertEqual(
            (current["chain_commit"], current["chain_tree"]), (self.head, self.tree)
        )
        self.assertEqual(
            [
                current[key]
                for key in (
                    "model_compatibility_changed",
                    "product_qualification",
                    "installation_authorized",
                )
            ],
            [False, False, False],
        )
        self.fixture.git("checkout", "--quiet", "--detach", self.v8["chain_commit"])
        try:
            historical = execution.verify(self.fixture.chain, execution.PROFILE_V8)
            self.assertEqual(historical["chain_commit"], self.v8["chain_commit"])
            with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
                execution.verify(self.fixture.chain, execution.PROFILE_V9)
        finally:
            self.fixture.git("checkout", "--quiet", "--detach", self.head)
        self.assertEqual(
            {
                name: (self.fixture.profiles / name).read_bytes()
                for name in self.historical
            },
            self.historical,
        )

    def test_unchanged_execution_closure_cannot_inherit_v8_identity_or_tree(self):
        self.assertEqual(self.manifest["files"], self.v8["files"])
        self.assertNotEqual(self.tree, self.v8["chain_tree"])
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE_V8)
        changed = dict(self.manifest, chain_tree=self.v8["chain_tree"])
        self.path.write_text(json.dumps(changed))
        with patch.object(
            execution, "MANIFEST_SHA256_V9", execution.digest(self.path.read_bytes())
        ):
            with self.assertRaisesRegex(ValueError, "exact integrated Chain tree"):
                execution.verify(self.fixture.chain, execution.PROFILE_V9)

    def test_identical_tree_at_another_commit_requires_its_own_source_evidence(self):
        self.fixture.git(
            "-c",
            "user.name=Controlled source fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "another source identity",
        )
        self.assertEqual(
            self.fixture.git("rev-parse", "HEAD^{tree}").strip(), self.tree
        )
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE_V9)

    def test_all_consumers_select_one_current_source_and_keep_explicit_v8(self):
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {
            "TRAINING_COMMIT": self.head,
            "TRAINING_TREE": self.tree,
        }
        for profile, commit, tree in (
            (execution.PROFILE_V9, self.head, self.tree),
            (execution.PROFILE_V8, self.v8["chain_commit"], self.v8["chain_tree"]),
        ):
            with self.subTest(profile=profile):
                result = self.fixture.import_consumers(roles, profile, self.pins())
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = {
                    name: dict.fromkeys(fields, commit)
                    for name, fields in original.LEGACY_ROLES.items()
                }
                expected["hepta_neural_study_diverse_v3"] = {
                    "TRAINING_COMMIT": commit,
                    "TRAINING_TREE": tree,
                }
                self.assertEqual(json.loads(result.stdout), expected)

    def test_tampered_v9_manifest_refuses_every_current_consumer(self):
        pins = self.pins()
        self.path.write_bytes(self.path.read_bytes() + b" ")
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {"TRAINING_COMMIT": self.head}
        for name, fields in roles.items():
            with self.subTest(consumer=name):
                result = self.fixture.import_consumers(
                    {name: fields}, execution.PROFILE_V9, pins
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exact execution-source manifest", result.stderr)
        historical = self.fixture.import_consumers(roles, execution.PROFILE_V8, pins)
        self.assertEqual(historical.returncode, 0, historical.stderr)

    def test_reader_rejects_v8_in_every_current_chain_role(self):
        repositories = self.repositories()
        with patch.object(
            study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V9
        ):
            self.assertEqual(
                evidence.integrated_sources(repositories)["chain_commit"], self.head
            )
            for role in evidence.REPOSITORIES - {"hepta"}:
                for field in ("commit", "tree"):
                    with self.subTest(role=role, field=field):
                        changed = copy.deepcopy(repositories)
                        changed[role]["identity"][field] = self.v8["chain_" + field]
                        with self.assertRaisesRegex(ValueError, "same V9 Chain"):
                            evidence.integrated_sources(changed)

    def test_current_evidence_rejects_v8_or_missing_profile_even_with_current_roles(
        self,
    ):
        root = self.fixture.chain.parent / "evidence"
        root.mkdir()
        repositories = self.repositories()
        with (
            patch.object(
                study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V9
            ),
            patch.object(study, "TRAINING_COMMIT", self.head),
            patch.object(study, "TRAINING_TREE", self.tree),
            patch.dict(os.environ, {"DIVERSE_TRAINING_CHAIN_SHA": self.head}),
            patch.object(evidence.DiverseEvidence, "command", return_value=None),
            patch.object(evidence.DiverseEvidence, "loop", return_value=None),
        ):
            current = evidence.integrated_sources(repositories)
            for selected, expected in (
                (execution.PROFILE_V8, False),
                (None, False),
                (execution.PROFILE_V9, True),
            ):
                case = root / (selected or "missing")
                case.mkdir()
                (case / "final-source-diff.patch").write_bytes(b"")
                record = dict(
                    schema="hepta-neural-complete-source-diverse-v3",
                    valid=True,
                    run=evidence.original.run_identity(),
                    repositories=repositories,
                )
                if selected is not None:
                    record["execution_source"] = dict(current, profile=selected)
                for name in ("source-before.json", "source-after.json"):
                    evidence.original.save(case / name, record)
                evidence.assess(case)
                report = evidence.read(case / "qualification-summary.json")
                observed = report["checks"]["complete_source"]
                self.assertIs(observed["passed"], expected)
                if not expected:
                    self.assertIn(
                        "cannot inherit historical observations", observed["error"]
                    )
                self.assertFalse(report["installation_authority"])

    def test_source_collector_checks_current_chain_before_collecting_identity(self):
        root = self.fixture.chain.parent / "hepta"
        root.mkdir()
        self.fixture.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(
                study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V9
            ),
            patch.object(evidence.original.ci, "git", return_value=str(root)),
            patch.object(
                evidence.original, "collect_source", return_value={"identity": {}}
            ) as collect,
        ):
            self.assertEqual(evidence.source(root / "source.json"), 1)
            self.assertEqual([call.args[0] for call in collect.call_args_list], [root])
            record = evidence.read(root / "source.json")
            self.assertFalse(record["valid"])
            self.assertNotIn("execution_source", record)

    def test_unfrozen_current_profile_refuses_before_training_import(self):
        pins = dict(self.pins(), CHAIN_COMMIT_V9="UNPUBLISHED")
        result = self.fixture.import_consumers(
            {"hepta_neural_study_diverse_v3": {"TRAINING_COMMIT": self.head}},
            execution.PROFILE_V9,
            pins,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not been frozen", result.stderr)


class ExecutionSourceV9InputTests(unittest.TestCase):
    """Real Git and Python inputs reproduce V8 gaps without model execution."""

    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.chain = self.fixture.chain
        self.unlisted = []
        for scope in ("scripts", "formal", "config"):
            path = self.chain / scope / "unlisted.py"
            path.parent.mkdir(exist_ok=True)
            path.write_text("value = 1\n")
            self.unlisted.append(path)
        self.fixture.git("add", "scripts", "formal", "config")
        self.fixture.commit()
        head = self.fixture.git("rev-parse", "HEAD").strip()
        tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.pins = self.fixture.fixture_pins()
        for version in ("V8", "V9"):
            profile = getattr(execution, "PROFILE_" + version)
            manifest = dict(
                execution.checked_manifest(profile), chain_commit=head, chain_tree=tree
            )
            path = self.fixture.profiles / getattr(
                execution, "MANIFEST_NAME_" + version
            )
            path.write_text(json.dumps(manifest))
            for name, value in (
                ("CHAIN_COMMIT_" + version, head),
                ("CHAIN_TREE_" + version, tree),
                ("MANIFEST_SHA256_" + version, execution.digest(path.read_bytes())),
            ):
                self.pins[name] = value
                self.enterContext(patch.object(execution, name, value))

    def refuse_v9(self, reason):
        execution.verify(self.chain, execution.PROFILE_V8)
        with self.assertRaisesRegex(ValueError, reason):
            execution.verify(self.chain, execution.PROFILE_V9)

    def child(self, body, environment=None):
        script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import hepta_smollm_execution_source_v1 as execution
for name, value in json.loads(sys.argv[2]).items():
    setattr(execution, name, Path(value) if name == 'PROFILES' else value)
chain = Path(sys.argv[3])
sys.path.insert(0, str(chain / 'scripts'))
"""
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                script + body,
                str(Path(__file__).resolve().parent),
                json.dumps(self.pins),
                str(self.chain),
            ],
            env=dict(os.environ) if environment is None else environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def merge_checkout(self, *, base=None, parents=None, tree=None):
        source = self.pins["CHAIN_COMMIT_V9"]
        if base is None:
            base = self.fixture.git("rev-parse", source + "^").strip()
        if tree is None:
            tree = self.fixture.git("merge-tree", "--write-tree", base, source).strip()
        if parents is None:
            parents = (base, source)
        merged = self.fixture.git(
            "-c",
            "user.name=Controlled merge fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit-tree",
            tree,
            *(arg for parent in parents for arg in ("-p", parent)),
            "-m",
            "controlled merge fixture",
        ).strip()
        self.fixture.git("checkout", "--quiet", "--detach", merged)
        return base, merged

    def test_clean_repeated_verification_and_import_preserve_source_inputs(self):
        result = self.child("""
execution.verify(chain, execution.PROFILE_V9)
import controlled
assert controlled.fixture_source is True
execution.verify(chain, execution.PROFILE_V9)
assert not (chain / 'scripts/__pycache__').exists()
print('verified-import-verified')
""")
        self.assertEqual(
            (result.returncode, result.stdout),
            (0, "verified-import-verified\n"),
            result.stderr,
        )

    def test_bytecode_policy_requires_interpreter_and_child_environment(self):
        for writes_disabled, inherited in ((False, "1"), (True, None), (True, "0")):
            with self.subTest(writes_disabled=writes_disabled, inherited=inherited):
                environment = dict(os.environ)
                environment.pop("PYTHONDONTWRITEBYTECODE", None)
                if inherited is not None:
                    environment["PYTHONDONTWRITEBYTECODE"] = inherited
                result = self.child(
                    f"sys.dont_write_bytecode = {writes_disabled!r}\n"
                    "execution.verify(chain, execution.PROFILE_V9)\n",
                    environment,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("V9 requires disabled bytecode writes", result.stderr)

    def test_hidden_index_changes_in_each_scope_refuse_without_repair(self):
        for path in self.unlisted:
            relative = str(path.relative_to(self.chain))
            for flag in ("assume-unchanged", "skip-worktree"):
                with self.subTest(path=relative, flag=flag):
                    self.fixture.git("update-index", "--" + flag, "--", relative)
                    try:
                        path.write_text("value = 2\n")
                        self.assertEqual(self.fixture.git("status", "--porcelain"), "")
                        self.refuse_v9("hidden index flags")
                        self.assertEqual(path.read_text(), "value = 2\n")
                        state = self.fixture.git("ls-files", "-v", "--", relative)[0]
                        self.assertTrue(state == "S" or state.islower())
                    finally:
                        path.write_text("value = 1\n")
                        self.fixture.git("update-index", "--no-" + flag, "--", relative)

    def test_ignored_package_shadow_of_pinned_source_refuses(self):
        package = self.chain / "scripts/controlled"
        package.mkdir()
        (package / "__init__.py").write_text("fixture_source = 'unlisted-package'\n")
        (self.chain / ".git/info/exclude").write_text("/scripts/controlled/\n")
        self.refuse_v9("untracked or ignored inputs")
        result = self.child("import controlled\nprint(controlled.fixture_source)\n")
        self.assertEqual(
            (result.returncode, result.stdout), (0, "unlisted-package\n"), result.stderr
        )
        self.assertEqual(self.fixture.source.read_bytes(), b"fixture_source = True\n")

    def test_ignored_unchecked_bytecode_of_pinned_source_refuses(self):
        alternate = self.chain.parent / "alternate.py"
        alternate.write_text("fixture_source = 'unlisted-bytecode'\n")
        cache = Path(importlib.util.cache_from_source(str(self.fixture.source)))
        cache.parent.mkdir()
        py_compile.compile(
            str(alternate),
            cfile=str(cache),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
        (self.chain / ".git/info/exclude").write_text("__pycache__/\n")
        self.refuse_v9("untracked or ignored inputs")
        # -B prevents writes but does not prevent loading pre-existing bytecode.
        result = self.child("import controlled\nprint(controlled.fixture_source)\n")
        self.assertEqual(
            (result.returncode, result.stdout),
            (0, "unlisted-bytecode\n"),
            result.stderr,
        )
        self.assertEqual(self.fixture.source.read_bytes(), b"fixture_source = True\n")

    def test_ignored_extensions_and_directory_symlink_refuse(self):
        (self.chain / ".git/info/exclude").write_text("*\n")
        for relative in (
            "scripts/controlled.so",
            "formal/controlled.pyd",
            "config/alias",
        ):
            with self.subTest(relative=relative):
                path = self.chain / relative
                if relative == "config/alias":
                    path.symlink_to(self.chain / "scripts", target_is_directory=True)
                else:
                    path.write_bytes(b"unreviewed-native-input")
                try:
                    self.refuse_v9("untracked or ignored inputs")
                    self.assertTrue(path.exists())
                finally:
                    path.unlink()

    @unittest.skipIf(
        os.name == "nt", "Git external-diff fixture uses POSIX command quoting"
    )
    def test_unpinned_change_cannot_execute_external_diff_or_textconv(self):
        marker = self.chain.parent / "unexpected-hook"
        hook = self.chain.parent / "hook.py"
        hook.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        command = shlex.join([sys.executable, str(hook)])
        self.fixture.git("config", "diff.external", command)
        self.fixture.git("config", "diff.review.textconv", command)
        (self.chain / ".git/info/attributes").write_text(
            "scripts/unlisted.py diff=review\n"
        )
        self.unlisted[0].write_text("value = 2\n")
        with self.assertRaises(subprocess.CalledProcessError):
            execution.verify(self.chain, execution.PROFILE_V9)
        self.assertFalse(marker.exists())

    def test_canonical_merge_binds_source_and_tested_without_relaxing_head_guard(self):
        base, merged = self.merge_checkout()
        result = execution.verify_merged(self.chain, execution.PROFILE_V9, base)
        self.assertEqual(
            (
                result["chain_commit"],
                result["tested_commit"],
                result["base_commit"],
                result["chain_tree"],
                result["lane"],
            ),
            (
                self.pins["CHAIN_COMMIT_V9"],
                merged,
                base,
                self.pins["CHAIN_TREE_V9"],
                "base-merge",
            ),
        )
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.chain, execution.PROFILE_V9)
        with self.assertRaisesRegex(ValueError, "requires V9"):
            execution.verify_merged(self.chain, execution.PROFILE_V8, base)
        for invalid in (None, "HEAD", ""):
            with self.subTest(base=invalid):
                with self.assertRaisesRegex(ValueError, "explicit exact merge base"):
                    execution.verify_merged(self.chain, execution.PROFILE_V9, invalid)
        self.assertEqual(self.fixture.git("rev-parse", "HEAD").strip(), merged)

    def test_same_tree_cannot_replace_ordered_merge_parents_or_exact_base(self):
        source = self.pins["CHAIN_COMMIT_V9"]
        tree = self.pins["CHAIN_TREE_V9"]
        base, _ = self.merge_checkout()
        with self.assertRaisesRegex(ValueError, "parents differ"):
            execution.verify_merged(self.chain, execution.PROFILE_V9, source)
        for parents in ((source, base), (source,)):
            with self.subTest(parents=parents):
                self.merge_checkout(base=base, parents=parents, tree=tree)
                self.assertEqual(
                    self.fixture.git("rev-parse", "HEAD^{tree}").strip(), tree
                )
                with self.assertRaisesRegex(ValueError, "parents differ"):
                    execution.verify_merged(self.chain, execution.PROFILE_V9, base)

    def test_merge_rejects_ignored_package_bytecode_and_hidden_index_inputs(self):
        from hepta_ci_candidate import candidate_plan

        base, merged = self.merge_checkout()
        for kind in ("package", "bytecode"):
            with self.subTest(kind=kind):
                if kind == "package":
                    path = self.chain / "scripts/controlled/__init__.py"
                    path.parent.mkdir()
                    path.write_text("fixture_source = 'unlisted-package'\n")
                else:
                    alternate = self.chain.parent / "alternate.py"
                    alternate.write_text("fixture_source = 'unlisted-bytecode'\n")
                    path = Path(
                        importlib.util.cache_from_source(str(self.fixture.source))
                    )
                    path.parent.mkdir()
                    py_compile.compile(
                        str(alternate),
                        cfile=str(path),
                        doraise=True,
                        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
                    )
                (self.chain / ".git/info/exclude").write_text("*\n")
                try:
                    # The existing candidate owner alone accepts these ignored
                    # inputs even on the exact canonical merge checkout.
                    candidate_plan(
                        source=self.pins["CHAIN_COMMIT_V9"],
                        tested=merged,
                        lane="base-merge",
                        base=base,
                        repository=self.chain,
                    )
                    with self.assertRaisesRegex(
                        ValueError, "untracked or ignored inputs"
                    ):
                        execution.verify_merged(self.chain, execution.PROFILE_V9, base)
                    self.assertTrue(path.exists())
                finally:
                    path.unlink()
                    path.parent.rmdir()
        path = self.unlisted[0]
        relative = str(path.relative_to(self.chain))
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.fixture.git("update-index", "--" + flag, "--", relative)
                try:
                    path.write_text("value = 2\n")
                    index = (self.chain / ".git/index").read_bytes()
                    with self.assertRaisesRegex(
                        ValueError, "dirty or has hidden index"
                    ):
                        execution.verify_merged(self.chain, execution.PROFILE_V9, base)
                    self.assertEqual((self.chain / ".git/index").read_bytes(), index)
                    self.assertEqual(path.read_text(), "value = 2\n")
                finally:
                    path.write_text("value = 1\n")
                    self.fixture.git("update-index", "--no-" + flag, "--", relative)
        self.assertEqual(self.fixture.git("rev-parse", "HEAD").strip(), merged)

    def test_merge_refuses_changed_canonical_tree_and_forged_pinned_tree(self):
        source = self.pins["CHAIN_COMMIT_V9"]
        self.fixture.git("checkout", "--quiet", "--detach", source + "^")
        (self.chain / "base-only").write_text("independent base change\n")
        self.fixture.git("add", "base-only")
        self.fixture.commit()
        base = self.fixture.git("rev-parse", "HEAD").strip()
        canonical = self.fixture.git("merge-tree", "--write-tree", base, source).strip()
        self.assertNotEqual(canonical, self.pins["CHAIN_TREE_V9"])
        for tree, reason in (
            (canonical, "exact integrated Chain tree"),
            (self.pins["CHAIN_TREE_V9"], "canonical merge"),
        ):
            with self.subTest(tree=tree):
                self.merge_checkout(base=base, tree=tree)
                with self.assertRaisesRegex(ValueError, reason):
                    execution.verify_merged(self.chain, execution.PROFILE_V9, base)

    def test_merge_retains_interpreter_and_child_bytecode_policy(self):
        base, _ = self.merge_checkout()
        for disabled, inherited in ((False, "1"), (True, None)):
            with self.subTest(disabled=disabled, inherited=inherited):
                environment = dict(os.environ)
                environment.pop("PYTHONDONTWRITEBYTECODE", None)
                if inherited is not None:
                    environment["PYTHONDONTWRITEBYTECODE"] = inherited
                result = self.child(
                    f"sys.dont_write_bytecode = {disabled!r}\n"
                    f"execution.verify_merged(chain, execution.PROFILE_V9, {base!r})\n",
                    environment,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("V9 requires disabled bytecode writes", result.stderr)


if __name__ == "__main__":
    unittest.main()
