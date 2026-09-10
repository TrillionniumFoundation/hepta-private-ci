//! Offline signing boundary for externally controlled H7 authority material.
//!
//! This module deliberately has no connection to the supervisor daemon and
//! never generates keys.  Callers must provide a signing key through an
//! explicit, owner-controlled file descriptor or an owner-only regular file.
//! The request format is tagged JSON so an external ceremony can review the
//! exact inputs before invoking the signer binary.

use std::fs;
use std::fs::File;
use std::io::Read;
use std::path::Path;

use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantSigner;
use crate::signed_authority::H7H89ProductionTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7Artifact;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7OfflineEvaluation;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use codex_hepta_memory::H7SignedArtifactTransition;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;
use zeroize::Zeroize;

/// Maximum bytes accepted from a key file/FD.  This prevents accidentally
/// consuming an unbounded stream while still allowing a textual 64-byte hex
/// seed and a trailing newline.
pub const MAX_SIGNING_KEY_INPUT_BYTES: usize = 4096;

/// Maximum request JSON accepted by the offline signer.
pub const MAX_SIGNING_REQUEST_BYTES: usize = 8 * 1024 * 1024;

/// A reviewable, tagged request understood by the offline signer.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum SignRequest {
    H7Envelope {
        signer_id: String,
        signer_epoch: u64,
        artifact: H7Artifact,
        #[serde(default)]
        ope: Option<H7OfflineEvaluation>,
        transition: H7SignedArtifactTransition,
        expected_runtime_generation: u64,
        #[serde(default)]
        predecessor_artifact_sha256: Option<Sha256Digest>,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    },
    ProductionGrant {
        signer_id: String,
        signer_epoch: u64,
        h7_envelope: H7SignedArtifactEnvelope,
        agent_id: String,
        source_release: String,
        target_release: String,
        transition: H7H89ProductionTransition,
        expected_control_revision: u64,
        expected_lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    },
}

/// Typed output from [`sign_request`].  The caller may serialize the selected
/// envelope directly; the enum keeps the operation boundary explicit.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum SignResponse {
    H7Envelope { envelope: H7SignedArtifactEnvelope },
    ProductionGrant { grant: H7H89ProductionGrant },
}

