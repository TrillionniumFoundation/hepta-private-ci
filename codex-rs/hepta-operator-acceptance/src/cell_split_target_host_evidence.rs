//! Signed external target-host evidence for DecisionCell split qualification.
//!
//! This module is deliberately an ingestion and verification boundary.  The
//! existing [`CellSplitTargetHostHarnessV1`](super::CellSplitTargetHostHarnessV1)
//! remains a source-simulation fixture; it cannot manufacture a production
//! receipt.  A real target host must export this event log, sign the canonical
//! payload, and have an independent observer sign the same payload before the
//! strict production gate can accept it.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD as BASE64;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ed25519_dalek::Verifier;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;
use thiserror::Error;

use crate::durable::canonical_json;
use crate::durable::sha256;

pub const CELL_SPLIT_TARGET_HOST_EVIDENCE_SCHEMA_V1: &str =
    "hepta.learning.cell-split.target-host-evidence.v1";
pub const CELL_SPLIT_SIGNED_TARGET_HOST_EVIDENCE_SCHEMA_V1: &str =
    "hepta.learning.cell-split.target-host-signed-evidence.v1";
pub const CELL_SPLIT_TARGET_HOST_EVIDENCE_SIGNATURE_ALGORITHM_V1: &str =
    "ed25519-canonical-json-v1";
pub const CELL_SPLIT_TARGET_HOST_EVIDENCE_STORE_SCHEMA_V1: &str =
    "hepta.learning.cell-split.target-host-evidence-store.v1";
pub const CELL_SPLIT_TARGET_HOST_TRUST_POLICY_SCHEMA_V1: &str =
    "hepta.learning.cell-split.target-host-trust-policy.v1";

const EVIDENCE_SCHEMA: &str = CELL_SPLIT_TARGET_HOST_EVIDENCE_SCHEMA_V1;
const ENVELOPE_SCHEMA: &str = CELL_SPLIT_SIGNED_TARGET_HOST_EVIDENCE_SCHEMA_V1;
const PRODUCTION_ORIGIN: &str = "production-target-host";
#[cfg(test)]
const SIMULATION_ORIGIN: &str = "source-simulation";
const SIGNATURE_ALGORITHM: &str = CELL_SPLIT_TARGET_HOST_EVIDENCE_SIGNATURE_ALGORITHM_V1;
const MAX_EVENTS: usize = 4_096;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

/// The host class that produced a resource sample.  A production receipt must
/// contain at least one sample for the selected target class and cannot use a
/// simulation marker as its measurement source.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum CellSplitTargetHardwareV1 {
    Cpu,
    Gpu,
    Npu,
}

/// Operations that a target host must witness in its append-only event log.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum CellSplitTargetHostEventKindV1 {
    ArtifactLoaded,
    RouteCutover,
    RestartRecovered,
    PowerLossRecovered,
    RollbackCompleted,
    TombstoneCommitted,
    NoResurrectionVerified,
    ResourceMeasurement,
}

/// A real resource sample collected by the target host.  Values are kept as
/// integer counters so replay is deterministic across languages and hosts.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitTargetResourceSampleV1 {
    pub hardware: CellSplitTargetHardwareV1,
    pub hardware_model: String,
    pub measurement_source: String,
    pub hardware_attestation_digest: String,
    pub sample_count: u32,
    pub latency_micros: u64,
    pub memory_bytes: u64,
    pub communication_bytes: u64,
    pub training_micros: u64,
    pub migration_micros: u64,
}

/// One externally observed host event.  `eventDigest` covers the complete
/// event with that field empty and the previous event digest prepended, making
/// the event log tamper evident and replayable.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitTargetHostEventV1 {
    pub sequence: u64,
    pub event_kind: CellSplitTargetHostEventKindV1,
    pub occurred_at_unix_nanos: u128,
    pub split_id: String,
    pub target_host_id: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub operation_id: String,
    pub artifact_digest: String,
    pub route_digest: String,
    pub predecessor_digest: String,
    pub tombstone_digest: String,
    pub fault_injection_digest: String,
    pub receipt_digest: String,
    pub resource: Option<CellSplitTargetResourceSampleV1>,
    pub previous_event_digest: String,
    pub event_digest: String,
}

