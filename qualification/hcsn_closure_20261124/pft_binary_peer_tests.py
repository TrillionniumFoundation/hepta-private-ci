"""New binary-profile controls and JSON-default compatibility on changed source."""

import argparse
import copy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from . import pft_online_peer as wire
from . import pft_online_peer_tests as legacy
from .pft_binary_peer import BinaryMessages, HEADER, MAGIC
from .pft_statistics import canonical, digest


RECORDS = legacy.RECORDS


def binary_worker(database, contract, initial, control, crash):
    # Only this test child installs the explicit profile. The production service
    # default and the separately executed JSON controls remain unchanged.
    def service(*args, **kwargs):
        return wire.PeerService(*args, **kwargs, codec=BinaryMessages(contract))

    legacy.PeerService = service
    legacy.worker(database, contract, initial, control, crash)


class BinaryPeers(legacy.Peers):
    def start(self, name, initial=(), crash=False):
        context = multiprocessing.get_context("spawn")
        owner, child = context.Pipe()
        process = context.Process(target=binary_worker, args=(str(self.root / f"{name}.db"),
                    self.contract, initial, child, crash))
        process.start()
        child.close()
        self.handles.append((process, owner, 71 if crash else 0))
        if not owner.poll(5):
            raise TimeoutError("binary peer did not publish its listening address")
        return process, owner, owner.recv()


