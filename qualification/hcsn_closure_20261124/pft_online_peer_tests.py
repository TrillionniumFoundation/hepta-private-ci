"""Actual TCP processes, immutable retries, and independent numeric controls."""

import argparse
import copy
import json
import multiprocessing
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest

import numpy as np

from .pft_online_peer import (
    DeliveryUnknown,
    MAX_FRAME,
    PeerService,
    SCHEMA,
    _receive,
    _send,
    rpc,
)
from .pft_statistics import (
    DIGEST_FIELDS,
    StatisticsLedger,
    canonical,
    digest,
    make_packet,
)


RECORDS = []


def fixture():
    contract = dict(
        schema="pft-online-statistics-v1",
        model_family="hcsn-pft-readout-research-v1",
        epoch=0,
        dimension=5,
        outputs=2,
        regularizer=0.2,
        dtype="float64",
        aggregation="sum-f64-canonical-batch-id",
        statistics_validation="augmented-psd-rtol-1e-10-v1",
        **{key: digest(["tcp-fixture", key]) for key in DIGEST_FIELDS},
    )
    rng, packets, xs, ys = np.random.default_rng(48117), [], [], []
    for i, n in enumerate((3, 7, 11, 13)):
        x, y = rng.normal(size=(n, 5)) + i, rng.normal(size=(n, 2))
        packets.append(
            make_packet(
                contract,
                f"peer-batch-{i}",
                digest([x.tolist(), y.tolist()]),
                [digest([i, j]) for j in range(n)],
                x,
                y,
            )
        )
        xs.append(x)
        ys.append(y)
    return contract, packets, xs, ys


def independent(xs, ys):
    return np.linalg.lstsq(
        np.vstack((*xs, np.sqrt(0.2) * np.eye(5))),
        np.vstack((*ys, np.zeros((5, 2)))),
        rcond=None,
    )[0]


def worker(database, contract, initial, control, crash_after_commit):
    ledger = StatisticsLedger(database, contract)
    for packet in initial:
        ledger.append(packet, ledger.state()["head"])
    if crash_after_commit:
        original = StatisticsLedger.append

        def exit_before_ack(self, packet, expected_head):
            result = original(self, packet, expected_head)
            if result["status"] == "accepted":
                os._exit(71)
            return result

        StatisticsLedger.append = exit_before_ack
    service = PeerService(database, contract)
    address = service.start()
    control.send(dict(pid=os.getpid(), address=address))
    neighbors, rounds, sent, uncertain, refused = [], 0, 0, 0, 0
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if control.poll(0.01):
                message = control.recv()
                if message == "stop":
                    break
                neighbors = message
            for neighbor in neighbors:
                try:
                    sent += service.sync(neighbor)
                except DeliveryUnknown:
                    uncertain += 1
                except ValueError:
                    refused += 1
            rounds += 1
        control.send(
            dict(
                pid=os.getpid(),
                rounds=rounds,
                sent=sent,
                unknown_delivery=uncertain,
                refused=refused,
            )
        )
    finally:
        service.close()


class Peers:
    def __init__(self, root, contract):
        self.root, self.contract, self.handles = root, contract, []

    def start(self, name, initial=(), crash=False):
        context = multiprocessing.get_context("spawn")
        owner, child = context.Pipe()
        process = context.Process(
            target=worker,
            args=(str(self.root / f"{name}.db"), self.contract, initial, child, crash),
        )
        process.start()
        child.close()
        self.handles.append((process, owner, 71 if crash else 0))
        if not owner.poll(5):
            raise TimeoutError("peer did not publish its actual listening address")
        ready = owner.recv()
        return process, owner, ready

    def close(self):
        for process, owner, _ in self.handles:
            if process.is_alive():
                try:
                    owner.send("stop")
                except (OSError, EOFError):
                    pass
        for process, owner, expected_exit in self.handles:
            process.join(5)
            timed_out = process.is_alive()
            if timed_out:
                process.kill()
                process.join()
            records = []
            while owner.poll():
                try:
                    records.append(owner.recv())
                except (OSError, EOFError):
                    break
            owner.close()
            RECORDS.append(
                dict(
                    child_pid=process.pid,
                    exit_code=process.exitcode,
                    cleanup_timeout=timed_out,
                    observations=records,
                )
            )
            if timed_out:
                raise TimeoutError("owned peer did not stop")
            if process.exitcode != expected_exit:
                raise RuntimeError(
                    f"peer {process.pid} exited {process.exitcode}, expected {expected_exit}"
                )


