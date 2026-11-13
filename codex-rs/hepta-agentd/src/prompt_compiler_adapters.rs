//! Independently authenticated admission and exact-tokenizer adapters for the
//! product context compiler.
//!
//! The admission trust root and signed digest bundle live outside the Agent
//! home rollback domain and are reloaded for every verification.  Agentd owns
//! no signing key and cannot mint an accepted admission.  The tokenizer is a
//! pinned executable protocol whose binary, vocabulary and normalization bytes
//! are digest-checked before and after every invocation.

#[cfg(unix)]
use std::fs::File;
use std::fmt;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::str::FromStr;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_context_compiler::ContextAdmissionRecordV2;
use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileRevisionV2;
use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_intelligence::PromptCompilerProductAdaptersV3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdIdentity;
use crate::authbus_trust::hex_bytes;

const ADMISSION_VERIFIER_DOMAIN_V3: &[u8] = b"hepta.context-admission-verifier.v3";
const ADMISSION_RECORD_SIGNATURE_DOMAIN_V3: &[u8] =
    b"hepta.context-admission-record-authority.v3";
const ADMISSION_SNAPSHOT_SIGNATURE_DOMAIN_V3: &[u8] =
    b"hepta.context-admission-snapshot-authority.v3";
const ADMISSION_FILE_SCHEMA_V3: u32 = 3;
const TOKENIZER_PROTOCOL_SCHEMA_V1: u32 = 1;
const MAX_ADMISSION_TRUST_BYTES: u64 = 16 * 1024;
const MAX_ADMISSION_BUNDLE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_SIGNED_ADMISSION_RECORDS: usize = 4096;
const MAX_SIGNED_ADMISSION_SNAPSHOTS: usize = 4096;
const MAX_TOKENIZER_BINARY_BYTES: u64 = 128 * 1024 * 1024;
const MAX_TOKENIZER_VOCABULARY_BYTES: u64 = 512 * 1024 * 1024;
const MAX_TOKENIZER_NORMALIZATION_BYTES: u64 = 16 * 1024 * 1024;
const MAX_TOKENIZER_INPUT_BYTES: usize = 32 * 1024 * 1024;
const MAX_TOKENIZER_STDOUT_BYTES: u64 = 16 * 1024;
const MAX_TOKENIZER_STDERR_BYTES: u64 = 64 * 1024;
const TOKENIZER_POLL_INTERVAL: Duration = Duration::from_millis(5);

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ContextAdmissionAuthorityTrustV3 {
    schema_version: u32,
    authority_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ContextAdmissionAuthorityBundleV3 {
    schema_version: u32,
    authority_id: String,
    key_epoch: u64,
    records: Vec<SignedAdmissionDigestV3>,
    snapshots: Vec<SignedAdmissionDigestV3>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignedAdmissionDigestV3 {
    digest_hex: String,
    signature_hex: String,
}

#[derive(Clone)]
struct AdmissionAuthorityViewV3 {
    authority_id: StableId,
    key_epoch: u64,
    verifying_key_bytes: [u8; 32],
    record_digests: std::collections::BTreeSet<Digest32>,
    snapshot_digests: std::collections::BTreeSet<Digest32>,
    verifier_digest: Digest32,
}

#[derive(Clone)]
pub struct ExternalContextAdmissionAuthorityV3 {
    trust_path: PathBuf,
    bundle_path: PathBuf,
    rollback_root: PathBuf,
    expected_authority_id: StableId,
    expected_key_epoch: u64,
    expected_verifying_key: [u8; 32],
    verifier_digest: Digest32,
}

impl fmt::Debug for ExternalContextAdmissionAuthorityV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ExternalContextAdmissionAuthorityV3")
            .field("authority_id", &self.expected_authority_id)
            .field("key_epoch", &self.expected_key_epoch)
            .field("verifier_digest", &self.verifier_digest)
            .finish_non_exhaustive()
    }
}

impl ExternalContextAdmissionAuthorityV3 {
    pub fn open(
        identity: &AgentdIdentity,
        trust_path: &Path,
        bundle_path: &Path,
    ) -> Result<Self, AgentdPromptCompilerAdapterErrorV3> {
        let rollback_root = identity.home_root.canonicalize()?;
        let view = load_admission_authority_view(
            trust_path,
            bundle_path,
            &rollback_root,
            /*expected*/ None,
        )?;
        Ok(Self {
            trust_path: trust_path.to_path_buf(),
            bundle_path: bundle_path.to_path_buf(),
            rollback_root,
            expected_authority_id: view.authority_id,
            expected_key_epoch: view.key_epoch,
            expected_verifying_key: view.verifying_key_bytes,
            verifier_digest: view.verifier_digest,
        })
    }