/// Unsigned canonical payload exported by a real target host.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitTargetHostEvidenceV1 {
    pub schema: String,
    pub schema_version: u32,
    pub origin: String,
    pub split_id: String,
    pub target_host_id: String,
    pub target_host_nonce: String,
    pub target_host_attestation_digest: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub parent_artifact_digest: String,
    pub child_artifact_digest: String,
    pub events: Vec<CellSplitTargetHostEventV1>,
    pub evidence_digest: String,
}

/// Detached signature by the target host owner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitTargetHostSignatureV1 {
    pub signer_id: String,
    pub verifying_key_base64: String,
    pub signature_base64: String,
}

/// Signed evidence envelope.  The independent observer signs the exact same
/// canonical payload; the gate checks that observer identity is different from
/// the host signer and belongs to the externally supplied trust policy.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSignedTargetHostEvidenceV1 {
    pub schema: String,
    pub schema_version: u32,
    pub signature_algorithm: String,
    pub payload: CellSplitTargetHostEvidenceV1,
    pub host_signature: CellSplitTargetHostSignatureV1,
    pub observer_signatures: Vec<CellSplitTargetHostSignatureV1>,
}

/// Trust material supplied out of band by the deployment owner.  Public keys
/// are deliberately not trusted merely because they appear in the evidence.
#[derive(Clone, Debug, Default)]
pub struct CellSplitTargetHostEvidenceTrustPolicyV1 {
    pub host_keys: BTreeMap<String, VerifyingKey>,
    pub observer_keys: BTreeMap<String, VerifyingKey>,
}

/// JSON transport form for the externally pinned trust policy used by the
/// target-host evidence ingest command.  The key material is supplied by the
/// deployment owner; it is never inferred from an evidence envelope.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitTargetHostEvidenceTrustPolicyFileV1 {
    pub schema: String,
    pub schema_version: u32,
    pub host_keys: BTreeMap<String, String>,
    pub observer_keys: BTreeMap<String, String>,
}

impl CellSplitTargetHostEvidenceTrustPolicyV1 {
    /// Decode an externally supplied JSON trust policy.  The file contains
    /// base64 encoded Ed25519 public keys and is intentionally independent of
    /// the signed evidence envelope.
    pub fn from_json_bytes(bytes: &[u8]) -> Result<Self, CellSplitTargetHostEvidenceErrorV1> {
        let file: CellSplitTargetHostEvidenceTrustPolicyFileV1 = serde_json::from_slice(bytes)?;
        if file.schema != CELL_SPLIT_TARGET_HOST_TRUST_POLICY_SCHEMA_V1
            || file.schema_version != 1
            || file.host_keys.is_empty()
            || file.observer_keys.is_empty()
        {
            return Err(invalid("target-host trust policy header"));
        }
        let host_keys = decode_trusted_keys(file.host_keys, "host")?;
        let observer_keys = decode_trusted_keys(file.observer_keys, "observer")?;
        Ok(Self {
            host_keys,
            observer_keys,
        })
    }

    /// Decode a trust policy from a regular file using the same race and
    /// symlink checks as the durable evidence store.
    pub fn from_json_file(
        path: impl AsRef<Path>,
    ) -> Result<Self, CellSplitTargetHostEvidenceErrorV1> {
        let bytes =
            crate::durable::secure_read(path.as_ref(), crate::durable::MAX_SMALL_FILE_BYTES)
                .map_err(|error| durable_error(error.to_string()))?;
        Self::from_json_bytes(&bytes)
    }

    /// Serialize the transport form for deployment tooling that persists an
    /// externally pinned policy.  This method never creates a signature or a
    /// production receipt.
    pub fn to_json_bytes(&self) -> Result<Vec<u8>, CellSplitTargetHostEvidenceErrorV1> {
        if self.host_keys.is_empty() || self.observer_keys.is_empty() {
            return Err(invalid("target-host trust policy is empty"));
        }
        let file = CellSplitTargetHostEvidenceTrustPolicyFileV1 {
            schema: CELL_SPLIT_TARGET_HOST_TRUST_POLICY_SCHEMA_V1.to_string(),
            schema_version: 1,
            host_keys: encode_trusted_keys(&self.host_keys),
            observer_keys: encode_trusted_keys(&self.observer_keys),
        };
        canonical(&file)
    }
}

