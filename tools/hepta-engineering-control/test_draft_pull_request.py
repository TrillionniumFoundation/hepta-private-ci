from __future__ import annotations

import unittest

from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.pull_request import (
    DraftPullRequestRequest,
    open_draft_pull_request,
)


SHA = "1" * 40


class FakeApi:
    def __init__(self, *, files=None, existing=None):
        self.files = files or [{"filename": "codex-rs/hepta-feature/src/lib.rs"}]
        self.existing = [] if existing is None else existing
        self.calls = []

    def __call__(self, method, path, payload):
        self.calls.append((method, path, payload))
        if "/git/ref/heads/" in path:
            return {"object": {"type": "commit", "sha": SHA}}
        if "/compare/" in path:
            return {
                "status": "ahead",
                "ahead_by": 1,
                "total_commits": 1,
                "files": self.files,
            }
        if method == "GET" and "/pulls?" in path:
            return self.existing
        if method == "POST" and path.endswith("/pulls"):
            return {
                "number": 42,
                "html_url": "https://github.example/pull/42",
            }
        raise AssertionError((method, path, payload))


def request(**overrides):
    values = {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "base": "main",
        "head": "self-iteration/candidate-42",
        "expected_head_sha": SHA,
        "title": "candidate: bounded improvement",
        "body": "Generated candidate. Independent review required.",
        "allowed_paths": ("codex-rs/hepta-feature",),
    }
    values.update(overrides)
    return DraftPullRequestRequest(**values)


class DraftPullRequestTests(unittest.TestCase):
    def test_creates_only_a_draft_review_object(self):
        api = FakeApi()
        receipt = open_draft_pull_request(request(), api)
        self.assertTrue(receipt.created)
        self.assertTrue(receipt.draft)
        self.assertFalse(receipt.merge_authority)
        self.assertFalse(receipt.activation_authority)
        self.assertFalse(receipt.promotion_authority)
        self.assertFalse(receipt.release_authority)
        posts = [call for call in api.calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        method, path, payload = posts[0]
        self.assertEqual(method, "POST")
        self.assertTrue(path.endswith("/pulls"))
        self.assertIs(payload["draft"], True)
        self.assertIs(payload["maintainer_can_modify"], False)
        self.assertNotIn("merge", path)
        self.assertNotIn("merge", payload)

    def test_existing_exact_draft_is_idempotent(self):
        api = FakeApi(
            existing=[
                {
                    "number": 7,
                    "html_url": "https://github.example/pull/7",
                    "draft": True,
                    "head": {"sha": SHA},
                }
            ]
        )
        receipt = open_draft_pull_request(request(), api)
        self.assertFalse(receipt.created)
        self.assertEqual(receipt.number, 7)
        self.assertFalse(any(method == "POST" for method, _, _ in api.calls))

    def test_protected_workflow_envelope_is_rejected_before_network(self):
        api = FakeApi(files=[{"filename": ".github/workflows/self-merge.yml"}])
        with self.assertRaisesRegex(EngineeringError, "protected_path_requested"):
            open_draft_pull_request(
                request(allowed_paths=(".github/workflows",)), api
            )
        self.assertEqual(api.calls, [])

    def test_out_of_envelope_change_is_rejected(self):
        api = FakeApi(files=[{"filename": "codex-rs/hepta-other/src/lib.rs"}])
        with self.assertRaisesRegex(EngineeringError, "candidate_path_outside_envelope"):
            open_draft_pull_request(request(), api)
        self.assertFalse(any(method == "POST" for method, _, _ in api.calls))

    def test_non_self_iteration_branch_is_rejected_before_network(self):
        api = FakeApi()
        with self.assertRaisesRegex(EngineeringError, "invalid_self_iteration_head"):
            open_draft_pull_request(request(head="feature/unbounded"), api)
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
