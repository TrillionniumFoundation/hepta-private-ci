//! Original issuer key publication and explicit unused-genesis completion.
//! No issuer state, signer identity or sequence is reconstructed after use.
use super::*;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use rustix::fs::AtFlags;
use rustix::fs::FlockOperation;
use rustix::fs::Mode;
use rustix::fs::OFlags;
use std::ffi::OsStr;
use std::path::PathBuf;

const KEY: &str = "issuer.key";
const KEY_NEXT: &str = "issuer.key.next";
const INITIALIZATION_LOCK: &str = "issuer-initialization.lock";

#[cfg(test)]
pub(super) fn at_state_publication_cut() {
    tests::at_key_cut("state-published");
}

pub(super) fn validate_policy(
    signer_id: &str,
    policies: &[DeploymentGrantPolicy],
) -> io::Result<()> {
    if signer_id.is_empty() || signer_id.len() > 64 || policies.is_empty() || policies.len() > 16 {
        return Err(io::Error::other("invalid local issuer policy"));
    }
    for policy in policies {
        let probe = FinalUseGrant {
            schema_version: 1,
            signer_id: signer_id.to_owned(),
            authority_epoch: 1,
            grant_id: "policy-validation".into(),
            nonce: [1; 32],
            binding: FinalUseBinding {
                subject_id: policy.subject_id.clone(),
                destination_id: policy.destination_id.clone(),
                request_sha256: [1; 32],
                scope_sha256: policy.scope_sha256,
                payload_sha256: [1; 32],
            },
            not_before_unix_ms: 1,
            expires_at_unix_ms: 1_u64
                .checked_add(policy.lifetime_ms)
                .ok_or_else(|| io::Error::other("invalid lifetime"))?,
        };
        probe.signing_bytes().map_err(io::Error::other)?;
    }
    Ok(())
}

pub(super) fn initial_state(
    signer_id: String,
    policies: Vec<DeploymentGrantPolicy>,
) -> IssuerState {
    IssuerState {
        signer_id,
        policies,
        head: FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        sequence: 0,
        writer_authorization: None,
    }
}

// A coordination lock, not authority state. All publication uses this held
// directory descriptor; no key bytes are serialized or included in errors.
pub(super) struct KeyPublication {
    directory: File,
    path: PathBuf,
    owner_uid: u32,
    _lock: File,
}

impl KeyPublication {
    pub(super) fn open(path: &Path) -> io::Result<Self> {
        let directory: File = rustix::fs::open(
            path,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )?
        .into();
        let owner_uid = rustix::process::geteuid().as_raw();
        let metadata = directory.metadata()?;
        if !path.is_absolute()
            || !metadata.is_dir()
            || metadata.uid() != owner_uid
            || metadata.mode() & 0o777 != 0o700
        {
            return Err(io::Error::other(
                "issuer initialization requires the original private directory",
            ));
        }
        let lock: File = rustix::fs::openat(
            &directory,
            INITIALIZATION_LOCK,
            OFlags::RDWR | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::RUSR | Mode::WUSR,
        )?
        .into();
        check_private(&lock, owner_uid, None)?;
        rustix::fs::flock(&lock, FlockOperation::NonBlockingLockExclusive)?;
        check_same_name(&directory, INITIALIZATION_LOCK, &lock)?;
        Ok(Self {
            directory,
            path: path.to_path_buf(),
            owner_uid,
            _lock: lock,
        })
    }

    fn exists(&self, name: &str) -> io::Result<bool> {
        match rustix::fs::statat(&self.directory, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(_) => Ok(true),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(error) => Err(error.into()),
        }
    }

    fn read_key(&self, name: &str) -> io::Result<(File, [u8; 32])> {
        let mut file: File = rustix::fs::openat(
            &self.directory,
            name,
            OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::empty(),
        )?
        .into();
        check_private(&file, self.owner_uid, Some(32))?;
        check_same_name(&self.directory, name, &file)?;
        let mut bytes = [0; 32];
        file.read_exact(&mut bytes)?;
        Ok((file, bytes))
    }

    pub(super) fn create_key(&self) -> io::Result<()> {
        let mut file: File = rustix::fs::openat(
            &self.directory,
            KEY_NEXT,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        )?
        .into();
        check_private(&file, self.owner_uid, Some(0))?;
        let bytes = random_bytes()?;
        file.write_all(&bytes)?;
        self.publish_key(&file, &bytes)
    }

