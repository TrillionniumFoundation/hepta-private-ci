//! Inventory addressing uses the existing pinned child, bounded pipes and
//! cancellation behavior. Only the typed request/decision profile differs.

use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_cognitive_store::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;

use crate::MemoryInventoryAddressResolverV1;
use crate::MemoryInventoryResolvedAddressV1;
use super::{ElapsedCounter, MemoryCellAddressWorkerConfigV1, MemoryCellAddressWorkerMetricsV1, MemoryCellAddressWorkerV1, WireProfile};
use super::inventory_wire::BoundInventoryRequest;

pub struct MemoryInventoryAddressWorkerV1 {
    worker: MemoryCellAddressWorkerV1,
}

impl MemoryInventoryAddressWorkerV1 {
    pub async fn start(config: MemoryCellAddressWorkerConfigV1) -> Result<Self, String> {
        Ok(Self { worker: MemoryCellAddressWorkerV1::start_profile(config, WireProfile::Inventory).await? })
    }

    pub fn metrics(&self) -> MemoryCellAddressWorkerMetricsV1 { self.worker.metrics() }

    pub async fn take_last_validated_response(&self) -> Option<Vec<u8>> {
        self.worker.take_last_validated_response().await
    }
}

impl MemoryInventoryAddressResolverV1 for MemoryInventoryAddressWorkerV1 {
    fn model_digest(&self) -> ContractDigestV1 { self.worker.config.model_digest }

    fn resolve<'a>(
        &'a self,
        request: &'a MemoryInventoryRequestV1,
        snapshot: &'a MemoryInventoryOwnerSnapshotV1,
    ) -> Pin<Box<dyn Future<Output = Result<Option<MemoryInventoryResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let worker = &self.worker;
            let _elapsed = ElapsedCounter { counter: &worker.counters.host, started: Instant::now() };
            worker.counters.attempts.fetch_add(1, Ordering::Relaxed);
            let bound = BoundInventoryRequest::build(request, snapshot, &worker.config.aliases)?;
            tokio::time::timeout(worker.config.request_timeout, worker.exchange(&bound.bytes, |response| {
                bound.validate_response(response, worker.config.model_digest, request)
            })).await.map_err(|_| "inventory address worker request timed out".to_string())?
        })
    }
}
