//! Explicitly stop the original publication writer before HEAD signing.
//!
//! The evidence can be reread, but only the fresh call returns a single-use
//! continuation tied to this service instance. Readback and cold opening never
//! recreate that continuation or complete an interrupted publication.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::LearningArtifactOwnerService;
use crate::ArtifactOwnerHostError;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::LearningArtifactOwnerHost;
use crate::OriginalArtifactRegistryDurableV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

/// An exact-operation expectation, not evidence or signing authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalArtifactPublicationContextV1 {
    pub operation_id: StableId,
    pub admission: WithdrawalBoundArtifactAdmissionV3,
    pub expected_registry_predecessor_head: Digest32,
}

/// The sole fresh continuation. It cannot be cloned, decoded, recovered from
/// evidence, or moved to a reopened writer with the same lease.
#[derive(Debug)]
pub struct OriginalArtifactPreparedPublicationV1 {
    original_instance: Arc<()>,
    context: OriginalArtifactPublicationContextV1,
    transaction: ArtifactPublicationTransactionV1,
    staged: ArtifactRegistry,
    observed: OriginalArtifactRegistryDurableV1,
}

impl OriginalArtifactPreparedPublicationV1 {
    pub fn registry_durable(&self) -> &OriginalArtifactRegistryDurableV1 {
        &self.observed
    }
}

#[derive(Debug)]
pub enum OriginalArtifactPreparationErrorV1 {
    Owner(ArtifactOwnerHostError),
    Publication(ArtifactPublicationError),
    ReadbackRequired,
    NoCheckpoint,
    Pending(ArtifactPublicationPhaseV1),
    Context,
    ChangedDuringRead,
    Fenced,
    Clock,
}

impl fmt::Display for OriginalArtifactPreparationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OriginalArtifactPreparationErrorV1 {}

impl From<ArtifactOwnerHostError> for OriginalArtifactPreparationErrorV1 {
    fn from(value: ArtifactOwnerHostError) -> Self {
        Self::Owner(value)
    }
}

impl From<ArtifactPublicationError> for OriginalArtifactPreparationErrorV1 {
    fn from(value: ArtifactPublicationError) -> Self {
        Self::Publication(value)
    }
}

impl LearningArtifactOwnerService {
    /// The explicit write entrance. Persist one fresh original operation only
    /// through RegistryDurable, leaving HEAD signing to its independent owner.
    pub fn prepare_original_registry(
        &mut self,
        context: OriginalArtifactPublicationContextV1,
        payload: &[u8],
    ) -> Result<OriginalArtifactPreparedPublicationV1, OriginalArtifactPreparationErrorV1> {
        self.prepare_original_registry_with_clock(context, payload, &now_unix_millis)
    }

    /// Observe original bytes without beginning, resuming, repairing or
    /// acknowledging a publication. Pending is not permission to write again.
    pub fn read_original_registry_durable(
        &self,
        context: &OriginalArtifactPublicationContextV1,
    ) -> Result<OriginalArtifactRegistryDurableV1, OriginalArtifactPreparationErrorV1> {
        self.read_original_registry_durable_with_clock(context, &now_unix_millis)
    }

    /// Consume the one fresh continuation and the original complete HEAD
    /// signature. Loss or any failure consumes the continuation permanently.
    pub fn finish_original_registry(
        &mut self,
        prepared: OriginalArtifactPreparedPublicationV1,
        signed: SignedCurrentArtifactHeadV1,
    ) -> Result<ArtifactPublicationReceiptV1, OriginalArtifactPreparationErrorV1> {
        self.finish_original_registry_with_clock(prepared, signed, &now_unix_millis)
    }

    fn prepare_original_registry_with_clock(
        &mut self,
        context: OriginalArtifactPublicationContextV1,
        payload: &[u8],
        clock: &impl Fn() -> Result<u64, OriginalArtifactPreparationErrorV1>,
    ) -> Result<OriginalArtifactPreparedPublicationV1, OriginalArtifactPreparationErrorV1> {
        if self.original_preparation_fenced.load(Ordering::Acquire) {
            return Err(OriginalArtifactPreparationErrorV1::Fenced);
        }
        if self.recovery_required.is_some()
            || self
                .host
                .read_original_publication_checkpoint(&context.operation_id)?
                .is_some()
        {
            return Err(OriginalArtifactPreparationErrorV1::ReadbackRequired);
        }
        let started = clock()?;
        let predecessor = LearningArtifactOwnerHost::read_original_registry_predecessor(
            &self.host,
            context.expected_registry_predecessor_head,
            self.storage_binding,
            started,
        )?;
        let manifest = &context.admission.validated_manifest.manifest;
        if manifest.producer_id != *self.host.producer_id()
            || manifest.bytes_digest != Digest32::of_bytes(payload)
            || manifest.encoded_size_bytes != payload.len() as u64
        {
            return Err(OriginalArtifactPreparationErrorV1::Context);
        }
        // Complete validation before consuming the original writer entrance.
        ArtifactPublicationTransactionV1::begin_original_registry(
            context.operation_id.clone(),
            context.admission.clone(),
            &self.withdrawal_registry,
            &predecessor,
            context.expected_registry_predecessor_head,
            fresh(clock, started)?,
        )?;
        self.recovery_required = Some(context.operation_id.clone());
        self.original_preparation_active = true;
        let mut transaction = LearningArtifactOwnerHost::begin_original_registry_publication(
            &self.host,
            context.operation_id.clone(),
            context.admission.clone(),
            &self.withdrawal_registry,
            &predecessor,
            context.expected_registry_predecessor_head,
            fresh(clock, started)?,
        )?;
        let mut staged = predecessor;
        self.host.stage_compatibility_registration(
            &transaction,
            &mut staged,
            fresh(clock, started)?,
        )?;
        self.host.ensure_payload_durable(
            &mut transaction,
            &staged,
            payload,
            fresh(clock, started)?,
        )?;
        self.host.ensure_registry_durable(
            &mut transaction,
            &staged,
            &self.withdrawal_registry,
            self.storage_binding,
            fresh(clock, started)?,
        )?;
        let observed = self.read_original_registry_durable_with_clock(&context, clock)?;
        if observed.checkpoint().phase != ArtifactPublicationPhaseV1::RegistryDurable
            || observed.checkpoint().state_digest != transaction.state_digest()
            || observed.observed_unix_millis() < started
        {
            self.original_preparation_fenced
                .store(true, Ordering::Release);
            return Err(OriginalArtifactPreparationErrorV1::ChangedDuringRead);
        }
        Ok(OriginalArtifactPreparedPublicationV1 {
            original_instance: Arc::clone(&self.original_preparation_instance),
            context,
            transaction,
            staged,
            observed,
        })
    }

