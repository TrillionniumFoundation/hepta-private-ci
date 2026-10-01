"""Compile-failure evidence must identify the intended consumer restriction."""

import importlib.util
import json
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "platform_wire_production_surface.py"
SPEC = importlib.util.spec_from_file_location("production_surface", SCRIPT)
surface = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(surface)


def diagnostic(code, message, target="platform-wire-production-surface"):
    return json.dumps(
        {
            "reason": "compiler-message",
            "target": {"name": target},
            "message": {"level": "error", "code": {"code": code}, "message": message},
        }
    )


class ProductionSurfaceEvidenceTests(unittest.TestCase):
    def test_infrastructure_failure_is_not_a_rejection(self):
        self.assertFalse(surface.expected_rejection(Path("session_escape.rs"), ""))
        self.assertFalse(
            surface.expected_rejection(
                Path("session_escape.rs"), "failed to download dependency\n"
            )
        )

    def test_dependency_error_does_not_prove_consumer_restriction(self):
        output = diagnostic("E0599", "no method named session", target="dependency")
        self.assertFalse(surface.expected_rejection(Path("session_escape.rs"), output))

    def test_unrelated_consumer_error_is_rejected(self):
        output = diagnostic("E0599", "no method named unrelated")
        self.assertFalse(surface.expected_rejection(Path("session_escape.rs"), output))

    def test_each_raw_owner_must_be_denied(self):
        names = surface.DIAGNOSTICS["raw_owners.rs"][1]
        for admitted in names:
            output = diagnostic(
                "E0432",
                "unresolved imports "
                + ", ".join(name for name in names if name != admitted),
            )
            with self.subTest(admitted=admitted):
                self.assertFalse(
                    surface.expected_rejection(Path("raw_owners.rs"), output)
                )

    def test_intended_diagnostics_are_accepted(self):
        for name, (codes, fragments) in surface.DIAGNOSTICS.items():
            with self.subTest(fixture=name):
                output = diagnostic(codes[0], " ".join(fragments))
                self.assertTrue(surface.expected_rejection(Path(name), output))


if __name__ == "__main__":
    unittest.main()
