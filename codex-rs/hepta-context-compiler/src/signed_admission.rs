use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ContextAdmissionRecordV2;
use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;

const RECORD_SIGNATURE_DOMAIN: &[u8] = b"hepta.context-admission-record-signature.v2";
const SNAPSHOT_SIGNATURE_DOMAIN: &[u8] = b"hepta.context-admission-snapshot-signature.v2";
const VERIFIER_DOMAIN: &[u8] = b"hepta.context-admission-verifier.ed25519.v2";
const MAX_SIGNED_RECORDS: usize = 4_096;
const MAX_SIGNED_SNAPSHOTS: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedAdmissionRecordV2 {
    record: ContextAdmissionRecordV2,
    issuer_id: StableId,
    key_id: StableId,
    signature: [u8; 64],
}

impl SignedAdmissionRecordV2 {
    pub fn new(
        record: ContextAdmissionRecordV2,
        issuer_id: StableId,
        key_id: StableId,
        signature: [u8; 64],
    ) -> Result<Self, SignedAdmissionAuthorityErrorV2> {
        record
            .validate_shape()
            .map_err(|_| SignedAdmissionAuthorityErrorV2::InvalidRecord)?;
        if signature.iter().all(|byte| *byte == 0) {
            return Err(SignedAdmissionAuthorityErrorV2::InvalidSignature);
        }
        Ok(Self {
            record,
            issuer_id,
            key_id,
            signature,
        })
    }

    #[must_use]
    pub const fn record(&self) -> &ContextAdmissionRecordV2 {
        &self.record
    }

    #[must_use]
    pub const fn issuer_id(&self) -> &StableId {
        &self.issuer_id
    }

    #[must_use]
    pub const fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn signature(&self) -> &[u8; 64] {
        &self.signature
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedAdmissionSnapshotV2 {
    snapshot: ContextAdmissionSnapshotV2,
    issuer_id: StableId,
    key_id: StableId,
    signature: [u8; 64],
}

impl SignedAdmissionSnapshotV2 {
    pub fn new(
        snapshot: ContextAdmissionSnapshotV2,
        issuer_id: StableId,
        key_id: StableId,
        signature: [u8; 64],
    ) -> Result<Self, SignedAdmissionAuthorityErrorV2> {
        snapshot
            .validate_shape()
            .map_err(|_| SignedAdmissionAuthorityErrorV2::InvalidSnapshot)?;
        if signature.iter().all(|byte| *byte == 0) {
            return Err(SignedAdmissionAuthorityErrorV2::InvalidSignature);
        }
        Ok(Self {
            snapshot,
            issuer_id,
            key_id,
            signature,
        })
    }

    #[must_use]
    pub const fn snapshot(&self) -> &ContextAdmissionSnapshotV2 {
        &self.snapshot
    }

    #[must_use]
    pub const fn issuer_id(&self) -> &StableId {
        &self.issuer_id
    }

    #[must_use]
    pub const fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn signature(&self) -> &[u8; 64] {
        &self.signature
    }
}

/// Verification-only admission authority.
///
/// The type contains no signing key and exposes no signing operation. Agentd may
/// load signed records and snapshots plus a public key, but cannot mint either.
#[derive(Clone, Eq, PartialEq)]
pub struct SignedAdmissionVerifierV2 {
    issuer_id: StableId,
    key_id: StableId,
    verifying_key: [u8; 32],
    record_signatures: BTreeMap<Digest32, [u8; 64]>,
    snapshot_signatures: BTreeMap<Digest32, [u8; 64]>,
    verifier_digest: Digest32,
}

impl fmt::Debug for SignedAdmissionVerifierV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SignedAdmissionVerifierV2")
            .field("issuer_id", &self.issuer_id)
            .field("key_id", &self.key_id)
            .field("verifying_key_digest", &Digest32::of_bytes(&self.verifying_key))
            .field("record_count", &self.record_signatures.len())
            .field("snapshot_count", &self.snapshot_signatures.len())
            .field("verifier_digest", &self.verifier_digest)
            .finish()
    }
}

