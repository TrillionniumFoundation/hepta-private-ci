//! Readonly serving from the consumed original host. Owner locks are released
//! before any response write; no cached page is accepted as a completed read.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_types::Digest32;

use super::Error;
use super::MAX_BYTES;
use super::MAX_PAGES;
use super::PAGE_BYTES;
use super::codec::Body;
use super::wire;
use super::super::OriginalCellEvaluationHostV1;
use crate::AgentdRootAuthorityPeer;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

struct Transfer { id: u64, bytes: Vec<u8>, digest: Digest32, next_page: usize, context: Digest32 }

impl OriginalCellEvaluationHostV1 {
    pub async fn serve_model_material(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
            )?;
            self.serve_model_material_channel(&mut channel)
        }).await.map_err(|_| Error::CommitUncertain)?
    }

    fn serve_model_material_channel(&self, channel: &mut HostAuthorityPeerChannel) -> Result<u64, Error> {
        let mut transfer = None;
        let mut retained = None;
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.model_material_response(bytes, request_id, &mut transfer, &mut retained)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? { return Ok(request_id - 1); }
        }
        Err(Error::Unavailable)
    }

    fn model_material_response(
        &self, bytes: &[u8], request_id: u64,
        transfer: &mut Option<Transfer>, retained: &mut Option<Digest32>,
    ) -> Result<Vec<u8>, Error> {
        if bytes.len() > 16_384 { return Err(Error::Binding("bounded original material request")); }
        let request: wire::Request = serde_json::from_slice(bytes)?;
        let context = wire::context_binding(&self.context, super::super::now()?)?;
        request.require(request_id, context)?;
        let outcome = match &request.read {
            wire::Read::Begin => {
                if transfer.is_some() { return Err(Error::Binding("one original transfer in progress")); }
                let bytes = match self.read_original_model_material() {
                    Ok(bytes) => bytes,
                    Err(error) => {
                        use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as Journal;
                        use crate::OriginalCellEvaluationReceiptErrorV1 as Receipt;
                        use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1 as Store;
                        let outcome = match error {
                            Error::Receipt(Receipt::Owner(Journal::Pending)) => wire::Outcome::Pending,
                            Error::Receipt(Receipt::Owner(Journal::Store(Store::Missing))) => wire::Outcome::Missing,
                            Error::Busy => wire::Outcome::Busy,
                            _ => wire::Outcome::Uncertain,
                        };
                        self.context.authenticate(super::super::now()?)?;
                        return serde_json::to_vec(&wire::Response { request, outcome }).map_err(Error::from);
                    }
                };
                let _body = Body::decode(&bytes)?;
                let digest = Digest32::of_bytes(&bytes);
                if retained.is_some_and(|previous| previous != digest)
                    || bytes.is_empty() || bytes.len() > MAX_BYTES
                    || bytes.len().div_ceil(PAGE_BYTES) > MAX_PAGES
                { return Err(Error::CommitUncertain); }
                let active = Transfer { id: request_id, bytes, digest, next_page: 0, context };
                *transfer = Some(active);
                page(transfer.as_mut().ok_or(Error::CommitUncertain)?, /*index*/ 0)?
            }
            wire::Read::Page { transfer: id, index } => {
                let active = transfer.as_mut().ok_or(Error::Binding("original transfer is missing"))?;
                if active.id != *id || active.context != context { return Err(Error::CommitUncertain); }
                page(active, *index as usize)?
            }
            wire::Read::Finish { transfer: id, digest } => {
                let active = transfer.take().ok_or(Error::Binding("original transfer is missing"))?;
                if active.id != *id || active.context != context || digest != &active.digest.to_string()
                    || active.next_page != active.bytes.len().div_ceil(PAGE_BYTES)
                { return Err(Error::CommitUncertain); }
                // This actual second read brackets the entire transfer. A
                // withdrawal, changed byte/window, missing result or failed
                // read closes this session instead of granting a partial cap.
                if self.read_original_model_material()? != active.bytes {
                    return Err(Error::CommitUncertain);
                }
                *retained = Some(active.digest);
                wire::Outcome::Completed { transfer: *id, total: active.bytes.len(), digest: active.digest.to_string() }
            }
        };
        self.context.authenticate(super::super::now()?)?;
        let encoded = serde_json::to_vec(&wire::Response { request, outcome })?;
        if encoded.len() > 16_384 { return Err(Error::Binding("bounded original material response")); }
        Ok(encoded)
    }

    fn read_original_model_material(&self) -> Result<Vec<u8>, Error> {
        let result = {
            let mut owners = self.owners.try_lock().map_err(|_| Error::Busy)?;
            self.runtime.block_on(owners.original_model_material(&self.context))
        };
        // No owner, Source, ledger or Trainer lock survives the wire write.
        result
    }
}

fn page(active: &mut Transfer, index: usize) -> Result<wire::Outcome, Error> {
    if index != active.next_page || index >= MAX_PAGES { return Err(Error::Binding("ordered original material pages")); }
    let offset = index.checked_mul(PAGE_BYTES).ok_or(Error::CommitUncertain)?;
    if offset >= active.bytes.len() { return Err(Error::Binding("original material page boundary")); }
    let end = offset.saturating_add(PAGE_BYTES).min(active.bytes.len());
    let bytes = STANDARD_NO_PAD.encode(&active.bytes[offset..end]);
    active.next_page += 1;
    Ok(wire::Outcome::Page { transfer: active.id, index: index as u32, offset,
        total: active.bytes.len(), digest: active.digest.to_string(), bytes })
}
