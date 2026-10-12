"""Opt-in tiny Qwen2/PEFT writer proof; no pretrained task result or test labels."""

from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

from experience_memory import ExperienceReader
from pretrained import frozen_digest
from test_source_composition_curriculum import event
from test_source_write_training import reader


class BindingWriterTests(unittest.TestCase):
    def test_real_adapter_update_charges_both_source_only_forwards(self):
        writer = reader()
        docs = (
            event("location", "service", "location", "site_a", scope="s"),
            event("version", "service", "version", "site_b", scope="s"),
        )
        with redirect_stdout(io.StringIO()), patch("experience_memory.STEPS", 4):
            receipt = writer.fit_sources(
                docs,
                revision=2,
                allowed_roots={d.root for d in docs},
                revoked=set(),
                binding_objective="source_margin",
                loss_backend="full",
            )
        self.assertEqual(receipt["binding_objective"], "source_margin")
        self.assertEqual(receipt["steps"], 4)
        self.assertEqual(receipt["binding_receipt"]["forward_token_charge_factor"], 2)
        self.assertEqual(len(receipt["binding_receipt"]["training_pairs"]), 2)
        self.assertEqual(
            receipt["input_tokens"],
            2 * receipt["write_schedule"]["planned_input_tokens"],
        )
        self.assertEqual(
            receipt["supervised_tokens"],
            2 * receipt["write_schedule"]["planned_supervised_tokens"],
        )
        self.assertEqual(
            receipt["actual_projection_positions"], receipt["input_tokens"]
        )
        self.assertLessEqual(receipt["input_tokens"], receipt["token_ceiling"])
        self.assertTrue(receipt["base_unchanged"])
        self.assertEqual(frozen_digest(writer.model), writer.base_digest)
        self.assertEqual(writer.roots, {d.root for d in docs})
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in writer.model.parameters()
            )
        )

    def test_zero_admitted_negative_fails_without_a_fake_null(self):
        writer = reader()
        docs = (event("single", "service", "location", "site_a", scope="s"),)
        with self.assertRaises(ValueError):
            writer.fit_sources(
                docs,
                revision=2,
                allowed_roots={d.root for d in docs},
                revoked=set(),
                binding_objective="source_margin",
                loss_backend="full",
            )
        self.assertEqual(writer.roots, set())

    def test_unsupported_loss_or_two_hop_pairing_rejected_before_update(self):
        writer = reader()
        docs = (event("single", "service", "location", "site_a", scope="s"),)
        for backend, curriculum in (
            ("supervised_positions", "single_hop"),
            ("full", "source_two_hop"),
        ):
            with self.subTest(backend=backend, curriculum=curriculum):
                with self.assertRaises(ValueError):
                    writer.fit_sources(
                        docs,
                        revision=2,
                        allowed_roots={d.root for d in docs},
                        revoked=set(),
                        binding_objective="source_margin",
                        loss_backend=backend,
                        curriculum=curriculum,
                    )
        self.assertEqual(writer.roots, set())


if __name__ == "__main__":
    unittest.main()
