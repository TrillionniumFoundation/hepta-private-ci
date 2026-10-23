//! Verified, replayable publication material for the existing cognitive owner.
//!
//! No caller-supplied candidate/proof images or public keys are accepted here.
//! Every archive reconstructs the exact candidate and signed proof from its
//! source snapshot, policy, inputs and receipts against an installed manifest.

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::CompactionInputRecordV2;
use crate::CompactionPolicyV2;
use crate::CompactionQualificationV2;
use crate::CompactionSemanticPayloadV2;
use crate::CompactionTrustRoleV1;
use crate::QualifiedCandidateBuildRequestV1;
use crate::QualifiedCompactionCandidateV2;
use crate::SignedCompactionEvaluationReceiptV1;
use crate::SignedRetentionSelectionReceiptV1;
use crate::SignedSemanticGenerationReceiptV1;
use crate::TrustedCompactionEvaluatorV1;
use crate::TrustedCompactionProofRequestV1;
use crate::TrustedCompactionProofV1;
use crate::TrustedRetentionSelectorV1;
use crate::TrustedSemanticGeneratorV1;
use crate::TrustedTokenizerV1;
use crate::archive_codec::Decoder;
use crate::archive_codec::Encoder;
use crate::archive_codec::Wire;
use crate::archive_codec::WireError;
use crate::archive_codec::wire_struct;
use crate::compaction_input_manifest_digest;
use crate::trust_registry::CompactionAdmissionErrorV1;
use crate::trust_registry::CompactionTrustedPrincipalV1;
use crate::trust_registry::VerifiedCompactionTrustRegistryV1;

const ARCHIVE_DOMAIN: &[u8] = b"hepta.compaction.publication-archive.v1\0";
const REQUEST_DOMAIN: &[u8] = b"hepta.compaction.publication-request.v1\0";
const TOKEN_ACCOUNTING_DOMAIN: &[u8] = b"hepta.compaction.token-accounting-batch.v1\0";

/// Metadata and receipts are budgeted separately from semantic payload bytes.
/// The full archive may therefore carry the maximum payload plus bounded
/// source/proof metadata instead of silently reusing the payload ceiling.
pub const MAX_COMPACTION_ARCHIVE_METADATA_BYTES_V1: usize = 64 * 1024 * 1024;
pub const MAX_COMPACTION_FULL_ARCHIVE_BYTES_V1: usize =
    crate::MAX_QUALIFIED_COMPACTION_BYTES as usize + MAX_COMPACTION_ARCHIVE_METADATA_BYTES_V1;

/// A fresh tokenizer attestation over the entire request. Per-record immutable
/// token certificates remain useful for caching; this receipt additionally
/// binds their use to a key epoch, validity interval, purpose and unique nonce.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCompactionTokenAccountingV1 {
    pub schema_version: u32,
    pub key_id: StableId,
    pub trust_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub nonce: Digest32,
    pub source_snapshot_digest: Digest32,
    pub source_memory_snapshot_digest: Digest32,
    pub policy_digest: Digest32,
    pub input_manifest_digest: Digest32,
    pub payload_digest: Digest32,
    pub payload_tokenization_receipt_digest: Digest32,
    pub signature: [u8; 64],
}

wire_struct!(SignedCompactionTokenAccountingV1 {
    schema_version: u32, key_id: StableId, trust_epoch: u64,
    issued_at_unix_seconds: u64, expires_at_unix_seconds: u64, nonce: Digest32,
    source_snapshot_digest: Digest32, source_memory_snapshot_digest: Digest32,
    policy_digest: Digest32, input_manifest_digest: Digest32, payload_digest: Digest32,
    payload_tokenization_receipt_digest: Digest32, signature: [u8; 64]
});

