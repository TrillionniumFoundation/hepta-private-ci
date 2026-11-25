//! Fixed credential bytes for one existing PoN child exchange.
//! The private snapshot closes the hash-source / child-reopen gap. It is not
//! an authority issuer, durable owner, or a substitute for host permissions.

use super::super::Sha256Digest;
use std::fs;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Clone, Debug)]
pub(in super::super) struct CredentialPin {
    pub(in super::super) source: PathBuf,
    pub(in super::super) sha256: Sha256Digest,
    pub(in super::super) public_key: [u8; 32],
    pub(in super::super) snapshot_root: PathBuf,
}

pub(in super::super) struct CredentialSnapshot {
    directory: PathBuf,
    path: PathBuf,
    remove_on_drop: bool,
}

impl CredentialSnapshot {
    pub(in super::super) fn path(&self) -> &Path {
        &self.path
    }

    pub(super) fn child_started(&mut self) {
        // A dropped future or an unconfirmed reap must retain the pathname
        // while the original child may still need to open it. No new reaper.
        self.remove_on_drop = false;
    }

    pub(super) fn child_reaped(&mut self) {
        self.remove_on_drop = true;
    }
}

impl Drop for CredentialSnapshot {
    fn drop(&mut self) {
        if self.remove_on_drop {
            let _ = fs::remove_file(&self.path);
            let _ = fs::remove_dir(&self.directory);
        }
    }
}

impl CredentialPin {
    #[cfg(not(all(
        target_os = "linux",
        any(target_arch = "x86_64", target_arch = "aarch64")
    )))]
    pub(in super::super) fn prepare(&self, _deadline: Instant) -> io::Result<CredentialSnapshot> {
        let _ = (
            &self.source,
            &self.sha256,
            &self.public_key,
            &self.snapshot_root,
        );
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "PoN credential platform",
        ))
    }

    #[cfg(all(
        target_os = "linux",
        any(target_arch = "x86_64", target_arch = "aarch64")
    ))]
    pub(in super::super) fn prepare(&self, deadline: Instant) -> io::Result<CredentialSnapshot> {
        use std::io::Read;
        use std::io::Write;
        use std::os::unix::fs::DirBuilderExt;
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;

        unsafe extern "C" {
            fn geteuid() -> u32;
        }
        // SAFETY: geteuid has no arguments and returns this process's UID.
        let uid = unsafe { geteuid() };
        let invalid = || io::Error::new(io::ErrorKind::InvalidData, "PoN credential pin invalid");
        let checkpoint = || {
            if Instant::now() >= deadline {
                Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "PoN credential deadline",
                ))
            } else {
                Ok(())
            }
        };
        checkpoint()?;
        if !self.source.is_absolute() || self.source.canonicalize()? != self.source {
            return Err(invalid());
        }
        let mut source = fs::OpenOptions::new()
            .read(true)
            .custom_flags(0x20000 | 0x800) // Linux O_NOFOLLOW | O_NONBLOCK.
            .open(&self.source)?;
        let metadata = source.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != uid
            || !(64..=65).contains(&metadata.len())
        {
            return Err(invalid());
        }
        let mut bytes = Vec::with_capacity(66);
        Read::by_ref(&mut source).take(66).read_to_end(&mut bytes)?;
        if Sha256Digest::for_bytes(&bytes) != self.sha256 {
            return Err(invalid());
        }
        let text = std::str::from_utf8(&bytes).map_err(|_| invalid())?;
        let text = text.strip_suffix('\n').unwrap_or(text);
        if !super::super::lower_hex_32(text) {
            return Err(invalid());
        }
        let mut seed = [0_u8; 32];
        for (index, byte) in seed.iter_mut().enumerate() {
            *byte =
                u8::from_str_radix(&text[index * 2..index * 2 + 2], 16).map_err(|_| invalid())?;
        }
        let caller = ed25519_dalek::SigningKey::from_bytes(&seed);
        if caller.verifying_key().to_bytes() != self.public_key {
            return Err(invalid());
        }
        checkpoint()?;
        let metadata = fs::symlink_metadata(&self.snapshot_root)?;
        if !self.snapshot_root.is_absolute()
            || self.snapshot_root.canonicalize()? != self.snapshot_root
            || !metadata.is_dir()
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != uid
        {
            return Err(invalid());
        }
        // Use the existing owner's private root, not ambient TMPDIR. Random
        // create-new names prevent collisions without reusable retry identity.
        let mut random = [0_u8; 16];
        fs::File::open("/dev/urandom")?.read_exact(&mut random)?;
        let name = random
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let directory = self.snapshot_root.join(name);
        fs::DirBuilder::new().mode(0o700).create(&directory)?;
        let snapshot = CredentialSnapshot {
            path: directory.join("auth-secret"),
            directory,
            remove_on_drop: true,
        };
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(0x20000 | 0x800)
            .open(snapshot.path())?;
        file.write_all(&bytes)?;
        checkpoint()?;
        Ok(snapshot)
    }
}

#[cfg(all(
    test,
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
#[path = "automation_effect_host_pon_credential_tests.rs"]
mod tests;
