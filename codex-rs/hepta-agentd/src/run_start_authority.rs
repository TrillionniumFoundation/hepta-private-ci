//! Sealed current-trust witness for durable Objective RunStart admission.
//!
//! A durable record is evidence of a past publication, not permission to start
//! work now. This module is the only constructor of `VerifiedRunStartV1`. It
//! re-reads the Fleet generation, AuthBus trust, signed body, expiry, objective
//! projection and exact owner fence before minting a single-use witness.

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIntelligenceAdmittedOutcomeV1;
use crate::AgentdState;
use crate::RunReceipt;
use crate::authbus_ingress;
use crate::objective_runtime::authentication_is_current;
use crate::state::objective_run_fence;

/// Non-cloneable proof that one exact durable RunStart was current at a named
/// Agentd owner boundary. All fields are private and construction is crate-
/// local to this module, so deserialization, request data and ordinary tests
/// cannot manufacture authority.
pub(crate) struct VerifiedRunStartV1<'a> {
    agentd: &'a AgentdState,
    record: &'a RunStartRecordV1,
    verified_at_ms: u64,
    current_generation: u64,
    proof_digest: Digest32,
}

impl std::fmt::Debug for VerifiedRunStartV1<'_> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("VerifiedRunStartV1")
            .field("run_id", &self.record.snapshot.run_id)
            .field("verified_at_ms", &self.verified_at_ms)
            .field("current_generation", &self.current_generation)
            .field("proof_digest", &self.proof_digest)
            .finish_non_exhaustive()
    }
}

impl<'a> VerifiedRunStartV1<'a> {
    pub(crate) fn record(&self) -> &'a RunStartRecordV1 {
        self.record
    }

    pub(crate) const fn verified_at_ms(&self) -> u64 {
        self.verified_at_ms
    }

    pub(crate) const fn current_generation(&self) -> u64 {
        self.current_generation
    }

    pub(crate) const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    /// Consume the old witness and re-observe every mutable trust domain. This
    /// is used after asynchronous owner preparation and immediately before a
    /// durable lifecycle mutation.
    pub(crate) fn reverify(self) -> Result<Self, AgentdError> {
        verify_current_run_start(self.agentd, self.record)
    }

    /// Compatibility admission remains available only through a fresh sealed
    /// witness. The state method performs its own final double-read as defense
    /// in depth; this call cannot turn the earlier check into a reusable token.
    pub(crate) fn admit_compatibility(self) -> Result<RunReceipt, AgentdError> {
        let record = self.record;
        let agentd = self.agentd;
        let expected_generation = self.current_generation;
        let expected_fence = record.snapshot.fence_digest.to_string();
        let receipt = agentd.start_current_run_start_record(record)?;
        if receipt.generation != expected_generation || receipt.fence_digest != expected_fence {
            return Err(AgentdError::GenerationFenced(
                "sealed RunStart changed identity during compatibility admission".to_string(),
            ));
        }
        Ok(receipt)
    }

    /// Enter the canonical seven-owner path through the same single-use proof.
    /// The canonical path revalidates after each asynchronous boundary and does
    /// not receive a constructor for this witness.
    pub(crate) async fn admit_canonical(
        self,
    ) -> Result<Option<AgentdIntelligenceAdmittedOutcomeV1>, AgentdError> {
        self.agentd.start_canonical_intelligence(self.record).await
    }
}

pub(crate) fn verify_current_run_start<'a>(
    agentd: &'a AgentdState,
    record: &'a RunStartRecordV1,
) -> Result<VerifiedRunStartV1<'a>, AgentdError> {
    authbus_ingress::require_ready(agentd)?;
    let now_ms = authbus_ingress::now_ms()?;
    let current_generation = agentd.current_generation()?;
    let expected_fence = objective_run_fence(agentd.identity(), current_generation);
    if record.snapshot.generation != current_generation
        || record.snapshot.fence_digest.to_string() != expected_fence
        || record.authentication.expires_at_ms <= now_ms
        || record.admission.deadline_unix_micros.div_ceil(1_000) <= now_ms
    {
        return Err(AgentdError::GenerationFenced(
            "durable RunStart generation, fence, authentication or deadline is not current"
                .to_string(),
        ));
    }

    let host = authbus_ingress::attached(agentd)?;
    let trust = host.trust(agentd)?;
    if !authentication_is_current(record, &trust, agentd.identity(), now_ms)? {
        return Err(AgentdError::Invalid(
            "durable RunStart authentication is not current".to_string(),
        ));
    }
    if let Some(owner) = agentd.objective_runtime.get() {
        owner.revalidate_projection(record, agentd.identity())?;
    }

    let proof_digest = proof_digest(record, current_generation, now_ms);
    Ok(VerifiedRunStartV1 {
        agentd,
        record,
        verified_at_ms: now_ms,
        current_generation,
        proof_digest,
    })
}

fn proof_digest(
    record: &RunStartRecordV1,
    current_generation: u64,
    verified_at_ms: u64,
) -> Digest32 {
    let mut bytes = b"hepta.runtime-agentd.verified-run-start.v1\0".to_vec();
    bytes.extend_from_slice(record.snapshot.run_id.as_str().as_bytes());
    bytes.extend_from_slice(record.snapshot.objective_digest.as_array());
    bytes.extend_from_slice(record.snapshot.fence_digest.as_array());
    bytes.extend_from_slice(record.authentication.signed_body_digest.as_array());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    bytes.extend_from_slice(&verified_at_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}
