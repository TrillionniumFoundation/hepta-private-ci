"""Independent-process concurrency, crash recovery and pooled-data checks."""

import argparse
from contextlib import contextmanager
import copy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .pft_statistics import (
    DIGEST_FIELDS,
    StatisticsLedger,
    digest,
    make_packet,
    validate_packet,
)
from .pft_statistics_codec import decode_packet, encode_packet


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
        **{key: digest(["synthetic-fixture", key]) for key in DIGEST_FIELDS},
    )
    rng, packets, xs, ys = np.random.default_rng(817), [], [], []
    for i, n in enumerate((3, 7, 11)):
        x, y = rng.normal(size=(n, 5)) + i, rng.normal(size=(n, 2))
        packets.append(
            make_packet(
                contract,
                f"batch-{i}",
                digest([x.tolist(), y.tolist()]),
                [digest([i, j]) for j in range(n)],
                x,
                y,
            )
        )
        xs.append(x)
        ys.append(y)
    return contract, packets, np.vstack(xs), np.vstack(ys)


def worker(path, contract, packet, expected, output, mode, barrier):
    ledger = StatisticsLedger(path, contract)
    if mode == "before_commit":
        original = ledger.connect

        @contextmanager
        def interrupted():
            with original() as db:

                def stop(statement):
                    if statement.startswith("INSERT INTO samples"):
                        os._exit(41)

                db.set_trace_callback(stop)
                yield db

        ledger.connect = interrupted
    if barrier is not None:
        barrier.wait(timeout=30)
    try:
        result = ledger.append(packet, expected)
    except ValueError as error:
        result = dict(status="rejected", reason=str(error))
    if mode == "after_commit":
        os._exit(42)
    Path(output).write_text(json.dumps(dict(pid=os.getpid(), **result)))


def launch(root, contract, packets, expected, mode="append"):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(len(packets)) if len(packets) > 1 else None
    processes, files = [], []
    for i, packet in enumerate(packets):
        output = root / f"result-{i}.json"
        process = context.Process(
            target=worker,
            args=(
                str(root / "ledger.db"),
                contract,
                packet,
                expected,
                str(output),
                mode,
                barrier,
            ),
        )
        process.start()
        processes.append(process)
        files.append(output)
    for process in processes:
        process.join(45)
        if process.is_alive():
            process.terminate()
            process.join()
            raise TimeoutError("owned qualification process did not finish")
    record = dict(
        mode=mode,
        pids=[p.pid for p in processes],
        exits=[p.exitcode for p in processes],
        receipts=[json.loads(p.read_text()) if p.exists() else None for p in files],
    )
    RECORDS.append(record)
    return record


