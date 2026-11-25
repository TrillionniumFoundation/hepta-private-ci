//! Fixed registered-owner installation of original, retained Root material.

use super::super::super::COGNITIVE_ACTIVE_DB_POINTER;
use super::super::super::COGNITIVE_DB_FILENAME;
use super::super::super::COGNITIVE_STORE_LOCK_FILENAME;
use super::super::super::active_pointer_temporary_name;
use super::super::super::parse_active_pointer;
use super::*;
use codex_state::RootSqliteMaterialRegistration;
use codex_state::RootSqliteOwnerCopy;
use codex_state::RootSqliteOwnerPublished;
use std::ffi::OsStr;

/// Physical installed bytes, still holding the original exclusive store lock.
/// The anchor authenticates image contents, not protected Current or permission
/// to recover. The trusted Root caller must finish its original full-head/token
/// and lifetime checks while retaining this capability, then drop it before
/// releasing the actual UID60001 launch to the original recovery factory.
/// No writer, checkpoint setter, second owner, frontier reset or grant exists.
#[must_use]
pub struct InstalledCognitiveMaterial {
    anchor: CognitiveRecoveryAnchor,
    publication: RootSqliteOwnerPublished,
}

impl InstalledCognitiveMaterial {
    pub fn path(&self) -> &Path {
        self.publication.path()
    }
    pub fn anchor(&self) -> &CognitiveRecoveryAnchor {
        &self.anchor
    }

    /// Recheck the same physical source, owner directory, original lock,
    /// installed image and pointer. This never re-authenticates Current.
    pub fn verify_unchanged(&self) -> Result<(), CognitiveRecoveryError> {
        self.publication.verify_unchanged().map_err(recovery_error)
    }
}

impl VerifiedCognitiveMaterial {
    /// Install an exact retained image for the fixed UID60001 original owner.
    ///
    /// The Root caller supplies its independently authenticated full Current
    /// anchor and fixed original layout. It must have retired the old publisher
    /// and retain its serialized slot through this synchronous operation even
    /// if its caller disconnects. This API never establishes those facts itself.
    /// The existing original lock must already exist; no owner/frontier/counter
    /// directory is created or reset. All older Dirty images remain untouched.
    ///
    /// A distinct installation discriminator leaves the later original factory
    /// free to create its own authority-bound recovered generation. The original
    /// pointer parser and encoding stay unchanged. Any error can leave a new
    /// image or changed pointer; no automatic retry/cleanup is safe. Reconcile
    /// with original Root Current and re-enter the trusted cold-launch ceremony.
    pub fn install_for_registered_owner(
        self,
        layout: &HeptaAgentLayout,
        expected_current: &CognitiveRecoveryAnchor,
    ) -> Result<InstalledCognitiveMaterial, CognitiveRecoveryError> {
        RootSqliteMaterialRegistration::verify_caller(/*registered_uid*/ 60001)
            .map_err(recovery_error)?;
        validate_requirement(
            layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(expected_current),
        )?;
        if self.anchor != *expected_current {
            return Err(CognitiveRecoveryError::AccessDenied(
                "retained material differs from independent Current".into(),
            ));
        }
        self.verify_unchanged()?;
        let root = layout.cognitive_root();
        let config = SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::try_from(root.to_path_buf())
                .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?,
        );
        // This is only a physical install-attempt discriminator, never an
        // authority fence. The original factory still requires its real lease.
        let discriminator = Sha256Digest::for_bytes(b"hepta:cognitive:root-material-install:v1");
        let name = recovered_database_filename(expected_current, &discriminator);
        let temporary = active_pointer_temporary_name(&name)
            .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?;
        let publication = RootSqliteOwnerCopy::bind_registered(
            &config,
            OsStr::new(COGNITIVE_STORE_LOCK_FILENAME),
        )
        .map_err(recovery_error)?
        .materialize_consolidated_candidate(&self.retained, OsStr::new(&name))
        .map_err(recovery_error)?
        .observe_active_pointer(OsStr::new(COGNITIVE_ACTIVE_DB_POINTER))
        .map_err(recovery_error)?;
        let previous = match publication.previous_pointer_bytes() {
            Some(bytes) => parse_active_pointer(
                std::str::from_utf8(bytes)
                    .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?,
            )
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?,
            None => COGNITIVE_DB_FILENAME,
        };
        // Reuse the original resolver's target checks as well as its parser;
        // the held pointer snapshot is verified before publication afterwards.
        let selected = resolve_active_database_path(root)
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        if selected != root.join(previous) {
            return Err(CognitiveRecoveryError::Indeterminate(
                "active pointer changed during installation".into(),
            ));
        }
        publication.verify_unchanged().map_err(recovery_error)?;
        self.verify_unchanged()?;
        let publication = publication
            .publish(OsStr::new(&temporary))
            .map_err(recovery_error)?;
        self.verify_unchanged()?;
        let installed = InstalledCognitiveMaterial {
            anchor: self.anchor,
            publication,
        };
        installed.verify_unchanged()?;
        Ok(installed)
    }
}