    fn current_view(
        &self,
    ) -> Result<AdmissionAuthorityViewV3, AgentdPromptCompilerAdapterErrorV3> {
        load_admission_authority_view(
            &self.trust_path,
            &self.bundle_path,
            &self.rollback_root,
            Some((
                &self.expected_authority_id,
                self.expected_key_epoch,
                self.expected_verifying_key,
                self.verifier_digest,
            )),
        )
    }
}

impl ContextAdmissionVerifierV2 for ExternalContextAdmissionAuthorityV3 {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        self.current_view()
            .is_ok_and(|view| view.record_digests.contains(&record.record_digest))
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        self.current_view()
            .is_ok_and(|view| view.snapshot_digests.contains(&snapshot.snapshot_digest))
    }
}

/// Canonical bytes signed by the independent admission authority for one
/// context admission record digest.
#[must_use]
pub fn context_admission_record_signing_bytes_v3(
    authority_id: &StableId,
    key_epoch: u64,
    record_digest: Digest32,
) -> Vec<u8> {
    admission_signing_bytes(
        ADMISSION_RECORD_SIGNATURE_DOMAIN_V3,
        authority_id,
        key_epoch,
        record_digest,
    )
}

/// Canonical bytes signed by the independent admission authority for one
/// complete context admission snapshot digest.
#[must_use]
pub fn context_admission_snapshot_signing_bytes_v3(
    authority_id: &StableId,
    key_epoch: u64,
    snapshot_digest: Digest32,
) -> Vec<u8> {
    admission_signing_bytes(
        ADMISSION_SNAPSHOT_SIGNATURE_DOMAIN_V3,
        authority_id,
        key_epoch,
        snapshot_digest,
    )
}

fn admission_signing_bytes(
    domain: &[u8],
    authority_id: &StableId,
    key_epoch: u64,
    digest: Digest32,
) -> Vec<u8> {
    let mut bytes = domain.to_vec();
    push_part(&mut bytes, authority_id.as_str().as_bytes());
    bytes.extend_from_slice(&key_epoch.to_be_bytes());
    bytes.extend_from_slice(digest.as_array());
    bytes
}

fn load_admission_authority_view(
    trust_path: &Path,
    bundle_path: &Path,
    rollback_root: &Path,
    expected: Option<(&StableId, u64, [u8; 32], Digest32)>,
) -> Result<AdmissionAuthorityViewV3, AgentdPromptCompilerAdapterErrorV3> {
    if trust_path == bundle_path {
        return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
            "admission trust and signed bundle must be separate files",
        ));
    }
    let trust_bytes = read_external_immutable_file(
        trust_path,
        rollback_root,
        MAX_ADMISSION_TRUST_BYTES,
        /*executable*/ false,
    )?;
    let trust: ContextAdmissionAuthorityTrustV3 = serde_json::from_slice(&trust_bytes)?;
    if trust.schema_version != ADMISSION_FILE_SCHEMA_V3
        || trust.key_epoch == 0
        || trust.revoked
    {
        return Err(AgentdPromptCompilerAdapterErrorV3::AdmissionTrustRejected);
    }
    let authority_id = StableId::new(trust.authority_id.clone()).map_err(|_| {
        AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration("invalid admission authority id")
    })?;
    let verifying_key_bytes = hex_bytes::<32>(&trust.public_key_hex)
        .map_err(|_| AgentdPromptCompilerAdapterErrorV3::AdmissionTrustRejected)?;
    let verifying_key = VerifyingKey::from_bytes(&verifying_key_bytes)
        .map_err(|_| AgentdPromptCompilerAdapterErrorV3::AdmissionTrustRejected)?;
    let verifier_digest = admission_verifier_digest(
        &authority_id,
        trust.key_epoch,
        verifying_key_bytes,
    );
    if let Some((expected_id, expected_epoch, expected_key, expected_digest)) = expected
        && (&authority_id != expected_id
            || trust.key_epoch != expected_epoch
            || verifying_key_bytes != expected_key
            || verifier_digest != expected_digest)
    {
        return Err(AgentdPromptCompilerAdapterErrorV3::AdmissionTrustChanged);
    }

    let bundle_bytes = read_external_immutable_file(
        bundle_path,
        rollback_root,
        MAX_ADMISSION_BUNDLE_BYTES,
        /*executable*/ false,
    )?;
    let bundle: ContextAdmissionAuthorityBundleV3 = serde_json::from_slice(&bundle_bytes)?;
    if bundle.schema_version != ADMISSION_FILE_SCHEMA_V3
        || bundle.authority_id != trust.authority_id
        || bundle.key_epoch != trust.key_epoch
        || bundle.records.len() > MAX_SIGNED_ADMISSION_RECORDS
        || bundle.snapshots.len() > MAX_SIGNED_ADMISSION_SNAPSHOTS
    {
        return Err(AgentdPromptCompilerAdapterErrorV3::AdmissionBundleRejected);
    }

    let record_digests = verify_signed_admission_digests(
        &verifying_key,
        &authority_id,
        trust.key_epoch,
        ADMISSION_RECORD_SIGNATURE_DOMAIN_V3,
        bundle.records,
    )?;
    let snapshot_digests = verify_signed_admission_digests(
        &verifying_key,
        &authority_id,
        trust.key_epoch,
        ADMISSION_SNAPSHOT_SIGNATURE_DOMAIN_V3,
        bundle.snapshots,
    )?;
    if snapshot_digests.is_empty() {
        return Err(AgentdPromptCompilerAdapterErrorV3::AdmissionBundleRejected);
    }
    Ok(AdmissionAuthorityViewV3 {
        authority_id,
        key_epoch: trust.key_epoch,
        verifying_key_bytes,
        record_digests,
        snapshot_digests,
        verifier_digest,
    })
}

