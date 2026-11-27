import ast
import hashlib
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_stdlib_loader.loader import (
    BASE64_SHA256,
    PHASE_SHA256,
    STATE_SHA256,
    N256InputError,
    load_authentic_n256_input,
)


ROOT = Path(__file__).resolve().parents[2]
ORIGINALS = ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001"


def _canonical(value):
    return value.rstrip(b"\n") + b"\n"


def _copy_originals(root):
    paths = {}
    for name, expected in (
        ("N256_STATE.json", STATE_SHA256),
        ("N256_PHASE.json", PHASE_SHA256),
        ("N256_STATE.npz.b64", BASE64_SHA256),
    ):
        value = _canonical((ORIGINALS / name).read_bytes())
        if hashlib.sha256(value).hexdigest() != expected:
            raise AssertionError(f"fixture {name} does not reconstruct exact Git bytes")
        path = root / name
        path.write_bytes(value)
        paths[name] = path
    return paths


class N256StdlibLoaderTest(unittest.TestCase):
    def test_loads_every_authentic_coordinate_and_phase_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _copy_originals(Path(directory))
            values, certificate = load_authentic_n256_input(
                paths["N256_STATE.json"],
                paths["N256_PHASE.json"],
                paths["N256_STATE.npz.b64"],
            )
        self.assertEqual(tuple(len(value) for value in values[:3]), (257, 257, 1028))
        self.assertEqual(certificate.compared_fp64_coordinates, 1542)
        self.assertEqual(certificate.phase_packets, 8)
        self.assertTrue(certificate.authentic_n256_bundle_loaded)
        self.assertTrue(certificate.independent_stdlib_decode)
        self.assertFalse(certificate.candidate_or_oracle_imported)
        self.assertEqual(certificate.dynamic_calls, 0)
        self.assertEqual(certificate.matrix_exponential_calls, 0)
        self.assertEqual(certificate.reference_records_emitted, 0)
        self.assertFalse(certificate.largegrid_qualification)

    def test_rejects_noncanonical_or_changed_base64(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _copy_originals(Path(directory))
            original = paths["N256_STATE.npz.b64"].read_bytes()
            paths["N256_STATE.npz.b64"].write_bytes(original + b"\n")
            with self.assertRaisesRegex(N256InputError, "SHA-256 mismatch"):
                load_authentic_n256_input(
                    paths["N256_STATE.json"],
                    paths["N256_PHASE.json"],
                    paths["N256_STATE.npz.b64"],
                )
            changed = bytearray(original)
            changed[32] = ord("A") if changed[32] != ord("A") else ord("B")
            paths["N256_STATE.npz.b64"].write_bytes(changed)
            with self.assertRaisesRegex(N256InputError, "SHA-256 mismatch"):
                load_authentic_n256_input(
                    paths["N256_STATE.json"],
                    paths["N256_PHASE.json"],
                    paths["N256_STATE.npz.b64"],
                )

    def test_rejects_changed_state_or_phase_original(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _copy_originals(Path(directory))
            state = paths["N256_STATE.json"].read_bytes()
            paths["N256_STATE.json"].write_bytes(
                state.replace(b"attempt001", b"attempt00X", 1)
            )
            with self.assertRaisesRegex(N256InputError, "state JSON SHA-256 mismatch"):
                load_authentic_n256_input(
                    paths["N256_STATE.json"],
                    paths["N256_PHASE.json"],
                    paths["N256_STATE.npz.b64"],
                )
            paths = _copy_originals(Path(directory))
            phase = paths["N256_PHASE.json"].read_bytes()
            paths["N256_PHASE.json"].write_bytes(phase.replace(b"phase-0", b"phase-X"))
            with self.assertRaisesRegex(N256InputError, "phase JSON SHA-256 mismatch"):
                load_authentic_n256_input(
                    paths["N256_STATE.json"],
                    paths["N256_PHASE.json"],
                    paths["N256_STATE.npz.b64"],
                )

    def test_source_is_independent_and_excludes_numeric_kernels(self):
        source = (Path(__file__).parent / "loader.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertFalse(imported & {"numpy", "scipy", "torch"})
        self.assertNotIn("expm_multiply", source)
        self.assertNotIn("hcsn_currentstate_n256_candidate", source)
        self.assertNotIn("hcsn_currentstate_n256_oracle", source)


if __name__ == "__main__":
    unittest.main()
