//! The private local backend of the original purpose-fixed read client.
//! It retains one concrete Version binding. There is no local peer/socket
//! substitute, callback, receipt deserializer or owner getter.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_types::Digest32;

use super::super::retained_publication::version::OriginalVersionLocalReadBindingV1;
use super::super::retained_publication::version::OriginalVersionLocalReadOperationV1 as LocalReadOperation;
use super::Error;
use super::OriginalCircuitEvaluatedLearningReadContextV1;
use super::OriginalCircuitLearningReadClientV1;
use super::OriginalCircuitLearningReadbackV1 as Readback;
use super::now;
use super::profile::ReadProfile;
use super::readiness;
use super::wire;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;

struct OriginalLocalReadSlot {
    next_request_id: u64,
    retained: Option<Readback>,
}

struct OriginalLocalReadState {
    original: OriginalVersionLocalReadBindingV1,
    context: ReadProfile,
    binding: Digest32,
    slot: Mutex<Option<OriginalLocalReadSlot>>,
    #[cfg(test)]
    probe: Mutex<Option<Arc<fixture::OriginalLocalReadProbeState>>>,
}

/// A sealed same-host capability created by an actual published Version.
/// Cloning retains the same permit, absolute end, counter and terminal slot.
pub struct OriginalCircuitPublishedLocalReadV1 {
    original: Arc<OriginalLocalReadState>,
}

impl Clone for OriginalCircuitPublishedLocalReadV1 {
    fn clone(&self) -> Self {
        Self {
            original: Arc::clone(&self.original),
        }
    }
}

impl OriginalCircuitPublishedLocalReadV1 {
    pub(crate) fn from_original_version(
        original: OriginalVersionLocalReadBindingV1,
    ) -> Result<Self, Error> {
        if Instant::now() >= original.original_end() {
            return Err(Error::Unavailable);
        }
        let context = ReadProfile::Evaluated(original.original_context());
        let binding = context.binding(now()?)?;
        Ok(Self {
            original: Arc::new(OriginalLocalReadState {
                original,
                context,
                binding,
                slot: Mutex::new(Some(OriginalLocalReadSlot {
                    next_request_id: 1,
                    retained: None,
                })),
                #[cfg(test)]
                probe: Mutex::new(None),
            }),
        })
    }

    fn require_original_selection(
        &self,
        expected: &OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<Instant, Error> {
        self.require_original_window()?;
        let ReadProfile::Evaluated(context) = &self.original.context else {
            return Err(Error::Binding("local evaluated Selection profile"));
        };
        context.require_original_selection(expected)?;
        Ok(self.original.original.original_end())
    }

    fn require_original_next_use(
        &self,
        expected: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Instant, Error> {
        self.require_original_window()?;
        let ReadProfile::Evaluated(context) = &self.original.context else {
            return Err(Error::Binding("local evaluated NextUse profile"));
        };
        context.require_original_next_use(expected)?;
        Ok(self.original.original.original_end())
    }

    fn require_original_window(&self) -> Result<(), Error> {
        if Instant::now() >= self.original.original.original_end()
            || self.original.context.binding(now()?)? != self.original.binding
        {
            return Err(Error::Unavailable);
        }
        Ok(())
    }

    pub(crate) async fn read_current(&self) -> Result<Readback, Error> {
        self.read_original(LocalReadOperation::Readback)
            .await?
            .ok_or(Error::Binding("original local readback is not pending"))
    }

    pub(crate) async fn read_completion_readiness(&self) -> Result<Option<Readback>, Error> {
        if self.original.context.mode()? != wire::Mode::NextUse {
            return Err(Error::Binding("local readiness requires original NextUse"));
        }
        self.read_original(LocalReadOperation::CompletionReadiness)
            .await
    }

    async fn read_original(
        &self,
        operation: LocalReadOperation,
    ) -> Result<Option<Readback>, Error> {
        // Taking the one slot precedes all fallible work. Only this awaiting
        // call can return it. Cancellation, error or timeout leaves it empty;
        // a detached blocking response can never repair or replenish it.
        let mut slot = self
            .original
            .slot
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        self.require_original_window()?;
        if !(1..=128).contains(&slot.next_request_id) {
            return Err(Error::Unavailable);
        }
        let started_at = now()?;
        let started = Instant::now();
        let deadline = started
            .checked_add(self.original.original.original_timeout())
            .ok_or(Error::Unavailable)?
            .min(self.original.original.original_end());
        if started >= deadline {
            return Err(Error::Unavailable);
        }
        let request_id = slot.next_request_id;
        slot.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let request = self
            .original
            .context
            .request(self.original.binding, request_id)?;
        let bytes = match operation {
            LocalReadOperation::Readback => serde_json::to_vec(&request)?,
            LocalReadOperation::CompletionReadiness => {
                serde_json::to_vec(&readiness::Request::from_profile(
                    &self.original.context,
                    self.original.binding,
                    request_id,
                )?)?
            }
        };
        let original = Arc::clone(&self.original);
        #[cfg(test)]
        let terminal = original.fixture_original_read_submitted()?;
        let worker = tokio::task::spawn_blocking(move || {
            #[cfg(test)]
            if let Some(terminal) = &terminal {
                terminal.mark_original_started();
            }
            let response = OriginalVersionLocalReadBindingV1::respond(
                &original.original,
                operation,
                &bytes,
                request_id,
            )
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())));
            #[cfg(test)]
            if response.is_ok() {
                if let Some(terminal) = &terminal {
                    terminal.pause_after_original_response(deadline)?;
                }
            }
            response
        });
        let response = tokio::time::timeout_at(tokio::time::Instant::from_std(deadline), worker)
            .await
            .map_err(|_| Error::Unavailable)?
            .map_err(|_| Error::Unavailable)??;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        let current = match operation {
            LocalReadOperation::Readback => {
                let response: wire::Response = serde_json::from_slice(&response)?;
                response.require_request(&request)?;
                Some(self.original.context.decode(response.read)?)
            }
            LocalReadOperation::CompletionReadiness => {
                let response: readiness::Response = serde_json::from_slice(&response)?;
                response.request.require_profile(
                    &self.original.context,
                    self.original.binding,
                    request_id,
                )?;
                match response.result {
                    readiness::Readiness::NotReady => None,
                    readiness::Readiness::Ready { read } => {
                        Some(self.original.context.decode(read)?)
                    }
                }
            }
        };
        let fresh = now()?;
        if fresh < started_at
            || self.original.context.binding(fresh)? != self.original.binding
            || Instant::now() >= deadline
        {
            return Err(Error::Binding("original local read window after owner I/O"));
        }
        if slot
            .retained
            .as_ref()
            .is_some_and(|prior| current.as_ref() != Some(prior))
        {
            return Err(Error::Binding(
                "original local read cannot change or become pending",
            ));
        }
        if let Some(read) = &current {
            slot.retained = Some(read.clone());
        }
        let mut destination = self
            .original
            .slot
            .try_lock()
            .map_err(|_| Error::Unavailable)?;
        self.require_original_window()?;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        *destination = Some(slot);
        Ok(current)
    }
}

