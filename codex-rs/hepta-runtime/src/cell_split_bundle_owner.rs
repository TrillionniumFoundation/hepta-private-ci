//! Atomic bridge from a cell-split migration to one CAS owner per child.
//!
//! A parameter-bundle owner represents one linear cell lineage, so sibling
//! children cannot be appended to one owner. This bridge keeps one independent
//! owner per child, stages every append on clones, and publishes the complete
//! owner set only after every child state has prepared successfully.

use codex_hepta_control_plane::OrganMigrationError;
use codex_hepta_control_plane::OrganStateMigrationV1;
use codex_hepta_learning_artifacts::CellParameterBundleOwnerV1;
use codex_hepta_learning_artifacts::CellParameterBundlePublishRequestV1;
use codex_hepta_learning_artifacts::CellParameterBundleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::collections::BTreeMap;

use crate::CellSplitMigrationError;
use crate::CellSplitMigrationOwnerV1;

#[derive(Debug)]
pub struct CellSplitParameterBundleSetMigrationOwnerV1 {
    migration: CellSplitMigrationOwnerV1,
    owners: BTreeMap<String, CellParameterBundleOwnerV1>,
    candidates: BTreeMap<String, CellParameterBundleV1>,
    before_owners: Option<BTreeMap<String, CellParameterBundleOwnerV1>>,
}

impl CellSplitParameterBundleSetMigrationOwnerV1 {
    /// Bind one independently owned CAS lineage to each candidate child.
    /// Selection and activation remain outside this owner.
    pub fn new(
        migration: CellSplitMigrationOwnerV1,
        owners: BTreeMap<String, CellParameterBundleOwnerV1>,
        candidates: Vec<CellParameterBundleV1>,
    ) -> Result<Self, CellSplitMigrationError> {
        let expected: BTreeMap<_, _> = migration
            .plan()
            .children
            .iter()
            .map(|spec| (spec.child_id.clone(), ()))
            .collect();
        if owners.len() != expected.len() || owners.keys().any(|key| !expected.contains_key(key)) {
            return Err(CellSplitMigrationError::PartialChild {
                child_id: "parameter-bundle-owner-set".to_owned(),
            });
        }
        let mut by_child = BTreeMap::new();
        for bundle in candidates {
            bundle
                .validate()
                .map_err(|_| CellSplitMigrationError::InvalidState("parameter bundle candidate"))?;
            let child_id = bundle.identity.child_id.to_string();
            if !expected.contains_key(&child_id) || by_child.insert(child_id, bundle).is_some() {
                return Err(CellSplitMigrationError::PartialChild {
                    child_id: "parameter-bundle-identity".to_owned(),
                });
            }
        }
        if by_child.len() != expected.len()
            || owners.iter().any(|(child_id, owner)| {
                by_child
                    .get(child_id)
                    .is_none_or(|bundle| bundle.identity.scope_digest != owner.scope_digest())
            })
        {
            return Err(CellSplitMigrationError::PartialChild {
                child_id: "parameter-bundle-set".to_owned(),
            });
        }
        Ok(Self {
            migration,
            owners,
            candidates: by_child,
            before_owners: None,
        })
    }

    #[must_use]
    pub fn migration(&self) -> &CellSplitMigrationOwnerV1 {
        &self.migration
    }

    #[must_use]
    pub fn owners(&self) -> &BTreeMap<String, CellParameterBundleOwnerV1> {
        &self.owners
    }

    fn callback_error() -> OrganMigrationError {
        StableId::new("runtime.cell-split.parameter-bundle")
            .map_or(OrganMigrationError::Rejected, OrganMigrationError::Callback)
    }

    fn stage(
        &self,
    ) -> Result<BTreeMap<String, CellParameterBundleOwnerV1>, CellSplitMigrationError> {
        let mut staged = self.owners.clone();
        for (child_id, bundle) in &self.candidates {
            let owner =
                staged
                    .get_mut(child_id)
                    .ok_or_else(|| CellSplitMigrationError::PartialChild {
                        child_id: child_id.clone(),
                    })?;
            let expected_head_digest = owner.head_digest();
            let receipt = owner
                .publish(CellParameterBundlePublishRequestV1 {
                    operation_id: bundle.bundle_id.clone(),
                    expected_head_digest,
                    bundle: bundle.clone(),
                })
                .map_err(|_| CellSplitMigrationError::ParameterBundleReceiptMismatch)?;
            if receipt.bundle_id != bundle.bundle_id
                || receipt.bundle_digest != bundle.bundle_digest
                || receipt.authority.grants_any()
            {
                return Err(CellSplitMigrationError::ParameterBundleReceiptMismatch);
            }
        }
        Ok(staged)
    }
}

impl OrganStateMigrationV1 for CellSplitParameterBundleSetMigrationOwnerV1 {
    fn snapshot(
        &mut self,
        predecessor: codex_hepta_types::Generation,
    ) -> Result<Vec<u8>, OrganMigrationError> {
        let snapshot = self.migration.snapshot(predecessor)?;
        self.before_owners = Some(self.owners.clone());
        Ok(snapshot)
    }

    fn migrate(
        &mut self,
        snapshot: &[u8],
        predecessor: codex_hepta_types::Generation,
        candidate: codex_hepta_types::Generation,
    ) -> Result<(), OrganMigrationError> {
        self.migration.migrate(snapshot, predecessor, candidate)?;
        let staged = match self.stage() {
            Ok(staged) => staged,
            Err(_) => {
                self.owners = self.before_owners.clone().unwrap_or_default();
                return Err(Self::callback_error());
            }
        };
        self.owners = staged;
        Ok(())
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        predecessor: codex_hepta_types::Generation,
        candidate: codex_hepta_types::Generation,
    ) -> Result<(), OrganMigrationError> {
        self.migration.rollback(snapshot, predecessor, candidate)?;
        self.owners = self.before_owners.take().ok_or_else(Self::callback_error)?;
        Ok(())
    }
}

impl crate::RuntimeTopologyMigrationOwnerV1 for CellSplitParameterBundleSetMigrationOwnerV1 {
    fn handoff_plan_digest(&self) -> Digest32 {
        self.migration.handoff_plan_digest()
    }
}

#[cfg(test)]
#[path = "cell_split_bundle_owner_tests.rs"]
mod tests;
