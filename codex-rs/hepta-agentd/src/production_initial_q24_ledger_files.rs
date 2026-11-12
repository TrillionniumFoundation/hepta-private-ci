//! Existing owner descriptors plus the actual Root client's opaque trust handoff.
//! Explicit first-A initialization cannot repair or replace earlier history.
//! An error after initialization can leave original headers; it never retries
//! by erasing them. The actual producer initializes the still-empty signature
//! journal only after binding these inputs to the original published task.

use std::ffi::CString;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;

use super::files::OriginalFiles;
use super::files::require_unwritten;
use super::ledger_data::LedgerDeploymentData;
use super::ledger_data::invalid;
use crate::AgentdError;
use crate::CircuitQ24TaskOpenModeV1;
use crate::OriginalCellQ24TaskLedgerInputsV1;
use crate::OriginalRootInitialLearningTrustV1;

pub(super) fn open(
    data: LedgerDeploymentData,
    original: OriginalRootInitialLearningTrustV1,
    files: &mut OriginalFiles,
) -> Result<OriginalCellQ24TaskLedgerInputsV1, AgentdError> {
    let (trust, generator, observer) = original.into_ledger_authorities();
    let observed_at = now()?;
    trust
        .verifier()
        .require_signer_binding(LearningEvidenceRoleV1::Generator, &generator, observed_at)
        .map_err(invalid)?;
    trust
        .verifier()
        .require_signer_binding(LearningEvidenceRoleV1::Observer, &observer, observed_at)
        .map_err(invalid)?;
    verify_independent_roles(&generator.principal, &observer.principal, observed_at)
        .map_err(invalid)?;
    if generator.controller_id == observer.controller_id {
        return Err(invalid("Generator and Observer share a controller"));
    }
    let config = data.configuration(generator, observer, observed_at)?;
    let objective = trust.verifier().objective_digest();
    let binding = Digest32::from_array(data.binding);
    let key_file = files.read(&data.generator_key)?;
    let generator_key = original_key(&key_file, &config.generator.verifying_key)?;
    // Use the same tracker as Source, Cell, Artifact and model loading. All
    // writer aliases and all nonempty first-A files fail before initialization.
    let ledger_file = files.write(&data.ledger)?;
    let witness_file = files.write(&data.ledger_witness)?;
    let signature_journal = files.write(&data.signature_journal)?;
    let signature_witness_file = files.write(&data.signature_witness.path)?;
    let mut held = Vec::with_capacity(4);
    for (path, file) in [
        (&data.ledger, &ledger_file),
        (&data.ledger_witness, &witness_file),
        (&data.signature_journal, &signature_journal),
        (&data.signature_witness.path, &signature_witness_file),
    ] {
        require_unwritten(file)?;
        held.push(OriginalParent::open_original(path, file)?);
    }
    let ledger =
        DurableLedger::create(ledger_file, binding, data.maximum_records).map_err(invalid)?;
    let witness = LedgerWitnessStore::create(witness_file, binding).map_err(invalid)?;
    let signature_witness = FileAnchorWitnessStore::open(
        signature_witness_file,
        JournalScope {
            scope_digest: Digest32::from_array(data.signature_witness.scope),
            objective_digest: objective,
        },
        Generation::new(data.signature_witness.generation).map_err(invalid)?,
        data.signature_witness.maximum_records,
    )
    .map_err(invalid)?;
    if signature_witness.current().map_err(invalid)?.is_some() {
        return Err(invalid("first-A signature witness already has history"));
    }
    let ledger = LedgerWriter::from_durable(
        ledger,
        witness,
        trust,
        &held[0].directory,
        &held[1].directory,
    )
    .map_err(invalid)?;
    for parent in &held {
        parent.require_original()?;
        parent.directory.sync_all()?;
        parent.require_original()?;
    }
    if original_key(&key_file, &config.generator.verifying_key)?.to_bytes()
        != generator_key.to_bytes()
        || now()? >= config.claim_deadline_unix_seconds
    {
        return Err(invalid("original Generator changed during initialization"));
    }
    for (role, signer) in [
        (LearningEvidenceRoleV1::Generator, &config.generator),
        (LearningEvidenceRoleV1::Observer, &config.observer),
    ] {
        ledger
            .verifier()
            .require_signer_binding(role, signer, now()?)
            .map_err(invalid)?;
    }
    Ok(OriginalCellQ24TaskLedgerInputsV1 {
        ledger: Arc::new(Mutex::new(ledger)),
        signature_journal,
        signature_witness,
        open_mode: CircuitQ24TaskOpenModeV1::Create,
        config,
        generator_key,
    })
}

