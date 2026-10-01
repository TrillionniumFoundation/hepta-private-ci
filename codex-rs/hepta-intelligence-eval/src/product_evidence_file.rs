//! Immutable, bounded evidence publication on an authority-approved file.
//!
//! The host opens and protects the file and supplies the complete original
//! signed request (including its evidence preimages). This sink neither signs
//! nor admits that request. It preserves the request and exact terminal native
//! decision, and acknowledges only after fsync. A torn write is indeterminate;
//! recovery never truncates, overwrites, or invents a publication ACK.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationDispositionV1;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;

const MAGIC: &[u8; 8] = b"HEPTEV01";
const MAX_REQUEST: usize = 16 * 1024 * 1024;
const MAX_RECORD: usize = MAX_REQUEST + 64 * 1024;

/// An ACK retained independently by the evidence owner detects file rollback.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductPublicationRecoveryV1 {
    Unacknowledged,
    Acknowledged(Digest32),
}

/// One immutable publication per execution, with an exclusive OS file lock.
/// Parent-directory creation durability and path authorization belong to the
/// host. Keep this object alive until publication and independent ACK retention.
pub struct LockedFileProductEvidenceSinkV1 {
    file: File,
    execution_digest: Digest32,
    prefix: Vec<u8>,
    published: Option<Vec<u8>>,
    poisoned: bool,
}

impl LockedFileProductEvidenceSinkV1 {
    pub fn open(
        mut file: File,
        execution_digest: Digest32,
        original_signed_request: &[u8],
        recovery: ProductPublicationRecoveryV1,
    ) -> Result<Self, ProductEvidenceSinkErrorV1> {
        if execution_digest.is_zero()
            || original_signed_request.is_empty()
            || original_signed_request.len() > MAX_REQUEST
            || !file.metadata().map_err(unavailable)?.is_file()
        {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        file.try_lock()
            .map_err(|_| ProductEvidenceSinkErrorV1::Unavailable)?;
        if file.metadata().map_err(unavailable)?.len() > MAX_RECORD as u64 {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        let mut prefix = MAGIC.to_vec();
        prefix.extend_from_slice(execution_digest.as_array());
        prefix.extend_from_slice(Digest32::of_bytes(original_signed_request).as_array());
        prefix.extend_from_slice(&(original_signed_request.len() as u32).to_be_bytes());
        prefix.extend_from_slice(original_signed_request);
        file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
        let mut previous = Vec::new();
        (&mut file)
            .take(MAX_RECORD as u64 + 1)
            .read_to_end(&mut previous)
            .map_err(unavailable)?;
        let published = if previous.is_empty() {
            None
        } else {
            if previous.len() < prefix.len() + 32
                || previous.len() > MAX_RECORD
                || previous[..prefix.len()] != prefix
                || previous[previous.len() - 32..]
                    != *Digest32::of_bytes(&previous[..previous.len() - 32]).as_array()
            {
                return Err(ProductEvidenceSinkErrorV1::Indeterminate);
            }
            Some(previous)
        };
        if let ProductPublicationRecoveryV1::Acknowledged(expected) = recovery
            && (expected.is_zero()
                || published
                    .as_ref()
                    .is_none_or(|bytes| Digest32::of_bytes(bytes) != expected))
        {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        Ok(Self {
            file,
            execution_digest,
            prefix,
            published,
            poisoned: false,
        })
    }
}

impl ProductQualificationEvidenceSinkV1 for LockedFileProductEvidenceSinkV1 {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        if self.poisoned {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        if execution_digest != self.execution_digest
            || decision.decision.authority.grants_any()
            || decision.decision.evidence_digest.is_zero()
            || decision.trust_digest.is_zero()
            || decision.authentication_digest.is_zero()
            || decision.decision.failed_metrics.len() > 128
        {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        let mut bytes = self.prefix.clone();
        for id in [
            &decision.decision.evaluation_id,
            &decision.decision.candidate_id,
            &decision.decision.baseline_id,
        ] {
            push_id(&mut bytes, id)?;
        }
        bytes.push(match decision.decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
            IndependentEvaluationDispositionV1::Ineligible => 1,
            IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
        });
        bytes.extend_from_slice(&(decision.decision.failed_metrics.len() as u32).to_be_bytes());
        for id in &decision.decision.failed_metrics {
            push_id(&mut bytes, id)?;
        }
        for digest in [
            decision.decision.evidence_digest,
            decision.trust_digest,
            decision.authentication_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(0); // The exact native decision always denies promotion authority.
        let checksum = Digest32::of_bytes(&bytes);
        bytes.extend_from_slice(checksum.as_array());
        if bytes.len() > MAX_RECORD {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        if let Some(published) = &self.published {
            if published != &bytes {
                return Err(ProductEvidenceSinkErrorV1::Rejected);
            }
            self.file
                .sync_all()
                .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
            return Ok(Digest32::of_bytes(published));
        }
        self.poisoned = true;
        self.file
            .seek(SeekFrom::Start(0))
            .and_then(|_| self.file.write_all(&bytes))
            .and_then(|()| self.file.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        let digest = Digest32::of_bytes(&bytes);
        self.published = Some(bytes);
        self.poisoned = false;
        Ok(digest)
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), ProductEvidenceSinkErrorV1> {
    let value = id.as_str().as_bytes();
    if value.len() > 4096 {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}
fn unavailable(_: std::io::Error) -> ProductEvidenceSinkErrorV1 {
    ProductEvidenceSinkErrorV1::Unavailable
}

#[cfg(test)]
#[path = "product_evidence_file_tests.rs"]
mod tests;
