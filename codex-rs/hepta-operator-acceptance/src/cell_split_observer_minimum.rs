//! Independent, challenge-bound Supervisor minimum-checkpoint source.
//!
//! A detached historical Observer signature cannot prove the minimum is still
//! current. This read-only port demands a new challenge signed by a separately
//! pinned minimum-store owner at every deep verification. The filesystem owner
//! below stores one immutable, fsynced minimum in a different private root.
//!
//! Production requires an independently administered, rollback-resistant
//! storage and signing service. A filesystem protected only by local locks
//! cannot detect restoration of its *entire* directory. Neither this file
//! store nor a signed response grants final-use or physical split authority.

use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::durable::{
    SidecarLock, canonical_json, lock_existing_sidecar, lock_sidecar,
    secure_read, secure_root, sha256, write_private_new,
};

const SCHEMA: &str = "hepta.learning.cell-split.supervisor-minimum-online.v1";
const STORED_SCHEMA: &str = "hepta.learning.cell-split.supervisor-minimum-file.v1";
const STORE_FILE: &str = "independent-supervisor-minimum.json";
const MAX_RECORD_BYTES: usize = 16 * 1024;

/// Exact run-specific minimum read requested by a verifier. It is not an
/// authority claim: the separately administered source owns its value.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSupervisorMinimumSubjectV1 {
    pub split_id: String,
    pub target_host_id: String,
    pub target_host_nonce: String,
    pub plan_digest: String,
    pub host_evidence_digest: String,
    pub journal_domain_id: String,
    pub journal_idempotency_key: String,
    pub journal_authority_epoch: u64,
    pub journal_revision: u64,
    pub original_checkpoint_bytes_digest: String,
    pub minimum_checkpoint_digest: String,
}

impl CellSplitSupervisorMinimumSubjectV1 {
    fn validate(&self) -> Result<(), CellSplitSupervisorMinimumErrorV1> {
        if self.split_id.is_empty()
            || self.split_id.len() > 256
            || self.target_host_id.is_empty()
            || self.target_host_id.len() > 256
            || self.target_host_nonce.is_empty()
            || self.target_host_nonce.len() > 256
            || self.journal_domain_id.is_empty()
            || self.journal_domain_id.len() > 256
            || self.journal_authority_epoch == 0
            || self.journal_revision == 0
            || [
                &self.plan_digest,
                &self.host_evidence_digest,
                &self.journal_idempotency_key,
                &self.original_checkpoint_bytes_digest,
                &self.minimum_checkpoint_digest,
            ]
            .iter()
            .any(|value| !digest_shape(value))
        {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        Ok(())
    }
}

/// Fresh evidence that a distinct store still retains the exact bound
/// checkpoint. The detached signature covers a new verifier challenge.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSupervisorMinimumReadbackV1 {
    pub schema: String,
    pub subject: CellSplitSupervisorMinimumSubjectV1,
    pub challenge_nonce: String,
    pub original_store_record_digest: String,
    pub signature_bytes: Vec<u8>,
}

pub fn cell_split_supervisor_minimum_readback_signing_payload_v1(
    proof: &CellSplitSupervisorMinimumReadbackV1,
) -> Result<Vec<u8>, CellSplitSupervisorMinimumErrorV1> {
    let mut unsigned = proof.clone();
    unsigned.signature_bytes.clear();
    let mut bytes = b"hepta.learning.cell-split.supervisor-minimum-readback.v1\0".to_vec();
    bytes.extend_from_slice(&canonical_json(&unsigned)?);
    Ok(bytes)
}

/// No allow-all default. Production must connect this port to a separately
/// administered authenticated minimum store. Its current value must not be
/// derived from the requested Supervisor journal or the supplied transcript.
pub trait CellSplitSupervisorMinimumOnlinePortV1 {
    type Error: std::fmt::Display;

    fn read_current(
        &mut self,
        subject: &CellSplitSupervisorMinimumSubjectV1,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorMinimumReadbackV1, Self::Error>;
}

/// The minimum-store signer must not be allowed to mint an anchor from a
/// caller's self-asserted checkpoint. The independent issuer checks actual
/// journal custody, external monotonic frontier and frozen split admission.
/// No production allow-all implementation or fallback is supplied.
pub trait CellSplitSupervisorMinimumAdmissionPortV1 {
    type Error: std::fmt::Display;