impl SignedAdmissionVerifierV2 {
    pub fn new(
        issuer_id: StableId,
        key_id: StableId,
        verifying_key: [u8; 32],
        records: Vec<SignedAdmissionRecordV2>,
        snapshots: Vec<SignedAdmissionSnapshotV2>,
    ) -> Result<Self, SignedAdmissionAuthorityErrorV2> {
        VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| SignedAdmissionAuthorityErrorV2::InvalidVerifyingKey)?;
        if records.len() > MAX_SIGNED_RECORDS {
            return Err(SignedAdmissionAuthorityErrorV2::RecordLimitExceeded);
        }
        if snapshots.is_empty() || snapshots.len() > MAX_SIGNED_SNAPSHOTS {
            return Err(SignedAdmissionAuthorityErrorV2::SnapshotLimitExceeded);
        }

        let mut record_signatures = BTreeMap::new();
        for signed in records {
            if signed.issuer_id != issuer_id {
                return Err(SignedAdmissionAuthorityErrorV2::IssuerMismatch);
            }
            if signed.key_id != key_id {
                return Err(SignedAdmissionAuthorityErrorV2::KeyMismatch);
            }
            verify_record_signature(&verifying_key, &signed)?;
            if record_signatures
                .insert(signed.record.record_digest, signed.signature)
                .is_some()
            {
                return Err(SignedAdmissionAuthorityErrorV2::DuplicateRecord);
            }
        }

        let mut snapshot_signatures = BTreeMap::new();
        for signed in snapshots {
            if signed.issuer_id != issuer_id {
                return Err(SignedAdmissionAuthorityErrorV2::IssuerMismatch);
            }
            if signed.key_id != key_id {
                return Err(SignedAdmissionAuthorityErrorV2::KeyMismatch);
            }
            verify_snapshot_signature(&verifying_key, &signed)?;
            if snapshot_signatures
                .insert(signed.snapshot.snapshot_digest, signed.signature)
                .is_some()
            {
                return Err(SignedAdmissionAuthorityErrorV2::DuplicateSnapshot);
            }
        }

        let verifier_digest = verifier_identity_digest(&issuer_id, &key_id, &verifying_key);
        Ok(Self {
            issuer_id,
            key_id,
            verifying_key,
            record_signatures,
            snapshot_signatures,
            verifier_digest,
        })
    }

    #[must_use]
    pub const fn issuer_id(&self) -> &StableId {
        &self.issuer_id
    }

    #[must_use]
    pub const fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn verifying_key_bytes(&self) -> &[u8; 32] {
        &self.verifying_key
    }

    #[must_use]
    pub const fn record_count(&self) -> usize {
        self.record_signatures.len()
    }

    #[must_use]
    pub const fn snapshot_count(&self) -> usize {
        self.snapshot_signatures.len()
    }

    fn verifies_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        if record.validate_shape().is_err() {
            return false;
        }
        let Some(signature) = self.record_signatures.get(&record.record_digest) else {
            return false;
        };
        verify_bytes(
            &self.verifying_key,
            &admission_record_signing_payload_v2(&self.issuer_id, &self.key_id, record),
            signature,
        )
    }

    fn verifies_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        if snapshot.validate_shape().is_err() {
            return false;
        }
        let Some(signature) = self.snapshot_signatures.get(&snapshot.snapshot_digest) else {
            return false;
        };
        verify_bytes(
            &self.verifying_key,
            &admission_snapshot_signing_payload_v2(&self.issuer_id, &self.key_id, snapshot),
            signature,
        )
    }
}

