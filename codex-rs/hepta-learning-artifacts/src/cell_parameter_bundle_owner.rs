//! CAS owner for immutable `CellParameterBundleV1` records.

use std::collections::BTreeMap;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::cell_parameter_bundle::{
    CellBundlePredecessorV1, CellComponentModeV1, CellComponentRefV1,
    CellParameterBundleAppendDispositionV1, CellParameterBundleErrorV1,
    CellParameterBundlePublishRequestV1, CellParameterBundleReceiptV1, CellParameterBundleV1,
    digest_head,
};

const MAX_BUNDLES: usize = 4_096;

/// The artifact owner for immutable cell bundles.  Every mutation is a CAS
/// against the current head; exact operation replay is idempotent.
#[derive(Clone, Debug)]
pub struct CellParameterBundleOwnerV1 {
    scope_digest: Digest32,
    head_digest: Digest32,
    records: Vec<CellParameterBundleV1>,
    by_id: BTreeMap<StableId, usize>,
    receipts: BTreeMap<StableId, CellParameterBundleReceiptV1>,
}

impl CellParameterBundleOwnerV1 {
    pub fn new(scope_digest: Digest32) -> Result<Self, CellParameterBundleErrorV1> {
        if scope_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyScope);
        }
        Ok(Self {
            scope_digest,
            head_digest: Digest32::ZERO,
            records: Vec::new(),
            by_id: BTreeMap::new(),
            receipts: BTreeMap::new(),
        })
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub fn records(&self) -> &[CellParameterBundleV1] {
        &self.records
    }

    #[must_use]
    pub fn current(&self) -> Option<&CellParameterBundleV1> {
        self.records.last()
    }

    pub fn append(
        &mut self,
        expected_head_digest: Digest32,
        bundle: CellParameterBundleV1,
    ) -> Result<CellParameterBundleReceiptV1, CellParameterBundleErrorV1> {
        self.publish(CellParameterBundlePublishRequestV1 {
            operation_id: bundle.bundle_id.clone(),
            expected_head_digest,
            bundle,
        })
    }

    pub fn publish(
        &mut self,
        request: CellParameterBundlePublishRequestV1,
    ) -> Result<CellParameterBundleReceiptV1, CellParameterBundleErrorV1> {
        request.bundle.validate()?;
        if request.bundle.identity.scope_digest != self.scope_digest {
            return Err(CellParameterBundleErrorV1::ScopeMismatch);
        }
        if let Some(existing) = self.receipts.get(&request.operation_id) {
            let matching = existing.bundle_id == request.bundle.bundle_id
                && existing.bundle_digest == request.bundle.bundle_digest
                && existing.predecessor_head_digest == request.expected_head_digest;
            if !matching {
                return Err(CellParameterBundleErrorV1::IdentityConflict(
                    request.operation_id.to_string(),
                ));
            }
            return Ok(CellParameterBundleReceiptV1 {
                disposition: CellParameterBundleAppendDispositionV1::IdempotentReplay,
                ..existing.clone()
            });
        }
        if request.expected_head_digest != self.head_digest {
            return Err(CellParameterBundleErrorV1::CasConflict);
        }
        if self.by_id.contains_key(&request.bundle.bundle_id) {
            return Err(CellParameterBundleErrorV1::IdentityConflict(
                request.bundle.bundle_id.to_string(),
            ));
        }
        self.validate_successor(&request.bundle)?;
        if self.records.len() >= MAX_BUNDLES {
            return Err(CellParameterBundleErrorV1::Capacity);
        }
        let sequence = u64::try_from(self.records.len())
            .map_err(|_| CellParameterBundleErrorV1::Arithmetic)?
            .checked_add(1)
            .ok_or(CellParameterBundleErrorV1::Arithmetic)?;
        let predecessor_head_digest = self.head_digest;
        let head_digest = digest_head(
            predecessor_head_digest,
            sequence,
            request.bundle.bundle_digest,
        );
        let receipt = CellParameterBundleReceiptV1 {
            disposition: CellParameterBundleAppendDispositionV1::Appended,
            operation_id: request.operation_id.clone(),
            sequence,
            bundle_id: request.bundle.bundle_id.clone(),
            bundle_digest: request.bundle.bundle_digest,
            predecessor_head_digest,
            head_digest,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.by_id
            .insert(request.bundle.bundle_id.clone(), self.records.len());
        self.records.push(request.bundle);
        self.head_digest = head_digest;
        self.receipts.insert(request.operation_id, receipt.clone());
        Ok(receipt)
    }

    /// Reconcile an operation after an acknowledgement loss.  The receipt is
    /// accepted only if every immutable field matches the owner journal.
    pub fn replay_receipt(
        &self,
        receipt: &CellParameterBundleReceiptV1,
    ) -> Result<CellParameterBundleReceiptV1, CellParameterBundleErrorV1> {
        let stored = self
            .receipts
            .get(&receipt.operation_id)
            .ok_or(CellParameterBundleErrorV1::ReceiptMismatch)?;
        if stored.operation_id != receipt.operation_id
            || stored.disposition != receipt.disposition
            || stored.sequence != receipt.sequence
            || stored.bundle_id != receipt.bundle_id
            || stored.bundle_digest != receipt.bundle_digest
            || stored.predecessor_head_digest != receipt.predecessor_head_digest
            || stored.head_digest != receipt.head_digest
            || stored.authority != receipt.authority
        {
            return Err(CellParameterBundleErrorV1::ReceiptMismatch);
        }
        Ok(CellParameterBundleReceiptV1 {
            disposition: CellParameterBundleAppendDispositionV1::IdempotentReplay,
            ..stored.clone()
        })
    }

    /// Create a fresh successor that restores an old immutable bundle.  The
    /// old record is never resurrected as the current CAS head.
    pub fn rollback_to_old_bundle(
        &mut self,
        expected_head_digest: Digest32,
        target_bundle_id: &StableId,
        operation_id: StableId,
    ) -> Result<CellParameterBundleReceiptV1, CellParameterBundleErrorV1> {
        if expected_head_digest != self.head_digest {
            return Err(CellParameterBundleErrorV1::CasConflict);
        }
        let target = self
            .by_id
            .get(target_bundle_id)
            .and_then(|index| self.records.get(*index))
            .ok_or_else(|| {
                CellParameterBundleErrorV1::RollbackTargetNotFound(target_bundle_id.to_string())
            })?
            .clone();
        let current = self
            .current()
            .ok_or(CellParameterBundleErrorV1::RollbackConflict)?;
        if current.bundle_id == target.bundle_id {
            return Err(CellParameterBundleErrorV1::RollbackConflict);
        }
        let generation = current
            .identity
            .generation
            .next()
            .map_err(|_| CellParameterBundleErrorV1::Arithmetic)?;
        let parent = predecessor_of(current);
        let mut bundle = target.clone();
        bundle.bundle_id = operation_id.clone();
        bundle.identity.child_id = operation_id.clone();
        bundle.identity.generation = generation;
        bundle.identity.lineage_digest = Digest32::ZERO;
        bundle.parent_predecessor = Some(parent);
        bundle.rollback_target = Some(CellBundlePredecessorV1 {
            bundle_id: target.bundle_id.clone(),
            bundle_digest: target.bundle_digest,
            generation: target.identity.generation,
            lineage_digest: target.identity.lineage_digest,
        });
        for component in [&mut bundle.adapter, &mut bundle.head] {
            component.mode = CellComponentModeV1::Cloned;
            component.source_artifact_digest = Some(component.artifact.content_digest);
        }
        bundle.seal()?;
        self.publish(CellParameterBundlePublishRequestV1 {
            operation_id,
            expected_head_digest,
            bundle,
        })
    }

    fn validate_successor(
        &self,
        bundle: &CellParameterBundleV1,
    ) -> Result<(), CellParameterBundleErrorV1> {
        if let Some(target) = bundle.rollback_target.as_ref() {
            let stored = self
                .by_id
                .get(&target.bundle_id)
                .and_then(|index| self.records.get(*index))
                .ok_or_else(|| {
                    CellParameterBundleErrorV1::RollbackTargetNotFound(target.bundle_id.to_string())
                })?;
            if stored.bundle_digest != target.bundle_digest
                || stored.identity.generation != target.generation
                || stored.identity.lineage_digest != target.lineage_digest
            {
                return Err(CellParameterBundleErrorV1::RollbackConflict);
            }
        }
        match (self.current(), bundle.parent_predecessor.as_ref()) {
            (None, None) if bundle.identity.generation.get() == 1 => {}
            (None, None) => return Err(CellParameterBundleErrorV1::MissingPredecessor),
            (Some(current), Some(parent)) => {
                if !self.by_id.contains_key(&parent.bundle_id) {
                    return Err(CellParameterBundleErrorV1::PredecessorNotFound(
                        parent.bundle_id.to_string(),
                    ));
                }
                if parent.bundle_id != current.bundle_id
                    || parent.bundle_digest != current.bundle_digest
                    || parent.generation != current.identity.generation
                    || parent.lineage_digest != current.identity.lineage_digest
                {
                    return Err(CellParameterBundleErrorV1::PredecessorMismatch);
                }
                if bundle.identity.cell_id != current.identity.cell_id {
                    return Err(CellParameterBundleErrorV1::IdentityConflict(
                        bundle.identity.cell_id.to_string(),
                    ));
                }
                if bundle.shared_base != current.shared_base {
                    return Err(CellParameterBundleErrorV1::MalformedInheritance(
                        "shared base replacement requires a separate qualified contract",
                    ));
                }
                let source = bundle.rollback_target.as_ref().and_then(|target| {
                    self.by_id
                        .get(&target.bundle_id)
                        .and_then(|index| self.records.get(*index))
                });
                let inheritance_parent = source.unwrap_or(current);
                validate_component_inheritance(&bundle.adapter, &inheritance_parent.adapter)?;
                validate_component_inheritance(&bundle.head, &inheritance_parent.head)?;
            }
            (None, Some(_)) | (Some(_), None) => {
                return Err(CellParameterBundleErrorV1::MissingPredecessor);
            }
        }
        Ok(())
    }
}

fn validate_component_inheritance(
    child: &CellComponentRefV1,
    parent: &CellComponentRefV1,
) -> Result<(), CellParameterBundleErrorV1> {
    match child.mode {
        CellComponentModeV1::Cloned => {
            if child.source_artifact_digest != Some(parent.artifact.content_digest)
                || child.artifact.content_digest != parent.artifact.content_digest
            {
                return Err(CellParameterBundleErrorV1::MalformedInheritance(
                    "cloned component is not inherited from the predecessor",
                ));
            }
        }
        CellComponentModeV1::Reinitialized => {
            if child.source_artifact_digest.is_some()
                || child.artifact.content_digest == parent.artifact.content_digest
            {
                return Err(CellParameterBundleErrorV1::MalformedInheritance(
                    "reinitialized component must be fresh",
                ));
            }
        }
    }
    Ok(())
}

fn predecessor_of(bundle: &CellParameterBundleV1) -> CellBundlePredecessorV1 {
    CellBundlePredecessorV1 {
        bundle_id: bundle.bundle_id.clone(),
        bundle_digest: bundle.bundle_digest,
        generation: bundle.identity.generation,
        lineage_digest: bundle.identity.lineage_digest,
    }
}