fn verify_signed_admission_digests(
    verifying_key: &VerifyingKey,
    authority_id: &StableId,
    key_epoch: u64,
    domain: &[u8],
    signed: Vec<SignedAdmissionDigestV3>,
) -> Result<std::collections::BTreeSet<Digest32>, AgentdPromptCompilerAdapterErrorV3> {
    let mut digests = std::collections::BTreeSet::new();
    for entry in signed {
        let digest = Digest32::from_str(&entry.digest_hex)
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::AdmissionBundleRejected)?;
        if digest.is_zero() || !digests.insert(digest) {
            return Err(AgentdPromptCompilerAdapterErrorV3::AdmissionBundleRejected);
        }
        let signature_bytes = hex_bytes::<64>(&entry.signature_hex)
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::AdmissionSignatureInvalid)?;
        verifying_key
            .verify_strict(
                &admission_signing_bytes(domain, authority_id, key_epoch, digest),
                &Signature::from_bytes(&signature_bytes),
            )
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::AdmissionSignatureInvalid)?;
    }
    Ok(digests)
}

fn admission_verifier_digest(
    authority_id: &StableId,
    key_epoch: u64,
    verifying_key: [u8; 32],
) -> Digest32 {
    let mut bytes = ADMISSION_VERIFIER_DOMAIN_V3.to_vec();
    push_part(&mut bytes, authority_id.as_str().as_bytes());
    bytes.extend_from_slice(&key_epoch.to_be_bytes());
    bytes.extend_from_slice(&verifying_key);
    Digest32::of_bytes(&bytes)
}

#[derive(Clone)]
pub struct PinnedTokenizerProcessV3 {
    binary_path: PathBuf,
    vocabulary_path: PathBuf,
    normalization_path: PathBuf,
    rollback_root: PathBuf,
    tokenizer_digest: Digest32,
    product_profile_digest: Digest32,
    binary_digest: Digest32,
    vocabulary_digest: Digest32,
    normalization_digest: Digest32,
    timeout: Duration,
}

impl fmt::Debug for PinnedTokenizerProcessV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PinnedTokenizerProcessV3")
            .field("tokenizer_digest", &self.tokenizer_digest)
            .field("product_profile_digest", &self.product_profile_digest)
            .field("binary_digest", &self.binary_digest)
            .field("vocabulary_digest", &self.vocabulary_digest)
            .field("normalization_digest", &self.normalization_digest)
            .field("timeout", &self.timeout)
            .finish_non_exhaustive()
    }
}

