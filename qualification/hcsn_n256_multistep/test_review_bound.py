"""Short artifact-only controls; no numerical propagation or reference solver."""

import gzip
import hashlib
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np

from qualification.hcsn_n256_multistep import review_bound as reader


class ReviewArtifactsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.attempt = root / "attempt"
        source_root = patch.object(
            reader, "__file__", str(root / "qualification/example/review_bound.py")
        )
        source_root.start()
        self.addCleanup(source_root.stop)
        roster = root / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001"
        roster.mkdir(parents=True)
        times = reader.WARM_QUERIES
        lane_times = {
            "warm": times,
            "coarse": (times[0], times[4], times[7]),
            "cold": times[5:],
        }
        roster_rows, packet_rows = [], []
        for lane, queries in lane_times.items():
            folder = self.attempt / lane
            folder.mkdir(parents=True)
            capsules = []
            for index, time in enumerate(queries):
                packet = reader.wire.Packet(
                    "packet-one", 1, 1, 2, "0", "1", self.tensor(np.zeros((5, 1))),
                    self.tensor(np.zeros((1, 1))), self.tensor(np.zeros((1,)))
                )
                blocks = {
                    key: self.tensor(np.zeros(shape))
                    for key, shape in reader.STATE_BLOCKS + (
                        ("physics_nodes", (257,)), ("physics_reset", (255,)),
                        ("reset_packet-one", (255,)),
                    )
                }
                envelope = reader.wire.Envelope(
                    {"time": time, "packet_order": [packet.identity]},
                    tuple(reader.wire.Block(name, value) for name, value in sorted(blocks.items())),
                    (packet,),
                )
                payload = reader.wire.encode(envelope)
                name = f"capsule-{index}.bin.gz"
                (folder / name).write_bytes(gzip.compress(payload, mtime=0))
                counts = reader.wire.coordinate_counts(envelope)
                capsules.append(
                    {"path": name, "sha256": hashlib.sha256(payload).hexdigest(),
                     "raw_bytes": len(payload), "coordinates": counts}
                )
                def fraction(raw):
                    value = Fraction(raw)
                    return {"fraction": [value.numerator, value.denominator]}
                packet_rows.append({
                    "capsule_order": len(roster_rows), "source": packet.identity,
                    "generation": 1, "origin": 1, "target": 2, "dimension": 1,
                    "start": fraction("0"), "end": fraction("1"),
                })
                roster_rows.append({
                    "lane": lane, "lane_order": index, "time": fraction(time),
                    "packets": 1, "coordinate_count": 2607,
                })
            np.savez(folder / "STATES.npz", values=np.zeros((len(queries), 2600), dtype="<f8"))
            result = {
                "capsules": capsules,
                "remaining_phase": [{"identity": "packet-one", "integrated_remaining_content": [0] * 5}],
                "initial_total_probability_and_content": [0] * 5,
            }
            (folder / "RESULT.json").write_text(json.dumps(result))
        (roster / "CAPSULES.json").write_text(json.dumps(roster_rows))
        (roster / "PACKET_ROSTER.jsonl").write_text(
            "\n".join(json.dumps(row) for row in packet_rows)
        )
        for reference in ("reference_coarse", "reference_fine"):
            folder = self.attempt / reference
            folder.mkdir()
            np.savez(folder / "REFERENCE.npz", values=np.zeros((8, 2600), dtype="<f8"))
            (folder / "RESULT.json").write_text(json.dumps({"queries": times, "shape": [8, 2600]}))
        (self.attempt / "REVIEW.json").write_text("leave original report untouched")

    @staticmethod
    def tensor(values):
        values = np.asarray(values, dtype="<f8")
        return reader.wire.Tensor("<f8", values.shape, values.tobytes())

    def test_full_readback(self):
        result = reader.review(self.attempt)
        self.assertEqual(result["capsules"], 14)
        self.assertTrue(result["all_candidate_rows_exactly_bound_to_capsules"])
        self.assertTrue(result["remaining_phase_roster_verified"])
        self.assertEqual((self.attempt / "REVIEW.json").read_text(), "leave original report untouched")

    def test_mismatched_candidate_row(self):
        wrong = np.zeros((3, 2600), dtype="<f8")
        wrong[1, -1] = -0.0  # Numerically equal, but not the capsule's exact payload.
        np.savez(self.attempt / "cold/STATES.npz", values=wrong)
        with self.assertRaisesRegex(ValueError, "capsule/NPZ byte mismatch at row 1"):
            reader.review(self.attempt)

    def test_broadcastable_reference_shape(self):
        np.savez(self.attempt / "reference_fine/REFERENCE.npz", values=np.zeros((1, 2600), dtype="<f8"))
        with self.assertRaisesRegex(ValueError, "expected finite little-endian FP64"):
            reader.review(self.attempt)

    def test_nonfinite_reference(self):
        values = np.zeros((8, 2600), dtype="<f8")
        values[2, 5] = np.nan
        np.savez(self.attempt / "reference_fine/REFERENCE.npz", values=values)
        with self.assertRaisesRegex(ValueError, "expected finite little-endian FP64"):
            reader.review(self.attempt)

    def test_reordered_bdf_queries(self):
        result_path = self.attempt / "reference_coarse/RESULT.json"
        result = json.loads(result_path.read_text())
        result["queries"].reverse()
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "unexpected BDF query roster"):
            reader.review(self.attempt)

    def test_missing_phase_row(self):
        result_path = self.attempt / "warm/RESULT.json"
        result = json.loads(result_path.read_text())
        result["remaining_phase"] = []
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "remaining-phase roster differs"):
            reader.review(self.attempt)


if __name__ == "__main__":
    unittest.main()