impl OriginalCircuitLearningReadClientV1 {
    pub fn from_original_evaluated_local_selection(
        local: OriginalCircuitPublishedLocalReadV1,
        context: OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<Self, Error> {
        local.require_original_selection(&context)?;
        let context =
            OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(context)?;
        Self::from_original_local_profile(local, ReadProfile::Evaluated(context))
    }

    pub fn from_original_evaluated_local_next_use(
        local: OriginalCircuitPublishedLocalReadV1,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        local.require_original_next_use(&selection)?;
        let context =
            OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(selection)?;
        Self::from_original_local_profile(local, ReadProfile::Evaluated(context))
    }

    fn from_original_local_profile(
        local: OriginalCircuitPublishedLocalReadV1,
        context: ReadProfile,
    ) -> Result<Self, Error> {
        let binding = context.binding(now()?)?;
        if binding != local.original.binding {
            return Err(Error::Binding("same original local read binding"));
        }
        local.require_original_window()?;
        Ok(Self {
            context,
            binding,
            channel: Mutex::new(None),
            retained: Mutex::new(None),
            local: Some(local),
        })
    }

    pub(crate) fn require_original_local_shared_readbacks(
        &self,
        shared: &crate::OriginalCircuitPublishedEvidenceReadbackV1,
    ) -> Result<(), Error> {
        let local = self
            .local
            .as_ref()
            .ok_or(Error::Binding("local Version capability required"))?;
        local.require_original_window()?;
        OriginalVersionLocalReadBindingV1::require_original_shared_readbacks(
            &local.original.original,
            shared,
        )
        .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        local.require_original_window()
    }

    pub(crate) fn require_original_local_evaluated_selection(
        &self,
        expected: &OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<Instant, Error> {
        self.require_original_evaluated_selection(expected)?;
        self.local
            .as_ref()
            .ok_or(Error::Binding("local Selection capability required"))?
            .require_original_selection(expected)
    }

    pub(crate) fn require_original_local_evaluated_next_use(
        &self,
        expected: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Instant, Error> {
        self.require_original_evaluated_next_use(expected)?;
        self.local
            .as_ref()
            .ok_or(Error::Binding("local NextUse capability required"))?
            .require_original_next_use(expected)
    }
}

#[cfg(test)]
#[path = "circuit_learning_local_read_support_tests.rs"]
mod fixture;