impl PinnedTokenizerProcessV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn open(
        identity: &AgentdIdentity,
        product_profile: &ContextModelProfileRevisionV2,
        binary_path: &Path,
        vocabulary_path: &Path,
        normalization_path: &Path,
        timeout: Duration,
    ) -> Result<Self, AgentdPromptCompilerAdapterErrorV3> {
        product_profile
            .validate()
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::InvalidProductProfile)?;
        if timeout.is_zero() || timeout > Duration::from_secs(60) {
            return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
                "tokenizer timeout must be between zero and sixty seconds",
            ));
        }
        let rollback_root = identity.home_root.canonicalize()?;
        let value = Self {
            binary_path: binary_path.to_path_buf(),
            vocabulary_path: vocabulary_path.to_path_buf(),
            normalization_path: normalization_path.to_path_buf(),
            rollback_root,
            tokenizer_digest: product_profile.base_profile.tokenizer_digest,
            product_profile_digest: product_profile.digest(),
            binary_digest: product_profile.tokenizer_binary_digest,
            vocabulary_digest: product_profile.tokenizer_vocabulary_digest,
            normalization_digest: product_profile.tokenizer_normalization_digest,
            timeout,
        };
        value.verify_artifacts()?;
        Ok(value)
    }

    fn verify_artifacts(&self) -> Result<(), AgentdPromptCompilerAdapterErrorV3> {
        let actual_binary = digest_external_immutable_file(
            &self.binary_path,
            &self.rollback_root,
            MAX_TOKENIZER_BINARY_BYTES,
            /*executable*/ true,
        )?;
        let actual_vocabulary = digest_external_immutable_file(
            &self.vocabulary_path,
            &self.rollback_root,
            MAX_TOKENIZER_VOCABULARY_BYTES,
            /*executable*/ false,
        )?;
        let actual_normalization = digest_external_immutable_file(
            &self.normalization_path,
            &self.rollback_root,
            MAX_TOKENIZER_NORMALIZATION_BYTES,
            /*executable*/ false,
        )?;
        if actual_binary != self.binary_digest
            || actual_vocabulary != self.vocabulary_digest
            || actual_normalization != self.normalization_digest
        {
            return Err(AgentdPromptCompilerAdapterErrorV3::TokenizerArtifactMismatch);
        }
        Ok(())
    }

    fn invoke(&self, bytes: &[u8]) -> Result<u64, AgentdPromptCompilerAdapterErrorV3> {
        if bytes.is_empty() || bytes.len() > MAX_TOKENIZER_INPUT_BYTES {
            return Err(AgentdPromptCompilerAdapterErrorV3::TokenizerInputInvalid);
        }
        self.verify_artifacts()?;
        let mut child = Command::new(&self.binary_path)
            .arg("--hepta-token-count-v1")
            .arg("--vocabulary")
            .arg(&self.vocabulary_path)
            .arg("--normalization")
            .arg(&self.normalization_path)
            .arg("--tokenizer-digest")
            .arg(self.tokenizer_digest.to_string())
            .env_clear()
            .env("LC_ALL", "C")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerUnavailable)?;

        let stdout = child
            .stdout
            .take()
            .ok_or(AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid)?;
        let stderr = child
            .stderr
            .take()
            .ok_or(AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid)?;
        let stdout_reader = thread::spawn(move || read_bounded(stdout, MAX_TOKENIZER_STDOUT_BYTES));
        let stderr_reader = thread::spawn(move || read_bounded(stderr, MAX_TOKENIZER_STDERR_BYTES));

        let write_result = child
            .stdin
            .take()
            .ok_or(AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid)
            .and_then(|mut stdin| {
                stdin
                    .write_all(bytes)
                    .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerUnavailable)
            });
        if let Err(error) = write_result {
            terminate_child(&mut child);
            let _ = stdout_reader.join();
            let _ = stderr_reader.join();
            return Err(error);
        }

        let status = wait_bounded(&mut child, self.timeout)?;
        let stdout = stdout_reader
            .join()
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerUnavailable)??;
        let stderr = stderr_reader
            .join()
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerUnavailable)??;
        self.verify_artifacts()?;
        if !status.success() || !stderr.is_empty() {
            return Err(AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid);
        }
        let response: TokenizerCountResponseV1 = serde_json::from_slice(&stdout)
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid)?;
        if response.schema_version != TOKENIZER_PROTOCOL_SCHEMA_V1
            || Digest32::from_str(&response.tokenizer_digest)
                .ok()
                .filter(|digest| *digest == self.tokenizer_digest)
                .is_none()
            || Digest32::from_str(&response.input_sha256)
                .ok()
                .filter(|digest| *digest == Digest32::of_bytes(bytes))
                .is_none()
            || response.token_count == 0
        {
            return Err(AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid);
        }
        Ok(response.token_count)
    }
}

