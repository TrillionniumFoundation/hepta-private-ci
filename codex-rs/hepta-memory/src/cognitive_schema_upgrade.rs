//! Explicit migration of an independently authenticated old owner cut.
//! Ordinary exact reopen never migrates and retains its current-schema rule.
//! The existing descriptor-bound SQLite image implementation is Unix-only;
//! other platforms return Unavailable without a path-based recovery fallback.

use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
#[cfg(unix)]
use codex_utils_absolute_path::AbsolutePathBuf;

use super::CognitiveRecoveryAnchor;
use super::CognitiveRecoveryError;
use super::CognitiveStore;
use super::CognitiveStoreOpenGuard;
use super::PROFILE;
use super::reconcile_failed_recovery_candidate;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityVerifier;
#[cfg(unix)]
use crate::cognitive_path::canonical_path_without_redirection;
use crate::cognitive_store::COGNITIVE_DB_FILENAME;
use crate::cognitive_store::MIGRATOR;
use crate::cognitive_store::publish_active_database;
use crate::cognitive_store::resolve_active_database_path;
use crate::cognitive_store::valid_recovered_database_filename;

#[path = "cognitive_schema_upgrade_image.rs"]
mod image;
#[path = "cognitive_schema_profile.rs"]
mod profile;
#[path = "cognitive_schema_upgrade_types.rs"]
mod types;

use profile::indeterminate;
pub use types::CognitiveSchemaUpgradeHostV1;
pub use types::CognitiveSchemaUpgradeTransitionV1;
pub use types::CognitiveSchemaUpgradeWitnessV1;

const TRANSITION_PROFILE: &str = "hepta:cognitive:schema-upgrade-transition:v1";

/// Verified migration candidate without a store or write capability. Dropping
/// this value releases the owner fence but preserves its candidate: the host
/// may already have retained the transition before reporting an error/crashing.
/// A retry must use this value or the independently retained transition.
pub struct PreparedCognitiveSchemaUpgradeV1 {
    root: PathBuf,
    config: SqliteConfig,
    transition: CognitiveSchemaUpgradeTransitionV1,
    open_guard: Option<Arc<CognitiveStoreOpenGuard>>,
}

impl CognitiveStore {
    /// Validate the old schema, complete current cut and exact migration ledger
    /// before migrating a private copy under the existing exclusive owner lock.
    /// No new anchor is accepted until the explicit host retention ceremony.
    /// The descriptor-bound upgrade implementation currently requires Unix.
    pub async fn prepare_schema_upgrade<H, V>(
        layout: &HeptaAgentLayout,
        host: &H,
        authority: &ProductionAuthorityLease,
        verifier: &V,
    ) -> Result<PreparedCognitiveSchemaUpgradeV1, CognitiveRecoveryError>
    where
        H: CognitiveSchemaUpgradeHostV1 + ?Sized,
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let fence = verify_authority(layout.agent_id(), authority, verifier)?;
        let CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(old) = host
            .current_witness(layout.agent_id())
            .map_err(CognitiveRecoveryError::AccessDenied)?
        else {
            return Err(CognitiveRecoveryError::AccessDenied("upgrade requires an independently retained current old anchor; pending transitions require resume".into()));
        };
        if old.owner_agent_id != *layout.agent_id() {
            return Err(CognitiveRecoveryError::AccessDenied(
                "upgrade witness owner mismatch".into(),
            ));
        }
        let source = profile::historical(&old)?;
        let target = profile::current()?;
        let plan = profile::plan_digest(&source, &target)?;
        let (root, config, guard) = acquire(layout)?;
        let active = resolve_active_database_path(&root).map_err(indeterminate)?;
        let image = image::copy_verified(&config, &root, &active, &old, &fence, &source).await?;
        let migrated = async {
            require_old(host, &old)?;
            verify_authority(layout.agent_id(), authority, verifier)?;
            MIGRATOR.run(&image.pool).await.map_err(indeterminate)?;
            profile::capture_verified(&image.pool, layout.agent_id(), &target).await
        }
        .await;
        let new = match migrated {
            Ok(new) => new,
            Err(error) => {
                image.discard().await;
                return Err(error);
            }
        };
        let image = image::seal_current(&config, &root, image, &new).await?;
        if let Err(error) = require_old(host, &old) {
            image.discard().await;
            return Err(error);
        }
        let candidate = image.close().await;
        Ok(PreparedCognitiveSchemaUpgradeV1 {
            root,
            config,
            transition: CognitiveSchemaUpgradeTransitionV1 {
                profile: TRANSITION_PROFILE.into(),
                old_anchor: old,
                new_anchor: new,
                source_version: source.version,
                target_version: target.version,
                migration_plan_digest: plan,
                authority_fence_digest: fence,
                predecessor_database_filename: filename(&active)?,
                prepared_database_filename: filename(&candidate)?,
            },
            open_guard: Some(Arc::new(guard)),
        })
    }

    /// Resume only the exact transition read from independent host custody.
    /// No local candidate discovery, anchor reconstruction, or largest-version
    /// selection is permitted, even if local files look internally consistent.
    pub async fn resume_schema_upgrade<H, V>(
        layout: &HeptaAgentLayout,
        host: &H,
        authority: &ProductionAuthorityLease,
        verifier: &V,
    ) -> Result<Self, CognitiveRecoveryError>
    where
        H: CognitiveSchemaUpgradeHostV1 + ?Sized,
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let fence = verify_authority(layout.agent_id(), authority, verifier)?;
        let CognitiveSchemaUpgradeWitnessV1::RetainedTransition(transition) = host
            .current_witness(layout.agent_id())
            .map_err(CognitiveRecoveryError::AccessDenied)?
        else {
            return Err(CognitiveRecoveryError::AccessDenied(
                "no independently retained schema transition".into(),
            ));
        };
        validate_transition(&transition, layout.agent_id(), &fence)?;
        let (root, config, guard) = acquire(layout)?;
        PreparedCognitiveSchemaUpgradeV1 {
            root,
            config,
            transition,
            open_guard: Some(Arc::new(guard)),
        }
        .activate(host, authority, verifier)
        .await
    }
}

