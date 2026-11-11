//! Root-only readback of the original non-Root FinalUse journal. No owner lock,
//! nonce claim, state creation, migration or repair is available on this port.

use std::fs::File;
use std::fs::Metadata;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::super::FinalUseBinding;
use super::super::FinalUseError;
use super::super::FinalUseFrontier;
use super::super::FinalUseIssuerTrustKey;
use super::super::FinalUseRevocations;
use super::super::PinnedIssuerKey;
use super::super::SignedFinalUseGrant;
use super::super::State;
use super::super::frontier_for_state;
use super::super::identifier;
use super::super::map_trust_error;
use super::super::pin_issuer_keys;
use super::super::retained::RetainedUse;
use super::super::valid_head;
use super::CLAIM_FRAME_BYTES;
use super::MAX_CLAIMS;
use super::STATE_SCHEMA_V3;
use super::StoreTrust;
use super::StoredV3;
use super::decode_claims;
use crate::AuthorityFrontierStore;
use crate::VerifiedUseTokenWitnessV1;

/// A Root-enrolled view of one original consumer, not a FinalUse authority.
/// The host supplies its protected frontier and original issuer trust; these
/// inputs must never be selected from an untrusted publication request.
///
/// The directory, lock and claims inode are retained. A journal replacement
/// (including an authorized revocation compaction) fences this instance and
/// requires explicit Root enrollment of the new original state. A witness is
/// checked as data; an authenticated effect-owner record is still required to
/// prove that an effect completed.
pub struct RootFinalUseObserverV1 {
    directory_path: PathBuf,
    directory: File,
    lock: File,
    lock_stamp: FileStamp,
    claims: File,
    consumer_uid: u32,
    signer_id: String,
    issuer_keys: Vec<PinnedIssuerKey>,
    issuer_trust_sha256: [u8; 32],
    frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    failed: AtomicBool,
}

impl RootFinalUseObserverV1 {
    /// Open existing schema-3 key-ring state owned by this exact non-Root uid.
    /// This does not take the authority lock or create any filesystem entry.
    pub fn open_original(
        directory: &Path,
        consumer_uid: u32,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        if rustix::process::geteuid().as_raw() != 0
            || consumer_uid == 0
            || consumer_uid == u32::MAX
            || !directory.is_absolute()
        {
            return Err(FinalUseError::UnsafeStateDirectory);
        }
        if !identifier(&signer_id) {
            return Err(FinalUseError::InvalidTrust);
        }
        let (issuer_keys, issuer_trust_sha256) = pin_issuer_keys(issuer_keys)?;
        let directory_path = directory.to_owned();
        let directory = open_directory(directory, consumer_uid)?;
        let lock = open_file(&directory, "authority.lock", consumer_uid)?;
        let lock_stamp = FileStamp::read(&lock)?;
        let claims = open_file(&directory, "authority.claims", consumer_uid)?;
        let observer: RootFinalUseObserverV1 = Self {
            directory_path,
            directory,
            lock,
            lock_stamp,
            claims,
            consumer_uid,
            signer_id,
            issuer_keys,
            issuer_trust_sha256,
            frontier,
            failed: AtomicBool::new(false),
        };
        observer.read_current()?;
        Ok(observer)
    }

    pub fn consumer_uid(&self) -> u32 {
        self.consumer_uid
    }

    pub fn signer_id(&self) -> &str {
        &self.signer_id
    }

    /// The original full issuer key-ring pin, for the Root enrollment record.
    /// This is data; it grants no signature, nonce or publication authority.
    pub fn issuer_trust_digest(&self) -> [u8; 32] {
        self.issuer_trust_sha256
    }

    /// Verify the original signature and consumed dispatch entry against the
    /// current Root frontier. Historical grant expiry does not renew or revoke
    /// that entry; current epoch/revocation changes still deny retained use.
    pub fn verify_original_retained_use(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> Result<FinalUseRevocations, FinalUseError> {
        let retained: RetainedUse<'_> = RetainedUse::authenticate(
            &self.signer_id,
            &self.issuer_keys,
            signed,
            expected,
            witness,
        )?;
        retained.verify_state(&self.read_current()?)
    }

