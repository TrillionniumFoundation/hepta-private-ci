import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hepta_memory_retrieval_policy as policy
from scripts import hepta_memory_retrieval_refresh_map as refresh


class MapRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Map test fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        for path in refresh.OBJECT_INPUTS:
            target = self.root / path
            if path == refresh.ROOT:
                (target / "src").mkdir(parents=True, exist_ok=True)
                (target / "src/lib.rs").write_text("// fixture\n")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"// fixture {path}\n")
        self.write(
            policy.POLICY_RELATIVE_PATH.as_posix(),
            json.dumps(policy.POLICY),
        )
        self.original = {
            "module": "memory.retrieval",
            "sourceBase": {"commit": "0" * 40, "tree": "0" * 40},
            "sourceIdentityPolicy": "obsolete-policy",
            "claimBoundary": {
                "productionImplementation": False,
                "activation": False,
            },
            "operations": [{"operation": "retrieve"}],
            "observedSourcePaths": [],
        }
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()

    def git(self, *args, input_text=None):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            input=input_text,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD")

    def test_binds_exact_source_policy_objects_claims_and_operations(self):
        mapping = refresh.refresh(self.root, self.head)
        identity = {
            "commit": self.head,
            "tree": self.git("rev-parse", "HEAD^{tree}"),
        }
        self.assertEqual(mapping["sourceBase"], identity)
        self.assertEqual(mapping["observedAtHead"], identity)
        self.assertEqual(
            mapping["sourceIdentityPolicy"],
            refresh.SOURCE_IDENTITY_POLICY,
        )
        for name in ("claimBoundary", "operations"):
            self.assertEqual(mapping[name], self.original[name])
        objects = {
            row["path"]: row["object"]
            for row in mapping["sourceObjects"]
        }
        self.assertEqual(tuple(objects), refresh.OBJECT_INPUTS)
        self.assertEqual(
            objects[refresh.ROOT],
            self.git("rev-parse", "HEAD:" + refresh.ROOT),
        )
        self.assertEqual(
            mapping["observedSourcePaths"],
            list(refresh.INPUTS),
        )

    def test_map_and_parent_directories_are_not_observation_inputs(self):
        mapping = refresh.refresh(self.root, self.head)
        for path in mapping["observedSourcePaths"]:
            self.assertNotEqual(path, refresh.MAP)
            self.assertFalse(refresh.MAP.startswith(path.rstrip("/") + "/"))
        for row in mapping["sourceObjects"]:
            self.assertNotEqual(row["path"], refresh.MAP)
            self.assertFalse(
                refresh.MAP.startswith(row["path"].rstrip("/") + "/")
            )

    def test_map_only_commit_preserves_every_observed_object(self):
        source = self.head
        mapping = refresh.refresh(self.root, source)
        self.write(refresh.MAP, json.dumps(mapping, indent=2) + "\n")
        self.commit()
        candidate = self.head
        self.assertEqual(
            self.git("show", "-s", "--format=%P", candidate),
            source,
        )
        self.assertEqual(
            self.git("diff", "--name-only", source, candidate),
            refresh.MAP,
        )
        self.assertEqual(
            self.git(
                "diff",
                "--name-only",
                source,
                candidate,
                "--",
                *mapping["observedSourcePaths"],
            ),
            "",
        )
        for row in mapping["sourceObjects"]:
            self.assertEqual(
                self.git("rev-parse", f"{candidate}:{row['path']}"),
                row["object"],
            )

    def test_stage_source_emits_fail_closed_proposal(self):
        source = self.head
        mapping, seal = refresh.stage(self.root, source)
        self.assertEqual(seal["state"], "proposal")
        self.assertEqual(seal["source_head_sha"], source)
        self.assertIsNone(seal["candidate_head_sha"])
        self.assertEqual(
            seal["source_tree_sha"],
            mapping["sourceBase"]["tree"],
        )
        self.assertRegex(
            seal["implementation_map_blob_sha"],
            r"^[0-9a-f]{40}$",
        )
        self.assertRegex(
            seal["implementation_map_sha256"],
            r"^[0-9a-f]{64}$",
        )
        for name in (
            "repository_checks_satisfied",
            "implementation_ready",
            "production_ready",
            "merge_ready",
        ):
            self.assertFalse(seal[name])

    def test_stage_exact_map_only_child_emits_sealed_identity(self):
        source = self.head
        mapping = refresh.refresh(self.root, source)
        self.write(refresh.MAP, json.dumps(mapping, indent=2) + "\n")
        self.commit()
        candidate = self.head

        observed, seal = refresh.stage(self.root, candidate)

        self.assertEqual(observed, mapping)
        self.assertEqual(seal["state"], "sealed")
        self.assertEqual(seal["source_head_sha"], source)
        self.assertEqual(seal["candidate_head_sha"], candidate)
        self.assertEqual(
            seal["candidate_tree_sha"],
            self.git("rev-parse", "HEAD^{tree}"),
        )
        self.assertEqual(
            seal["implementation_map_blob_sha"],
            self.git("rev-parse", f"HEAD:{refresh.MAP}"),
        )
        projection = refresh._projection(seal)
        self.assertIn(source, projection)
        self.assertIn(candidate, projection)
        self.assertIn("implementation_ready = false", projection)

    def test_stage_rejects_tampered_map_only_child(self):
        mapping = refresh.refresh(self.root, self.head)
        mapping["sourceBase"]["commit"] = "0" * 40
        self.write(refresh.MAP, json.dumps(mapping, indent=2) + "\n")
        self.commit()
        with self.assertRaises(refresh.RefreshError):
            refresh.stage(self.root, self.head)

    def test_untracked_file_invalidates_clean_source(self):
        self.write("untracked.txt", "work in progress")
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_modified_source_invalidates_clean_source(self):
        target = self.root / refresh.OBJECT_INPUTS[0]
        target.write_text("// changed\n")
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_another_head_is_rejected(self):
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, "a" * 40)

    def test_unsafe_inherited_path_is_rejected(self):
        self.original["observedSourcePaths"] = ["../escape"]
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_safe_legacy_path_is_dropped_in_favor_of_canonical_policy(self):
        self.original["observedSourcePaths"] = ["legacy/safe/path"]
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()
        mapping = refresh.refresh(self.root, self.head)
        self.assertEqual(
            mapping["observedSourcePaths"],
            list(refresh.INPUTS),
        )
        self.assertNotIn(
            "legacy/safe/path",
            mapping["observedSourcePaths"],
        )

    def test_wrong_module_is_rejected(self):
        self.original["module"] = "another.module"
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_missing_paths_are_explicit_without_fabricated_objects(self):
        mapping = refresh.refresh(self.root, self.head)
        self.assertIn(refresh.ROOT, mapping["observedSourcePaths"])
        self.assertNotIn(refresh.ROOT, mapping["observedMissingPaths"])
        self.assertIn("MODULE.bazel", mapping["observedMissingPaths"])
        self.assertNotIn(
            "MODULE.bazel",
            {row["path"] for row in mapping["sourceObjects"]},
        )

    def test_every_object_input_is_unique_sorted_and_observed(self):
        mapping = refresh.refresh(self.root, self.head)
        object_paths = [row["path"] for row in mapping["sourceObjects"]]
        self.assertEqual(object_paths, sorted(set(object_paths)))
        for path in object_paths:
            self.assertTrue(
                any(
                    path == parent
                    or path.startswith(parent.rstrip("/") + "/")
                    for parent in mapping["observedSourcePaths"]
                )
            )


if __name__ == "__main__":
    unittest.main()