    fn verify_original_minimum(
        &mut self,
        subject: &CellSplitSupervisorMinimumSubjectV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitSupervisorMinimumErrorV1 {
    #[error("invalid or mismatched independently retained Supervisor minimum")]
    Invalid,
    #[error("independent Supervisor minimum has not been durably published")]
    Missing,
    #[error(transparent)]
    Durable(#[from] crate::AcceptanceError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StoredMinimumV1 {
    schema: String,
    subject: CellSplitSupervisorMinimumSubjectV1,
    store_signature_bytes: Vec<u8>,
}

fn stored_signing_payload(
    subject: &CellSplitSupervisorMinimumSubjectV1,
) -> Result<Vec<u8>, CellSplitSupervisorMinimumErrorV1> {
    let mut payload = b"hepta.learning.cell-split.supervisor-minimum-file.v1\0".to_vec();
    payload.extend_from_slice(&canonical_json(subject)?);
    Ok(payload)
}

/// A concrete create-only minimum service for isolated local qualification.
/// The root must belong to the independent Observer, not the Supervisor or
/// CellSplit coordinator; whole-root anti-rollback remains an external gate.
pub struct CellSplitSupervisorMinimumFileStoreV1 {
    root: PathBuf,
    signer: SigningKey,
    _lock: SidecarLock,
}

impl CellSplitSupervisorMinimumFileStoreV1 {
    pub fn open(
        root: &Path,
        signer: SigningKey,
    ) -> Result<Self, CellSplitSupervisorMinimumErrorV1> {
        Self::open_inner(root, signer, false)
    }

    /// Read-only recovery cannot initialize an empty root, create a lock,
    /// or publish a caller-supplied minimum to compensate for missing state.
    pub fn open_existing(
        root: &Path,
        signer: SigningKey,
    ) -> Result<Self, CellSplitSupervisorMinimumErrorV1> {
        Self::open_inner(root, signer, true)
    }

    fn open_inner(
        root: &Path,
        signer: SigningKey,
        existing_only: bool,
    ) -> Result<Self, CellSplitSupervisorMinimumErrorV1> {
        if signer.verifying_key().is_weak() {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        let root = secure_root(root, "independent Supervisor minimum store")?;
        // The lock file is a persistent first-open continuity marker.
        // Losing either half of an initialized source must never let a
        // restarted caller silently create a replacement trusted minimum.
        let had_lock = match fs::symlink_metadata(
            root.join(crate::durable::SIDECAR_LOCK_FILE),
        ) {
            Ok(_) => true,
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        let had_record = match fs::symlink_metadata(root.join(STORE_FILE)) {
            Ok(_) => true,
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        if had_lock != had_record {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        let lock = if existing_only {
            lock_existing_sidecar(&root)?
        } else {
            lock_sidecar(&root)?
        };
        let store = Self {
            root,
            signer,
            _lock: lock,
        };
        if existing_only {
            let _ = store.read_verified()?;
        }
        Ok(store)
    }

    /// Host-authorized irreversible *first* minimum publication. A resumed
    /// caller may re-submit identical bytes but cannot replace that minimum.
    /// A separate observer must authenticate the journal before invoking it.
    pub fn publish_once<A: CellSplitSupervisorMinimumAdmissionPortV1>(
        &mut self,
        subject: &CellSplitSupervisorMinimumSubjectV1,
        admission: &mut A,
    ) -> Result<(), CellSplitSupervisorMinimumErrorV1> {
        subject.validate()?;
        admission
            .verify_original_minimum(subject)
            .map_err(|_| CellSplitSupervisorMinimumErrorV1::Invalid)?;
        let record = StoredMinimumV1 {
            schema: STORED_SCHEMA.into(),
            subject: subject.clone(),
            store_signature_bytes: self
                .signer
                .sign(&stored_signing_payload(subject)?)
                .to_bytes()
                .to_vec(),
        };
        let expected = canonical_json(&record)?;
        match fs::symlink_metadata(self.root.join(STORE_FILE)) {
            Ok(_) if self.read_stored_bytes()? != expected => {
                Err(CellSplitSupervisorMinimumErrorV1::Invalid)
            }
            Ok(_) => Ok(()),
            Err(error) if error.kind() == ErrorKind::NotFound => {
                // Admission may change during preparation; recheck immediately
                // before the irreversible, create-only durable publication.
                admission
                    .verify_original_minimum(subject)
                    .map_err(|_| CellSplitSupervisorMinimumErrorV1::Invalid)?;
                write_private_new(&self.root.join(STORE_FILE), &expected)?;
                if self.read_stored_bytes()? != expected {
                    return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
                }
                Ok(())
            }
            Err(error) => Err(error.into()),
        }
    }

    fn read_stored_bytes(&self) -> Result<Vec<u8>, CellSplitSupervisorMinimumErrorV1> {
        match secure_read(&self.root.join(STORE_FILE), MAX_RECORD_BYTES) {
            Err(crate::AcceptanceError::Io(error))
                if error.kind() == ErrorKind::NotFound =>
            {
                Err(CellSplitSupervisorMinimumErrorV1::Missing)
            }
            result => result.map_err(Into::into),
        }
    }

    fn read_verified(
        &self,
    ) -> Result<(StoredMinimumV1, Vec<u8>), CellSplitSupervisorMinimumErrorV1> {
        let bytes = self.read_stored_bytes()?;
        let record: StoredMinimumV1 = serde_json::from_slice(&bytes)?;
        record.subject.validate()?;
        if record.schema != STORED_SCHEMA
            || record.store_signature_bytes.len() != 64
            || canonical_json(&record)? != bytes
        {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        let signature = Signature::from_slice(&record.store_signature_bytes)
            .map_err(|_| CellSplitSupervisorMinimumErrorV1::Invalid)?;
        self.signer
            .verifying_key()
            .verify_strict(&stored_signing_payload(&record.subject)?, &signature)
            .map_err(|_| CellSplitSupervisorMinimumErrorV1::Invalid)?;
        Ok((record, bytes))
    }
}

impl CellSplitSupervisorMinimumOnlinePortV1 for CellSplitSupervisorMinimumFileStoreV1 {
    type Error = CellSplitSupervisorMinimumErrorV1;

    fn read_current(
        &mut self,
        subject: &CellSplitSupervisorMinimumSubjectV1,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorMinimumReadbackV1, Self::Error> {
        subject.validate()?;
        if !digest_shape(challenge_nonce) {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        let (record, bytes) = self.read_verified()?;
        if record.subject != *subject {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        let mut proof = CellSplitSupervisorMinimumReadbackV1 {
            schema: SCHEMA.into(),
            subject: subject.clone(),
            challenge_nonce: challenge_nonce.to_owned(),
            original_store_record_digest: sha256(&bytes),
            signature_bytes: Vec::new(),
        };
        proof.signature_bytes = self
            .signer
            .sign(&cell_split_supervisor_minimum_readback_signing_payload_v1(&proof)?)
            .to_bytes()
            .to_vec();
        // The state may have changed even under an advisory single-writer
        // lock if an uncooperative process bypassed the store. Deny the proof.
        if self.read_stored_bytes()? != bytes {
            return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
        }
        Ok(proof)
    }
}

pub fn verify_cell_split_supervisor_minimum_online_v1(
    subject: &CellSplitSupervisorMinimumSubjectV1,
    nonce: &str,
    proof: &CellSplitSupervisorMinimumReadbackV1,
    trusted_store_key: &VerifyingKey,
) -> Result<(), CellSplitSupervisorMinimumErrorV1> {
    subject.validate()?;
    if trusted_store_key.is_weak()
        || proof.schema != SCHEMA
        || &proof.subject != subject
        || proof.challenge_nonce != nonce
        || !digest_shape(nonce)
        || !digest_shape(&proof.original_store_record_digest)
        || proof.signature_bytes.len() != 64
    {
        return Err(CellSplitSupervisorMinimumErrorV1::Invalid);
    }
    let signature = Signature::from_slice(&proof.signature_bytes)
        .map_err(|_| CellSplitSupervisorMinimumErrorV1::Invalid)?;
    trusted_store_key
        .verify_strict(
            &cell_split_supervisor_minimum_readback_signing_payload_v1(proof)?,
            &signature,
        )
        .map_err(|_| CellSplitSupervisorMinimumErrorV1::Invalid)
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        && value.bytes().any(|b| b != b'0')
}

#[cfg(test)]
#[path = "cell_split_observer_minimum_tests.rs"]
mod tests;