/// Adapter used by the durable acceptance owner to ingest a report exported by
/// a real target host.  It carries the externally pinned trust policy and does
/// not expose a way to elevate the source simulation harness.
#[derive(Clone, Debug)]
pub struct CellSplitTargetHostEvidenceAdapterV1 {
    policy: CellSplitTargetHostEvidenceTrustPolicyV1,
}

impl CellSplitTargetHostEvidenceAdapterV1 {
    #[must_use]
    pub fn new(policy: CellSplitTargetHostEvidenceTrustPolicyV1) -> Self {
        Self { policy }
    }

    pub fn ingest_json(
        &self,
        bytes: &[u8],
    ) -> Result<CellSplitTargetHostProductionReceiptV1, CellSplitTargetHostEvidenceErrorV1> {
        verify_cell_split_target_host_evidence_json(bytes, &self.policy)
    }

    pub fn ingest_envelope(
        &self,
        envelope: &CellSplitSignedTargetHostEvidenceV1,
    ) -> Result<CellSplitTargetHostProductionReceiptV1, CellSplitTargetHostEvidenceErrorV1> {
        verify_cell_split_target_host_evidence(envelope, &self.policy)
    }
}

/// Durable owner for an already signed target-host evidence envelope.
///
/// The owner verifies the envelope against the externally pinned trust policy
/// before writing it, uses the same private atomic-replace protocol as the
/// operator acceptance sidecars, and verifies the exact persisted bytes on
/// reopen.  It deliberately accepts no unsigned payload and never creates a
/// production receipt from the source simulation harness.
#[derive(Clone, Copy, Debug, Default)]
pub struct CellSplitTargetHostEvidenceStoreV1;

impl CellSplitTargetHostEvidenceStoreV1 {
    /// Verify an evidence byte stream without writing it.  This is the
    /// command-line ingest/verify path and still issues a receipt only after
    /// all signed lifecycle checks pass.
    pub fn verify_bytes(
        bytes: &[u8],
        policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    ) -> Result<CellSplitTargetHostProductionReceiptV1, CellSplitTargetHostEvidenceErrorV1> {
        verify_cell_split_target_host_evidence_json(bytes, policy)
    }

    /// Read an evidence file through the same bounded, no-follow reader used
    /// by the durable store.  The CLI uses `-` for stdin separately.
    pub fn read_input(
        path: impl AsRef<Path>,
    ) -> Result<Vec<u8>, CellSplitTargetHostEvidenceErrorV1> {
        crate::durable::secure_read(path.as_ref(), crate::durable::MAX_SMALL_FILE_BYTES)
            .map_err(|error| durable_error(error.to_string()))
    }

    pub fn persist(
        path: impl AsRef<Path>,
        envelope: &CellSplitSignedTargetHostEvidenceV1,
        policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    ) -> Result<CellSplitTargetHostProductionReceiptV1, CellSplitTargetHostEvidenceErrorV1> {
        let receipt = verify_cell_split_target_host_evidence(envelope, policy)?;
        let bytes = envelope.canonical_bytes()?;
        let path = path.as_ref();
        let temporary = path.with_extension("target-host-evidence.tmp");
        crate::durable::write_private_atomic_replace(path, &temporary, &bytes)
            .map_err(|error| durable_error(error.to_string()))?;
        Ok(receipt)
    }

    pub fn reopen(
        path: impl AsRef<Path>,
        policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    ) -> Result<
        (
            CellSplitSignedTargetHostEvidenceV1,
            CellSplitTargetHostProductionReceiptV1,
        ),
        CellSplitTargetHostEvidenceErrorV1,
    > {
        let bytes =
            crate::durable::secure_read(path.as_ref(), crate::durable::MAX_SMALL_FILE_BYTES)
                .map_err(|error| durable_error(error.to_string()))?;
        let envelope: CellSplitSignedTargetHostEvidenceV1 = serde_json::from_slice(&bytes)?;
        if envelope.canonical_bytes()? != bytes {
            return Err(invalid("stored target-host evidence is not canonical JSON"));
        }
        let receipt = verify_cell_split_target_host_evidence(&envelope, policy)?;
        Ok((envelope, receipt))
    }
}

