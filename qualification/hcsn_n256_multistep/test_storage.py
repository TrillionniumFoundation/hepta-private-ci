"""Synthetic full-shape persistence checks; no authentic inputs or propagation."""

import gzip
import tempfile
import unittest
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n256_engineering import candidate as primitive
from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire
from qualification.hcsn_n256_multistep import flow, storage


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.state = flow.DynamicState(np.zeros((5, 2, 255)), np.zeros((5, 3)),
            np.zeros((5, 2)), np.zeros((5, 2)), np.zeros((5, 3)))
        self.state.active[:, 0, 0] = [1., -.3, .2, -.7, .1]
        reset = (1.,) + (0.,)*254
        packet = flow.Packet("synthetic", 2, 2, 1, flow.F(1, 5), flow.F(1, 4),
            primitive.CSR.from_rows(({},)), (.1, -.1, .2, -.2, .3), (1.,), reset)
        self.capsule = flow.Capsule("synthetic", 0, flow.F(1, 10), self.state.coordinates(), (packet,))
        self.physics = {"nodes": np.linspace(0, 8, 257), "reset": reset,
            "metadata": {"physics": {"mu": 0., "sigma": .35, "discount": .15}, "reset_distance": .03125}}

    def test_actual_restore_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.bin.gz"
            record = storage.save(self.capsule, self.physics, path)
            capsule, state, packets, physics = storage.load(path)
            self.assertEqual(capsule.state, self.capsule.state)
            self.assertEqual(packets, self.capsule.packets)
            self.assertEqual(state.coordinates(), self.state.coordinates())
            self.assertEqual(wire.encode(storage.envelope(capsule, physics)), gzip.decompress(path.read_bytes()))
            self.assertEqual(record["coordinates"]["total"], 2600 + 7 + 255 + 512)

    def test_reset_omission_is_not_a_complete_checkpoint(self):
        envelope = storage.envelope(self.capsule, self.physics)
        incomplete = wire.Envelope(envelope.metadata,
            tuple(block for block in envelope.blocks if not block.name.startswith("reset_")), envelope.packets)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.bin.gz"
            path.write_bytes(gzip.compress(wire.encode(incomplete), mtime=0))
            with self.assertRaisesRegex(ValueError, "complete state/reset"):
                storage.load(path)

    def test_packet_order_cannot_silently_change(self):
        envelope = storage.envelope(self.capsule, self.physics)
        wrong = wire.Envelope({**envelope.metadata, "packet_order": []}, envelope.blocks, envelope.packets)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.bin.gz"
            path.write_bytes(gzip.compress(wire.encode(wrong), mtime=0))
            with self.assertRaisesRegex(ValueError, "packet ordering"):
                storage.load(path)


if __name__ == "__main__":
    unittest.main()
