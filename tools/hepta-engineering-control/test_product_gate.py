from pathlib import Path
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import product_gate


class ProductGateTests(unittest.TestCase):
    def identity(
        self,
        *,
        event_name="pull_request",
        lane="base-merge",
        pull_request_number=780,
    ):
        return {
            "repository_full_name": product_gate.EXPECTED_REPOSITORY,
            "repository_id": product_gate.EXPECTED_REPOSITORY_ID,
            "workflow_ref": (
                product_gate.EXPECTED_REPOSITORY
                + "/.github/workflows/hepta-consolidated-source.yml@refs/pull/780/merge"
            ),
            "job_name": product_gate.EXPECTED_JOB,
            "run_id": 1,
            "run_attempt": 1,
            "event_name": event_name,
            "lane": lane,
            "pull_request_number": pull_request_number,
        }

    def test_pull_request_product_caller_composes_v2_orchestrator(self):
        source = "a" * 40
        base = "b" * 40
        merge = "c" * 40
        merge_tree = "d" * 40
        source_tree = "e" * 40
        calls = {
            ("rev-parse", "HEAD"): merge,
            ("rev-parse", "HEAD^{tree}"): merge_tree,
            ("rev-parse", f"{source}^{{tree}}"): source_tree,
            ("show", "-s", "--format=%P", "HEAD"): f"{base} {source}",
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _root, *args: calls[args],
        ), mock.patch(
            "control_engineering_v2.orchestration._git",
            side_effect=lambda _root, *args: {
                ("rev-parse", "HEAD"): merge,
                ("rev-parse", "HEAD^{tree}"): merge_tree,
                (
                    "status",
                    "--porcelain=v2",
                    "--untracked-files=all",
                ): "",
                ("config", "--get", "remote.origin.url"): (
                    "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
                ),
            }[args],
        ):
            with tempfile.TemporaryDirectory() as temp:
                receipt = product_gate.build_product_receipt(
                    Path(temp),
                    source_sha=source,
                    base_sha=base,
                    **self.identity(),
                )
        self.assertTrue(receipt["productCallerComposed"])
        self.assertEqual(
            receipt["plan"]["assignments"][0]["package_id"],
            "control.engineering.repository-product-gate",
        )
        self.assertEqual(receipt["orderedParents"], [base, source])
        self.assertFalse(receipt["mergeAuthority"])
        self.assertFalse(receipt["releaseAuthority"])

    def test_pull_request_source_head_product_caller_composes_same_v2_path(self):
        source = "a" * 40
        source_tree = "e" * 40
        calls = {
            ("rev-parse", "HEAD"): source,
            ("rev-parse", "HEAD^{tree}"): source_tree,
            ("rev-parse", f"{source}^{{tree}}"): source_tree,
            ("show", "-s", "--format=%P", "HEAD"): "f" * 40,
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _root, *args: calls[args],
        ), mock.patch(
            "control_engineering_v2.orchestration._git",
            side_effect=lambda _root, *args: {
                ("rev-parse", "HEAD"): source,
                ("rev-parse", "HEAD^{tree}"): source_tree,
                (
                    "status",
                    "--porcelain=v2",
                    "--untracked-files=all",
                ): "",
                ("config", "--get", "remote.origin.url"): (
                    "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
                ),
            }[args],
        ):
            with tempfile.TemporaryDirectory() as temp:
                receipt = product_gate.build_product_receipt(
                    Path(temp),
                    source_sha=source,
                    base_sha="b" * 40,
                    **self.identity(lane="source-head"),
                )
        self.assertEqual(receipt["mode"], "source-head")
        self.assertEqual(receipt["testedSha"], source)
        self.assertEqual(receipt["ciIdentity"]["executionLane"], "source-head")
        self.assertTrue(receipt["productCallerComposed"])

    def test_source_push_requires_exact_head(self):
        source = "a" * 40
        calls = {
            ("rev-parse", "HEAD"): "f" * 40,
            ("rev-parse", "HEAD^{tree}"): "d" * 40,
            ("rev-parse", f"{source}^{{tree}}"): "e" * 40,
            ("show", "-s", "--format=%P", "HEAD"): "",
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _root, *args: calls[args],
        ):
            with self.assertRaisesRegex(ValueError, "source_head_mismatch"):
                product_gate.build_product_receipt(
                    ".",
                    source_sha=source,
                    base_sha=None,
                    **self.identity(
                        event_name="push",
                        lane="source-head",
                        pull_request_number=0,
                    ),
                )

    def test_base_merge_lane_is_invalid_on_push(self):
        with self.assertRaisesRegex(ValueError, "execution_lane_event_mismatch"):
            product_gate.build_product_receipt(
                ".",
                source_sha="a" * 40,
                base_sha="b" * 40,
                **self.identity(
                    event_name="push",
                    lane="base-merge",
                    pull_request_number=0,
                ),
            )

    def test_ci_identity_mismatch_fails_closed(self):
        identity = self.identity()
        identity["repository_id"] = 0
        with self.assertRaisesRegex(ValueError, "repository_id_mismatch"):
            product_gate.build_product_receipt(
                ".",
                source_sha="a" * 40,
                base_sha="b" * 40,
                **identity,
            )


if __name__ == "__main__":
    unittest.main()