    fn read_current(&self) -> Result<State, FinalUseError> {
        if self.failed.load(Ordering::Acquire) {
            return Err(FinalUseError::Unavailable);
        }
        let result = (|| {
            if rustix::process::geteuid().as_raw() != 0 {
                return Err(FinalUseError::UnsafeStateDirectory);
            }
            self.require_original_files()?;
            let before = self
                .frontier
                .load(&self.signer_id)
                .map_err(map_trust_error)?;
            let snapshot = self.read_file("authority.json", 8 * 1024 * 1024)?;
            let stored: StoredV3 =
                serde_json::from_slice(&snapshot.bytes).map_err(|_| FinalUseError::InvalidTrust)?;
            if stored.schema != STATE_SCHEMA_V3
                || stored.signer_id != self.signer_id
                || stored.trust != StoreTrust::IssuerKeyRing(self.issuer_trust_sha256)
                || !valid_head(&stored.head)
            {
                return Err(FinalUseError::InvalidTrust);
            }
            let claims =
                self.read_file("authority.claims", (MAX_CLAIMS + 1) * CLAIM_FRAME_BYTES)?;
            if !claims.stamp.same_inode(&FileStamp::read(&self.claims)?) {
                return Err(FinalUseError::Unavailable);
            }
            let state = State {
                used_nonces: decode_claims(&claims.bytes, stored.head.authority_epoch)?,
                head: stored.head,
                failed: false,
            };
            if frontier_for_state(&state) != before
                || self
                    .frontier
                    .load(&self.signer_id)
                    .map_err(map_trust_error)?
                    != before
            {
                return Err(FinalUseError::AntiRollbackViolation);
            }
            self.require_readback("authority.json", &snapshot)?;
            self.require_readback("authority.claims", &claims)?;
            self.require_original_files()?;
            if self.failed.load(Ordering::Acquire) {
                return Err(FinalUseError::Unavailable);
            }
            Ok(state)
        })();
        if result.is_err() {
            self.failed.store(true, Ordering::Release);
        }
        result
    }

    fn require_original_files(&self) -> Result<(), FinalUseError> {
        let directory = open_directory(&self.directory_path, self.consumer_uid)?;
        let named_lock = open_file(&self.directory, "authority.lock", self.consumer_uid)?;
        let named_claims = open_file(&self.directory, "authority.claims", self.consumer_uid)?;
        if !FileStamp::read(&directory)?.same_inode(&FileStamp::read(&self.directory)?)
            || FileStamp::read(&self.lock)? != self.lock_stamp
            || FileStamp::read(&named_lock)? != self.lock_stamp
            || !FileStamp::read(&named_claims)?.same_inode(&FileStamp::read(&self.claims)?)
        {
            return Err(FinalUseError::Unavailable);
        }
        Ok(())
    }

    fn read_file(&self, name: &str, maximum: usize) -> Result<Readback, FinalUseError> {
        let mut file = open_file(&self.directory, name, self.consumer_uid)?;
        let stamp = FileStamp::read(&file)?;
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(maximum as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| FinalUseError::Unavailable)?;
        if bytes.len() > maximum || stamp.len != bytes.len() as u64 {
            return Err(FinalUseError::InvalidTrust);
        }
        let readback = Readback { file, stamp, bytes };
        self.require_readback(name, &readback)?;
        Ok(readback)
    }

    fn require_readback(&self, name: &str, readback: &Readback) -> Result<(), FinalUseError> {
        let named = open_file(&self.directory, name, self.consumer_uid)?;
        if FileStamp::read(&readback.file)? != readback.stamp
            || FileStamp::read(&named)? != readback.stamp
        {
            return Err(FinalUseError::Unavailable);
        }
        Ok(())
    }
}

struct Readback {
    file: File,
    stamp: FileStamp,
    bytes: Vec<u8>,
}

#[derive(Eq, PartialEq)]
struct FileStamp {
    dev: u64,
    ino: u64,
    uid: u32,
    mode: u32,
    nlink: u64,
    len: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl FileStamp {
    fn read(file: &File) -> Result<Self, FinalUseError> {
        let value = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
        Ok(Self {
            dev: value.dev(),
            ino: value.ino(),
            uid: value.uid(),
            mode: value.mode(),
            nlink: value.nlink(),
            len: value.len(),
            modified: (value.mtime(), value.mtime_nsec()),
            changed: (value.ctime(), value.ctime_nsec()),
        })
    }

    fn same_inode(&self, other: &Self) -> bool {
        self.dev == other.dev && self.ino == other.ino
    }
}

fn private(metadata: &Metadata, consumer_uid: u32) -> bool {
    metadata.uid() == consumer_uid && metadata.mode() & 0o077 == 0
}

fn open_directory(path: &Path, consumer_uid: u32) -> Result<File, FinalUseError> {
    use rustix::fs::OFlags;
    let file: File = rustix::fs::open(
        path,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| FinalUseError::UnsafeStateDirectory)?
    .into();
    let metadata = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_dir() || !private(&metadata, consumer_uid) {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    Ok(file)
}

fn open_file(directory: &File, name: &str, consumer_uid: u32) -> Result<File, FinalUseError> {
    use rustix::fs::OFlags;
    let file: File = rustix::fs::openat(
        directory,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| FinalUseError::Unavailable)?
    .into();
    let metadata = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_file() || metadata.nlink() != 1 || !private(&metadata, consumer_uid) {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(test)]
#[path = "final_use_root_observer_tests.rs"]
mod tests;
