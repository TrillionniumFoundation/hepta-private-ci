"""Unit tests for the exact-head independent platform.types review gate."""

from __future__ import annotations

import unittest

from platform_types_independent_review import evaluate_review_gate

HEAD = "1" * 40
OLD = "2" * 40


def pull(author: str = "pr-author", head: str = HEAD):
    return {"user": {"login": author}, "head": {"sha": head}}


def commit(author: str = "implementer", committer: str = "implementer"):
    return {
        "author": {"login": author},
        "committer": {"login": committer},
    }


def review(
    review_id: int,
    reviewer: str,
    *,
    state: str = "APPROVED",
    commit_id: str = HEAD,
    association: str = "MEMBER",
    submitted_at: str | None = None,
):
    return {
        "id": review_id,
        "user": {"login": reviewer},
        "state": state,
        "commit_id": commit_id,
        "author_association": association,
        "submitted_at": submitted_at or f"2026-09-27T00:00:{review_id:02d}Z",
    }


class IndependentReviewTests(unittest.TestCase):
    def evaluate(self, reviews, commits=None, author="pr-author"):
        return evaluate_review_gate(
            repository="example/repository",
            pr_number=1001,
            expected_head=HEAD,
            pull_request=pull(author),
            reviews=reviews,
            commits=commits or [commit()],
        )

    def test_independent_member_approval_on_current_head_passes(self):
        result = self.evaluate([review(1, "independent-reviewer")])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            [row["reviewer"] for row in result["qualifyingApprovals"]],
            ["independent-reviewer"],
        )

    def test_pr_author_and_candidate_commit_actor_cannot_approve(self):
        result = self.evaluate([review(1, "pr-author"), review(2, "implementer")])
        self.assertEqual(result["status"], "failed")
        reasons = {
            row["reviewer"]: row["rejectionReason"]
            for row in result["rejectedDecisiveReviews"]
        }
        self.assertEqual(reasons["pr-author"], "pull_request_author")
        self.assertIn(reasons["implementer"], {"commit_author", "commit_committer"})

    def test_approval_must_bind_exact_current_head(self):
        result = self.evaluate([review(1, "independent-reviewer", commit_id=OLD)])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["rejectedDecisiveReviews"][0]["rejectionReason"],
            "approval_not_bound_to_current_head",
        )

    def test_latest_decisive_state_controls_but_comments_do_not_clear_approval(self):
        rejected = self.evaluate(
            [
                review(1, "independent-reviewer", state="APPROVED"),
                review(2, "independent-reviewer", state="CHANGES_REQUESTED"),
            ]
        )
        self.assertEqual(rejected["status"], "failed")
        self.assertEqual(
            rejected["rejectedDecisiveReviews"][0]["rejectionReason"],
            "latest_decisive_state_changes_requested",
        )

        passed = self.evaluate(
            [
                review(1, "independent-reviewer", state="APPROVED"),
                review(2, "independent-reviewer", state="COMMENTED"),
            ]
        )
        self.assertEqual(passed["status"], "passed")

    def test_public_outsider_and_bot_reviews_do_not_satisfy_formal_gate(self):
        result = self.evaluate(
            [
                review(1, "outside-user", association="CONTRIBUTOR"),
                review(2, "review-bot[bot]", association="MEMBER"),
            ]
        )
        self.assertEqual(result["status"], "failed")
        reasons = {
            row["reviewer"]: row["rejectionReason"]
            for row in result["rejectedDecisiveReviews"]
        }
        self.assertEqual(
            reasons["outside-user"],
            "reviewer_not_repository_member_or_collaborator",
        )
        self.assertEqual(reasons["review-bot[bot]"], "bot_reviewer")


if __name__ == "__main__":
    unittest.main()