/// Gate output that can be persisted by the durable acceptance owner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitTargetHostProductionReceiptV1 {
    pub schema: String,
    pub evidence_digest: String,
    pub replay_digest: String,
    pub host_signature_digest: String,
    pub observer_signature_digests: Vec<String>,
    pub target_host_id: String,
    pub split_id: String,
    pub hardware: BTreeSet<CellSplitTargetHardwareV1>,
    pub event_count: usize,
    pub resource_sample_count: usize,
    pub production_gate_passed: bool,
}

#[derive(Debug, Error)]
pub enum CellSplitTargetHostEvidenceErrorV1 {
    #[error("target-host evidence is invalid: {0}")]
    Invalid(String),
    #[error("target-host evidence encoding failed: {0}")]
    Encoding(#[from] serde_json::Error),
    #[error("target-host evidence canonicalization failed: {0}")]
    Canonical(String),
}

/// Append-only recorder used by a real target-host adapter.  It computes the
/// hash chain and leaves signatures to the host/observer key owners.
#[derive(Clone, Debug)]
pub struct CellSplitTargetHostEvidenceRecorderV1 {
    payload: CellSplitTargetHostEvidenceV1,
}

impl CellSplitTargetHostEvidenceRecorderV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        split_id: impl Into<String>,
        target_host_id: impl Into<String>,
        target_host_nonce: impl Into<String>,
        target_host_attestation_digest: impl Into<String>,
        parent_generation: u64,
        child_generation: u64,
        parent_artifact_digest: impl Into<String>,
        child_artifact_digest: impl Into<String>,
    ) -> Result<Self, CellSplitTargetHostEvidenceErrorV1> {
        let payload = CellSplitTargetHostEvidenceV1 {
            schema: EVIDENCE_SCHEMA.to_string(),
            schema_version: 1,
            origin: PRODUCTION_ORIGIN.to_string(),
            split_id: split_id.into(),
            target_host_id: target_host_id.into(),
            target_host_nonce: target_host_nonce.into(),
            target_host_attestation_digest: target_host_attestation_digest.into(),
            parent_generation,
            child_generation,
            parent_artifact_digest: parent_artifact_digest.into(),
            child_artifact_digest: child_artifact_digest.into(),
            events: Vec::new(),
            evidence_digest: String::new(),
        };
        let recorder = Self { payload };
        recorder.validate_header()?;
        Ok(recorder)
    }

    pub fn append(
        &mut self,
        mut event: CellSplitTargetHostEventV1,
    ) -> Result<(), CellSplitTargetHostEvidenceErrorV1> {
        if self.payload.events.len() >= MAX_EVENTS {
            return Err(invalid("event count exceeds replay bound"));
        }
        let expected_sequence = self.payload.events.len() as u64 + 1;
        let previous = self
            .payload
            .events
            .last()
            .map_or(ZERO_DIGEST, |item| item.event_digest.as_str());
        if event.sequence != expected_sequence
            || event.split_id != self.payload.split_id
            || event.target_host_id != self.payload.target_host_id
            || event.parent_generation != self.payload.parent_generation
            || event.child_generation != self.payload.child_generation
            || event.previous_event_digest != previous
            || event.operation_id.is_empty()
            || event.receipt_digest.is_empty()
            || event.occurred_at_unix_nanos == 0
        {
            return Err(invalid("event identity, sequence or chain precondition"));
        }
        event.event_digest = String::new();
        let digest = event_digest(&event)?;
        event.event_digest = digest;
        self.payload.events.push(event);
        self.payload.evidence_digest = String::new();
        Ok(())
    }

    /// Return the sequence number and predecessor digest that a real target
    /// host must put on its next event.  The recorder keeps the hash-chain
    /// state private so an external adapter cannot accidentally fork it; the
    /// event's `event_digest` may be left empty because `append` computes it.
    #[must_use]
    pub fn next_event_context(&self) -> (u64, String) {
        let sequence = self.payload.events.len() as u64 + 1;
        let previous = self
            .payload
            .events
            .last()
            .map_or_else(|| ZERO_DIGEST.to_string(), |item| item.event_digest.clone());
        (sequence, previous)
    }

    /// Number of events already accepted by the append-only recorder.
    #[must_use]
    pub fn event_count(&self) -> usize {
        self.payload.events.len()
    }

    /// Identity metadata copied into each event by an external lifecycle
    /// runner. The recorder keeps the payload itself private so callers must
    /// still use `append` for sequence and hash-chain validation.
    #[must_use]
    pub fn split_id(&self) -> &str {
        &self.payload.split_id
    }

    #[must_use]
    pub fn target_host_id(&self) -> &str {
        &self.payload.target_host_id
    }

    #[must_use]
    pub const fn parent_generation(&self) -> u64 {
        self.payload.parent_generation
    }

    #[must_use]
    pub const fn child_generation(&self) -> u64 {
        self.payload.child_generation
    }

    pub fn finish(
        mut self,
    ) -> Result<CellSplitTargetHostEvidenceV1, CellSplitTargetHostEvidenceErrorV1> {
        self.payload.evidence_digest = evidence_digest(&self.payload)?;
        replay_payload(&self.payload)?;
        Ok(self.payload)
    }

    fn validate_header(&self) -> Result<(), CellSplitTargetHostEvidenceErrorV1> {
        let p = &self.payload;
        if p.schema != EVIDENCE_SCHEMA
            || p.schema_version != 1
            || p.origin != PRODUCTION_ORIGIN
            || p.split_id.is_empty()
            || p.target_host_id.is_empty()
            || p.target_host_nonce.is_empty()
            || !digest_shape(&p.target_host_attestation_digest)
            || p.parent_generation == 0
            || p.child_generation != p.parent_generation.saturating_add(1)
            || !digest_shape(&p.parent_artifact_digest)
            || !digest_shape(&p.child_artifact_digest)
        {
            return Err(invalid("production target-host header"));
        }
        Ok(())
    }
}

