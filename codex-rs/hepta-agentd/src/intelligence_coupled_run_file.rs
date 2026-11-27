//! Evaluator-owned receipt file for a single ordinary RunStart. The host supplies
//! the file; the ordinary request never selects a path or a new writer.
use super::*;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::sync::Mutex;

const HEADER: &[u8; 8] = b"HEPTCFR1";
const MATERIAL_FIELDS: usize = 6;
// Six material hashes, two ID hashes, signed payload/credential hashes, the
// digest of the complete original durable journal record,
// the evaluator signature and the frame checksum.
const SIZE: usize = 8 + 11 * 32 + 64 + 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct VerifiedUse {
    pub readback: AgentdCoupledFieldReadbackV1,
    run_id: StableId,
    payload_digest: Digest32,
    credential_digest: Digest32,
    signature: [u8; 64],
}

impl VerifiedUse {
    pub(super) fn new(
        binding: &AgentdEvaluationBindingV1,
        readback: AgentdCoupledFieldReadbackV1,
        payload: &[u8],
        signed: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    ) -> Self {
        Self {
            readback,
            run_id: binding.run_id.clone(),
            payload_digest: Digest32::of_bytes(payload),
            credential_digest: Digest32::of_bytes(&signed.signing_bytes()),
            signature: signed.signature,
        }
    }

    fn bytes(
        &self,
        original: &RunStartRecordV1,
    ) -> Result<Vec<u8>, AgentdIntelligenceEvaluationError> {
        if original.snapshot.run_id != self.run_id {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        let mut bytes = Vec::with_capacity(SIZE);
        bytes.extend_from_slice(HEADER);
        for digest in [
            Digest32::of_bytes(self.run_id.as_str().as_bytes()),
            Digest32::of_bytes(self.readback.binding.candidate_id.as_str().as_bytes()),
        ]
        .into_iter()
        .chain(self.readback.digests())
        .chain([
            self.payload_digest,
            self.credential_digest,
            original
                .durable_record_digest_v1()
                .map_err(|_| AgentdIntelligenceEvaluationError::Binding)?,
        ]) {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.signature);
        let checksum = Digest32::of_bytes(&bytes);
        bytes.extend_from_slice(checksum.as_array());
        Ok(bytes)
    }
}

/// One host-enrolled run owns one preopened regular file. The provisioning
/// host is responsible for durably installing its directory entry. Exact retries may
/// finish an interrupted prefix. A complete different result cannot overwrite it.
pub struct AgentdCoupledFieldRunFileV1 {
    pub(super) run_id: StableId,
    file: Mutex<File>,
}

impl AgentdCoupledFieldRunFileV1 {
    pub fn open(run_id: StableId, file: File) -> Result<Self, AgentdIntelligenceEvaluationError> {
        use AgentdIntelligenceEvaluationError::Binding;
        let metadata = file.metadata().map_err(|_| Binding)?;
        if !metadata.is_file() || metadata.len() > SIZE as u64 {
            return Err(Binding);
        }
        file.try_lock().map_err(|_| Binding)?;
        Ok(Self {
            run_id,
            file: Mutex::new(file),
        })
    }

    pub(super) fn retain(
        &self,
        original: &RunStartRecordV1,
        selected: &VerifiedUse,
    ) -> Result<(), AgentdIntelligenceEvaluationError> {
        use AgentdIntelligenceEvaluationError::Binding;
        if self.run_id != selected.run_id {
            return Err(Binding);
        }
        let expected = selected.bytes(original)?;
        let mut file = self.file.try_lock().map_err(|_| Binding)?;
        file.seek(SeekFrom::Start(0)).map_err(|_| Binding)?;
        let mut existing = Vec::with_capacity(SIZE + 1);
        (&mut *file)
            .take((SIZE + 1) as u64)
            .read_to_end(&mut existing)
            .map_err(|_| Binding)?;
        if !expected.starts_with(&existing) {
            return Err(Binding);
        }
        file.write_all(&expected[existing.len()..])
            .and_then(|()| file.sync_all())
            .map_err(|_| Binding)
    }

    /// Cold-read a completed receipt using the independently retained original
    /// journal entry, the original signed task evaluation and the owner's trust.
    /// The time is the verifier's time for the requested evidence check.
    pub fn verify_retained(
        &self,
        original: &RunStartRecordV1,
        binding: &AgentdEvaluationBindingV1,
        signed: &AgentdSignedEvaluationV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<AgentdCoupledFieldReadbackV1, AgentdIntelligenceEvaluationError> {
        use AgentdIntelligenceEvaluationError::Binding;
        if self.run_id != binding.run_id
            || original.snapshot.run_id != self.run_id
            || original.snapshot.objective_digest != binding.objective_digest
            || signed.bundle.candidate_id != binding.selected_candidate_id
            || signed.bundle.objective_digest != binding.objective_digest
        {
            return Err(Binding);
        }
        let mut bytes = [0u8; SIZE];
        {
            let mut file = self.file.try_lock().map_err(|_| Binding)?;
            if file.metadata().map_err(|_| Binding)?.len() != SIZE as u64 {
                return Err(Binding);
            }
            file.seek(SeekFrom::Start(0))
                .and_then(|_| file.read_exact(&mut bytes))
                .map_err(|_| Binding)?;
        }
        let mut fields = [[0u8; 32]; MATERIAL_FIELDS];
        for (field, encoded) in fields
            .iter_mut()
            .zip(bytes[HEADER.len() + 2 * 32..].chunks_exact(32))
        {
            field.copy_from_slice(encoded);
        }
        let [
            registry_witness,
            qualification_digest,
            artifact_bytes_digest,
            evaluation_dataset_digest,
            plan_digest,
            holdout_use_digest,
        ] = fields.map(Digest32::from_array);
        let readback = AgentdCoupledFieldReadbackV1 {
            binding:
                codex_hepta_intelligence::coupled_field_admission::CoupledFieldCandidateBindingV1 {
                    candidate_id: binding.selected_candidate_id.clone(),
                    artifact_bytes_digest,
                    evaluation_dataset_digest,
                    plan_digest,
                    holdout_use_digest,
                },
            registry_witness,
            qualification_digest,
        };
        let payload = intelligence_coupled_field_use_payload_v1(
            binding,
            &signed.evidence,
            &readback,
            original.durable_record_digest_v1().map_err(|_| Binding)?,
        )?;
        let credential = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &signed.use_attestation,
                &payload,
                now,
            )
            .map_err(AgentdIntelligenceEvaluationError::Evidence)?;
        let decision = decide_with_signed_evidence_v2(
            signed.bundle.clone(),
            signed.roles.clone(),
            &signed.evidence,
            verifier,
            now,
        )
        .map_err(AgentdIntelligenceEvaluationError::Evaluation)?;
        if credential.principal() != &signed.bundle.evaluator
            || decision.decision.authority.grants_any()
            || decision.decision.disposition
                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(Binding);
        }
        let proof = VerifiedUse::new(binding, readback, &payload, &signed.use_attestation);
        if proof.bytes(original)? != bytes {
            return Err(Binding);
        }
        Ok(proof.readback)
    }
}
