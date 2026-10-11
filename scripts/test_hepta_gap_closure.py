#!/usr/bin/env python3
"""Hostile tests for the exact Hepta source/merge identity verifier."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "hepta_gap_closure_under_test",
    SCRIPT_DIR / "hepta-gap-closure.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load scripts/hepta-gap-closure.py")
GAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GAP)


class ExactIdentityTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temporary_path = Path(self.temporary.name)
        self.repo = self.temporary_path / "repo"
        self.repo.mkdir()
        self.event_path = self.temporary_path / "event.json"
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Hepta Identity Test")
        self.git("config", "user.email", "identity-test@invalid")
        self.git("config", "commit.gpgsign", "false")

        self.write(GAP.IDENTITY_WORKFLOW_PATH, "name: identity-test\n")
        self.write(GAP.IDENTITY_VERIFIER_PATH, "# verifier fixture\n")
        self.write(GAP.SOURCE_REGISTRY_VERIFIER_PATH, "# registry fixture\n")
        self.write(
            GAP.QUALIFICATION_MANIFEST_PATH,
            json.dumps(
                {
                    "candidate_identity": GAP.STATIC_CANDIDATE_IDENTITY,
                    "schema_version": 2,
                    "source_identity_policy": GAP.STATIC_SOURCE_IDENTITY_POLICY,
                },
                sort_keys=True,
            )
            + "\n",
        )
        self.write(
            GAP.QUALIFICATION_PLAN_AUDIT_PATH,
            json.dumps(
                {
                    "candidateIdentity": GAP.STATIC_CANDIDATE_IDENTITY,
                    "schema": "hepta.test-plan-audit.v1",
                },
                sort_keys=True,
            )
            + "\n",
        )
        self.write("docs/spec.md", "root\n")
        self.write_document_system([GAP.DOCUMENT_SYSTEM_PATH, "docs/spec.md"])
        self.root_commit = self.commit("root")
        self.write("docs/spec.md", "base\n")
        self.base = self.commit("base")
        self.write("docs/spec.md", "source one\n")
        self.source_one = self.commit("source one")
        self.write("docs/spec.md", "source two\n")
        self.source = self.commit("source two")
        self.write_pull_request_event()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(
        self,
        *arguments: str,
        input_text: str | None = None,
        check: bool = True,
    ) -> str:
        process = subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and process.returncode:
            self.fail(
                "git "
                + " ".join(arguments)
                + " failed: "
                + (process.stderr or process.stdout)
            )
        return process.stdout.strip()

    def write(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_document_system(self, paths: list[str]) -> None:
        self.write(
            GAP.DOCUMENT_SYSTEM_PATH,
            json.dumps(
                {
                    "canonicalPaths": paths,
                    "repository": {
                        "fullName": "example/hepta",
                        "id": 101,
                    },
                },
                sort_keys=True,
            )
            + "\n",
        )

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def pull_request_event(self, merge_commit: str | None = None) -> dict[str, Any]:
        repository = {"full_name": "example/hepta", "id": 101}
        return {
            "action": "synchronize",
            "number": 17,
            "pull_request": {
                "base": {
                    "ref": "integration",
                    "repo": copy.deepcopy(repository),
                    "sha": self.base,
                },
                "head": {
                    "ref": "candidate",
                    "repo": copy.deepcopy(repository),
                    "sha": self.source,
                },
                "merge_commit_sha": merge_commit,
            },
            "repository": repository,
        }

    def write_event(self, payload: dict[str, Any]) -> None:
        self.event_path.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_pull_request_event(self, merge_commit: str | None = None) -> None:
        self.write_event(self.pull_request_event(merge_commit))

    def write_push_event(self) -> None:
        self.write_event(
            {
                "after": self.source,
                "before": self.base,
                "deleted": False,
                "ref": "refs/heads/candidate",
                "repository": {
                    "full_name": "example/hepta",
                    "id": 101,
                },
            }
        )

    def identity_arguments(
        self,
        *,
        kind: str = "source-head",
        expected: str | None = None,
        event_name: str = "pull_request",
    ) -> dict[str, Any]:
        return {
            "base": self.base,
            "event_name": event_name,
            "event_path": str(self.event_path),
            "expected": expected or self.source,
            "kind": kind,
            "repo": self.repo,
            "repository": "example/hepta",
            "repository_id": 101,
            "source": self.source,
            "workflow_path": GAP.IDENTITY_WORKFLOW_PATH,
        }

    def expected_merge_tree(self) -> str:
        return GAP.identity_expected_merge_tree(self.repo, self.base, self.source)

    def make_merge(
        self,
        *,
        parents: list[str] | None = None,
        tree: str | None = None,
        message: str = "synthetic merge",
    ) -> str:
        arguments = ["commit-tree", tree or self.expected_merge_tree()]
        for parent in parents or [self.base, self.source]:
            arguments.extend(["-p", parent])
        return self.git(*arguments, input_text=message + "\n")

    def checkout(self, commit: str) -> None:
        self.git("checkout", "--detach", commit)

    def repository_snapshot(self) -> dict[str, tuple[str, str]]:
        snapshot: dict[str, tuple[str, str]] = {}
        for path in sorted(self.repo.rglob("*")):
            relative = path.relative_to(self.repo).as_posix()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif path.is_file():
                snapshot[relative] = (
                    "file",
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return snapshot

    def test_linear_source_receipt_round_trip(self) -> None:
        receipt = GAP.build_exact_identity_receipt(**self.identity_arguments())
        self.assertEqual([self.source_one, self.source], receipt["sourceLineage"])
        self.assertEqual([self.source_one], receipt["sourceParents"])
        self.assertEqual(self.base, receipt["baseCommit"])
        self.assertEqual(self.source, receipt["sourceCommit"])
        self.assertIsNone(receipt["mergeCandidate"])
        self.assertEqual("pull_request", receipt["eventIdentity"]["eventName"])
        self.assertEqual(17, receipt["eventIdentity"]["pullRequestNumber"])
        self.assertFalse(receipt["authorityGranted"])
        self.assertEqual(
            receipt,
            GAP.verify_exact_identity_receipt(
                receipt,
                **self.identity_arguments(),
            ),
        )

    def test_push_source_receipt_is_event_bound(self) -> None:
        self.write_push_event()
        arguments = self.identity_arguments(event_name="push")
        receipt = GAP.build_exact_identity_receipt(**arguments)
        self.assertEqual(
            {"eventName": "push", "ref": "refs/heads/candidate"},
            receipt["eventIdentity"],
        )
        GAP.verify_exact_identity_receipt(receipt, **arguments)

    def test_source_range_must_be_nonempty(self) -> None:
        payload = self.pull_request_event()
        payload["pull_request"]["base"]["sha"] = self.source
        self.write_event(payload)
        arguments = self.identity_arguments()
        arguments["base"] = self.source
        with self.assertRaisesRegex(GAP.ExactIdentityError, "must advance"):
            GAP.build_exact_identity_receipt(**arguments)

    def test_source_range_rejects_merge_commits(self) -> None:
        self.git("checkout", "-b", "side", self.source_one)
        self.write("docs/side.md", "side\n")
        self.commit("side")
        self.checkout(self.source)
        self.git("merge", "--no-ff", "side", "-m", "forbidden source merge")
        merged_source = self.git("rev-parse", "HEAD")
        self.source = merged_source
        self.write_pull_request_event()
        with self.assertRaisesRegex(GAP.ExactIdentityError, "merge commit"):
            GAP.build_exact_identity_receipt(**self.identity_arguments())

    def test_source_range_rejects_diverged_base(self) -> None:
        self.checkout(self.root_commit)
        self.write("docs/spec.md", "sibling\n")
        sibling = self.commit("sibling")
        self.checkout(self.source)
        payload = self.pull_request_event()
        payload["pull_request"]["base"]["sha"] = sibling
        self.write_event(payload)
        arguments = self.identity_arguments()
        arguments["base"] = sibling
        with self.assertRaisesRegex(GAP.ExactIdentityError, "not an ancestor"):
            GAP.build_exact_identity_receipt(**arguments)

    def test_checkout_and_literal_oid_are_exact(self) -> None:
        with self.assertRaisesRegex(GAP.ExactIdentityError, "checkout"):
            GAP.build_exact_identity_receipt(
                **self.identity_arguments(expected=self.source_one)
            )
        arguments = self.identity_arguments()
        arguments["source"] = self.source[:12]
        with self.assertRaisesRegex(GAP.ExactIdentityError, "source Git OID"):
            GAP.build_exact_identity_receipt(**arguments)
        arguments = self.identity_arguments()
        arguments["workflow_path"] = GAP.IDENTITY_VERIFIER_PATH
        with self.assertRaisesRegex(GAP.ExactIdentityError, "workflow path drift"):
            GAP.build_exact_identity_receipt(**arguments)

    def test_inherited_git_environment_cannot_redirect_verification(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": str(self.temporary_path / "attacker.git"),
                "GIT_INDEX_FILE": str(self.temporary_path / "attacker.index"),
                "GIT_OBJECT_DIRECTORY": str(self.temporary_path / "objects"),
            },
        ):
            receipt = GAP.build_exact_identity_receipt(**self.identity_arguments())
        self.assertEqual(self.source, receipt["sourceCommit"])
        arguments = self.identity_arguments()
        arguments["repo"] = self.repo / "docs"
        with self.assertRaisesRegex(GAP.ExactIdentityError, "checkout root"):
            GAP.build_exact_identity_receipt(**arguments)

    def test_dirty_index_and_untracked_file_are_rejected(self) -> None:
        self.write("docs/spec.md", "staged\n")
        self.git("add", "docs/spec.md")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "working tree"):
            GAP.build_exact_identity_receipt(**self.identity_arguments())
        self.git("restore", "--staged", "docs/spec.md")
        self.git("restore", "docs/spec.md")
        self.write("untracked.txt", "untracked\n")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "working tree"):
            GAP.build_exact_identity_receipt(**self.identity_arguments())

    def test_exact_merge_receipt_and_verification_are_read_only(self) -> None:
        merge = self.make_merge()
        self.checkout(merge)
        self.write_pull_request_event(merge)
        arguments = self.identity_arguments(kind="merge-candidate", expected=merge)
        before = self.repository_snapshot()
        receipt = GAP.build_exact_identity_receipt(**arguments)
        GAP.verify_exact_identity_receipt(receipt, **arguments)
        after = self.repository_snapshot()
        self.assertEqual(before, after)
        self.assertEqual([self.base, self.source], receipt["mergeParents"])
        self.assertEqual(self.expected_merge_tree(), receipt["mergeTree"])

    def test_merge_parent_order_and_tree_are_closed_world(self) -> None:
        correct_tree = self.expected_merge_tree()
        variants = [
            (
                "reversed parents",
                [self.source, self.base],
                correct_tree,
                "parent order",
            ),
            (
                "extra parent",
                [self.base, self.source, self.root_commit],
                correct_tree,
                "parent order",
            ),
            (
                "wrong tree",
                [self.base, self.source],
                GAP.identity_commit_tree(self.repo, self.base),
                "tree mismatch",
            ),
        ]
        for name, parents, tree, failure in variants:
            with self.subTest(name=name):
                candidate = self.make_merge(
                    parents=parents,
                    tree=tree,
                    message=name,
                )
                self.checkout(candidate)
                self.write_pull_request_event(candidate)
                with self.assertRaisesRegex(GAP.ExactIdentityError, failure):
                    GAP.build_exact_identity_receipt(
                        **self.identity_arguments(
                            kind="merge-candidate",
                            expected=candidate,
                        )
                    )

    def test_event_merge_observation_cannot_override_synthetic_merge(self) -> None:
        merge = self.make_merge()
        self.checkout(merge)
        self.write_pull_request_event(self.source)
        arguments = self.identity_arguments(
            kind="merge-candidate",
            expected=merge,
        )
        receipt = GAP.build_exact_identity_receipt(**arguments)
        self.assertEqual(self.source, receipt["eventIdentity"]["mergeCommit"])
        self.assertEqual(merge, receipt["mergeCandidate"])
        self.assertEqual([self.base, self.source], receipt["mergeParents"])
        GAP.verify_exact_identity_receipt(receipt, **arguments)
        self.write_pull_request_event(None)
        nullable = GAP.build_exact_identity_receipt(**arguments)
        self.assertIsNone(nullable["eventIdentity"]["mergeCommit"])
        GAP.verify_exact_identity_receipt(nullable, **arguments)

        self.write_push_event()
        with self.assertRaisesRegex(
            GAP.ExactIdentityError,
            "requires a pull request",
        ):
            GAP.build_exact_identity_receipt(
                **self.identity_arguments(
                    kind="merge-candidate",
                    expected=merge,
                    event_name="push",
                )
            )

    def test_event_identity_rejects_missing_and_mismatched_fields(self) -> None:
        variants: list[tuple[str, dict[str, Any], str]] = []
        missing_repository = self.pull_request_event()
        missing_repository.pop("repository")
        variants.append(("missing repository", missing_repository, "repository"))
        boolean_repository_id = self.pull_request_event()
        boolean_repository_id["repository"]["id"] = True
        variants.append(("boolean repository id", boolean_repository_id, "id drift"))
        wrong_base = self.pull_request_event()
        wrong_base["pull_request"]["base"]["sha"] = self.root_commit
        variants.append(("wrong base", wrong_base, "base drift"))
        wrong_source = self.pull_request_event()
        wrong_source["pull_request"]["head"]["sha"] = self.source_one
        variants.append(("wrong source", wrong_source, "source drift"))
        missing_action = self.pull_request_event()
        missing_action.pop("action")
        variants.append(("missing action", missing_action, "action"))
        missing_pull_request = self.pull_request_event()
        missing_pull_request.pop("pull_request")
        variants.append(
            ("missing pull request", missing_pull_request, "event identity")
        )
        for name, payload, failure in variants:
            with self.subTest(name=name):
                self.write_event(payload)
                with self.assertRaisesRegex(GAP.ExactIdentityError, failure):
                    GAP.build_exact_identity_receipt(**self.identity_arguments())

    def test_event_file_must_be_external_and_shape_must_match_name(self) -> None:
        internal_event = self.repo / "event.json"
        internal_event.write_text(
            json.dumps(self.pull_request_event()),
            encoding="utf-8",
        )
        arguments = self.identity_arguments()
        arguments["event_path"] = str(internal_event)
        with self.assertRaisesRegex(GAP.ExactIdentityError, "outside"):
            GAP.build_exact_identity_receipt(**arguments)

        internal_event.unlink()
        self.write_pull_request_event()
        with self.assertRaisesRegex(GAP.ExactIdentityError, "push event shape"):
            GAP.build_exact_identity_receipt(
                **self.identity_arguments(event_name="push")
            )

    def test_event_and_arguments_cannot_override_canonical_repository(self) -> None:
        payload = self.pull_request_event()
        payload["repository"]["id"] = 202
        payload["pull_request"]["base"]["repo"]["id"] = 202
        payload["pull_request"]["head"]["repo"]["id"] = 202
        self.write_event(payload)
        arguments = self.identity_arguments()
        arguments["repository_id"] = 202
        with self.assertRaisesRegex(GAP.ExactIdentityError, "canonical repository id"):
            GAP.build_exact_identity_receipt(**arguments)

    def test_receipt_tampering_staleness_and_future_skew_fail(self) -> None:
        receipt = GAP.build_exact_identity_receipt(**self.identity_arguments())
        variants: list[tuple[str, dict[str, Any], str]] = []
        tampered_digest = copy.deepcopy(receipt)
        tampered_digest["documentSetDigest"] = "0" * 64
        variants.append(("digest", tampered_digest, "documentSetDigest"))
        tampered_lineage = copy.deepcopy(receipt)
        tampered_lineage["sourceLineage"].reverse()
        variants.append(("lineage", tampered_lineage, "sourceLineage"))
        extra_field = copy.deepcopy(receipt)
        extra_field["untrusted"] = True
        variants.append(("extra field", extra_field, "field set"))
        authority = copy.deepcopy(receipt)
        authority["authorityGranted"] = True
        variants.append(("authority", authority, "authority"))
        stale = copy.deepcopy(receipt)
        stale["observedAt"] = (
            (datetime.now(timezone.utc) - timedelta(days=2))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        variants.append(("stale", stale, "stale"))
        future = copy.deepcopy(receipt)
        future["observedAt"] = (
            (datetime.now(timezone.utc) + timedelta(minutes=10))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        variants.append(("future", future, "future skew"))
        boolean_ttl = copy.deepcopy(receipt)
        boolean_ttl["ttlSeconds"] = True
        variants.append(("boolean ttl", boolean_ttl, "TTL"))
        noncanonical_time = copy.deepcopy(receipt)
        noncanonical_time["observedAt"] = receipt["observedAt"].replace("Z", "+00:00")
        variants.append(
            ("noncanonical time", noncanonical_time, "observation timestamp")
        )
        for name, payload, failure in variants:
            with self.subTest(name=name):
                with self.assertRaisesRegex(GAP.ExactIdentityError, failure):
                    GAP.verify_exact_identity_receipt(
                        payload,
                        **self.identity_arguments(),
                    )

    def test_receipt_io_is_external_canonical_and_duplicate_safe(self) -> None:
        receipt = GAP.build_exact_identity_receipt(**self.identity_arguments())
        output = self.temporary_path / "artifacts" / "receipt.json"
        GAP.write_exact_identity_receipt(str(output), receipt, self.repo)
        self.assertEqual(
            receipt, GAP.read_exact_identity_receipt(str(output), self.repo)
        )
        self.assertEqual(
            GAP._identity_canonical_json(receipt) + b"\n",
            output.read_bytes(),
        )
        with self.assertRaisesRegex(GAP.ExactIdentityError, "outside"):
            GAP.write_exact_identity_receipt(
                str(self.repo / "receipt.json"),
                receipt,
                self.repo,
            )
        with self.assertRaisesRegex(GAP.ExactIdentityError, "outside"):
            GAP.read_exact_identity_receipt(
                str(self.repo / GAP.QUALIFICATION_MANIFEST_PATH),
                self.repo,
            )
        duplicate = self.temporary_path / "duplicate.json"
        duplicate.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "duplicate JSON key"):
            GAP.read_exact_identity_receipt(str(duplicate), self.repo)
        nonfinite = self.temporary_path / "nonfinite.json"
        nonfinite.write_text('{"ttlSeconds":NaN}\n', encoding="utf-8")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "non-finite"):
            GAP.read_exact_identity_receipt(str(nonfinite), self.repo)

    def test_canonical_document_inventory_is_closed_and_regular(self) -> None:
        self.write_document_system(
            [GAP.DOCUMENT_SYSTEM_PATH, "docs/spec.md", "docs/spec.md"]
        )
        duplicate = self.commit("duplicate document")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "duplicate"):
            GAP.identity_document_set_digest(self.repo, duplicate)

        self.write_document_system([GAP.DOCUMENT_SYSTEM_PATH, "../outside"])
        unsafe = self.commit("unsafe document")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "unsafe"):
            GAP.identity_document_set_digest(self.repo, unsafe)

        link = self.repo / "docs/link.md"
        link.symlink_to("spec.md")
        self.write_document_system([GAP.DOCUMENT_SYSTEM_PATH, "docs/link.md"])
        symlink = self.commit("symlink document")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "regular file"):
            GAP.identity_document_set_digest(self.repo, symlink)

        link.unlink()
        self.write_document_system(["docs/spec.md"])
        missing_owner = self.commit("missing document owner")
        with self.assertRaisesRegex(GAP.ExactIdentityError, "include itself"):
            GAP.identity_document_set_digest(self.repo, missing_owner)

    def test_static_manifests_cannot_embed_dynamic_tuple(self) -> None:
        qualification_root = REPOSITORY_ROOT / "qualification" / "gap-closure"
        self.assertFalse((qualification_root / "EXACT_HEAD_REQUEST.json").exists())
        self.assertFalse(
            (qualification_root / "REGISTRY_EXACT_HEAD_REQUEST.json").exists()
        )
        manifest = json.loads(GAP.QUALIFICATION_MANIFEST.read_text(encoding="utf-8"))
        audit = json.loads(GAP.QUALIFICATION_PLAN_AUDIT.read_text(encoding="utf-8"))
        self.assertEqual([], GAP.validate_static_candidate_manifest(manifest))
        self.assertEqual([], GAP.static_identity_leaks(audit))
        self.assertEqual(
            GAP.STATIC_CANDIDATE_IDENTITY,
            audit["candidateIdentity"],
        )
        for path in sorted(qualification_root.glob("*.json")):
            with self.subTest(static_document=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual([], GAP.static_identity_leaks(value))
        hostile = copy.deepcopy(manifest)
        hostile["base_commit"] = self.base
        failures = GAP.validate_static_candidate_manifest(hostile)
        self.assertTrue(any("dynamic candidate identity" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
