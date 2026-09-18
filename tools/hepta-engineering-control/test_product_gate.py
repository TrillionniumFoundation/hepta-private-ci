from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import product_gate


CANONICAL_REGISTRY = """{
  "schema": "hepta.work-package-registry.v4",
  "schemaVersion": 4,
  "documentClass": "canonical_registry",
  "packages": [
    {
      "id": "ECP-1-ENGINEERING-CONTROL-PLANE",
      "module": "control.engineering",
      "state": "source_implemented",
      "authorityDelta": "none",
      "developmentAfter": ["DOC-2-DEFAULT-BRANCH-SELECTION"],
      "activationAfter": ["DOC-2-DEFAULT-BRANCH-SELECTION"],
      "owner": "developer-productivity",
      "deputy": "architecture",
      "sourceMutationAllowed": true,
      "allowedWritePaths": ["tools/hepta-engineering-control/**"]
    }
  ]
}
"""
CANONICAL_PATH = product_gate.CANONICAL_WORK_PACKAGE_PATH.as_posix()
CANONICAL_BLOB = "9" * 40


class ProductGateTests(unittest.TestCase):
    def write_canonical_registry(self, root: Path) -> None:
        target = root / "docs" / "delivery" / "WORK_PACKAGES.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(CANONICAL_REGISTRY, encoding="utf-8")

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

    def product_receipt(self, lane: str) -> dict[str, object]:
        source = "a" * 40
        base = "b" * 40
        merge = "c" * 40
        source_tree = "e" * 40
        merge_tree = "d" * 40
        receipt = {
            "schema": "hepta.control-engineering-product-execution.v2",
            "mode": lane,
            "ciIdentity": {
                "repository": product_gate.EXPECTED_REPOSITORY,
                "repositoryId": product_gate.EXPECTED_REPOSITORY_ID,
                "workflowRef": (
                    product_gate.EXPECTED_REPOSITORY
                    + "/.github/workflows/hepta-consolidated-source.yml@refs/pull/780/merge"
                ),
                "job": product_gate.EXPECTED_JOB,
                "runId": 42,
                "runAttempt": 3,
                "eventName": "pull_request",
                "executionLane": lane,
                "pullRequestNumber": 780,
            },
            "sourceSha": source,
            "sourceTree": source_tree,
            "testedSha": source if lane == "source-head" else merge,
            "testedTree": source_tree if lane == "source-head" else merge_tree,
            "orderedParents": ["f" * 40] if lane == "source-head" else [base, source],
            "canonicalWorkPackage": {
                "path": CANONICAL_PATH,
                "schema": "hepta.work-package-registry.v4",
                "schemaVersion": 4,
                "packageId": product_gate.CANONICAL_ENGINEERING_PACKAGE,
                "blobOid": CANONICAL_BLOB,
                "registryDigest": "1" * 64,
                "packageDigest": "2" * 64,
                "state": "source_implemented",
                "authorityDelta": "none",
                "developmentAfter": ["DOC-2-DEFAULT-BRANCH-SELECTION"],
                "activationAfter": ["DOC-2-DEFAULT-BRANCH-SELECTION"],
            },
            "plan": {
                "assignments": [
                    {"package_id": "control.engineering.repository-product-gate"}
                ],
                "runtime_authority": False,
                "merge_authority": False,
                "release_authority": False,
            },
            "auditAnchor": {"sequence": 1, "eventDigest": "3" * 64},
            "productCallerComposed": True,
            "productTestsUpstreamRequired": True,
            "runtimeAuthority": False,
            "mergeAuthority": False,
            "activationAuthority": False,
            "promotionAuthority": False,
            "releaseAuthority": False,
            "externalEffectAuthority": False,
        }
        receipt["receiptDigest"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return receipt

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
            ("show", f"HEAD:{CANONICAL_PATH}"): CANONICAL_REGISTRY,
            ("rev-parse", f"HEAD:{CANONICAL_PATH}"): CANONICAL_BLOB,
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
                self.write_canonical_registry(Path(temp))
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
        self.assertEqual(
            receipt["canonicalWorkPackage"]["packageId"],
            "ECP-1-ENGINEERING-CONTROL-PLANE",
        )
        self.assertEqual(receipt["canonicalWorkPackage"]["blobOid"], CANONICAL_BLOB)
        self.assertEqual(
            receipt["canonicalWorkPackage"]["developmentAfter"],
            ["DOC-2-DEFAULT-BRANCH-SELECTION"],
        )
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
            ("show", f"HEAD:{CANONICAL_PATH}"): CANONICAL_REGISTRY,
            ("rev-parse", f"HEAD:{CANONICAL_PATH}"): CANONICAL_BLOB,
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
                self.write_canonical_registry(Path(temp))
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

    def test_missing_canonical_work_package_registry_fails_closed(self):
        source = "a" * 40
        source_tree = "e" * 40
        calls = {
            ("rev-parse", "HEAD"): source,
            ("rev-parse", "HEAD^{tree}"): source_tree,
            ("rev-parse", f"{source}^{{tree}}"): source_tree,
            ("show", "-s", "--format=%P", "HEAD"): "f" * 40,
        }
        def missing_registry(_root, *args):
            if args == ("show", f"HEAD:{CANONICAL_PATH}"):
                raise ValueError("git_read_failed")
            return calls[args]

        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=missing_registry,
        ):
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(
                    ValueError, "canonical_work_package_registry_unavailable"
                ):
                    product_gate.build_product_receipt(
                        Path(temp),
                        source_sha=source,
                        base_sha="b" * 40,
                        **self.identity(lane="source-head"),
                    )

    def test_tampered_canonical_engineering_package_fails_closed(self):
        source = "a" * 40
        source_tree = "e" * 40
        calls = {
            ("rev-parse", "HEAD"): source,
            ("rev-parse", "HEAD^{tree}"): source_tree,
            ("rev-parse", f"{source}^{{tree}}"): source_tree,
            ("show", "-s", "--format=%P", "HEAD"): "f" * 40,
            ("show", f"HEAD:{CANONICAL_PATH}"): CANONICAL_REGISTRY.replace(
                '"authorityDelta": "none"', '"authorityDelta": "merge"'
            ),
            ("rev-parse", f"HEAD:{CANONICAL_PATH}"): CANONICAL_BLOB,
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _root, *args: calls[args],
        ):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaisesRegex(
                    ValueError, "canonical_engineering_package_binding"
                ):
                    product_gate.build_product_receipt(
                        root,
                        source_sha=source,
                        base_sha="b" * 40,
                        **self.identity(lane="source-head"),
                    )

    def test_product_receipt_pair_binds_both_exact_lanes(self):
        source = self.product_receipt("source-head")
        merge = self.product_receipt("base-merge")
        pair = product_gate.verify_product_receipt_pair(
            source,
            merge,
            expected_repository=product_gate.EXPECTED_REPOSITORY,
            expected_repository_id=product_gate.EXPECTED_REPOSITORY_ID,
            expected_run_id=42,
            expected_run_attempt=3,
            expected_source_sha="a" * 40,
            expected_base_sha="b" * 40,
            expected_pull_request_number=780,
        )
        self.assertEqual(
            pair["sourceProductReceiptDigest"], source["receiptDigest"]
        )
        self.assertEqual(
            pair["mergeProductReceiptDigest"], merge["receiptDigest"]
        )
        self.assertEqual(
            pair["canonicalWorkPackageBlobOid"], CANONICAL_BLOB
        )
        self.assertFalse(pair["mergeAuthority"])
        self.assertEqual(
            pair["readinessReceiptSetDigest"],
            hashlib.sha256(
                json.dumps(
                    {
                        "baseMerge": merge["receiptDigest"],
                        "sourceHead": source["receiptDigest"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_product_receipt_pair_rejects_tamper_and_lane_drift(self):
        source = self.product_receipt("source-head")
        merge = self.product_receipt("base-merge")
        source["testedTree"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "product_receipt_digest_mismatch"):
            product_gate.verify_product_receipt_pair(
                source,
                merge,
                expected_repository=product_gate.EXPECTED_REPOSITORY,
                expected_repository_id=product_gate.EXPECTED_REPOSITORY_ID,
                expected_run_id=42,
                expected_run_attempt=3,
                expected_source_sha="a" * 40,
                expected_base_sha="b" * 40,
                expected_pull_request_number=780,
            )

        source = self.product_receipt("source-head")
        merge = self.product_receipt("base-merge")
        merge["canonicalWorkPackage"]["blobOid"] = "8" * 40
        merge["receiptDigest"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in merge.items() if key != "receiptDigest"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "product_receipt_pair_canonical_drift"):
            product_gate.verify_product_receipt_pair(
                source,
                merge,
                expected_repository=product_gate.EXPECTED_REPOSITORY,
                expected_repository_id=product_gate.EXPECTED_REPOSITORY_ID,
                expected_run_id=42,
                expected_run_attempt=3,
                expected_source_sha="a" * 40,
                expected_base_sha="b" * 40,
                expected_pull_request_number=780,
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
