//! Data for one supervisor-authorized disclosure of an already configured task.
//! Generator authentication is not Source-read authority. Only the protected
//! Root registration and that task's actual custody authorize the fixed read.
//! No future RunStart, Decision, publication digest or freeze is an input.

use codex_hepta_learning_ledger::{LearningEvidenceRoleV1, LearningEvidenceVerifierV1,
    LedgerWriter, SignedLearningEvidenceV1, TrustedLearningSignerV1};
use codex_hepta_types::{Digest32, StableId};
use crate::{AgentdRootAuthorityPeer, CircuitTaskSourceInputV1, CircuitTaskSourcePublicationV1};
use super::{Error, wire};
use super::super::super::codec;

/// Pre-existing task, ledger, trust and recipient facts. This value is data,
/// not a read grant. The host must independently authorize its exact contents
/// through the protected supervisor; a submitted signature cannot select them.
pub struct OriginalCircuitPrefreezeSourceRequestV1 {
    pub generation_operation_id: String,
    pub generation_intent_digest: Digest32,
    pub task_digest: Digest32,
    pub source: CircuitTaskSourceInputV1,
    pub ledger_binding_digest: Digest32,
    pub evidence_trust_digest: Digest32,
    pub trust_distribution_digest: Digest32,
    pub trust_generation: u64,
    pub generator: TrustedLearningSignerV1,
    pub experience_signer: TrustedLearningSignerV1,
    pub dataset_signer: TrustedLearningSignerV1,
    pub consumer: AgentdRootAuthorityPeer,
    pub consumer_uid: u32,
    pub nonce: [u8; 16],
}

impl OriginalCircuitPrefreezeSourceRequestV1 {
    /// Canonical challenge for the existing Generator's signature. This pure
    /// encoder does not sign, register a reader, create a RunStart or read Source.
    /// The fixed input exists before A; its actual RunStart first arrives through
    /// the authenticated Root read and is never reconstructed from a digest.
    pub fn signing_payload(&self) -> Result<Vec<u8>, Error> {
        StableId::new(&self.generation_operation_id).map_err(|_| Error::InvalidBinding)?;
        if self.generation_intent_digest.is_zero() || self.task_digest.is_zero()
            || self.ledger_binding_digest.is_zero() || self.evidence_trust_digest.is_zero()
            || self.trust_distribution_digest.is_zero() || self.trust_generation == 0
            || self.consumer_uid == 0 || self.consumer.pid == 0
            || self.consumer.pid > i32::MAX as u32 || self.consumer.process_start_ticks == 0
            || self.nonce == [0; 16] || self.source.observation.len() > wire::BOUND
            || self.source.candidates.len() > 64
            || !(1..=3_600_000).contains(&self.source.lease_duration_ms)
        { return Err(Error::InvalidBinding); }
        let mut out = wire::Writer::new(b"hepta.circuit.prefreeze-source-disclosure.v1\0");
        out.text(&self.generation_operation_id)?;
        for digest in [self.generation_intent_digest, self.task_digest,
            self.ledger_binding_digest, self.evidence_trust_digest, self.trust_distribution_digest]
        { out.digest(digest)?; }
        out.u64(self.trust_generation)?;
        // Match the original source configuration codec's fixed placeholder.
        // It is not an executed operation or a fabricated admission.
        let input = self.source.input(StableId::new("circuit-source")
            .map_err(|_| Error::InvalidBinding)?);
        out.bytes(&codec::encode_input(&input)?)?;
        out.u64(self.source.lease_duration_ms)?;
        for signer in [&self.generator, &self.experience_signer, &self.dataset_signer] {
            out.id(&signer.principal.principal_id)?;
            out.id(&signer.controller_id)?;
            out.raw(&signer.verifying_key)?;
        }
        out.text(&self.consumer.boot_id)?;
        out.u32(self.consumer.pid)?;
        out.u64(self.consumer.process_start_ticks)?;
        out.u32(self.consumer_uid)?;
        out.raw(&self.nonce)?;
        let payload = out.finish();
        wire::bounded(&payload)?;
        Ok(payload)
    }

    pub(crate) fn require_evidence(
        &self, verifier: &LearningEvidenceVerifierV1, distribution: Digest32,
        generation: u64, evidence: &SignedLearningEvidenceV1, at: u64,
    ) -> Result<Digest32, Error> {
        if verifier.trust_digest() != self.evidence_trust_digest
            || distribution != self.trust_distribution_digest || generation != self.trust_generation
            || verifier.objective_digest() != self.source.objective_digest
        { return Err(Error::InvalidBinding); }
        for (role, signer) in [
            (LearningEvidenceRoleV1::Generator, &self.generator),
            (LearningEvidenceRoleV1::Observer, &self.experience_signer),
            (LearningEvidenceRoleV1::Observer, &self.dataset_signer),
        ] {
            verifier.require_signer_binding(role, signer, at).map_err(|_| Error::InvalidBinding)?;
        }
        let payload = self.signing_payload()?;
        let actual = verifier.verify(LearningEvidenceRoleV1::Generator, evidence, &payload, at)
            .map_err(|_| Error::InvalidBinding)?;
        if actual.principal() != &self.generator.principal
            || actual.controller_id() != &self.generator.controller_id
        { return Err(Error::InvalidBinding); }
        Ok(Digest32::of_parts(&[
            b"hepta.circuit.prefreeze-source-connection.v1\0", &payload,
            &evidence.signing_bytes(), &evidence.signature,
        ]))
    }

    pub(crate) fn require_ledger(
        &self, ledger: &LedgerWriter, evidence: &SignedLearningEvidenceV1, at: u64,
    ) -> Result<Digest32, Error> {
        if ledger.binding_digest() != self.ledger_binding_digest {
            return Err(Error::InvalidBinding);
        }
        self.require_evidence(ledger.verifier(), ledger.trust_distribution_digest(),
            ledger.trust_generation(), evidence, at)
    }

    pub(crate) fn require_publication(&self, observed: &CircuitTaskSourcePublicationV1)
        -> Result<(), Error>
    {
        let record = observed.original_record();
        let expected = self.source.input(observed.input().operation_id.clone());
        if observed.input() != &expected || record.snapshot.run_id != self.source.scope.run_id
            || record.snapshot.objective_digest != self.source.objective_digest
        { return Err(Error::InvalidBinding); }
        Ok(())
    }
}
