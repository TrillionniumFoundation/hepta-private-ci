//! Validation of private physical publication material, without writer activation.

use super::*;
use std::path::Path;
use std::path::PathBuf;

#[path = "cognitive_store_material_install.rs"]
mod install;
pub use install::InstalledCognitiveMaterial;

#[path = "cognitive_store_material_registration.rs"]
mod registration;
pub use registration::RootCognitiveMaterialRegistration;

/// A validated private image, not a protected Current or permission to recover.
/// Root must durably commit its original checkpoint before treating this cut
/// as Current. This object supplies no writer, grant, replay or activation API.
pub struct VerifiedCognitiveMaterial {
    path: PathBuf,
    anchor: CognitiveRecoveryAnchor,
    retained: codex_state::ExistingSqliteRecoveryGuard,
}

impl VerifiedCognitiveMaterial {
    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn anchor(&self) -> &CognitiveRecoveryAnchor {
        &self.anchor
    }

    /// Metadata/identity revalidation of the same held database, parent and
    /// sidecar descriptors. No SQLite work, full hash, Current or grant is
    /// inferred. Full-cut/integrity verification precedes construction.
    pub fn verify_unchanged(&self) -> Result<(), CognitiveRecoveryError> {
        #[cfg(unix)]
        {
            codex_hepta_contracts::RootAuthorityDirectory::open(self.path.parent().ok_or_else(
                || CognitiveRecoveryError::Invalid("material parent missing".into()),
            )?)
            .map_err(|error| CognitiveRecoveryError::AccessDenied(error.to_string()))?;
            self.retained
                .verify_inspection_unchanged()
                .map_err(recovery_error)
        }
        #[cfg(not(unix))]
        {
            Err(CognitiveRecoveryError::Unavailable(
                "Root material admission requires Unix".into(),
            ))
        }
    }
}

pub(super) async fn validate_private_candidate(
    config: &SqliteConfig,
    candidate: &Path,
    owner: &AgentId,
    expected: &CognitiveRecoveryAnchor,
    root: &Path,
    commit_gate: &CognitiveCommitGate,
) -> Result<(), CognitiveRecoveryError> {
    let connection_gate = commit_gate.clone();
    let pool = config
        .open_durable_evidence_pool_guarded(&candidate, move || connection_gate.commit_allowed())
        .await
        .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
    let authenticated = async {
        let mut transaction = pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
        let observed = capture(&mut transaction, owner)
            .await
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        if observed != *expected {
            return Err(CognitiveRecoveryError::AccessDenied(
                "recovery candidate differs from independently retained current cut".to_string(),
            ));
        }
        let integrity: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check(1)")
            .fetch_all(&mut *transaction)
            .await
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        if integrity != ["ok"] {
            return Err(CognitiveRecoveryError::Indeterminate(
                "recovery candidate failed SQLite integrity_check".to_string(),
            ));
        }
        transaction
            .commit()
            .await
            .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;

        // Authenticate the bounded schema and full cut above before any
        // quick_check/foreign_key_check can evaluate candidate SQL expressions.
        // Release the sole pooled connection before the original store check.
        verify_store(&pool, owner)
            .await
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;

        Ok(())
    }
    .await;
    if let Err(error) = authenticated {
        pool.close().await;
        return Err(error);
    }
    pool.close().await;

    config
        .checkpoint_private_recovery_database(&candidate)
        .await
        .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;

    cleanup_candidate_sidecars(&candidate)?;
    protect_database_file(&candidate)
        .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
    {
        let mut options = std::fs::OpenOptions::new();
        options.read(true);
        #[cfg(windows)]
        options.write(true);
        let file = options.open(&candidate).map_err(|error| {
            CognitiveRecoveryError::Unavailable(format!(
                "open recovered cognitive database for sync: {error}"
            ))
        })?;
        file.sync_all().map_err(|error| {
            CognitiveRecoveryError::Unavailable(format!(
                "sync recovered cognitive database: {error}"
            ))
        })?;
    }
    sync_cognitive_directory(root)
        .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;

    Ok(())
}

impl CognitiveStore {
    /// Root-private physical material admission is unavailable on non-Unix
    /// platforms. This does not change the original shared recovery verifier.
    #[cfg(not(unix))]
    pub async fn verify_root_material_candidate(
        layout: &HeptaAgentLayout,
        expected: &CognitiveRecoveryAnchor,
    ) -> Result<VerifiedCognitiveMaterial, CognitiveRecoveryError> {
        let _ = (layout, expected);
        Err(CognitiveRecoveryError::Unavailable(
            "Root material admission requires Unix".into(),
        ))
    }