impl SignedCompactionTokenAccountingV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, CompactionAdmissionErrorV1> {
        let mut output = Encoder::new(TOKEN_ACCOUNTING_DOMAIN)?;
        self.schema_version.write(&mut output)?;
        self.key_id.write(&mut output)?;
        self.trust_epoch.write(&mut output)?;
        self.issued_at_unix_seconds.write(&mut output)?;
        self.expires_at_unix_seconds.write(&mut output)?;
        self.nonce.write(&mut output)?;
        self.source_snapshot_digest.write(&mut output)?;
        self.source_memory_snapshot_digest.write(&mut output)?;
        self.policy_digest.write(&mut output)?;
        self.input_manifest_digest.write(&mut output)?;
        self.payload_digest.write(&mut output)?;
        self.payload_tokenization_receipt_digest.write(&mut output)?;
        Ok(output.finish())
    }

    pub fn receipt_digest(&self) -> Result<Digest32, CompactionAdmissionErrorV1> {
        let bytes = self.signing_bytes()?;
        Ok(Digest32::of_parts(&[&bytes, &self.signature]))
    }

    fn verify(
        &self,
        request: &CompactionPublicationRequestV1,
        principal: &CompactionTrustedPrincipalV1,
        now: u64,
    ) -> Result<(), CompactionAdmissionErrorV1> {
        let enrollment = &principal.enrollment;
        if self.schema_version != 1
            || self.nonce.is_zero()
            || self.key_id != enrollment.key_id
            || self.trust_epoch != enrollment.trust_epoch
            || self.issued_at_unix_seconds < enrollment.valid_from_unix_seconds
            || self.expires_at_unix_seconds > enrollment.valid_until_unix_seconds
            || self.issued_at_unix_seconds >= self.expires_at_unix_seconds
            || now < self.issued_at_unix_seconds
            || now >= self.expires_at_unix_seconds
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "token batch identity, epoch, nonce or validity",
            ));
        }
        if self.source_snapshot_digest != request.source_snapshot.vector_digest
            || self.source_memory_snapshot_digest
                != request.source_memory_snapshot.snapshot_digest
            || self.policy_digest != request.evidence.policy.digest()
            || self.input_manifest_digest
                != compaction_input_manifest_digest(&request.evidence.inputs)
            || self.payload_digest != request.evidence.semantic_payload.payload_digest
            || self.payload_tokenization_receipt_digest
                != request
                    .evidence
                    .semantic_payload
                    .tokenization_receipt
                    .receipt_digest()
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "token batch subject substitution",
            ));
        }
        let key = VerifyingKey::from_bytes(&enrollment.verifying_key)
            .map_err(|_| CompactionAdmissionErrorV1::Invalid("tokenizer key"))?;
        key.verify_strict(
            &self.signing_bytes()?,
            &Signature::from_bytes(&self.signature),
        )
        .map_err(|_| CompactionAdmissionErrorV1::Invalid("token batch signature"))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPublicationEvidenceV1 {
    pub policy: CompactionPolicyV2,
    pub semantic_payload: CompactionSemanticPayloadV2,
    pub inputs: Vec<CompactionInputRecordV2>,
    pub selection_receipt: SignedRetentionSelectionReceiptV1,
    pub generation_receipt: SignedSemanticGenerationReceiptV1,
    pub token_accounting_receipt: SignedCompactionTokenAccountingV1,
    pub qualification: CompactionQualificationV2,
    pub evaluation_receipt: SignedCompactionEvaluationReceiptV1,
}

wire_struct!(CompactionPublicationEvidenceV1 {
    policy: CompactionPolicyV2, semantic_payload: CompactionSemanticPayloadV2,
    inputs: Vec<CompactionInputRecordV2>, selection_receipt: SignedRetentionSelectionReceiptV1,
    generation_receipt: SignedSemanticGenerationReceiptV1,
    token_accounting_receipt: SignedCompactionTokenAccountingV1,
    qualification: CompactionQualificationV2, evaluation_receipt: SignedCompactionEvaluationReceiptV1
});