impl CellSplitTargetHostEvidenceV1 {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, CellSplitTargetHostEvidenceErrorV1> {
        canonical(self)
    }

    /// Sign the canonical payload with the target-host key and one or more
    /// independent observer keys.
    pub fn sign(
        &self,
        host_signer_id: impl Into<String>,
        host_key: &SigningKey,
        observers: impl IntoIterator<Item = (String, SigningKey)>,
    ) -> Result<CellSplitSignedTargetHostEvidenceV1, CellSplitTargetHostEvidenceErrorV1> {
        replay_payload(self)?;
        let bytes = self.canonical_bytes()?;
        let host_signature = sign_payload(host_signer_id.into(), host_key, &bytes);
        let observer_signatures = observers
            .into_iter()
            .map(|(signer_id, key)| sign_payload(signer_id, &key, &bytes))
            .collect();
        Ok(CellSplitSignedTargetHostEvidenceV1 {
            schema: ENVELOPE_SCHEMA.to_string(),
            schema_version: 1,
            signature_algorithm: SIGNATURE_ALGORITHM.to_string(),
            payload: self.clone(),
            host_signature,
            observer_signatures,
        })
    }
}

impl CellSplitSignedTargetHostEvidenceV1 {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, CellSplitTargetHostEvidenceErrorV1> {
        canonical(self)
    }
}

/// Verify a signed JSON report and issue a strict production receipt.
pub fn verify_cell_split_target_host_evidence_json(
    bytes: &[u8],
    policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
) -> Result<CellSplitTargetHostProductionReceiptV1, CellSplitTargetHostEvidenceErrorV1> {
    let envelope: CellSplitSignedTargetHostEvidenceV1 = serde_json::from_slice(bytes)?;
    verify_cell_split_target_host_evidence(&envelope, policy)
}

