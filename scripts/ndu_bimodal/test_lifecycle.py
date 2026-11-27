"""Protocol tests only: manufactured evidence is not qualification evidence."""

import tempfile
from pathlib import Path
import unittest

from ndu_bimodal.lifecycle import (
    CheckpointStore,
    CostLedger,
    KINDS,
    Limits,
    Packet,
    PacketInbox,
    Prices,
    digest,
    no_update_gate,
)


class Clock:
    def __init__(self):
        self.wall = 0.0
        self.cpu = 0.0

    def advance(self, seconds, cpu=0.0):
        self.wall += seconds
        self.cpu += cpu

    def now(self):
        return self.wall

    def cpu_now(self):
        return self.cpu

    def ns(self):
        return int(self.wall * 1_000_000_000)


def protocol_evidence(candidate):
    # Manufactured input tests pointer transitions, not a scientific claim.
    return dict(
        kind="prospective_measured",
        fixture=False,
        synthetic=False,
        candidate_sha256=candidate,
        evidence_sha256=digest(b"manufactured protocol test evidence"),
        net_gain_lcb=0.1,
        minimum_gain=0.01,
        retention_lcb=0.0,
        minimum_retention=-0.01,
        constraints_pass=True,
        parity_pass=True,
        future_sample_pass=True,
        unknown_rejection_pass=True,
    )


