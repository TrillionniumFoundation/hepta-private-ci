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


if __name__ == "__main__":
    unittest.main()
