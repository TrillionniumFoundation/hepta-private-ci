//! Private backend for the same concrete CURRENT owner. Only the exact
//! enrolled preparation/publication can be expressed; there is no arbitrary CAS.

use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use crate::AgentdError;
use crate::authority_host_service::generation_publication::Command;
use crate::authority_host_service::generation_publication::PublicationProfile;
use crate::authority_host_service::generation_publication::PublicationVersion;
use crate::authority_host_service::generation_publication::Request;
use crate::authority_host_service::generation_publication::Response;
use crate::authority_host_service::generation_publication::head_digest;
use crate::neuron_generation_current::types::CurrentHead;
use crate::neuron_generation_current::types::Published;

#[path = "root_generation_publication_stream.rs"]
mod stream;
pub(crate) use stream::OriginalPublicationStream;

struct Lane {
    stream: OriginalPublicationStream,
    sequence: u64,
}

pub(crate) struct RootGenerationCurrentClient {
    profile: PublicationProfile,
    version: PublicationVersion,
    connection: crate::RootGenerationPublicationConnectionV1,
    lane: Mutex<Option<Lane>>,
    fenced: AtomicBool,
}

/// An original CURRENT transition may have completed before acknowledgement
/// was lost. This typed source is retained through Agentd's existing Io variant.
#[derive(Debug, thiserror::Error)]
#[error("original Root generation publication outcome is uncertain")]
pub(crate) struct RootGenerationPublicationUncertain;

pub(crate) fn uncertain() -> AgentdError {
    AgentdError::Io(std::io::Error::other(RootGenerationPublicationUncertain))
}

impl RootGenerationCurrentClient {
    pub(crate) fn from_original_stream(
        mut stream: OriginalPublicationStream,
        bootstrap: &crate::authority_host_service::generation_publication::PublicationBootstrap,
        operation: &str,
        connection: crate::RootGenerationPublicationConnectionV1,
    ) -> Result<Self, AgentdError> {
        connection.require_original_publication_session()?;
        let version = PublicationVersion::from_purpose(&bootstrap.purpose)?;
        let request = Request {
            schema: version.schema(),
            purpose: version.purpose().into(),
            request_id: 1,
            profile: String::new(),
            command: Command::Observe,
        };
        let raw = stream
            .exchange(&serde_json::to_vec(&request)?)
            .map_err(AgentdError::Io)?;
        let response: Response = serde_json::from_slice(&raw)?;
        let profile = &response.profile;
        if response.schema != version.schema()
            || response.purpose != version.purpose()
            || response.request_id != 1
            || profile.purpose != version.purpose()
            || profile.initial != bootstrap.initial
            || profile.scope != bootstrap.scope
            || profile.writer != bootstrap.writer
            || profile.learning_operation != operation
            || profile.identity
                != crate::neuron_generation_process_identity_digest_v1(
                    &bootstrap.identity.identity()?,
                )?
                .to_string()
            || profile.digest()? != profile.binding
            || profile.intent.supersedes.is_some()
            || !matches!(
                profile.intent.completion,
                crate::NeuronGenerationPredecessorCompletionV1::OwnerDrained
                    | crate::NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
            )
        {
            return Err(AgentdError::GenerationFenced(
                "original publication profile differs".into(),
            ));
        }
        validate_head(profile, &response.head)?;
        connection.require_original_publication_session()?;
        Ok(Self {
            profile: response.profile,
            version,
            connection,
            lane: Mutex::new(Some(Lane {
                stream,
                sequence: 2,
            })),
            fenced: AtomicBool::new(false),
        })
    }

    pub(crate) fn scope(&self) -> &codex_hepta_neuron::CellGenerationScopeV2 {
        self.profile.intent.previous.scope()
    }

    pub(crate) fn require_selection(
        &self,
        decision: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        operation: &codex_hepta_types::StableId,
        selection: codex_hepta_types::Digest32,
    ) -> Result<(), AgentdError> {
        self.observe()?;
        if self.profile.decision != decision.head_digest.to_string()
            || self.profile.learning_operation != decision.request.operation_id.as_str()
            || self.profile.intent.operation_id != operation.as_str()
            || self.profile.intent.selection != selection.into_array()
        {
            self.fence();
            return Err(uncertain());
        }
        Ok(())
    }

    pub(crate) fn require_successor_context(
        &self,
        session: &crate::root_production_inputs::OriginalQ24SuccessorSession,
        initial: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
    ) -> Result<(), AgentdError> {
        self.connection.require_same_successor_session(session)?;
        self.observe()?;
        if self.profile.initial != initial.head_digest.to_string()
            || self.profile.scope != scope.binding().to_string()
            || self.profile.writer != session.writer_proof()?
            || self.profile.identity
                != crate::neuron_generation_process_identity_digest_v1(session.identity())?
                    .to_string()
            || self.profile.learning_operation != initial.request.operation_id.as_str()
        {
            self.fence();
            return Err(uncertain());
        }
        self.connection.require_same_successor_session(session)
    }

    fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
        if let Ok(mut held) = self.lane.try_lock() {
            held.take();
        }
    }

    pub(crate) fn observe(&self) -> Result<CurrentHead, AgentdError> {
        self.exchange(Command::Observe)
    }

    pub(crate) fn replace(
        &self,
        expected: &CurrentHead,
        next: &CurrentHead,
    ) -> Result<(), AgentdError> {
        let intent = &self.profile.intent;
        let mut prepared = expected.clone();
        prepared.prepared = Some(intent.clone());
        let command = if expected.current == intent.previous
            && expected
                .prepared
                .as_ref()
                .is_none_or(|existing| existing == intent)
            && next == &prepared
        {
            Command::Prepare {
                expected: head_digest(expected)?,
                intent: intent.digest()?.to_string(),
            }
        } else {
            let record = next.published.as_ref().ok_or_else(uncertain)?;
            let exact = CurrentHead {
                schema_version: 1,
                current: intent.target.clone(),
                prepared: None,
                initial: None,
                published: Some(Published {
                    intent: intent.clone(),
                    signed: record.signed.clone(),
                    witness: record.witness.clone(),
                    signed_grant_digest: crate::neuron_generation_current::signed_grant_digest(
                        &record.signed,
                    )?
                    .into_array(),
                }),
            };
            if expected.current != intent.previous
                || expected.prepared.as_ref() != Some(intent)
                || next != &exact
                || record.signed.grant.binding != intent.binding()?
            {
                return Err(uncertain());
            }
            record.witness.validate().map_err(|_| uncertain())?;
            Command::Publish {
                expected: head_digest(expected)?,
                intent: intent.digest()?.to_string(),
                signed: record.signed.clone(),
                witness: record.witness.clone(),
            }
        };
        if &self.exchange(command)? != next {
            self.fence();
            return Err(uncertain());
        }
        Ok(())
    }

    fn exchange(&self, command: Command) -> Result<CurrentHead, AgentdError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(uncertain());
        }
        if self
            .connection
            .require_original_publication_session()
            .is_err()
        {
            self.fence();
            return Err(uncertain());
        }
        let mut held = self.lane.try_lock().map_err(|_| {
            self.fenced.store(true, Ordering::Release);
            uncertain()
        })?;
        let mut lane = held.take().ok_or_else(uncertain)?;
        // Empty until complete framing, profile and transition validation.
        // Any timeout, loss, concurrent call or malformed response consumes it.
        let request_id = lane.sequence;
        lane.sequence = request_id.checked_add(1).ok_or_else(uncertain)?;
        let request = Request {
            schema: self.version.schema(),
            purpose: self.version.purpose().into(),
            request_id,
            profile: self.profile.binding.clone(),
            command,
        };
        let raw = lane
            .stream
            .exchange(&serde_json::to_vec(&request).map_err(|_| uncertain())?)
            .map_err(|_| uncertain())?;
        let response: Response = serde_json::from_slice(&raw).map_err(|_| uncertain())?;
        if response.schema != self.version.schema()
            || response.purpose != self.version.purpose()
            || response.request_id != request_id
            || response.profile != self.profile
            || self.fenced.load(Ordering::Acquire)
        {
            return Err(uncertain());
        }
        validate_head(&self.profile, &response.head)?;
        if self
            .connection
            .require_original_publication_session()
            .is_err()
        {
            self.fenced.store(true, Ordering::Release);
            return Err(uncertain());
        }
        *held = Some(lane);
        Ok(response.head)
    }
}

fn validate_head(profile: &PublicationProfile, head: &CurrentHead) -> Result<(), AgentdError> {
    let intent = &profile.intent;
    if head.schema_version != 1
        || (head.current != intent.previous && head.current != intent.target)
        || head
            .prepared
            .as_ref()
            .is_some_and(|actual| actual != intent)
    {
        return Err(uncertain());
    }
    if head.current == intent.target {
        let record = head.published.as_ref().ok_or_else(uncertain)?;
        if record.intent != *intent
            || head.prepared.is_some()
            || record.signed.grant.binding != intent.binding()?
            || record.signed_grant_digest
                != crate::neuron_generation_current::signed_grant_digest(&record.signed)?
                    .into_array()
        {
            return Err(uncertain());
        }
        record.witness.validate().map_err(|_| uncertain())?;
    }
    Ok(())
}