class BinaryPeerTests(unittest.TestCase):
    def test_message_roundtrip_and_strict_profile_boundaries(self):
        contract, packets, _, _ = legacy.fixture()
        codec = BinaryMessages(contract)
        request = dict(schema=wire.SCHEMA, contract_sha256=digest(contract),
                       operation="offer", arguments=dict(packet=packets[0], expected_head=digest("head")))
        raw = codec.encode(request)
        self.assertEqual(canonical(codec.decode(raw)), canonical(request))
        inventory = dict(schema=wire.SCHEMA, contract_sha256=digest(contract), operation="inventory", arguments={})
        self.assertEqual(codec.decode(codec.encode(inventory)), inventory)
        malformed = [raw[:8], b"WRNG" + raw[4:], raw + b"x", raw[:-1],
                     HEADER.pack(MAGIC, 2, 1) + b"{}", codec.encode(inventory) + b"x"]
        meta = canonical(inventory) + b" "
        malformed.append(HEADER.pack(MAGIC, 0, len(meta)) + meta)
        for rejected in malformed:
            with self.assertRaises(ValueError):
                codec.decode(rejected)
        changed = copy.deepcopy(request)
        changed["arguments"]["unexpected"] = "not allowed"
        with self.assertRaises(ValueError):
            codec.encode(changed)
        foreign = dict(inventory, contract_sha256=digest("foreign"))
        with self.assertRaises(ValueError):
            codec.encode(foreign)
        with tempfile.TemporaryDirectory() as tmp:
            bad = dict(contract, epoch=contract["epoch"] + 1)
            with self.assertRaises(ValueError):
                wire.PeerService(Path(tmp) / "wrong.db", bad, codec=codec)
            self.assertFalse((Path(tmp) / "wrong.db").exists())
        RECORDS.append(dict(control="binary_message_boundaries", original_offer_json_bytes=len(canonical(request)),
                            binary_offer_bytes=len(raw), roundtrip_canonical_equal=True, malformed=len(malformed)))

    def test_actual_four_process_binary_cycle(self):
        contract, packets, xs, ys = legacy.fixture()
        codec = BinaryMessages(contract)
        with tempfile.TemporaryDirectory() as tmp:
            peers = BinaryPeers(Path(tmp), contract)
            try:
                live = [peers.start(f"peer-{i}", [packet]) for i, packet in enumerate(packets)]
                self.assertEqual(len({v[2]["pid"] for v in live}), 4)
                for i, (_, owner, _) in enumerate(live):
                    owner.send([live[(i + 1) % 4][2]["address"]])
                deadline, candidates = time.monotonic() + 20, []
                while time.monotonic() < deadline:
                    candidates = [wire.rpc(v[2]["address"], digest(contract), "snapshot", {}, codec=codec) for v in live]
                    if all(candidate["revision"] == 4 for candidate in candidates):
                        break
                    time.sleep(0.02)
                self.assertTrue(all(candidate["revision"] == 4 for candidate in candidates))
                self.assertTrue(all(candidate == candidates[0] for candidate in candidates))
                reference = legacy.independent(xs, ys)
                np.testing.assert_allclose(candidates[0]["weight"], reference, rtol=1e-7, atol=1e-7)
                RECORDS.append(dict(control="binary_four_process_cycle", peers=[v[2] for v in live],
                                    candidate=candidates[0], max_weight_error=float(np.max(np.abs(reference-candidates[0]["weight"])))))
            finally:
                peers.close()

    def test_binary_lost_ack_then_exact_old_head_replay(self):
        contract, packets, xs, ys = legacy.fixture()
        codec = BinaryMessages(contract)
        with tempfile.TemporaryDirectory() as tmp:
            peers = BinaryPeers(Path(tmp), contract)
            try:
                process, _, first = peers.start("receiver", crash=True)
                initial = wire.rpc(first["address"], digest(contract), "inventory", {}, codec=codec)
                offer = dict(packet=packets[0], expected_head=initial["head"])
                with self.assertRaises(wire.DeliveryUnknown):
                    wire.rpc(first["address"], digest(contract), "offer", offer, codec=codec)
                process.join(5)
                self.assertEqual(process.exitcode, 71)
                restarted, _, ready = peers.start("receiver")
                self.assertNotEqual(restarted.pid, process.pid)
                receipt = wire.rpc(ready["address"], digest(contract), "offer", offer, codec=codec)
                self.assertEqual((receipt["status"], receipt["revision"]), ("idempotent", 1))
                candidate = wire.rpc(ready["address"], digest(contract), "snapshot", {}, codec=codec)
                self.assertEqual(candidate["count"], 3)
                np.testing.assert_allclose(candidate["weight"], legacy.independent(xs[:1], ys[:1]), rtol=1e-7, atol=1e-7)
                RECORDS.append(dict(control="binary_lost_ack", original=first, restarted=ready, receipt=receipt))
            finally:
                peers.close()

    def test_mixed_wire_profiles_refuse_without_fallback_or_mutation(self):
        contract, packets, _, _ = legacy.fixture()
        codec = BinaryMessages(contract)
        with tempfile.TemporaryDirectory() as tmp:
            plain = legacy.Peers(Path(tmp), contract)
            binary = BinaryPeers(Path(tmp), contract)
            try:
                _, _, a = plain.start("plain", [packets[0]])
                _, _, b = binary.start("binary", [packets[0]])
                plain_before = wire.rpc(a["address"], digest(contract), "inventory", {})
                binary_before = wire.rpc(b["address"], digest(contract), "inventory", {}, codec=codec)
                with self.assertRaises(wire.DeliveryUnknown):
                    wire.rpc(a["address"], digest(contract), "offer", dict(packet=packets[1], expected_head=plain_before["head"]), codec=codec)
                with self.assertRaises(wire.DeliveryUnknown):
                    wire.rpc(b["address"], digest(contract), "offer", dict(packet=packets[1], expected_head=binary_before["head"]))
                self.assertEqual(wire.rpc(a["address"], digest(contract), "inventory", {}), plain_before)
                self.assertEqual(wire.rpc(b["address"], digest(contract), "inventory", {}, codec=codec), binary_before)
                RECORDS.append(dict(control="mixed_profile_refusal", unchanged_head=plain_before["head"], automatic_fallback=False))
            finally:
                plain.close()
                binary.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(legacy.PeerTests), loader.loadTestsFromTestCase(BinaryPeerTests)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    with args.output.open("x") as stream:
        json.dump(dict(schema="pft-binary-peer-tests-v1", pid=os.getpid(), tests=result.testsRun,
                       failures=len(result.failures), errors=len(result.errors), records=RECORDS,
                       wall_seconds=time.perf_counter()-started, authenticated_work=False,
                       real_user_adoption=False, model_quality_gain=False), stream, indent=2, allow_nan=False)
        stream.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
