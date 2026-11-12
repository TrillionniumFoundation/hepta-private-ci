import ast
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from . import candidate, compare, oracle


class EngineeringTests(unittest.TestCase):
    def fixture(self, root):
        op1 = candidate.CSR.from_rows(({0: -2.0, 1: 2.0}, {1: -1.0}))
        op2 = candidate.CSR.from_rows(({},))
        source = hashlib.sha256(b"fixture-source").hexdigest()
        input_hash = hashlib.sha256(b"fixture-input").hexdigest()
        packets = (
            candidate.NumericPacket(
                source, 1, 1, 0, F(0), F(1, 40), op1, tuple([0.25, 0.5] * 5), (0.0, 1.0)
            ),
            candidate.NumericPacket(
                source, 1, 1, 0, F(1, 40), F(1, 20), op2, tuple([0.125] * 5), (1.0,)
            ),
        )
        capsule = candidate.NumericCapsule(
            hashlib.sha256(b"fixture-roster").hexdigest(),
            (("input", input_hash),),
            hashlib.sha256(b"fixture-capsule").hexdigest(),
            0,
            F(0),
            3,
            tuple([0.0] * 80),
            packets,
        )
        fixture = {
            "state": [value.hex() for value in capsule.state],
            "operators": [
                {
                    "name": "two",
                    "dense": [[(-2.0).hex(), (2.0).hex()], [(0.0).hex(), (-1.0).hex()]],
                },
                {"name": "one", "dense": [[(0.0).hex()]]},
            ],
            "packets": [
                {
                    "source": source,
                    "generation": 1,
                    "target": 1,
                    "origin": 0,
                    "start": [0, 1],
                    "end": [1, 40],
                    "operator": "two",
                    "alpha": [value.hex() for value in packets[0].alpha],
                    "output": [value.hex() for value in packets[0].output],
                },
                {
                    "source": source,
                    "generation": 1,
                    "target": 1,
                    "origin": 0,
                    "start": [1, 40],
                    "end": [1, 20],
                    "operator": "one",
                    "alpha": [value.hex() for value in packets[1].alpha],
                    "output": [value.hex() for value in packets[1].output],
                },
            ],
        }
        path = Path(root) / "fixture.json"
        path.write_text(json.dumps(fixture))
        return capsule, path

    def test_small_fixture_roundtrip_oracle_and_comparator(self):
        with tempfile.TemporaryDirectory() as root:
            capsule, fixture = self.fixture(root)
            raw = candidate.dump(capsule)
            restored = candidate.load(raw)
            self.assertEqual(candidate.dump(restored), raw)
            left = candidate.coordinate_lines(restored)
            right = oracle.coordinate_lines(oracle.from_fixture(fixture))
            left_path, right_path = (
                Path(root) / "left.jsonl",
                Path(root) / "right.jsonl",
            )
            left_path.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in left)
            )
            right_path.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in right)
            )
            self.assertEqual(
                compare.compare(left_path, right_path),
                {"coordinates": 103, "mismatches": 0, "passed": True},
            )

    def test_digest_section_order_and_negative_zero_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            capsule, _ = self.fixture(root)
            raw = candidate.dump(capsule)
            damaged = bytearray(raw)
            damaged[16] ^= 1
            with self.assertRaisesRegex(ValueError, "container identity"):
                candidate.load(bytes(damaged))
            changed = list(capsule.state)
            changed[0] = -0.0
            with self.assertRaisesRegex(ValueError, "nonnegative-zero"):
                candidate.NumericCapsule(
                    capsule.roster_identity,
                    capsule.input_hashes,
                    capsule.capsule_identity,
                    0,
                    F(0),
                    3,
                    tuple(changed),
                    capsule.packets,
                )

    def test_missing_signed_channel_and_source_hash_rejected(self):
        op = candidate.CSR.from_rows(({},))
        with self.assertRaisesRegex(ValueError, "numeric packet shape"):
            candidate.NumericPacket(
                "0" * 64, 1, 1, 0, F(0), F(1, 40), op, (1.0,) * 4, (1.0,)
            )
        with self.assertRaisesRegex(ValueError, "authentic input hash"):
            candidate.load_inputs(__file__, __file__, __file__)

    def test_oracle_and_comparator_import_isolation(self):
        package = Path(__file__).parent

        def imported(name):
            tree = ast.parse((package / name).read_text())
            return [
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            ]

        self.assertFalse(
            any(
                "candidate" in name or "compare" in name
                for name in imported("oracle.py")
            )
        )
        self.assertFalse(
            any(
                "candidate" in name or "oracle" in name
                for name in imported("compare.py")
            )
        )

    def test_comparator_rejects_denominator_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as root:
            left, right = Path(root) / "left", Path(root) / "right"
            row = {"key": ["state", 0], "fp64_le": "0000000000000000"}
            left.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            right.write_text(json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "sorted and unique"):
                compare.compare(left, right)


if __name__ == "__main__":
    unittest.main()