/// Source fields are filled from an opaque owner-acquired cut by the cognitive
/// coordinator. Standalone construction remains a non-authorizing proposal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPublicationRequestV1 {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub source_memory_snapshot: CognitiveSnapshot,
    pub generation: Generation,
    pub predecessor_checkpoint_digest: Option<Digest32>,
    pub evidence: CompactionPublicationEvidenceV1,
}

wire_struct!(CompactionPublicationRequestV1 {
    source_snapshot: CognitiveSnapshotKeyV1, source_memory_snapshot: CognitiveSnapshot,
    generation: Generation, predecessor_checkpoint_digest: Option<Digest32>,
    evidence: CompactionPublicationEvidenceV1
});

impl CompactionPublicationRequestV1 {
    fn canonicalize(&mut self) {
        self.source_memory_snapshot.records.sort_by(|a, b| {
            a.record_id
                .cmp(&b.record_id)
                .then_with(|| a.revision.cmp(&b.revision))
        });
        self.evidence.inputs.sort_by(|a, b| {
            a.record
                .record_id
                .cmp(&b.record.record_id)
                .then_with(|| a.record.revision.cmp(&b.record.revision))
                .then_with(|| a.digest().cmp(&b.digest()))
        });
        self.evidence.policy.protected_record_ids.sort();
    }

    /// Excludes semantic payload bytes while retaining their signed digest and
    /// accounting fields. This avoids cloning a potentially 64 MiB payload
    /// solely to clear it before request identity is encoded.
    pub fn request_digest(&self) -> Result<Digest32, CompactionAdmissionErrorV1> {
        let payload = &self.evidence.semantic_payload;
        if payload.payload.len() > crate::MAX_QUALIFIED_COMPACTION_BYTES as usize
            || Digest32::of_bytes(&payload.payload) != payload.payload_digest
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "payload byte integrity",
            ));
        }
        let mut metadata = Self {
            source_snapshot: self.source_snapshot.clone(),
            source_memory_snapshot: self.source_memory_snapshot.clone(),
            generation: self.generation,
            predecessor_checkpoint_digest: self.predecessor_checkpoint_digest,
            evidence: CompactionPublicationEvidenceV1 {
                policy: self.evidence.policy.clone(),
                semantic_payload: CompactionSemanticPayloadV2 {
                    source_snapshot_digest: payload.source_snapshot_digest,
                    source_memory_snapshot_digest: payload.source_memory_snapshot_digest,
                    payload_digest: payload.payload_digest,
                    payload: Vec::new(),
                    generator_implementation_digest: payload.generator_implementation_digest,
                    generator_receipt_digest: payload.generator_receipt_digest,
                    tokenizer_digest: payload.tokenizer_digest,
                    encoded_bytes: payload.encoded_bytes,
                    token_count: payload.token_count,
                    tokenization_receipt: payload.tokenization_receipt.clone(),
                },
                inputs: self.evidence.inputs.clone(),
                selection_receipt: self.evidence.selection_receipt.clone(),
                generation_receipt: self.evidence.generation_receipt.clone(),
                token_accounting_receipt: self.evidence.token_accounting_receipt.clone(),
                qualification: self.evidence.qualification.clone(),
                evaluation_receipt: self.evidence.evaluation_receipt.clone(),
            },
        };
        metadata.canonicalize();
        let mut output = Encoder::new(REQUEST_DOMAIN)?;
        metadata.write(&mut output)?;
        Ok(Digest32::of_bytes(&output.finish()))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionNonceBindingV1 {
    pub role: CompactionTrustRoleV1,
    pub key_id: StableId,
    pub trust_epoch: u64,
    pub nonce: Digest32,
    pub receipt_digest: Digest32,
}