impl ContextAdmissionVerifierV2 for SignedAdmissionVerifierV2 {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        self.verifies_record(record)
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        self.verifies_snapshot(snapshot)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SignedAdmissionAuthorityErrorV2 {
    InvalidVerifyingKey,
    InvalidRecord,
    InvalidSnapshot,
    InvalidSignature,
    RecordLimitExceeded,
    SnapshotLimitExceeded,
    IssuerMismatch,
    KeyMismatch,
    DuplicateRecord,
    DuplicateSnapshot,
    SignatureVerificationFailed,
}

impl fmt::Display for SignedAdmissionAuthorityErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SignedAdmissionAuthorityErrorV2 {}

#[must_use]
pub fn admission_record_signing_payload_v2(
    issuer_id: &StableId,
    key_id: &StableId,
    record: &ContextAdmissionRecordV2,
) -> Vec<u8> {
    let mut bytes = RECORD_SIGNATURE_DOMAIN.to_vec();
    push_id(&mut bytes, issuer_id);
    push_id(&mut bytes, key_id);
    bytes.extend_from_slice(record.record_digest.as_array());
    bytes
}

#[must_use]
pub fn admission_snapshot_signing_payload_v2(
    issuer_id: &StableId,
    key_id: &StableId,
    snapshot: &ContextAdmissionSnapshotV2,
) -> Vec<u8> {
    let mut bytes = SNAPSHOT_SIGNATURE_DOMAIN.to_vec();
    push_id(&mut bytes, issuer_id);
    push_id(&mut bytes, key_id);
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    bytes
}

fn verify_record_signature(
    verifying_key: &[u8; 32],
    signed: &SignedAdmissionRecordV2,
) -> Result<(), SignedAdmissionAuthorityErrorV2> {
    if verify_bytes(
        verifying_key,
        &admission_record_signing_payload_v2(&signed.issuer_id, &signed.key_id, &signed.record),
        &signed.signature,
    ) {
        Ok(())
    } else {
        Err(SignedAdmissionAuthorityErrorV2::SignatureVerificationFailed)
    }
}

fn verify_snapshot_signature(
    verifying_key: &[u8; 32],
    signed: &SignedAdmissionSnapshotV2,
) -> Result<(), SignedAdmissionAuthorityErrorV2> {
    if verify_bytes(
        verifying_key,
        &admission_snapshot_signing_payload_v2(
            &signed.issuer_id,
            &signed.key_id,
            &signed.snapshot,
        ),
        &signed.signature,
    ) {
        Ok(())
    } else {
        Err(SignedAdmissionAuthorityErrorV2::SignatureVerificationFailed)
    }
}

fn verify_bytes(verifying_key: &[u8; 32], message: &[u8], signature: &[u8; 64]) -> bool {
    let Ok(key) = VerifyingKey::from_bytes(verifying_key) else {
        return false;
    };
    key.verify(message, &Signature::from_bytes(signature)).is_ok()
}

fn verifier_identity_digest(
    issuer_id: &StableId,
    key_id: &StableId,
    verifying_key: &[u8; 32],
) -> Digest32 {
    let mut bytes = VERIFIER_DOMAIN.to_vec();
    push_id(&mut bytes, issuer_id);
    push_id(&mut bytes, key_id);
    bytes.extend_from_slice(verifying_key);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use crate::ContextAdmissionBindingV2;
    use crate::ContextAdmissionRecordV2;
    use crate::ContextAdmissionSnapshotV2;
    use crate::ContextAdmissionVerifierV2;
    use crate::ContextRoleV2;

    use super::SignedAdmissionRecordV2;
    use super::SignedAdmissionSnapshotV2;
    use super::SignedAdmissionVerifierV2;
    use super::admission_record_signing_payload_v2;
    use super::admission_snapshot_signing_payload_v2;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|error| panic!("valid id: {error:?}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn signed_authority_verifies_only_registered_exact_objects() {
        let key = SigningKey::from_bytes(&[17_u8; 32]);
        let issuer = id("context-admission-authority");
        let key_id = id("context-admission-key-1");
        let snapshot = ContextAdmissionSnapshotV2::new(
            id("snapshot-1"),
            digest("scope"),
            digest("authority-domain"),
            100,
            1,
            Vec::new(),
            true,
            None,
        )
        .unwrap_or_else(|error| panic!("valid snapshot: {error:?}"));
        let record = ContextAdmissionRecordV2::new(
            id("admission-1"),
            ContextAdmissionBindingV2 {
                item_id: id("item-1"),
                role: ContextRoleV2::TrustedInstruction,
                content_digest: digest("content"),
                source_digest: digest("source"),
                generation_vector_digest: digest("generation"),
                scope_digest: digest("scope"),
                authority_domain_digest: digest("authority-domain"),
                contains_secret: false,
            },
            90,
            200,
        )
        .unwrap_or_else(|error| panic!("valid record: {error:?}"));

        let record_signature = key
            .sign(&admission_record_signing_payload_v2(&issuer, &key_id, &record))
            .to_bytes();
        let snapshot_signature = key
            .sign(&admission_snapshot_signing_payload_v2(
                &issuer, &key_id, &snapshot,
            ))
            .to_bytes();
        let verifier = SignedAdmissionVerifierV2::new(
            issuer.clone(),
            key_id.clone(),
            key.verifying_key().to_bytes(),
            vec![SignedAdmissionRecordV2::new(
                record.clone(),
                issuer.clone(),
                key_id.clone(),
                record_signature,
            )
            .unwrap_or_else(|error| panic!("signed record: {error:?}"))],
            vec![SignedAdmissionSnapshotV2::new(
                snapshot.clone(),
                issuer,
                key_id,
                snapshot_signature,
            )
            .unwrap_or_else(|error| panic!("signed snapshot: {error:?}"))],
        )
        .unwrap_or_else(|error| panic!("verifier: {error:?}"));

        assert!(verifier.verify_record(&record));
        assert!(verifier.verify_snapshot(&snapshot));

        let unknown_record = ContextAdmissionRecordV2::new(
            id("admission-2"),
            ContextAdmissionBindingV2 {
                item_id: id("item-2"),
                role: ContextRoleV2::TrustedInstruction,
                content_digest: digest("other-content"),
                source_digest: digest("source"),
                generation_vector_digest: digest("generation"),
                scope_digest: digest("scope"),
                authority_domain_digest: digest("authority-domain"),
                contains_secret: false,
            },
            90,
            200,
        )
        .unwrap_or_else(|error| panic!("valid unknown record: {error:?}"));
        assert!(!verifier.verify_record(&unknown_record));
    }

    #[test]
    fn verifier_identity_does_not_depend_on_loaded_record_count() {
        let key = SigningKey::from_bytes(&[19_u8; 32]);
        let issuer = id("context-admission-authority");
        let key_id = id("context-admission-key-1");
        let snapshot = ContextAdmissionSnapshotV2::new(
            id("snapshot-1"),
            digest("scope"),
            digest("authority-domain"),
            100,
            1,
            Vec::new(),
            true,
            None,
        )
        .unwrap_or_else(|error| panic!("valid snapshot: {error:?}"));
        let signature = key
            .sign(&admission_snapshot_signing_payload_v2(
                &issuer, &key_id, &snapshot,
            ))
            .to_bytes();
        let signed = SignedAdmissionSnapshotV2::new(
            snapshot,
            issuer.clone(),
            key_id.clone(),
            signature,
        )
        .unwrap_or_else(|error| panic!("signed snapshot: {error:?}"));
        let first = SignedAdmissionVerifierV2::new(
            issuer.clone(),
            key_id.clone(),
            key.verifying_key().to_bytes(),
            Vec::new(),
            vec![signed.clone()],
        )
        .unwrap_or_else(|error| panic!("first verifier: {error:?}"));
        let second = SignedAdmissionVerifierV2::new(
            issuer,
            key_id,
            key.verifying_key().to_bytes(),
            Vec::new(),
            vec![signed],
        )
        .unwrap_or_else(|error| panic!("second verifier: {error:?}"));
        assert_eq!(
            ContextAdmissionVerifierV2::verifier_digest(&first),
            ContextAdmissionVerifierV2::verifier_digest(&second)
        );
    }
}
