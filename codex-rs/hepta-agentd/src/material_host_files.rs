//! Descriptor-only nonRoot custody checks, distinct from the Root loader.
//! No Root helper is weakened and no directory or store is created here.

use std::collections::BTreeSet;
use std::ffi::CString;
use std::fs::{File, Metadata};
use std::io::Read;
use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::fs::{FileExt, MetadataExt};
use std::os::unix::net::UnixStream;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use ed25519_dalek::SigningKey;
use serde::de::DeserializeOwned;
use crate::AgentdError;
use super::{config::{Configuration, Operation, Peer}, invalid, OriginalMaterialHostFilesV1};

#[derive(Clone, Copy)]
enum Access { ReadOnly, ReadWrite }

fn private_file(file: &File, uid: u32, access: Access) -> Result<Metadata, AgentdError> {
    let metadata = file.metadata()?;
    // SAFETY: F_GETFL reads flags on this borrowed live descriptor only.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    let expected = match access { Access::ReadOnly => libc::O_RDONLY, Access::ReadWrite => libc::O_RDWR };
    if !metadata.is_file() || metadata.uid() != uid || metadata.mode() & 0o7777 != 0o600
        || metadata.nlink() != 1 || flags < 0 || flags & libc::O_ACCMODE != expected
        || flags & (libc::O_APPEND | libc::O_PATH) != 0
    { return Err(invalid("original Material file owner, type, link, mode or access differs")); }
    Ok(metadata)
}

fn same_file(before: &Metadata, after: &Metadata) -> bool {
    before.dev() == after.dev() && before.ino() == after.ino() && before.len() == after.len()
        && before.uid() == after.uid() && before.gid() == after.gid() && before.mode() == after.mode()
        && before.nlink() == after.nlink() && before.mtime() == after.mtime()
        && before.mtime_nsec() == after.mtime_nsec() && before.ctime() == after.ctime()
        && before.ctime_nsec() == after.ctime_nsec()
}

pub(super) fn read_root<T: DeserializeOwned>(file: &File) -> Result<T, AgentdError> {
    let before = private_file(file, 0, Access::ReadOnly)?;
    if before.len() == 0 || before.len() > 65_536 { return Err(invalid("bounded Root configuration is absent")); }
    let mut bytes = vec![0; before.len() as usize];
    file.read_exact_at(&mut bytes, 0)?;
    let after = private_file(file, 0, Access::ReadOnly)?;
    if !same_file(&before, &after) { return Err(invalid("Root configuration changed during observation")); }
    serde_json::from_slice(&bytes).map_err(invalid)
}

pub(super) fn read_key(file: File, uid: u32) -> Result<SigningKey, AgentdError> {
    let before = private_file(&file, uid, Access::ReadOnly)?;
    if before.len() != 32 { return Err(invalid("preprovisioned Material signing key has wrong size")); }
    let mut bytes = [0_u8; 32];
    if let Err(error) = file.read_exact_at(&mut bytes, 0) {
        bytes.fill(0);
        return Err(error.into());
    }
    let after = match private_file(&file, uid, Access::ReadOnly) {
        Ok(after) => after,
        Err(error) => { bytes.fill(0); return Err(error); }
    };
    if !same_file(&before, &after) {
        bytes.fill(0);
        return Err(invalid("preprovisioned signing key changed during observation"));
    }
    let key = SigningKey::from_bytes(&bytes);
    bytes.fill(0);
    Ok(key)
}

