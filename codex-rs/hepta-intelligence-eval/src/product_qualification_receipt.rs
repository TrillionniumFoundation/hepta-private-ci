//! Integrity sealing for the mutable single-outcome product qualification header.
//!
//! The v4 evidence domain binds the complete signed decision, including its
//! disposition, identities and failed metrics. Prior v3 receipts do not satisfy
//! this seal, and downstream signatures over their evidence digest must be
//! reissued. Typed archive, attempt journal and publication formats are unchanged.
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationDispositionV1;
use crate::ProductEvaluationError;
use crate::SignedEvaluationDecisionV1;

use super::push_id;
use super::push_ids;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductQualificationReceiptV1 {
    pub temporal_execution_digest: Digest32,
    pub candidate_id: StableId,
    pub evaluator: AuthenticatedPrincipalV1,
    pub generator: AuthenticatedPrincipalV1,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub snapshot_ids: Vec<StableId>,
    pub claim_scope: EvaluationClaimScopeV1,
    pub decision: SignedEvaluationDecisionV1,
    pub publication_digest: Digest32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
    pub(super) receipt_seal: Digest32,
}

impl ProductQualificationReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), ProductEvaluationError> {
        if self.temporal_execution_digest.is_zero()
            || self.objective_digest.is_zero()
            || self.dataset_digest.is_zero()
            || self.publication_digest.is_zero()
            || self.decision.decision.evidence_digest.is_zero()
            || self.decision.trust_digest.is_zero()
            || self.decision.authentication_digest.is_zero()
            || self.snapshot_ids.is_empty()
            || self.authority.grants_any()
            || self.decision.decision.authority.grants_any()
            || self.decision.decision.candidate_id != self.candidate_id
        {
            return Err(ProductEvaluationError::Integrity("qualification receipt"));
        }
        let expected = product_qualification_evidence_digest(self);
        if self.evidence_digest != expected || self.receipt_seal != product_qualification_seal(self)
        {
            return Err(ProductEvaluationError::Integrity(
                "qualification receipt seal",
            ));
        }
        Ok(())
    }
}

pub(super) fn product_qualification_evidence_digest(
    receipt: &ProductQualificationReceiptV1,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-qualification.v4".to_vec();
    for digest in [
        receipt.temporal_execution_digest,
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.decision.decision.evidence_digest,
        receipt.decision.trust_digest,
        receipt.decision.authentication_digest,
        receipt.publication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let decision = &receipt.decision.decision;
    for id in [
        &decision.evaluation_id,
        &decision.candidate_id,
        &decision.baseline_id,
    ] {
        push_id(&mut bytes, id);
    }
    bytes.push(match decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        IndependentEvaluationDispositionV1::Ineligible => 1,
        IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    push_ids(&mut bytes, &decision.failed_metrics);
    push_id(&mut bytes, &receipt.candidate_id);
    push_principal(&mut bytes, &receipt.evaluator);
    push_principal(&mut bytes, &receipt.generator);
    bytes.push(match receipt.claim_scope {
        EvaluationClaimScopeV1::Qualification => 0,
        EvaluationClaimScopeV1::SystemLongitudinal => 1,
    });
    push_ids(&mut bytes, &receipt.snapshot_ids);
    bytes.push(u8::from(receipt.authority.grants_any()));
    bytes.push(u8::from(receipt.decision.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

pub(super) fn product_qualification_seal(receipt: &ProductQualificationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-qualification-receipt.v1".to_vec();
    bytes.extend_from_slice(product_qualification_evidence_digest(receipt).as_array());
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) {
    push_id(bytes, &principal.principal_id);
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    for value in [
        principal.authority_epoch,
        principal.authenticated_at,
        principal.expires_at,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}
