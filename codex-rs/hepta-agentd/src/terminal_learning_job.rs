//! Recovery of one native terminal job in the original protected CAS owner.
//!
//! Registration belongs to the existing broker. This module accepts only that
//! concrete capability, never a pathname, signer, caller receipt or new grant.
//! A durable Computing fence precedes the fit; only its committed result can be
//! recovered. An interrupted fit is unknown and is never run a second time.

#[cfg(test)]
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdSharedReplayHostV1;
use crate::TerminalLearningErrorV1 as Error;
use crate::TerminalLearningReceiptV1;
use crate::TerminalLearningRequestV1;

#[path = "terminal_learning_job_codec.rs"]
mod codec;

/// The original broker must register/open this bound through its existing
/// authorization path. This constant does not create a registration.
pub const TERMINAL_LEARNING_JOB_RECORD_BYTES_V1: u64 = 64 * 1024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TerminalLearningJobRecordV1 {
    schema: u8,
    binding: String,
    state: State,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "stage", content = "result", deny_unknown_fields)]
enum State {
    Vacant,
    Computing,
    Committed(Box<codec::SavedReceipt>),
}

impl TerminalLearningJobRecordV1 {
    /// Registration data only: at most 256 dataset records and 16 KiB payload.
    /// No serialized SharedExperienceUseV1 or principal grants are accepted.
    pub fn vacant(
        request: &TerminalLearningRequestV1,
        agent_id: &AgentId,
        producer_id: &StableId,
    ) -> Result<Self, Error> {
        let binding = request.job_digest(agent_id, producer_id)?;
        let profile = &request.profile;
        let payload_bytes = 184
            + profile.artifact_id.as_str().len()
            + profile.producer_id.as_str().len()
            + profile
                .action_ids
                .iter()
                .map(|action| 64 + profile.sensor_id.as_str().len() + action.as_str().len())
                .sum::<usize>();
        if request.budget.maximum_dataset_records > 256
            || request.budget.maximum_artifact_bytes > 16 * 1024
            || payload_bytes as u64 > request.budget.maximum_artifact_bytes
        {
            return Err(Error::Capacity);
        }
        Ok(Self {
            schema: 1,
            binding: binding.to_string(),
            state: State::Vacant,
        })
    }
}

enum Store {
    Host(HostAuthorityFrontierStore<TerminalLearningJobRecordV1>),
    #[cfg(test)]
    Test(Arc<dyn AuthorityFrontierStore<TerminalLearningJobRecordV1>>),
}

pub struct TerminalLearningJobOwnerV1 {
    owner_id: String,
    agent_id: AgentId,
    producer_id: StableId,
    binding: Digest32,
    store: Store,
}

impl TerminalLearningJobOwnerV1 {
    /// Consume an existing 64 KiB registration for this exact signed request.
    /// Missing or corrupt state is never initialized or repaired here.
    pub fn from_registered(
        store: HostAuthorityFrontierStore<TerminalLearningJobRecordV1>,
        original_owner_id: String,
        request: &TerminalLearningRequestV1,
        agent_id: AgentId,
        producer_id: StableId,
    ) -> Result<Self, Error> {
        Self::configured(
            Store::Host(store),
            original_owner_id,
            request,
            agent_id,
            producer_id,
        )
    }

    fn configured(
        store: Store,
        owner_id: String,
        request: &TerminalLearningRequestV1,
        agent_id: AgentId,
        producer_id: StableId,
    ) -> Result<Self, Error> {
        TerminalLearningJobRecordV1::vacant(request, &agent_id, &producer_id)?;
        let binding = request.job_digest(&agent_id, &producer_id)?;
        let owner = Self {
            owner_id,
            agent_id,
            producer_id,
            binding,
            store,
        };
        owner.load()?;
        Ok(owner)
    }

    pub(crate) fn check_scope(
        &self,
        agent_id: &AgentId,
        producer_id: &StableId,
    ) -> Result<(), Error> {
        if agent_id != &self.agent_id || producer_id != &self.producer_id {
            return Err(Error::WrongScope);
        }
        Ok(())
    }

    pub(crate) async fn restore(
        &self,
        replay: &AgentdSharedReplayHostV1,
        request: &TerminalLearningRequestV1,
        now: u64,
    ) -> Result<Option<TerminalLearningReceiptV1>, Error> {
        if request.job_digest(&self.agent_id, &self.producer_id)? != self.binding {
            return Err(Error::Conflict);
        }
        match self.load()?.state {
            State::Vacant => Ok(None),
            State::Computing => Err(Error::CommitUncertain),
            State::Committed(saved) => saved
                .restore(replay, request, self.binding, now)
                .await
                .map(Some),
        }
    }

    pub(crate) fn claim(&self) -> Result<(), Error> {
        let current = self.load()?;
        if current.state != State::Vacant {
            return Err(Error::CommitUncertain);
        }
        let mut next = current.clone();
        next.state = State::Computing;
        self.replace(&current, &next)
    }

    pub(crate) fn complete(&self, receipt: &TerminalLearningReceiptV1) -> Result<(), Error> {
        if receipt.job_digest != self.binding {
            return Err(Error::Conflict);
        }
        let current = self.load()?;
        let mut next = current.clone();
        next.state = State::Committed(Box::new(codec::SavedReceipt::capture(receipt)?));
        if current == next {
            return Ok(());
        }
        if current.state != State::Computing {
            return Err(Error::CommitUncertain);
        }
        self.replace(&current, &next)
    }

    fn load(&self) -> Result<TerminalLearningJobRecordV1, Error> {
        let record = match &self.store {
            Store::Host(store) => store.load(&self.owner_id),
            #[cfg(test)]
            Store::Test(store) => store.load(&self.owner_id),
        }
        .map_err(|_| Error::CommitUncertain)?;
        if record.schema != 1 || record.binding != self.binding.to_string() {
            return Err(Error::Conflict);
        }
        check_size(&record)?;
        Ok(record)
    }

    fn replace(
        &self,
        current: &TerminalLearningJobRecordV1,
        next: &TerminalLearningJobRecordV1,
    ) -> Result<(), Error> {
        check_size(next)?;
        match &self.store {
            Store::Host(store) => store.compare_and_set(&self.owner_id, current, next),
            #[cfg(test)]
            Store::Test(store) => store.compare_and_set(&self.owner_id, current, next),
        }
        .map_err(|_| Error::CommitUncertain)
    }

    #[cfg(test)]
    pub(crate) fn from_test(
        store: Arc<dyn AuthorityFrontierStore<TerminalLearningJobRecordV1>>,
        request: &TerminalLearningRequestV1,
        agent_id: AgentId,
        producer_id: StableId,
    ) -> Result<Self, Error> {
        Self::configured(
            Store::Test(store),
            "terminal-test-owner".into(),
            request,
            agent_id,
            producer_id,
        )
    }
}

fn check_size(record: &TerminalLearningJobRecordV1) -> Result<(), Error> {
    // Reserve 4 KiB for the original Root envelope and owner identifier.
    if serde_json::to_vec(record)
        .map_err(|_| Error::InvalidRequest)?
        .len()
        > 60 * 1024
    {
        return Err(Error::Capacity);
    }
    Ok(())
}