class PeerTests(unittest.TestCase):
    def test_four_process_cycle_converges_without_a_reducer(self):
        contract, packets, xs, ys = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            peers = Peers(Path(tmp), contract)
            try:
                live = [
                    peers.start(f"peer-{i}", [packet])
                    for i, packet in enumerate(packets)
                ]
                self.assertEqual(len({item[2]["pid"] for item in live}), 4)
                for i, (_, owner, _) in enumerate(live):
                    owner.send([live[(i + 1) % 4][2]["address"]])
                deadline, candidates = time.monotonic() + 20, []
                while time.monotonic() < deadline:
                    candidates = [
                        rpc(item[2]["address"], digest(contract), "snapshot", {})
                        for item in live
                    ]
                    if all(candidate["revision"] == 4 for candidate in candidates):
                        break
                    time.sleep(0.02)
                self.assertTrue(
                    all(candidate["revision"] == 4 for candidate in candidates)
                )
                self.assertTrue(
                    all(candidate == candidates[0] for candidate in candidates)
                )
                reference = independent(xs, ys)
                for candidate in candidates:
                    np.testing.assert_allclose(
                        candidate["weight"], reference, rtol=1e-7, atol=1e-7
                    )
                RECORDS.append(
                    dict(
                        control="four_process_cycle",
                        peers=[v[2] for v in live],
                        candidate=candidates[0],
                        max_weight_error=float(
                            np.max(np.abs(reference - candidates[0]["weight"]))
                        ),
                    )
                )
            finally:
                peers.close()

    def test_lost_ack_and_actual_receiver_restart_are_idempotent(self):
        contract, packets, xs, ys = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            peers = Peers(Path(tmp), contract)
            try:
                process, _, first = peers.start("receiver", crash=True)
                initial = rpc(first["address"], digest(contract), "inventory", {})
                original_offer = dict(packet=packets[0], expected_head=initial["head"])
                with self.assertRaises(DeliveryUnknown):
                    rpc(first["address"], digest(contract), "offer", original_offer)
                process.join(5)
                self.assertEqual(process.exitcode, 71)
                restarted, _, ready = peers.start("receiver")
                self.assertNotEqual(restarted.pid, process.pid)
                receipt = rpc(
                    ready["address"], digest(contract), "offer", original_offer
                )
                self.assertEqual(
                    (receipt["status"], receipt["revision"]), ("idempotent", 1)
                )
                candidate = rpc(ready["address"], digest(contract), "snapshot", {})
                self.assertEqual(candidate["count"], 3)
                np.testing.assert_allclose(
                    candidate["weight"],
                    independent(xs[:1], ys[:1]),
                    rtol=1e-7,
                    atol=1e-7,
                )
                RECORDS.append(
                    dict(
                        control="lost_ack_restart",
                        original=first,
                        restarted=ready,
                        unknown_delivery_observed=True,
                        replay_receipt=receipt,
                        candidate=candidate,
                    )
                )
            finally:
                peers.close()

    def test_socket_rejections_never_mutate_the_ledger(self):
        contract, packets, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            peers = Peers(Path(tmp), contract)
            try:
                _, _, ready = peers.start("receiver", [packets[0]])
                address, identity = ready["address"], digest(contract)
                before = rpc(address, identity, "inventory", {})
                changed = copy.deepcopy(packets[0])
                changed["body"]["source_sha256"] = digest("changed source")
                changed["payload_sha256"] = digest(changed["body"])
                for packet, head in [
                    (changed, before["head"]),
                    (packets[1], digest("stale")),
                ]:
                    with self.assertRaises(ValueError):
                        rpc(
                            address,
                            identity,
                            "offer",
                            dict(packet=packet, expected_head=head),
                        )
                with self.assertRaises(DeliveryUnknown):
                    rpc(address, digest("foreign epoch"), "inventory", {})
                good = canonical(
                    dict(
                        schema=SCHEMA,
                        contract_sha256=identity,
                        operation="inventory",
                        arguments={},
                    )
                )
                frames = [
                    struct.pack("!I", MAX_FRAME + 1),
                    struct.pack("!I", 1) + b"{",
                    struct.pack("!I", len(good) + 1) + good + b" ",
                ]
                for frame in frames:
                    with socket.create_connection(address, timeout=2) as stream:
                        stream.sendall(frame)
                        stream.shutdown(socket.SHUT_WR)
                        self.assertEqual(stream.recv(1), b"")
                with socket.create_connection(address, timeout=4) as stream:
                    stream.sendall(struct.pack("!I", 3) + b"{")
                    time.sleep(0.9)
                    stream.sendall(b" ")
                    self.assertEqual(stream.recv(1), b"")
                self.assertEqual(rpc(address, identity, "inventory", {}), before)
                with self.assertRaises(ValueError):
                    PeerService(Path(tmp) / "public.db", contract, ("0.0.0.0", 0))
                RECORDS.append(
                    dict(
                        control="socket_rejections",
                        unchanged_head=before["head"],
                        rejected_frames=len(frames) + 1,
                    )
                )
            finally:
                peers.close()

    def test_a_success_response_for_another_request_is_unknown(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(2)

            def wrong_reply():
                stream, _ = listener.accept()
                with stream:
                    stream.settimeout(2)
                    request = _receive(stream)
                    _send(
                        stream,
                        dict(
                            schema=SCHEMA,
                            contract_sha256=request["contract_sha256"],
                            request_sha256=digest("another request"),
                            ok=True,
                            result={},
                        ),
                    )

            thread = threading.Thread(target=wrong_reply)
            thread.start()
            try:
                with self.assertRaises(DeliveryUnknown):
                    rpc(listener.getsockname(), digest("contract"), "inventory", {})
            finally:
                thread.join(3)
            self.assertFalse(thread.is_alive())
            RECORDS.append(
                dict(control="foreign_response_digest", unknown_delivery_observed=True)
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PeerTests)
    )
    with args.output.open("x") as stream:
        json.dump(
            dict(
                schema="pft-peer-tests-v1",
                pid=os.getpid(),
                tests=result.testsRun,
                failures=len(result.failures),
                errors=len(result.errors),
                records=RECORDS,
                wall_seconds=time.perf_counter() - started,
                real_user_adoption=False,
                authenticated_work=False,
                model_quality_gain=False,
            ),
            stream,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