/// Verify the signed envelope.  This is the only API that can produce a
/// production receipt; source simulation reports never enter this path.
pub fn verify_cell_split_target_host_evidence(
    envelope: &CellSplitSignedTargetHostEvidenceV1,
    policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
) -> Result<CellSplitTargetHostProductionReceiptV1, CellSplitTargetHostEvidenceErrorV1> {
    if envelope.schema != ENVELOPE_SCHEMA
        || envelope.schema_version != 1
        || envelope.signature_algorithm != SIGNATURE_ALGORITHM
    {
        return Err(invalid("signed evidence envelope header"));
    }
    let payload = &envelope.payload;
    replay_payload(payload)?;
    let payload_bytes = payload.canonical_bytes()?;
    let host_key = policy
        .host_keys
        .get(&envelope.host_signature.signer_id)
        .ok_or_else(|| invalid("host signer is not trusted"))?;
    verify_signature(&envelope.host_signature, host_key, &payload_bytes)?;
    if envelope.observer_signatures.is_empty() {
        return Err(invalid("independent observer signature is required"));
    }
    let mut observer_ids = BTreeSet::new();
    let mut observer_signature_digests = Vec::with_capacity(envelope.observer_signatures.len());
    for signature in &envelope.observer_signatures {
        if signature.signer_id == envelope.host_signature.signer_id
            || !observer_ids.insert(signature.signer_id.clone())
        {
            return Err(invalid("observer must be independent and unique"));
        }
        let observer_key = policy
            .observer_keys
            .get(&signature.signer_id)
            .ok_or_else(|| invalid("observer signer is not trusted"))?;
        if observer_key == host_key {
            return Err(invalid("observer key must be independent from host key"));
        }
        verify_signature(signature, observer_key, &payload_bytes)?;
        observer_signature_digests.push(signature_digest(signature)?);
    }
    let mut hardware = BTreeSet::new();
    let mut resource_sample_count = 0;
    for event in &payload.events {
        if let Some(sample) = &event.resource {
            resource_sample_count += 1;
            validate_resource(sample)?;
            hardware.insert(sample.hardware);
        }
    }
    if resource_sample_count == 0 {
        return Err(invalid("target-host resource measurement is required"));
    }
    Ok(CellSplitTargetHostProductionReceiptV1 {
        schema: "hepta.learning.cell-split.target-host-production-receipt.v1".to_string(),
        evidence_digest: payload.evidence_digest.clone(),
        replay_digest: replay_digest(payload)?,
        host_signature_digest: signature_digest(&envelope.host_signature)?,
        observer_signature_digests,
        target_host_id: payload.target_host_id.clone(),
        split_id: payload.split_id.clone(),
        hardware,
        event_count: payload.events.len(),
        resource_sample_count,
        production_gate_passed: true,
    })
}

fn sign_payload(
    signer_id: String,
    key: &SigningKey,
    payload: &[u8],
) -> CellSplitTargetHostSignatureV1 {
    CellSplitTargetHostSignatureV1 {
        signer_id,
        verifying_key_base64: BASE64.encode(key.verifying_key().to_bytes()),
        signature_base64: BASE64.encode(key.sign(payload).to_bytes()),
    }
}

fn decode_trusted_keys(
    encoded: BTreeMap<String, String>,
    role: &str,
) -> Result<BTreeMap<String, VerifyingKey>, CellSplitTargetHostEvidenceErrorV1> {
    let mut decoded = BTreeMap::new();
    for (signer_id, value) in encoded {
        if signer_id.is_empty() {
            return Err(invalid(format!("duplicate or empty {role} signer id")));
        }
        let bytes = BASE64
            .decode(value)
            .map_err(|_| invalid(format!("malformed {role} verifying key")))?;
        let bytes: [u8; 32] = bytes
            .try_into()
            .map_err(|_| invalid(format!("{role} verifying key must be 32 bytes")))?;
        let key = VerifyingKey::from_bytes(&bytes)
            .map_err(|_| invalid(format!("malformed {role} verifying key")))?;
        if decoded.insert(signer_id, key).is_some() {
            return Err(invalid(format!("duplicate {role} signer id")));
        }
    }
    Ok(decoded)
}

fn encode_trusted_keys(keys: &BTreeMap<String, VerifyingKey>) -> BTreeMap<String, String> {
    keys.iter()
        .map(|(signer_id, key)| (signer_id.clone(), BASE64.encode(key.to_bytes())))
        .collect()
}

fn verify_signature(
    signature: &CellSplitTargetHostSignatureV1,
    expected_key: &VerifyingKey,
    payload: &[u8],
) -> Result<(), CellSplitTargetHostEvidenceErrorV1> {
    let key_bytes = BASE64
        .decode(&signature.verifying_key_base64)
        .map_err(|_| invalid("malformed verifying key"))?;
    if key_bytes != expected_key.to_bytes() {
        return Err(invalid("evidence key differs from trusted key"));
    }
    let signature_bytes = BASE64
        .decode(&signature.signature_base64)
        .map_err(|_| invalid("malformed signature"))?;
    let signature = Signature::from_slice(&signature_bytes)
        .map_err(|_| invalid("malformed Ed25519 signature"))?;
    expected_key
        .verify(payload, &signature)
        .map_err(|_| invalid("signature verification failed"))
}

