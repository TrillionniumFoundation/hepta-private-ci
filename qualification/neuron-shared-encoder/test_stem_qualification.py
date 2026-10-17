#!/usr/bin/env python3
"""Protocol tests for real Stem qualification receipts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from neuron_shared_encoder.stem_qualification import (  # noqa: E402
    CheckpointRefV1,
    ComponentResourceBundleV1,
    ComponentResourceReceiptV1,
    MetricIntervalV1,
    SourceDisjointSplitV1,
    StemQualificationError,
    SCHEMA_COMPONENT,
    SCHEMA_RESOURCE,
    StemQualificationRunV1,
    qualify_from_receipt,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


CHECKPOINT = CheckpointRefV1(
    model_id="stem-421m",
    model_manifest_digest=digest("model-manifest"),
    weights_digest=digest("weights"),
    tokenizer_digest=digest("tokenizer"),
    preprocessor_digest=digest("preprocessor"),
    backend_id="torch",
    runtime_digest=digest("runtime"),
    device_identity_digest=digest("device"),
    checkpoint_digest=digest("checkpoint"),
    quantization_digest=digest("quantization"),
    stem_digest=digest("stem"),
    parameter_count=421_000_000,
    generation=0,
    quantization_id="bf16",
)

SPLIT = SourceDisjointSplitV1(
    train_source_digest=digest("train-source"),
    eval_source_digest=digest("eval-source"),
    train_manifest_digest=digest("train-manifest"),
    eval_manifest_digest=digest("eval-manifest"),
    future_source_digest=digest("future-source"),
    ood_source_digest=digest("ood-source"),
    future_manifest_digest=digest("future-manifest"),
    ood_manifest_digest=digest("ood-manifest"),
    split_manifest_digest=digest("split-manifest"),
    lineage_digest=digest("lineage"),
    dedupe_report_digest=digest("dedupe-report"),
    train_count=1000,
    eval_count=400,
    future_count=300,
    ood_count=250,
    overlap_count=0,
    source_family_count=2,
    future_window_count=2,
)


def metric(
    metric_id: str = "eval_quality",
    source_digest: str | None = None,
    sample_count: int = 400,
) -> MetricIntervalV1:
    return MetricIntervalV1(
        metric_id=metric_id,
        value=0.80,
        lcb=0.76,
        ucb=0.84,
        sample_count=sample_count,
        confidence_level=0.95,
        evaluator_digest=digest("evaluator"),
        heldout_source_digest=source_digest or SPLIT.eval_source_digest,
    )


QUALIFY_METRICS = (
    metric("eval_quality", SPLIT.eval_source_digest, 400),
    metric("future_quality", SPLIT.future_source_digest, 300),
    metric("ood_risk", SPLIT.ood_source_digest, 250),
)


def component(kind: str) -> ComponentResourceReceiptV1:
    is_device = kind == "device"
    return ComponentResourceReceiptV1(
        component_id=f"{kind}.run",
        component_kind=kind,
        artifact_digest=digest(f"{kind}.artifact"),
        measurement_digest=digest(f"{kind}.measurement"),
        forward_calls=0 if is_device else 100,
        input_tokens=0 if is_device else 1000,
        flops=0.0 if is_device else 1000.0,
        peak_memory_bytes=10000.0,
        p50_latency_ms=1.0,
        p95_latency_ms=2.0,
        p99_latency_ms=3.0,
        energy_mj=1.0,
        parameter_count=0 if is_device else 100,
    )


def bundle() -> ComponentResourceBundleV1:
    kinds = (
        "cell_head",
        "controller_decoder",
        "device",
        "modality_tower",
        "projector",
        "state_cache",
        "stem_encoder",
        "verification",
    )
    return ComponentResourceBundleV1(
        bundle_id="resources.run",
        benchmark_id="bench.v1",
        hardware_digest=CHECKPOINT.device_identity_digest,
        runtime_digest=CHECKPOINT.runtime_digest,
        measurement_digest=digest("measurement"),
        components=tuple(component(kind) for kind in kinds),
        p50_latency_ms=8.0,
        p95_latency_ms=16.0,
        p99_latency_ms=24.0,
        energy_mj=8.0,
        peak_memory_bytes=50000.0,
        batch_size=4,
        warmup_steps=2,
        measured_steps=10,
        repetitions=3,
        cache_hit_rate=0.5,
    )


def run() -> StemQualificationRunV1:
    return StemQualificationRunV1(
        run_id="run-421m-v1",
        candidate_id="stem-421m",
        task_id="task-1",
        stem_digest=CHECKPOINT.stem_digest,
        stem_generation=CHECKPOINT.generation,
        checkpoint=CHECKPOINT,
        source_split=SPLIT,
        registry_stem_digest=CHECKPOINT.stem_digest,
        registry_generation=CHECKPOINT.generation,
        tower_registry_digest=digest("tower-registry"),
        projector_registry_digest=digest("projector-registry"),
        objective_digest=digest("objective"),
        evaluation_plan_digest=digest("plan"),
        cases_digest=digest("cases"),
        budget_digest=digest("budget"),
        cost_profile_digest=digest("cost-profile"),
        evidence_manifest_digest=digest("evidence-manifest"),
        metrics=QUALIFY_METRICS,
        resources=bundle(),
    )


class StemQualificationTests(unittest.TestCase):
    def test_valid_run_is_deterministic_and_denied(self) -> None:
        first = run()
        second = run()
        self.assertEqual(first.run_digest, second.run_digest)
        self.assertEqual(first.to_dict()["authority"], "DENY_ALL")
        self.assertEqual(first.to_dict()["status"], "SHADOW_COMPLETE")
        self.assertEqual(first.to_dict()["task_id"], "task-1")
        self.assertEqual(first.resources.total_flops, 7000.0)
        self.assertEqual(first.resources.to_dict()["schema"], SCHEMA_RESOURCE)
        self.assertEqual(component("device").to_dict()["schema"], SCHEMA_COMPONENT)

    def test_metric_interval_must_contain_value(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(metric(), lcb=0.85)

    def test_source_overlap_is_rejected(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(SPLIT, overlap_count=1)

    def test_train_and_eval_source_must_differ(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(SPLIT, eval_source_digest=SPLIT.train_source_digest)

    def test_source_policy_requires_multiple_families_and_future_windows(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(SPLIT, source_family_count=1)
        with self.assertRaises(StemQualificationError):
            replace(SPLIT, future_window_count=1)

    def test_all_quality_cohorts_are_required(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(run(), metrics=(metric(),))

    def test_component_quantiles_must_be_ordered(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(component("device"), p95_latency_ms=0.5)

    def test_device_receipt_allows_zero_compute(self) -> None:
        self.assertEqual(component("device").flops, 0.0)
        self.assertEqual(component("device").parameter_count, 0)

    def test_component_bundle_requires_all_kinds(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(bundle(), components=bundle().components[:-1])

    def test_component_bundle_rejects_duplicate_kind(self) -> None:
        comps = bundle().components
        with self.assertRaises(StemQualificationError):
            replace(bundle(), components=comps[:-2] + (comps[-1], comps[-1]))

    def test_component_bundle_rejects_duplicate_id(self) -> None:
        comps = bundle().components
        duplicate = replace(comps[1], component_id=comps[0].component_id)
        with self.assertRaises(StemQualificationError):
            replace(bundle(), components=(comps[0], duplicate) + comps[2:])

    def test_synthetic_component_is_not_qualification_evidence(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(component("device"), evidence_class="SYNTHETIC_SMOKE")

    def test_incomplete_resource_is_rejected(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(component("device"), complete=False)

    def test_generation_mismatch_is_rejected(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(run(), stem_generation=1)

    def test_runtime_mismatch_is_rejected(self) -> None:
        bad = replace(bundle(), runtime_digest=digest("other-runtime"))
        with self.assertRaises(StemQualificationError):
            replace(run(), resources=bad)

    def test_gold_visibility_is_rejected(self) -> None:
        with self.assertRaises(StemQualificationError):
            replace(run(), model_input_gold_visible=True)

    def test_legacy_point_receipt_cannot_be_silently_promoted(self) -> None:
        legacy = SimpleNamespace(
            receipt_status="COMPLETE",
            evidence_class="REAL_SHADOW",
            independent_new_source=True,
            model_input_gold_visible=False,
            task_id="task-1",
            budget_digest=digest("budget"),
            model_digest=CHECKPOINT.checkpoint_digest,
            stem_digest=CHECKPOINT.stem_digest,
            source_digest=SPLIT.eval_source_digest,
        )
        result = qualify_from_receipt(
            legacy,
            run_id="run-upgrade",
            candidate_id="stem-421m",
            task_id="task-1",
            checkpoint=CHECKPOINT,
            source_split=SPLIT,
            expected_budget_digest=digest("budget"),
            expected_cases_digest=digest("cases"),
            expected_cost_profile_digest=digest("cost-profile"),
            registry_stem_digest=CHECKPOINT.stem_digest,
            registry_generation=CHECKPOINT.generation,
            tower_registry_digest=digest("tower-registry"),
            projector_registry_digest=digest("projector-registry"),
            objective_digest=digest("objective"),
            evaluation_plan_digest=digest("plan"),
            cases_digest=digest("cases"),
            budget_digest=digest("budget"),
            cost_profile_digest=digest("cost-profile"),
            evidence_manifest_digest=digest("evidence-manifest"),
            metrics=QUALIFY_METRICS,
            resources=bundle(),
        )
        self.assertEqual(result.candidate_id, "stem-421m")

    def test_adapter_rejects_mismatched_supplied_budget(self) -> None:
        legacy = SimpleNamespace(
            receipt_status="COMPLETE",
            evidence_class="REAL_SHADOW",
            independent_new_source=True,
            model_input_gold_visible=False,
            task_id="task-1",
            budget_digest=digest("budget"),
            model_digest=CHECKPOINT.checkpoint_digest,
            stem_digest=CHECKPOINT.stem_digest,
            source_digest=SPLIT.eval_source_digest,
        )
        with self.assertRaises(StemQualificationError):
            qualify_from_receipt(
                legacy,
                run_id="run-upgrade",
                candidate_id="stem-421m",
                task_id="task-1",
                checkpoint=CHECKPOINT,
                source_split=SPLIT,
                expected_budget_digest=digest("budget"),
                expected_cases_digest=digest("cases"),
                expected_cost_profile_digest=digest("cost-profile"),
                registry_stem_digest=CHECKPOINT.stem_digest,
                registry_generation=CHECKPOINT.generation,
                tower_registry_digest=digest("tower-registry"),
                projector_registry_digest=digest("projector-registry"),
                objective_digest=digest("objective"),
                evaluation_plan_digest=digest("plan"),
                cases_digest=digest("cases"),
                budget_digest=digest("other-budget"),
                cost_profile_digest=digest("cost-profile"),
                evidence_manifest_digest=digest("evidence-manifest"),
                metrics=QUALIFY_METRICS,
                resources=bundle(),
            )

    def test_incomplete_bridge_receipt_is_rejected(self) -> None:
        legacy = SimpleNamespace(
            receipt_status="INCOMPLETE",
            evidence_class="REAL_SHADOW",
            independent_new_source=True,
            model_input_gold_visible=False,
            stem_digest=CHECKPOINT.stem_digest,
            source_digest=SPLIT.eval_source_digest,
        )
        with self.assertRaises(StemQualificationError):
            qualify_from_receipt(
                legacy,
                run_id="run-upgrade",
                candidate_id="stem-421m",
                task_id="task-1",
                checkpoint=CHECKPOINT,
                source_split=SPLIT,
                expected_budget_digest=digest("budget"),
                expected_cases_digest=digest("cases"),
                expected_cost_profile_digest=digest("cost-profile"),
                registry_stem_digest=CHECKPOINT.stem_digest,
                registry_generation=CHECKPOINT.generation,
                tower_registry_digest=digest("tower-registry"),
                projector_registry_digest=digest("projector-registry"),
                objective_digest=digest("objective"),
                evaluation_plan_digest=digest("plan"),
                cases_digest=digest("cases"),
                budget_digest=digest("budget"),
                cost_profile_digest=digest("cost-profile"),
                evidence_manifest_digest=digest("evidence-manifest"),
                metrics=(metric(),),
                resources=bundle(),
            )


if __name__ == "__main__":
    unittest.main()