impl ExactTokenizerV2 for PinnedTokenizerProcessV3 {
    fn tokenizer_digest(&self) -> Digest32 {
        self.tokenizer_digest
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        self.invoke(bytes).map_err(|error| match error {
            AgentdPromptCompilerAdapterErrorV3::TokenizerArtifactMismatch => {
                ContextCompilerV2Error::TokenizerArtifactMismatch
            }
            AgentdPromptCompilerAdapterErrorV3::TokenizerTimedOut => {
                ContextCompilerV2Error::TokenizerTimedOut
            }
            AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid
            | AgentdPromptCompilerAdapterErrorV3::TokenizerInputInvalid => {
                ContextCompilerV2Error::TokenizerProtocolInvalid
            }
            _ => ContextCompilerV2Error::TokenizerUnavailable,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TokenizerCountResponseV1 {
    schema_version: u32,
    tokenizer_digest: String,
    input_sha256: String,
    token_count: u64,
}

#[derive(Clone)]
pub struct AgentdPromptCompilerAdaptersV3 {
    admission: ExternalContextAdmissionAuthorityV3,
    tokenizer: PinnedTokenizerProcessV3,
    product_profile_digest: Digest32,
}

impl fmt::Debug for AgentdPromptCompilerAdaptersV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdPromptCompilerAdaptersV3")
            .field("admission", &self.admission)
            .field("tokenizer", &self.tokenizer)
            .field("product_profile_digest", &self.product_profile_digest)
            .finish()
    }
}

impl AgentdPromptCompilerAdaptersV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn open(
        identity: &AgentdIdentity,
        product_profile: &ContextModelProfileRevisionV2,
        admission_trust_path: &Path,
        admission_bundle_path: &Path,
        tokenizer_binary_path: &Path,
        tokenizer_vocabulary_path: &Path,
        tokenizer_normalization_path: &Path,
        tokenizer_timeout: Duration,
    ) -> Result<Self, AgentdPromptCompilerAdapterErrorV3> {
        let admission = ExternalContextAdmissionAuthorityV3::open(
            identity,
            admission_trust_path,
            admission_bundle_path,
        )?;
        let tokenizer = PinnedTokenizerProcessV3::open(
            identity,
            product_profile,
            tokenizer_binary_path,
            tokenizer_vocabulary_path,
            tokenizer_normalization_path,
            tokenizer_timeout,
        )?;
        Ok(Self {
            admission,
            tokenizer,
            product_profile_digest: product_profile.digest(),
        })
    }
}

impl ContextAdmissionVerifierV2 for AgentdPromptCompilerAdaptersV3 {
    fn verifier_digest(&self) -> Digest32 {
        self.admission.verifier_digest()
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        self.admission.verify_record(record)
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        self.admission.verify_snapshot(snapshot)
    }
}

impl ExactTokenizerV2 for AgentdPromptCompilerAdaptersV3 {
    fn tokenizer_digest(&self) -> Digest32 {
        self.tokenizer.tokenizer_digest()
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        self.tokenizer.count_tokens(bytes)
    }
}

impl PromptCompilerProductAdaptersV3 for AgentdPromptCompilerAdaptersV3 {
    fn product_profile_digest(&self) -> Digest32 {
        self.product_profile_digest
    }
}

#[derive(Debug)]
pub enum AgentdPromptCompilerAdapterErrorV3 {
    InvalidConfiguration(&'static str),
    InvalidProductProfile,
    AdmissionTrustRejected,
    AdmissionTrustChanged,
    AdmissionBundleRejected,
    AdmissionSignatureInvalid,
    TokenizerArtifactMismatch,
    TokenizerInputInvalid,
    TokenizerUnavailable,
    TokenizerProtocolInvalid,
    TokenizerTimedOut,
    Io(std::io::Error),
    Json(serde_json::Error),
}

impl AgentdPromptCompilerAdapterErrorV3 {
    #[must_use]
    pub const fn stable_code(&self) -> &'static str {
        match self {
            Self::InvalidConfiguration(_) => "agentd_prompt_adapter_invalid_configuration",
            Self::InvalidProductProfile => "agentd_prompt_adapter_invalid_product_profile",
            Self::AdmissionTrustRejected => "agentd_prompt_adapter_admission_trust_rejected",
            Self::AdmissionTrustChanged => "agentd_prompt_adapter_admission_trust_changed",
            Self::AdmissionBundleRejected => "agentd_prompt_adapter_admission_bundle_rejected",
            Self::AdmissionSignatureInvalid => "agentd_prompt_adapter_admission_signature_invalid",
            Self::TokenizerArtifactMismatch => "agentd_prompt_adapter_tokenizer_artifact_mismatch",
            Self::TokenizerInputInvalid => "agentd_prompt_adapter_tokenizer_input_invalid",
            Self::TokenizerUnavailable => "agentd_prompt_adapter_tokenizer_unavailable",
            Self::TokenizerProtocolInvalid => "agentd_prompt_adapter_tokenizer_protocol_invalid",
            Self::TokenizerTimedOut => "agentd_prompt_adapter_tokenizer_timed_out",
            Self::Io(_) => "agentd_prompt_adapter_io",
            Self::Json(_) => "agentd_prompt_adapter_json",
        }
    }
}

impl fmt::Display for AgentdPromptCompilerAdapterErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.stable_code())
    }
}

