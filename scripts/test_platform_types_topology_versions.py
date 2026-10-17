"""Version-framing and source-barrier checks, not authenticated owner execution."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py"
sys.path.insert(0, str(ORACLE.parent))
spec = importlib.util.spec_from_file_location("topology_version_oracle", ORACLE)
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


class TopologyVersionTests(unittest.TestCase):
    def setUp(self):
        document = json.loads(
            (
                ROOT / "codex-rs/hepta-types/PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json"
            ).read_text()
        )
        self.values = {row["protocol"]: row["json"] for row in document["validVectors"]}

    def test_historical_read_and_new_commitment_are_distinct(self):
        old = self.values["RuntimeTopologyCandidateV1"]
        new = self.values["RuntimeTopologyCandidateV2"]
        self.assertEqual(oracle.topology_digest(old, 1), old["candidate_digest"])
        self.assertEqual(oracle.topology_digest(new, 2), new["candidate_digest"])
        self.assertNotEqual(old["candidate_digest"], new["candidate_digest"])
        for version, candidate, other in [(1, old, new), (2, new, old)]:
            with self.assertRaisesRegex(ValueError, "candidate digest"):
                oracle.topology_digest(
                    dict(candidate, candidate_digest=other["candidate_digest"]), version
                )
            with self.assertRaisesRegex(ValueError, "topology: kind"):
                oracle.topology_digest(other, version)

    def test_preserve_old_unbound_fields_without_downgrading_v2(self):
        old = copy.deepcopy(self.values["RuntimeTopologyCandidateV1"])
        new = copy.deepcopy(self.values["RuntimeTopologyCandidateV2"])
        for candidate in (old, new):
            candidate["evaluation_digest"] = "12" * 32
        self.assertEqual(oracle.topology_digest(old, 1), old["candidate_digest"])
        with self.assertRaisesRegex(ValueError, "candidate digest"):
            oracle.topology_digest(new, 2)

    def test_public_legacy_entrypoint_is_only_the_immutable_refusal_barrier(self):
        source = (ROOT / "codex-rs/hepta-supervisor/src/module_runtime.rs").read_text()
        method = source.split("pub fn register_selected_topology_candidate(", 1)[
            1
        ].split("    // Keep the pre-selection", 1)[0]
        self.assertIn("selection: &VerifiedSelfEvolutionSelectionV1", method)
        self.assertEqual(
            method.split(") -> Result<(), RuntimeModuleSupervisorErrorV1> {", 1)[
                1
            ].strip(),
            "let _ = selection;\n        self.reject_legacy_topology_candidate(&candidate, &abis)\n    }",
        )
        barrier = source.split("fn reject_legacy_topology_candidate(", 1)[1].split(
            "    /// Atomically", 1
        )[0]
        self.assertIn("&self,", barrier)
        self.assertEqual(
            barrier.split(") -> Result<(), RuntimeModuleSupervisorErrorV1> {", 1)[
                1
            ].strip(),
            "Err(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)\n    }",
        )
        self.assertIn(
            "pending_topologies: BTreeMap<Digest32, RuntimeTopologyCandidateV2>", source
        )
        current = source.split("pub fn register_selected_topology_candidate_v2(", 1)[
            1
        ].split("    pub fn", 1)[0]
        for guard in [
            "candidate.validate()?",
            "receipt.candidate_artifact_digest != candidate.candidate_digest",
            "receipt.candidate_generation != candidate.candidate_generation",
            "receipt.predecessor_generation != candidate.baseline_generation",
        ]:
            self.assertIn(guard, current)
        self.assertLess(
            current.index("candidate.validate()?"),
            current.index("self.pending_topologies"),
        )


if __name__ == "__main__":
    unittest.main()
