//! One private original material transfer. Only its actual T before/after
//! reads are shared; every export rereads the complete physical B/retention
//! panel and E journal. No native lane or owner lock survives a response write.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_types::Digest32;

use super::super::OriginalCellEvaluationHostV1;
use super::super::TrainingOperation;
use super::Error;
use super::MAX_BYTES;
use super::MAX_PAGES;
use super::OriginalCellEvaluationModelMaterialV1;
use super::PAGE_BYTES;
use super::codec::Body;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

// Paging metadata alone has no way to complete or restore an original owner.
struct Transfer {
    id: u64,
    bytes: Vec<u8>,
    digest: Digest32,
    next_page: usize,
    context: Digest32,
}
struct Active {
    pages: Transfer,
    training: Option<TrainingOperation>,
}
// Non-Clone, non-Deserialize and borrowed from this exact original host. The
// real Training operation stays private to this one original peer invocation.
struct Session<'a> {
    host: &'a OriginalCellEvaluationHostV1,
    active: Option<Active>,
    completed: Option<OriginalCellEvaluationModelMaterialV1>,
    retained: Option<Digest32>,
}
impl<'a> Session<'a> {
    fn new(host: &'a OriginalCellEvaluationHostV1) -> Self {
        Self { host, active: None, completed: None, retained: None }
    }
}

struct Queued(Arc<AtomicBool>);
impl Drop for Queued {
    fn drop(&mut self) { self.0.store(true, Ordering::Release); }
}
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
    Ok(())
}

impl OriginalCellEvaluationHostV1 {
    pub async fn serve_model_material(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        // Pin the actual original peer and absolute deadline before queueing.
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        let queued = Queued(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            require_not_cancelled(&cancelled)?;
            self.serve_model_material_channel(&mut channel, &cancelled)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    fn serve_model_material_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
        cancelled: &AtomicBool,
    ) -> Result<u64, Error> {
        let mut session = Session::new(self);
        for request_id in 1..=128_u64 {
            require_not_cancelled(cancelled)?;
            if !channel.exchange(|bytes| {
                self.model_material_response(bytes, request_id, &mut session, cancelled)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                // An absent Finish never restores the fenced original Owners.
                if session.active.is_some() || session.completed.is_some() {
                    return Err(Error::CommitUncertain);
                }
                return Ok(request_id - 1);
            }
            channel.check_peer_lifetime()?;
            require_not_cancelled(cancelled)?;
            self.finish_model_material_response(&mut session)?;
        }
        Err(Error::Unavailable)
    }

    fn model_material_response(
        &self,
        bytes: &[u8],
        request_id: u64,
        session: &mut Session<'_>,
        cancelled: &AtomicBool,
    ) -> Result<Vec<u8>, Error> {
        require_not_cancelled(cancelled)?;
        if !std::ptr::eq(self, session.host) || session.completed.is_some() {
            return Err(Error::CommitUncertain);
        }
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded original material request"));
        }
        let request: wire::Request = serde_json::from_slice(bytes)?;
        let context = wire::context_binding(&self.context, super::super::now()?)?;
        request.require(request_id, context)?;
        let outcome = match &request.read {
            wire::Read::Begin => {
                if session.active.is_some() {
                    return Err(Error::Binding("one original transfer in progress"));
                }
                let (bytes, training) = match self.begin_original_model_material_transfer() {
                    Ok(original) => original,
                    Err(error) => {
                        use crate::OriginalCellEvaluationReceiptErrorV1 as Receipt;
                        use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as Journal;
                        use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1 as Store;
                        let outcome = match error {
                            Error::Receipt(Receipt::Owner(Journal::Pending)) => wire::Outcome::Pending,
                            Error::Receipt(Receipt::Owner(Journal::Store(Store::Missing))) => wire::Outcome::Missing,
                            Error::Busy => wire::Outcome::Busy,
                            _ => wire::Outcome::Uncertain,
                        };
                        self.context.authenticate(super::super::now()?)?;
                        require_not_cancelled(cancelled)?;
                        return encode_response(request, outcome);
                    }
                };
                let _body = Body::decode(&bytes)?;
                let digest = Digest32::of_bytes(&bytes);
                let pages = bytes.len().div_ceil(PAGE_BYTES);
                if session.retained.is_some_and(|previous| previous != digest)
                    || bytes.is_empty() || bytes.len() > MAX_BYTES || pages > MAX_PAGES
                    || request_id.checked_add(pages as u64).is_none_or(|last| last > 128)
                {
                    return Err(Error::CommitUncertain);
                }
                session.active = Some(Active {
                    pages: Transfer { id: request_id, bytes, digest, next_page: 0, context },
                    training,
                });
                page(&mut session.active.as_mut().ok_or(Error::CommitUncertain)?.pages, 0)?
            }
            wire::Read::Page { transfer: id, index } => {
                let active = session.active.as_mut()
                    .ok_or(Error::Binding("original transfer is missing"))?;
                if active.pages.id != *id || active.pages.context != context {
                    return Err(Error::CommitUncertain);
                }
                page(&mut active.pages, *index as usize)?
            }
            wire::Read::Finish { transfer: id, digest } => {
                let active = session.active.take()
                    .ok_or(Error::Binding("original transfer is missing"))?;
                let Active { pages, training } = active;
                if pages.id != *id || pages.context != context
                    || digest != &pages.digest.to_string()
                    || pages.next_page != pages.bytes.len().div_ceil(PAGE_BYTES)
                {
                    return Err(Error::CommitUncertain);
                }
                let completed = self.finish_original_model_material_transfer(training, &pages.bytes)?;
                // This entire body, including all original signatures and their
                // windows, must be byte-equal after actual Panel/T/E rereads.
                if completed.bytes != pages.bytes || completed.binding() != pages.digest {
                    return Err(Error::CommitUncertain);
                }
                session.completed = Some(completed);
                wire::Outcome::Completed {
                    transfer: *id, total: pages.bytes.len(), digest: pages.digest.to_string(),
                }
            }
        };
        self.context.authenticate(super::super::now()?)?;
        require_not_cancelled(cancelled)?;
        encode_response(request, outcome)
    }

    fn begin_original_model_material_transfer(
        &self,
    ) -> Result<(Vec<u8>, Option<TrainingOperation>), Error> {
        let mut owners = self.owners.try_lock().map_err(|_| Error::Busy)?;
        self.runtime.block_on(owners.begin_model_material_transfer(&self.context))
        // Owners stays fenced; the mutex is released before the wire write.
    }

    fn finish_original_model_material_transfer(
        &self,
        training: Option<TrainingOperation>,
        expected: &[u8],
    ) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        let mut owners = self.owners.try_lock().map_err(|_| Error::Busy)?;
        self.runtime.block_on(owners.finish_model_material_transfer(
            &self.context, training, expected,
        ))
        // Failed/cancelled Finish cannot clear the original fence.
    }