/// Sealed verification result, not a writer capability. The durable owner must
/// still compare owner/root/manifest/source/deployment/lease in its transaction.
#[derive(Clone, Debug)]
pub struct VerifiedCompactionPublicationV1 {
    candidate: QualifiedCompactionCandidateV2,
    proof: TrustedCompactionProofV1,
    principals: [CompactionTrustedPrincipalV1; 4],
    nonce_bindings: [CompactionNonceBindingV1; 4],
    owner_id: StableId,
    root_key_digest: Digest32,
    registry_digest: Digest32,
    accepted_at_unix_seconds: u64,
    request_digest: Digest32,
    archive: Vec<u8>,
}

impl VerifiedCompactionPublicationV1 {
    pub fn verify(
        mut request: CompactionPublicationRequestV1,
        registry: &VerifiedCompactionTrustRegistryV1,
        accepted_at_unix_seconds: u64,
    ) -> Result<Self, CompactionAdmissionErrorV1> {
        registry.validate_current_at(accepted_at_unix_seconds)?;
        if request.evidence.inputs.len() > crate::MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(CompactionAdmissionErrorV1::Invalid("input record limit"));
        }
        request.canonicalize();
        let request_digest = request.request_digest()?;
        let evidence = &request.evidence;
        let selection = &evidence.selection_receipt;
        let generation = &evidence.generation_receipt;
        let evaluation = &evidence.evaluation_receipt;
        let selector = registry.resolve(
            CompactionTrustRoleV1::RetentionSelector,
            &selection.key_id,
            selection.trust_epoch,
            accepted_at_unix_seconds,
        )?;
        let generator = registry.resolve(
            CompactionTrustRoleV1::SemanticGenerator,
            &generation.key_id,
            generation.trust_epoch,
            accepted_at_unix_seconds,
        )?;
        let tokenizer = registry.resolve(
            CompactionTrustRoleV1::Tokenizer,
            &selection.tokenizer_key_id,
            selection.tokenizer_trust_epoch,
            accepted_at_unix_seconds,
        )?;
        let evaluator = registry.resolve(
            CompactionTrustRoleV1::Evaluator,
            &evaluation.key_id,
            evaluation.trust_epoch,
            accepted_at_unix_seconds,
        )?;
        if evaluator.principal_id == generator.principal_id
            || evaluator.principal_id == selector.principal_id
            || evaluator.enrollment.verifying_key == generator.enrollment.verifying_key
            || evaluator.enrollment.verifying_key == selector.enrollment.verifying_key
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "evaluator is not an independent registered principal",
            ));
        }
        if generator.artifact_digest != request.source_snapshot.vector.model_digest
            || tokenizer.artifact_digest != request.source_snapshot.vector.tokenizer_digest
            || evaluator.subject_id != evidence.qualification.evaluator_id
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "registered model, tokenizer or evaluator substitution",
            ));
        }
        evidence.token_accounting_receipt.verify(
            &request,
            tokenizer,
            accepted_at_unix_seconds,
        )?;
        let trusted_selector = TrustedRetentionSelectorV1 {
            enrollment: selector.enrollment.clone(),
        };
        let trusted_generator = TrustedSemanticGeneratorV1 {
            enrollment: generator.enrollment.clone(),
        };
        let trusted_tokenizer = TrustedTokenizerV1 {
            enrollment: tokenizer.enrollment.clone(),
            tokenizer_digest: tokenizer.artifact_digest,
        };
        let trusted_evaluator = TrustedCompactionEvaluatorV1 {
            enrollment: evaluator.enrollment.clone(),
            evaluator_id: evaluator.subject_id.clone(),
        };
        let candidate = crate::build_qualified_candidate(QualifiedCandidateBuildRequestV1 {
            source_snapshot: request.source_snapshot.clone(),
            source_memory_snapshot: &request.source_memory_snapshot,
            generation: request.generation,
            predecessor_checkpoint_digest: request.predecessor_checkpoint_digest,
            policy: &evidence.policy,
            semantic_payload: &evidence.semantic_payload,
            selector: &trusted_selector,
            selection_receipt: selection,
            generator: &trusted_generator,
            generation_receipt: generation,
            tokenizer: &trusted_tokenizer,
            inputs: evidence.inputs.clone(),
            verification_time_unix_seconds: accepted_at_unix_seconds,
        })
        .map_err(|error| CompactionAdmissionErrorV1::Trust(error.to_string()))?;
        let proof = crate::prove_compaction(TrustedCompactionProofRequestV1 {
            candidate: &candidate,
            evaluator: &trusted_evaluator,
            qualification: evidence.qualification.clone(),
            evaluation_receipt: evaluation,
            verification_time_unix_seconds: accepted_at_unix_seconds,
        })
        .map_err(|error| CompactionAdmissionErrorV1::Trust(error.to_string()))?;
        let nonce_bindings = [
            CompactionNonceBindingV1 {
                role: CompactionTrustRoleV1::RetentionSelector,
                key_id: selection.key_id.clone(),
                trust_epoch: selection.trust_epoch,
                nonce: selection.nonce,
                receipt_digest: selection.receipt_digest(),
            },
            CompactionNonceBindingV1 {
                role: CompactionTrustRoleV1::SemanticGenerator,
                key_id: generation.key_id.clone(),
                trust_epoch: generation.trust_epoch,
                nonce: generation.nonce,
                receipt_digest: generation.receipt_digest(),
            },
            CompactionNonceBindingV1 {
                role: CompactionTrustRoleV1::Tokenizer,
                key_id: evidence.token_accounting_receipt.key_id.clone(),
                trust_epoch: evidence.token_accounting_receipt.trust_epoch,
                nonce: evidence.token_accounting_receipt.nonce,
                receipt_digest: evidence.token_accounting_receipt.receipt_digest()?,
            },
            CompactionNonceBindingV1 {
                role: CompactionTrustRoleV1::Evaluator,
                key_id: evaluation.key_id.clone(),
                trust_epoch: evaluation.trust_epoch,
                nonce: evaluation.nonce,
                receipt_digest: evaluation.receipt_digest(),
            },
        ];
        let mut output = Encoder::new(ARCHIVE_DOMAIN)?;
        1_u32.write(&mut output)?;
        registry.owner_id().write(&mut output)?;
        registry.root_key_digest().write(&mut output)?;
        registry.manifest_digest().write(&mut output)?;
        accepted_at_unix_seconds.write(&mut output)?;
        request.write(&mut output)?;
        request_digest.write(&mut output)?;
        candidate.candidate_digest().write(&mut output)?;
        candidate
            .checkpoint()
            .checkpoint_digest
            .write(&mut output)?;
        proof.proof.proof_digest.write(&mut output)?;
        let archive = output.finish();
        validate_archive_lengths(request.evidence.semantic_payload.payload.len(), archive.len())?;
        Ok(Self {
            candidate,
            proof,
            principals: [
                selector.clone(),
                generator.clone(),
                tokenizer.clone(),
                evaluator.clone(),
            ],
            nonce_bindings,
            owner_id: registry.owner_id().clone(),
            root_key_digest: registry.root_key_digest(),
            registry_digest: registry.manifest_digest(),
            accepted_at_unix_seconds,
            request_digest,
            archive,
        })
    }

    /// Replays every cryptographic and semantic construction check. Byte hashes
    /// alone are insufficient: a self-consistent but forged image must fail.
    pub fn reopen(
        archive: &[u8],
        payload: &[u8],
        accepted_registry: &VerifiedCompactionTrustRegistryV1,
    ) -> Result<Self, CompactionAdmissionErrorV1> {
        validate_archive_lengths(payload.len(), archive.len())?;
        let mut input = Decoder::new(archive, ARCHIVE_DOMAIN)?;
        if u32::read(&mut input)? != 1
            || StableId::read(&mut input)? != *accepted_registry.owner_id()
            || Digest32::read(&mut input)? != accepted_registry.root_key_digest()
            || Digest32::read(&mut input)? != accepted_registry.manifest_digest()
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "archive owner or trust substitution",
            ));
        }
        let accepted_at = u64::read(&mut input)?;
        let mut request = CompactionPublicationRequestV1::read(&mut input)?;
        request.evidence.semantic_payload.payload = payload.to_vec();
        let request_digest = Digest32::read(&mut input)?;
        let candidate_digest = Digest32::read(&mut input)?;
        let checkpoint_digest = Digest32::read(&mut input)?;
        let proof_digest = Digest32::read(&mut input)?;
        input.finish()?;
        let verified = Self::verify(request, accepted_registry, accepted_at)?;
        if verified.request_digest != request_digest
            || verified.candidate.candidate_digest() != candidate_digest
            || verified.candidate.checkpoint().checkpoint_digest != checkpoint_digest
            || verified.proof.proof.proof_digest != proof_digest
            || verified.archive.as_slice() != archive
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "archive cross-object integrity or canonical encoding",
            ));
        }
        Ok(verified)
    }

    pub fn readmit_current_trust(
        &self,
        registry: &VerifiedCompactionTrustRegistryV1,
        now: u64,
    ) -> Result<(), CompactionAdmissionErrorV1> {
        if self.owner_id != *registry.owner_id()
            || self.root_key_digest != registry.root_key_digest()
        {
            return Err(CompactionAdmissionErrorV1::Invalid(
                "current owner or root substitution",
            ));
        }
        for principal in &self.principals {
            registry.readmit_principal(principal, now)?;
        }
        Ok(())
    }

    pub fn candidate(&self) -> &QualifiedCompactionCandidateV2 {
        &self.candidate
    }

    pub fn proof(&self) -> &TrustedCompactionProofV1 {
        &self.proof
    }

    pub fn owner_id(&self) -> &StableId {
        &self.owner_id
    }

    pub fn root_key_digest(&self) -> Digest32 {
        self.root_key_digest
    }

    pub fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    pub fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    pub fn accepted_at_unix_seconds(&self) -> u64 {
        self.accepted_at_unix_seconds
    }

    pub fn archive(&self) -> &[u8] {
        &self.archive
    }

    pub fn archive_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.archive)
    }

    pub fn nonce_bindings(&self) -> &[CompactionNonceBindingV1; 4] {
        &self.nonce_bindings
    }
}