impl std::error::Error for AgentdPromptCompilerAdapterErrorV3 {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Json(error) => Some(error),
            _ => None,
        }
    }
}

impl From<std::io::Error> for AgentdPromptCompilerAdapterErrorV3 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<serde_json::Error> for AgentdPromptCompilerAdapterErrorV3 {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}

#[cfg(unix)]
fn read_external_immutable_file(
    path: &Path,
    rollback_root: &Path,
    maximum_bytes: u64,
    executable: bool,
) -> Result<Vec<u8>, AgentdPromptCompilerAdapterErrorV3> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
            "external artifact paths must be absolute",
        ));
    }
    let canonical = path.canonicalize()?;
    if canonical != path || canonical.starts_with(rollback_root) {
        return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
            "external artifacts must be canonical and outside the Agent home rollback domain",
        ));
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() > maximum_bytes
        || (executable && before.mode() & 0o111 == 0)
    {
        return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
            "external artifact is not a bounded immutable regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
            "external artifact changed while opening",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || identity(&after) != identity(&before)
        || identity(&file.metadata()?) != identity(&before)
    {
        return Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
            "external artifact changed while reading",
        ));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_external_immutable_file(
    _path: &Path,
    _rollback_root: &Path,
    _maximum_bytes: u64,
    _executable: bool,
) -> Result<Vec<u8>, AgentdPromptCompilerAdapterErrorV3> {
    Err(AgentdPromptCompilerAdapterErrorV3::InvalidConfiguration(
        "product prompt adapters currently require Unix file identity checks",
    ))
}

fn digest_external_immutable_file(
    path: &Path,
    rollback_root: &Path,
    maximum_bytes: u64,
    executable: bool,
) -> Result<Digest32, AgentdPromptCompilerAdapterErrorV3> {
    Ok(Digest32::of_bytes(&read_external_immutable_file(
        path,
        rollback_root,
        maximum_bytes,
        executable,
    )?))
}

fn wait_bounded(
    child: &mut Child,
    timeout: Duration,
) -> Result<ExitStatus, AgentdPromptCompilerAdapterErrorV3> {
    let started = Instant::now();
    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerUnavailable)?
        {
            return Ok(status);
        }
        if started.elapsed() >= timeout {
            terminate_child(child);
            return Err(AgentdPromptCompilerAdapterErrorV3::TokenizerTimedOut);
        }
        thread::sleep(TOKENIZER_POLL_INTERVAL);
    }
}

fn terminate_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn read_bounded(
    mut reader: impl Read,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdPromptCompilerAdapterErrorV3> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|_| AgentdPromptCompilerAdapterErrorV3::TokenizerUnavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes {
        return Err(AgentdPromptCompilerAdapterErrorV3::TokenizerProtocolInvalid);
    }
    Ok(bytes)
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

#[cfg(test)]
#[path = "prompt_compiler_adapters_tests.rs"]
mod tests;
