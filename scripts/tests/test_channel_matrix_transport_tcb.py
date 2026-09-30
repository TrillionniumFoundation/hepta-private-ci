"""Executable transport TCB regressions for channel.matrix."""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_transport_tcb.py"
spec = importlib.util.spec_from_file_location("channel_matrix_transport_tcb_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class TransportTcbTests(unittest.TestCase):
    def test_repository_transport_tcb_is_closed(self) -> None:
        row = module.validate(ROOT)
        self.assertEqual(row["result"], "pass")
        self.assertEqual(
            row["observedImplementationPaths"],
            sorted(
                [
                    "codex-rs/hepta-matrix-sdk/src/sdk.rs",
                    "codex-rs/hepta-matrix-sdk/src/sdk_implementation.rs",
                ]
            ),
        )
        self.assertFalse(row["authorityGranted"])

    def fixture(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        registry = "docs/modules/channel.matrix/TRANSPORT_TCB.json"
        selected = [
            registry,
            "codex-rs/hepta-matrix-sdk/src/lib.rs",
            "codex-rs/hepta-matrix-sdk/src/sdk.rs",
            "codex-rs/hepta-matrix-sdk/src/sdk_implementation.rs",
            "codex-rs/hepta-matrix-sdk/src/authority.rs",
            "codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs",
            "codex-rs/hepta-matrixd/src/runner.rs",
        ]
        for relative in selected:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        return root

    def test_removing_forbid_unsafe_fails_closed(self) -> None:
        root = self.fixture()
        path = root / "codex-rs/hepta-matrix-sdk/src/lib.rs"
        path.write_text(
            path.read_text(encoding="utf-8").replace("#![forbid(unsafe_code)]", ""),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "forbids unsafe"):
            module.validate(root)

    def test_unregistered_transport_implementation_fails_closed(self) -> None:
        root = self.fixture()
        rogue = root / "codex-rs/hepta-matrix-sdk/src/rogue.rs"
        rogue.write_text(
            "impl MatrixOutboundTransport for MatrixSdkClient {}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "unregistered"):
            module.validate(root)

    def test_raw_client_escape_and_product_composition_drift_fail_closed(self) -> None:
        root = self.fixture()
        facade = root / "codex-rs/hepta-matrix-sdk/src/sdk.rs"
        facade.write_text(
            facade.read_text(encoding="utf-8") + "\npub fn client() {}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "raw client"):
            module.validate(root)

        root = self.fixture()
        runner = root / "codex-rs/hepta-matrixd/src/runner.rs"
        runner.write_text(
            runner.read_text(encoding="utf-8").replace(
                "run_outbox_sender(", "run_unregistered_sender("
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "registered transport"):
            module.validate(root)

    def test_dynamic_or_ffi_transport_boundary_fails_closed(self) -> None:
        for token in ("libloading", 'extern "C"'):
            with self.subTest(token=token):
                root = self.fixture()
                path = root / "codex-rs/hepta-matrix-sdk/src/dynamic.rs"
                path.write_text(f"// {token}\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "forbidden dynamic boundary"):
                    module.validate(root)


if __name__ == "__main__":
    unittest.main()
