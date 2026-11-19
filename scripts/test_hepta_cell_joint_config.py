import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hepta_cell_joint_config as config


class JointConfigurationFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Cell integrity test")
        self.git("config", "user.email", "cell-integrity@example.invalid")
        (self.source / "code.rs").write_text("const VALUE: u8 = 1;\n")
        self.git("add", "code.rs")
        self.git("commit", "-qm", "test source")
        self.document = {
            "schema": config.SCHEMA,
            "source": {
                "repository": "example/cell",
                "commit": self.git("rev-parse", "HEAD"),
                "tree": self.git("rev-parse", "HEAD^{tree}"),
            },
            "artifacts": {
                role: self.bind(role, (role + "\n").encode()) for role in config.ROLES
            },
            "required_workflows": [".github/workflows/cell.yml"],
        }
        self.ci = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 7,
                    "head_sha": self.document["source"]["commit"],
                    "repository": {"full_name": "example/cell"},
                    "path": ".github/workflows/cell.yml",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                    "html_url": "https://example.invalid/run/7",
                }
            ],
        }
        self.bind_ci()

    def git(self, *args):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.source), *args], stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def bind(self, name, data):
        (self.artifacts / name).write_bytes(data)
        return {
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    def bind_ci(self):
        self.document["ci_evidence"] = self.bind(
            "ci.json", json.dumps(self.ci).encode()
        )

    def verify(self):
        return config.verify(self.document, self.source, self.artifacts)


class JointConfigurationTests(JointConfigurationFixture):
    def test_complete_identity_has_no_adoption_authority(self):
        result = self.verify()
        self.assertEqual(result["source"], self.document["source"])
        self.assertFalse(result["authority_granted"])
        self.assertFalse(result["production_qualification"])
        self.assertFalse(result["provider_authenticity_verified"])

    def test_unstaged_staged_and_untracked_sources_reject(self):
        for mode in ("unstaged", "staged", "untracked"):
            with self.subTest(mode=mode):
                if mode == "untracked":
                    (self.source / "extra.rs").write_text("changed")
                else:
                    (self.source / "code.rs").write_text("changed")
                    if mode == "staged":
                        self.git("add", "code.rs")
                with self.assertRaisesRegex(ValueError, "source checkout"):
                    self.verify()
                self.git("reset", "--hard", "HEAD")
                self.git("clean", "-fd")

    def test_same_tree_other_commit_is_not_same_execution(self):
        self.git("commit", "--allow-empty", "-qm", "other execution identity")
        with self.assertRaisesRegex(ValueError, "execution tree"):
            self.verify()

    def test_hidden_tracked_bytes_and_modes_are_rejected(self):
        path = self.source / "code.rs"
        original = path.read_bytes()
        for mode in ("assume-unchanged", "skip-worktree", "filemode"):
            with self.subTest(mode=mode):
                if mode == "filemode":
                    self.git("config", "core.filemode", "false")
                    path.chmod(0o755)
                else:
                    self.git("update-index", "--" + mode, "code.rs")
                    path.write_bytes(b"x" * len(original))
                self.assertEqual(self.git("status", "--porcelain"), "")
                with self.assertRaisesRegex(ValueError, "tracked source"):
                    self.verify()
                if mode != "filemode":
                    self.git("update-index", "--no-" + mode, "code.rs")
                path.write_bytes(original)
                path.chmod(0o644)

    def test_tracked_symlink_target_is_verified_without_following_it(self):
        link = self.source / "LICENSE"
        link.symlink_to("../outside-license")
        self.git("add", "LICENSE")
        self.git("commit", "-qm", "tracked link")
        self.document["source"].update(
            commit=self.git("rev-parse", "HEAD"),
            tree=self.git("rev-parse", "HEAD^{tree}"),
        )
        self.ci["workflow_runs"][0]["head_sha"] = self.document["source"]["commit"]
        self.bind_ci()
        self.verify()
        self.git("update-index", "--assume-unchanged", "LICENSE")
        link.unlink()
        link.symlink_to("../different-license")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "tracked source symlink"):
            self.verify()

    def test_final_source_scan_rejects_parent_replacement_after_open(self):
        parent = self.source / "src"
        parent.mkdir()
        (self.source / "code.rs").rename(parent / "code.rs")
        self.git("add", "-A")
        self.git("commit", "-qm", "nested source")
        self.document["source"].update(
            commit=self.git("rev-parse", "HEAD"),
            tree=self.git("rev-parse", "HEAD^{tree}"),
        )
        self.ci["workflow_runs"][0]["head_sha"] = self.document["source"]["commit"]
        self.bind_ci()
        original, calls = config.regular_file, []

        @contextmanager
        def changing_read(root_fd, name):
            with original(root_fd, name) as stream:
                if name == "src/code.rs":
                    calls.append(name)
                    if len(calls) == 2:
                        moved = self.root / "moved-source"
                        parent.rename(moved)
                        parent.symlink_to(moved, target_is_directory=True)
                yield stream

        with patch.object(config, "regular_file", changing_read):
            with self.assertRaisesRegex(ValueError, "symlinks"):
                self.verify()
        self.assertEqual(len(calls), 2)

    def test_missing_role_cannot_freeze(self):
        for role in config.ROLES:
            document = copy.deepcopy(self.document)
            del document["artifacts"][role]
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "eight"):
                config.verify(document, self.source, self.artifacts)

    def test_same_size_model_tampering_is_detected(self):
        path = self.artifacts / "candidate_model"
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaisesRegex(ValueError, "artifact bytes"):
            self.verify()

    def test_an_earlier_artifact_cannot_change_while_later_inputs_are_read(self):
        read = config.read_artifact

        def changing_read(root, binding, **options):
            result = read(root, binding, **options)
            if binding["path"] == "budget":
                path = self.artifacts / "adoption_rules"
                path.write_bytes(b"x" * path.stat().st_size)
            return result

        with patch.object(config, "read_artifact", side_effect=changing_read):
            with self.assertRaisesRegex(ValueError, "during joint configuration"):
                self.verify()

    def test_artifact_size_symlink_and_escape_are_rejected(self):
        original = self.document["artifacts"]["trainer"].copy()
        for change in ({"bytes": True}, {"bytes": 1}, {"path": "../trainer"}):
            self.document["artifacts"]["trainer"] = original | change
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()
        self.document["artifacts"]["trainer"] = original
        path = self.artifacts / "trainer"
        path.rename(self.artifacts / "original")
        path.symlink_to(self.artifacts / "original")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.verify()

    def test_parent_symlink_swap_cannot_escape_the_artifact_root(self):
        nested = self.artifacts / "nested"
        outside = self.root / "outside"
        nested.mkdir()
        outside.mkdir()
        data = b"identical expected bytes"
        (outside / "model").write_bytes(data)
        self.document["artifacts"]["candidate_model"] = self.bind("nested/model", data)
        original_open, original_check = os.open, Path.is_symlink
        swapped = False

        def swap():
            nonlocal swapped
            if not swapped:
                nested.rename(self.artifacts / "moved")
                nested.symlink_to(outside, target_is_directory=True)
                swapped = True

        def checked(path):
            result = original_check(path)
            if path == nested and not result:
                swap()
            return result

        def opened(path, flags, *args, **kwargs):
            if path == "nested" and flags & os.O_DIRECTORY:
                swap()
            return original_open(path, flags, *args, **kwargs)

        with patch.object(Path, "is_symlink", checked):
            with patch.object(os, "open", side_effect=opened) as intercepted:
                with patch.object(
                    os, "supports_dir_fd", os.supports_dir_fd | {intercepted}
                ):
                    with self.assertRaises(ValueError):
                        self.verify()
        self.assertTrue(swapped)

    def test_ci_other_source_or_repository_is_rejected(self):
        for change in (
            {"head_sha": "1" * 40},
            {"repository": {"full_name": "other/cell"}},
        ):
            original = self.ci["workflow_runs"][0].copy()
            self.ci["workflow_runs"][0].update(change)
            self.bind_ci()
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "another source"),
            ):
                self.verify()
            self.ci["workflow_runs"][0] = original

    def test_incomplete_duplicate_and_missing_ci_are_rejected(self):
        for mode in ("pagination", "duplicate", "missing"):
            ci = copy.deepcopy(self.ci)
            if mode == "pagination":
                ci["total_count"] += 1
            elif mode == "duplicate":
                ci["workflow_runs"] *= 2
                ci["total_count"] = 2
            else:
                ci["workflow_runs"][0]["path"] = ".github/workflows/other.yml"
            self.document["ci_evidence"] = self.bind("ci.json", json.dumps(ci).encode())
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.verify()

    def test_required_failure_running_or_skipped_is_not_success(self):
        for status, conclusion in (
            ("in_progress", None),
            ("completed", "failure"),
            ("completed", "skipped"),
        ):
            self.ci["workflow_runs"][0].update(status=status, conclusion=conclusion)
            self.bind_ci()
            with (
                self.subTest(conclusion=conclusion),
                self.assertRaisesRegex(ValueError, "not succeeded"),
            ):
                self.verify()

    def test_invalid_json_cannot_override_evidence(self):
        for raw in (
            b'{"head":1,"head":2}',
            b'{"cost":NaN}',
            b'{"cost":Infinity}',
            b'{"cost":1e999}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                config.strict_json(raw)


class JointConfigurationV2Tests(JointConfigurationFixture):
    """Engineering integrity controls; no model execution or scientific evaluation."""

    def setUp(self):
        super().setUp()
        self.legacy = copy.deepcopy(self.document)
        self.document["schema"] = "hepta.cell-joint-config.v2"
        self.document["artifacts"]["candidate_model"] = self.bind(
            "candidate-model-v2.bin", (self.artifacts / "incumbent_model").read_bytes()
        )
        for axis in ("state_schema", "encoder", "backend"):
            for prefix in ("", "incumbent_"):
                role = prefix + axis
                self.document["artifacts"][role] = self.bind(
                    role, (axis + "\n").encode()
                )
        models = {}
        for role, prefix in (
            ("incumbent_model", "incumbent_"),
            ("candidate_model", ""),
        ):
            models[role] = {"model_sha256": self.document["artifacts"][role]["sha256"]}
            for axis in ("state_schema", "encoder", "backend"):
                models[role][axis + "_sha256"] = self.document["artifacts"][
                    prefix + axis
                ]["sha256"]
        self.document["compatibility"] = {
            "schema": "hepta.cell-model-compatibility.v1",
            "models": models,
            "state_transition": {"mode": "carry"},
        }
        self.calls = 0

    def cli(self, readback=None, role=None, error=None, task="task-successor-1"):
        self.calls += 1
        configuration = self.root / "configuration.json"
        configuration.write_text(json.dumps(self.document))
        output = self.root / f"result-{self.calls}.json"
        argv = [
            sys.executable,
            str(Path(config.__file__).resolve()),
            str(configuration),
            "--source-root",
            str(self.source),
            "--artifact-root",
            str(self.artifacts),
            "--output",
            str(output),
        ]
        if readback is not None:
            path = self.root / "consumer.json"
            path.write_bytes(
                readback
                if isinstance(readback, bytes)
                else json.dumps(readback).encode()
            )
            argv += ["--consumer-readback", str(path)]
        if role is not None:
            argv += ["--expected-model-role", role]
            if task is not None:
                argv += ["--expected-task-id", task]
        process = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        self.assertEqual(
            process.returncode, 1 if error else 0, process.stdout + process.stderr
        )
        response = json.loads(process.stdout)
        if error:
            self.assertEqual(response["configuration_integrity"], "rejected")
            self.assertIn(error, response["error"])
            self.assertFalse(output.exists())
            return response
        return json.loads(output.read_text())

    def readback(self, result, role="candidate_model"):
        return {
            "schema": "hepta.cell-consumption-readback.v1",
            "task_id": "task-successor-1",
            "model_role": role,
            "bundle_sha256": result["bundle_sha256"],
        } | self.document["compatibility"]["models"][role]

    def test_candidate_and_noupdate_use_the_selected_complete_contract(self):
        self.document["artifacts"]["candidate_model"] = self.document["artifacts"][
            "incumbent_model"
        ].copy()
        models = self.document["compatibility"]["models"]
        models["candidate_model"]["model_sha256"] = models["incumbent_model"][
            "model_sha256"
        ]
        for axis in ("state_schema", "encoder", "backend"):
            binding = self.bind("new-" + axis, (axis + " v2\n").encode())
            self.document["artifacts"][axis] = binding
            models["candidate_model"][axis + "_sha256"] = binding["sha256"]
        self.document["compatibility"]["state_transition"] = {"mode": "reset"}
        frozen = self.cli()
        for role in ("candidate_model", "incumbent_model"):
            with self.subTest(role=role):
                result = self.cli(self.readback(frozen, role), role)
                self.assertEqual(
                    result["consumer"]["consumption_binding_integrity"], "verified"
                )
                for field in (
                    "semantic_compatibility_verified",
                    "state_transition_executed",
                    "model_execution_verified",
                    "actual_successor_consumption_verified",
                    "authority_granted",
                ):
                    self.assertFalse(result[field])
                self.assertFalse(
                    result["consumer"]["consumer_readback_authenticity_verified"]
                )
        self.cli(
            self.readback(frozen, "incumbent_model"),
            "candidate_model",
            "selected model",
        )
        wrong = self.readback(frozen, "incumbent_model") | models["candidate_model"]
        self.cli(wrong, "incumbent_model", "selected model")

    def test_same_model_does_not_allow_reuse_after_any_bound_role_changes(self):
        original = copy.deepcopy(self.document)
        frozen = self.cli()
        old_readback = self.readback(frozen)
        for role in (
            "trainer",
            "evaluator",
            "data",
            "budget",
            "state_schema",
            "encoder",
            "backend",
            "runtime",
            "adoption_rules",
        ):
            with self.subTest(role=role):
                self.document = copy.deepcopy(original)
                binding = self.bind("changed-" + role, (role + " changed\n").encode())
                self.document["artifacts"][role] = binding
                if role in ("state_schema", "encoder", "backend"):
                    self.document["compatibility"]["models"]["candidate_model"][
                        role + "_sha256"
                    ] = binding["sha256"]
                    self.document["compatibility"]["state_transition"] = {
                        "mode": "reset"
                    }
                changed = self.cli()
                self.assertNotEqual(changed["bundle_sha256"], frozen["bundle_sha256"])
                self.cli(old_readback, "candidate_model", "different complete bundle")

    def test_missing_contracts_wrong_versions_and_undeclared_axes_are_rejected(self):
        original = copy.deepcopy(self.document)
        for case in (
            "state_schema",
            "configuration_version",
            "contract_version",
            "model",
            "schema",
            "encoder",
            "backend",
            "transition",
        ):
            with self.subTest(case=case):
                self.document = copy.deepcopy(original)
                declaration = self.document["compatibility"]
                if case == "state_schema":
                    del self.document["artifacts"][case]
                elif case == "configuration_version":
                    self.document["schema"] = "hepta.cell-joint-config.v99"
                elif case == "contract_version":
                    declaration["schema"] = "hepta.cell-model-compatibility.v99"
                elif case == "transition":
                    declaration["state_transition"] = {"mode": "unknown"}
                else:
                    axis = "state_schema" if case == "schema" else case
                    declaration["models"]["candidate_model"][axis + "_sha256"] = (
                        "f" * 64
                    )
                self.cli(
                    error={
                        "state_schema": "v2 requires",
                        "configuration_version": "unknown joint",
                        "contract_version": "unknown or incomplete",
                        "transition": "must declare",
                    }.get(case, "does not match")
                )

    def test_changed_axes_require_reset_or_exact_declared_migration(self):
        original = copy.deepcopy(self.document)
        for axis in ("model", "state_schema", "encoder", "backend"):
            self.document = copy.deepcopy(original)
            binding = self.bind("new-" + axis, (axis + " incompatible\n").encode())
            self.document["artifacts"][
                "candidate_model" if axis == "model" else axis
            ] = binding
            declaration = self.document["compatibility"]
            declaration["models"]["candidate_model"][axis + "_sha256"] = binding[
                "sha256"
            ]
            declaration["state_transition"] = {"mode": "carry"}
            self.cli(error="requires reset or migration")
            declaration["state_transition"] = {"mode": "reset"}
            self.assertFalse(self.cli()["state_transition_executed"])
        declaration["state_transition"] = {"mode": "migrate"}
        self.cli(error="v2 requires")
        migration = self.bind("migration.bin", b"declared migration; never executed\n")
        self.document["artifacts"]["state_migration"] = migration
        self.cli(error="both exact contracts")
        transition = declaration["state_transition"]
        transition["migration_sha256"] = migration["sha256"]
        for label, role in (("from", "incumbent_model"), ("to", "candidate_model")):
            raw = json.dumps(
                declaration["models"][role],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            transition[label + "_contract_sha256"] = hashlib.sha256(raw).hexdigest()
        self.assertFalse(self.cli()["semantic_compatibility_verified"])
        transition["from_contract_sha256"] = transition["to_contract_sha256"]
        self.cli(error="both exact contracts")

    def test_relocated_content_is_stable_but_a_new_source_commit_invalidates_consumption(
        self,
    ):
        frozen = self.cli()
        old_readback = self.readback(frozen)
        moved_source, moved_artifacts = (
            self.root / "other-source",
            self.root / "other-artifacts",
        )
        shutil.copytree(self.source, moved_source)
        shutil.copytree(self.artifacts, moved_artifacts)
        self.source, self.artifacts = moved_source, moved_artifacts
        (self.artifacts / "relocated").mkdir()
        for binding in [
            *self.document["artifacts"].values(),
            self.document["ci_evidence"],
        ]:
            old_path = self.artifacts / binding["path"]
            binding["path"] = "relocated/" + binding["path"]
            old_path.rename(self.artifacts / binding["path"])
        self.assertEqual(
            self.cli(old_readback, "candidate_model")["bundle_sha256"],
            frozen["bundle_sha256"],
        )
        self.git("commit", "--allow-empty", "-qm", "new execution source")
        self.document["source"]["commit"] = self.git("rev-parse", "HEAD")
        self.ci["workflow_runs"][0]["head_sha"] = self.document["source"]["commit"]
        self.bind_ci()
        self.cli(old_readback, "candidate_model", "different complete bundle")

    def test_legacy_output_and_consumer_version_and_input_limits(self):
        current = copy.deepcopy(self.document)
        readback = self.readback(self.cli())
        self.document = self.legacy
        result = self.cli()
        self.assertTrue(result["legacy"])
        self.assertEqual(result["schema"], "hepta.cell-joint-config-integrity.v1")
        self.assertNotIn("bundle_sha256", result)
        self.cli(readback, "candidate_model", "legacy configurations")
        self.document = current
        self.cli(readback, error="explicit expected model role")
        self.cli(readback, "candidate_model", "task identity", task=None)
        self.cli(
            readback | {"task_id": "old-task-same-bundle"},
            "candidate_model",
            "different task",
        )
        self.cli(
            readback | {"schema": "hepta.cell-consumption-readback.v99"},
            "candidate_model",
            "unknown or incomplete",
        )
        self.cli(
            b'{"bundle_sha256": "a", "bundle_sha256": "b"}',
            "candidate_model",
            "duplicate JSON key",
        )
        self.cli(b" " * (1024 * 1024 + 1), "candidate_model", "exceeds 1 MiB")

    def test_new_roles_cannot_bypass_byte_integrity_or_nofollow(self):
        for role in ("state_schema", "incumbent_state_schema", "encoder", "backend"):
            with self.subTest(role=role):
                path = self.artifacts / self.document["artifacts"][role]["path"]
                original = path.read_bytes()
                path.write_bytes(b"x" * len(original))
                self.cli(error="artifact bytes or identity changed")
                path.write_bytes(original)
        path = self.artifacts / "state_schema"
        path.rename(self.artifacts / "real-schema")
        path.symlink_to(self.artifacts / "real-schema")
        self.cli(error="symlinks")

    def test_consumer_helper_rechecks_bundle_and_has_no_input_aliases(self):
        result = self.verify()
        original = copy.deepcopy(self.document)
        readback = self.readback(result)
        self.document["source"]["commit"] = "f" * 40
        self.document["compatibility"]["models"]["candidate_model"]["model_sha256"] = (
            "f" * 64
        )
        self.assertEqual(result["source"], original["source"])
        self.assertEqual(result["bundle"]["compatibility"], original["compatibility"])
        consumer = config.check_consumer_readback(
            result, readback, "candidate_model", "task-successor-1"
        )
        self.assertEqual(consumer["readback"], readback)
        readback["task_id"] = "mutated-after-verification"
        self.assertEqual(consumer["readback"]["task_id"], "task-successor-1")
        tampered = copy.deepcopy(result)
        tampered["bundle"]["compatibility"]["models"]["candidate_model"][
            "model_sha256"
        ] = "f" * 64
        with self.assertRaisesRegex(ValueError, "bundle content"):
            config.check_consumer_readback(
                tampered,
                readback | {"model_sha256": "f" * 64},
                "candidate_model",
                "task-successor-1",
            )
        for field in ("schema", "configuration_integrity"):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "verified v2"),
            ):
                config.check_consumer_readback(
                    result | {field: "rejected"},
                    readback,
                    "candidate_model",
                    "task-successor-1",
                )


if __name__ == "__main__":
    unittest.main()
