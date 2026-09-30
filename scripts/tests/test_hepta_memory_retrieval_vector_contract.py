"""Synthetic tests for the source-only vector publication contract verifier."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import hepta_memory_retrieval_vector_contract as vector_contract


def write_text(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(root: Path, relative: str, value) -> None:
    write_text(root, relative, json.dumps(value, indent=2) + "\n")


def composition_fixture():
    return {
        "schema": "hepta.memory-retrieval.product-composition.v1",
        "module": "memory.retrieval",
        "sourceIdentityPolicy": "runtime-exact-head-and-tree",
        "activationMode": "compatibility",
        "productionEnabled": False,
        "encoder": {
            "state": "not-established",
            "modelDigest": None,
            "dimensions": None,
            "normalization": None,
        },
        "index": {
            "state": "not-product-qualified",
            "schema": "hepta.memory-retrieval.vector-index.v2",
            "version": 2,
            "writerFenceRequired": True,
            "staleWriterRejected": True,
            "checkedPublish": (
                "codex-hepta-memory-retrieval:append_vector_publication_checked_v1"
            ),
            "uncertainCommitPolicy": "reload-exact-current-no-blind-republish",
            "exactReplayIdempotent": True,
            "postCommitReloadRequired": True,
            "publisher": None,
            "durableStore": None,
        },
        "promotionBlockers": list(vector_contract.REQUIRED_BLOCKERS),
    }


class VectorPublicationContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.composition = composition_fixture()
        write_json(
            self.root,
            vector_contract.PRODUCT_COMPOSITION,
            self.composition,
        )
        write_text(
            self.root,
            vector_contract.VECTOR_SOURCE,
            "\n".join(vector_contract.REQUIRED_SOURCE_MARKERS) + "\n",
        )
        write_text(
            self.root,
            vector_contract.VECTOR_TEST,
            "\n".join(vector_contract.REQUIRED_TEST_MARKERS) + "\n",
        )
        write_text(
            self.root,
            vector_contract.VECTOR_GUIDE,
            "\n".join(vector_contract.REQUIRED_GUIDE_MARKERS) + "\n",
        )
        write_text(
            self.root,
            vector_contract.LIB_SOURCE,
            "\n".join(vector_contract.REQUIRED_LIB_MARKERS) + "\n",
        )

    def validate(self):
        return vector_contract.validate(self.root)

    def save_composition(self, composition=None):
        write_json(
            self.root,
            vector_contract.PRODUCT_COMPOSITION,
            composition or self.composition,
        )

    def test_exact_source_only_contract_is_accepted(self):
        result = self.validate()
        self.assertEqual(
            result["checkedPublish"],
            "codex-hepta-memory-retrieval:append_vector_publication_checked_v1",
        )
        self.assertFalse(result["productionImplementation"])
        self.assertFalse(result["productionEncoderEstablished"])
        self.assertFalse(result["durablePublisherEstablished"])
        self.assertFalse(result["durableStoreEstablished"])

    def test_checked_publish_binding_cannot_drift(self):
        composition = deepcopy(self.composition)
        composition["index"]["checkedPublish"] = "unchecked-publish"
        self.save_composition(composition)
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "checkedPublish",
        ):
            self.validate()

    def test_uncertain_commit_policy_cannot_be_weakened(self):
        composition = deepcopy(self.composition)
        composition["index"]["uncertainCommitPolicy"] = "blind-retry"
        self.save_composition(composition)
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "uncertainCommitPolicy",
        ):
            self.validate()

    def test_source_only_contract_cannot_claim_a_publisher(self):
        composition = deepcopy(self.composition)
        composition["index"]["publisher"] = "unqualified-publisher"
        self.save_composition(composition)
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "publisher",
        ):
            self.validate()

    def test_source_only_contract_cannot_enable_production(self):
        composition = deepcopy(self.composition)
        composition["productionEnabled"] = True
        self.save_composition(composition)
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "cannot enable production",
        ):
            self.validate()

    def test_uncertain_outcome_source_marker_is_required(self):
        markers = [
            marker
            for marker in vector_contract.REQUIRED_SOURCE_MARKERS
            if marker != "CommitOutcomeUnknown"
        ]
        write_text(
            self.root,
            vector_contract.VECTOR_SOURCE,
            "\n".join(markers) + "\n",
        )
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "CommitOutcomeUnknown",
        ):
            self.validate()

    def test_failure_injection_test_marker_is_required(self):
        markers = [
            marker
            for marker in vector_contract.REQUIRED_TEST_MARKERS
            if marker
            != "successful_publish_with_failed_confirmation_is_outcome_unknown"
        ]
        write_text(
            self.root,
            vector_contract.VECTOR_TEST,
            "\n".join(markers) + "\n",
        )
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "failed_confirmation",
        ):
            self.validate()

    def test_deployed_backend_disclaimer_is_required(self):
        markers = [
            marker
            for marker in vector_contract.REQUIRED_GUIDE_MARKERS
            if marker != "does **not** establish a deployed durable backend"
        ]
        write_text(
            self.root,
            vector_contract.VECTOR_GUIDE,
            "\n".join(markers) + "\n",
        )
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "deployed durable backend",
        ):
            self.validate()

    def test_duplicate_composition_key_is_rejected(self):
        write_text(
            self.root,
            vector_contract.PRODUCT_COMPOSITION,
            '{"module":"memory.retrieval","module":"other"}\n',
        )
        with self.assertRaisesRegex(
            vector_contract.VectorContractError,
            "duplicate JSON key",
        ):
            self.validate()


if __name__ == "__main__":
    unittest.main()