fn replay_payload(
    payload: &CellSplitTargetHostEvidenceV1,
) -> Result<(), CellSplitTargetHostEvidenceErrorV1> {
    if payload.schema != EVIDENCE_SCHEMA
        || payload.schema_version != 1
        || payload.origin != PRODUCTION_ORIGIN
        || payload.split_id.is_empty()
        || payload.target_host_id.is_empty()
        || payload.target_host_nonce.is_empty()
        || !digest_shape(&payload.target_host_attestation_digest)
        || payload.parent_generation == 0
        || payload.child_generation != payload.parent_generation.saturating_add(1)
        || !digest_shape(&payload.parent_artifact_digest)
        || !digest_shape(&payload.child_artifact_digest)
        || payload.events.is_empty()
        || payload.events.len() > MAX_EVENTS
    {
        return Err(invalid("production payload header"));
    }
    let required = [
        CellSplitTargetHostEventKindV1::ArtifactLoaded,
        CellSplitTargetHostEventKindV1::RouteCutover,
        CellSplitTargetHostEventKindV1::RestartRecovered,
        CellSplitTargetHostEventKindV1::PowerLossRecovered,
        CellSplitTargetHostEventKindV1::RollbackCompleted,
        CellSplitTargetHostEventKindV1::TombstoneCommitted,
        CellSplitTargetHostEventKindV1::NoResurrectionVerified,
    ];
    let mut seen = BTreeSet::new();
    let mut previous_kind = None;
    let mut previous_digest = ZERO_DIGEST.to_string();
    let mut previous_timestamp = 0_u128;
    let mut operation_ids = BTreeSet::new();
    let mut receipt_digests = BTreeSet::new();
    for (offset, event) in payload.events.iter().enumerate() {
        if event.sequence != offset as u64 + 1
            || event.split_id != payload.split_id
            || event.target_host_id != payload.target_host_id
            || event.parent_generation != payload.parent_generation
            || event.child_generation != payload.child_generation
            || event.previous_event_digest != previous_digest
            || event.operation_id.is_empty()
            || event.receipt_digest.is_empty()
            || event.occurred_at_unix_nanos <= previous_timestamp
            || !operation_ids.insert(event.operation_id.clone())
            || !receipt_digests.insert(event.receipt_digest.clone())
            || event.event_digest != event_digest(event)?
        {
            return Err(invalid("event replay or hash chain"));
        }
        validate_event_payload(event, payload)?;
        if !matches!(
            event.event_kind,
            CellSplitTargetHostEventKindV1::ResourceMeasurement
        ) {
            if let Some(previous_kind) = previous_kind
                && event_order(event.event_kind) < event_order(previous_kind)
            {
                return Err(invalid("event lifecycle order regressed"));
            }
            if !seen.insert(event.event_kind) {
                return Err(invalid("duplicate lifecycle event"));
            }
            previous_kind = Some(event.event_kind);
        }
        previous_digest = event.event_digest.clone();
        previous_timestamp = event.occurred_at_unix_nanos;
    }
    if required.iter().any(|kind| !seen.contains(kind)) {
        return Err(invalid("required target-host event is missing"));
    }
    if payload.evidence_digest != evidence_digest(payload)? {
        return Err(invalid("evidence digest does not match canonical payload"));
    }
    Ok(())
}

fn validate_event_payload(
    event: &CellSplitTargetHostEventV1,
    payload: &CellSplitTargetHostEvidenceV1,
) -> Result<(), CellSplitTargetHostEvidenceErrorV1> {
    match event.event_kind {
        CellSplitTargetHostEventKindV1::ArtifactLoaded => {
            if event.artifact_digest != payload.child_artifact_digest {
                return Err(invalid("loaded artifact differs from child artifact"));
            }
        }
        CellSplitTargetHostEventKindV1::RouteCutover => {
            if event.route_digest.is_empty() || event.predecessor_digest.is_empty() {
                return Err(invalid("route cutover receipt is incomplete"));
            }
        }
        CellSplitTargetHostEventKindV1::RestartRecovered => {
            if event.receipt_digest.is_empty() {
                return Err(invalid("restart recovery receipt is incomplete"));
            }
        }
        CellSplitTargetHostEventKindV1::PowerLossRecovered => {
            if event.receipt_digest.is_empty() || !digest_shape(&event.fault_injection_digest) {
                return Err(invalid("power-loss witness is incomplete"));
            }
        }
        CellSplitTargetHostEventKindV1::RollbackCompleted => {
            if event.predecessor_digest.is_empty() {
                return Err(invalid("rollback predecessor is missing"));
            }
        }
        CellSplitTargetHostEventKindV1::TombstoneCommitted => {
            if !digest_shape(&event.tombstone_digest) {
                return Err(invalid("tombstone digest is malformed"));
            }
        }
        CellSplitTargetHostEventKindV1::NoResurrectionVerified => {
            if event.tombstone_digest.is_empty() || event.predecessor_digest.is_empty() {
                return Err(invalid("no-resurrection witness is incomplete"));
            }
        }
        CellSplitTargetHostEventKindV1::ResourceMeasurement => {
            let resource = event
                .resource
                .as_ref()
                .ok_or_else(|| invalid("resource event has no sample"))?;
            validate_resource(resource)?;
        }
    }
    Ok(())
}

