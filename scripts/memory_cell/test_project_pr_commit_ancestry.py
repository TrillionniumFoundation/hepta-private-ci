"""Registered-Git-history fixtures test trust boundaries, not semantic QA."""

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from project_pr_commit_ancestry import (
    assess,
    check_case,
    read_receipt,
    run,
    unique_pairs,
)
from project_pr_source_materialize import canonical, digest

CUT = "2026-10-12T08:00:00Z"


def corpus():
    a, b, c, d = (x * 40 for x in "abcd")
    case = dict(
        repo="rust-lang/rust",
        pull_number=1,
        head_sha=a,
        tree_sha=d,
        parents=[b],
        commits=[
            dict(sha=b, committed_at=CUT),
            dict(sha=a, committed_at=CUT),
        ],
    )
    observed = {
        b: dict(
            sha=b,
            tree_sha=d,
            parents=[],
            authored_at=CUT,
            committed_at=CUT,
        ),
        a: dict(
            sha=a,
            tree_sha=d,
            parents=[b],
            authored_at=CUT,
            committed_at=CUT,
        ),
    }
    return case, observed, c


class RegisteredAncestryTests(unittest.TestCase):
    def test_direct_registered_ancestry_is_a_partial_proof_only(self):
        case, observed, _ = corpus()
        report = check_case(case, observed)
        self.assertEqual(report["registered_reachable"], 2)
        self.assertTrue(report["all_registered_commits_reachable"])
        self.assertFalse(report["full_pull_request_ancestry_certified"])
        self.assertFalse(report["historical_patch_semantics_certified"])

    def test_declared_commit_without_registered_path_remains_unproven(self):
        case, observed, c = corpus()
        observed[case["head_sha"]]["parents"] = [c]
        case["parents"] = [c]
        report = check_case(case, observed)
        self.assertEqual(
            report["registered_ancestry_unproven"], [case["commits"][0]["sha"]]
        )
        self.assertFalse(report["all_registered_commits_reachable"])

    def test_two_parent_merge_has_no_implicit_unique_first_parent_claim(self):
        case, observed, c = corpus()
        observed[c] = dict(
            sha=c,
            tree_sha="d" * 40,
            parents=[],
            authored_at=CUT,
            committed_at=CUT,
        )
        case["commits"].insert(1, dict(sha=c, committed_at=CUT))
        observed[case["head_sha"]]["parents"] = [case["commits"][0]["sha"], c]
        case["parents"] = list(observed[case["head_sha"]]["parents"])
        report = check_case(case, observed)
        self.assertEqual(report["registered_reachable"], 3)
        self.assertEqual(report["registered_merge_commits"], 1)

    def test_head_tree_parents_and_chronology_are_strict(self):
        for change in ("tree_sha", "parents", "late", "author_late"):
            case, observed, c = corpus()
            if change == "tree_sha":
                observed[case["head_sha"]]["tree_sha"] = c
            elif change == "parents":
                observed[case["head_sha"]]["parents"] = [c]
            elif change == "late":
                observed[case["head_sha"]]["committed_at"] = (
                    "2026-10-13T00:00:00Z"
                )
            else:
                observed[case["head_sha"]]["authored_at"] = (
                    "2026-10-13T00:00:00Z"
                )
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_case(case, observed)

    def test_mutated_or_missing_git_objects_fail_closed(self):
        for change in ("missing", "duplicate_parent", "wrong_commit", "self_parent"):
            case, observed, _ = corpus()
            oid = case["head_sha"]
            if change == "missing":
                observed.pop(oid)
            elif change == "duplicate_parent":
                observed[oid]["parents"] = [case["parents"][0]] * 2
            elif change == "wrong_commit":
                observed[oid]["sha"] = "0" * 40
            else:
                observed[oid]["parents"] = [oid]
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_case(case, observed)

    def test_aggregate_never_issues_semantic_or_production_authority(self):
        case, observed, _ = corpus()
        manifest = dict(cases=[case])
        result = assess(manifest, [observed])
        self.assertEqual(result["registered_commit_refs"], 2)
        self.assertIsNone(result["citation_precision"])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["independent_semantic_review"])

    def test_offline_receipt_rejects_forged_authority_and_extra_files(self):
        case, observed, _ = corpus()
        manifest = dict(cases=[case])
        sha = "9" * 64
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "ancestry"
            output.mkdir()
            inventory = dict(
                schema="hepta.memorycell.project-registered-ancestry.v1",
                original_source_sha256=sha,
                original_ready_sha256="8" * 64,
                observed=[observed],
                analysis=assess(manifest, [observed]),
                remote_git_object_requests=2,
                complete_original_git_commit_objects=True,
            )
            receipt = output / "inventory.json"
            receipt.write_bytes(canonical(inventory) + b"\n")
            ready = dict(
                schema="hepta.memorycell.project-registered-ancestry-ready.v1",
                inventory_sha256=digest(receipt.read_bytes()),
                original_source_sha256=sha,
                research_only=True,
                independent_semantic_review=False,
                production_accepted=False,
            )
            (output / "READY.json").write_bytes(canonical(ready) + b"\n")
            with (
                patch("project_pr_commit_ancestry.read_pinned", return_value=manifest),
                patch(
                    "project_pr_commit_ancestry.reopen_materialized",
                    return_value={"original_ready_sha256": "8" * 64},
                ),
            ):
                self.assertEqual(
                    run(root, root, output, sha=sha, offline=True),
                    inventory["analysis"],
                )
                inventory["independent_review_certified"] = True
                receipt.write_bytes(canonical(inventory) + b"\n")
                ready["inventory_sha256"] = digest(receipt.read_bytes())
                (output / "READY.json").write_bytes(canonical(ready) + b"\n")
                with self.assertRaises(ValueError):
                    run(root, root, output, sha=sha, offline=True)
                inventory.pop("independent_review_certified")
                receipt.write_bytes(canonical(inventory) + b"\n")
                ready["inventory_sha256"] = digest(receipt.read_bytes())
                (output / "READY.json").write_bytes(canonical(ready) + b"\n")
                (output / "INCOMPLETE.json").write_text("{}")
                with self.assertRaises(ValueError):
                    run(root, root, output, sha=sha, offline=True)

    def test_canonical_record_duplicate_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            unique_pairs([("a", 1), ("a", 2)])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "inventory.json"
            p.write_text('{"a":1,"a":2}\n')
            with self.assertRaises(ValueError):
                read_receipt(p)
            p.unlink()
            p.symlink_to(Path(td) / "missing.json")
            with self.assertRaises(ValueError):
                read_receipt(p)


if __name__ == "__main__":
    unittest.main()
