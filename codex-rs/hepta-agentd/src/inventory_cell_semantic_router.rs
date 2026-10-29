//! Optional semantic resolver using one shared, prewarmed node encoder session.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellRequestV1, InventoryCellRouteV1};
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_memory::InventoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use crate::{InventoryCellAddressResolverV1, InventoryCellResolvedAddressV1, InventoryCellSemanticHeadV1};
use crate::{InventoryCellEncoderWorkerV1, InventoryCellEncoderWorkerMetricsV1};

/// Share the same `Arc<InventoryCellEncoderWorkerV1>` among the node's resolvers;
/// small head artifacts do not create another ONNX process or session.
pub struct InventoryCellSemanticRouterV1 {
    head: InventoryCellSemanticHeadV1,
    encoder: Arc<InventoryCellEncoderWorkerV1>,
}

impl InventoryCellSemanticRouterV1 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32, encoder: Arc<InventoryCellEncoderWorkerV1>) -> Result<Self, String> {
        let head = InventoryCellSemanticHeadV1::from_bytes(bytes, expected)?;
        if head.encoder_digest() != encoder.encoder_digest() { return Err("semantic router and shared encoder differ".to_string()); }
        Ok(Self { head, encoder })
    }

    pub fn encoder_metrics(&self) -> InventoryCellEncoderWorkerMetricsV1 { self.encoder.metrics() }

    pub async fn route_text(&self, text: &str) -> Result<Option<InventoryCellRouteV1>, String> {
        if !self.head.has_valid_addresses(text) { return Ok(None); }
        let Some(features) = self.encoder.encode(text).await? else { return Ok(None); };
        self.head.route_features(text, &features)
    }
}

impl InventoryCellAddressResolverV1 for InventoryCellSemanticRouterV1 {
    fn model_digest(&self) -> ContractDigestV1 { self.head.model_digest() }
    fn resolve<'a>(&'a self, request: &'a InventoryCellRequestV1, snapshot: &'a InventoryCellOwnerSnapshotV1) -> Pin<Box<dyn Future<Output = Result<Option<InventoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let Some(route) = self.route_text(&request.text).await? else { return Ok(None); };
            if route.entity.as_ref().is_some_and(|key| snapshot.current(key, InventoryCellKindV1::Semantic).is_none())
                || route.workflow.as_ref().is_some_and(|key| snapshot.current(key, InventoryCellKindV1::Skill).is_none())
            { return Ok(None); }
            Ok(Some(InventoryCellResolvedAddressV1 { request: request.clone(), route,
                owner_cut_digest: snapshot.owner_cut_digest(), model_digest: self.head.model_digest() }))
        })
    }
}
