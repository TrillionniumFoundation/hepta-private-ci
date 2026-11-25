//! Private ownership of the actual fresh journal result. No serialized
//! observation can reconstruct this value or supply its original human source.
use super::*;
use codex_hepta_memory::ProductionQueuedReceipt;

pub(crate) enum PreparedOriginal<T> {
    Fresh {
        observation: PairedPreparationObservation,
        continuation: T,
    },
    Retained(PairedPreparationObservation),
}

#[cfg(test)]
impl<T> PreparedOriginal<T> {
    pub(crate) fn into_observation(self) -> PairedPreparationResponse {
        match self {
            Self::Fresh {
                observation,
                continuation,
            } => {
                // The public A response deliberately drops the actual receipt.
                // A response, restart or later lookup cannot recover this owner.
                drop(continuation);
                PairedPreparationResponse::FreshPrepared(observation)
            }
            Self::Retained(observation) => PairedPreparationResponse::RetainedReadOnly(observation),
        }
    }
}

pub(super) struct FreshJournalPreparation {
    writer: Arc<ProductionDurableWriter>,
    receipt: ProductionQueuedReceipt,
    request: PairedPreparationRequest,
}

impl FreshJournalPreparation {
    pub(super) fn from_original_commit(
        writer: Arc<ProductionDurableWriter>,
        receipt: ProductionQueuedReceipt,
        request: PairedPreparationRequest,
    ) -> Result<Self, AgentdError> {
        if receipt.replayed
            || receipt.inherited_from_generation.is_some()
            || receipt.external_effect
            || receipt.owner_agent_id != *writer.owner_agent_id()
            || receipt.topic != TOPIC
        {
            return Err(invalid(
                "paired continuation requires this fresh original commit",
            ));
        }
        Ok(Self {
            writer,
            receipt,
            request,
        })
    }

    pub(super) fn bind_original(
        self,
        verified: &VerifiedPairedTurn,
    ) -> Result<OriginalPairedContinuation<'_>, AgentdError> {
        verified.original_ingress()?;
        if verified.request() != &self.request.original
            || verified.route().agent_id != *self.writer.owner_agent_id()
        {
            return Err(invalid("fresh receipt and original paired source differ"));
        }
        Ok(OriginalPairedContinuation {
            prepared: self,
            verified,
        })
    }
}

/// Borrowed original provenance plus the one actual transaction result. The
/// verified source remains in its required runtime; this type is neither Clone
/// nor serializable and has no public constructor or receipt accessor.
pub(crate) struct OriginalPairedContinuation<'a> {
    prepared: FreshJournalPreparation,
    verified: &'a VerifiedPairedTurn,
}

impl OriginalPairedContinuation<'_> {
    /// Consume the private result for the existing preparation-only API. The
    /// actual receipt is checked and discarded here; returning its observation
    /// cannot arm a later consumer or recreate the private continuation.
    pub(super) fn finish_read_only(self) -> Result<(), AgentdError> {
        self.verified.original_ingress()?;
        let payload: PreparationPayload =
            serde_json::from_str(&self.prepared.receipt.payload_json)?;
        if self.prepared.request.original != *self.verified.request()
            || payload.original_route != *self.verified.route()
            || payload.permission_revision != self.verified.permission_revision()
            || payload.expires_at_ms != self.verified.expires_at_ms()
            || payload.statement_sha256 != self.verified.statement_sha256().to_string()
        {
            return Err(invalid(
                "fresh original receipt lost its verified source binding",
            ));
        }
        Ok(())
    }
}