fn validate_archive_lengths(
    payload_bytes: usize,
    archive_bytes: usize,
) -> Result<(), CompactionAdmissionErrorV1> {
    if payload_bytes > crate::MAX_QUALIFIED_COMPACTION_BYTES as usize {
        return Err(CompactionAdmissionErrorV1::Invalid("payload byte limit"));
    }
    if archive_bytes > MAX_COMPACTION_FULL_ARCHIVE_BYTES_V1 {
        return Err(CompactionAdmissionErrorV1::Invalid(
            "full publication archive byte limit",
        ));
    }
    if archive_bytes.saturating_sub(payload_bytes) > MAX_COMPACTION_ARCHIVE_METADATA_BYTES_V1 {
        return Err(CompactionAdmissionErrorV1::Invalid(
            "publication archive metadata byte limit",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod archive_limit_tests {
    use super::*;

    #[test]
    fn payload_and_archive_limits_are_independent() {
        let payload_limit = crate::MAX_QUALIFIED_COMPACTION_BYTES as usize;
        assert!(validate_archive_lengths(payload_limit, payload_limit).is_ok());
        assert!(
            validate_archive_lengths(
                payload_limit,
                payload_limit + MAX_COMPACTION_ARCHIVE_METADATA_BYTES_V1,
            )
            .is_ok()
        );
        assert!(validate_archive_lengths(payload_limit + 1, payload_limit + 1).is_err());
        assert!(
            validate_archive_lengths(
                payload_limit,
                payload_limit + MAX_COMPACTION_ARCHIVE_METADATA_BYTES_V1 + 1,
            )
            .is_err()
        );
    }
}