impl PreparedCognitiveSchemaUpgradeV1 {
    pub fn transition(&self) -> &CognitiveSchemaUpgradeTransitionV1 {
        &self.transition
    }

    /// Durably retain and freshly re-read the exact transition before atomic
    /// pointer activation. On failure this handle keeps its lock and receipt;
    /// after a process loss the host-retained transition is the only resume key.
    /// On success the host must archive the transition and retain its new anchor
    /// as the current recovery witness. Every later owner mutation needs a new
    /// independently retained anchor; this transition cannot recover or replace
    /// an advanced active cut and must never serve as an automatic fallback.
    pub async fn activate<H, V>(
        &mut self,
        host: &H,
        authority: &ProductionAuthorityLease,
        verifier: &V,
    ) -> Result<CognitiveStore, CognitiveRecoveryError>
    where
        H: CognitiveSchemaUpgradeHostV1 + ?Sized,
        V: ProductionAuthorityVerifier + ?Sized,
    {
        if self.open_guard.is_none() {
            return Err(CognitiveRecoveryError::AccessDenied(
                "schema transition is already activated".into(),
            ));
        }
        let t = &self.transition;
        let owner = &t.old_anchor.owner_agent_id;
        let fence = verify_authority(owner, authority, verifier)?;
        validate_transition(t, owner, &fence)?;
        match host
            .current_witness(owner)
            .map_err(CognitiveRecoveryError::AccessDenied)?
        {
            CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(anchor) if anchor == t.old_anchor => {
                host.retain_transition(t)
                    .map_err(CognitiveRecoveryError::AccessDenied)?
            }
            CognitiveSchemaUpgradeWitnessV1::RetainedTransition(retained) if retained == *t => {}
            _ => {
                return Err(CognitiveRecoveryError::AccessDenied(
                    "host upgrade witness changed or was revoked".into(),
                ));
            }
        }
        require_transition(host, t)?;
        let active = resolve_active_database_path(&self.root).map_err(indeterminate)?;
        let predecessor = active == self.root.join(&t.predecessor_database_filename);
        let (expected, schema) = if predecessor {
            (&t.old_anchor, profile::historical(&t.old_anchor)?)
        } else {
            (&t.new_anchor, profile::current()?)
        };
        // Even after retention, the active source must be exactly old or new.
        // An unrelated/advanced active DB is never overwritten by an old receipt.
        let active_image =
            image::copy_verified(&self.config, &self.root, &active, expected, &fence, &schema)
                .await?;
        let image = if predecessor {
            active_image.discard().await;
            image::copy_verified(
                &self.config,
                &self.root,
                &self.root.join(&t.prepared_database_filename),
                &t.new_anchor,
                &fence,
                &profile::current()?,
            )
            .await?
        } else {
            active_image
        };
        let image = image::seal_current(&self.config, &self.root, image, &t.new_anchor).await?;
        let admission = verify_authority(owner, authority, verifier)
            .and_then(|current| validate_transition(t, owner, &current))
            .and_then(|()| require_transition(host, t));
        if let Err(error) = admission {
            image.discard().await;
            return Err(error);
        }
        if let Err(error) = publish_active_database(&self.root, &image.path) {
            let path = image.close().await;
            return Err(reconcile_failed_recovery_candidate(
                &self.root,
                &path,
                indeterminate(error),
            ));
        }
        Ok(CognitiveStore {
            pool: image.pool,
            owner_agent_id: owner.clone(),
            path: image.path,
            _open_guard: self.open_guard.take(),
        })
    }
}

