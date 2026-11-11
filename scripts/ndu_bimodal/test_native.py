"""Real Rust/Torch integration checks; JOINT_V4_NATIVE_BINARY is mandatory.

The fixtures train/reconstruct small generated colour cards. Passing these
tests is not evidence of semantic quality, NDU advantage or cloud qualification.
Replay, disk and accounting failures are injected; parity always invokes Rust.
"""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
import torch

from scripts.joint_generation_v4_io import framed_media, packet_bytes, read_packet
from scripts.ndu_bimodal.generator_training import colour_card, train
from scripts.ndu_bimodal import delivery
from scripts.ndu_bimodal.lifecycle import CostLedger, Limits
from scripts.ndu_bimodal.native import NativeSession, encode_input, load_generator, sha


class NativeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("JOINT_V4_NATIVE_BINARY")
        if not configured:
            raise RuntimeError(
                "Set JOINT_V4_NATIVE_BINARY to the real source-built binary"
            )
        cls.binary = Path(configured).resolve(strict=True)
        torch.set_num_threads(1)
        cls.baseline, cls.candidate, cls.training = train(seed=91, steps=3)

    def public(self, seed=310):
        _, image = colour_card(seed)
        return encode_input("describe colour", image)

    def session(self, **kwargs):
        return NativeSession(self.candidate, self.binary, self.public(), **kwargs)

    def ledger(self, max_calls=16):
        return CostLedger(
            Limits(
                max_candidate_bytes=8_000_000,
                max_calls=max_calls,
                max_seconds=90,
                finalization_seconds=5,
                finalization_calls=1,
            )
        )

    def test_actual_training_updates_content_and_cold_load_keeps_terminal_heads(self):
        before = load_generator(self.baseline).state_dict()
        model = load_generator(self.candidate)
        after = model.state_dict()
        changed = {key for key in before if not torch.equal(before[key], after[key])}
        self.assertNotEqual(self.baseline, self.candidate)
        self.assertEqual(model.export_weights(), self.candidate)
        self.assertTrue(any(key.startswith("core.") for key in changed))
        self.assertTrue(any("encoder" in key for key in changed))
        for key in before:
            if key.startswith(("critic.", "delivery_critic.", "actor.")):
                torch.testing.assert_close(before[key], after[key], rtol=0, atol=0)
        self.assertFalse(self.training["terminal_heads_trained"])
        self.assertFalse(self.training["old_actor_trained"])

    def test_ordinary_temporal_kernel_cold_packet_keeps_actual_native_parity(self):
        metadata, tensors = read_packet(self.candidate)
        metadata["mode"] = "ordinary"
        weights = packet_bytes(metadata, tensors)
        session = NativeSession(weights, self.binary, self.public())
        for modality in ("both", "text", "image"):
            session.repair(modality)
        result = session.finish()
        self.assertEqual(load_generator(weights).export_weights(), weights)
        self.assertLessEqual(result["state_max_abs_error"], 5e-10)
        self.assertTrue(all(row["status"] == "passed" for row in result["calls"]))

    def test_real_encoding_repair_and_terminal_byte_parity(self):
        session = self.session()
        for modality in ("both", "image", "text"):
            before = {
                name: output.detach().clone()
                for name, output in session.generator.outputs(session.state).items()
                if name in {"text", "image"}
            }
            receipt = session.repair(modality)
            after = session.generator.outputs(session.state)
            expected = {
                name: float((after[name] - value).abs().max())
                for name, value in before.items()
            }
            self.assertEqual(receipt["continuous_candidate_max_abs_change"], expected)
            self.assertTrue(receipt["continuous_candidate_changed"])
            self.assertFalse(receipt["quality_improvement_certified"])
            self.assertNotIn("content_changed", receipt)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            result = session.finish(submit=True, output=output)
            self.assertEqual(
                result["text_utf8"],
                (output / "generated.txt").read_bytes().decode("utf-8"),
            )
            self.assertEqual(
                result["image_sha256"], sha((output / "generated.ppm").read_bytes())
            )
            with Image.open(output / "generated.ppm") as image:
                image.load()
                self.assertEqual((image.size, image.mode), ((16, 16), "RGB"))
        cursors, media = framed_media(session.prefix)
        self.assertEqual(cursors, (16, 0, 0, 128))
        self.assertEqual(media[3].decode("utf-8"), result["text_utf8"])
        self.assertLessEqual(result["state_max_abs_error"], 5e-10)
        self.assertTrue(all(row["status"] == "passed" for row in result["calls"]))
        self.assertEqual(result["binary_sha256"], sha(self.binary.read_bytes()))
        self.assertIsNone(result["semantic_quality"])
        self.assertEqual(result["production_update"], "no-update")

    def test_read_replays_actual_calls_and_charges_sequential_events(self):
        ledger = self.ledger()
        session = self.session(ledger=ledger, wall_seconds=60)
        session.repair("text")
        session.repair("image")
        old_public = session.public_bytes
        receipts = session.read(self.public(711))
        self.assertEqual(len(receipts), 2)
        self.assertNotEqual(session.public_bytes, old_public)
        self.assertEqual(session.history, ["text", "image"])
        session.finish()
        summary = ledger.summary()
        calls = [event for event in summary["events"] if event["calls"]]
        self.assertEqual(
            [event["kind"] for event in calls],
            [
                "observation",
                "generate",
                "generate",
                "observation",
                "recompute",
                "recompute",
                "submit",
            ],
        )
        self.assertEqual(summary["calls"], len(session.calls))
        self.assertEqual(summary["calls"], 7)
        self.assertIsNone(summary["monetary"])
        self.assertTrue(all(event["status"] == "ok" for event in summary["events"]))

    def test_interrupted_local_delivery_reuses_actual_terminal_bytes_without_dispatch(
        self,
    ):
        session = self.session()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            original_write = delivery._write_once

            def fail_text(path, raw):
                if path.name == "generated.txt":
                    raise OSError("injected full disk")
                return original_write(path, raw)

            with patch.object(delivery, "_write_once", side_effect=fail_text):
                with self.assertRaises(OSError):
                    session.finish(submit=True, output=output)
            original = (
                session.native_state,
                session.prefix,
                len(session.calls),
                session.deadline,
            )
            self.assertTrue(session.closed)
            self.assertFalse((output / "delivery.json").exists())
            with patch.object(
                session, "_invoke", side_effect=AssertionError("no replay")
            ):
                result = session.finish(submit=True, output=output)
                self.assertEqual(
                    (
                        session.native_state,
                        session.prefix,
                        len(session.calls),
                        session.deadline,
                    ),
                    original,
                )
                with self.assertRaises(ValueError):
                    session.finish(submit=True, output=Path(temporary) / "substitution")
                session.deadline = time.monotonic() - 1
                self.assertEqual(session.finish(submit=True, output=output), result)
            self.assertEqual(
                delivery.read_delivery(
                    output, expected_identity=result["delivery"]["identity"]
                ),
                result,
            )

    def test_failed_publication_cannot_renew_expired_budget(self):
        session = self.session()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            with patch(
                "scripts.ndu_bimodal.native.commit_delivery",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaises(OSError):
                    session.finish(submit=True, output=output)
            spent = len(session.calls)
            session.deadline = time.monotonic() - 1
            with patch.object(
                session, "_invoke", side_effect=AssertionError("no replay")
            ):
                with self.assertRaises(TimeoutError):
                    session.finish(submit=True, output=output)
            self.assertEqual(len(session.calls), spent)
            self.assertFalse(output.exists())

    def test_late_terminal_control_closes_without_publication_or_redispatch(self):
        clock = [0.0]
        ledger = CostLedger(Limits(8_000_000, 16, 90, 5, 1), clock=lambda: clock[0])
        session = self.session(ledger=ledger)

        def decode_then_expire(prefix):
            decoded = framed_media(prefix)
            clock[0] = 91.0
            return decoded

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            with patch(
                "scripts.ndu_bimodal.native.framed_media",
                side_effect=decode_then_expire,
            ):
                with self.assertRaises(TimeoutError):
                    session.finish(submit=True, output=output)
            self.assertTrue(session.closed)
            self.assertIsNone(session._terminal_result)
            self.assertFalse(output.exists())
            self.assertEqual(ledger.events[-1]["status"], "timeout")
            spent = len(session.calls)
            with patch.object(
                session, "_invoke", side_effect=AssertionError("no replay")
            ):
                with self.assertRaisesRegex(RuntimeError, "cannot be redispatched"):
                    session.finish(submit=True, output=output)
            self.assertEqual(len(session.calls), spent)

    def test_late_postcommit_accounting_recovers_the_committed_original(self):
        clock = [0.0]
        ledger = CostLedger(Limits(8_000_000, 16, 90, 5, 1), clock=lambda: clock[0])
        session = self.session(ledger=ledger)

        def commit_then_expire(*args, **kwargs):
            result = delivery.commit_delivery(*args, **kwargs)
            clock[0] = 91.0
            return result

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            with patch(
                "scripts.ndu_bimodal.native.commit_delivery",
                side_effect=commit_then_expire,
            ):
                with self.assertRaises(TimeoutError):
                    session.finish(submit=True, output=output)
            original = (len(session.calls), len(ledger.events))
            with patch.object(
                session, "_invoke", side_effect=AssertionError("no replay")
            ):
                result = session.finish(submit=True, output=output)
            self.assertEqual((len(session.calls), len(ledger.events)), original)
            self.assertEqual(result["production_update"], "no-update")
            self.assertEqual(
                delivery.read_delivery(
                    output, expected_identity=result["delivery"]["identity"]
                ),
                result,
            )

    def test_late_publication_without_ledger_is_not_an_in_budget_success(self):
        session = self.session()

        def commit_then_expire(*args, **kwargs):
            result = delivery.commit_delivery(*args, **kwargs)
            session.deadline = time.monotonic() - 1
            return result

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            with patch(
                "scripts.ndu_bimodal.native.commit_delivery",
                side_effect=commit_then_expire,
            ):
                with self.assertRaises(TimeoutError):
                    session.finish(submit=True, output=output)
            spent = len(session.calls)
            with patch.object(
                session, "_invoke", side_effect=AssertionError("no replay")
            ):
                recovered = session.finish(submit=True, output=output)
            self.assertEqual(len(session.calls), spent)
            self.assertEqual(recovered["production_update"], "no-update")

    def test_public_tensors_are_snapshotted_before_native_state_binding(self):
        public = self.public()
        session = NativeSession(self.candidate, self.binary, public)
        bound = session.public_bytes
        public["image"].zero_()
        public["tokens"].zero_()
        self.assertEqual(session.public_bytes, bound)
        self.assertFalse(torch.equal(public["image"], session.public["image"]))
        session.repair("image")
        session.finish()

    def test_read_preflight_preserves_current_candidate_and_terminal_call(self):
        session = self.session(max_calls=4)
        session.repair("text")
        before = (session.native_state, session.public_bytes, tuple(session.history))
        with self.assertRaises(RuntimeError):
            session.read(self.public(712))
        self.assertEqual(
            (session.native_state, session.public_bytes, tuple(session.history)), before
        )
        self.assertEqual(len(session.calls), 2)
        result = session.finish()
        self.assertEqual(len(result["calls"]), 3)

    def test_failed_read_replay_restores_candidate_but_keeps_real_spend(self):
        session = self.session()
        session.repair("image")
        before = (session.native_state, session.public_bytes, tuple(session.history))
        with patch.object(
            session, "repair", side_effect=RuntimeError("injected replay failure")
        ):
            with self.assertRaises(RuntimeError):
                session.read(self.public(713))
        self.assertEqual(
            (session.native_state, session.public_bytes, tuple(session.history)), before
        )
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(session.calls[-1]["kind"], "observation")
        self.assertEqual(session.calls[-1]["status"], "passed")
        result = session.finish()
        self.assertEqual(len(result["calls"]), 4)

    def test_terminal_bytes_ignore_legacy_learned_terminal_and_action_heads(self):
        modified = load_generator(self.candidate)
        with torch.no_grad():
            for name, parameter in modified.named_parameters():
                if name.startswith(("critic.", "delivery_critic.", "actor.")):
                    parameter.fill_(7.0)
        sessions = [
            NativeSession(weights, self.binary, self.public())
            for weights in (self.candidate, modified.export_weights())
        ]
        for session in sessions:
            session.finish()
        self.assertEqual(sessions[0].prefix, sessions[1].prefix)

    def test_call_and_time_reserve_allow_only_finalization(self):
        call_limited = self.session(max_calls=2)
        with self.assertRaises(RuntimeError):
            call_limited.repair("image")
        result = call_limited.finish()
        self.assertEqual(len(result["calls"]), 2)
        time_limited = self.session(wall_seconds=60, reserve_seconds=10)
        # Tighten the owner's deadline while leaving ample actual STOP time.
        time_limited.deadline = time.monotonic() + 9
        with self.assertRaises(TimeoutError):
            time_limited.repair("image")
        self.assertEqual(len(time_limited.calls), 1)
        time_limited.finish()
        self.assertEqual(len(time_limited.calls), 2)

    def test_unknown_and_malformed_inputs_reject_before_native_dispatch(self):
        _, image = colour_card(410)
        for text, raw in (
            ("", image),
            ("hello", b"not-an-image"),
            ("hello", b"P6\n15 16\n255\n" + bytes(15 * 16 * 3)),
        ):
            with self.subTest(text=text, length=len(raw)):
                with self.assertRaises((ValueError, OSError)):
                    encode_input(text, raw)
        metadata, tensors = read_packet(self.candidate)
        metadata["mode"] = "unknown-core"
        with self.assertRaises(ValueError):
            load_generator(packet_bytes(metadata, tensors))
        ledger = self.ledger()
        unknown = self.public()
        unknown["private_target"] = torch.tensor([1.0])
        with self.assertRaises(ValueError):
            NativeSession(self.candidate, self.binary, unknown, ledger=ledger)
        self.assertEqual(ledger.calls, 0)
        invalid = self.public()
        invalid["image"][0, 0, 0, 0] = float("nan")
        with self.assertRaises(ValueError):
            NativeSession(self.candidate, self.binary, invalid)
        with self.assertRaises(ValueError):
            self.session(required_mask=True)


if __name__ == "__main__":
    unittest.main()
