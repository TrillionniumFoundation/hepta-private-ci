//! Bounded replay journal with a separately durable acknowledged-prefix anchor.
//!
//! A complete but unacknowledged append is consumed on recovery. A lost or
//! changed acknowledged prefix is never interpreted as permission to retry.
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use super::Access;
use super::FinalUseError;
use super::MAX_CLAIMS;
use super::entry_exists;
use super::open_private;
use super::replace_entry;
use super::same_file;

const NONCE_FILE: &str = "authority.nonces";
const NONCE_NEXT: &str = "authority.nonces.next";
const ANCHOR_FILE: &str = "authority.nonces.anchor";
const ANCHOR_NEXT: &str = "authority.nonces.anchor.next";
const RECORD_BYTES: usize = 40;
const MAX_ANCHOR_BYTES: u64 = 1024;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Anchor {
    schema: u32,
    epoch: u64,
    records: usize,
    digest: [u8; 32],
}

/// Missing anchors may be adopted only while migrating a V1/V2 store. V3
/// metadata is the durable marker that makes absence a storage failure.
pub(super) enum Recovery {
    Legacy,
    Anchored,
}

pub(super) struct Journal {
    file: File,
    anchor: Anchor,
}

impl Journal {
    pub(super) fn open(
        root: &File,
        epoch: u64,
        recovery: Recovery,
    ) -> Result<(Self, BTreeSet<[u8; 32]>), FinalUseError> {
        if !entry_exists(root, NONCE_FILE)? {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(root, NONCE_FILE, Access::Write)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take((MAX_CLAIMS * RECORD_BYTES) as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| FinalUseError::Unavailable)?;
        if bytes.len() > MAX_CLAIMS * RECORD_BYTES || bytes.len() % RECORD_BYTES != 0 {
            return Err(FinalUseError::InvalidTrust);
        }
        let saved = match recovery {
            Recovery::Legacy => None,
            Recovery::Anchored => {
                if !entry_exists(root, ANCHOR_FILE)? {
                    return Err(FinalUseError::InvalidTrust);
                }
                let mut encoded = Vec::new();
                open_private(root, ANCHOR_FILE, Access::Read)?
                    .take(MAX_ANCHOR_BYTES + 1)
                    .read_to_end(&mut encoded)
                    .map_err(|_| FinalUseError::Unavailable)?;
                if encoded.len() as u64 > MAX_ANCHOR_BYTES {
                    return Err(FinalUseError::InvalidTrust);
                }
                let anchor: Anchor =
                    serde_json::from_slice(&encoded).map_err(|_| FinalUseError::InvalidTrust)?;
                if anchor.schema != 1
                    || anchor.epoch == 0
                    || anchor.epoch > epoch
                    || anchor.records > MAX_CLAIMS
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                Some(anchor)
            }
        };
        let mut digest = [0; 32];
        let mut nonces = BTreeSet::new();
        let mut prefix_matches = saved
            .as_ref()
            .is_none_or(|anchor| anchor.records == 0 && anchor.digest == digest);
        for (index, record) in bytes.chunks_exact(RECORD_BYTES).enumerate() {
            let recorded_epoch = u64::from_le_bytes(
                record[..8]
                    .try_into()
                    .map_err(|_| FinalUseError::InvalidTrust)?,
            );
            if recorded_epoch == 0 || recorded_epoch > epoch {
                return Err(FinalUseError::InvalidTrust);
            }
            let nonce: [u8; 32] = record[8..]
                .try_into()
                .map_err(|_| FinalUseError::InvalidTrust)?;
            if nonce == [0; 32] || recorded_epoch == epoch && !nonces.insert(nonce) {
                return Err(FinalUseError::InvalidTrust);
            }
            digest = chain(digest, record);
            if let Some(anchor) = &saved
                && anchor.records == index + 1
            {
                prefix_matches = anchor.digest == digest;
            }
        }
        if let Some(anchor) = &saved {
            if anchor.epoch == epoch {
                if !prefix_matches || anchor.records > bytes.len() / RECORD_BYTES {
                    return Err(FinalUseError::InvalidTrust);
                }
            } else {
                // Head publication precedes rotation. No new-epoch claim can
                // have been released before a new-epoch anchor was durable.
                if !nonces.is_empty() {
                    return Err(FinalUseError::InvalidTrust);
                }
                return Ok((Self::reset(root, epoch, &nonces)?, nonces));
            }
        }
        // Legacy recovery may contain old-epoch records after a head update.
        // Compact only after the current-epoch replay set has been recovered.
        if bytes.len() / RECORD_BYTES != nonces.len() {
            return Ok((Self::reset(root, epoch, &nonces)?, nonces));
        }
        let journal = Self {
            file,
            anchor: Anchor {
                schema: 1,
                epoch,
                records: nonces.len(),
                digest,
            },
        };
        // Also anchors a complete append whose caller died before acknowledgement.
        journal.persist_anchor(root)?;
        Ok((journal, nonces))
    }

    pub(super) fn ensure_live(&self, root: &File) -> Result<(), FinalUseError> {
        let mut encoded = Vec::new();
        open_private(root, ANCHOR_FILE, Access::Read)?
            .take(MAX_ANCHOR_BYTES + 1)
            .read_to_end(&mut encoded)
            .map_err(|_| FinalUseError::Unavailable)?;
        if encoded.len() as u64 > MAX_ANCHOR_BYTES {
            return Err(FinalUseError::InvalidTrust);
        }
        let saved: Anchor =
            serde_json::from_slice(&encoded).map_err(|_| FinalUseError::InvalidTrust)?;
        if saved != self.anchor {
            return Err(FinalUseError::InvalidTrust);
        }
        let path = open_private(root, NONCE_FILE, Access::Read)?;
        if !same_file(&self.file, &path)?
            || path
                .metadata()
                .map_err(|_| FinalUseError::Unavailable)?
                .len()
                != (self.anchor.records * RECORD_BYTES) as u64
        {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(())
    }

    pub(super) fn append(
        &mut self,
        root: &File,
        epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        self.ensure_live(root)?;
        if epoch != self.anchor.epoch || self.anchor.records >= MAX_CLAIMS {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut record = [0; RECORD_BYTES];
        record[..8].copy_from_slice(&epoch.to_le_bytes());
        record[8..].copy_from_slice(&nonce);
        self.file
            .seek(SeekFrom::End(0))
            .map_err(|_| FinalUseError::Unavailable)?;
        self.file
            .write_all(&record)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        self.anchor.records += 1;
        self.anchor.digest = chain(self.anchor.digest, &record);
        self.persist_anchor(root)?;
        self.ensure_live(root)
    }

    pub(super) fn reset(
        root: &File,
        epoch: u64,
        nonces: &BTreeSet<[u8; 32]>,
    ) -> Result<Self, FinalUseError> {
        if nonces.len() > MAX_CLAIMS {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(root, NONCE_NEXT, Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        let mut digest = [0; 32];
        for nonce in nonces {
            let mut record = [0; RECORD_BYTES];
            record[..8].copy_from_slice(&epoch.to_le_bytes());
            record[8..].copy_from_slice(nonce);
            file.write_all(&record)
                .map_err(|_| FinalUseError::Unavailable)?;
            digest = chain(digest, &record);
        }
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        replace_entry(root, NONCE_NEXT, NONCE_FILE)?;
        root.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        let journal = Self {
            file,
            anchor: Anchor {
                schema: 1,
                epoch,
                records: nonces.len(),
                digest,
            },
        };
        journal.persist_anchor(root)?;
        Ok(journal)
    }

    fn persist_anchor(&self, root: &File) -> Result<(), FinalUseError> {
        let bytes = serde_json::to_vec(&self.anchor).map_err(|_| FinalUseError::Unavailable)?;
        let mut file = open_private(root, ANCHOR_NEXT, Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        replace_entry(root, ANCHOR_NEXT, ANCHOR_FILE)?;
        root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }
}

fn chain(previous: [u8; 32], record: &[u8]) -> [u8; 32] {
    let mut digest = Sha256::new();
    digest.update(previous);
    digest.update(record);
    digest.finalize().into()
}
