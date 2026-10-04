"""The artifact CURRENT closure covers arbitrary inferred receiver names."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import verify_hepta_callers as proof


class ArtifactCurrentCallerClosureTests(unittest.TestCase):
    def verify_case(self, unexpected):
        row = next(
            row
            for row in proof._boundary_rows(proof._load_manifest(proof.MANIFEST))
            if row.identifier == "learning_artifact_verified_current_view"
        )
        row = replace(row, product_callers=("known.rs",))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            definition = root / row.definition_path
            definition.parent.mkdir(parents=True)
            definition.write_bytes((proof.ROOT / row.definition_path).read_bytes())
            known = "fn load() { let inferred = load_selected_candidate(a, b, c)?; inferred.with_current(current, consume)?; }"
            (root / "known.rs").write_text(known)
            (root / "new.rs").write_text(unexpected)
            index = {
                "known.rs": known,
                "new.rs": proof._strip_cfg_test_items(
                    proof._strip_rust_non_code(unexpected)
                ),
            }
            return proof._verify_boundary(root, row, index, ("_tests.rs",))

    def test_a_new_inferred_receiver_cannot_bypass_the_closed_caller_inventory(self):
        with self.assertRaisesRegex(
            proof.VerificationFailure, r"unexpected=\['new.rs'\]"
        ):
            self.verify_case(
                "fn load() { let renamed = load_selected_candidate(a, b, c)?; renamed.with_current(current, consume)?; }"
            )

    def test_an_explicit_branded_call_cannot_bypass_the_closed_caller_inventory(self):
        with self.assertRaisesRegex(
            proof.VerificationFailure, r"unexpected=\['new.rs'\]"
        ):
            self.verify_case(
                "fn load() { RevalidatingCandidate::with_current(&mut opaque, current, consume)?; }"
            )

    def test_examples_and_test_only_items_cannot_manufacture_a_product_caller(self):
        result = self.verify_case(
            'fn text() { let example = "renamed.with_current(current)"; } // renamed.with_current(current)\n#[cfg(test)] mod tests { fn example() { renamed.with_current(current); } }'
        )
        self.assertEqual(result["productCallers"], ["known.rs"])


class ArtifactRenewalCallerClosureTests(unittest.TestCase):
    def test_new_raw_renewal_constructor_is_limited_to_the_sole_writer_service(self):
        row = next(
            row
            for row in proof._boundary_rows(proof._load_manifest(proof.MANIFEST))
            if row.identifier == "learning_artifact_owner_renewal"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (row.definition_path, *row.product_callers):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((proof.ROOT / name).read_bytes())
            index = {
                name: proof._strip_cfg_test_items(
                    proof._strip_rust_non_code((root / name).read_text())
                )
                for name in row.product_callers
            }
            index["new.rs"] = (
                "fn unauthorized() { LearningArtifactOwnerHost::"
                "open_for_fresh_evidence_publication(config); }"
            )
            with self.assertRaisesRegex(
                proof.VerificationFailure, r"unexpected=\['new.rs'\]"
            ):
                proof._verify_boundary(root, row, index, ("_tests.rs",))


class ArtifactPublicationClockRoutingTests(unittest.TestCase):
    """Source routing guards complement real owner phase/recovery tests."""

    routes = (
        (
            "codex-rs/hepta-agentd/src/learning_operator_artifact_owner.rs",
            "service",
            "publish_with_clock",
            "clock()",
        ),
        (
            "codex-rs/hepta-agentd/src/learning_withdrawal.rs",
            "owner",
            "publish_with_state_changes_and_clock",
            "now()",
        ),
        (
            "codex-rs/hepta-infer-worker-host/src/initial_cpu_publication.rs",
            "service",
            "publish_with_clock",
            "now_ms()",
        ),
        (
            "codex-rs/hepta-infer-worker-host/src/initial_cpu_withdrawal.rs",
            "owner",
            "publish_with_state_changes_and_clock",
            "now_ms()",
        ),
    )

    def assert_clock_route(self, source, receiver, method, clock):
        import re

        code = proof._strip_cfg_test_items(proof._strip_rust_non_code(source))
        self.assertEqual(
            len(re.findall(rf"\b{receiver}\s*\.\s*{method}\s*\(", code)), 1
        )
        self.assertNotRegex(
            code, rf"\b{receiver}\s*\.\s*(?:publish|publish_with_state_changes)\s*\("
        )
        call = code.index(method)
        callback = code[call:]
        self.assertIn("&mut ||", callback)
        self.assertIn(clock, callback)
        self.assertIn("ClockUnavailable", callback)

    def test_all_real_publication_routes_use_existing_fallible_clocks(self):
        for path, receiver, method, clock in self.routes:
            with self.subTest(path=path):
                self.assert_clock_route(
                    (proof.ROOT / path).read_text(), receiver, method, clock
                )

    def test_each_route_rejects_a_return_to_logical_time_compatibility(self):
        for path, receiver, method, clock in self.routes:
            with self.subTest(path=path):
                source = (proof.ROOT / path).read_text()
                old = (
                    "publish"
                    if method == "publish_with_clock"
                    else "publish_with_state_changes"
                )
                with self.assertRaises(AssertionError):
                    self.assert_clock_route(
                        source.replace(method, old), receiver, method, clock
                    )


if __name__ == "__main__":
    unittest.main()
