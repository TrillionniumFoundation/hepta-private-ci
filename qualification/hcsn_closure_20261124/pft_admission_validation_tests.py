"""Real admission counts and concurrent capped-writer controls."""

import argparse
import copy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import traceback
import unittest

import numpy as np

from . import pft_online_peer as wire
from . import pft_online_peer_tests as legacy
from . import pft_statistics as stats
from .pft_binary_peer_tests import BinaryPeerTests
from .pft_statistics_tests import LedgerTests


RECORDS = []
BASELINE = None


def single_offer():
    contract, packets, _, _ = legacy.fixture()
    counts = dict(validate_packet=0, eigvalsh=0)
    lock = threading.Lock()
    validate, exported, eigen = (
        stats.validate_packet,
        wire.validate_packet,
        np.linalg.eigvalsh,
    )

    def validation(*args, **kwargs):
        with lock:
            counts["validate_packet"] += 1
        return validate(*args, **kwargs)

    def eigvalsh(*args, **kwargs):
        with lock:
            counts["eigvalsh"] += 1
        return eigen(*args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        service = wire.PeerService(Path(tmp) / "one.db", contract)
        before = service.ledger.state()
        address = service.start()
        try:
            stats.validate_packet = wire.validate_packet = validation
            np.linalg.eigvalsh = eigvalsh
            receipt = wire.rpc(
                address,
                stats.digest(contract),
                "offer",
                dict(packet=packets[0], expected_head=before["head"]),
            )
        finally:
            stats.validate_packet, wire.validate_packet, np.linalg.eigvalsh = (
                validate,
                exported,
                eigen,
            )
            service.close()
    return dict(
        counts=counts,
        receipt=receipt,
        packet_sha256=packets[0]["payload_sha256"],
        measurement="one received TCP offer; fixture production excluded",
    )


def receiver(index, phase, database, contract, barrier, committed, control):
    wire.MAX_BATCHES = 1
    trace, service, error = [], None, None
    try:
        service = wire.PeerService(database, contract)

        def gate(value, location):
            trace.append(
                dict(
                    phase=location,
                    at=time.monotonic(),
                    observed_revision=value["revision"]
                    if location == "inventory"
                    else None,
                )
            )
            barrier.wait(timeout=5)
            if index == 1 and not committed.wait(5):
                raise TimeoutError("first owner did not complete its commit")
            return value

        if phase == "baseline":
            inventory = wire._inventory
            wire._inventory = lambda ledger: gate(inventory(ledger), "inventory")
        else:
            validation = stats.validate_packet
            stats.validate_packet = lambda packet, contract: gate(
                validation(packet, contract), "validated"
            )
        dispatch = service.dispatch

        def observed(operation, arguments):
            trace.append(dict(phase="request_started", at=time.monotonic()))
            try:
                result = dispatch(operation, arguments)
                trace.append(
                    dict(
                        phase="committed", at=time.monotonic(), status=result["status"]
                    )
                )
                if index == 0 and result["status"] == "accepted":
                    committed.set()
                return result
            except Exception as exc:
                trace.append(
                    dict(phase="refused", at=time.monotonic(), error=repr(exc))
                )
                raise

        service.dispatch = observed
        control.send(dict(pid=os.getpid(), address=service.start()))
        control.recv()
    except Exception:
        error = traceback.format_exc()
    finally:
        if service is not None:
            service.close()
        try:
            control.send(dict(pid=os.getpid(), trace=trace, error=error))
        except (EOFError, OSError):
            pass
        control.close()
    raise SystemExit(1 if error else 0)


def concurrent_capacity(phase):
    contract, packets, _, _ = legacy.fixture()
    context = multiprocessing.get_context("spawn")
    barrier, committed = context.Barrier(2), context.Event()
    owners, observations, clients, error = [], [], [None, None], None
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "shared.db"
        ledger = stats.StatisticsLedger(database, contract)
        heads = [
            ledger.state()["head"],
            stats.digest(
                dict(
                    contract_sha256=stats.digest(contract),
                    batches=[
                        (packets[0]["body"]["batch_id"], packets[0]["payload_sha256"])
                    ],
                )
            ),
        ]
        try:
            ready = []
            for i in range(2):
                parent, child = context.Pipe()
                process = context.Process(
                    target=receiver,
                    args=(i, phase, str(database), contract, barrier, committed, child),
                )
                process.start()
                child.close()
                owners.append((process, parent))
                if not parent.poll(5):
                    raise TimeoutError("receiver startup")
                ready.append(parent.recv())

            def send(index):
                row = dict(started=time.monotonic())
                try:
                    row.update(
                        status="accepted",
                        receipt=wire.rpc(
                            ready[index]["address"],
                            stats.digest(contract),
                            "offer",
                            dict(packet=packets[index], expected_head=heads[index]),
                        ),
                    )
                except wire.DeliveryUnknown as exc:
                    row.update(
                        status="unknown", error=repr(exc), cause=repr(exc.__cause__)
                    )
                except ValueError as exc:
                    row.update(status="refused", error=str(exc))
                row["finished"] = time.monotonic()
                clients[index] = row

            threads = [
                threading.Thread(target=send, args=(i,), daemon=True) for i in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(7)
            if any(thread.is_alive() for thread in threads):
                raise TimeoutError("client deadline")
        except Exception:
            error = traceback.format_exc()
        finally:
            for process, pipe in owners:
                try:
                    pipe.send("stop")
                except (BrokenPipeError, EOFError, OSError):
                    pass
            for process, pipe in owners:
                process.join(6)
                forced = process.is_alive()
                if forced:
                    process.kill()
                    process.join(1)
                try:
                    observation = pipe.recv() if pipe.poll() else None
                except (EOFError, OSError):
                    observation = None
                observations.append(
                    dict(
                        pid=process.pid,
                        exit_code=process.exitcode,
                        forced=forced,
                        observation=observation,
                    )
                )
                pipe.close()
        state = ledger.state()
    return dict(
        phase=phase,
        owners=observations,
        clients=clients,
        state=state,
        error=error,
        capacity_limit_holds=state["revision"] <= 1,
        predicted_second_head=heads[1],
    )


def overlap(record):
    owners = record["owners"]
    if (
        record["error"]
        or len({owner["pid"] for owner in owners}) != 2
        or any(
            owner["exit_code"] != 0
            or owner["forced"]
            or not owner["observation"]
            or owner["observation"]["error"]
            for owner in owners
        )
    ):
        return False
    first, second = [owner["observation"]["trace"] for owner in owners]
    committed = next(
        (event["at"] for event in first if event["phase"] == "committed"), None
    )
    second_start = next(
        (event["at"] for event in second if event["phase"] == "request_started"), None
    )
    gate = "inventory" if record["phase"] == "baseline" else "validated"
    gates = [
        next((event for event in trace if event["phase"] == gate), None)
        for trace in (first, second)
    ]
    first_client = record["clients"][0] or {}
    return (
        committed is not None
        and second_start is not None
        and second_start < committed
        and all(
            event is not None
            and event["at"] < committed
            and (gate != "inventory" or event["observed_revision"] == 0)
            for event in gates
        )
        and first_client.get("receipt", {}).get("head")
        == record["predicted_second_head"]
    )


class AdmissionTests(unittest.TestCase):
    def test_single_received_offer_has_one_complete_validation(self):
        observed = single_offer()
        RECORDS.append(dict(control="single_offer", **observed))
        self.assertEqual(observed["counts"], dict(validate_packet=1, eigvalsh=1))
        self.assertEqual(
            {k: v for k, v in observed.items() if k != "counts"},
            {k: v for k, v in BASELINE["single_offer"].items() if k != "counts"},
        )

    def test_refusal_priority_and_exact_replay_at_capacity(self):
        contract, packets, _, _ = legacy.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            service = wire.PeerService(Path(tmp) / "bounded.db", contract)
            address = service.start()
            bound = wire.MAX_BATCHES
            wire.MAX_BATCHES = 1
            try:
                first = wire.rpc(
                    address,
                    stats.digest(contract),
                    "offer",
                    dict(
                        packet=packets[0], expected_head=service.ledger.state()["head"]
                    ),
                )
                state = service.ledger.state()
                replay = wire.rpc(
                    address,
                    stats.digest(contract),
                    "offer",
                    dict(packet=packets[0], expected_head="0" * 64),
                )
                self.assertEqual(replay, dict(first, status="idempotent"))
                conflict = copy.deepcopy(packets[1])
                conflict["body"]["batch_id"] = packets[0]["body"]["batch_id"]
                conflict["payload_sha256"] = stats.digest(conflict["body"])
                invalid = copy.deepcopy(packets[1])
                invalid["body"]["yty"][0][0] = -1.0
                invalid["payload_sha256"] = stats.digest(invalid["body"])
                for packet, reason in [
                    ({}, "envelope"),
                    (invalid, "positive semidefinite"),
                    (conflict, "conflicts"),
                    (packets[1], "batch bound"),
                ]:
                    with self.assertRaisesRegex(ValueError, reason):
                        wire.rpc(
                            address,
                            stats.digest(contract),
                            "offer",
                            dict(packet=packet, expected_head=state["head"]),
                        )
                    self.assertEqual(service.ledger.state(), state)
                for limit in (True, False, 0, -1, 1.0, "1"):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        service.ledger.append(
                            packets[1], state["head"], max_batches=limit
                        )
                    self.assertEqual(service.ledger.state(), state)
                with self.assertRaisesRegex(ValueError, "envelope"):
                    service.ledger.append({}, state["head"], max_batches=True)
                service.ledger.append(packets[1], state["head"])
                externally_over_limit = service.ledger.state()
                self.assertEqual(externally_over_limit["revision"], 2)
                with self.assertRaisesRegex(ValueError, "batch bound"):
                    wire.rpc(
                        address,
                        stats.digest(contract),
                        "offer",
                        dict(packet=packets[0], expected_head="0" * 64),
                    )
                self.assertEqual(service.ledger.state(), externally_over_limit)
                RECORDS.append(
                    dict(
                        control="refusal_priority",
                        unchanged_capped_state=state,
                        replay=replay,
                        bound_types_rejected=6,
                        packet_refusals=4,
                        uncapped_writer_can_exceed_limit=externally_over_limit,
                    )
                )
            finally:
                wire.MAX_BATCHES = bound
                service.close()

    def test_future_head_does_not_bypass_transactional_capacity(self):
        observed = concurrent_capacity("candidate")
        RECORDS.append(dict(control="concurrent_capacity", **observed))
        self.assertTrue(overlap(observed))
        self.assertTrue(observed["capacity_limit_holds"])
        self.assertEqual(observed["state"]["revision"], 1)
        self.assertEqual(
            [c["status"] for c in observed["clients"]], ["accepted", "refused"]
        )
        self.assertIn("batch bound", observed["clients"][1]["error"])


def main():
    global BASELINE
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    if args.phase == "baseline":
        result = dict(phase="baseline", single_offer=single_offer())
        print(json.dumps(result), flush=True)
        result["capacity"] = concurrent_capacity("baseline")
        result["expected_defect_reproduced"] = (
            result["single_offer"]["counts"] == dict(validate_packet=2, eigvalsh=2)
            and overlap(result["capacity"])
            and result["capacity"]["state"]["revision"] == 2
            and [c["status"] for c in result["capacity"]["clients"]]
            == ["accepted", "accepted"]
        )
        passed = result["expected_defect_reproduced"]
    else:
        BASELINE = json.loads(args.baseline.read_text())
        suite = unittest.TestSuite(
            unittest.defaultTestLoader.loadTestsFromTestCase(cls)
            for cls in (LedgerTests, legacy.PeerTests, BinaryPeerTests, AdmissionTests)
        )
        observed = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
        result = dict(
            phase="candidate",
            tests=observed.testsRun,
            failures=len(observed.failures),
            errors=len(observed.errors),
            skipped=len(observed.skipped),
            records=RECORDS,
            ledger_records=__import__(
                LedgerTests.__module__, fromlist=["RECORDS"]
            ).RECORDS,
            peer_records=legacy.RECORDS,
        )
        passed = (
            observed.wasSuccessful()
            and not observed.skipped
            and observed.testsRun == 15
        )
    result["seconds"] = time.monotonic() - started
    if args.phase == "candidate":
        result["passed"] = passed
    else:
        result["baseline_capacity_passed"] = result["capacity"]["capacity_limit_holds"]
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
