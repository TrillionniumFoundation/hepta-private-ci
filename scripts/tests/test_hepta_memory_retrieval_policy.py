from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import hepta_memory_retrieval_policy as policy


CRITICAL_SOURCE_OBJECTS = {
    "codex-rs/hepta-agentd/src/cognitive_retrieval_context.rs",
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-agentd/src/retrieval_delivery_append.rs",
    "codex-rs/hepta-agentd/src/retrieval_executor.rs",
    "codex-rs/hepta-agentd/src/retrieval_product_mode.rs",
    "codex-rs/hepta-memory-retrieval/Cargo.toml",
    "codex-rs/hepta-memory-retrieval/src/lib.rs",
    "codex-rs/hepta-memory-retrieval/src/lifecycle.rs",
    "codex-rs/hepta-memory-retrieval/src/lifecycle_append.rs",
    "codex-rs/hepta-memory-retrieval/src/semantics.rs",
    "codex-rs/hepta-memory-retrieval/src/vector_publication.rs",
    "codex-rs/hepta-memory-retrieval/src/vector_publication_append.rs",
    "codex-rs/hepta-memory-retrieval/src/work.rs",
    "codex-rs/hepta-memory-retrieval/tests/lifecycle_append_api.rs",
    "codex-rs/hepta-memory-retrieval/tests/vector_publication_append_api.rs",
    "docs/modules/memory.retrieval/VECTOR_OWNER.md",
    "qualification/memory-retrieval/product-composition.json",
    "qualification/memory-retrieval/qualification-policy.json",
    "qualification/memory-retrieval/recovery-matrix.json",
    "scripts/hepta_memory_retrieval_policy.py",
    "scripts/hepta_memory_retrieval_qualification.py",
    "scripts/hepta_memory_retrieval_status.py",
    "scripts/hepta_memory_retrieval_vector_contract.py",
    "scripts/tests/test_hepta_memory_retrieval_vector_contract.py",
}


class QualificationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.frozen = "a" * 40
        self.policy = deepcopy(policy.POLICY)
        self.write_map()
        self.write_policy()

    def write_map(self):
        path = self.root / policy.IMPLEMENTATION_MAP_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "module": "memory.retrieval",
                    "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
                    "sourceBase": {
                        "commit": self.frozen,
                        "tree": "b" * 40,
                    },
                    "observedAtHead": {
                        "commit": self.frozen,
                        "tree": "b" * 40,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_policy(self):
        path = self.root / policy.POLICY_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.policy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def satisfy_one_gate(self, subject=None):
        gate = self.policy["externalGates"][0]
        gate["state"] = "satisfied_external"
        gate["evidence"] = {
            "subjectSha": subject or self.frozen,
            "sha256": "c" * 64,
            "uri": "worm://memory-retrieval/evidence.json",
            "signer": "independent-acceptance-key-v1",
            "signature": "detached-signature",
            "observedAt": "2026-09-30T00:00:00Z",
        }
        self.write_policy()

    def test_matching_external_subject_is_accepted(self):
        self.satisfy_one_gate()
        loaded = policy.load_policy(self.root)
        self.assertEqual(
            loaded["externalGates"][0]["evidence"]["subjectSha"],
            self.frozen,
        )

    def test_stale_external_subject_is_rejected(self):
        self.satisfy_one_gate("d" * 40)
        with self.assertRaisesRegex(
            policy.PolicyError,
            "not bound to the frozen source",
        ):
            policy.load_policy(self.root)

    def test_satisfied_gate_requires_exact_observation_map(self):
        self.satisfy_one_gate()
        (self.root / policy.IMPLEMENTATION_MAP_RELATIVE_PATH).unlink()
        with self.assertRaisesRegex(
            policy.PolicyError,
            "require an implementation map",
        ):
            policy.load_policy(self.root)

    def test_mandatory_repository_check_cannot_be_removed(self):
        self.policy["requiredChecks"] = [
            row
            for row in self.policy["requiredChecks"]
            if row["name"] != "CI required"
        ]
        self.write_policy()
        with self.assertRaisesRegex(
            policy.PolicyError,
            "mandatory required check",
        ):
            policy.load_policy(self.root)

    def test_mandatory_external_gate_cannot_be_removed(self):
        removed = self.policy["externalGates"].pop()
        self.write_policy()
        with self.assertRaisesRegex(
            policy.PolicyError,
            removed["name"],
        ):
            policy.load_policy(self.root)

    def test_missing_gate_cannot_carry_evidence(self):
        self.policy["externalGates"][0]["evidence"] = {
            "subjectSha": self.frozen,
        }
        self.write_policy()
        with self.assertRaisesRegex(
            policy.PolicyError,
            "must not carry evidence",
        ):
            policy.load_policy(self.root)

    def test_critical_source_objects_are_explicitly_bound(self):
        self.assertTrue(
            CRITICAL_SOURCE_OBJECTS.issubset(
                set(self.policy["sourceObjectInputs"])
            )
        )

    def test_critical_source_object_cannot_be_removed(self):
        self.policy["sourceObjectInputs"].remove(
            "codex-rs/hepta-memory-retrieval/src/vector_publication_append.rs"
        )
        self.write_policy()
        with self.assertRaisesRegex(
            policy.PolicyError,
            "mandatory source objects are absent",
        ):
            policy.load_policy(self.root)


if __name__ == "__main__":
    unittest.main()