    fn read_original_registry_durable_with_clock(
        &self,
        context: &OriginalArtifactPublicationContextV1,
        clock: &impl Fn() -> Result<u64, OriginalArtifactPreparationErrorV1>,
    ) -> Result<OriginalArtifactRegistryDurableV1, OriginalArtifactPreparationErrorV1> {
        if self.original_preparation_fenced.load(Ordering::Acquire) {
            return Err(OriginalArtifactPreparationErrorV1::Fenced);
        }
        let result = LearningArtifactOwnerHost::read_original_registry_durable(
            &self.host,
            context,
            &self.withdrawal_registry,
            self.storage_binding,
            clock,
        );
        if matches!(
            &result,
            Err(OriginalArtifactPreparationErrorV1::Owner(_)
                | OriginalArtifactPreparationErrorV1::Publication(_)
                | OriginalArtifactPreparationErrorV1::ChangedDuringRead
                | OriginalArtifactPreparationErrorV1::Clock)
        ) {
            self.original_preparation_fenced
                .store(true, Ordering::Release);
        }
        result
    }

    fn finish_original_registry_with_clock(
        &mut self,
        mut prepared: OriginalArtifactPreparedPublicationV1,
        signed: SignedCurrentArtifactHeadV1,
        clock: &impl Fn() -> Result<u64, OriginalArtifactPreparationErrorV1>,
    ) -> Result<ArtifactPublicationReceiptV1, OriginalArtifactPreparationErrorV1> {
        if !Arc::ptr_eq(
            &prepared.original_instance,
            &self.original_preparation_instance,
        ) || self.recovery_required.as_ref() != Some(&prepared.context.operation_id)
        {
            return Err(OriginalArtifactPreparationErrorV1::ReadbackRequired);
        }
        let before = self.read_original_registry_durable_with_clock(&prepared.context, clock)?;
        if before.observed_unix_millis() < prepared.observed.observed_unix_millis() {
            self.original_preparation_fenced
                .store(true, Ordering::Release);
            return Err(OriginalArtifactPreparationErrorV1::Clock);
        }
        if !before.same_original_read(&prepared.observed)
            || before.checkpoint().phase != ArtifactPublicationPhaseV1::RegistryDurable
            || signed.binding != self.storage_binding
            || signed.witness.head_digest != before.registry_receipt().head_digest
            || signed.witness.predecessor_head_digest
                != prepared.context.expected_registry_predecessor_head
            || signed.withdrawal_scope_digest != prepared.context.admission.withdrawal_scope_digest
        {
            return Err(OriginalArtifactPreparationErrorV1::Context);
        }
        let started = before.observed_unix_millis();
        self.host.ensure_witness_durable(
            &mut prepared.transaction,
            &signed,
            &self.withdrawal_registry,
            fresh(clock, started)?,
        )?;
        let receipt = self.host.acknowledge(
            &mut prepared.transaction,
            &self.withdrawal_registry,
            fresh(clock, started)?,
        )?;
        let after = self.read_original_registry_durable_with_clock(&prepared.context, clock)?;
        if after.checkpoint().phase != ArtifactPublicationPhaseV1::Acknowledged
            || after.checkpoint().state_digest != receipt.state_digest
            || after.current_head() != Some(&signed)
            || after.observed_unix_millis() < started
        {
            self.original_preparation_fenced
                .store(true, Ordering::Release);
            return Err(OriginalArtifactPreparationErrorV1::ChangedDuringRead);
        }
        self.registry = prepared.staged;
        self.recovery_required = None;
        self.original_preparation_active = false;
        Ok(receipt)
    }
}

fn fresh(
    clock: &impl Fn() -> Result<u64, OriginalArtifactPreparationErrorV1>,
    started: u64,
) -> Result<u64, OriginalArtifactPreparationErrorV1> {
    let current = clock()?;
    if current < started {
        return Err(OriginalArtifactPreparationErrorV1::Clock);
    }
    Ok(current)
}

fn now_unix_millis() -> Result<u64, OriginalArtifactPreparationErrorV1> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OriginalArtifactPreparationErrorV1::Clock)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| OriginalArtifactPreparationErrorV1::Clock)
}

#[cfg(test)]
#[path = "owner_service_preparation_tests.rs"]
mod tests;
