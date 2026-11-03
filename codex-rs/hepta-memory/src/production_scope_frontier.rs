//! A bounded observation of the original writer's complete execution scope.
//! It retains the original lifetime fence and grants no effect, retry, or lease.

use std::sync::Arc;
use super::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionScopeClaimState { Claimed, Renewed, Entered, Settled }

/// Read-only original claim evidence. Only the owning ledger reader builds it.
#[derive(Debug)]
pub struct ProductionScopeClaim {
    receipt: DurableDispatchClaim,
    state: ProductionScopeClaimState,
}
impl ProductionScopeClaim {
    pub fn receipt(&self) -> &DurableDispatchClaim { &self.receipt }
    pub fn state(&self) -> ProductionScopeClaimState { self.state }
}

/// The original immutable intent/outbox pair, complete claim chain, and outcome.
/// A terminal event and a Settled claim are separate facts; a crash may separate them.
#[derive(Debug)]
pub struct ProductionScopeOperation {
    request: ProductionDispatchRequest,
    state: LocalOutcomeState,
    generation: u64,
    admission_event_id: String,
    outbox_id: String,
    terminal_event_id: Option<String>,
    terminal_receipt: Option<String>,
    terminal_generation: Option<u64>,
    claims: Vec<ProductionScopeClaim>,
}
impl ProductionScopeOperation {
    pub fn request(&self) -> &ProductionDispatchRequest { &self.request }
    pub fn state(&self) -> LocalOutcomeState { self.state }
    pub fn generation(&self) -> u64 { self.generation }
    pub fn admission_event_id(&self) -> &str { &self.admission_event_id }
    pub fn outbox_id(&self) -> &str { &self.outbox_id }
    pub fn terminal_event_id(&self) -> Option<&str> { self.terminal_event_id.as_deref() }
    pub fn terminal_receipt(&self) -> Option<&str> { self.terminal_receipt.as_deref() }
    pub fn terminal_generation(&self) -> Option<u64> { self.terminal_generation }
    pub fn claims(&self) -> &[ProductionScopeClaim] { &self.claims }
}

/// Not Clone, Deserialize, or publicly constructible. This is an owner-bound
/// read witness, never a replacement FinalUse authority. Release it before
/// checkpoint/currentness or any API which reacquires the writer's read lease.
#[must_use = "retain the original writer frontier until the owner consumes its observation"]
pub struct ProductionScopeFrontier {
    owner_agent_id: AgentId,
    lease_id: String,
    scope_sha256: Sha256Digest,
    generation: u64,
    fencing_token: String,
    lifecycle: Arc<writer_lifecycle::WriterLifecycle>,
    records: Vec<ProductionScopeOperation>,
    _fence: writer_lifecycle::ProductionPreparationFence,
}
impl ProductionScopeFrontier {
    pub fn records(&self) -> &[ProductionScopeOperation] { &self.records }
    pub fn verify_binding(&self, writer: &ProductionDurableWriter, scope: &Sha256Digest)
        -> Result<(), ProductionWriterError> {
        if &self.owner_agent_id != writer.owner_agent_id() || self.lease_id != writer.lease_id()
            || &self.scope_sha256 != scope || self.generation != writer.generation()
            || self.fencing_token != writer.lease.fencing_token()
            || !Arc::ptr_eq(&self.lifecycle, &writer.lifecycle) {
            return Err(ProductionWriterError::StaleReceipt);
        }
        drop(writer.lifecycle.lock_open()?);
        writer.authority.validate_for_agent(writer.owner_agent_id())?;
        writer.live_verifier.as_ref().ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&writer.authority, writer.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)
    }
}

impl ProductionDurableWriter {
    /// Enumerate every immutable operation in this lease/scope, without a
    /// generation filter, then reject any old-generation material. Read bounds
    /// are 4096 operations, 32768 event/claim rows, and 64 MiB of source fields.
    /// These limits are observation bounds, not new model/context budgets.
    /// The fence excludes new operation admission. Legacy observation helpers
    /// may still advance nonterminal claims/outcomes, so those are snapshots.
    /// A continuation consumer must require both an immutable terminal event
    /// and its original Settled claim; neither alone authorizes new work.
    pub async fn observe_scope_frontier(&self, scope: &Sha256Digest)
        -> Result<ProductionScopeFrontier, ProductionWriterError> {
        let fence = self.acquire_preparation_fence().await?;
        let original = self.lease.observe_scope(scope).await?;
        let mut records = Vec::with_capacity(original.len());
        for row in original {
            if row.generation != self.generation() || row.fencing_token != self.lease.fencing_token()
                || row.terminal_generation.is_some_and(|generation| generation != self.generation())
                || row.claims.iter().any(|claim| claim.receipt.owner_generation != self.generation()
                    || claim.receipt.fencing_token != self.lease.fencing_token()) {
                return Err(ProductionWriterError::StaleReceipt);
            }
            let operation_digest = dispatch_operation_digest(&self.authority.grant_digest,
                self.lease_id(), &row.operation_id, &row.topic, &row.payload_sha256,
                &row.semantic_sha256, row.expected_predecessor_sha256.as_ref());
            let request = ProductionDispatchRequest {
                schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
                namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_owned(),
                lease_id: self.lease_id().to_owned(), occurrence_key: row.operation_id.clone(),
                idempotency_key: row.operation_id, topic: row.topic, payload_json: row.payload_json,
                payload_sha256: row.payload_sha256, operation_scope_sha256: scope.clone(),
                operation_subject_id: row.subject_id, operation_destination_id: row.destination_id,
                operation_semantic_sha256: row.semantic_sha256,
                operation_policy_generation: row.policy_generation,
                expected_predecessor_sha256: row.expected_predecessor_sha256, operation_digest,
            };
            let claims = row.claims.into_iter().map(|claim| {
                let state = match claim.state {
                    "claimed" => ProductionScopeClaimState::Claimed,
                    "renewed" => ProductionScopeClaimState::Renewed,
                    "entered" => ProductionScopeClaimState::Entered,
                    "settled" => ProductionScopeClaimState::Settled,
                    _ => return Err(ProductionWriterError::StaleReceipt),
                };
                Ok(ProductionScopeClaim { receipt: claim.receipt, state })
            }).collect::<Result<Vec<_>, ProductionWriterError>>()?;
            records.push(ProductionScopeOperation {
                request, state: row.state, generation: row.generation,
                admission_event_id: row.admission_event_id, outbox_id: row.outbox_id,
                terminal_event_id: row.terminal_event_id, terminal_receipt: row.terminal_receipt,
                terminal_generation: row.terminal_generation, claims,
            });
        }
        let result = ProductionScopeFrontier {
            owner_agent_id: self.owner_agent_id().clone(), lease_id: self.lease_id().to_owned(),
            scope_sha256: scope.clone(), generation: self.generation(),
            fencing_token: self.lease.fencing_token().to_owned(), lifecycle: Arc::clone(&self.lifecycle),
            records, _fence: fence,
        };
        result.verify_binding(self, scope)?;
        Ok(result)
    }
}
