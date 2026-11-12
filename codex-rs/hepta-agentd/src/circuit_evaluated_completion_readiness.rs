//! Independent readiness for the actual evaluated-retention C task.
//! An original five-cut S result narrows this read-only held connection.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Channel;
use super::Error;
use super::OriginalCircuitEvaluatedLearningReadContextV1;
use super::OriginalCircuitLearningReadbackV1 as Readback;
use super::now;
use super::profile::ReadProfile;
use super::wire;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;

const PURPOSE: &str = "runtime.learning.original-circuit.evaluated-completion-readiness.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    purpose: String,
    original: wire::Request,
}

impl Request {
    pub(super) fn new(
        context: &ReadProfile,
        binding: Digest32,
        request_id: u64,
    ) -> Result<Self, Error> {
        require_evaluated_next_use(context)?;
        Ok(Self {
            purpose: PURPOSE.into(),
            original: context.request(binding, request_id)?,
        })
    }

    pub(super) fn require_context(
        &self,
        context: &ReadProfile,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        require_evaluated_next_use(context)?;
        if self.purpose != PURPOSE || !(1..=128).contains(&request_id) {
            return Err(Error::Binding(
                "fixed evaluated completion-readiness purpose",
            ));
        }
        context.require_request(&self.original, binding, request_id)
    }
}

pub(super) fn require_evaluated_next_use(context: &ReadProfile) -> Result<(), Error> {
    if !matches!(context, ReadProfile::Evaluated(_)) || context.mode()? != wire::Mode::NextUse {
        return Err(Error::Binding(
            "evaluated readiness requires original five-cut Selection",
        ));
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request: Request,
    pub result: Readiness,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Readiness {
    NotReady,
    Ready { read: wire::OriginalRead },
}

/// Only actual D and opaque original S bind the already-held ordinary stream.
/// No deadline, role identity, signature, CURRENT or execution is produced here.
pub(crate) struct OriginalCircuitEvaluatedCompletionReadinessClientV1 {
    context: ReadProfile,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    binding: Digest32,
    channel: Mutex<Option<Channel>>,
    retained: Mutex<Option<Readback>>,
}

impl OriginalCircuitEvaluatedCompletionReadinessClientV1 {
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        let started = now()?;
        let (scope, verifier, _) = selection.original_context().receipt_configuration();
        if scope != material.scope
            || verifier.trust_digest() != material.verifier.trust_digest()
            || verifier.scope_digest() != material.verifier.scope_digest()
            || verifier.objective_digest() != material.verifier.objective_digest()
        {
            return Err(Error::Binding(
                "same original evaluated Material scope and verifier",
            ));
        }
        let context = ReadProfile::Evaluated(
            OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(
                selection.clone(),
            )?,
        );
        require_evaluated_next_use(&context)?;
        let binding = context.binding(started)?;
        let prefix = context.prefix();
        let initial =
            LearningIterationCoordinatorV1::new(prefix.request.clone(), prefix.owners.clone())?;
        let mut original_dataset = prefix.clone();
        original_dataset.head_digest = original_dataset.receipts[2].predecessor;
        original_dataset.receipts.truncate(2);
        if initial.snapshot() != &material.initial || &original_dataset != dataset.snapshot() {
            return Err(Error::Binding(
                "same initial and original Dataset before evaluated readiness",
            ));
        }
        peer.check_peer_lifetime()?;
        let owner = Self {
            context,
            material: material.clone(),
            dataset: dataset.clone(),
            binding,
            channel: Mutex::new(Some(Channel {
                peer,
                next_request_id: 1,
            })),
            retained: Mutex::new(None),
        };
        owner.require_current_context(started)?;
        Ok(owner)
    }

    fn require_current_context(&self, started: u64) -> Result<(), Error> {
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &self.dataset,
            &self.material,
        )
        .map_err(|_| Error::Binding("same original Material evaluated readiness context"))?;
        if fresh < started || self.context.binding(fresh)? != self.binding {
            return Err(Error::Binding(
                "original evaluated readiness signatures and clock",
            ));
        }
        Ok(())
    }

    /// Authenticated Missing/Pending or the unchanged completed result retains
    /// the channel. Invalid, cancelled or regressing results consume it.
    pub(crate) async fn read_current(&self) -> Result<Option<Readback>, Error> {
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started = now()?;
        self.require_current_context(started)?;
        if !(1..=128).contains(&channel.next_request_id) {
            return Err(Error::Binding(
                "bounded original evaluated readiness connection",
            ));
        }
        let request_id = channel.next_request_id;
        let request = Request::new(&self.context, self.binding, request_id)?;
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let bytes = serde_json::to_vec(&request)?;
        let queued = QueuedReadFence(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let (channel, response) = tokio::task::spawn_blocking(move || {
            if cancelled.load(Ordering::Acquire) {
                return Err(Error::Unavailable);
            }
            let response = channel.peer.request(&bytes)?;
            Ok::<_, Error>((channel, response))
        })
        .await
        .map_err(|_| Error::Unavailable)??;
        drop(queued);
        let response: Response = serde_json::from_slice(&response)?;
        response
            .request
            .require_context(&self.context, self.binding, request_id)?;
        let current = match response.result {
            Readiness::NotReady => None,
            Readiness::Ready { read } => Some(self.context.decode(read)?),
        };
        channel.peer.check_peer_lifetime()?;
        self.require_current_context(started)?;
        {
            let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
            if retained
                .as_ref()
                .is_some_and(|prior| current.as_ref() != Some(prior))
            {
                return Err(Error::Binding(
                    "completed evaluated C cannot change or become pending",
                ));
            }
            if let Some(ready) = &current {
                *retained = Some(ready.clone());
            }
        }
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        Ok(current)
    }
}

struct QueuedReadFence(Arc<AtomicBool>);
impl Drop for QueuedReadFence {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

impl Readback {
    /// Compare the actual remote Selection read with Version's opaque physical
    /// publication. This exposes no Source digest getter or reusable lease.
    pub(crate) fn require_original_evaluated_version_selection(
        &self,
        version: &crate::OriginalCircuitRetainedVersionPublicationV1,
    ) -> Result<(), Error> {
        if self.publication != version.publication_digest()
            || self.source_input != version.task_digest()
            || self.source_publication.is_some()
            || self.observation
                != (codex_hepta_learning_artifacts::LearningIterationObservationV1::Selection {
                    candidate_bundle: version.bundle_digest(),
                    selection_digest: version.selection_digest(),
                })
        {
            return Err(Error::Binding(
                "same actual evaluated Version Source and Cell publication",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "circuit_evaluated_readiness_support_tests.rs"]
pub(crate) mod fixture;
