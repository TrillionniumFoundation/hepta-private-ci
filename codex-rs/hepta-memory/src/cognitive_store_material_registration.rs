//! Fixed active-generation registration, separate from each copy attempt.

use super::*;
use codex_state::RootSqliteMaterialIdentity;
use codex_state::RootSqliteMaterialRegistration;

/// A Root-only registration of the actual original active generation. The
/// launcher binds this AFTER the original recovery factory returns the sole
/// owner, before protected publication and Session release. Root persists its
/// identity in the existing protected registration; this is no Current witness.
pub struct RootCognitiveMaterialRegistration {
    layout: HeptaAgentLayout,
    source: RootSqliteMaterialRegistration,
    #[cfg(unix)]
    pointer: Option<(std::fs::File, std::fs::Metadata, Vec<u8>)>,
}

impl RootCognitiveMaterialRegistration {
    /// Derive the filename with the original private active-pointer parser.
    /// Neither a checkpoint request nor the Host supplies a source filename.
    /// A subsequent cold recovery needs a new trusted-launch registration;
    /// capture never automatically admits another generation or inode.
    pub fn bind_registered_layout(
        layout: &HeptaAgentLayout,
        registered_uid: u32,
    ) -> Result<Self, CognitiveRecoveryError> {
        #[cfg(unix)]
        {
            // SAFETY: geteuid has no preconditions or pointer arguments.
            if unsafe { libc::geteuid() } != 0 || registered_uid == 0 {
                return Err(CognitiveRecoveryError::AccessDenied(
                    "Root must register a non-Root owner".into(),
                ));
            }
            let root = layout.cognitive_root();
            let path = resolve_active_database_path(root)
                .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
            let config = SqliteConfig::from_sqlite_home(
                AbsolutePathBuf::try_from(root.to_path_buf())
                    .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?,
            );
            let source =
                RootSqliteMaterialRegistration::bind_registered(&config, &path, registered_uid)
                    .map_err(recovery_error)?;
            let pointer = retain_pointer(root, registered_uid)?;
            let result = Self {
                layout: layout.clone(),
                source,
                pointer,
            };
            result.verify_registered()?;
            Ok(result)
        }
        #[cfg(not(unix))]
        {
            let _ = (layout, registered_uid);
            Err(CognitiveRecoveryError::Unavailable(
                "Root material registration requires Unix".into(),
            ))
        }
    }

    pub fn identity(&self) -> &RootSqliteMaterialIdentity {
        self.source.identity()
    }

    /// Revalidate the immutable selection and retained identities. Database
    /// content may change; its full bytes/sidecars receive a new bounded guard
    /// for each copy. Pointer contents and identity may not change at all.
    pub fn verify_registered(&self) -> Result<(), CognitiveRecoveryError> {
        self.source.verify_registered().map_err(recovery_error)?;
        #[cfg(unix)]
        verify_pointer(self.layout.cognitive_root(), &self.pointer)?;
        let selected = resolve_active_database_path(self.layout.cognitive_root())
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        if selected != self.source.identity().database_path() {
            return Err(CognitiveRecoveryError::Indeterminate(
                "registered cognitive generation changed".into(),
            ));
        }
        Ok(())
    }

    /// Copy to one fresh original default filename in a fixed Root layout.
    /// The caller holds the original coherent owner transaction; copying does
    /// not acquire its live exclusive lock, authenticate Current or publish.
    /// Exact full-cut/schema/integrity validation remains mandatory afterwards.
    pub fn materialize_private_candidate(
        &self,
        destination: &HeptaAgentLayout,
    ) -> Result<PathBuf, CognitiveRecoveryError> {
        if destination.agent_id() != self.layout.agent_id() {
            return Err(CognitiveRecoveryError::AccessDenied(
                "material destination owner differs".into(),
            ));
        }
        self.verify_registered()?;
        let config = SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::try_from(destination.cognitive_root().to_path_buf())
                .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?,
        );
        let capture = self.source.bind_capture(&config).map_err(recovery_error)?;
        self.verify_registered()?;
        let candidate = capture
            .materialize_private_candidate(std::ffi::OsStr::new(
                super::super::super::COGNITIVE_DB_FILENAME,
            ))
            .map_err(recovery_error)?;
        self.verify_registered()?;
        Ok(candidate)
    }
}

#[cfg(unix)]
fn retain_pointer(
    root: &Path,
    registered_uid: u32,
) -> Result<Option<(std::fs::File, std::fs::Metadata, Vec<u8>)>, CognitiveRecoveryError> {
    use std::io::Read;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = match std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(root.join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER))
    {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(CognitiveRecoveryError::Indeterminate(error.to_string())),
    };
    let metadata = file
        .metadata()
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
    if !metadata.is_file()
        || metadata.uid() != registered_uid
        || metadata.nlink() != 1
        || metadata.mode() & 0o7777 != 0o600
        || metadata.len() > 256
    {
        return Err(CognitiveRecoveryError::Indeterminate(
            "registered active pointer is not private".into(),
        ));
    }
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(257)
        .read_to_end(&mut bytes)
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
    if bytes.len() > 256 {
        return Err(CognitiveRecoveryError::Indeterminate(
            "registered active pointer exceeds bound".into(),
        ));
    }
    Ok(Some((file, metadata, bytes)))
}

#[cfg(unix)]
fn verify_pointer(
    root: &Path,
    retained: &Option<(std::fs::File, std::fs::Metadata, Vec<u8>)>,
) -> Result<(), CognitiveRecoveryError> {
    use std::os::unix::fs::FileExt;
    use std::os::unix::fs::MetadataExt;
    let path = root.join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER);
    let path_metadata = std::fs::symlink_metadata(&path);
    let Some((file, expected, bytes)) = retained else {
        return match path_metadata {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            _ => Err(CognitiveRecoveryError::Indeterminate(
                "active pointer appeared after registration".into(),
            )),
        };
    };
    let snapshot = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.mode(),
            metadata.uid(),
            metadata.nlink(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
            metadata.is_file(),
            metadata.file_type().is_symlink(),
        )
    };
    for metadata in [path_metadata, file.metadata()] {
        let metadata =
            metadata.map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        if snapshot(&metadata) != snapshot(expected) {
            return Err(CognitiveRecoveryError::Indeterminate(
                "registered active pointer changed".into(),
            ));
        }
    }
    let mut observed = vec![0; bytes.len()];
    file.read_exact_at(&mut observed, 0)
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
    if observed != *bytes {
        return Err(CognitiveRecoveryError::Indeterminate(
            "registered active pointer bytes changed".into(),
        ));
    }
    let after = file
        .metadata()
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
    if snapshot(&after) != snapshot(expected) {
        return Err(CognitiveRecoveryError::Indeterminate(
            "registered active pointer changed during observation".into(),
        ));
    }
    Ok(())
}