pub(super) fn require_all(files: &OriginalMaterialHostFilesV1, cfg: &Configuration) -> Result<(), AgentdError> {
    let mut originals = BTreeSet::new();
    for file in [&files.configuration, &files.evidence_trust, &files.trust_root, &files.signed_distribution,
        &files.baseline.base, &files.baseline.encoder, &files.baseline.heads] {
        let metadata = private_file(file, 0, Access::ReadOnly)?;
        if !originals.insert((metadata.dev(), metadata.ino())) { return Err(invalid("duplicate Root input inode")); }
    }
    for file in [&files.baseline.organ_adapter, &files.baseline.cell_adapter].into_iter().flatten() {
        let metadata = private_file(file, 0, Access::ReadOnly)?;
        if !originals.insert((metadata.dev(), metadata.ino())) { return Err(invalid("duplicate model input inode")); }
    }
    for file in [&files.experience_key, &files.dataset_key] {
        let metadata = private_file(file, cfg.material.uid, Access::ReadOnly)?;
        if metadata.len() != 32 || !originals.insert((metadata.dev(), metadata.ino())) {
            return Err(invalid("Material key inode aliases another input or has wrong size"));
        }
    }
    for file in [&files.ledger, &files.ledger_witness, &files.experience, &files.experience_witness,
        &files.dataset, &files.dataset_witness] {
        let metadata = private_file(file, cfg.material.uid, Access::ReadWrite)?;
        if !originals.insert((metadata.dev(), metadata.ino())) { return Err(invalid("Material writers must have distinct original inodes")); }
    }
    if files.ledger.metadata()?.len() < 72 || files.ledger_witness.metadata()?.len() < 72 {
        return Err(invalid("Material cannot initialize or replace its original ledger/witness"));
    }
    for file in [&files.experience, &files.experience_witness, &files.dataset, &files.dataset_witness] {
        let length = file.metadata()?.len();
        match cfg.operation {
            Operation::Create if length != 0 => return Err(invalid("explicit pair create requires the preheld original empty files")),
            Operation::Recover if length == 0 => return Err(invalid("pair recovery cannot initialize a missing owner")),
            _ => {},
        }
    }
    require_directory_child(&files.ledger_directory, &files.ledger, &cfg.ledger_name, cfg.material.uid)?;
    require_directory_child(&files.witness_directory, &files.ledger_witness, &cfg.ledger_witness_name, cfg.material.uid)?;
    let channels = [(&files.source, &cfg.source_root, 0, cfg.source_root_gid),
        (&files.workflow, &cfg.workflow_root, 0, cfg.workflow_root_gid),
        (&files.experience_command, &cfg.experience_command.peer, cfg.experience_command.uid, cfg.experience_command.gid),
        (&files.dataset_command, &cfg.dataset_command.peer, cfg.dataset_command.uid, cfg.dataset_command.gid),
        (&files.experience_readback, &cfg.experience_readback.peer, cfg.experience_readback.uid, cfg.experience_readback.gid),
        (&files.dataset_readback, &cfg.dataset_readback.peer, cfg.dataset_readback.uid, cfg.dataset_readback.gid),
        (&files.dataset_source, &cfg.dataset_source.peer, cfg.dataset_source.uid, cfg.dataset_source.gid)];
    for (channel, peer, uid, gid) in channels {
        let mut value = std::mem::MaybeUninit::<libc::stat>::uninit();
        // SAFETY: fstat initializes value on success and observes this live
        // stream only. Dup aliases must not become competing role readers.
        if unsafe { libc::fstat(channel.stream.as_raw_fd(), value.as_mut_ptr()) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        // SAFETY: successful fstat initialized value above.
        let value = unsafe { value.assume_init() };
        if value.st_mode & libc::S_IFMT != libc::S_IFSOCK || !originals.insert((value.st_dev, value.st_ino)) {
            return Err(invalid("original Material channels must be distinct actual sockets"));
        }
        require_peer(&channel.stream, &channel.original_peer_pidfd, peer, uid, gid)?;
    }
    Ok(())
}

fn require_directory_child(directory: &File, child: &File, name: &str, uid: u32) -> Result<(), AgentdError> {
    let parent = directory.metadata()?;
    if !parent.is_dir() || parent.uid() != uid || parent.mode() & 0o7777 != 0o700
        || name.is_empty() || name.len() > 255 || name == "." || name == ".." || name.contains('/')
    { return Err(invalid("original Material custody directory/name differs")); }
    let name = CString::new(name).map_err(invalid)?;
    let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
    // SAFETY: the directory and nul-terminated name are live; successful
    // fstatat initializes stat. AT_SYMLINK_NOFOLLOW refuses a named alias.
    if unsafe { libc::fstatat(directory.as_raw_fd(), name.as_ptr(), stat.as_mut_ptr(), libc::AT_SYMLINK_NOFOLLOW) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: fstatat returned success above.
    let stat = unsafe { stat.assume_init() };
    let metadata = child.metadata()?;
    if stat.st_mode & libc::S_IFMT != libc::S_IFREG || stat.st_dev != metadata.dev() || stat.st_ino != metadata.ino() {
        return Err(invalid("ledger directory entry is not its actual original descriptor"));
    }
    Ok(())
}

pub(super) fn require_peer(stream: &UnixStream, pidfd: &OwnedFd, peer: &Peer, uid: u32, gid: u32)
    -> Result<(), AgentdError>
{
    require_process(peer, uid, gid)?;
    crate::root_production_handoff::require_original_resident_process_pin(pidfd, peer.pid).map_err(invalid)?;
    let mut credentials = std::mem::MaybeUninit::<libc::ucred>::uninit();
    let mut size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    // SAFETY: getsockopt writes only the ucred buffer of the supplied size.
    if unsafe { libc::getsockopt(stream.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED,
        credentials.as_mut_ptr().cast(), &mut size) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if size as usize != std::mem::size_of::<libc::ucred>() { return Err(invalid("SO_PEERCRED size differs")); }
    // SAFETY: getsockopt successfully filled exactly one ucred.
    let credentials = unsafe { credentials.assume_init() };
    if credentials.pid <= 0 || credentials.pid as u32 != peer.pid || credentials.uid != uid || credentials.gid != gid {
        return Err(invalid("fixed Material channel peer differs"));
    }
    require_process(peer, uid, gid)
}

pub(super) fn require_process(peer: &Peer, uid: u32, gid: u32) -> Result<(), AgentdError> {
    if peer.pid == 0 || peer.pid > i32::MAX as u32 || peer.process_start_ticks == 0
        || bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
    { return Err(invalid("original process boot identity differs")); }
    let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
    let ticks = stat.rsplit_once(") ").and_then(|(_, rest)| rest.split_whitespace().nth(19))
        .and_then(|v| v.parse::<u64>().ok());
    if ticks != Some(peer.process_start_ticks) { return Err(invalid("original process start ticks differ")); }
    crate::authority_host_runtime::verify_process_credentials(peer.pid, uid, gid)?;
    Ok(())
}

fn bounded_text(path: &str, maximum: u64) -> Result<String, AgentdError> {
    let mut text = String::new();
    File::open(path)?.take(maximum + 1).read_to_string(&mut text)?;
    if text.len() as u64 > maximum { return Err(invalid("bounded process record exceeded")); }
    Ok(text)
}

pub(super) fn original_ends(cfg: &Configuration, entered: Instant) -> Result<(Instant, Instant), AgentdError> {
    // Sample Instant first, so translating the same real monotonic epoch never
    // increases either supplied deadline by time spent sampling that clock.
    let anchor = Instant::now();
    let mut value = std::mem::MaybeUninit::<libc::timespec>::uninit();
    // SAFETY: successful clock_gettime initializes this timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, value.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: clock_gettime returned success above.
    let value = unsafe { value.assume_init() };
    let sampled = u64::try_from(value.tv_sec).ok().and_then(|s| s.checked_mul(1_000_000_000))
        .and_then(|s| u64::try_from(value.tv_nsec).ok().filter(|n| *n < 1_000_000_000).and_then(|n| s.checked_add(n)))
        .ok_or_else(|| invalid("original monotonic clock could not be represented"))?;
    let remaining_end = cfg.lifetime_deadline_monotonic_ns.checked_sub(sampled).filter(|n| *n != 0)
        .ok_or_else(|| invalid("original Material lifetime already ended"))?;
    let remaining_start = cfg.startup_deadline_monotonic_ns.checked_sub(sampled).filter(|n| *n != 0)
        .ok_or_else(|| invalid("original common startup already ended"))?;
    let end = anchor.checked_add(Duration::from_nanos(remaining_end)).ok_or_else(|| invalid("invalid original lifetime"))?
        .min(entered + Duration::from_secs(300));
    let startup = anchor.checked_add(Duration::from_nanos(remaining_start)).ok_or_else(|| invalid("invalid original startup"))?
        .min(entered + Duration::from_secs(30)).min(end);
    remaining(startup)?;
    Ok((startup, end))
}
pub(super) fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now()).filter(|d| !d.is_zero())
        .ok_or_else(|| invalid("original Material deadline ended; same-operation readback is required"))
}
pub(super) fn now() -> Result<u64, AgentdError> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).map_err(invalid)
}
