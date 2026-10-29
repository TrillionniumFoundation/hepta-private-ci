//! Inventory writes retain canonical authorization, revision CAS and withdrawal transactions.

use codex_hepta_types::Digest32;
use crate::{CognitiveAccess, CognitiveScope, CognitiveStore, CognitiveStoreError, CognitiveWriteReceipt, ForgetMemoryDraft, KgFactSetDraft, LedgerSourceKind, MemoryDraft, MemoryLifecycleState, MemoryRevisionDraft, MemoryVerification, SourceDraft, StableMemoryId, MemoryCellWriteModeV1};
use crate::cognitive_store::unavailable;
use crate::memory_cell_owner::invalid;
use crate::memory_inventory_owner::{MemoryInventoryAddressV1, MemoryInventoryRecordV1, inventory_stable_key};

impl CognitiveStore {
    /// The host must authorize an explicit memory directive and derive access/
    /// scope from its authenticated principal. Model proposals cannot acquire
    /// verified status merely by supplying this typed payload.
    pub async fn write_memory_inventory(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        record: &MemoryInventoryRecordV1,
        mode: MemoryCellWriteModeV1,
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        self.authorize(access, scope)?;
        record.validate().map_err(invalid)?;
        let stable_key = inventory_stable_key(&record.address())?;
        let revision = match mode {
            MemoryCellWriteModeV1::Create => 1,
            MemoryCellWriteModeV1::Correct { expected_revision } => expected_revision
                .checked_add(1)
                .filter(|revision| *revision > 1)
                .ok_or_else(|| {
                    CognitiveStoreError::Invalid(
                        "memory revision overflow or zero predecessor".to_string(),
                    )
                })?,
        };
        let content = serde_json::to_string(record).map_err(unavailable)?;
        let source = SourceDraft {
            scope: scope.clone(),
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: format!("{stable_key}:revision:{revision}"),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: record.effective_at as i64,
        };
        let draft = MemoryRevisionDraft {
            scope: scope.clone(),
            content,
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: record.effective_at as i64,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        };
        let facts = KgFactSetDraft::default();
        match mode {
            MemoryCellWriteModeV1::Create => {
                self.remember_with_kg(
                    access,
                    &source,
                    &MemoryDraft {
                        stable_key,
                        revision: draft,
                    },
                    &facts,
                )
                .await
            }
            MemoryCellWriteModeV1::Correct { expected_revision } => {
                let id = StableMemoryId::for_key(self.owner_agent_id(), scope, &stable_key);
                self.correct_with_kg(access, &id, expected_revision, &source, &draft, &facts)
                    .await
            }
        }
    }

    /// Tombstones preserve the stable typed address through immutable ancestry;
    /// readers never silently fall back to an older value at that address.
    pub async fn forget_memory_inventory(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        address: &MemoryInventoryAddressV1,
        expected_revision: u64,
        reason: &str,
        now_unix_seconds: i64,
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        self.authorize(access, scope)?;
        if now_unix_seconds < 0
            || reason.trim().is_empty()
            || reason.len() > 256
            || reason.contains('\0')
        {
            return Err(CognitiveStoreError::Invalid(
                "memory withdrawal time or reason".to_string(),
            ));
        }
        let stable_key = inventory_stable_key(address)?;
        let id = StableMemoryId::for_key(self.owner_agent_id(), scope, &stable_key);
        let source = SourceDraft {
            scope: scope.clone(),
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: format!(
                "{stable_key}:withdraw:{expected_revision}:{}",
                Digest32::of_bytes(reason.as_bytes())
            ),
            content: reason.as_bytes().to_vec(),
            observed_at_unix_seconds: now_unix_seconds,
        };
        self.forget_with_kg(
            access,
            &id,
            expected_revision,
            &source,
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: reason.to_string(),
                valid_from_unix_seconds: now_unix_seconds,
                citations: Vec::new(),
            },
        )
        .await
    }
}
