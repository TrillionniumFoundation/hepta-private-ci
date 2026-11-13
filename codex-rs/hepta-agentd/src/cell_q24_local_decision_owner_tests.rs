//! Finite policy/coordinator semantics over synthetic learning evidence.
//! These tests neither construct a Root factory nor qualify Selector custody.

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::config;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::neuron_generation_update_bootstrap::learning_test_decision;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;

fn qualified() -> anyhow::Result<LearningIterationCoordinatorV1> {
    let f = Fixture::new(config()?)?;
    let old = learning_test_decision(&f, learning_test_baseline()?, "none")?;
    let mut next = LearningIterationCoordinatorV1::new(
        old.snapshot().request.clone(),
        old.snapshot().owners.clone(),
    )?;
    for original in &old.snapshot().receipts {
        let mut original = original.clone();
        if let LearningIterationObservationV1::Evaluation { disposition, .. } =
            &mut original.observation
        {
            *disposition = LearningEvaluationDispositionV1::Qualified;
        }
        original.predecessor = next.snapshot().head_digest;
        next.record(original.clone(), original.observed_unix_seconds)?;
    }
    let candidate = next
        .candidate()
        .ok_or_else(|| anyhow::anyhow!("fixture candidate"))?
        .digest()?;
    let proposal = learning_test_receipt(
        &next,
        LearningIterationObservationV1::Proposal {
            candidate_bundle: candidate,
            proposal_id: next.snapshot().request.operation_id.clone(),
            composition_digest: Digest32::of_bytes(b"synthetic policy proposal"),
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
    );
    next.record(proposal.clone(), proposal.observed_unix_seconds)?;
    Ok(next)
}

#[test]
fn finite_policy_retention_and_deferral_preserve_independent_qualification() -> anyhow::Result<()> {
    let original = qualified()?;
    let mut policies = std::collections::BTreeSet::new();
    for policy in [
        CellQ24LocalPolicyV1::AdoptQualified,
        CellQ24LocalPolicyV1::RetainCurrent,
        CellQ24LocalPolicyV1::DeferQualified,
    ] {
        let mut coordinator = original.clone();
        let receipt = decision(policy, coordinator.snapshot(), /*at*/ 21)?;
        let LearningIterationObservationV1::LocalDecisionV2(local) = &receipt.observation else {
            anyhow::bail!("local decision");
        };
        policies.insert(local.policy_digest.to_string());
        assert_eq!(local.proposal_head, original.snapshot().head_digest);
        assert_eq!(local.reason_digest, policy.reason());
        assert_eq!(local.disposition, policy.disposition());
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        assert_eq!(
            coordinator.next_stage(),
            Some(LearningIterationStageV1::Selection)
        );
        assert!(
            coordinator
                .snapshot()
                .receipts
                .iter()
                .any(|retained| matches!(
                    retained.observation,
                    LearningIterationObservationV1::Evaluation {
                        disposition: LearningEvaluationDispositionV1::Qualified,
                        ..
                    }
                ))
        );
        let selected = coordinator
            .next_task_bundle()
            .ok_or_else(|| anyhow::anyhow!("selected policy bundle"))?;
        match policy {
            CellQ24LocalPolicyV1::AdoptQualified => {
                assert_eq!(Some(selected), coordinator.candidate())
            }
            CellQ24LocalPolicyV1::RetainCurrent | CellQ24LocalPolicyV1::DeferQualified => {
                assert_eq!(selected, &original.snapshot().request.selected_bundle)
            }
        }
        // Exact replay is the coordinator's lost-ACK readback path. It must
        // preserve the complete checkpoint, while a replacement stays refused.
        let retained = coordinator.snapshot().clone();
        assert_eq!(
            coordinator.record(receipt.clone(), /*now_unix_seconds*/ 22)?,
            retained.head_digest
        );
        assert_eq!(coordinator.snapshot(), &retained);
        let mut substituted = receipt;
        substituted.evidence_digest = Digest32::of_bytes(b"substituted local decision evidence");
        assert!(
            coordinator
                .record(substituted, /*now_unix_seconds*/ 22)
                .is_err()
        );
        assert_eq!(coordinator.snapshot(), &retained);
    }
    assert_eq!(policies.len(), 3);
    Ok(())
}

#[test]
fn local_policy_cannot_convert_missing_proposal_or_expiry_into_a_decision() -> anyhow::Result<()> {
    let original = qualified()?;
    let mut cut = original.snapshot().clone();
    let proposal = cut
        .receipts
        .pop()
        .ok_or_else(|| anyhow::anyhow!("proposal"))?;
    cut.head_digest = proposal.predecessor;
    assert!(decision(CellQ24LocalPolicyV1::AdoptQualified, &cut, /*at*/ 21).is_err());
    assert!(
        decision(
            CellQ24LocalPolicyV1::RetainCurrent,
            original.snapshot(),
            original.snapshot().request.envelope.expiry_unix_seconds
        )
        .is_err()
    );
    Ok(())
}
