//! NDU dispatch through the existing private Agentd control socket.
use super::*;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_protocol::NduCommittedEntryV1;
use codex_hepta_agent_protocol::NduControlRequestV1;
use codex_hepta_agent_protocol::NduControlResultV1;
use codex_hepta_agent_protocol::NduMutationOperationV1;
use codex_hepta_agent_protocol::NduMutationV1;
use codex_hepta_ndu::NduProjectionKindV1;

use super::replay::NduExternalReplayBeginV2;
use super::replay::NduExternalReplayStoreErrorV2;

impl AgentdNduOwnerHostV1 {
    pub(crate) fn control(
        &self,
        request: NduControlRequestV1,
        mut live_guard: impl FnMut() -> Result<(), AgentdNduOwnerErrorV1>,
    ) -> Result<NduControlResultV1, AgentdNduOwnerErrorV1> {
        let encoded_len = serde_json::to_vec(&request)
            .map_err(|_| AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-006"))?
            .len();
        let now = now_unix_ms()?;
        if matches!(&request, NduControlRequestV1::ExternalAdmissionV2 { .. }) {
            request
                .validate_external_admission_v2(encoded_len, now, &BTreeSet::new())
                .map_err(AgentdNduOwnerErrorV1::Admission)?;
        }

        let mut owner = self.lock_owner()?;
        live_guard()?;
        if let Some(feed) = &self.feed {
            feed.refresh(&self.authority)?;
        }
        owner.refresh_revocation_frontier(current_frontier(&self.authority)?)?;

        let (request, replay_key) = match request {
            NduControlRequestV1::ExternalAdmissionV2 {
                request_id,
                idempotency_key,
                caller_id,
                issued_at_unix_ms,
                deadline_unix_ms,
                host_generation,
                fence_digest,
                revocation_head_digest,
                payload_digest,
                request,
                extensions,
                ..
            } => {
                if host_generation != self.spawn_generation
                    || fence_digest != *owner.context().fence_digest.as_array()
                    || revocation_head_digest
                        != *owner.context().revocation_frontier_digest.as_array()
                {
                    return Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-005"));
                }
                let binding_bytes = serde_json::to_vec(&(
                    &request_id,
                    payload_digest,
                    issued_at_unix_ms,
                    deadline_unix_ms,
                    host_generation,
                    fence_digest,
                    revocation_head_digest,
                    &extensions,
                ))
                .map_err(|_| AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-006"))?;
                let binding_digest = Digest32::of_parts(&[
                    b"hepta.agentd.ndu-external-replay.v2\0",
                    &binding_bytes,
                ]);
                let key = (caller_id, idempotency_key);
                let mut replay = self.lock_admission_replay()?;
                match replay
                    .begin(key.clone(), binding_digest, deadline_unix_ms, now)
                    .map_err(replay_store_error)?
                {
                    NduExternalReplayBeginV2::Cached(result) => return Ok(result),
                    NduExternalReplayBeginV2::Fresh => {}
                }
                drop(replay);
                (*request, Some((key, binding_digest)))
            }
            ordinary => (ordinary, None),
        };

        let head = owner.journal_head_digest()?;
        let result = match request {
            NduControlRequestV1::Context => Ok(NduControlResultV1::Context {
                journal_head: *head.as_array(),
                revocation_head: *owner.context().revocation_frontier_digest.as_array(),
                principal_id: owner.context().principal_id.to_string(),
                host_generation: self.spawn_generation,
                policy_digest: *owner.production_policy_digest().as_array(),
            }),
            NduControlRequestV1::Prepare {
                mutation,
                expected_head,
            } => {
                let expected_head = Digest32::from_array(expected_head);
                if head != expected_head {
                    Err(NduOwnerError::JournalHeadMismatch.into())
                } else {
                    let binding = owner
                        .final_use_binding_at_head(&native_mutation(mutation)?, expected_head)?;
                    Ok(NduControlResultV1::Prepared {
                        journal_head: *head.as_array(),
                        binding,
                    })
                }
            }
            NduControlRequestV1::Apply {
                mutation,
                expected_head,
                grant,
            } => {
                let entry = owner.apply_mutation_at_head_guarded(
                    &grant,
                    native_mutation(mutation)?,
                    Digest32::from_array(expected_head),
                    || {
                        live_guard().map_err(|_| {
                            NduOwnerError::InvalidContext("product lifecycle fence")
                        })?;
                        if let Some(feed) = &self.feed {
                            feed.require_current(&self.authority).map_err(|_| {
                                NduOwnerError::InvalidContext(
                                    "revocation feed changed before mutation",
                                )
                            })?;
                        }
                        Ok(())
                    },
                )?;
                Ok(NduControlResultV1::Committed {
                    entry: wire_entry(entry),
                })
            }
            NduControlRequestV1::Selection { objective, subject } => {
                let projection = owner
                    .selected_projection_digest(
                        Digest32::from_array(objective),
                        Digest32::from_array(subject),
                    )?
                    .map(|digest| *digest.as_array());
                Ok(NduControlResultV1::Selection {
                    journal_head: *head.as_array(),
                    projection,
                })
            }
            NduControlRequestV1::Outcome { identity } => Ok(NduControlResultV1::Outcome {
                entry: owner
                    .mutation_result(Digest32::from_array(identity))?
                    .map(wire_entry),
            }),
            NduControlRequestV1::ExternalAdmissionV2 { .. } => {
                Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-006"))
            }
        };

        if let (Some((key, binding_digest)), Ok(value)) = (replay_key, &result) {
            let mut replay = self.lock_admission_replay()?;
            replay
                .complete(&key, binding_digest, value.clone())
                .map_err(replay_store_error)?;
        }
        result
    }
}

fn replay_store_error(error: NduExternalReplayStoreErrorV2) -> AgentdNduOwnerErrorV1 {
    let code = match error {
        NduExternalReplayStoreErrorV2::Conflict => "NDU-ADMIT-008",
        NduExternalReplayStoreErrorV2::Capacity => "NDU-ADMIT-009",
        NduExternalReplayStoreErrorV2::Pending => "NDU-ADMIT-010",
        NduExternalReplayStoreErrorV2::UnsupportedPlatform
        | NduExternalReplayStoreErrorV2::Symlink
        | NduExternalReplayStoreErrorV2::NotRegular
        | NduExternalReplayStoreErrorV2::TooLarge
        | NduExternalReplayStoreErrorV2::Corrupt
        | NduExternalReplayStoreErrorV2::MissingEntry
        | NduExternalReplayStoreErrorV2::Indeterminate
        | NduExternalReplayStoreErrorV2::Io(_) => "NDU-ADMIT-011",
    };
    AgentdNduOwnerErrorV1::Admission(code)
}

fn native_mutation(wire: NduMutationV1) -> Result<NduOwnerMutationV1, AgentdNduOwnerErrorV1> {
    let identity_digest = Digest32::from_array(wire.identity);
    let objective_digest = Digest32::from_array(wire.objective);
    let subject_digest = Digest32::from_array(wire.subject);
    let projection_digest = Digest32::from_array(wire.projection);
    if wire.operation != NduMutationOperationV1::Select && wire.expected_predecessor.is_some() {
        return Err(NduOwnerError::InvalidContext("predecessor on non-selection mutation").into());
    }
    Ok(match wire.operation {
        NduMutationOperationV1::AppendPreference | NduMutationOperationV1::AppendUtility => {
            NduOwnerMutationV1::AppendProjection {
                kind: if wire.operation == NduMutationOperationV1::AppendPreference {
                    NduProjectionKindV1::Preference
                } else {
                    NduProjectionKindV1::Utility
                },
                identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            }
        }
        NduMutationOperationV1::Select => NduOwnerMutationV1::SelectProjection {
            identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
            expected_predecessor: wire.expected_predecessor.map(Digest32::from_array),
        },
        NduMutationOperationV1::Revoke => NduOwnerMutationV1::RevokeProjection {
            identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        },
    })
}

fn wire_entry(entry: NduProjectionEntryV1) -> NduCommittedEntryV1 {
    NduCommittedEntryV1 {
        operation: match entry.kind {
            NduProjectionKindV1::Preference => NduMutationOperationV1::AppendPreference,
            NduProjectionKindV1::Utility => NduMutationOperationV1::AppendUtility,
            NduProjectionKindV1::SelectedProjection => NduMutationOperationV1::Select,
            NduProjectionKindV1::Revocation => NduMutationOperationV1::Revoke,
        },
        sequence: entry.sequence,
        identity: *entry.identity_digest.as_array(),
        objective: *entry.objective_digest.as_array(),
        subject: *entry.subject_digest.as_array(),
        projection: *entry.payload_digest.as_array(),
        predecessor_entry: *entry.predecessor_entry_digest.as_array(),
        entry_digest: *entry.entry_digest.as_array(),
    }
}

fn now_unix_ms() -> Result<u64, AgentdNduOwnerErrorV1> {
    let milliseconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-004"))?
        .as_millis();
    u64::try_from(milliseconds)
        .map_err(|_| AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-004"))
}