class LifecycleTests(unittest.TestCase):
    def ledger(self, clock, limits=None, priced=False):
        prices = (
            {
                kind: Prices(
                    wall_second=1.0,
                    cpu_second=2.0,
                    byte_second=0.01,
                    call=0.1,
                )
                for kind in KINDS
            }
            if priced
            else None
        )
        return CostLedger(
            limits or Limits(2048, 20, 30, 2, 1),
            prices,
            clock.now,
            clock.cpu_now,
        )

    def packet(self, data, arrival=3, deadline=10):
        return Packet(
            "input",
            "image",
            0,
            int(arrival * 1e9),
            int(deadline * 1e9),
            digest(data),
            len(data),
        )

    def test_future_bytes_require_read_after_arrival(self):
        clock, raw, loaded = Clock(), b"actual image bytes", []
        ledger = self.ledger(clock)

        def loader(packet_id, maximum):
            loaded.append((packet_id, maximum))
            return raw

        inbox = PacketInbox([self.packet(raw)], loader, ledger, clock.ns, clock.advance)
        with self.assertRaises(RuntimeError):
            inbox.read("input")
        self.assertEqual(loaded, [])
        self.assertEqual(ledger.calls, 0)
        self.assertFalse(inbox.wait("input", 1))
        self.assertEqual(loaded, [])
        self.assertTrue(inbox.wait("input", 2))
        self.assertEqual(loaded, [])
        self.assertEqual(inbox.read("input"), raw)
        self.assertEqual(inbox.read("input"), raw)
        self.assertEqual(ledger.calls, 2)
        self.assertEqual(ledger.resident, {"packet:input": len(raw)})
        with self.assertRaises(RuntimeError):
            inbox.wait("input", 1)
        with self.assertRaises(KeyError):
            inbox.read("undeclared")
        self.assertEqual(ledger.events[-1]["status"], "failed")

    def test_late_or_corrupted_reads_are_paid_and_not_retained(self):
        for late in (False, True):
            with self.subTest(late=late):
                clock, raw = Clock(), b"visible"
                ledger = self.ledger(clock)

                def loader(_packet_id, _maximum):
                    clock.advance(2 if late else 0.1)
                    return raw if late else b"invalid"

                inbox = PacketInbox(
                    [self.packet(raw, arrival=0, deadline=1)],
                    loader,
                    ledger,
                    clock.ns,
                    clock.advance,
                )
                with self.assertRaises(TimeoutError if late else ValueError):
                    inbox.read("input")
                self.assertEqual(ledger.calls, 1)
                self.assertEqual(ledger.resident, {})
                event = [e for e in ledger.events if e["kind"] == "observation"][-1]
                self.assertEqual(event["status"], "timeout" if late else "failed")

    def test_strict_public_packet_and_media_extension(self):
        raw = b"video segment"
        descriptor = self.packet(raw).public()
        descriptor["hidden_answer"] = "not visible"
        with self.assertRaises(ValueError):
            Packet.from_dict(descriptor)
        descriptor.pop("hidden_answer")
        descriptor.update(
            modality="video", media_clock="clip-1", media_time_ns=123, sync_group="av"
        )
        self.assertEqual(Packet.from_dict(descriptor).public(), descriptor)
        descriptor["media_clock"] = None
        with self.assertRaises(ValueError):
            Packet.from_dict(descriptor)

    def test_residency_recompute_reuse_are_paid_without_wall_double_count(self):
        clock = Clock()
        ledger = self.ledger(clock, priced=True)
        ledger.retain("candidate", 10)
        with ledger.operation("generate", calls=1):
            clock.advance(2, cpu=0.5)
        with ledger.operation("reuse"):
            clock.advance(3, cpu=0.25)
        ledger.release("candidate")
        with ledger.operation("recompute", calls=1):
            clock.advance(4, cpu=1)
        ledger.retain("replacement", 5)
        clock.advance(2)
        result = ledger.summary()
        self.assertEqual(
            {
                k: result[k]
                for k in (
                    "wall_seconds",
                    "cpu_seconds",
                    "byte_seconds",
                    "calls",
                    "elapsed_seconds",
                    "resident_bytes",
                )
            },
            dict(
                wall_seconds=9,
                cpu_seconds=1.75,
                byte_seconds=60,
                calls=2,
                elapsed_seconds=11,
                resident_bytes=5,
            ),
        )
        self.assertAlmostEqual(result["monetary"], 13.3)
        with self.assertRaises(RuntimeError):
            with ledger.operation("control"):
                with ledger.operation("reuse"):
                    pass

    def test_unknown_money_failures_and_finalization_reserve(self):
        clock = Clock()
        ledger = self.ledger(clock, Limits(5, 3, 10, 2, 1))
        with self.assertRaises(ValueError):
            with ledger.operation("generate", calls=2):
                clock.advance(1)
                raise ValueError("provider failed")
        self.assertEqual(ledger.calls, 2)
        self.assertIsNone(ledger.summary()["monetary"])
        with self.assertRaises(RuntimeError):
            with ledger.operation("generate", calls=1):
                self.fail("reserved call was spent")
        ledger.retain("a", 3)
        with self.assertRaises(RuntimeError):
            ledger.retain("b", 3)
        self.assertEqual(ledger.resident, {"a": 3})
        clock.advance(7)
        with self.assertRaises(TimeoutError):
            with ledger.operation("control"):
                self.fail("finalization time was spent")
        with ledger.operation("submit", calls=1, finalization=True):
            clock.advance(1)
        self.assertEqual(ledger.calls, 3)

    def test_overrun_is_charged_and_result_rejected(self):
        clock = Clock()
        ledger = self.ledger(clock, Limits(5, 2, 3, 1, 1))
        with self.assertRaises(TimeoutError):
            with ledger.operation("generate", calls=1):
                clock.advance(2.1, cpu=0.2)
        self.assertEqual(ledger.events[-1]["status"], "timeout")
        self.assertEqual(ledger.calls, 1)

    def test_gate_rejects_fixtures_negative_gain_and_missing_future(self):
        identity = digest(b"candidate")
        evidence = protocol_evidence(identity)
        self.assertEqual(no_update_gate(evidence, identity)["decision"], "activate")
        for changes in (
            {"fixture": True},
            {"synthetic": True},
            {"kind": "diagnostic"},
            {"future_sample_pass": False},
            {"net_gain_lcb": -0.05, "minimum_gain": -0.1},
        ):
            with self.subTest(changes=changes):
                changed = dict(evidence, **changes)
                self.assertEqual(
                    no_update_gate(changed, identity)["decision"], "no-update"
                )

    def test_checkpoint_cold_reload_and_real_cas_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "store"
            original = {
                "config.json": b'{"version":1}',
                "parameters/weights.bin": bytes(range(128)),
            }
            store = CheckpointStore(root)
            baseline = store.install(original, provenance="baseline")
            initial = store.initialize(baseline)
            candidate = store.install(
                {
                    "config.json": b'{"version":2}',
                    "parameters/weights.bin": bytes(reversed(range(128))),
                },
                provenance="measured",
            )
            store.stage(candidate)
            result = store.activate(
                protocol_evidence(candidate), initial["pointer_sha256"]
            )
            self.assertEqual(result["decision"], "activate")
            changed = result["pointer"]
            cold = CheckpointStore(root)
            self.assertNotEqual(cold.load(candidate), original)
            restored = cold.rollback(baseline, changed["pointer_sha256"])
            reloaded = CheckpointStore(root)
            self.assertEqual(reloaded.load(reloaded.pointer()["active"]), original)
            self.assertEqual(restored["revision"], 2)
            self.assertNotEqual(restored["pointer_sha256"], initial["pointer_sha256"])
            with self.assertRaises(RuntimeError):
                reloaded.rollback(candidate, initial["pointer_sha256"])

    def test_fixture_candidate_cannot_change_pointer_and_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = CheckpointStore(Path(temporary) / "store")
            baseline = store.install({"model.bin": b"baseline"}, "baseline")
            initial = store.initialize(baseline)
            fixture = store.install({"model.bin": b"fixture"})
            store.stage(fixture)
            result = store.activate(
                protocol_evidence(fixture), initial["pointer_sha256"]
            )
            self.assertEqual(result["decision"], "no-update")
            self.assertEqual(store.pointer(), initial)
            payload = store.root / "objects" / baseline / "model.bin"
            payload.write_bytes(b"modified")
            with self.assertRaises(ValueError):
                store.load(baseline)
            with self.assertRaises(ValueError):
                store.install({"../outside.bin": b"x"})

    def test_complete_file_manifest_and_byte_only_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = CheckpointStore(Path(temporary) / "store")
            payload = b"\x80\x04N."
            identity = store.install({"opaque.pkl": payload})
            self.assertEqual(store.load(identity), {"opaque.pkl": payload})
            extra = store.root / "objects" / identity / "unlisted.bin"
            extra.write_bytes(b"not in manifest")
            with self.assertRaises(ValueError):
                store.load(identity)


if __name__ == "__main__":
    unittest.main()
