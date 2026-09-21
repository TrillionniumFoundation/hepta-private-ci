//! Fixed-size nonce deltas. Checksums detect corruption, not authority: the
//! selected issuer trust and independent frontier still govern admission.

use super::FinalUseError;
use super::MAX_CLAIMS;
use super::State;
use sha2::Digest;
use sha2::Sha256;

pub(super) const RECORD_BYTES: usize = 80;
pub(super) const MAX_LOG_BYTES: usize = MAX_CLAIMS * RECORD_BYTES;

pub(super) fn encode(
    state: &State,
    nonce: [u8; 32],
    trust_digest: [u8; 32],
) -> [u8; RECORD_BYTES] {
    let mut record = [0; RECORD_BYTES];
    record[..8].copy_from_slice(&state.head.authority_epoch.to_le_bytes());
    record[8..16].copy_from_slice(&state.head.revision.to_le_bytes());
    record[16..48].copy_from_slice(&nonce);
    let checksum = checksum(&record[..48], trust_digest);
    record[48..].copy_from_slice(&checksum);
    record
}

pub(super) fn replay(
    bytes: &[u8],
    state: &mut State,
    trust_digest: [u8; 32],
) -> Result<(), FinalUseError> {
    // A partial final record was never acknowledged. The caller checkpoints
    // this validated prefix before truncating the log or accepting more work.
    // An independent frontier ahead of the prefix still fences production
    // reopen; this parser must never manufacture a missing consumed nonce.
    if bytes.len() > MAX_LOG_BYTES + RECORD_BYTES - 1 {
        return Err(FinalUseError::InvalidTrust);
    }
    for record in bytes.chunks_exact(RECORD_BYTES) {
        if record[48..] != checksum(&record[..48], trust_digest) {
            return Err(FinalUseError::InvalidTrust);
        }
        let epoch = u64::from_le_bytes(
            record[..8].try_into().map_err(|_| FinalUseError::InvalidTrust)?,
        );
        let revision = u64::from_le_bytes(
            record[8..16].try_into().map_err(|_| FinalUseError::InvalidTrust)?,
        );
        let nonce: [u8; 32] = record[16..48]
            .try_into()
            .map_err(|_| FinalUseError::InvalidTrust)?;
        if epoch == 0 || revision == 0 || nonce == [0; 32]
            || epoch > state.head.authority_epoch
        {
            return Err(FinalUseError::InvalidTrust);
        }
        if epoch < state.head.authority_epoch {
            // A durable newer-epoch checkpoint supersedes old grants. This is
            // the crash cut after checkpoint rename but before log truncation.
            continue;
        }
        if revision > state.head.revision
            || (revision < state.head.revision && !state.used_nonces.contains(&nonce))
        {
            return Err(FinalUseError::InvalidTrust);
        }
        state.used_nonces.insert(nonce);
        if state.used_nonces.len() > MAX_CLAIMS {
            return Err(FinalUseError::InvalidTrust);
        }
    }
    Ok(())
}

fn checksum(payload: &[u8], trust_digest: [u8; 32]) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.nonce-log.v1\0");
    hash.update(trust_digest);
    hash.update(payload);
    hash.finalize().into()
}