struct OriginalParent {
    directory: File,
    directory_path: PathBuf,
    original_file: File,
    name: CString,
}

impl OriginalParent {
    fn open_original(path: &Path, original_file: &File) -> Result<Self, AgentdError> {
        let parent = path
            .parent()
            .ok_or_else(|| invalid("original containing directory missing"))?;
        if parent.canonicalize()? != parent {
            return Err(invalid("original containing directory is not canonical"));
        }
        let directory = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(parent)?;
        let name = CString::new(
            path.file_name()
                .ok_or_else(|| invalid("original filename missing"))?
                .as_bytes(),
        )
        .map_err(invalid)?;
        let held = Self {
            directory,
            directory_path: parent.to_path_buf(),
            original_file: original_file.try_clone()?,
            name,
        };
        held.require_original()?;
        Ok(held)
    }

    fn require_original(&self) -> Result<(), AgentdError> {
        let directory = self.directory.metadata()?;
        let path = std::fs::symlink_metadata(&self.directory_path)?;
        let file = self.original_file.metadata()?;
        // SAFETY: geteuid only observes this process's actual owner.
        let uid = unsafe { libc::geteuid() };
        if !directory.is_dir()
            || !path.is_dir()
            || directory.dev() != path.dev()
            || directory.ino() != path.ino()
            || directory.uid() != uid
            || directory.mode() & 0o077 != 0
            || !file.is_file()
            || file.uid() != uid
            || file.mode() & 0o077 != 0
            || file.nlink() != 1
        {
            return Err(invalid("original Ledger parent/file custody changed"));
        }
        let mut entry = std::mem::MaybeUninit::<libc::stat>::uninit();
        // SAFETY: the owned directory descriptor and NUL-terminated filename
        // live through fstatat, which initializes entry on a successful return.
        let result = unsafe {
            libc::fstatat(
                self.directory.as_raw_fd(),
                self.name.as_ptr(),
                entry.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        };
        if result != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        // SAFETY: fstatat returned zero and initialized the complete stat value.
        let entry = unsafe { entry.assume_init() };
        if entry.st_dev != file.dev()
            || entry.st_ino != file.ino()
            || entry.st_mode & libc::S_IFMT != libc::S_IFREG
            || entry.st_nlink != 1
        {
            return Err(invalid(
                "Ledger descriptor is not the original directory entry",
            ));
        }
        Ok(())
    }
}

fn original_key(file: &File, verifying_key: &[u8; 32]) -> Result<SigningKey, AgentdError> {
    // SAFETY: F_GETFL only inspects the live, owned original descriptor.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    if flags < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if flags & libc::O_ACCMODE != libc::O_RDONLY || flags & libc::O_PATH != 0 {
        return Err(invalid(
            "original Generator key requires a read-only descriptor",
        ));
    }
    let stamp = |m: std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.uid(),
            m.gid(),
            m.mode(),
            m.nlink(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    let before = file.metadata()?;
    if !before.is_file() || before.len() != 32 || before.nlink() != 1 || before.mode() & 0o077 != 0
    {
        return Err(invalid(
            "original Generator key must be a private 32-byte file",
        ));
    }
    let before = stamp(before);
    let mut bytes = [0_u8; 32];
    let mut comparison = [0_u8; 32];
    file.read_exact_at(&mut bytes, /*offset*/ 0)?;
    file.read_exact_at(&mut comparison, /*offset*/ 0)?;
    if bytes != comparison || stamp(file.metadata()?) != before {
        return Err(invalid("original Generator key changed while reading"));
    }
    let key = SigningKey::from_bytes(&bytes);
    if key.verifying_key().to_bytes() != *verifying_key {
        return Err(invalid("Generator key differs from the original Root role"));
    }
    Ok(key)
}

fn now() -> Result<u64, AgentdError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|time| time.as_secs())
        .map_err(invalid)
}

#[cfg(test)]
#[path = "production_initial_q24_ledger_files_tests.rs"]
mod tests;
