//! Exact completed signatures under actual current Root trust. Historical
//! signature time comes only from the retained first Root acceptance. These
//! checks return data and never restore an execution or checkpoint owner.

use std::io;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;

use super::super::q24_evaluation::OriginalCompletedBDataV1;
use super::completed_journal::CompletedJournalObservation;
use super::completed_learning::OriginalCompletedLearningContextV1;
use super::completed_record::RootCompletedLearningAcceptanceDataV1;
use crate::learning_iteration_auth::OriginalReceiptVerificationV1;
use crate::learning_iteration_auth::independent_receipt_stages;
use crate::learning_owner_evidence;

pub(super) struct CompletedSignatures {
    pub(super) verified_at: u64,
    pub(super) journals: [String; 7],
    pub(super) signatures: [String; 7],
}

pub(super) fn verify_original_completions(
    context: &OriginalCompletedLearningContextV1<'_>,
    journals: &[CompletedJournalObservation],
    independent_b: &OriginalCompletedBDataV1,
    accepted: Option<&RootCompletedLearningAcceptanceDataV1>,
) -> io::Result<CompletedSignatures> {
    let fixed: [&CompletedJournalObservation; 7] =
        journals
            .iter()
            .collect::<Vec<_>>()
            .try_into()
            .map_err(|_| io::Error::other("all seven original completion journals required"))?;
    for (index, journal) in fixed.iter().enumerate() {
        if journal.records.len() != if index == 3 { 2 } else { 1 }
            || journal
                .records
                .iter()
                .any(|(_, state)| !matches!(state, ProductEvaluationExecutionStateV1::Completed(_)))
        {
            return Err(io::Error::other(
                "original completed journal has pending or extra work",
            ));
        }
    }
    let cuts: [String; 7] = fixed
        .iter()
        .map(|journal| journal.cut.data_digest().map(|d| d.to_string()))
        .collect::<io::Result<Vec<_>>>()?
        .try_into()
        .map_err(|_| io::Error::other("original completed cut count"))?;
    if let Some(fact) = accepted {
        if fact.journals != cuts || fact.independent_b != independent_b.acceptance.to_string() {
            return Err(io::Error::other("retained terminal physical cut differs"));
        }
    }
    let (_, freeze) = learning_owner_evidence::decode(completed(&fixed[0].records[0].1)?)
        .map_err(io::Error::other)?;
    context.require_current_freeze_signer(&freeze)?;
    let mut signatures = Vec::with_capacity(7);
    let mut used_training = None;
    for receipt in &context.terminal().receipts {
        let stage = receipt.observation.stage();
        if stage == LearningIterationStageV1::Proposal {
            continue;
        }
        let payload =
            learning_iteration_receipt_signing_bytes_v1(receipt).map_err(io::Error::other)?;
        let signed = if stage == LearningIterationStageV1::Evaluation {
            independent_b.evaluation_attestation.clone()
        } else {
            let index = match stage {
                LearningIterationStageV1::Experience => 1,
                LearningIterationStageV1::Dataset => 2,
                LearningIterationStageV1::Training => 3,
                LearningIterationStageV1::Selection if matches!(receipt.observation,
                    codex_hepta_learning_artifacts::LearningIterationObservationV1::LocalDecisionV2(_)) => 4,
                LearningIterationStageV1::Selection => 5,
                LearningIterationStageV1::NextUse => 6,
                _ => return Err(io::Error::other("original completed stage differs")),
            };
            let mut matches = Vec::new();
            for (_, state) in &fixed[index].records {
                let bytes = completed(state)?;
                let (saved, signed) =
                    learning_owner_evidence::decode(bytes).map_err(io::Error::other)?;
                if saved == payload {
                    matches.push((Digest32::of_bytes(bytes), signed));
                }
            }
            let [(digest, signed)] = matches.as_slice() else {
                return Err(io::Error::other(
                    "unique original stage completion required",
                ));
            };
            if index == 3 {
                used_training = Some(*digest);
            }
            signed.clone()
        };
        context.require_current_signer(&signed)?;
        signatures.push((receipt, signed));
    }
    if signatures.len() != 7 || context.terminal().training_no_update_v2().is_some() {
        return Err(io::Error::other(
            "seven actual evaluated terminal signatures required",
        ));
    }
    let actual_plan = fixed[3]
        .records
        .iter()
        .map(|(_, state)| completed(state).map(Digest32::of_bytes))
        .collect::<io::Result<Vec<_>>>()?;
    if actual_plan
        .iter()
        .filter(|digest| Some(**digest) != used_training)
        .copied()
        .collect::<Vec<_>>()
        != vec![independent_b.plan_attestation]
    {
        return Err(io::Error::other(
            "original Training journal and B plan signature differ",
        ));
    }
    let hashes: [String; 7] = signatures
        .iter()
        .map(|(receipt, signed)| {
            let payload =
                learning_iteration_receipt_signing_bytes_v1(receipt).map_err(io::Error::other)?;
            let bytes =
                learning_owner_evidence::encode(&payload, signed).map_err(io::Error::other)?;
            Ok(Digest32::of_bytes(&bytes).to_string())
        })
        .collect::<io::Result<Vec<_>>>()?
        .try_into()
        .map_err(|_| io::Error::other("original signature count"))?;
    if accepted.is_some_and(|fact| fact.signatures != hashes) {
        return Err(io::Error::other("retained original signatures changed"));
    }
    let verify_at = |at| -> io::Result<()> {
        let (payload, signed) = learning_owner_evidence::decode(completed(&fixed[0].records[0].1)?)
            .map_err(io::Error::other)?;
        codex_hepta_learning_ledger::LearningEvidenceVerifierV1::verify(
            context.current_verifier(),
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            &payload,
            at,
        )
        .map_err(io::Error::other)?;
        let mut verified = Vec::with_capacity(7);
        for (receipt, signed) in &signatures {
            let request = OriginalReceiptVerificationV1::new(
                context.current_verifier(),
                context.terminal(),
                receipt,
            )
            .map_err(io::Error::other)?;
            let current = OriginalReceiptVerificationV1::verify(&request, signed, at)
                .map_err(io::Error::other)?;
            for stage in independent_receipt_stages(context.terminal(), receipt) {
                let (_, prior) = verified
                    .iter()
                    .rev()
                    .find(|(observed, _)| observed == stage)
                    .ok_or_else(|| io::Error::other("original independent stage missing"))?;
                verify_signed_actor_separation(prior, &current, at).map_err(io::Error::other)?;
            }
            verified.push((receipt.observation.stage(), current));
        }
        Ok(())
    };
    let at = match accepted {
        Some(fact) => fact.root_verified_at_seconds,
        None => context.current_unix_seconds()?,
    };
    verify_at(at)?;
    let verified_at = if accepted.is_none() {
        let now = context.current_unix_seconds()?;
        verify_at(now)?;
        now
    } else {
        at
    };
    Ok(CompletedSignatures {
        verified_at,
        journals: cuts,
        signatures: hashes,
    })
}

fn completed(state: &ProductEvaluationExecutionStateV1) -> io::Result<&[u8]> {
    match state {
        ProductEvaluationExecutionStateV1::Completed(bytes) => Ok(bytes),
        _ => Err(io::Error::other("original journal is not completed")),
    }
}
