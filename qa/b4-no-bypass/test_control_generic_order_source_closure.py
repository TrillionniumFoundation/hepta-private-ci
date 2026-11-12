"""Guard actual generic Circuit control completion without loosening bypass checks."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "control_generic_order_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
CONTROL = "codex-rs/hepta-agentd/src/control.rs"


class ControlGenericFunctionOrderTests(unittest.TestCase):
    def test_actual_generic_function_and_negative_mutants(self):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        rows = [row for row in manifest["protected_file"] if row["path"] == CONTROL]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            row["required_function_order"][0]["function"],
            "fn serve_connection<P: ControlProfile>(",
        )
        source = (ROOT / CONTROL).read_text()
        mutations = (
            (
                "fn serve_connection<P: ControlProfile>(",
                "fn serve_connection<P: OtherProfile>(",
            ),
            ("if circuit_admission {", "if disabled_control_branch {"),
            (
                "P::response(&state, request).await",
                "P::response_without_owner(&state, request).await",
            ),
            (
                "timeout(IO_TIMEOUT, P::response(&state, request))",
                "timeout(IO_TIMEOUT, P::response_without_limit(&state, request))",
            ),
            (
                "frames::write_frame(&mut writer, &bytes).await?",
                "frames::write_frame(&mut writer, &other_bytes).await?",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / CONTROL
            path.parent.mkdir(parents=True)
            path.write_text(source)
            self.assertEqual(
                PROOF._verify_protected_files(root, {"protected_file": [row]}),
                [CONTROL],
            )
            for old, new in mutations:
                with self.subTest(old=old):
                    self.assertEqual(source.count(old), 1)
                    path.write_text(source.replace(old, new, 1))
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": [row]})