    /// Revalidation of retained Root material is unavailable on non-Unix.
    #[cfg(not(unix))]
    pub async fn verify_retained_root_material(
        layout: &HeptaAgentLayout,
        expected: &CognitiveRecoveryAnchor,
    ) -> Result<VerifiedCognitiveMaterial, CognitiveRecoveryError> {
        let _ = (layout, expected);
        Err(CognitiveRecoveryError::Unavailable(
            "Root material admission requires Unix".into(),
        ))
    }

    /// Validate and consolidate an already isolated Root-private candidate.
    ///
    /// The launcher derives this layout from its fixed material registration.
    /// It must be an actual Root-owned protected path through non-writable
    /// Root ancestors. The only database filename accepted is the original
    /// cognitive database name; no live owner or active pointer is opened.
    ///
    /// `expected` is the exact prospective cut from the original authenticated
    /// publication exchange. Equality authenticates these candidate bytes to
    /// that exchange, not their currentness. No checkpoint is advanced here.
    /// The caller must retain this material before the original Prepare/Commit
    /// CAS can reference it, and must independently reconcile every unknown.
    #[cfg(unix)]
    pub async fn verify_root_material_candidate(
        layout: &HeptaAgentLayout,
        expected: &CognitiveRecoveryAnchor,
    ) -> Result<VerifiedCognitiveMaterial, CognitiveRecoveryError> {
        validate_requirement(
            layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(expected),
        )?;
        let root = layout.cognitive_root();
        let _protected = codex_hepta_contracts::RootAuthorityDirectory::open(root)
            .map_err(|error| CognitiveRecoveryError::AccessDenied(error.to_string()))?;
        let config = SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::try_from(root.to_path_buf())
                .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?,
        );
        let path = root.join(super::super::COGNITIVE_DB_FILENAME);
        // Validate Root ownership/mode/link/sidecar identities before SQLite is
        // allowed to recover this private copy. The live source is never opened.
        config
            .bind_existing_recovery_database(&path)
            .map_err(recovery_error)?;
        validate_private_candidate(
            &config,
            &path,
            layout.agent_id(),
            expected,
            root,
            &CognitiveCommitGate::default(),
        )
        .await?;
        Self::verify_retained_root_material(layout, expected).await
    }

    /// Recheck an already consolidated private image using the original
    /// retained-descriptor read-only verifier. No checkpoint, journal-mode
    /// change, sidecar cleanup, writer, Current or recovery activation occurs.
    /// The caller independently proves the cut is the retained Current before
    /// using it for recovery; this method establishes exact image integrity.
    #[cfg(unix)]
    pub async fn verify_retained_root_material(
        layout: &HeptaAgentLayout,
        expected: &CognitiveRecoveryAnchor,
    ) -> Result<VerifiedCognitiveMaterial, CognitiveRecoveryError> {
        use std::os::unix::fs::OpenOptionsExt;
        validate_requirement(
            layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(expected),
        )?;
        let root = layout.cognitive_root();
        let _protected = codex_hepta_contracts::RootAuthorityDirectory::open(root)
            .map_err(|error| CognitiveRecoveryError::AccessDenied(error.to_string()))?;
        let config = SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::try_from(root.to_path_buf())
                .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?,
        );
        let path = root.join(super::super::COGNITIVE_DB_FILENAME);
        let guard = config
            .bind_existing_recovery_database(&path)
            .map_err(recovery_error)?;
        let pool = config
            .open_cold_image_read_only_pool(&guard)
            .await
            .map_err(recovery_error)?;
        let verified = async {
            let mut transaction = pool.begin().await.map_err(unavailable)?;
            let observed = capture(&mut transaction, layout.agent_id()).await?;
            if observed != *expected {
                return Err(CognitiveStoreError::Corrupt(
                    "private material changed after consolidation".into(),
                ));
            }
            let integrity: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check(1)")
                .fetch_all(&mut *transaction)
                .await
                .map_err(unavailable)?;
            if integrity != ["ok"] {
                return Err(CognitiveStoreError::Corrupt(
                    "private material failed final integrity check".into(),
                ));
            }
            transaction.rollback().await.map_err(unavailable)?;
            Ok::<_, CognitiveStoreError>(())
        }
        .await;
        pool.close().await;
        verified.map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        guard
            .verify_inspection_unchanged()
            .map_err(recovery_error)?;
        // Read-only revalidation also completes durability for a prior
        // uncertain copy. It does not rewrite or reconsolidate Current bytes.
        std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&path)
            .and_then(|file| file.sync_all())
            .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
        sync_cognitive_directory(root)
            .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
        guard
            .verify_inspection_unchanged()
            .map_err(recovery_error)?;
        Ok(VerifiedCognitiveMaterial {
            path,
            anchor: expected.clone(),
            retained: guard,
        })
    }
}
