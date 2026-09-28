//! Bounded canonical metadata for an immutable publication request.
//! Payload bytes remain in the existing payload store, never duplicated here.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::LearningArtifactOwnerServiceError as Error;
use super::LearningArtifactPublishRequestV1;
use super::request_identity::RequestIdentityVerifier;
use crate::ArtifactKind;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::validate_artifact_manifest_v2;

pub(super) const MAX_REQUEST_RECORD_BYTES: usize = 128 * 1024;
const MAGIC: &[u8; 8] = b"HEPTAI01";

#[derive(Clone, Debug)]
pub(super) struct RequestRecord {
    pub(super) operation_id: StableId,
    pub(super) admission: WithdrawalBoundArtifactAdmissionV3,
    pub(super) signed_head: SignedCurrentArtifactHeadV1,
    pub(super) predecessor: Digest32,
    pub(super) identity: Digest32,
    pub(super) bound_at: u64,
}

impl RequestRecord {
    pub(super) fn from_request(
        request: &LearningArtifactPublishRequestV1,
        identity: Digest32,
    ) -> Result<Self, Error> {
        let validated_manifest = validate_artifact_manifest_v2(
            request.admission.validated_manifest.manifest.clone(),
            request.admission.admitted_at,
        )
        .map_err(|_| Error::RequestMismatch)?;
        Ok(Self {
            operation_id: request.operation_id.clone(),
            admission: WithdrawalBoundArtifactAdmissionV3 {
                validated_manifest,
                ..request.admission.clone()
            },
            signed_head: request.signed_current_head.clone(),
            predecessor: request.expected_registry_predecessor_head,
            identity,
            bound_at: request.now,
        })
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, Error> {
        let mut bytes = MAGIC.to_vec();
        put_id(&mut bytes, &self.operation_id);
        put_u64(&mut bytes, self.bound_at);
        bytes.extend_from_slice(self.predecessor.as_array());
        bytes.extend_from_slice(self.identity.as_array());
        let admission = &self.admission;
        bytes.extend_from_slice(admission.withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(admission.withdrawal_head_digest.as_array());
        put_u64(&mut bytes, admission.admitted_at);
        bytes.extend_from_slice(admission.admission_digest.as_array());
        let manifest = &admission.validated_manifest.manifest;
        put_id(&mut bytes, &manifest.artifact_id);
        bytes.push(manifest.kind.tag());
        put_u64(&mut bytes, manifest.generation.get());
        bytes.push(match manifest.provenance_mode {
            ProvenanceModeV1::DatasetDerived => 0,
            ProvenanceModeV1::DatasetIndependent => 1,
        });
        for values in [&manifest.source_dataset_digests, &manifest.lineage_digests] {
            put_u64(&mut bytes, values.len() as u64);
            for value in values {
                bytes.extend_from_slice(value.as_array());
            }
        }
        put_u64(&mut bytes, manifest.predecessor_ids.len() as u64);
        for value in &manifest.predecessor_ids {
            put_id(&mut bytes, value);
        }
        match &manifest.rollback_predecessor {
            Some(value) => {
                bytes.push(1);
                put_id(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(manifest.bytes_digest.as_array());
        put_u64(&mut bytes, manifest.encoded_size_bytes);
        for value in [
            manifest.training_code_digest,
            manifest.runtime_tuple_digest,
            manifest.device_profile_digest,
            manifest.objective_class_digest,
            manifest.compatibility_digest,
            manifest.schema_profile_digest,
            manifest.normalization_digest,
        ] {
            bytes.extend_from_slice(value.as_array());
        }
        put_id(&mut bytes, &manifest.producer_id);
        put_u64(&mut bytes, manifest.created_at);
        put_u64(&mut bytes, manifest.expires_at);
        let signed = &self.signed_head;
        bytes.extend_from_slice(signed.withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(signed.binding.as_array());
        let witness = &signed.witness;
        put_id(&mut bytes, &witness.registry_id);
        put_u64(&mut bytes, witness.generation.get());
        bytes.extend_from_slice(witness.head_digest.as_array());
        bytes.extend_from_slice(witness.predecessor_head_digest.as_array());
        put_u64(&mut bytes, witness.authority_epoch);
        put_id(&mut bytes, &witness.signer_id);
        bytes.extend_from_slice(witness.signing_key_digest.as_array());
        put_u64(&mut bytes, witness.issued_at);
        put_u64(&mut bytes, witness.expires_at);
        bytes.extend_from_slice(&signed.signature);
        let checksum = Digest32::of_bytes(&bytes);
        bytes.extend_from_slice(checksum.as_array());
        if bytes.len() > MAX_REQUEST_RECORD_BYTES {
            return Err(Error::RequestBindingCorrupt);
        }
        Ok(bytes)
    }

    pub(super) fn decode(bytes: &[u8], verifier: &RequestIdentityVerifier) -> Result<Self, Error> {
        if bytes.len() < MAGIC.len() + 32 || bytes.len() > MAX_REQUEST_RECORD_BYTES {
            return Err(Error::RequestBindingCorrupt);
        }
        let (body, checksum) = bytes.split_at(bytes.len() - 32);
        if Digest32::of_bytes(body).as_array().as_slice() != checksum {
            return Err(Error::RequestBindingCorrupt);
        }
        let mut input = Decoder(body);
        if input.take(8)? != MAGIC {
            return Err(Error::RequestBindingCorrupt);
        }
        let operation_id = input.id()?;
        let bound_at = input.number()?;
        let predecessor = input.digest()?;
        let identity = input.digest()?;
        let withdrawal_scope_digest = input.digest()?;
        let withdrawal_head_digest = input.digest()?;
        let admitted_at = input.number()?;
        let admission_digest = input.digest()?;
        let artifact_id = input.id()?;
        let kind = match input.byte()? {
            0 => ArtifactKind::Prompt,
            1 => ArtifactKind::Policy,
            2 => ArtifactKind::Model,
            3 => ArtifactKind::Workflow,
            4 => ArtifactKind::Skill,
            5 => ArtifactKind::Parameters,
            6 => ArtifactKind::Topology,
            7 => ArtifactKind::Code,
            8 => ArtifactKind::ExternalAdapter,
            9 => ArtifactKind::SensorCore,
            _ => return Err(Error::RequestBindingCorrupt),
        };
        let generation =
            Generation::new(input.number()?).map_err(|_| Error::RequestBindingCorrupt)?;
        let provenance_mode = match input.byte()? {
            0 => ProvenanceModeV1::DatasetDerived,
            1 => ProvenanceModeV1::DatasetIndependent,
            _ => return Err(Error::RequestBindingCorrupt),
        };
        let source_dataset_digests = input.digests(64)?;
        let lineage_digests = input.digests(1024)?;
        let count = input.count(64)?;
        let mut predecessor_ids = Vec::with_capacity(count);
        for _ in 0..count {
            predecessor_ids.push(input.id()?);
        }
        let rollback_predecessor = match input.byte()? {
            0 => None,
            1 => Some(input.id()?),
            _ => return Err(Error::RequestBindingCorrupt),
        };
        let manifest = LearningArtifactManifestV2 {
            artifact_id,
            kind,
            generation,
            provenance_mode,
            source_dataset_digests,
            lineage_digests,
            predecessor_ids,
            rollback_predecessor,
            bytes_digest: input.digest()?,
            encoded_size_bytes: input.number()?,
            training_code_digest: input.digest()?,
            runtime_tuple_digest: input.digest()?,
            device_profile_digest: input.digest()?,
            objective_class_digest: input.digest()?,
            compatibility_digest: input.digest()?,
            schema_profile_digest: input.digest()?,
            normalization_digest: input.digest()?,
            producer_id: input.id()?,
            created_at: input.number()?,
            expires_at: input.number()?,
        };
        let validated_manifest = validate_artifact_manifest_v2(manifest, admitted_at)
            .map_err(|_| Error::RequestBindingCorrupt)?;
        let admission = WithdrawalBoundArtifactAdmissionV3 {
            validated_manifest,
            withdrawal_scope_digest,
            withdrawal_head_digest,
            admitted_at,
            admission_digest,
            authority: AuthorityPosture::DENY_ALL,
        };
        let head_scope = input.digest()?;
        let binding = input.digest()?;
        let witness = RegistryHeadWitnessV1 {
            registry_id: input.id()?,
            generation: Generation::new(input.number()?)
                .map_err(|_| Error::RequestBindingCorrupt)?,
            head_digest: input.digest()?,
            predecessor_head_digest: input.digest()?,
            authority_epoch: input.number()?,
            signer_id: input.id()?,
            signing_key_digest: input.digest()?,
            issued_at: input.number()?,
            expires_at: input.number()?,
        };
        let signature = input
            .take(64)?
            .try_into()
            .map_err(|_| Error::RequestBindingCorrupt)?;
        let signed_head = SignedCurrentArtifactHeadV1 {
            witness,
            withdrawal_scope_digest: head_scope,
            binding,
            signature,
        };
        if !input.0.is_empty() || bound_at < admitted_at {
            return Err(Error::RequestBindingCorrupt);
        }
        let record = Self {
            operation_id,
            admission,
            signed_head,
            predecessor,
            identity,
            bound_at,
        };
        let expected = verifier.verify_metadata(
            &record.operation_id,
            &record.admission,
            &record.signed_head,
            record.predecessor,
        )?;
        if expected != identity || record.encode()?.as_slice() != bytes {
            return Err(Error::RequestBindingCorrupt);
        }
        Ok(record)
    }
}

fn put_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
fn put_id(bytes: &mut Vec<u8>, value: &StableId) {
    put_u64(bytes, value.as_str().len() as u64);
    bytes.extend_from_slice(value.as_str().as_bytes());
}

struct Decoder<'a>(&'a [u8]);
impl<'a> Decoder<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], Error> {
        if count > self.0.len() {
            return Err(Error::RequestBindingCorrupt);
        }
        let (value, rest) = self.0.split_at(count);
        self.0 = rest;
        Ok(value)
    }
    fn byte(&mut self) -> Result<u8, Error> {
        Ok(self.take(1)?[0])
    }
    fn number(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| Error::RequestBindingCorrupt)?,
        ))
    }
    fn count(&mut self, limit: usize) -> Result<usize, Error> {
        let count = usize::try_from(self.number()?).map_err(|_| Error::RequestBindingCorrupt)?;
        if count > limit {
            return Err(Error::RequestBindingCorrupt);
        }
        Ok(count)
    }
    fn id(&mut self) -> Result<StableId, Error> {
        let count = self.count(128)?;
        let text =
            std::str::from_utf8(self.take(count)?).map_err(|_| Error::RequestBindingCorrupt)?;
        StableId::new(text.to_owned()).map_err(|_| Error::RequestBindingCorrupt)
    }
    fn digest(&mut self) -> Result<Digest32, Error> {
        let bytes: [u8; 32] = self
            .take(32)?
            .try_into()
            .map_err(|_| Error::RequestBindingCorrupt)?;
        Ok(Digest32::from_array(bytes))
    }
    fn digests(&mut self, limit: usize) -> Result<Vec<Digest32>, Error> {
        let count = self.count(limit)?;
        let mut values = Vec::with_capacity(count);
        for _ in 0..count {
            values.push(self.digest()?);
        }
        Ok(values)
    }
}
