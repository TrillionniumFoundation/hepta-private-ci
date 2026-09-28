
//! Canonical durable request identity for new work, recovery and terminal replay.

use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerTrustV1;
use crate::verify_artifact_admission_v3;

const MAGIC: &str = "HEPTA-ARTIFACT-REQUEST-IDENTITY-V1";
const MAX_RECORD_BYTES: u64 = 4096;

#[derive(Debug)]
pub(super) struct RequestIdentityStore {
    directory: PathBuf,
    registry_id: StableId,
    head_keys: BTreeMap<StableId, [u8; 32]>,
    trust_digest: Digest32,
    storage_binding: Digest32,
}

impl RequestIdentityStore {
    pub(super) fn new(
        root: &Path,
        trust: &ArtifactOwnerTrustV1,
        trust_digest: Digest32,
        storage_binding: Digest32,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        let directory = root.join("transactions").join("request-identities-v1");
        ensure_private_directory(&directory)?;
        Ok(Self {
            directory,
            registry_id: trust.registry_id.clone(),
            head_keys: trust
                .head_signers
                .iter()
                .map(|signer| (signer.signer_id.clone(), signer.verifying_key))
                .collect(),
            trust_digest,
            storage_binding,
        })
    }

    pub(super) fn verify(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        let admission = &request.admission;
        verify_artifact_admission_v3(
            admission,
            admission.withdrawal_head_digest,
            admission.admitted_at,
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let manifest = &admission.validated_manifest.manifest;
        let signed = &request.signed_current_head;
        if request.now < admission.admitted_at
            || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
            || request.payload.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
            || signed.binding != self.storage_binding
            || signed.witness.registry_id != self.registry_id
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let key_bytes = self
            .head_keys
            .get(&signed.witness.signer_id)
            .ok_or(LearningArtifactOwnerServiceError::RequestMismatch)?;
        if Digest32::of_bytes(key_bytes) != signed.witness.signing_key_digest {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        VerifyingKey::from_bytes(key_bytes)
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?
            .verify_strict(
                &signed.signing_bytes(),
                &Signature::from_bytes(&signed.signature),
            )
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)
    }

    pub(super) fn bind_or_verify(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        let expected = self.encode(request);
        if expected.len() as u64 > MAX_RECORD_BYTES {
            return Err(LearningArtifactOwnerServiceError::CapacityExceeded);
        }
        let path = self.path_for(&request.operation_id);
        match self.read_existing(&path)? {
            Some(actual) if actual == expected => {
                self.sync_existing(&path)?;
                return Ok(());
            }
            Some(_) => return Err(LearningArtifactOwnerServiceError::RequestIdentityConflict),
            None => {}
        }
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        match options.open(&path) {
            Ok(mut file) => {
                file.write_all(&expected)
                    .and_then(|()| file.sync_all())
                    .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
                sync_directory(&self.directory)?;
                Ok(())
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                match self.read_existing(&path)? {
                    Some(actual) if actual == expected => {
                        self.sync_existing(&path)?;
                        Ok(())
                    }
                    Some(_) => Err(LearningArtifactOwnerServiceError::RequestIdentityConflict),
                    None => Err(LearningArtifactOwnerServiceError::ControlIo(error)),
                }
            }
            Err(error) => Err(LearningArtifactOwnerServiceError::ControlIo(error)),
        }
    }

    fn sync_existing(&self, path: &Path) -> Result<(), LearningArtifactOwnerServiceError> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .and_then(|file| file.sync_all())
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        sync_directory(&self.directory)
    }

    fn path_for(&self, operation_id: &StableId) -> PathBuf {
        self.directory.join(format!(
            "{}.request-v1",
            Digest32::of_bytes(operation_id.as_str().as_bytes())
        ))
    }

    fn read_existing(
        &self,
        path: &Path,
    ) -> Result<Option<Vec<u8>>, LearningArtifactOwnerServiceError> {
        let metadata = match fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(LearningArtifactOwnerServiceError::ControlIo(error)),
        };
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() > MAX_RECORD_BYTES
        {
            return Err(LearningArtifactOwnerServiceError::RequestIdentityConflict);
        }
        let mut bytes = Vec::new();
        File::open(path)
            .and_then(|file| file.take(MAX_RECORD_BYTES + 1).read_to_end(&mut bytes))
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(LearningArtifactOwnerServiceError::RequestIdentityConflict);
        }
        Ok(Some(bytes))
    }

    fn encode(&self, request: &LearningArtifactPublishRequestV1) -> Vec<u8> {
        let signed = &request.signed_current_head;
        let signing_digest = Digest32::of_bytes(&signed.signing_bytes());
        let signature_digest = Digest32::of_bytes(&signed.signature);
        let payload_digest = Digest32::of_bytes(&request.payload);
        let body = format!(
            concat!(
                "{MAGIC}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n"
            ),
            request.operation_id,
            request.admission.admission_digest,
            request.admission.validated_manifest.manifest_digest,
            request.admission.withdrawal_scope_digest,
            request.admission.withdrawal_head_digest,
            request.admission.admitted_at,
            request.payload.len(),
            payload_digest,
            request.expected_registry_predecessor_head,
            signed.binding,
            signing_digest,
            signature_digest,
            self.trust_digest,
        );
        let digest = Digest32::of_bytes(body.as_bytes());
        format!("{body}{digest}\n").into_bytes()
    }
}

fn ensure_private_directory(path: &Path) -> Result<(), LearningArtifactOwnerServiceError> {
    if !path.exists() {
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        builder.mode(0o700);
        builder
            .create(path)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let parent = path
            .parent()
            .ok_or(LearningArtifactOwnerServiceError::InvalidConfiguration)?;
        sync_directory(parent)?;
    }
    let metadata = fs::symlink_metadata(path)
        .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
    }
    sync_directory(path)
}

fn sync_directory(path: &Path) -> Result<(), LearningArtifactOwnerServiceError> {
    #[cfg(unix)]
    {
        File::open(path)
            .and_then(|file| file.sync_all())
            .map_err(LearningArtifactOwnerServiceError::ControlIo)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(LearningArtifactOwnerServiceError::ControlIo(
            std::io::Error::new(
                std::io::ErrorKind::Unsupported,
                "directory durability is not qualified",
            ),
        ))
    }
}