    fn finish_model_material_response(&self, session: &mut Session<'_>) -> Result<(), Error> {
        if !std::ptr::eq(self, session.host) { return Err(Error::CommitUncertain); }
        if let Some(completed) = session.completed.take() {
            let mut owners = self.owners.try_lock().map_err(|_| Error::Busy)?;
            if !owners.fenced { return Err(Error::CommitUncertain); }
            let current = owners.current_time()?;
            // The actual original peer write/pidfd check has also finished.
            // This is pure whole-body freshness, never another CURRENT cache.
            completed.authenticate_current(current)?;
            self.context.authenticate(current)?;
            session.retained = Some(completed.binding());
            owners.fenced = false;
        }
        Ok(())
    }
}

fn encode_response(request: wire::Request, outcome: wire::Outcome) -> Result<Vec<u8>, Error> {
    let encoded = serde_json::to_vec(&wire::Response { request, outcome })?;
    if encoded.is_empty() || encoded.len() > 16_384 {
        return Err(Error::Binding("bounded original material response"));
    }
    Ok(encoded)
}

fn page(active: &mut Transfer, index: usize) -> Result<wire::Outcome, Error> {
    if index != active.next_page || index >= MAX_PAGES {
        return Err(Error::Binding("ordered original material pages"));
    }
    let offset = index.checked_mul(PAGE_BYTES).ok_or(Error::CommitUncertain)?;
    if offset >= active.bytes.len() {
        return Err(Error::Binding("original material page boundary"));
    }
    let end = offset.saturating_add(PAGE_BYTES).min(active.bytes.len());
    let bytes = STANDARD_NO_PAD.encode(&active.bytes[offset..end]);
    active.next_page += 1;
    Ok(wire::Outcome::Page {
        transfer: active.id, index: index as u32, offset,
        total: active.bytes.len(), digest: active.digest.to_string(), bytes,
    })
}

#[cfg(test)]
#[path = "neuron_cell_evaluation_model_material_service_support_tests.rs"]
mod tests;
