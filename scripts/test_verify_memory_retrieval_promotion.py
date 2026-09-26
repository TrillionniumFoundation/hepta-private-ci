import copy
import unittest

from verify_memory_retrieval_promotion import check_promotion

HEAD = "a" * 40


def envelope():
    return {"pull_request": {"draft": False, "head": {"sha": HEAD}, "user": {"login": "author"}},
            "permissions": {"reviewer": "write"},
            "reviews": [{"id": 1, "state": "APPROVED", "commit_id": HEAD,
                         "user": {"login": "reviewer", "type": "User"}}]}


class PromotionTests(unittest.TestCase):
    def verify(self, value):
        return check_promotion({"claimBoundary": {"productionImplementation": True}}, value, HEAD)

    def test_nonpromoting_candidate_needs_no_fabricated_review(self):
        self.assertEqual(check_promotion({"productionImplementation": False}, {}, HEAD), [])

    def test_current_independent_authorized_review(self):
        self.assertEqual(self.verify(envelope()), ["reviewer"])

    def test_draft_cannot_promote(self):
        value = envelope(); value["pull_request"]["draft"] = True
        with self.assertRaises(ValueError): self.verify(value)

    def test_stale_review_cannot_promote(self):
        value = envelope(); value["reviews"][0]["commit_id"] = "b" * 40
        with self.assertRaises(ValueError): self.verify(value)

    def test_wrong_head_cannot_promote(self):
        value = envelope(); value["pull_request"]["head"]["sha"] = "b" * 40
        with self.assertRaises(ValueError): self.verify(value)

    def test_self_review_cannot_promote(self):
        value = envelope(); value["pull_request"]["user"]["login"] = "reviewer"
        with self.assertRaises(ValueError): self.verify(value)

    def test_read_only_reviewer_cannot_promote(self):
        value = envelope(); value["permissions"]["reviewer"] = "read"
        with self.assertRaises(ValueError): self.verify(value)

    def test_bot_is_not_independent_human_acceptance(self):
        value = envelope(); value["reviews"][0]["user"]["type"] = "Bot"
        with self.assertRaises(ValueError): self.verify(value)

    def test_comment_does_not_clear_approval(self):
        value = envelope(); comment = copy.deepcopy(value["reviews"][0])
        comment.update(id=2, state="COMMENTED"); value["reviews"].append(comment)
        self.assertEqual(self.verify(value), ["reviewer"])

    def test_dismissal_and_changes_requested_clear_approval(self):
        for state in ("DISMISSED", "CHANGES_REQUESTED"):
            value = envelope(); decision = copy.deepcopy(value["reviews"][0])
            decision.update(id=2, state=state); value["reviews"].append(decision)
            with self.subTest(state=state), self.assertRaises(ValueError): self.verify(value)

    def test_claim_type_confusion_fails_closed(self):
        for flag in ("false", 0, 1, None):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                check_promotion({"productionImplementation": flag}, envelope(), HEAD)

    def test_duplicate_review_ids_rejected(self):
        value = envelope(); value["reviews"].append(copy.deepcopy(value["reviews"][0]))
        with self.assertRaises(ValueError): self.verify(value)


if __name__ == "__main__": unittest.main()
