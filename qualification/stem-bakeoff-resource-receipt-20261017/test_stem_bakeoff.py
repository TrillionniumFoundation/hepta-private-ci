import unittest

from cell_fast_path_actionir import canonical_digest
from stem_bakeoff import StemBakeoffPolicyV1, StemEvaluationReceiptV1, select_stem_bakeoff


D, E, F, G, H = (x * 64 for x in "abcde")


def receipt(candidate, *, quality=900_000, memory=100, p99=100, energy=100, modalities=("audio", "text"), status="succeeded"):
    payload = {"candidate": candidate, "quality": quality, "memory": memory, "p99": p99, "energy": energy, "modalities": modalities, "status": status}
    return StemEvaluationReceiptV1(
        candidate_id=candidate,
        stem_digest=D,
        hidden_abi_digest=E,
        benchmark_digest=F,
        runtime_digest=G,
        modalities=modalities,
        parameter_count=100,
        weight_bytes=200,
        quality_lcb_milli=quality if status == "succeeded" else 0,
        calibration_error_ppm=10 if status == "succeeded" else 0,
        ood_coverage_ppm=800_000 if status == "succeeded" else 0,
        latency_p95_ns=(min(90, p99) if status == "succeeded" else 0),
        latency_p99_ns=p99 if status == "succeeded" else 0,
        observed_memory_bytes=memory if status == "succeeded" else 0,
        energy_nj=energy if status == "succeeded" else 0,
        deterministic=True,
        adapter_hooks=True,
        status=status,
        receipt_digest=canonical_digest(payload),
    )


def policy(**overrides):
    values = dict(
        benchmark_digest=F,
        required_modalities=("audio", "text"),
        min_quality_lcb_milli=850_000,
        max_calibration_error_ppm=20,
        min_ood_coverage_ppm=700_000,
        max_latency_p95_ns=100,
        max_latency_p99_ns=200,
        max_memory_bytes=200,
        max_energy_nj=200,
    )
    values.update(overrides)
    return StemBakeoffPolicyV1(**values)


class StemBakeoffTests(unittest.TestCase):
    def test_selects_deterministically_from_pareto_frontier(self):
        chosen = select_stem_bakeoff((receipt("compact", quality=900_000), receipt("fast", quality=880_000, memory=80, p99=70)), policy())
        self.assertEqual(chosen.selected_candidate_id, "compact")
        self.assertEqual(chosen.authority, "DENY_ALL")
        self.assertFalse(chosen.effect_admitted)

    def test_keeps_tradeoff_candidates_on_frontier(self):
        chosen = select_stem_bakeoff((receipt("quality", quality=950_000, memory=190), receipt("efficient", quality=860_000, memory=80)), policy())
        self.assertEqual(chosen.pareto_candidate_ids, ("efficient", "quality"))

    def test_hard_budget_and_modality_gates_fail_closed(self):
        chosen = select_stem_bakeoff((receipt("too-large", memory=201), receipt("missing-audio", modalities=("text",))), policy())
        self.assertIsNone(chosen.selected_candidate_id)
        self.assertEqual(chosen.reason_codes, ("NO_ELIGIBLE_STEM",))

    def test_non_success_receipts_carry_no_metrics(self):
        with self.assertRaises(ValueError):
            StemEvaluationReceiptV1(
                candidate_id="failed", stem_digest=D, hidden_abi_digest=E, benchmark_digest=F, runtime_digest=G,
                modalities=("audio", "text"), parameter_count=1, weight_bytes=1, quality_lcb_milli=1,
                calibration_error_ppm=0, ood_coverage_ppm=0, latency_p95_ns=0, latency_p99_ns=0,
                observed_memory_bytes=0, energy_nj=0, deterministic=True, adapter_hooks=True,
                status="failed", receipt_digest=H,
            )

    def test_receipt_digests_and_decision_digest_are_stable(self):
        values = (receipt("a"), receipt("b", quality=860_000))
        self.assertEqual(select_stem_bakeoff(values, policy()).decision_digest, select_stem_bakeoff(values, policy()).decision_digest)

    def test_authority_cannot_be_injected(self):
        with self.assertRaises(ValueError):
            StemEvaluationReceiptV1(
                candidate_id="bad", stem_digest=D, hidden_abi_digest=E, benchmark_digest=F, runtime_digest=G,
                modalities=("text",), parameter_count=1, weight_bytes=1, quality_lcb_milli=1,
                calibration_error_ppm=1, ood_coverage_ppm=1, latency_p95_ns=1, latency_p99_ns=1,
                observed_memory_bytes=1, energy_nj=1, deterministic=True, adapter_hooks=True,
                status="succeeded", receipt_digest=H, authority="OWNER",
            )
