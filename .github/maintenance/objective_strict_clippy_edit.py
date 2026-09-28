#!/usr/bin/env python3
"""Apply strict-lint repairs needed by the objective closure candidate.

This is a development-only, one-shot source edit. It never weakens lint policy,
changes product authority, or asserts qualification. The successful source
closure commit deletes this script before publishing.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Real indirection for the large enum variant; no clippy suppression.
replace_exact(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "    Ready(IntelligenceHostEnvelopeV1),\n",
    "    Ready(Box<IntelligenceHostEnvelopeV1>),\n",
)
replace_exact(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "    Ok(CanonicalRunOutcomeV1::Ready(IntelligenceHostEnvelopeV1 {\n",
    "    Ok(CanonicalRunOutcomeV1::Ready(Box::new(IntelligenceHostEnvelopeV1 {\n",
)
replace_exact(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "        authority: AuthorityPosture::DENY_ALL,\n    }))\n}\n\nfn run_stage",
    "        authority: AuthorityPosture::DENY_ALL,\n    })))\n}\n\nfn run_stage",
)
replace_exact(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            CanonicalRunOutcomeV1::Ready(envelope) => {\n                let mut oracle = FileBackedFreshnessOracleV1::new(\n",
    "            CanonicalRunOutcomeV1::Ready(envelope) => {\n                let envelope = *envelope;\n                let mut oracle = FileBackedFreshnessOracleV1::new(\n",
)

# Generated measurement tests no longer need the legacy encoder import.
replace_exact(
    "codex-rs/hepta-objective/src/objective_admission_tests.rs",
    "use crate::encode_objective_function_v1;\n",
    "",
)

# The performance example is an executable gate, so report fixture errors and
# exit nonzero instead of using expect()/unwrap() or suppressing strict lints.
example = "codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs"
replace_exact(
    example,
    "const MIN_THROUGHPUT_PER_SEC: f64 = 20.0;\n\nfn id(value: &str) -> StableId {\n    StableId::new(value).expect(\"id\")\n}\n",
    "const MIN_THROUGHPUT_PER_SEC: f64 = 20.0;\n\nfn required<T, E: std::fmt::Debug>(result: Result<T, E>, context: &str) -> T {\n    match result {\n        Ok(value) => value,\n        Err(error) => {\n            eprintln!(\"{context}: {error:?}\");\n            std::process::exit(2);\n        }\n    }\n}\n\nfn id(value: &str) -> StableId {\n    required(StableId::new(value), \"invalid stable id\")\n}\n",
)
replace_exact(
    example,
    "    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).expect(\"set\");\n",
    "    let candidate_set_digest = required(\n        canonical_candidate_set_digest_v1(&candidates),\n        \"candidate set digest\",\n    );\n",
)
replace_exact(
    example,
    "    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).expect(\"order\");\n",
    "    let canonical_order_digest = required(\n        canonical_candidate_order_digest_v1(&candidates),\n        \"candidate order digest\",\n    );\n",
)
replace_exact(
    example,
    "            candidate_count: u32::try_from(candidate_count).expect(\"bounded\"),\n",
    "            candidate_count: required(\n                u32::try_from(candidate_count),\n                \"candidate count conversion\",\n            ),\n",
)
replace_exact(
    example,
    "        scored_outputs_digest: canonical_scored_outputs_digest_v1(&request).expect(\"scores\"),\n",
    "        scored_outputs_digest: required(\n            canonical_scored_outputs_digest_v1(&request),\n            \"scored outputs digest\",\n        ),\n",
)
replace_exact(
    example,
    "    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {\n",
    "    let verifier = required(\n        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {\n",
)
replace_exact(
    example,
    "    })\n    .expect(\"verifier\");\n\n    let completeness_payload",
    "        }),\n        \"learning evidence verifier\",\n    );\n\n    let completeness_payload",
)
replace_exact(
    example,
    "    let completeness_payload =\n        canonical_completeness_evidence_payload_v1(&request).expect(\"complete\");\n",
    "    let completeness_payload = required(\n        canonical_completeness_evidence_payload_v1(&request),\n        \"completeness evidence payload\",\n    );\n",
)
replace_exact(
    example,
    "    let profile_payload = canonical_profile_qualification_payload_v1(&profile).expect(\"profile\");\n",
    "    let profile_payload = required(\n        canonical_profile_qualification_payload_v1(&profile),\n        \"profile qualification payload\",\n    );\n",
)
replace_exact(
    example,
    "    let runtime_payload =\n        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment)\n            .expect(\"runtime\");\n",
    "    let runtime_payload = required(\n        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment),\n        \"runtime commitment payload\",\n    );\n",
)
replace_exact(
    example,
    "            let _ = decide_authenticated_intuition_v2(\n",
    "            let _ = required(\n                decide_authenticated_intuition_v2(\n",
)
replace_exact(
    example,
    "            )\n            .expect(\"warmup\");\n",
    "                ),\n                \"authenticated warmup decision\",\n            );\n",
)
replace_exact(
    example,
    "            let receipt = decide_authenticated_intuition_v2(\n",
    "            let receipt = required(\n                decide_authenticated_intuition_v2(\n",
)
replace_exact(
    example,
    "            )\n            .expect(\"authenticated decision\");\n",
    "                ),\n                \"authenticated measured decision\",\n            );\n",
)

# Frozen qualification is a test target. Preserve hard failure semantics while
# making every parse/conversion/lookup failure explicit and contextual.
test = "codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs"
replace_exact(
    test,
    "fn id(value: &str) -> StableId {\n    StableId::new(value).unwrap()\n}\n",
    "fn required<T, E: std::fmt::Debug>(result: Result<T, E>, context: &str) -> T {\n    match result {\n        Ok(value) => value,\n        Err(error) => panic!(\"{context}: {error:?}\"),\n    }\n}\n\nfn present<T>(value: Option<T>, context: &str) -> T {\n    match value {\n        Some(value) => value,\n        None => panic!(\"{context}\"),\n    }\n}\n\nfn id(value: &str) -> StableId {\n    required(StableId::new(value), \"invalid stable id\")\n}\n",
)
replace_exact(
    test,
    "    ProbabilityQ32::from_raw(raw as u64).unwrap()\n",
    "    required(ProbabilityQ32::from_raw(raw as u64), \"probability ppm\")\n",
)
replace_exact(
    test,
    '''fn parse_model() -> LinearScorer {
    let text = std::str::from_utf8(MODEL_BYTES).unwrap();
    let get = |key: &str| -> i64 {
        let prefix = format!("{key}=");
        text.lines()
            .find_map(|line| line.strip_prefix(prefix.as_str()))
            .unwrap_or_else(|| panic!("missing {key}"))
            .parse()
            .unwrap()
    };
    assert!(text.contains("format=hepta.intuition.linear-scorer.v1"));
''',
    '''fn parse_model() -> LinearScorer {
    let text = required(std::str::from_utf8(MODEL_BYTES), "model utf8");
    let get = |key: &str| -> i64 {
        let prefix = format!("{key}=");
        let raw = present(
            text.lines()
                .find_map(|line| line.strip_prefix(prefix.as_str())),
            &format!("missing {key}"),
        );
        required(raw.parse(), &format!("invalid {key}"))
    };
    assert!(text.contains("format=hepta.intuition.linear-scorer.v1"));
''',
)
replace_exact(
    test,
    "        / u128::try_from(model.ood_scale_q16).unwrap())\n",
    "        / required(u128::try_from(model.ood_scale_q16), \"positive ood scale\"))\n",
)
replace_exact(
    test,
    "        utility: FixedQ32::from_raw(i64::try_from(utility_raw).unwrap()),\n",
    "        utility: FixedQ32::from_raw(required(\n            i64::try_from(utility_raw),\n            \"utility score range\",\n        )),\n",
)
for old, new in [
    ("        let x: i64 = fields[1].parse().unwrap();\n", "        let x: i64 = required(fields[1].parse(), \"calibration x\");\n"),
    ("        let y: i64 = fields[2].parse().unwrap();\n", "        let y: i64 = required(fields[2].parse(), \"calibration y\");\n"),
    ("        let label: u64 = fields[3].parse().unwrap();\n", "        let label: u64 = required(fields[3].parse(), \"calibration label\");\n"),
    ("        let bin = usize::try_from((prediction * 5 / 1_000_001).min(4)).unwrap();\n", "        let bin = required(\n            usize::try_from((prediction * 5 / 1_000_001).min(4)),\n            \"calibration bin\",\n        );\n"),
    ("        u32::try_from(weighted_error / u128::from(rows)).unwrap(),\n", "        required(\n            u32::try_from(weighted_error / u128::from(rows)),\n            \"calibration ECE range\",\n        ),\n"),
]:
    replace_exact(test, old, new)
replace_exact(
    test,
    "        let x: i64 = fields[1].parse().unwrap();\n        let y: i64 = fields[2].parse().unwrap();\n        let in_domain: u8 = fields[3].parse().unwrap();\n",
    "        let x: i64 = required(fields[1].parse(), \"OOD x\");\n        let y: i64 = required(fields[2].parse(), \"OOD y\");\n        let in_domain: u8 = required(fields[3].parse(), \"OOD domain label\");\n",
)
replace_exact(
    test,
    "    u32::try_from(false_accepts * 1_000_000 / ood_rows).unwrap()\n",
    "    required(\n        u32::try_from(false_accepts * 1_000_000 / ood_rows),\n        \"OOD false-acceptance range\",\n    )\n",
)
replace_exact(
    test,
    "    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).unwrap();\n",
    "    let candidate_set_digest = required(\n        canonical_candidate_set_digest_v1(&candidates),\n        \"candidate set digest\",\n    );\n",
)
replace_exact(
    test,
    "    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).unwrap();\n",
    "    let canonical_order_digest = required(\n        canonical_candidate_order_digest_v1(&candidates),\n        \"candidate order digest\",\n    );\n",
)
replace_exact(
    test,
    "    let model_text = std::str::from_utf8(MODEL_BYTES).unwrap();\n",
    "    let model_text = required(std::str::from_utf8(MODEL_BYTES), \"model utf8\");\n",
)
replace_exact(
    test,
    '''                model_text
                    .lines()
                    .find(|line| line.starts_with("feature_schema="))
                    .unwrap()
                    .as_bytes(),
''',
    '''                present(
                    model_text
                        .lines()
                        .find(|line| line.starts_with("feature_schema=")),
                    "missing feature schema",
                )
                .as_bytes(),
''',
)
replace_exact(
    test,
    '''                model_text
                    .lines()
                    .find(|line| line.starts_with("output_schema="))
                    .unwrap()
                    .as_bytes(),
''',
    '''                present(
                    model_text
                        .lines()
                        .find(|line| line.starts_with("output_schema=")),
                    "missing output schema",
                )
                .as_bytes(),
''',
)
replace_exact(
    test,
    '''                model_text
                    .lines()
                    .find(|line| line.starts_with("score_semantics="))
                    .unwrap()
                    .as_bytes(),
''',
    '''                present(
                    model_text
                        .lines()
                        .find(|line| line.starts_with("score_semantics=")),
                    "missing score semantics",
                )
                .as_bytes(),
''',
)
replace_exact(
    test,
    "    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {\n",
    "    let verifier = required(\n        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {\n",
)
replace_exact(
    test,
    "    })\n    .unwrap();\n    let scoring = ScoringCommitmentV1 {\n",
    "        }),\n        \"learning evidence verifier\",\n    );\n    let scoring = ScoringCommitmentV1 {\n",
)
replace_exact(
    test,
    "        scored_outputs_digest: canonical_scored_outputs_digest_v1(&request).unwrap(),\n",
    "        scored_outputs_digest: required(\n            canonical_scored_outputs_digest_v1(&request),\n            \"scored outputs digest\",\n        ),\n",
)
replace_exact(
    test,
    "    let completeness_payload = canonical_completeness_evidence_payload_v1(&request).unwrap();\n",
    "    let completeness_payload = required(\n        canonical_completeness_evidence_payload_v1(&request),\n        \"completeness evidence payload\",\n    );\n",
)
replace_exact(
    test,
    "    let profile_qualification_payload =\n        canonical_profile_qualification_payload_v1(&profile).unwrap();\n",
    "    let profile_qualification_payload = required(\n        canonical_profile_qualification_payload_v1(&profile),\n        \"profile qualification payload\",\n    );\n",
)
replace_exact(
    test,
    "    let runtime_payload =\n        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment).unwrap();\n",
    "    let runtime_payload = required(\n        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment),\n        \"runtime commitment payload\",\n    );\n",
)
replace_exact(
    test,
    "    let revoked_verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {\n",
    "    let revoked_verifier = required(\n        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {\n",
)
replace_exact(
    test,
    "    })\n    .unwrap();\n    let revoked_completeness_evidence = sign(\n",
    "        }),\n        \"revoked learning evidence verifier\",\n    );\n    let revoked_completeness_evidence = sign(\n",
)
replace_exact(
    test,
    '''    let receipt = decide_authenticated_intuition_v2(
        request,
        profile,
        scoring,
        assignment,
        IntuitionQualificationEvidenceV2 {
            completeness: &completeness_evidence,
            profile_qualification: &profile_qualification_evidence,
            runtime: &runtime_evidence,
        },
        &verifier,
        150,
    )
    .unwrap();
''',
    '''    let receipt = required(
        decide_authenticated_intuition_v2(
            request,
            profile,
            scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness_evidence,
                profile_qualification: &profile_qualification_evidence,
                runtime: &runtime_evidence,
            },
            &verifier,
            150,
        ),
        "authenticated frozen decision",
    );
''',
)

for path in (example, test):
    text = (ROOT / path).read_text(encoding="utf-8")
    if ".expect(" in text or ".unwrap()" in text or ".unwrap_or_else(" in text:
        raise RuntimeError(f"{path}: unchecked expect/unwrap remains")

print("objective_strict_clippy_edit.py: applied")
