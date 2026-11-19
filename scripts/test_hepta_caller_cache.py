import tempfile
import unittest
from pathlib import Path

import verify_hepta_callers as verifier


class InvocationFieldIndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "src").mkdir()
        (self.root / "src/gate.rs").write_text(
            "pub struct Gate; impl Gate { "
            "pub fn enter(&self) {} pub fn leave(&self) {} }",
            encoding="utf-8",
        )
        self.client = self.root / "src/client.rs"
        self.client.write_text(
            "struct Holder { authority: Gate } "
            "impl Holder { fn call(&self) { "
            "self.authority.enter(); self.authority.leave(); } }",
            encoding="utf-8",
        )
        manifest = """schema_version = 2
plan_id = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
source_roots = ["src"]
ignored_path_fragments = []

[authority]
runtime = false

[privileged_inventory]
required_boundary_ids = ["gate_enter", "gate_leave"]
"""
        for method in ("enter", "leave"):
            manifest += f"""
[[boundary]]
id = "gate_{method}"
symbol = "Gate::{method}"
receiver_type = "Gate"
definition_path = "src/gate.rs"
definition_markers = ["pub struct Gate;"]
product_callers = ["src/client.rs"]
caller_markers = ["Holder"]
"""
        manifest += """
[[protected_file]]
path = "src/gate.rs"
required = ["pub struct Gate;"]
forbidden = []
"""
        (self.root / "CALLERS.toml").write_text(manifest, encoding="utf-8")

    def test_two_boundary_proof_rejects_changed_source_on_next_invocation(self):
        receipt = verifier.verify(self.root)
        self.assertEqual(receipt["rustFilesScanned"], 2)
        self.assertEqual(
            [row["productCallers"] for row in receipt["boundaries"]],
            [["src/client.rs"], ["src/client.rs"]],
        )
        # Reusing the old Holder->Gate field would wrongly accept this
        # second proof. A new invocation must derive the changed source.
        self.client.write_text(
            self.client.read_text(encoding="utf-8").replace(
                "authority: Gate", "authority: Other"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            verifier.VerificationFailure, "gate_enter: caller set mismatch"
        ):
            verifier.verify(self.root)

    def test_no_method_call_does_not_suppress_global_field_index_failure(self):
        self.client.write_text("struct Holder { authority: Gate", encoding="utf-8")
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "gate_enter: unbalanced Rust authority context",
        ):
            verifier.verify(self.root)


if __name__ == "__main__":
    unittest.main()