#[cfg(unix)]
fn acquire(
    layout: &HeptaAgentLayout,
) -> Result<(PathBuf, SqliteConfig, CognitiveStoreOpenGuard), CognitiveRecoveryError> {
    let root = canonical_path_without_redirection(layout.cognitive_root())
        .map_err(indeterminate)?
        .filter(|root| root == layout.cognitive_root())
        .ok_or_else(|| {
            CognitiveRecoveryError::Indeterminate(
                "schema upgrade root is absent or redirected".into(),
            )
        })?;
    let guard = CognitiveStoreOpenGuard::acquire_exclusive(&root).map_err(indeterminate)?;
    let home = AbsolutePathBuf::try_from(root.clone()).map_err(indeterminate)?;
    Ok((root, SqliteConfig::from_sqlite_home(home), guard))
}

#[cfg(not(unix))]
fn acquire(
    _layout: &HeptaAgentLayout,
) -> Result<(PathBuf, SqliteConfig, CognitiveStoreOpenGuard), CognitiveRecoveryError> {
    Err(CognitiveRecoveryError::Unavailable(
        "schema upgrade requires the qualified Unix descriptor-bound image and directory durability implementation".into(),
    ))
}

fn verify_authority<V: ProductionAuthorityVerifier + ?Sized>(
    owner: &AgentId,
    authority: &ProductionAuthorityLease,
    verifier: &V,
) -> Result<Sha256Digest, CognitiveRecoveryError> {
    verifier
        .verify(authority, owner)
        .map_err(CognitiveRecoveryError::AccessDenied)?;
    authority.validate_for_agent(owner).map_err(indeterminate)?;
    authority.fencing_token_digest().map_err(indeterminate)
}

fn require_old<H: CognitiveSchemaUpgradeHostV1 + ?Sized>(
    host: &H,
    old: &CognitiveRecoveryAnchor,
) -> Result<(), CognitiveRecoveryError> {
    if host
        .current_witness(&old.owner_agent_id)
        .map_err(CognitiveRecoveryError::AccessDenied)?
        != CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(old.clone())
    {
        return Err(CognitiveRecoveryError::AccessDenied(
            "old upgrade witness changed before migration/retention".into(),
        ));
    }
    Ok(())
}

fn require_transition<H: CognitiveSchemaUpgradeHostV1 + ?Sized>(
    host: &H,
    t: &CognitiveSchemaUpgradeTransitionV1,
) -> Result<(), CognitiveRecoveryError> {
    if host
        .current_witness(&t.old_anchor.owner_agent_id)
        .map_err(CognitiveRecoveryError::AccessDenied)?
        != CognitiveSchemaUpgradeWitnessV1::RetainedTransition(t.clone())
    {
        return Err(CognitiveRecoveryError::AccessDenied(
            "exact durable host transition acknowledgement is missing".into(),
        ));
    }
    Ok(())
}

fn validate_transition(
    t: &CognitiveSchemaUpgradeTransitionV1,
    owner: &AgentId,
    fence: &Sha256Digest,
) -> Result<(), CognitiveRecoveryError> {
    let source = profile::historical(&t.old_anchor)?;
    let target = profile::current()?;
    if t.profile != TRANSITION_PROFILE
        || t.old_anchor.owner_agent_id != *owner
        || t.new_anchor.owner_agent_id != *owner
        || t.new_anchor.profile != PROFILE
        || t.new_anchor.schema_digest.as_str() != target.oracle
        || t.source_version != source.version
        || t.target_version != target.version
        || t.migration_plan_digest != profile::plan_digest(&source, &target)?
        || t.authority_fence_digest != *fence
        || !valid_recovered_database_filename(&t.prepared_database_filename)
        || !(t.predecessor_database_filename == COGNITIVE_DB_FILENAME
            || valid_recovered_database_filename(&t.predecessor_database_filename))
        || t.prepared_database_filename == t.predecessor_database_filename
    {
        return Err(CognitiveRecoveryError::AccessDenied(
            "retained upgrade transition identity or compiled plan mismatch".into(),
        ));
    }
    Ok(())
}

fn filename(path: &std::path::Path) -> Result<String, CognitiveRecoveryError> {
    path.file_name()
        .and_then(|name| name.to_str())
        .map(str::to_string)
        .ok_or_else(|| {
            CognitiveRecoveryError::Indeterminate("upgrade database filename is invalid".into())
        })
}

#[cfg(all(test, unix))]
#[path = "cognitive_schema_upgrade_tests.rs"]
mod tests;