class LedgerTests(unittest.TestCase):
    def test_finite_inputs_cannot_export_overflowed_candidates(self):
        base, _, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            contract = dict(base, dimension=1, outputs=1, regularizer=1e308)
            ledger = StatisticsLedger(Path(tmp) / "regularizer.db", contract)
            packet = make_packet(
                contract, "one", digest("source"), [digest("row")], [[1e154]], [[1e154]]
            )
            ledger.append(packet, ledger.state()["head"])
            state = ledger.state()
            with self.assertRaisesRegex(ValueError, "regularized Gram"):
                ledger.snapshot()
            self.assertEqual(ledger.state(), state)
            contract = dict(contract, regularizer=1e307)
            finite = StatisticsLedger(Path(tmp) / "finite.db", contract)
            packet = make_packet(
                contract, "one", digest("source"), [digest("row")], [[1e154]], [[1e154]]
            )
            finite.append(packet, finite.state()["head"])
            self.assertAlmostEqual(
                finite.snapshot()["candidate"]["weight"][0][0], 10 / 11
            )
            for field, x, y in (("gram", 1e154, 0.0), ("yty", 0.0, 1e154)):
                contract = dict(base, dimension=1, outputs=1)
                ledger = StatisticsLedger(Path(tmp) / (field + ".db"), contract)
                for i in range(2):
                    packet = make_packet(
                        contract,
                        str(i),
                        digest(["source", i]),
                        [digest(["row", i])],
                        [[x]],
                        [[y]],
                    )
                    ledger.append(packet, ledger.state()["head"])
                state = ledger.state()
                with (
                    self.subTest(field=field),
                    self.assertRaisesRegex(ValueError, "accumulated statistics"),
                ):
                    ledger.snapshot()
                self.assertEqual(ledger.state(), state)

    def test_impossible_sample_rank_rejected_before_admission(self):
        contract, packets, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = StatisticsLedger(Path(tmp) / "ledger.db", contract)
            ledger.append(packets[0], ledger.state()["head"])
            state = ledger.state()
            for scale in (1.0, 1e150, 1e308):
                packet = copy.deepcopy(packets[1])
                body = packet["body"]
                body.update(
                    count=1,
                    sample_ids=body["sample_ids"][:1],
                    gram=(np.eye(5) * scale).tolist(),
                    rhs=np.zeros((5, 2)).tolist(),
                    yty=(np.eye(2) * scale).tolist(),
                )
                packet["payload_sha256"] = digest(body)
                # Encoding preserves bytes; mathematical admission is downstream.
                decoded = decode_packet(encode_packet(packet, contract), contract)
                self.assertEqual(decoded, packet)
                for representation in (packet, decoded):
                    with (
                        self.subTest(scale=scale),
                        np.errstate(over="raise", invalid="raise"),
                        self.assertRaisesRegex(ValueError, "rank exceeds"),
                    ):
                        ledger.append(representation, state["head"])
                    self.assertEqual(ledger.state(), state)

    def test_coercible_types_and_shapes_rejected_before_admission(self):
        contract, _, _, _ = fixture()
        packet = make_packet(
            contract,
            "zero",
            digest("zero"),
            [digest("zero-row")],
            np.zeros((1, 5)),
            np.zeros((1, 2)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            ledger = StatisticsLedger(Path(tmp) / "ledger.db", contract)
            state = ledger.state()
            for field in ("gram", "rhs", "yty"):
                for value in ("0.0", 0, False, None):
                    changed = copy.deepcopy(packet)
                    changed["body"][field][0][0] = value
                    changed["payload_sha256"] = digest(changed["body"])
                    with (
                        self.subTest(field=field, value=repr(value)),
                        self.assertRaisesRegex(ValueError, "plain finite float"),
                    ):
                        ledger.append(changed, state["head"])
                    self.assertEqual(ledger.state(), state)
                for value in ([], (), tuple(packet["body"][field])):
                    changed = copy.deepcopy(packet)
                    changed["body"][field] = value
                    changed["payload_sha256"] = digest(changed["body"])
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        ledger.append(changed, state["head"])
                    self.assertEqual(ledger.state(), state)
            self.assertEqual(ledger.append(packet, state["head"])["status"], "accepted")
            np.testing.assert_array_equal(
                ledger.snapshot()["candidate"]["weight"], np.zeros((5, 2))
            )

    def test_actual_low_rank_statistics_preserve_float_bytes(self):
        contract, _, _, _ = fixture()
        rng = np.random.default_rng(19073)
        for count in (1, 2, 3, 7, 13):
            x, y = rng.normal(size=(count, 5)), rng.normal(size=(count, 2))
            for scale in (1e-100, 1.0, 1e150):
                packet = make_packet(
                    contract,
                    f"real-{count}",
                    digest(["real", count, scale]),
                    [digest([count, row]) for row in range(count)],
                    x * scale,
                    y * scale,
                )
                with (
                    self.subTest(count=count, scale=scale),
                    np.errstate(over="raise", invalid="raise"),
                ):
                    g, h, t = validate_packet(packet, contract)
                np.testing.assert_array_equal(g, (x * scale).T @ (x * scale))
                np.testing.assert_array_equal(h, (x * scale).T @ (y * scale))
                np.testing.assert_array_equal(t, (y * scale).T @ (y * scale))
                self.assertEqual(
                    decode_packet(encode_packet(packet, contract), contract), packet
                )

    def test_concurrent_duplicate_and_competing_head(self):
        contract, packets, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = StatisticsLedger(root / "ledger.db", contract)
            initial = ledger.state()["head"]
            duplicates = launch(root, contract, [packets[0]] * 8, initial)
            self.assertEqual(duplicates["exits"], [0] * 8)
            self.assertCountEqual(
                [r["status"] for r in duplicates["receipts"]],
                ["accepted"] + ["idempotent"] * 7,
            )
            raced = launch(root, contract, packets[1:], ledger.state()["head"])
            self.assertEqual(raced["exits"], [0, 0])
            self.assertCountEqual(
                [r["status"] for r in raced["receipts"]], ["accepted", "rejected"]
            )
            for packet in packets[1:]:
                ledger.append(packet, ledger.state()["head"])
            self.assertEqual(ledger.state()["revision"], 3)

    def test_crash_before_and_after_commit(self):
        contract, packets, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = StatisticsLedger(root / "ledger.db", contract)
            initial = ledger.state()
            self.assertEqual(
                launch(root, contract, packets[:1], initial["head"], "before_commit")[
                    "exits"
                ],
                [41],
            )
            self.assertEqual(
                StatisticsLedger(root / "ledger.db", contract).state(), initial
            )
            self.assertEqual(
                launch(root, contract, packets[:1], initial["head"], "after_commit")[
                    "exits"
                ],
                [42],
            )
            resumed = StatisticsLedger(root / "ledger.db", contract)
            self.assertEqual(
                resumed.append(packets[0], initial["head"])["status"], "idempotent"
            )
            self.assertEqual(resumed.state()["revision"], 1)

    def test_rejections_leave_state_unchanged(self):
        contract, packets, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = StatisticsLedger(Path(tmp) / "ledger.db", contract)
            initial = ledger.state()["head"]
            ledger.append(packets[0], initial)
            state = ledger.state()
            changes = [
                ("source_sha256", digest("different bytes")),
                ("batch_id", "overlapping-samples"),
                ("count", True),
                ("count", 4),
                ("contract_sha256", digest("old epoch")),
            ]
            for key, value in changes:
                changed = copy.deepcopy(packets[0])
                changed["body"][key] = value
                changed["payload_sha256"] = digest(changed["body"])
                with self.assertRaises(ValueError):
                    ledger.append(changed, state["head"])
                self.assertEqual(ledger.state(), state)
            for key in (*DIGEST_FIELDS, "epoch", "regularizer"):
                changed = copy.deepcopy(contract)
                changed[key] = (
                    digest(["changed", key])
                    if key in DIGEST_FIELDS
                    else contract[key] + 1
                )
                with self.assertRaises(ValueError):
                    StatisticsLedger(ledger.path, changed)
            with self.assertRaisesRegex(ValueError, "stale expected head"):
                ledger.append(packets[1], initial)
            changed = copy.deepcopy(packets[1])
            changed["payload_sha256"] = digest("corrupted payload identity")
            with self.assertRaises(ValueError):
                ledger.append(changed, state["head"])
            for key, index, value in (
                ("gram", (0, 0), -1e9),
                ("gram", (0, 1), 1e9),
                ("rhs", (0, 0), 1e9),
                ("yty", (0, 0), -1e9),
            ):
                changed = copy.deepcopy(packets[1])
                changed["body"][key][index[0]][index[1]] = value
                changed["payload_sha256"] = digest(changed["body"])
                with self.assertRaises(ValueError):
                    ledger.append(changed, state["head"])
            changed = copy.deepcopy(packets[1])
            changed["body"]["gram"][0][0] = float("inf")
            with self.assertRaises(ValueError):
                ledger.append(changed, state["head"])
            with self.assertRaises(ValueError):
                StatisticsLedger(
                    Path(tmp) / "invalid.db", dict(contract, regularizer=-0.2)
                )
            self.assertEqual(ledger.state(), state)

    def test_order_restart_and_independent_augmented_least_squares(self):
        contract, packets, x, y = fixture()
        reference = np.linalg.lstsq(
            np.vstack((x, np.sqrt(0.2) * np.eye(5))),
            np.vstack((y, np.zeros((5, 2)))),
            rcond=None,
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            results = []
            for i, order in enumerate((packets, list(reversed(packets)))):
                ledger = StatisticsLedger(Path(tmp) / f"ledger-{i}.db", contract)
                for packet in order:
                    ledger.append(packet, ledger.state()["head"])
                candidate = StatisticsLedger(ledger.path, contract).snapshot()[
                    "candidate"
                ]
                np.testing.assert_allclose(
                    candidate["weight"], reference, rtol=1e-7, atol=1e-7
                )
                results.append(candidate)
            self.assertEqual(results[0], results[1])
            RECORDS.append(
                dict(
                    check="order_restart_pooled",
                    candidate=results[0],
                    max_weight_error=float(
                        np.max(np.abs(np.asarray(results[0]["weight"]) - reference))
                    ),
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(LedgerTests)
    )
    args.output.write_text(
        json.dumps(
            dict(
                schema="pft-online-tests-v1",
                pid=os.getpid(),
                tests=result.testsRun,
                failures=len(result.failures),
                errors=len(result.errors),
                records=RECORDS,
            ),
            indent=2,
        )
        + "\n"
    )
    raise SystemExit(0 if result.wasSuccessful() else 1)
