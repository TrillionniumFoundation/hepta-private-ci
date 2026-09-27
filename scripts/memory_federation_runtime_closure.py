#!/usr/bin/env python3
"""Apply the memory.federation product-runtime closure."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement, found {text.count(old)}")
    return text.replace(old, new, 1)


def reset_from_main(paths: list[str]) -> None:
    run("git", "checkout", "origin/main", "--", *paths)


def patch_memory_cargo() -> None:
    path = "codex-rs/hepta-memory/Cargo.toml"
    text = read(path)
    text = replace_once(
        text,
        "futures = { workspace = true, features = [\"std\"] }\nserde =",
        "futures = { workspace = true, features = [\"std\"] }\nrand = { workspace = true }\nserde =",
        "memory rand dependency",
    )
    text = replace_once(
        text,
        "tokio = { workspace = true, features = [\"time\"] }",
        "tokio = { workspace = true, features = [\"macros\", \"rt\", \"sync\", \"time\"] }\ntokio-util = { workspace = true, features = [\"rt\"] }",
        "memory cancellation dependencies",
    )
    write(path, text)


def patch_extension_cargo() -> None:
    path = "codex-rs/ext/hepta-memory/Cargo.toml"
    text = read(path)
    text = replace_once(
        text,
        "tokio = { workspace = true, features = [\"time\"] }",
        "tokio = { workspace = true, features = [\"time\"] }\ntokio-util = { workspace = true, features = [\"rt\"] }",
        "extension cancellation dependency",
    )
    write(path, text)


def patch_revalidation_drift() -> None:
    path = "codex-rs/hepta-memory/src/cognitive_federation.rs"
    text = read(path)
    text = replace_once(
        text,
        "    CapabilityMissing,\n    CapabilityRevision,",
        "    CapabilityMissing,\n    OwnerUnavailable,\n    CapabilityRevision,",
        "owner unavailable drift",
    )
    write(path, text)


def telemetry_source() -> str:
    return r'''use super::*;

pub const MAX_FEDERATION_DIAGNOSTICS_V2: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FederationProductPhaseV2 {
    Discovery,
    QueryBuild,
    PreflightAuthority,
    Transport,
    PostIoAuthority,
    Integrity,
    Aggregation,
    FinalUse,
    Cancellation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FederationProductDispositionV2 {
    Partial,
    Failed,
    Cancelled,
    Truncated,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FederationProductFailureV2 {
    DiscoveryUnavailable,
    QueryBuildRejected,
    DeadlineOrCancelled,
    AuthorityRejected,
    IntegrityRejected,
    TransportUnavailable,
    FinalUseUnavailable,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedPeerDiagnosticV2 {
    pub peer_digest: String,
    pub phase: FederationProductPhaseV2,
    pub disposition: FederationProductDispositionV2,
    pub failure: Option<FederationProductFailureV2>,
    pub cancellation_receipt_digest: Option<String>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct FederatedDiagnosticLedgerV2 {
    pub entries: Vec<FederatedPeerDiagnosticV2>,
    pub omitted_entries: u32,
}

impl FederatedDiagnosticLedgerV2 {
    pub(super) fn push(&mut self, entry: FederatedPeerDiagnosticV2) {
        if self.entries.len() < MAX_FEDERATION_DIAGNOSTICS_V2 {
            self.entries.push(entry);
        } else {
            self.omitted_entries = self.omitted_entries.saturating_add(1);
        }
    }

    pub fn binding_sha256(&self) -> Result<Sha256Digest, CognitiveStoreError> {
        let bytes = serde_json::to_vec(self).map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "memory federation diagnostics cannot be encoded: {error}"
            ))
        })?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FederationCancellationEvidenceV2 {
    pub receipts: Vec<FederationCancellationReceiptV2>,
    pub omitted_receipts: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedProductReadV2 {
    pub batch: FederatedRetrievalBatch,
    pub coverage: FederatedCoverageV2,
    pub diagnostics: FederatedDiagnosticLedgerV2,
}

#[derive(Clone)]
pub struct FederationProductControl {
    inner: Arc<FederationProductControlInner>,
}

struct FederationProductControlInner {
    token: CancellationToken,
    active: Mutex<BTreeMap<String, FederationCancellationRequestV2>>,
    evidence: Mutex<FederationCancellationEvidenceV2>,
}

impl Default for FederationProductControl {
    fn default() -> Self {
        Self::new()
    }
}

impl FederationProductControl {
    #[must_use]
    pub fn new() -> Self {
        Self {
            inner: Arc::new(FederationProductControlInner {
                token: CancellationToken::new(),
                active: Mutex::new(BTreeMap::new()),
                evidence: Mutex::new(FederationCancellationEvidenceV2::default()),
            }),
        }
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.inner.token.is_cancelled()
    }

    pub fn cancel(&self) {
        self.inner.token.cancel();
        let requests = self
            .inner
            .active
            .lock()
            .map(|mut active| std::mem::take(&mut *active))
            .unwrap_or_default();
        for request in requests.into_values() {
            if let Ok(receipt) = observe_cancellation(request, false) {
                self.record_receipt(receipt);
            }
        }
    }

    #[must_use]
    pub fn cancellation_evidence(&self) -> FederationCancellationEvidenceV2 {
        self.inner
            .evidence
            .lock()
            .map(|evidence| evidence.clone())
            .unwrap_or_default()
    }

    pub(super) fn token(&self) -> CancellationToken {
        self.inner.token.clone()
    }

    pub(super) fn register_query(
        &self,
        query: &FederatedQueryV2,
    ) -> Result<RegisteredFederationQueryV2, CognitiveStoreError> {
        if self.is_cancelled() {
            return Err(CognitiveStoreError::Unavailable(
                "memory federation product control is already cancelled".to_string(),
            ));
        }
        let key = query.binding_digest().to_string();
        let cancellation_id = StableId::new(format!("cancel:{}", query.binding_digest()))
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let cancellation_nonce_digest = domain_digest32(
            b"hepta.memory-federation.product-cancellation.v2",
            &[
                query.binding_digest().as_array(),
                query.nonce_digest.as_array(),
            ],
        );
        let request = FederationCancellationRequestV2 {
            cancellation_id,
            query_id: query.query_id.clone(),
            peer_id: query.peer_id.clone(),
            query_binding_digest: query.binding_digest(),
            lease_epoch: query.lease_epoch,
            cancellation_nonce_digest,
        };
        self.inner
            .active
            .lock()
            .map_err(|_| {
                CognitiveStoreError::Unavailable(
                    "memory federation cancellation registry is unavailable".to_string(),
                )
            })?
            .insert(key.clone(), request);
        if self.is_cancelled() {
            self.cancel();
            return Err(CognitiveStoreError::Unavailable(
                "memory federation product control was cancelled during registration".to_string(),
            ));
        }
        Ok(RegisteredFederationQueryV2 {
            control: self.clone(),
            key,
        })
    }

    fn record_receipt(&self, receipt: FederationCancellationReceiptV2) {
        if let Ok(mut evidence) = self.inner.evidence.lock() {
            if evidence.receipts.len() < MAX_FEDERATION_DIAGNOSTICS_V2 {
                evidence.receipts.push(receipt);
            } else {
                evidence.omitted_receipts = evidence.omitted_receipts.saturating_add(1);
            }
        }
    }
}

pub(super) struct RegisteredFederationQueryV2 {
    control: FederationProductControl,
    key: String,
}

impl Drop for RegisteredFederationQueryV2 {
    fn drop(&mut self) {
        if let Ok(mut active) = self.control.inner.active.lock() {
            active.remove(&self.key);
        }
    }
}

pub(super) fn peer_digest(value: &str) -> String {
    Sha256Digest::for_bytes(value.as_bytes()).as_str().to_string()
}

pub(super) fn product_phase(value: FederationAttemptPhaseV2) -> FederationProductPhaseV2 {
    match value {
        FederationAttemptPhaseV2::Admission => FederationProductPhaseV2::QueryBuild,
        FederationAttemptPhaseV2::PreflightAuthority => {
            FederationProductPhaseV2::PreflightAuthority
        }
        FederationAttemptPhaseV2::Transport => FederationProductPhaseV2::Transport,
        FederationAttemptPhaseV2::PostIoAuthority => {
            FederationProductPhaseV2::PostIoAuthority
        }
        FederationAttemptPhaseV2::Integrity | FederationAttemptPhaseV2::Finalization => {
            FederationProductPhaseV2::Integrity
        }
        FederationAttemptPhaseV2::Control => FederationProductPhaseV2::Cancellation,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancellation_control_emits_bounded_canonical_receipt() {
        let query = FederatedQueryV2 {
            query_id: StableId::new("query:control".to_string()).expect("query id"),
            peer_id: StableId::new("peer:control".to_string()).expect("peer id"),
            principal_id: StableId::new("principal:control".to_string())
                .expect("principal id"),
            scope_digest: Digest32::of_bytes(b"scope"),
            purpose_digest: Digest32::of_bytes(b"purpose"),
            generation_vector_digest: Digest32::of_bytes(b"generation"),
            query_digest: Digest32::of_bytes(b"query"),
            maximum_results: 1,
            deadline_unix_ms: 100,
            lease_epoch: 1,
            nonce_digest: Digest32::of_bytes(b"nonce"),
        };
        let control = FederationProductControl::new();
        let registration = control.register_query(&query).expect("register query");
        control.cancel();
        drop(registration);
        let evidence = control.cancellation_evidence();
        assert_eq!(evidence.receipts.len(), 1);
        assert!(!evidence.receipts[0].terminal_observed);
        assert!(control.is_cancelled());
    }
}
'''


def planner_source() -> str:
    return r'''use super::*;

#[derive(Clone)]
pub(super) struct ProductClock {
    logical_start_ms: u64,
    started_at: Instant,
}

impl ProductClock {
    pub(super) fn new(logical_start_ms: u64) -> Self {
        Self {
            logical_start_ms,
            started_at: Instant::now(),
        }
    }

    pub(super) fn start_ms(&self) -> u64 {
        self.logical_start_ms
    }

    pub(super) fn now_ms(&self) -> u64 {
        self.logical_start_ms.saturating_add(
            u64::try_from(self.started_at.elapsed().as_millis()).unwrap_or(u64::MAX),
        )
    }
}

pub(super) fn build_product_query_and_lease(
    reader: &FederatedMemoryReader,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    logical_start_ms: u64,
    deadline_unix_ms: u64,
) -> Result<(FederatedQueryV2, FederatedLeaseV2), CognitiveStoreError> {
    let capability = reader.capability();
    let peer_id = StableId::new(capability.owner_agent_id().as_str().to_string())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let principal_id = StableId::new(access.agent_id().as_str().to_string())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let mut scope_bytes = serde_json::to_vec(capability.scope())
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    scope_bytes.extend_from_slice(access.workspace_sha256().as_str().as_bytes());
    let scope_digest =
        domain_digest32(b"hepta.memory-federation.product-scope.v2", &[&scope_bytes]);
    let purpose_digest = Digest32::of_bytes(PRODUCT_FEDERATION_PURPOSE);
    let generation_vector_digest = domain_digest32(
        b"hepta.memory-federation.product-generation.v2",
        &[
            capability.id().as_str().as_bytes(),
            &capability.generation().to_be_bytes(),
            &capability.revision().to_be_bytes(),
        ],
    );
    let query_digest = Digest32::of_bytes(request.query().as_bytes());
    let nonce_digest = product_attempt_nonce_digest(
        query_digest,
        capability.id().as_str(),
        logical_start_ms,
    )?;
    let query_id_digest = domain_digest32(
        b"hepta.memory-federation.product-query-id.v2",
        &[nonce_digest.as_array(), peer_id.as_str().as_bytes()],
    );
    let query_id = StableId::new(format!("query:{query_id_digest}"))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let query = FederatedQueryV2 {
        query_id,
        peer_id,
        principal_id,
        scope_digest,
        purpose_digest,
        generation_vector_digest,
        query_digest,
        maximum_results: u32::try_from(MAX_RETRIEVAL_RESULTS).unwrap_or(u32::MAX),
        deadline_unix_ms,
        lease_epoch: capability.generation(),
        nonce_digest,
    };
    let lease_id = StableId::new(format!("lease:{}", query.binding_digest()))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let lease = FederatedLeaseV2 {
        lease_id,
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: query.lease_epoch,
        expires_unix_ms: capability_expiry_ms(capability)?,
        revoked: false,
    };
    Ok((query, lease))
}

fn product_attempt_nonce_digest(
    query_digest: Digest32,
    capability_id: &str,
    logical_start_ms: u64,
) -> Result<Digest32, CognitiveStoreError> {
    let mut random = [0_u8; 32];
    OsRng.try_fill_bytes(&mut random).map_err(|error| {
        CognitiveStoreError::Unavailable(format!(
            "memory federation OS randomness is unavailable: {error}"
        ))
    })?;
    Ok(domain_digest32(
        b"hepta.memory-federation.product-nonce.v2",
        &[
            &random,
            query_digest.as_array(),
            capability_id.as_bytes(),
            &logical_start_ms.to_be_bytes(),
        ],
    ))
}

pub(super) fn capability_expiry_ms(
    capability: &FederationCapability,
) -> Result<u64, CognitiveStoreError> {
    seconds_to_ms(capability.expires_at_unix_seconds())
}

pub(super) fn seconds_to_ms(value: i64) -> Result<u64, CognitiveStoreError> {
    let value = u64::try_from(value).map_err(|_| {
        CognitiveStoreError::Invalid("memory federation time must be non-negative".to_string())
    })?;
    value
        .checked_mul(1_000)
        .ok_or_else(|| CognitiveStoreError::Invalid("memory federation time overflow".to_string()))
}

pub(super) fn domain_digest32(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    for part in parts {
        bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Digest32::of_bytes(&bytes)
}
'''


def evidence_source() -> str:
    return r'''use super::*;

pub(super) fn product_evidence_item(
    candidate: &FederatedRetrievalCandidate,
) -> Result<FederatedEvidenceItemV2, FederationV2Error> {
    let source_owner_id = StableId::new(candidate.source_agent_id.as_str().to_string())
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let record_id = StableId::new(candidate.candidate.memory.id.memory_id.as_str().to_string())
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let record_revision = Revision::new(candidate.candidate.memory.id.revision)
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let record_digest = Digest32::from_str(candidate.candidate.memory.content_sha256.as_str())
        .map_err(|_| FederationV2Error::TransportRejected)?;
    let binding = serde_json::to_vec(&candidate.revalidation)
        .map_err(|_| FederationV2Error::TransportRejected)?;
    Ok(FederatedEvidenceItemV2 {
        source_owner_id,
        record_id,
        record_revision,
        record_digest,
        support_digest: domain_digest32(b"hepta.memory-federation.product-support.v2", &[&binding]),
        validity_digest: domain_digest32(
            b"hepta.memory-federation.product-validity.v2",
            &[&binding],
        ),
    })
}
'''


def discovery_source() -> str:
    return r'''use super::*;

pub(super) struct ProductDiscoveryV2 {
    pub(super) readers: Vec<(HeptaAgentLayout, FederatedMemoryReader)>,
    pub(super) failed_owners: usize,
    pub(super) diagnostics: FederatedDiagnosticLedgerV2,
}

struct DiscoveryOutcomeV2 {
    owner_layout: HeptaAgentLayout,
    peer_digest: String,
    result: Result<Vec<FederatedMemoryReader>, ()>,
}

fn discover_one(
    owner_layout: HeptaAgentLayout,
    consumer_agent_id: AgentId,
    now_unix_seconds: i64,
) -> BoxFuture<'static, DiscoveryOutcomeV2> {
    Box::pin(async move {
        let peer = peer_digest(owner_layout.agent_id().as_str());
        let result = tokio::time::timeout(
            PRODUCT_FEDERATION_DISCOVERY_PEER_BUDGET,
            FederatedMemoryReader::discover(
                &owner_layout,
                &consumer_agent_id,
                now_unix_seconds,
            ),
        )
        .await
        .map_err(|_| ())
        .and_then(|result| result.map_err(|_| ()));
        DiscoveryOutcomeV2 {
            owner_layout,
            peer_digest: peer,
            result,
        }
    })
}

pub(super) async fn discover_product_peers(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    clock: &ProductClock,
    global_deadline_ms: u64,
    control: &FederationProductControl,
) -> ProductDiscoveryV2 {
    let mut diagnostics = FederatedDiagnosticLedgerV2::default();
    let mut pending = owner_layouts.iter().cloned();
    let mut active: FuturesUnordered<BoxFuture<'static, DiscoveryOutcomeV2>> =
        FuturesUnordered::new();
    let mut unresolved = owner_layouts
        .iter()
        .map(|owner| peer_digest(owner.agent_id().as_str()))
        .collect::<BTreeSet<_>>();
    let mut readers = Vec::new();
    let mut failed_owners = 0_usize;

    while active.len() < PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY {
        let Some(owner) = pending.next() else { break };
        active.push(discover_one(
            owner,
            consumer_agent_id.clone(),
            request.now_unix_seconds(),
        ));
    }

    while !active.is_empty() && !control.is_cancelled() {
        let remaining = global_deadline_ms.saturating_sub(clock.now_ms());
        if remaining == 0 {
            break;
        }
        let outcome = tokio::time::timeout(
            Duration::from_millis(remaining),
            active.next(),
        )
        .await;
        let Ok(Some(outcome)) = outcome else { break };
        unresolved.remove(&outcome.peer_digest);
        match outcome.result {
            Ok(discovered) => {
                readers.extend(discovered.into_iter().filter(|reader| {
                    reader.capability().scope().consumer_workspace_sha256()
                        == access.workspace_sha256()
                }).map(|reader| (outcome.owner_layout.clone(), reader)));
            }
            Err(()) => {
                failed_owners = failed_owners.saturating_add(1);
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: outcome.peer_digest,
                    phase: FederationProductPhaseV2::Discovery,
                    disposition: FederationProductDispositionV2::Failed,
                    failure: Some(FederationProductFailureV2::DiscoveryUnavailable),
                    cancellation_receipt_digest: None,
                });
            }
        }
        if let Some(owner) = pending.next() {
            active.push(discover_one(
                owner,
                consumer_agent_id.clone(),
                request.now_unix_seconds(),
            ));
        }
    }

    if control.is_cancelled() || !unresolved.is_empty() {
        failed_owners = failed_owners.saturating_add(unresolved.len());
        for digest in unresolved {
            diagnostics.push(FederatedPeerDiagnosticV2 {
                peer_digest: digest,
                phase: FederationProductPhaseV2::Discovery,
                disposition: if control.is_cancelled() {
                    FederationProductDispositionV2::Cancelled
                } else {
                    FederationProductDispositionV2::Failed
                },
                failure: Some(if control.is_cancelled() {
                    FederationProductFailureV2::DeadlineOrCancelled
                } else {
                    FederationProductFailureV2::DiscoveryUnavailable
                }),
                cancellation_receipt_digest: None,
            });
        }
    }

    ProductDiscoveryV2 {
        readers,
        failed_owners,
        diagnostics,
    }
}
'''


def attempt_source() -> str:
    return r'''use super::*;

pub(super) enum ProductPeerOutcomeV2 {
    Canonical(FederationAttemptOutcomeV2),
    ProductFailure(FederationProductFailureV2),
}

pub(super) struct ProductPeerAttemptV2 {
    pub(super) peer_digest: String,
    pub(super) outcome: ProductPeerOutcomeV2,
    pub(super) captured: Option<FederatedRetrievalBatch>,
}

pub(super) async fn execute_product_peer(
    owner_layout: &HeptaAgentLayout,
    reader: &FederatedMemoryReader,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    clock: &ProductClock,
    global_deadline_ms: u64,
    control: &FederationProductControl,
) -> ProductPeerAttemptV2 {
    let peer = peer_digest(reader.capability().owner_agent_id().as_str());
    if clock.now_ms() >= global_deadline_ms || control.is_cancelled() {
        return ProductPeerAttemptV2 {
            peer_digest: peer,
            outcome: ProductPeerOutcomeV2::ProductFailure(
                FederationProductFailureV2::DeadlineOrCancelled,
            ),
            captured: None,
        };
    }
    let (query, lease) = match build_product_query_and_lease(
        reader,
        access,
        request,
        clock.start_ms(),
        global_deadline_ms,
    ) {
        Ok(value) => value,
        Err(_) => {
            return ProductPeerAttemptV2 {
                peer_digest: peer,
                outcome: ProductPeerOutcomeV2::ProductFailure(
                    FederationProductFailureV2::QueryBuildRejected,
                ),
                captured: None,
            };
        }
    };
    let registration = match control.register_query(&query) {
        Ok(registration) => registration,
        Err(_) => {
            return ProductPeerAttemptV2 {
                peer_digest: peer,
                outcome: ProductPeerOutcomeV2::ProductFailure(
                    FederationProductFailureV2::DeadlineOrCancelled,
                ),
                captured: None,
            };
        }
    };
    let captured = Arc::new(Mutex::new(None));
    let transport = ProductReaderTransport {
        reader,
        access,
        request,
        captured: Arc::clone(&captured),
    };
    let authority = ProductReaderAuthority {
        owner_layout,
        consumer_agent_id: access.agent_id(),
        expected_capability: reader.capability(),
        clock: clock.clone(),
    };
    let attempt_control = ProductAttemptControl {
        clock: clock.clone(),
        control: control.clone(),
    };
    let outcome = execute_once_outcome(
        &transport,
        &authority,
        &attempt_control,
        clock.start_ms(),
        query,
        &lease,
    )
    .await;
    drop(registration);
    let captured = captured.lock().ok().and_then(|mut batch| batch.take());
    ProductPeerAttemptV2 {
        peer_digest: peer,
        outcome: ProductPeerOutcomeV2::Canonical(outcome),
        captured,
    }
}

struct ProductReaderTransport<'a> {
    reader: &'a FederatedMemoryReader,
    access: &'a FederationConsumerAccess,
    request: &'a RetrievalRequest,
    captured: Arc<Mutex<Option<FederatedRetrievalBatch>>>,
}

impl FederationTransportV2 for ProductReaderTransport<'_> {
    fn send_once<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationTransportFuture<'a> {
        Box::pin(async move {
            let (batch, observed_frontier) = self
                .reader
                .retrieve_with_frontier(self.access, self.request)
                .await
                .map_err(|_| FederationV2Error::TransportRejected)?;
            let items = batch
                .candidates
                .iter()
                .map(product_evidence_item)
                .collect::<Result<Vec<_>, _>>()?;
            let completeness = if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else {
                FederatedCompletenessV2::Complete
            };
            let expires_unix_ms = capability_expiry_ms(self.reader.capability())
                .map_err(|_| FederationV2Error::TransportRejected)?;
            let response = RemoteFederatedResponseV2 {
                peer_id: query.peer_id.clone(),
                query_binding_digest: query.binding_digest(),
                scope_digest: query.scope_digest,
                purpose_digest: query.purpose_digest,
                generation_vector_digest: query.generation_vector_digest,
                response_digest: Digest32::ZERO,
                observed_frontier,
                expires_unix_ms,
                items,
                completeness,
                terminal_observed: true,
            }
            .seal()?;
            let mut guard = self
                .captured
                .lock()
                .map_err(|_| FederationV2Error::TransportRejected)?;
            *guard = Some(batch);
            Ok(FederationTransportResultV2::Terminal(response))
        })
    }
}

struct ProductReaderAuthority<'a> {
    owner_layout: &'a HeptaAgentLayout,
    consumer_agent_id: &'a AgentId,
    expected_capability: &'a FederationCapability,
    clock: ProductClock,
}

impl FederationAuthorityV2 for ProductReaderAuthority<'_> {
    fn revalidate<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFuture<'a> {
        Box::pin(async move {
            let observed_unix_ms = self.clock.now_ms();
            let now_unix_seconds = i64::try_from(observed_unix_ms / 1_000)
                .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let readers = FederatedMemoryReader::discover(
                self.owner_layout,
                self.consumer_agent_id,
                now_unix_seconds,
            )
            .await
            .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let current = readers
                .iter()
                .find(|reader| reader.capability().id() == self.expected_capability.id());
            let state = match current {
                None => FederationAuthorityStateV2::Revoked,
                Some(reader) if reader.capability() == self.expected_capability => {
                    FederationAuthorityStateV2::Current
                }
                Some(_) => FederationAuthorityStateV2::StaleGeneration,
            };
            let authority_capability =
                current.map_or(self.expected_capability, |reader| reader.capability());
            let authority_expires_unix_ms = capability_expiry_ms(authority_capability)
                .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            Ok(FederationAuthorityObservationV2 {
                query_binding_digest: query.binding_digest(),
                lease_epoch: query.lease_epoch,
                observed_unix_ms,
                authority_expires_unix_ms,
                state,
            })
        })
    }
}

struct ProductAttemptControl {
    clock: ProductClock,
    control: FederationProductControl,
}

impl FederationAttemptControlV2 for ProductAttemptControl {
    fn wait_for_stop<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationStopFuture<'a> {
        let current = self.clock.now_ms();
        let authority_deadline = query.deadline_unix_ms.min(lease.expires_unix_ms);
        let remaining = authority_deadline.saturating_sub(current);
        let cancellation = self.control.token();
        Box::pin(async move {
            tokio::select! {
                biased;
                () = cancellation.cancelled() => FederationStopReasonV2::Cancelled,
                () = tokio::time::sleep(Duration::from_millis(remaining)) => {
                    FederationStopReasonV2::DeadlineExpired
                }
            }
        })
    }
}
'''


def aggregator_source() -> str:
    return r'''use super::*;

pub(super) fn apply_peer_attempt(
    aggregate: &mut FederatedCoverageV2,
    candidates: &mut Vec<FederatedRetrievalCandidate>,
    diagnostics: &mut FederatedDiagnosticLedgerV2,
    attempt: ProductPeerAttemptV2,
) {
    match attempt.outcome {
        ProductPeerOutcomeV2::ProductFailure(failure) => {
            aggregate.failed_peers = aggregate.failed_peers.saturating_add(1);
            record_failure_class(&mut aggregate.failures, failure);
            diagnostics.push(FederatedPeerDiagnosticV2 {
                peer_digest: attempt.peer_digest,
                phase: match failure {
                    FederationProductFailureV2::DiscoveryUnavailable => {
                        FederationProductPhaseV2::Discovery
                    }
                    FederationProductFailureV2::QueryBuildRejected => {
                        FederationProductPhaseV2::QueryBuild
                    }
                    FederationProductFailureV2::DeadlineOrCancelled => {
                        FederationProductPhaseV2::Cancellation
                    }
                    FederationProductFailureV2::AuthorityRejected => {
                        FederationProductPhaseV2::PreflightAuthority
                    }
                    FederationProductFailureV2::IntegrityRejected => {
                        FederationProductPhaseV2::Integrity
                    }
                    FederationProductFailureV2::TransportUnavailable => {
                        FederationProductPhaseV2::Transport
                    }
                    FederationProductFailureV2::FinalUseUnavailable => {
                        FederationProductPhaseV2::FinalUse
                    }
                },
                disposition: if failure == FederationProductFailureV2::DeadlineOrCancelled {
                    FederationProductDispositionV2::Cancelled
                } else {
                    FederationProductDispositionV2::Failed
                },
                failure: Some(failure),
                cancellation_receipt_digest: None,
            });
        }
        ProductPeerOutcomeV2::Canonical(outcome) => {
            if let Some(failure) = outcome.failure {
                aggregate.failed_peers = aggregate.failed_peers.saturating_add(1);
                record_product_failure(&mut aggregate.failures, &failure.error);
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: attempt.peer_digest,
                    phase: product_phase(failure.phase),
                    disposition: if matches!(
                        failure.error,
                        FederationV2Error::AttemptCancelled | FederationV2Error::DeadlineExpired
                    ) {
                        FederationProductDispositionV2::Cancelled
                    } else {
                        FederationProductDispositionV2::Failed
                    },
                    failure: Some(classify_product_failure(&failure.error)),
                    cancellation_receipt_digest: None,
                });
                return;
            }
            let Some(result) = outcome.result else {
                aggregate.failed_peers = aggregate.failed_peers.saturating_add(1);
                aggregate.failures.integrity_rejected =
                    aggregate.failures.integrity_rejected.saturating_add(1);
                return;
            };
            if result.validity == FederatedValidityV2::Valid
                && !result.items.is_empty()
                && attempt.captured.is_none()
            {
                aggregate.failed_peers = aggregate.failed_peers.saturating_add(1);
                aggregate.failures.integrity_rejected =
                    aggregate.failures.integrity_rejected.saturating_add(1);
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: attempt.peer_digest,
                    phase: FederationProductPhaseV2::Integrity,
                    disposition: FederationProductDispositionV2::Failed,
                    failure: Some(FederationProductFailureV2::IntegrityRejected),
                    cancellation_receipt_digest: None,
                });
                return;
            }
            merge_product_coverage(aggregate, &result.coverage, result.validity);
            if result.validity != FederatedValidityV2::Valid {
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: attempt.peer_digest,
                    phase: FederationProductPhaseV2::PostIoAuthority,
                    disposition: FederationProductDispositionV2::Partial,
                    failure: Some(FederationProductFailureV2::AuthorityRejected),
                    cancellation_receipt_digest: None,
                });
                return;
            }
            let selected = result
                .items
                .iter()
                .map(|item| {
                    (
                        item.source_owner_id.as_str().to_string(),
                        item.record_id.as_str().to_string(),
                        item.record_revision.get(),
                    )
                })
                .collect::<BTreeSet<_>>();
            if let Some(batch) = attempt.captured {
                candidates.extend(batch.candidates.into_iter().filter(|candidate| {
                    selected.contains(&(
                        candidate.source_agent_id.as_str().to_string(),
                        candidate.candidate.memory.id.memory_id.as_str().to_string(),
                        candidate.candidate.memory.id.revision,
                    ))
                }));
            }
            if result.completeness != FederatedCompletenessV2::Complete {
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: attempt.peer_digest,
                    phase: FederationProductPhaseV2::Aggregation,
                    disposition: FederationProductDispositionV2::Partial,
                    failure: None,
                    cancellation_receipt_digest: None,
                });
            }
        }
    }
}

pub(super) fn finalize_candidates(
    candidates: &mut Vec<FederatedRetrievalCandidate>,
    coverage: &mut FederatedCoverageV2,
    diagnostics: &mut FederatedDiagnosticLedgerV2,
) {
    candidates.sort_by(|left, right| {
        right
            .candidate
            .reciprocal_rank_score
            .cmp(&left.candidate.reciprocal_rank_score)
            .then_with(|| left.source_agent_id.cmp(&right.source_agent_id))
            .then_with(|| {
                left.candidate
                    .memory
                    .id
                    .memory_id
                    .cmp(&right.candidate.memory.id.memory_id)
            })
            .then_with(|| {
                left.candidate
                    .memory
                    .id
                    .revision
                    .cmp(&right.candidate.memory.id.revision)
            })
    });
    candidates.dedup_by(|left, right| {
        left.source_agent_id == right.source_agent_id
            && left.candidate.memory.id == right.candidate.memory.id
    });
    let before = candidates.len();
    candidates.truncate(MAX_RETRIEVAL_RESULTS);
    let truncated = before.saturating_sub(candidates.len());
    coverage.truncated_items = coverage
        .truncated_items
        .saturating_add(u32::try_from(truncated).unwrap_or(u32::MAX));
    if truncated > 0 {
        diagnostics.push(FederatedPeerDiagnosticV2 {
            peer_digest: peer_digest("aggregate"),
            phase: FederationProductPhaseV2::Aggregation,
            disposition: FederationProductDispositionV2::Truncated,
            failure: None,
            cancellation_receipt_digest: None,
        });
    }
}

fn merge_product_coverage(
    aggregate: &mut FederatedCoverageV2,
    attempt: &FederatedCoverageV2,
    validity: FederatedValidityV2,
) {
    aggregate.truncated_peers = aggregate
        .truncated_peers
        .saturating_add(attempt.truncated_peers);
    aggregate.omitted_peer_candidates = aggregate
        .omitted_peer_candidates
        .saturating_add(attempt.omitted_peer_candidates);
    aggregate.truncated_items = aggregate
        .truncated_items
        .saturating_add(attempt.truncated_items);
    merge_failure_coverage(&mut aggregate.failures, &attempt.failures);
    if validity == FederatedValidityV2::Valid {
        aggregate.completed_peers = aggregate
            .completed_peers
            .saturating_add(attempt.completed_peers);
        aggregate.failed_peers = aggregate.failed_peers.saturating_add(attempt.failed_peers);
    } else {
        aggregate.failed_peers = aggregate
            .failed_peers
            .saturating_add(attempt.failed_peers)
            .saturating_add(attempt.completed_peers);
        aggregate.failures.authority_rejected = aggregate
            .failures
            .authority_rejected
            .saturating_add(attempt.completed_peers);
    }
}

fn merge_failure_coverage(
    aggregate: &mut FederatedFailureCoverageV2,
    attempt: &FederatedFailureCoverageV2,
) {
    aggregate.discovery_unavailable = aggregate
        .discovery_unavailable
        .saturating_add(attempt.discovery_unavailable);
    aggregate.deadline_or_cancelled = aggregate
        .deadline_or_cancelled
        .saturating_add(attempt.deadline_or_cancelled);
    aggregate.authority_rejected = aggregate
        .authority_rejected
        .saturating_add(attempt.authority_rejected);
    aggregate.integrity_rejected = aggregate
        .integrity_rejected
        .saturating_add(attempt.integrity_rejected);
    aggregate.transport_unavailable = aggregate
        .transport_unavailable
        .saturating_add(attempt.transport_unavailable);
}

fn record_failure_class(
    failures: &mut FederatedFailureCoverageV2,
    failure: FederationProductFailureV2,
) {
    match failure {
        FederationProductFailureV2::DiscoveryUnavailable => {
            failures.discovery_unavailable = failures.discovery_unavailable.saturating_add(1);
        }
        FederationProductFailureV2::DeadlineOrCancelled => {
            failures.deadline_or_cancelled = failures.deadline_or_cancelled.saturating_add(1);
        }
        FederationProductFailureV2::AuthorityRejected
        | FederationProductFailureV2::FinalUseUnavailable => {
            failures.authority_rejected = failures.authority_rejected.saturating_add(1);
        }
        FederationProductFailureV2::QueryBuildRejected
        | FederationProductFailureV2::IntegrityRejected => {
            failures.integrity_rejected = failures.integrity_rejected.saturating_add(1);
        }
        FederationProductFailureV2::TransportUnavailable => {
            failures.transport_unavailable = failures.transport_unavailable.saturating_add(1);
        }
    }
}

fn classify_product_failure(error: &FederationV2Error) -> FederationProductFailureV2 {
    match error {
        FederationV2Error::DeadlineExpired
        | FederationV2Error::AttemptCancelled
        | FederationV2Error::LeaseExpired
        | FederationV2Error::ResponseExpired => {
            FederationProductFailureV2::DeadlineOrCancelled
        }
        FederationV2Error::LeaseRevoked
        | FederationV2Error::LeaseEpochMismatch
        | FederationV2Error::AuthorityObservationRegressed
        | FederationV2Error::AuthorityExpired
        | FederationV2Error::LeaseAuthorityHorizonExceeded
        | FederationV2Error::AuthorityNotCurrent(_)
        | FederationV2Error::AuthorityGranted
        | FederationV2Error::AuthorityRevalidationFailed => {
            FederationProductFailureV2::AuthorityRejected
        }
        FederationV2Error::TransportRejected => {
            FederationProductFailureV2::TransportUnavailable
        }
        FederationV2Error::ZeroValue(_)
        | FederationV2Error::EmptyDigest(_)
        | FederationV2Error::InvalidMaximumResults
        | FederationV2Error::IdentityMismatch(_)
        | FederationV2Error::DigestMismatch(_)
        | FederationV2Error::MissingTerminalObservation
        | FederationV2Error::ResultLimitExceeded
        | FederationV2Error::DuplicateResultIdentity
        | FederationV2Error::InvalidCompleteness
        | FederationV2Error::InvalidCoverage
        | FederationV2Error::StaleEvidenceExposed
        | FederationV2Error::InvalidAttemptOutcome => {
            FederationProductFailureV2::IntegrityRejected
        }
    }
}

fn record_product_failure(
    failures: &mut FederatedFailureCoverageV2,
    error: &FederationV2Error,
) {
    record_failure_class(failures, classify_product_failure(error));
}
'''


def final_revalidator_source() -> str:
    return r'''use super::*;

pub(super) async fn revalidate_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    binding: &FederatedMemoryRevalidationBinding,
    now_unix_seconds: i64,
) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
    revalidate_federated_product_batch(
        consumer_agent_id,
        owner_layouts,
        access,
        std::slice::from_ref(binding),
        now_unix_seconds,
    )
    .await?
    .pop()
    .ok_or_else(|| {
        CognitiveStoreError::Corrupt(
            "single federated product revalidation returned no status".to_string(),
        )
    })
}

struct RevalidationGroupV2 {
    indices: Vec<usize>,
    owner_layout: HeptaAgentLayout,
    capability_id: String,
    bindings: Vec<FederatedMemoryRevalidationBinding>,
}

struct RevalidationOutcomeV2 {
    indices: Vec<usize>,
    statuses: Vec<FederatedRevalidationStatus>,
}

fn revalidate_group(
    group: RevalidationGroupV2,
    consumer_agent_id: AgentId,
    access: FederationConsumerAccess,
    now_unix_seconds: i64,
) -> BoxFuture<'static, RevalidationOutcomeV2> {
    Box::pin(async move {
        let stale = || {
            vec![
                FederatedRevalidationStatus::Stale(
                    FederationRevalidationDrift::OwnerUnavailable,
                );
                group.indices.len()
            ]
        };
        let statuses = match FederatedMemoryReader::discover(
            &group.owner_layout,
            &consumer_agent_id,
            now_unix_seconds,
        )
        .await
        {
            Ok(readers) => match readers
                .iter()
                .find(|reader| reader.capability().id().as_str() == group.capability_id)
            {
                Some(reader) => reader
                    .revalidate_many(&access, &group.bindings, now_unix_seconds)
                    .await
                    .ok()
                    .filter(|values| values.len() == group.indices.len())
                    .unwrap_or_else(stale),
                None => vec![
                    FederatedRevalidationStatus::Stale(
                        FederationRevalidationDrift::CapabilityMissing,
                    );
                    group.indices.len()
                ],
            },
            Err(_) => stale(),
        };
        RevalidationOutcomeV2 {
            indices: group.indices,
            statuses,
        }
    })
}

pub(super) async fn revalidate_federated_product_batch(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    access: &FederationConsumerAccess,
    bindings: &[FederatedMemoryRevalidationBinding],
    now_unix_seconds: i64,
) -> Result<Vec<FederatedRevalidationStatus>, CognitiveStoreError> {
    if bindings.is_empty() {
        return Ok(Vec::new());
    }
    if access.agent_id() != consumer_agent_id {
        return Ok(vec![
            FederatedRevalidationStatus::Stale(FederationRevalidationDrift::Consumer);
            bindings.len()
        ]);
    }
    let owners = owner_layouts
        .iter()
        .cloned()
        .map(|layout| (layout.agent_id().clone(), layout))
        .collect::<BTreeMap<_, _>>();
    let mut grouped = BTreeMap::<(AgentId, String), Vec<usize>>::new();
    for (index, binding) in bindings.iter().enumerate() {
        grouped
            .entry((
                binding.source_agent_id.clone(),
                binding.capability.id().as_str().to_string(),
            ))
            .or_default()
            .push(index);
    }
    let mut statuses = vec![
        FederatedRevalidationStatus::Stale(FederationRevalidationDrift::OwnerUnavailable);
        bindings.len()
    ];
    let mut pending = VecDeque::new();
    for ((owner_id, capability_id), indices) in grouped {
        let Some(owner_layout) = owners.get(&owner_id).cloned() else {
            for index in indices {
                statuses[index] = FederatedRevalidationStatus::Stale(
                    FederationRevalidationDrift::CapabilityMissing,
                );
            }
            continue;
        };
        pending.push_back(RevalidationGroupV2 {
            bindings: indices.iter().map(|index| bindings[*index].clone()).collect(),
            indices,
            owner_layout,
            capability_id,
        });
    }
    let mut active: FuturesUnordered<BoxFuture<'static, RevalidationOutcomeV2>> =
        FuturesUnordered::new();
    while active.len() < PRODUCT_FEDERATION_FINAL_REVALIDATION_CONCURRENCY {
        let Some(group) = pending.pop_front() else { break };
        active.push(revalidate_group(
            group,
            consumer_agent_id.clone(),
            access.clone(),
            now_unix_seconds,
        ));
    }
    let started = Instant::now();
    while !active.is_empty() {
        let elapsed = started.elapsed();
        let remaining = PRODUCT_FEDERATION_TOTAL_BUDGET.saturating_sub(elapsed);
        if remaining.is_zero() {
            break;
        }
        let Ok(Some(outcome)) = tokio::time::timeout(remaining, active.next()).await else {
            break;
        };
        for (index, status) in outcome.indices.into_iter().zip(outcome.statuses) {
            statuses[index] = status;
        }
        if let Some(group) = pending.pop_front() {
            active.push(revalidate_group(
                group,
                consumer_agent_id.clone(),
                access.clone(),
                now_unix_seconds,
            ));
        }
    }
    Ok(statuses)
}
'''


def module_source() -> str:
    return r'''use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use futures::future::BoxFuture;
use futures::stream::FuturesUnordered;
use futures::StreamExt;
use rand::rngs::OsRng;
use rand::TryRngCore;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory_federation::FederatedCompletenessV2;
use codex_hepta_memory_federation::FederatedCoverageV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2;
use codex_hepta_memory_federation::FederatedFailureCoverageV2;
use codex_hepta_memory_federation::FederatedLeaseV2;
use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::FederatedValidityV2;
use codex_hepta_memory_federation::FederationAttemptControlV2;
use codex_hepta_memory_federation::FederationAttemptOutcomeV2;
use codex_hepta_memory_federation::FederationAttemptPhaseV2;
use codex_hepta_memory_federation::FederationAuthorityFuture;
use codex_hepta_memory_federation::FederationAuthorityObservationV2;
use codex_hepta_memory_federation::FederationAuthorityStateV2;
use codex_hepta_memory_federation::FederationAuthorityV2;
use codex_hepta_memory_federation::FederationCancellationReceiptV2;
use codex_hepta_memory_federation::FederationCancellationRequestV2;
use codex_hepta_memory_federation::FederationStopFuture;
use codex_hepta_memory_federation::FederationStopReasonV2;
use codex_hepta_memory_federation::FederationTransportFuture;
use codex_hepta_memory_federation::FederationTransportResultV2;
use codex_hepta_memory_federation::FederationTransportV2;
use codex_hepta_memory_federation::FederationV2Error;
use codex_hepta_memory_federation::RemoteFederatedResponseV2;
use codex_hepta_memory_federation::execute_once_outcome;
use codex_hepta_memory_federation::observe_cancellation;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CognitiveStoreError;
use crate::FederatedMemoryReader;
use crate::FederatedMemoryRevalidationBinding;
use crate::FederatedRetrievalBatch;
use crate::FederatedRetrievalCandidate;
use crate::FederatedRevalidationStatus;
use crate::FederationCapability;
use crate::FederationConsumerAccess;
use crate::FederationRevalidationDrift;
use crate::MAX_FEDERATION_SOURCES_PER_AGENT;
use crate::MAX_RETRIEVAL_RESULTS;
use crate::RetrievalRequest;

mod aggregator;
mod attempt;
mod discovery;
mod evidence;
mod final_revalidator;
mod planner;
mod telemetry;

use aggregator::apply_peer_attempt;
use aggregator::finalize_candidates;
use attempt::execute_product_peer;
use discovery::discover_product_peers;
use evidence::product_evidence_item;
use planner::ProductClock;
use planner::build_product_query_and_lease;
use planner::capability_expiry_ms;
use planner::domain_digest32;
use planner::seconds_to_ms;

pub use telemetry::FederatedDiagnosticLedgerV2;
pub use telemetry::FederatedPeerDiagnosticV2;
pub use telemetry::FederatedProductReadV2;
pub use telemetry::FederationCancellationEvidenceV2;
pub use telemetry::FederationProductControl;
pub use telemetry::FederationProductDispositionV2;
pub use telemetry::FederationProductFailureV2;
pub use telemetry::FederationProductPhaseV2;
pub use telemetry::MAX_FEDERATION_DIAGNOSTICS_V2;
use telemetry::peer_digest;
use telemetry::product_phase;

const PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);
const PRODUCT_FEDERATION_DISCOVERY_PEER_BUDGET: Duration = Duration::from_millis(500);
const PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY: usize = 16;
const PRODUCT_FEDERATION_FINAL_REVALIDATION_CONCURRENCY: usize = 16;
const PRODUCT_FEDERATION_PURPOSE: &[u8] = b"hepta.cognitive.federated-recall.product.v2";

pub(super) async fn retrieve_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    omitted_owner_candidates: u32,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
    let control = FederationProductControl::new();
    let read = retrieve_federated_product_with_control(
        consumer_agent_id,
        owner_layouts,
        omitted_owner_candidates,
        access,
        request,
        &control,
    )
    .await?;
    Ok((read.batch, read.coverage))
}

pub(super) async fn retrieve_federated_product_with_control(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    omitted_owner_candidates: u32,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
    control: &FederationProductControl,
) -> Result<FederatedProductReadV2, CognitiveStoreError> {
    if access.agent_id() != consumer_agent_id {
        return Err(CognitiveStoreError::AccessDenied(
            "memory federation caller does not match the product consumer".to_string(),
        ));
    }
    let logical_start_ms = seconds_to_ms(request.now_unix_seconds())?;
    let clock = ProductClock::new(logical_start_ms);
    let global_deadline_ms = logical_start_ms
        .checked_add(u64::try_from(PRODUCT_FEDERATION_TOTAL_BUDGET.as_millis()).unwrap_or(u64::MAX))
        .ok_or_else(|| CognitiveStoreError::Invalid("federation deadline overflow".to_string()))?;
    let discovery = discover_product_peers(
        consumer_agent_id,
        owner_layouts,
        access,
        request,
        &clock,
        global_deadline_ms,
        control,
    )
    .await;
    let mut readers = discovery.readers;
    let mut diagnostics = discovery.diagnostics;
    readers.sort_by(|(_, left), (_, right)| {
        left.capability()
            .owner_agent_id()
            .cmp(right.capability().owner_agent_id())
            .then_with(|| left.capability().id().cmp(right.capability().id()))
    });
    readers.dedup_by(|(_, left), (_, right)| left.capability().id() == right.capability().id());
    let observable_peer_slots = readers.len().saturating_add(discovery.failed_owners);
    let truncated_peers = observable_peer_slots.saturating_sub(MAX_FEDERATION_SOURCES_PER_AGENT);
    for (_, reader) in readers.iter().skip(MAX_FEDERATION_SOURCES_PER_AGENT) {
        diagnostics.push(FederatedPeerDiagnosticV2 {
            peer_digest: peer_digest(reader.capability().owner_agent_id().as_str()),
            phase: FederationProductPhaseV2::Discovery,
            disposition: FederationProductDispositionV2::Truncated,
            failure: None,
            cancellation_receipt_digest: None,
        });
    }
    readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);
    let discovery_failure_slots = discovery
        .failed_owners
        .min(MAX_FEDERATION_SOURCES_PER_AGENT.saturating_sub(readers.len()));
    let requested_peer_slots = readers.len().saturating_add(discovery_failure_slots);
    let mut coverage = FederatedCoverageV2 {
        requested_peers: u32::try_from(requested_peer_slots).unwrap_or(u32::MAX),
        completed_peers: 0,
        failed_peers: u32::try_from(discovery_failure_slots).unwrap_or(u32::MAX),
        truncated_peers: u32::try_from(truncated_peers).unwrap_or(u32::MAX),
        omitted_peer_candidates: omitted_owner_candidates,
        truncated_items: 0,
        failures: FederatedFailureCoverageV2 {
            discovery_unavailable: u32::try_from(discovery_failure_slots).unwrap_or(u32::MAX),
            ..FederatedFailureCoverageV2::default()
        },
    };
    if omitted_owner_candidates > 0 {
        diagnostics.push(FederatedPeerDiagnosticV2 {
            peer_digest: peer_digest("omitted-owner-candidates"),
            phase: FederationProductPhaseV2::Discovery,
            disposition: FederationProductDispositionV2::Truncated,
            failure: None,
            cancellation_receipt_digest: None,
        });
    }
    let mut attempts = FuturesUnordered::new();
    for (owner_layout, reader) in &readers {
        attempts.push(execute_product_peer(
            owner_layout,
            reader,
            access,
            request,
            &clock,
            global_deadline_ms,
            control,
        ));
    }
    let mut candidates = Vec::new();
    while let Some(attempt) = attempts.next().await {
        apply_peer_attempt(
            &mut coverage,
            &mut candidates,
            &mut diagnostics,
            attempt,
        );
    }
    for receipt in control.cancellation_evidence().receipts {
        diagnostics.push(FederatedPeerDiagnosticV2 {
            peer_digest: peer_digest(receipt.query_id.as_str()),
            phase: FederationProductPhaseV2::Cancellation,
            disposition: FederationProductDispositionV2::Cancelled,
            failure: Some(FederationProductFailureV2::DeadlineOrCancelled),
            cancellation_receipt_digest: Some(receipt.receipt_digest.to_string()),
        });
    }
    finalize_candidates(&mut candidates, &mut coverage, &mut diagnostics);
    Ok(FederatedProductReadV2 {
        batch: FederatedRetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query().as_bytes()),
            candidates,
        },
        coverage,
        diagnostics,
    })
}

pub(super) use final_revalidator::revalidate_federated_product;
pub(super) use final_revalidator::revalidate_federated_product_batch;
'''


def write_modules() -> None:
    base = "codex-rs/hepta-memory/src/cognitive_runtime_federation"
    write(f"{base}/mod.rs", module_source())
    write(f"{base}/planner.rs", planner_source())
    write(f"{base}/discovery.rs", discovery_source())
    write(f"{base}/attempt.rs", attempt_source())
    write(f"{base}/aggregator.rs", aggregator_source())
    write(f"{base}/final_revalidator.rs", final_revalidator_source())
    write(f"{base}/evidence.rs", evidence_source())
    write(f"{base}/telemetry.rs", telemetry_source())


def patch_runtime_parent() -> None:
    path = "codex-rs/hepta-memory/src/cognitive_runtime.rs"
    text = read(path)
    start = text.index("async fn retrieve_federated_product(")
    end = text.index("impl fmt::Debug for CognitiveRuntime", start)
    text = text[:start] + text[end:]

    imports_end = text.index("#[path = \"cognitive_runtime_identity.rs\"]")
    imports = r'''use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory_federation::FederatedCoverageV2;
use codex_hepta_memory_federation::FederatedFailureCoverageV2;
use codex_hepta_paths::HeptaAgentLayout;

use crate::CognitiveCompactError;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CompactCheckpoint;
use crate::CompactCommitDecision;
use crate::CompactLease;
use crate::CompactParentSnapshot;
use crate::FederatedMemoryRevalidationBinding;
use crate::FederatedRecallSet;
use crate::FederatedRetrievalBatch;
use crate::FederatedRevalidationStatus;
use crate::FederationConsumerAccess;
use crate::RehydrationPlan;
use crate::RetrievalRequest;

'''
    text = imports + text[imports_end:]
    identity = '#[path = "cognitive_runtime_identity.rs"]\nmod identity;'
    module = identity + r'''

#[path = "cognitive_runtime_federation/mod.rs"]
mod cognitive_runtime_federation;

pub use cognitive_runtime_federation::FederatedDiagnosticLedgerV2;
pub use cognitive_runtime_federation::FederatedPeerDiagnosticV2;
pub use cognitive_runtime_federation::FederatedProductReadV2;
pub use cognitive_runtime_federation::FederationCancellationEvidenceV2;
pub use cognitive_runtime_federation::FederationProductControl;
pub use cognitive_runtime_federation::FederationProductDispositionV2;
pub use cognitive_runtime_federation::FederationProductFailureV2;
pub use cognitive_runtime_federation::FederationProductPhaseV2;
pub use cognitive_runtime_federation::MAX_FEDERATION_DIAGNOSTICS_V2;
use cognitive_runtime_federation::retrieve_federated_product;
use cognitive_runtime_federation::retrieve_federated_product_with_control;
use cognitive_runtime_federation::revalidate_federated_product;
use cognitive_runtime_federation::revalidate_federated_product_batch;

const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;'''
    text = replace_once(text, identity, module, "runtime module declaration")

    marker = "    /// Revalidates a product attachment only through canonical V2 composition.\n"
    method = r'''    /// Executes the canonical V2 product path with an explicit product-owned
    /// cancellation source and returns bounded diagnostic evidence.
    pub async fn retrieve_product_federated_with_control(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
        control: &FederationProductControl,
    ) -> Result<FederatedProductReadV2, CognitiveStoreError> {
        match self {
            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                omitted_owner_candidates,
                ..
            } => {
                retrieve_federated_product_with_control(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *omitted_owner_candidates,
                    access,
                    request,
                    control,
                )
                .await
            }
            Self::Absent
            | Self::Available(_)
            | Self::AvailableFederated { .. }
            | Self::Unavailable(_) => Err(CognitiveStoreError::AccessDenied(
                "canonical memory federation V2 is unavailable".to_string(),
            )),
        }
    }

'''
    text = replace_once(text, marker, method + marker, "controlled product API")
    write(path, text)


def patch_memory_lib() -> None:
    path = "codex-rs/hepta-memory/src/lib.rs"
    text = read(path)
    marker = "pub use cognitive_runtime::CognitiveUnavailableReason;"
    addition = marker + r'''
pub use cognitive_runtime::FederatedDiagnosticLedgerV2;
pub use cognitive_runtime::FederatedPeerDiagnosticV2;
pub use cognitive_runtime::FederatedProductReadV2;
pub use cognitive_runtime::FederationCancellationEvidenceV2;
pub use cognitive_runtime::FederationProductControl;
pub use cognitive_runtime::FederationProductDispositionV2;
pub use cognitive_runtime::FederationProductFailureV2;
pub use cognitive_runtime::FederationProductPhaseV2;
pub use cognitive_runtime::MAX_FEDERATION_DIAGNOSTICS_V2;'''
    text = replace_once(text, marker, addition, "memory runtime public exports")
    write(path, text)


def patch_extension() -> None:
    path = "codex-rs/ext/hepta-memory/src/cognitive/federation.rs"
    text = read(path)
    text = replace_once(
        text,
        "use codex_hepta_memory::FederatedMemoryExplanation;",
        "use codex_hepta_memory::FederatedDiagnosticLedgerV2;\nuse codex_hepta_memory::FederatedMemoryExplanation;\nuse codex_hepta_memory::FederatedProductReadV2;\nuse codex_hepta_memory::FederationProductControl;",
        "extension product imports",
    )
    text = replace_once(
        text,
        "    claimed_token_count: u32,\n}",
        "    claimed_token_count: u32,\n    diagnostics_sha256: Sha256Digest,\n}",
        "prepared diagnostics binding",
    )
    guard_marker = "struct FederatedFinalUseGuard {\n"
    guard = r'''struct CancelFederationOnDrop {
    control: Option<FederationProductControl>,
}

impl CancelFederationOnDrop {
    fn new(control: FederationProductControl) -> Self {
        Self {
            control: Some(control),
        }
    }

    fn disarm(&mut self) {
        self.control = None;
    }
}

impl Drop for CancelFederationOnDrop {
    fn drop(&mut self) {
        if let Some(control) = self.control.take() {
            control.cancel();
        }
    }
}

'''
    text = replace_once(text, guard_marker, guard + guard_marker, "extension cancellation guard")

    old_retrieve = r'''    async fn retrieve(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<(FederatedRetrievalBatch, FederatedAttachmentCoverage), CognitiveStoreError> {
        let (batch, coverage) = self
            .runtime
            .retrieve_product_federated(access, request)
            .await?;
        Ok((batch, FederatedAttachmentCoverage::from(&coverage)))
    }
'''
    new_retrieve = r'''    async fn retrieve(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
        control: &FederationProductControl,
    ) -> Result<FederatedProductReadV2, CognitiveStoreError> {
        self.runtime
            .retrieve_product_federated_with_control(access, request, control)
            .await
    }
'''
    text = replace_once(text, old_retrieve, new_retrieve, "extension controlled retrieve")

    old_prepared_binding = r'''        let source_binding_sha256 = federation_source_binding(
            input.thread_id,
            input.turn_id,
            input.cwd,
            &prepared.query_sha256,
            &prepared.coverage,
            &prepared.bindings,
            &content_sha256,
        )?;'''
    new_prepared_binding = r'''        let source_binding_sha256 = federation_source_binding_with_diagnostics(
            input.thread_id,
            input.turn_id,
            input.cwd,
            &prepared.query_sha256,
            &prepared.coverage,
            &prepared.bindings,
            &prepared.diagnostics_sha256,
            &content_sha256,
        )?;'''
    text = replace_once(text, old_prepared_binding, new_prepared_binding, "prepared diagnostic rebind")

    text = replace_once(
        text,
        "            turn_store.remove::<PreparedFederatedAttachment>();",
        "            turn_store.remove::<PreparedFederatedAttachment>();\n            turn_store.remove::<FederationProductControl>();\n            turn_store.remove::<FederatedDiagnosticLedgerV2>();",
        "turn product evidence reset",
    )
    old_call = r'''            let Ok((batch, coverage)) = self
                .retrieve(&access, &RetrievalRequest::new(query, now))
                .await
            else {
                return Vec::new();
            };'''
    new_call = r'''            let control = FederationProductControl::new();
            turn_store.insert(control.clone());
            let mut cancel_on_drop = CancelFederationOnDrop::new(control.clone());
            let retrieval = self
                .retrieve(&access, &RetrievalRequest::new(query, now), &control)
                .await;
            cancel_on_drop.disarm();
            let Ok(read) = retrieval else {
                return Vec::new();
            };
            let diagnostics_sha256 = match read.diagnostics.binding_sha256() {
                Ok(digest) => digest,
                Err(_) => return Vec::new(),
            };
            turn_store.insert(read.diagnostics.clone());
            let batch = read.batch;
            let coverage = FederatedAttachmentCoverage::from(&read.coverage);'''
    text = replace_once(text, old_call, new_call, "turn controlled retrieval")

    old_source_call = r'''            let Some(source_binding_sha256) = federation_source_binding(
                thread_store.level_id(),
                input.turn_id.as_str(),
                workspace.as_path(),
                &batch.query_sha256,
                &coverage,
                &bindings,
                &content_sha256,
            ) else {'''
    new_source_call = r'''            let Some(source_binding_sha256) = federation_source_binding_with_diagnostics(
                thread_store.level_id(),
                input.turn_id.as_str(),
                workspace.as_path(),
                &batch.query_sha256,
                &coverage,
                &bindings,
                &diagnostics_sha256,
                &content_sha256,
            ) else {'''
    text = replace_once(text, old_source_call, new_source_call, "turn diagnostics binding")
    text = replace_once(
        text,
        "                claimed_token_count,\n            });",
        "                claimed_token_count,\n                diagnostics_sha256,\n            });",
        "prepared diagnostic field",
    )

    old_function = r'''fn federation_source_binding(
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
    query_sha256: &Sha256Digest,
    coverage: &FederatedAttachmentCoverage,
    bindings: &[FederatedMemoryRevalidationBinding],
    content_sha256: &Sha256Digest,
) -> Option<Sha256Digest> {
    let serialized = serde_json::to_vec(bindings).ok()?;
    let serialized_coverage = serde_json::to_vec(coverage).ok()?;
    Some(digest_many(
        b"hepta:cognitive:federated-ephemeral-source-binding:v2",
        &[
            thread_id.as_bytes(),
            turn_id.as_bytes(),
            path_identity_bytes(workspace).as_slice(),
            query_sha256.as_str().as_bytes(),
            serialized_coverage.as_slice(),
            serialized.as_slice(),
            content_sha256.as_str().as_bytes(),
        ],
    ))
}'''
    new_function = r'''fn federation_source_binding(
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
    query_sha256: &Sha256Digest,
    coverage: &FederatedAttachmentCoverage,
    bindings: &[FederatedMemoryRevalidationBinding],
    content_sha256: &Sha256Digest,
) -> Option<Sha256Digest> {
    let empty_diagnostics = Sha256Digest::for_bytes(b"memory-federation-no-diagnostics");
    federation_source_binding_with_diagnostics(
        thread_id,
        turn_id,
        workspace,
        query_sha256,
        coverage,
        bindings,
        &empty_diagnostics,
        content_sha256,
    )
}

fn federation_source_binding_with_diagnostics(
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
    query_sha256: &Sha256Digest,
    coverage: &FederatedAttachmentCoverage,
    bindings: &[FederatedMemoryRevalidationBinding],
    diagnostics_sha256: &Sha256Digest,
    content_sha256: &Sha256Digest,
) -> Option<Sha256Digest> {
    let serialized = serde_json::to_vec(bindings).ok()?;
    let serialized_coverage = serde_json::to_vec(coverage).ok()?;
    Some(digest_many(
        b"hepta:cognitive:federated-ephemeral-source-binding:v3",
        &[
            thread_id.as_bytes(),
            turn_id.as_bytes(),
            path_identity_bytes(workspace).as_slice(),
            query_sha256.as_str().as_bytes(),
            serialized_coverage.as_slice(),
            serialized.as_slice(),
            diagnostics_sha256.as_str().as_bytes(),
            content_sha256.as_str().as_bytes(),
        ],
    ))
}'''
    text = replace_once(text, old_function, new_function, "diagnostic source binding function")
    write(path, text)


def patch_legacy_allow() -> None:
    path = "codex-rs/hepta-memory-federation/src/legacy.rs"
    text = read(path)
    if "#![allow(deprecated)]" not in text:
        text = text.replace(
            "//! Feature-gated compatibility surface for the original federation receipt.\n",
            "//! Feature-gated compatibility surface for the original federation receipt.\n\n#![allow(deprecated)]\n",
            1,
        )
    write(path, text)


def main() -> None:
    reset_from_main(
        [
            "codex-rs/hepta-memory/Cargo.toml",
            "codex-rs/hepta-memory/src/cognitive_federation.rs",
            "codex-rs/hepta-memory/src/cognitive_runtime.rs",
            "codex-rs/hepta-memory/src/lib.rs",
            "codex-rs/ext/hepta-memory/Cargo.toml",
            "codex-rs/ext/hepta-memory/src/cognitive/federation.rs",
        ]
    )
    generated = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime_federation"
    if generated.exists():
        shutil.rmtree(generated)
    patch_memory_cargo()
    patch_extension_cargo()
    patch_revalidation_drift()
    write_modules()
    patch_runtime_parent()
    patch_memory_lib()
    patch_extension()
    patch_legacy_allow()
    print("memory.federation product runtime closure applied")


if __name__ == "__main__":
    main()
