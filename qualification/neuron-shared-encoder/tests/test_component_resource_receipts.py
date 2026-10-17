from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.component_resource_receipts import (  # noqa: E402
    AGGREGATION_POLICY,
    COMPONENTS,
    ComponentReceiptError,
    ComponentResourceReceiptV1,
    ComponentUsageV1,
    DeviceReceiptV1,
    INCOMPLETE,
    REAL_MODEL_LOCAL_QUALIFICATION,
    REAL_SHADOW,
    SYNTHETIC_SMOKE,
    adapt_component_receipts,
)
from neuron_shared_encoder.prospective_plan import ResourceBudgetV1  # noqa: E402


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


BUDGET = digest("budget")
COST_WEIGHTS = digest("cost-weights")
MODEL = digest("model")
TOKENIZER = digest("tokenizer")
PREPROCESSOR = digest("preprocessor")
RUNTIME = digest("runtime")
SOURCE = digest("source")
SOURCE_BLOB = "a" * 40
DEVICE = digest("device")


def usage(component: str, *, device_digest: str = DEVICE, flops: float = 1.0) -> ComponentUsageV1:
    return ComponentUsageV1(
        component=component,
        component_digest=digest("component:" + component),
        device_digest=device_digest,
        forward_calls=8,
        input_tokens=10,
        flops=flops,
        peak_memory_bytes=2.0,
        p95_latency_ms=1.0,
        energy_mj=0.5,
        resident_params=100,
        active_params=50,
    )


def device(*, device_digest: str = DEVICE, runtime_digest: str = RUNTIME) -> DeviceReceiptV1:
    return DeviceReceiptV1(
        device_id="gpu.0",
        device_digest=device_digest,
        runtime_digest=runtime_digest,
        device_kind="cuda",
        precision="bf16",
        device_count=1,
        peak_memory_bytes=20.0,
        energy_mj=5.0,
    )


def receipt(
    *,
    candidate_id: str = "shared_head",
    evidence_class: str = REAL_SHADOW,
    components: tuple[ComponentUsageV1, ...] | None = None,
    device_value: DeviceReceiptV1 | None = None,
    status: str = "COMPLETE",
    missing_fields: tuple[str, ...] = (),
    device_missing: bool = False,
    **overrides,
) -> ComponentResourceReceiptV1:
    values = dict(
        receipt_id="receipt." + candidate_id,
        candidate_id=candidate_id,
        budget_digest=BUDGET,
        cost_weights_digest=COST_WEIGHTS,
        evidence_class=evidence_class,
        model_digest=MODEL,
        tokenizer_digest=TOKENIZER,
        preprocessor_digest=PREPROCESSOR,
        runtime_digest=RUNTIME,
        source_digest=SOURCE,
        source_blob_digest=SOURCE_BLOB,
        reader_forward_calls=8,
        charged_input_tokens=90,
        components=tuple(usage(component) for component in COMPONENTS) if components is None else components,
        device=None if device_missing else (device() if device_value is None else device_value),
        independent_new_source=True,
        model_input_gold_visible=False,
        status=status,
        missing_fields=missing_fields,
    )
    values.update(overrides)
    return ComponentResourceReceiptV1(**values)