#[derive(Debug, Error)]
pub enum ExternalSignerError {
    #[error("external signing key source is invalid: {0}")]
    KeySource(String),
    #[error("external signing key input failed: {0}")]
    KeyIo(#[source] std::io::Error),
    #[error("external signing key must be exactly 32 raw bytes or 64 hex characters")]
    KeyEncoding,
    #[error("external signing key contains non-hex data")]
    KeyHex,
    #[error("signing request is too large")]
    RequestTooLarge,
    #[error("signing request JSON is invalid: {0}")]
    RequestJson(#[source] serde_json::Error),
    #[error("H7 signing failed: {0}")]
    H7(String),
    #[error("production grant signing failed: {0}")]
    Grant(String),
}

/// Read an external Ed25519 seed from an owner-only, non-symlink regular file.
/// The file is never written by this module and its bytes are zeroized after
/// conversion to the dalek key type.
pub fn load_signing_key_from_path(path: &Path) -> Result<SigningKey, ExternalSignerError> {
    if !path.is_absolute() {
        return Err(ExternalSignerError::KeySource(
            "signing key path must be absolute".to_string(),
        ));
    }
    let metadata = fs::symlink_metadata(path).map_err(ExternalSignerError::KeyIo)?;
    if !metadata.file_type().is_file() {
        return Err(ExternalSignerError::KeySource(
            "signing key path must be a regular, non-symlink file".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(ExternalSignerError::KeySource(
                "signing key file must not be group/world accessible".to_string(),
            ));
        }
    }
    let mut file = File::open(path).map_err(ExternalSignerError::KeyIo)?;
    read_signing_key(&mut file)
}

/// Read an external Ed25519 seed from an already-open file descriptor.  The
/// descriptor is duplicated on Unix so this function never closes the
/// caller's descriptor.  No key material is generated or persisted.
#[cfg(unix)]
pub fn load_signing_key_from_fd(fd: i32) -> Result<SigningKey, ExternalSignerError> {
    use std::os::fd::FromRawFd;

    if fd < 0 {
        return Err(ExternalSignerError::KeySource(
            "key fd must be non-negative".to_string(),
        ));
    }
    // SAFETY: `dup` returns a new descriptor owned by this function; it is
    // immediately wrapped in File and therefore closed exactly once.
    let duplicate = unsafe { libc::dup(fd) };
    if duplicate < 0 {
        return Err(ExternalSignerError::KeyIo(std::io::Error::last_os_error()));
    }
    // SAFETY: `duplicate` is a valid descriptor returned by dup above.
    let mut file = unsafe { File::from_raw_fd(duplicate) };
    read_signing_key(&mut file)
}

#[cfg(not(unix))]
pub fn load_signing_key_from_fd(_fd: i32) -> Result<SigningKey, ExternalSignerError> {
    Err(ExternalSignerError::KeySource(
        "--key-fd is supported only on Unix hosts".to_string(),
    ))
}

/// Parse a request from a bounded file or stdin (`path == "-"`).
pub fn read_request(path: Option<&Path>) -> Result<SignRequest, ExternalSignerError> {
    let mut bytes = Vec::new();
    match path {
        None => {
            std::io::stdin()
                .take((MAX_SIGNING_REQUEST_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(ExternalSignerError::KeyIo)?;
        }
        Some(path) if path == Path::new("-") => {
            std::io::stdin()
                .take((MAX_SIGNING_REQUEST_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(ExternalSignerError::KeyIo)?;
        }
        Some(path) => {
            let metadata = fs::symlink_metadata(path).map_err(ExternalSignerError::KeyIo)?;
            if !metadata.file_type().is_file() {
                return Err(ExternalSignerError::KeySource(
                    "request path must be a regular, non-symlink file".to_string(),
                ));
            }
            let file = File::open(path).map_err(ExternalSignerError::KeyIo)?;
            file.take((MAX_SIGNING_REQUEST_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(ExternalSignerError::KeyIo)?;
        }
    }
    if bytes.len() > MAX_SIGNING_REQUEST_BYTES {
        bytes.zeroize();
        return Err(ExternalSignerError::RequestTooLarge);
    }
    let result = serde_json::from_slice(&bytes).map_err(ExternalSignerError::RequestJson);
    bytes.zeroize();
    result
}

/// Sign one explicitly supplied request with an externally loaded key.
/// There is intentionally no default request and no key-generation path.
pub fn sign_request(
    request: &SignRequest,
    signing_key: &SigningKey,
) -> Result<SignResponse, ExternalSignerError> {
    match request {
        SignRequest::H7Envelope {
            signer_id,
            signer_epoch,
            artifact,
            ope,
            transition,
            expected_runtime_generation,
            predecessor_artifact_sha256,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        } => {
            let signer =
                H7ArtifactSigner::new(signer_id.clone(), *signer_epoch, signing_key.clone())
                    .map_err(|error| ExternalSignerError::H7(error.to_string()))?;
            let envelope = signer
                .sign(
                    artifact,
                    ope.as_ref(),
                    *transition,
                    *expected_runtime_generation,
                    predecessor_artifact_sha256.clone(),
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::H7(error.to_string()))?;
            Ok(SignResponse::H7Envelope { envelope })
        }
        SignRequest::ProductionGrant {
            signer_id,
            signer_epoch,
            h7_envelope,
            agent_id,
            source_release,
            target_release,
            transition,
            expected_control_revision,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        } => {
            let agent = AgentId::parse(agent_id.clone())
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let signer = H7H89ProductionGrantSigner::new(
                signer_id.clone(),
                *signer_epoch,
                signing_key.clone(),
            )
            .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let grant = signer
                .sign(
                    &agent,
                    source_release.clone(),
                    target_release.clone(),
                    *transition,
                    h7_envelope,
                    *expected_control_revision,
                    *expected_lifecycle_generation,
                    *authority_epoch,
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionGrant { grant })
        }
    }
}

fn read_signing_key(file: &mut File) -> Result<SigningKey, ExternalSignerError> {
    let mut bytes = Vec::new();
    file.take((MAX_SIGNING_KEY_INPUT_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(ExternalSignerError::KeyIo)?;
    if bytes.len() > MAX_SIGNING_KEY_INPUT_BYTES {
        bytes.zeroize();
        return Err(ExternalSignerError::KeyEncoding);
    }
    let result = decode_seed(&bytes).map(|mut seed| {
        let key = SigningKey::from_bytes(&seed);
        seed.zeroize();
        key
    });
    bytes.zeroize();
    result
}

fn decode_seed(bytes: &[u8]) -> Result<[u8; 32], ExternalSignerError> {
    if bytes.len() == 32 {
        let mut seed = [0_u8; 32];
        seed.copy_from_slice(bytes);
        return Ok(seed);
    }
    let text = std::str::from_utf8(bytes)
        .map_err(|_| ExternalSignerError::KeyEncoding)?
        .trim();
    if text.len() != 64 {
        return Err(ExternalSignerError::KeyEncoding);
    }
    let mut seed = [0_u8; 32];
    for (index, pair) in text.as_bytes().as_chunks::<2>().0.iter().enumerate() {
        seed[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Ok(seed)
}

fn hex_value(value: u8) -> Result<u8, ExternalSignerError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        b'A'..=b'F' => Ok(value - b'A' + 10),
        _ => Err(ExternalSignerError::KeyHex),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::signed_authority::H7H89ProductionGrantVerifier;
    use codex_hepta_memory::H7ArtifactVerifier;
    use codex_hepta_memory::H7QualificationRuntime;
    use codex_hepta_memory::H7TrajectoryEvent;
    use std::io::Seek;
    use std::io::Write;

    fn digest(seed: u8) -> Sha256Digest {
        Sha256Digest::for_bytes(&[seed; 8])
    }

    fn fixture_artifact() -> H7Artifact {
        let mut runtime = H7QualificationRuntime::new();
        let event = H7TrajectoryEvent::new(
            "authority-cli-fixture",
            1,
            "reload",
            100,
            true,
            1,
            1,
            1,
            digest(1),
        )
        .expect("fixture event");
        runtime.append_trajectory_event(event).expect("append");
        runtime
            .evaluate_trajectory("authority-cli-fixture")
            .expect("evaluate");
        runtime
            .propose_artifact("authority-cli-artifact", "authority-cli-fixture", 1)
            .expect("artifact")
    }

    #[test]
    fn raw_and_hex_external_key_inputs_are_supported_without_generation() {
        let temp = tempfile::tempdir().expect("tempdir");
        let raw_path = temp.path().join("raw.key");
        let hex_path = temp.path().join("hex.key");
        let raw = [7_u8; 32];
        std::fs::write(&raw_path, raw).expect("write raw fixture");
        let hex = raw
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        std::fs::write(&hex_path, hex).expect("write hex fixture");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&raw_path, std::fs::Permissions::from_mode(0o600))
                .expect("raw permissions");
            std::fs::set_permissions(&hex_path, std::fs::Permissions::from_mode(0o600))
                .expect("hex permissions");
        }
        assert_eq!(
            load_signing_key_from_path(&raw_path)
                .expect("raw key")
                .to_bytes(),
            raw
        );
        assert_eq!(
            load_signing_key_from_path(&hex_path)
                .expect("hex key")
                .to_bytes(),
            raw
        );
    }

    #[test]
    fn request_boundary_signs_and_verifies_h7_envelope() {
        let artifact = fixture_artifact();
        let request = SignRequest::H7Envelope {
            signer_id: "external-h7".to_string(),
            signer_epoch: 4,
            artifact: artifact.clone(),
            ope: None,
            transition: H7SignedArtifactTransition::Reload,
            expected_runtime_generation: 0,
            predecessor_artifact_sha256: None,
            issued_at_unix_seconds: 100,
            expires_at_unix_seconds: 200,
        };
        let response =
            sign_request(&request, &SigningKey::from_bytes(&[7; 32])).expect("sign request");
        let SignResponse::H7Envelope { envelope } = response else {
            panic!("wrong response");
        };
        let verifier = H7ArtifactVerifier::from_bytes(
            "external-h7",
            4,
            SigningKey::from_bytes(&[7; 32]).verifying_key().to_bytes(),
        )
        .expect("verifier");
        verifier
            .verify(&envelope, &artifact, None, 150, 0, None)
            .expect("verify envelope");
    }

    #[test]
    fn request_boundary_signs_and_verifies_production_grant() {
        let artifact = fixture_artifact();
        let h7_signer = H7ArtifactSigner::new("external-h7", 4, SigningKey::from_bytes(&[7; 32]))
            .expect("h7 signer");
        let h7_envelope = h7_signer
            .sign(
                &artifact,
                None,
                H7SignedArtifactTransition::Reload,
                0,
                None,
                100,
                200,
            )
            .expect("h7 envelope");
        let request = SignRequest::ProductionGrant {
            signer_id: "external-grant".to_string(),
            signer_epoch: 9,
            h7_envelope: h7_envelope.clone(),
            agent_id: "00000000-0000-4000-8000-000000000001".to_string(),
            source_release: "release-a".to_string(),
            target_release: "release-b".to_string(),
            transition: H7H89ProductionTransition::Upgrade,
            expected_control_revision: 3,
            expected_lifecycle_generation: 1,
            authority_epoch: 8,
            issued_at_unix_seconds: 100,
            expires_at_unix_seconds: 200,
        };
        let response =
            sign_request(&request, &SigningKey::from_bytes(&[9; 32])).expect("sign grant request");
        let SignResponse::ProductionGrant { grant } = response else {
            panic!("wrong response");
        };
        let h7_verifier = h7_signer.verifier();
        let verifier = H7H89ProductionGrantVerifier::from_bytes_with_h7_verifier(
            "external-grant",
            9,
            SigningKey::from_bytes(&[9; 32]).verifying_key().to_bytes(),
            h7_verifier,
        )
        .expect("grant verifier");
        verifier
            .verify(
                &grant,
                &h7_envelope,
                &AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent"),
                "release-a",
                "release-b",
                3,
                1,
                8,
                150,
            )
            .expect("verify grant");
    }

    #[test]
    fn request_json_is_tagged_and_rejects_unknown_fields() {
        let artifact = fixture_artifact();
        let request = SignRequest::H7Envelope {
            signer_id: "external-h7".to_string(),
            signer_epoch: 1,
            artifact,
            ope: None,
            transition: H7SignedArtifactTransition::Reload,
            expected_runtime_generation: 0,
            predecessor_artifact_sha256: None,
            issued_at_unix_seconds: 10,
            expires_at_unix_seconds: 20,
        };
        let json = serde_json::to_vec(&request).expect("serialize");
        let decoded: SignRequest = serde_json::from_slice(&json).expect("decode");
        assert!(matches!(decoded, SignRequest::H7Envelope { .. }));
        let mut object: serde_json::Map<String, serde_json::Value> =
            serde_json::from_slice(&json).expect("object");
        object.insert("unexpected".to_string(), serde_json::Value::Bool(true));
        assert!(serde_json::from_value::<SignRequest>(serde_json::Value::Object(object)).is_err());
    }

    #[test]
    fn fd_loader_does_not_consume_or_close_caller_descriptor() {
        #[cfg(unix)]
        {
            use std::os::fd::AsRawFd;
            let mut file = tempfile::tempfile().expect("tempfile");
            file.write_all(&[8_u8; 32]).expect("write key");
            file.rewind().expect("rewind");
            let fd = file.as_raw_fd();
            let key = load_signing_key_from_fd(fd).expect("fd key");
            assert_eq!(key.to_bytes(), [8_u8; 32]);
            assert!(file.metadata().is_ok());
        }
    }
}
