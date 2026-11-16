import copy
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_fullpacket_v2_primitives.candidate import (
    CHANNELS,
    CSR,
    Capsule,
    PacketRecord,
    dump,
    from_fixture,
    load,
)
from qualification.hcsn_currentstate_fullpacket_v2_primitives.compare import compare
from qualification.hcsn_currentstate_fullpacket_v2_primitives.oracle import (
    aggregate_packet_totals,
    aggregate_rz_witness,
)
from qualification.hcsn_currentstate_fullpacket_v2_primitives.oracle import (
    from_fixture as oracle_from_fixture,
)

FIXTURE = Path(__file__).with_name("fixture.json")


class FullPacketFixtureTests(unittest.TestCase):
    def test_canonical_roundtrip_and_independent_full_coordinate_oracle(self):
        candidate = from_fixture(FIXTURE)
        oracle = oracle_from_fixture(FIXTURE)
        raw = dump(candidate)
        restored = load(raw)
        self.assertEqual(dump(restored), raw)
        self.assertEqual(
            hashlib.sha256(dump(restored)).digest(), hashlib.sha256(raw).digest()
        )
        self.assertEqual(
            compare(restored, oracle),
            {
                "coordinate_count": 48,
                "mismatch_count": 0,
                "mismatch_keys": (),
                "passed": True,
            },
        )
        self.assertEqual(len(restored.packets), 2 * CHANNELS)
        self.assertEqual(
            restored.operators[0].dense()[1][2],
            float.fromhex("0x0.0000000000001p-1022"),
        )

    def test_refuses_missing_signed_channel_duplicate_reorder_and_returning_upper(self):
        candidate = from_fixture(FIXTURE)
        with self.assertRaisesRegex(ValueError, "all probability and signed-content"):
            Capsule(
                candidate.bindings,
                candidate.interior_nodes,
                candidate.reset,
                candidate.time,
                candidate.schedule,
                candidate.upper_mode,
                candidate.state,
                candidate.packets[:-1],
                candidate.operators,
            )
        duplicate = tuple(
            sorted(
                candidate.packets + (candidate.packets[0],), key=lambda value: value.key
            )
        )
        with self.assertRaisesRegex(ValueError, "sorted and unique"):
            Capsule(
                candidate.bindings,
                candidate.interior_nodes,
                candidate.reset,
                candidate.time,
                candidate.schedule,
                candidate.upper_mode,
                candidate.state,
                duplicate,
                candidate.operators,
            )
        with self.assertRaisesRegex(ValueError, "sorted and unique"):
            Capsule(
                candidate.bindings,
                candidate.interior_nodes,
                candidate.reset,
                candidate.time,
                candidate.schedule,
                candidate.upper_mode,
                candidate.state,
                tuple(reversed(candidate.packets)),
                candidate.operators,
            )
        with self.assertRaisesRegex(ValueError, "nonreturning"):
            Capsule(
                candidate.bindings,
                candidate.interior_nodes,
                candidate.reset,
                candidate.time,
                candidate.schedule,
                0,
                candidate.state,
                candidate.packets,
                candidate.operators,
            )
        with self.assertRaisesRegex(ValueError, "lossless active/upper"):
            Capsule(
                candidate.bindings,
                candidate.interior_nodes + 1,
                candidate.reset,
                candidate.time,
                candidate.schedule,
                candidate.upper_mode,
                candidate.state,
                candidate.packets,
                candidate.operators,
            )

    def test_cold_loader_refuses_corruption_and_noncanonical_source(self):
        candidate = from_fixture(FIXTURE)
        raw = dump(candidate)
        damaged = bytearray(raw)
        damaged[-33] ^= 1
        with self.assertRaisesRegex(ValueError, "whole-container digest"):
            load(bytes(damaged))
        unknown = bytearray(raw)
        unknown[16:18] = struct.pack("<H", 99)
        unknown[-32:] = hashlib.sha256(unknown[:-32]).digest()
        with self.assertRaisesRegex(
            ValueError, "unknown, missing or reordered section"
        ):
            load(bytes(unknown))
        packet = candidate.packets[0]
        wrong_source = PacketRecord(
            packet.generation,
            packet.target,
            packet.origin,
            packet.channel,
            packet.start,
            packet.end,
            packet.coefficient,
            "33" * 32,
            packet.operator_id,
        )
        packets = tuple(
            sorted((wrong_source,) + candidate.packets[1:], key=lambda value: value.key)
        )
        with self.assertRaisesRegex(ValueError, "source identity"):
            Capsule(
                candidate.bindings,
                candidate.interior_nodes,
                candidate.reset,
                candidate.time,
                candidate.schedule,
                candidate.upper_mode,
                candidate.state,
                packets,
                candidate.operators,
            )
        with self.assertRaisesRegex(ValueError, "finite canonical binary64"):
            PacketRecord(
                1,
                1,
                0,
                0,
                candidate.time,
                candidate.time,
                float("nan"),
                candidate.bindings[1][2],
                candidate.operators[0].identity,
            )
        with self.assertRaisesRegex(ValueError, "finite canonical binary64"):
            PacketRecord(
                1,
                1,
                0,
                0,
                candidate.time,
                candidate.time,
                float("inf"),
                candidate.bindings[1][2],
                candidate.operators[0].identity,
            )
        with self.assertRaisesRegex(ValueError, "invalid CSR structure"):
            CSR(1, (0, 1), (0,), (0.0,))

    def test_same_totals_different_release_law_is_not_restorable(self):
        original = json.loads(FIXTURE.read_text())
        changed = copy.deepcopy(original)
        for packet in changed["packets"][:5]:
            packet["start"] = [1, 100]
            packet["end"] = [7, 200]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "changed.json"
            temporary.write_text(json.dumps(changed))
            original_oracle = oracle_from_fixture(FIXTURE)
            changed_oracle = oracle_from_fixture(temporary)
            self.assertEqual(
                aggregate_packet_totals(original_oracle),
                aggregate_packet_totals(changed_oracle),
            )
            self.assertEqual(
                aggregate_rz_witness(original_oracle),
                aggregate_rz_witness(changed_oracle),
            )
            with self.assertRaisesRegex(ValueError, "packet_metadata mismatch"):
                compare(from_fixture(FIXTURE), changed_oracle)

    def test_epsilon_pruning_of_subnormal_edge_is_detected(self):
        changed = json.loads(FIXTURE.read_text())
        changed["operators"][0]["entries"] = [
            entry
            for entry in changed["operators"][0]["entries"]
            if entry[2] != "0x0.0000000000001p-1022"
        ]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "pruned.json"
            temporary.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "packet_metadata mismatch"):
                compare(from_fixture(FIXTURE), oracle_from_fixture(temporary))


if __name__ == "__main__":
    unittest.main()