class ComponentReceiptTests(unittest.TestCase):
    def test_complete_receipt_binds_all_components_device_and_digests(self):
        item = receipt()
        self.assertTrue(item.complete)
        self.assertEqual(set(item.components_by_name), set(COMPONENTS))
        self.assertEqual(item.charged_flops, 9.0)
        self.assertEqual(item.charged_peak_memory_bytes, 20.0)
        self.assertEqual(item.to_dict()["aggregation_policy"], AGGREGATION_POLICY)
        self.assertEqual(len(item.receipt_digest), 64)

    def test_component_device_or_runtime_drift_is_rejected(self):
        with self.assertRaises(ComponentReceiptError):
            receipt(components=tuple(usage(name, device_digest=digest("other")) for name in COMPONENTS))
        with self.assertRaises(ComponentReceiptError):
            receipt(device_value=device(runtime_digest=digest("other")))

    def test_duplicate_or_missing_component_is_fail_closed(self):
        duplicate = tuple(usage(name) for name in COMPONENTS[:-1]) + (usage("encoder"),)
        with self.assertRaises(ComponentReceiptError):
            receipt(components=duplicate)
        missing = tuple(usage(name) for name in COMPONENTS[:-1])
        item = receipt(components=missing, status="INCOMPLETE", evidence_class=INCOMPLETE, missing_fields=("components.verifier",))
        self.assertFalse(item.complete)
        with self.assertRaises(ComponentReceiptError):
            item.validate_against_budget(ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 100, 100, 100, 100, 100))

    def test_incomplete_receipt_requires_exact_missing_fields(self):
        fields = (
            "charged_input_tokens",
            "components.decoder",
            "components.verifier",
            "device",
            "model_digest",
            "reader_forward_calls",
            "runtime_digest",
            "source_blob_digest",
            "source_digest",
            "tokenizer_digest",
        )
        item = receipt(
            evidence_class=INCOMPLETE,
            status="INCOMPLETE",
            model_digest=None,
            runtime_digest=None,
            source_digest=None,
            source_blob_digest=None,
            tokenizer_digest=None,
            reader_forward_calls=None,
            charged_input_tokens=None,
            components=tuple(usage(name) for name in COMPONENTS if name not in {"decoder", "verifier"}),
            device_missing=True,
            missing_fields=fields,
        )
        self.assertFalse(item.complete)
        with self.assertRaises(ComponentReceiptError):
            item.validate_against_budget(ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 100, 100, 100, 100, 100))

    def test_complete_receipt_cannot_claim_incomplete_evidence(self):
        with self.assertRaises(ComponentReceiptError):
            receipt(evidence_class=INCOMPLETE)

    def test_local_qualification_is_preserved_but_not_promoted_to_shadow(self):
        item = receipt(
            evidence_class=REAL_MODEL_LOCAL_QUALIFICATION,
        )
        self.assertEqual(item.evidence_class, REAL_MODEL_LOCAL_QUALIFICATION)
        with self.assertRaises(ComponentReceiptError):
            item.to_resource_cost()
        with self.assertRaises(ComponentReceiptError):
            item.to_prospective_receipt(ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 1000, 1000, 1000, 1000, 1000), expected_forward_calls=8)

    def test_synthetic_receipt_is_not_adapted_to_strict_plan(self):
        item = receipt(evidence_class=SYNTHETIC_SMOKE)
        with self.assertRaises(ComponentReceiptError):
            item.to_resource_cost()

    def test_real_shadow_adapts_only_after_equal_budget_validation(self):
        budget = ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 1000, 1000, 1000, 1000, 1000)
        item = receipt()
        prospective = item.to_prospective_receipt(budget, expected_forward_calls=8)
        cost = item.to_resource_cost()
        self.assertEqual(prospective.forward_calls, 8)
        self.assertEqual(prospective.flops, 9.0)
        self.assertEqual(cost.encoder_flops, 3.0)
        self.assertEqual(cost.cell_flops, 4.0)
        self.assertEqual(cost.controller_flops, 1.0)
        self.assertEqual(cost.verification_flops, 1.0)

    def test_budget_digest_weights_and_each_dimension_are_bound(self):
        budget = ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 1000, 8.0, 1000, 1000, 1000)
        with self.assertRaises(ComponentReceiptError):
            receipt().validate_against_budget(budget, expected_forward_calls=8)
        bad_weight = ResourceBudgetV1(BUDGET, digest("different-weights"), 8, 1000, 1000, 1000, 1000, 1000)
        with self.assertRaises(ComponentReceiptError):
            receipt().validate_against_budget(bad_weight, expected_forward_calls=8)
        with self.assertRaises(ComponentReceiptError):
            receipt().validate_against_budget(ResourceBudgetV1(BUDGET, COST_WEIGHTS, 7, 1000, 1000, 1000, 1000, 1000), expected_forward_calls=8)

    def test_adapter_rejects_duplicate_or_missing_candidate_set(self):
        budget = ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 1000, 1000, 1000, 1000, 1000)
        with self.assertRaises(ComponentReceiptError):
            adapt_component_receipts((receipt(), receipt(candidate_id="shared_head")), budget, expected_candidate_ids=("shared_head",))
        with self.assertRaises(ComponentReceiptError):
            adapt_component_receipts((receipt(),), budget, expected_candidate_ids=("shared_head", "split_head"))

    def test_gold_visibility_and_source_identity_are_rejected(self):
        with self.assertRaises(ComponentReceiptError):
            receipt(model_input_gold_visible=True)
        with self.assertRaises(ComponentReceiptError):
            receipt(independent_new_source=False)
        with self.assertRaises(ComponentReceiptError):
            receipt(source_blob_digest="b" * 64)

    def test_component_dimensions_reject_nonfinite_and_negative_values(self):
        with self.assertRaises(ComponentReceiptError):
            usage("encoder", flops=float("nan"))
        with self.assertRaises(ComponentReceiptError):
            ComponentUsageV1("encoder", digest("x"), DEVICE, 8, 10, 1.0, 1.0, 1.0, 1.0, 10, 11)


if __name__ == "__main__":
    unittest.main()
