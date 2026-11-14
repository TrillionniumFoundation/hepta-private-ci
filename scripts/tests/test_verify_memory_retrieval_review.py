from __future__ import annotations

import unittest

from scripts.verify_memory_retrieval_review import current_independent_approvals
from scripts.verify_memory_retrieval_review import promoted_claims
from scripts.verify_memory_retrieval_review import verify


class MemoryRetrievalReviewGateTests(unittest.TestCase):
    def test_no_promotion_needs_no_review(self) -> None:
        base = {"productionImplementation": False, "claimBoundary": {"release": False}}
        self.assertEqual(promoted_claims(base, base), [])
        result = verify(base, base, {}, [], head_sha="a" * 40)
        self.assertEqual(result["decision"], "not_required")

    def test_direct_push_promotion_is_rejected(self) -> None:
        base = {"productionImplementation": False}
        head = {"productionImplementation": True}
        with self.assertRaisesRegex(ValueError, "pull request"):
            verify(base, head, {}, [], head_sha="b" * 40)

    def test_draft_and_stale_approval_are_rejected(self) -> None:
        sha = "c" * 40
        base = {"claimBoundary": {"activation": False}}
        head = {"claimBoundary": {"activation": True}}
        draft = {"pull_request": {"draft": True, "user": {"login": "author"}, "head": {"sha": sha}}}
        with self.assertRaisesRegex(ValueError, "draft"):
            verify(base, head, draft, [], head_sha=sha)
        event = {"pull_request": {"draft": False, "user": {"login": "author"}, "head": {"sha": sha}}}
        stale = [{"id": 1, "state": "APPROVED", "commit_id": "d" * 40, "author_association": "MEMBER", "user": {"login": "reviewer", "type": "User"}}]
        with self.assertRaisesRegex(ValueError, "current-head"):
            verify(base, head, event, stale, head_sha=sha)

    def test_latest_review_and_independence_are_enforced(self) -> None:
        sha = "e" * 40
        reviews = [
            {"id": 1, "submitted_at": "2026-01-01T00:00:00Z", "state": "APPROVED", "commit_id": sha, "author_association": "MEMBER", "user": {"login": "reviewer", "type": "User"}},
            {"id": 2, "submitted_at": "2026-01-02T00:00:00Z", "state": "CHANGES_REQUESTED", "commit_id": sha, "author_association": "MEMBER", "user": {"login": "reviewer", "type": "User"}},
            {"id": 3, "submitted_at": "2026-01-03T00:00:00Z", "state": "APPROVED", "commit_id": sha, "author_association": "OWNER", "user": {"login": "independent", "type": "User"}},
            {"id": 4, "submitted_at": "2026-01-03T00:00:00Z", "state": "APPROVED", "commit_id": sha, "author_association": "OWNER", "user": {"login": "author", "type": "User"}},
        ]
        self.assertEqual(current_independent_approvals(reviews, author_login="author", head_sha=sha), ["independent"])
        base = {"claimBoundary": {"release": False}}
        head = {"claimBoundary": {"release": True}}
        event = {"pull_request": {"draft": False, "user": {"login": "author"}, "head": {"sha": sha}}}
        result = verify(base, head, event, reviews, head_sha=sha)
        self.assertEqual(result["decision"], "approved")
        self.assertEqual(result["approvedBy"], ["independent"])


if __name__ == "__main__":
    unittest.main()
