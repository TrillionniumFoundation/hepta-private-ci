"""Negative tests for pinned checkpoint provenance."""

from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.checkpoint_receipt import (  # noqa: E402
    CheckpointReceiptError,
    INCOMPLETE,
    PinnedCheckpointReceiptV1,
    REAL_MODEL_LOCAL_QUALIFICATION,
    REAL_SHADOW,
    SYNTHETIC_SMOKE,
)
from neuron_shared_encoder.component_resource_receipts import (  # noqa: E402
    COMPONENTS,
    ComponentResourceReceiptV1,
    ComponentUsageV1,
    DeviceReceiptV1,
)


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def checkpoint(*, evidence_class: str = REAL_SHADOW, **overrides) -> PinnedCheckpointReceiptV1:
    values = dict(
        receipt_id="checkpoint.receipt.1",
        candidate_id="shared_head",
        task_id="reader.task.1",
        source_split="future",
        checkpoint_digest=digest("checkpoint"),
        model_digest=digest("model"),
        tokenizer_digest=digest("tokenizer"),
        preprocessor_digest=digest("preprocessor"),
        runtime_digest=digest("runtime"),
        reader_manifest_digest=digest("reader-manifest"),
        source_digest=digest("source"),
        source_blob_digest="a" * 40,
        request_digest=digest("request"),
        held_label_digest=digest("held-labels"),
        evidence_class=evidence_class,
        checkpoint_loaded=True,
        independent_new_source=True,
    )
    values.update(overrides)
    return PinnedCheckpointReceiptV1(**values)


class CheckpointReceiptTests(unittest.TestCase):
    def test_complete_real_shadow_is_pinned_and_denied_authority(self):
        item = checkpoint()
        self.assertTrue(item.complete)
        self.assertEqual(item.authority, "DENY_ALL")
        self.assertEqual(len(item.receipt_digest), 64)
        item.require_real_shadow()

    def test_real_local_qualification_is_preserved_and_rejected_by_strict_gate(self):
        item = checkpoint(evidence_class=REAL_MODEL_LOCAL_QUALIFICATION)
        self.assertEqual(item.evidence_class, REAL_MODEL_LOCAL_QUALIFICATION)
        with self.assertRaises(CheckpointReceiptError):
            item.require_real_shadow()

    def test_source_split_and_loaded_checkpoint_are_required_for_real(self):
        with self.assertRaises(CheckpointReceiptError):
            checkpoint(source_split="train")
        with self.assertRaises(CheckpointReceiptError):
            checkpoint(checkpoint_loaded=False)

    def test_missing_identity_is_exact_and_cannot_be_zero_filled(self):
        with self.assertRaises(CheckpointReceiptError):
            checkpoint(model_digest=None)
        item = checkpoint(
            evidence_class=INCOMPLETE,
            status="INCOMPLETE",
            model_digest=None,
            missing_fields=("model_digest",),
        )
        self.assertFalse(item.complete)
        with self.assertRaises(CheckpointReceiptError):
            item.require_real_shadow()

    def test_gold_and_mutation_are_rejected(self):
        with self.assertRaises(CheckpointReceiptError):
            checkpoint(model_input_gold_visible=True)
        with self.assertRaises(CheckpointReceiptError):
            checkpoint(current_run_mutation=True)

    def test_synthetic_protocol_fixture_cannot_be_adapted_to_real(self):
        item = checkpoint(evidence_class=SYNTHETIC_SMOKE)
        with self.assertRaises(CheckpointReceiptError):
            item.require_real_shadow()

    def test_component_receipt_identity_must_match(self):
        item = checkpoint()
        device = DeviceReceiptV1("gpu.0", digest("device"), digest("runtime"), "cuda", "bf16", 1, 1.0, 1.0)
        components = tuple(
            ComponentUsageV1(name, digest("component:" + name), device.device_digest, 1, 1, 1.0, 1.0, 1.0, 1.0, 2, 1)
            for name in COMPONENTS
        )
        resource = ComponentResourceReceiptV1(
            receipt_id="resource.receipt.1",
            candidate_id="shared_head",
            budget_digest=digest("budget"),
            cost_weights_digest=digest("cost-weights"),
            evidence_class=REAL_SHADOW,
            model_digest=item.model_digest,
            tokenizer_digest=item.tokenizer_digest,
            preprocessor_digest=item.preprocessor_digest,
            runtime_digest=item.runtime_digest,
            source_digest=item.source_digest,
            source_blob_digest=item.source_blob_digest,
            reader_forward_calls=1,
            charged_input_tokens=1,
            components=components,
            device=device,
            independent_new_source=True,
        )
        item.bind_identity(resource)
        with self.assertRaises(CheckpointReceiptError):
            item.bind_identity(type("Wrong", (), {**{name: digest("wrong:" + name) for name in ("model_digest", "tokenizer_digest", "preprocessor_digest", "runtime_digest", "source_digest", "source_blob_digest")}})())


if __name__ == "__main__":
    unittest.main()
