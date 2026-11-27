#![cfg(target_os = "linux")]

use codex_hepta_agentd::OriginalCellQ24EvaluationTimingV1;
use codex_hepta_intelligence_eval::LongitudinalTimeEvidenceV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn into_evidence(
    value: OriginalCellQ24EvaluationTimingV1,
) -> Option<(LongitudinalTimeEvidenceV1, u64)> {
    match value {
        OriginalCellQ24EvaluationTimingV1::Qualification => None,
        OriginalCellQ24EvaluationTimingV1::SystemLongitudinal {
            timing,
            minimum_window_micros,
        } => Some((timing, minimum_window_micros)),
    }
}

#[test]
fn public_v1_timing_variants_construct_and_match_owned_evidence() -> anyhow::Result<()> {
    assert_eq!(
        into_evidence(OriginalCellQ24EvaluationTimingV1::Qualification),
        None
    );
    let evidence = LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: 25,
        windows: Vec::new(),
        observer: SignedLearningEvidenceV1 {
            evidence_id: StableId::new("evidence.one")?,
            principal_id: StableId::new("observer.one")?,
            role: LearningEvidenceRoleV1::Observer,
            trust_digest: Digest32::of_bytes(b"trust"),
            scope_digest: Digest32::of_bytes(b"scope"),
            objective_digest: Digest32::of_bytes(b"objective"),
            authority_epoch: 1,
            issued_at: 10,
            expires_at: 20,
            payload_digest: Digest32::of_bytes(b"payload"),
            signature: [7; 64],
        },
    };
    let value = OriginalCellQ24EvaluationTimingV1::SystemLongitudinal {
        timing: evidence.clone(),
        minimum_window_micros: 12,
    };
    assert_eq!(into_evidence(value), Some((evidence, 12)));
    Ok(())
}
