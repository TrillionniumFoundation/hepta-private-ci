//! A separate read-only purpose for waiting on actual ordinary C completion.
//! NotReady includes unresolved work; it never licenses execution or retry.

use std::sync::Mutex;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Channel;
use super::Error;
use super::OriginalCircuitLearningReadContextV1 as Context;
use super::OriginalCircuitLearningReadbackV1 as Readback;
use super::now;
use super::profile::ReadProfile;
use super::OriginalCircuitEvaluatedLearningReadContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use super::wire as original;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;

const PURPOSE: &str = "runtime.learning.original-circuit.completion-readiness.v1";
const EVALUATED_PURPOSE: &str = "runtime.learning.original-circuit.evaluated-completion-readiness.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    purpose: String,
    original: original::Request,
}

impl Request {
    pub(super) fn new(
        context: &Context,
        binding: Digest32,
        request_id: u64,
    ) -> Result<Self, Error> {
        if original::mode(context)? != original::Mode::NextUse {
            return Err(Error::Binding("readiness requires original Selection"));
        }
        Ok(Self {
            purpose: PURPOSE.into(),
            original: original::Request::new(context, binding, request_id)?,
        })
    }

    pub(super) fn require_context(
        &self,
        context: &Context,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        if self.purpose != PURPOSE || original::mode(context)? != original::Mode::NextUse {
            return Err(Error::Binding("fixed completion-readiness purpose"));
        }
        self.original.require_context(context, binding, request_id)
    }

    pub(super) fn from_profile(
        context: &ReadProfile,
        binding: Digest32,
        request_id: u64,
    ) -> Result<Self, Error> {
        match context {
            ReadProfile::TrainingNoUpdate(legacy) => Self::new(legacy, binding, request_id),
            ReadProfile::Evaluated(_) => {
                if context.mode()? != original::Mode::NextUse {
                    return Err(Error::Binding("evaluated readiness requires original Selection"));
                }
                Ok(Self {
                    purpose: EVALUATED_PURPOSE.into(),
                    original: context.request(binding, request_id)?,
                })
            }
        }
    }

    pub(super) fn require_profile(
        &self,
        context: &ReadProfile,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        match context {
            ReadProfile::TrainingNoUpdate(legacy) => self.require_context(legacy, binding, request_id),
            ReadProfile::Evaluated(_) => {
                if self.purpose != EVALUATED_PURPOSE || context.mode()? != original::Mode::NextUse {
                    return Err(Error::Binding("fixed evaluated completion-readiness purpose"));
                }
                context.require_request(&self.original, binding, request_id)
            }
        }
    }
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
    Ready { read: original::OriginalRead },
}

/// Only the concrete ordinary assembly receives this read-only capability.
/// Its already-held channel is moved here after actual opaque D and S arrive.
pub(crate) struct OriginalCircuitCompletionReadinessClientV1 {
    context: ReadProfile,
    binding: Digest32,
    channel: Mutex<Option<Channel>>,
    retained: Mutex<Option<Readback>>,
}

impl OriginalCircuitCompletionReadinessClientV1 {
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitSelectionCommandReceiptV1,
    ) -> Result<Self, Error> {
        let context = Context {
            prefix: selection.snapshot().clone(),
            scope: material.scope.clone(),
            verifier: material.verifier.clone(),
            training_evidence: selection.training_attestation().clone(),
            selection_evidence: Some(selection.attestation().clone()),
        };
        Self::bind_profile(peer, material, dataset, ReadProfile::TrainingNoUpdate(context))
    }

    pub(crate) fn bind_original_evaluated_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        let (scope, verifier, _) = selection.original_context().receipt_configuration();
        if scope != material.scope
            || verifier.trust_digest() != material.verifier.trust_digest()
            || verifier.scope_digest() != material.verifier.scope_digest()
            || verifier.objective_digest() != material.verifier.objective_digest()
        {
            return Err(Error::Binding("same original evaluated Material readiness context"));
        }
        let context = OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(selection.clone())?;
        Self::bind_profile(peer, material, dataset, ReadProfile::Evaluated(context))
    }

    fn bind_profile(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        context: ReadProfile,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        if context.mode()? != original::Mode::NextUse {
            return Err(Error::Binding("completion readiness requires original Selection"));
        }
        let initial = LearningIterationCoordinatorV1::new(
            context.prefix().request.clone(),
            context.prefix().owners.clone(),
        )?;
        let mut original_dataset = context.prefix().clone();
        original_dataset.head_digest = original_dataset.receipts[2].predecessor;
        original_dataset.receipts.truncate(2);
        if initial.snapshot() != &material.initial || &original_dataset != dataset.snapshot() {
            return Err(Error::Binding(
                "same initial and original Dataset before readiness",
            ));
        }
        peer.check_peer_lifetime()?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )
        .map_err(|_| Error::Binding("same original Material readiness context"))?;
        if fresh < started_at || context.binding(fresh)? != binding {
            return Err(Error::Binding("original readiness binding and clock"));
        }
        Ok(Self {
            context,
            binding,
            channel: Mutex::new(Some(Channel {
                peer,
                next_request_id: 1,
            })),
            retained: Mutex::new(None),
        })
    }

    /// Each poll reads the original task host. Only an authenticated NotReady
    /// reply retains the connection; every uncertain/invalid exchange consumes it.
    pub(crate) async fn read_current(&self) -> Result<Option<Readback>, Error> {
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started_at = now()?;
        if self.context.binding(started_at)? != self.binding
            || !(1..=128).contains(&channel.next_request_id)
        {
            return Err(Error::Binding("same bounded readiness connection"));
        }
        let request_id = channel.next_request_id;
        let request = Request::from_profile(&self.context, self.binding, request_id)?;
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let bytes = serde_json::to_vec(&request)?;
        let (channel, response) = tokio::task::spawn_blocking(move || {
            let response = channel.peer.request(&bytes)?;
            Ok::<_, Error>((channel, response))
        })
        .await
        .map_err(|_| Error::Unavailable)??;
        let response: Response = serde_json::from_slice(&response)?;
        response
            .request
            .require_profile(&self.context, self.binding, request_id)?;
        let current = match response.result {
            Readiness::NotReady => None,
            Readiness::Ready { read } => Some(self.context.decode(read)?),
        };
        channel.peer.check_peer_lifetime()?;
        let fresh = now()?;
        if fresh < started_at || self.context.binding(fresh)? != self.binding {
            return Err(Error::Binding("readiness clock after original peer I/O"));
        }
        {
            let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
            if retained
                .as_ref()
                .is_some_and(|prior| current.as_ref() != Some(prior))
            {
                return Err(Error::Binding(
                    "completed original C cannot change or become pending",
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

#[cfg(test)]
#[path = "circuit_completion_readiness_support_tests.rs"]
pub(crate) mod fixture;

#[cfg(test)]
#[path = "circuit_evaluated_completion_readiness_support_tests.rs"]
pub(crate) mod evaluated_fixture;