fn validate_resource(
    resource: &CellSplitTargetResourceSampleV1,
) -> Result<(), CellSplitTargetHostEvidenceErrorV1> {
    if resource.hardware_model.is_empty()
        || resource.measurement_source.is_empty()
        || resource.measurement_source.contains("simulation")
        || resource.measurement_source.contains("fixture")
        || !digest_shape(&resource.hardware_attestation_digest)
        || resource.sample_count == 0
        || resource.latency_micros == 0
        || resource.memory_bytes == 0
    {
        return Err(invalid("resource sample is not target-host measured"));
    }
    Ok(())
}

fn event_order(kind: CellSplitTargetHostEventKindV1) -> u8 {
    match kind {
        CellSplitTargetHostEventKindV1::ArtifactLoaded => 1,
        CellSplitTargetHostEventKindV1::RouteCutover => 2,
        CellSplitTargetHostEventKindV1::RestartRecovered => 3,
        CellSplitTargetHostEventKindV1::PowerLossRecovered => 4,
        CellSplitTargetHostEventKindV1::RollbackCompleted => 5,
        CellSplitTargetHostEventKindV1::TombstoneCommitted => 6,
        CellSplitTargetHostEventKindV1::NoResurrectionVerified => 7,
        CellSplitTargetHostEventKindV1::ResourceMeasurement => 0,
    }
}

fn event_digest(
    event: &CellSplitTargetHostEventV1,
) -> Result<String, CellSplitTargetHostEvidenceErrorV1> {
    let mut unsigned = event.clone();
    unsigned.event_digest.clear();
    let bytes = canonical(&unsigned)?;
    let mut hasher = Sha256::new();
    hasher.update(event.previous_event_digest.as_bytes());
    hasher.update(bytes);
    Ok(format!("{:x}", hasher.finalize()))
}

fn evidence_digest(
    payload: &CellSplitTargetHostEvidenceV1,
) -> Result<String, CellSplitTargetHostEvidenceErrorV1> {
    let mut unsigned = payload.clone();
    unsigned.evidence_digest.clear();
    Ok(sha256(&canonical(&unsigned)?))
}

fn replay_digest(
    payload: &CellSplitTargetHostEvidenceV1,
) -> Result<String, CellSplitTargetHostEvidenceErrorV1> {
    Ok(sha256(&canonical(&payload.events)?))
}

fn signature_digest(
    signature: &CellSplitTargetHostSignatureV1,
) -> Result<String, CellSplitTargetHostEvidenceErrorV1> {
    Ok(sha256(&canonical(signature)?))
}

fn canonical<T: Serialize>(value: &T) -> Result<Vec<u8>, CellSplitTargetHostEvidenceErrorV1> {
    canonical_json(value)
        .map_err(|error| CellSplitTargetHostEvidenceErrorV1::Canonical(error.to_string()))
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn invalid(message: impl Into<String>) -> CellSplitTargetHostEvidenceErrorV1 {
    CellSplitTargetHostEvidenceErrorV1::Invalid(message.into())
}

fn durable_error(message: impl Into<String>) -> CellSplitTargetHostEvidenceErrorV1 {
    CellSplitTargetHostEvidenceErrorV1::Invalid(format!(
        "durable evidence store: {}",
        message.into()
    ))
}

#[cfg(test)]
#[path = "cell_split_target_host_evidence_tests.rs"]
mod tests;
