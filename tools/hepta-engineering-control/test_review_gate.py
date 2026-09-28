import unittest

from control_engineering_v2.review_gate import require_independent_approved_review


class ReviewGateTests(unittest.TestCase):
    def review(self, review_id, state="APPROVED", commit="a" * 40, login="reviewer", user_id=2):
        return {
            "id": review_id,
            "user": {"id": user_id, "login": login},
            "state": state,
            "commit_id": commit,
            "submitted_at": f"2026-09-28T00:00:{review_id:02d}Z",
        }

    def test_current_head_non_author_approval_passes_without_semantic_acceptance(self):
        decision = require_independent_approved_review(
            [self.review(1)],
            expected_head_sha="a" * 40,
            author_user_id=1,
            author_login="author",
            allowed_reviewers=("reviewer",),
        )
        self.assertTrue(decision["githubApprovalObserved"])
        self.assertFalse(decision["independentSemanticAcceptance"])
        self.assertFalse(decision["mergeAuthority"])

    def test_latest_review_author_bot_outdated_and_unapproved_are_rejected(self):
        cases = (
            [self.review(1, login="author", user_id=1)],
            [self.review(1, login="ci[bot]", user_id=3)],
            [self.review(1, commit="b" * 40)],
            [self.review(1, state="CHANGES_REQUESTED")],
            [self.review(1), self.review(2, state="CHANGES_REQUESTED")],
        )
        for reviews in cases:
            with self.subTest(reviews=reviews), self.assertRaisesRegex(
                ValueError, "independent_current_head_approval_missing"
            ):
                require_independent_approved_review(
                    reviews,
                    expected_head_sha="a" * 40,
                    author_user_id=1,
                    author_login="author",
                )


if __name__ == "__main__":
    unittest.main()