    fn publish_key(&self, file: &File, expected: &[u8; 32]) -> io::Result<()> {
        check_private(file, self.owner_uid, Some(32))?;
        check_same_name(&self.directory, KEY_NEXT, file)?;
        file.sync_all()?;
        self.directory.sync_all()?;
        #[cfg(test)]
        tests::at_key_cut("prepared");
        rustix::fs::renameat_with(
            &self.directory,
            KEY_NEXT,
            &self.directory,
            KEY,
            rustix::fs::RenameFlags::NOREPLACE,
        )?;
        self.directory.sync_all()?;
        let (published, observed) = self.read_key(KEY)?;
        let before = file.metadata()?;
        let after = published.metadata()?;
        if before.dev() != after.dev() || before.ino() != after.ino() || &observed != expected {
            return Err(io::Error::other(
                "issuer key publication did not retain the original complete inode",
            ));
        }
        #[cfg(test)]
        tests::at_key_cut("published");
        Ok(())
    }

    // A missing key can only be resumed before any state publication began.
    // The original create order writes the key first; later state with a lost
    // key cannot prove which signing identity belongs to a retained candidate.
    fn require_unpublished_directory(&self) -> io::Result<()> {
        let observed = std::fs::symlink_metadata(&self.path)?;
        let retained = self.directory.metadata()?;
        if !observed.is_dir()
            || observed.dev() != retained.dev()
            || observed.ino() != retained.ino()
        {
            return Err(io::Error::other("issuer directory identity changed"));
        }
        for entry in std::fs::read_dir(&self.path)? {
            let name = entry?.file_name();
            if name != OsStr::new(INITIALIZATION_LOCK) && name != OsStr::new(KEY_NEXT) {
                return Err(io::Error::other(
                    "missing issuer key with retained state is not initialization",
                ));
            }
        }
        Ok(())
    }

    fn resume_key(&self) -> io::Result<[u8; 32]> {
        if self.exists(KEY)? {
            if self.exists(KEY_NEXT)? {
                return Err(io::Error::other(
                    "conflicting issuer key candidates are retained",
                ));
            }
            let (file, bytes) = self.read_key(KEY)?;
            file.sync_all()?;
            self.directory.sync_all()?;
            return Ok(bytes);
        }
        self.require_unpublished_directory()?;
        if self.exists(KEY_NEXT)? {
            let (file, bytes) = self.read_key(KEY_NEXT)?;
            self.publish_key(&file, &bytes)?;
            Ok(bytes)
        } else {
            // An explicitly authorized empty directory has no earlier key or
            // state to replace. The first identity uses the original RNG.
            self.create_key()?;
            self.read_key(KEY).map(|(_, bytes)| bytes)
        }
    }
}

fn check_private(file: &File, owner_uid: u32, length: Option<u64>) -> io::Result<()> {
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.uid() != owner_uid
        || metadata.mode() & 0o777 != 0o600
        || metadata.nlink() != 1
        || length.is_some_and(|length| metadata.len() != length)
    {
        return Err(io::Error::other(
            "issuer material must be original private 0600 with exact shape",
        ));
    }
    Ok(())
}

fn check_same_name(directory: &File, name: &str, file: &File) -> io::Result<()> {
    let named = rustix::fs::statat(directory, name, AtFlags::SYMLINK_NOFOLLOW)?;
    let retained = rustix::fs::fstat(file)?;
    if named.st_dev != retained.st_dev || named.st_ino != retained.st_ino {
        return Err(io::Error::other("issuer material inode changed"));
    }
    Ok(())
}

impl DeploymentFinalUseIssuer {
    /// Explicit Root-only continuation of the original unused installation.
    /// Retain the same complete key and exact signer/policy/genesis state.
    /// Short keys, missing keys after state publication and advanced states
    /// remain errors. Ordinary runtime open does not call this method.
    pub fn resume_protected_initialization(
        directory: &Path,
        signer_id: String,
        policies: Vec<DeploymentGrantPolicy>,
        clock: Arc<dyn AuthorityClock>,
        leases: AuthorityLeaseVerifier,
        lease_id: String,
        lease_revision: u64,
    ) -> io::Result<Self> {
        validate_policy(&signer_id, &policies)?;
        let _root = RootAuthorityDirectory::open(directory).map_err(io::Error::other)?;
        clock.now_unix_ms().map_err(io::Error::other)?;
        let lease = ProtectedLease::new(leases, lease_id, lease_revision)?;
        let store = DeploymentFrontierStore::open_protected(directory)?;
        let publication = KeyPublication::open(directory)?;
        let retained_key = publication.resume_key()?;
        let expected = initial_state(signer_id, policies);
        store.resume_protected_initialization(STATE_OWNER, &expected)?;
        let issuer = Self::open_inner(directory, clock, true, Some(lease))?;
        if issuer.store.load(STATE_OWNER).map_err(io::Error::other)? != expected
            || issuer.key.verifying_key() != SigningKey::from_bytes(&retained_key).verifying_key()
        {
            return Err(io::Error::other(
                "issuer initialization identity or original genesis changed",
            ));
        }
        Ok(issuer)
    }
}

#[cfg(test)]
#[path = "deployment_issuer_initialization_tests.rs"]
mod tests;
