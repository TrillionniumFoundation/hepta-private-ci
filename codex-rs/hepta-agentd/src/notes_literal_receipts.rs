//! Strict recovery of the existing Desktop sender observation schema. Parsing
//! local rows never proves an ACK; callers first obtain snapshot_acknowledged.

use codex_hepta_agent_protocol::ObjectiveAdmissionPublication;
use codex_hepta_agent_protocol::ObjectiveJournalAnchor;
use codex_hepta_agent_protocol::ObjectivePublicationOutcome;
use codex_hepta_memory::ObjectiveSenderObservationKind;
use codex_hepta_memory::ObjectiveSenderOrigin;
use codex_hepta_memory::ObjectiveSenderRequest;
use codex_hepta_memory::ObjectiveSenderSnapshot;
use serde::Deserialize;
use serde::Serialize;

use crate::notes_ui_wire::ObjectiveStage;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Identity {
    request_id: u64,
    agent_id: String,
    spawn_generation: u64,
    expected_peer_uid: u32,
    expected_peer_pid: u32,
    objective: Objective,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Objective {
    issuer_id: String,
    key_epoch: u64,
    message_id: String,
    sequence: u64,
    expires_at_ms: u64,
    spawn_generation: u64,
    run_id: String,
    objective_revision: u64,
    authority_epoch: u64,
    runtime_body_digest: String,
    preference_state_digest: String,
    model_tuple_digest: String,
    prompt_registry_digest: String,
    artifact_set_digest: String,
}

pub(crate) fn identity(
    request: &ObjectiveSenderRequest,
    origin: &ObjectiveSenderOrigin,
) -> Identity {
    let source = request.identity();
    Identity {
        request_id: origin.request_id,
        agent_id: origin.agent_id.to_string(),
        spawn_generation: origin.spawn_generation,
        expected_peer_uid: origin.expected_peer_uid,
        expected_peer_pid: origin.expected_peer_pid,
        objective: Objective {
            issuer_id: source.issuer_id.clone(),
            key_epoch: source.key_epoch,
            message_id: source.message_id.clone(),
            sequence: source.sequence,
            expires_at_ms: source.expires_at_ms,
            spawn_generation: source.body_spawn_generation,
            run_id: source.run_id.clone(),
            objective_revision: source.objective_revision,
            authority_epoch: source.authority_epoch,
            runtime_body_digest: source.runtime_body_digest.clone(),
            preference_state_digest: source.preference_state_digest.clone(),
            model_tuple_digest: source.model_tuple_digest.clone(),
            prompt_registry_digest: source.prompt_registry_digest.clone(),
            artifact_set_digest: source.artifact_set_digest.clone(),
        },
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Submission {
    schema: u32,
    original_sha256: String,
    submission: Identity,
    bytes_written: usize,
    request_frame_bytes: Option<usize>,
    status: SubmissionStatus,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum SubmissionStatus {
    NotSent {
        issue: String,
    },
    SubmitUnknown {
        issue: String,
    },
    RefusedBeforePublication {
        reason: String,
        response_generation: u64,
    },
    Admitted {
        run_id: String,
        objective_digest: String,
        hard_constraint_digest: String,
        publication_digest: String,
        chain_digest: String,
        disposition: String,
        idempotent: bool,
        response_generation: u64,
    },
    Conflict {
        run_id: String,
        conflict_digest: String,
        response_generation: u64,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct History {
    pub(crate) schema: u32,
    pub(crate) original_sha256: String,
    pub(crate) query: Identity,
    pub(crate) requested_anchor: Option<ObjectiveJournalAnchor>,
    pub(crate) bytes_written: usize,
    pub(crate) request_frame_bytes: Option<usize>,
    pub(crate) status: HistoryStatus,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum HistoryStatus {
    HistoricalPublication {
        publication: Box<ObjectiveAdmissionPublication>,
        response_generation: u64,
    },
    Unknown {
        issue: String,
    },
    QueryNotSent {
        issue: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum KnownPublication {
    Admitted {
        objective: String,
        hard: String,
        publication: String,
        chain: String,
        abstained: bool,
    },
    Conflict(String),
}

impl KnownPublication {
    pub(crate) fn stage(&self) -> ObjectiveStage {
        match self {
            Self::Admitted {
                abstained: true, ..
            } => ObjectiveStage::Abstained,
            Self::Admitted {
                abstained: false, ..
            } => ObjectiveStage::Admitted,
            Self::Conflict(_) => ObjectiveStage::Conflict,
        }
    }
}

pub(crate) struct Projection {
    pub(crate) stage: ObjectiveStage,
    pub(crate) known: Option<KnownPublication>,
    first: Option<Box<ObjectiveAdmissionPublication>>,
}

pub(crate) fn publication(
    request: &ObjectiveSenderRequest,
    value: &ObjectiveAdmissionPublication,
) -> Result<KnownPublication, ()> {
    let expected = request.identity();
    if value.run_id != expected.run_id
        || value.original_spawn_generation != expected.body_spawn_generation
        || value.issuer_id != expected.issuer_id
        || value.key_epoch != expected.key_epoch
        || value.message_id != expected.message_id
        || value.message_sequence != expected.sequence
        || value.expires_at_ms != expected.expires_at_ms
        || value.signed_body_digest != expected.signed_body_sha256.as_str()
        || !(1..=8192).contains(&value.publication_sequence)
        || [
            &value.profile_digest,
            &value.publication_digest,
            &value.chain_digest,
        ]
        .into_iter()
        .any(|d| !digest(d))
    {
        return Err(());
    }
    Ok(match &value.outcome {
        ObjectivePublicationOutcome::Compiled {
            objective_digest,
            hard_constraint_digest,
        }
        | ObjectivePublicationOutcome::ExplicitAbstain {
            objective_digest,
            hard_constraint_digest,
        } => {
            if !digest(objective_digest) || !digest(hard_constraint_digest) {
                return Err(());
            }
            KnownPublication::Admitted {
                objective: objective_digest.clone(),
                hard: hard_constraint_digest.clone(),
                publication: value.publication_digest.clone(),
                chain: value.chain_digest.clone(),
                abstained: matches!(
                    value.outcome,
                    ObjectivePublicationOutcome::ExplicitAbstain { .. }
                ),
            }
        }
        ObjectivePublicationOutcome::Conflict { conflict_digest } => {
            if !digest(conflict_digest) {
                return Err(());
            }
            KnownPublication::Conflict(conflict_digest.clone())
        }
    })
}

pub(crate) fn project(
    request: &ObjectiveSenderRequest,
    snapshot: &ObjectiveSenderSnapshot,
) -> Result<Projection, ()> {
    let mut out = Projection {
        stage: ObjectiveStage::Retained,
        known: None,
        first: None,
    };
    let expected = identity(request, request.origin());
    let mut submission_seen = false;
    for observation in &snapshot.observations {
        match observation.kind() {
            ObjectiveSenderObservationKind::Submission => {
                if submission_seen {
                    return Err(());
                }
                submission_seen = true;
                let record: Submission =
                    serde_json::from_slice(observation.exact_original()).map_err(|_| ())?;
                if record.schema != 1
                    || record.original_sha256 != request.identity().original_sha256.as_str()
                    || serde_json::to_value(&record.submission).map_err(|_| ())?
                        != serde_json::to_value(&expected).map_err(|_| ())?
                {
                    return Err(());
                }
                io_shape(record.bytes_written, record.request_frame_bytes)?;
                let response = |generation| {
                    response_shape(
                        request.origin().spawn_generation,
                        generation,
                        record.bytes_written,
                        record.request_frame_bytes,
                    )
                };
                let known = match record.status {
                    SubmissionStatus::NotSent { issue } => {
                        if record.bytes_written != 0 || issue.is_empty() || issue.len() > 96 {
                            return Err(());
                        }
                        out.stage = ObjectiveStage::NotSent;
                        None
                    }
                    SubmissionStatus::SubmitUnknown { issue } => {
                        if record.bytes_written == 0 || issue.is_empty() || issue.len() > 96 {
                            return Err(());
                        }
                        out.stage = ObjectiveStage::SubmitUnknown;
                        None
                    }
                    SubmissionStatus::RefusedBeforePublication {
                        reason,
                        response_generation,
                    } => {
                        response(response_generation)?;
                        if !matches!(
                            reason.as_str(),
                            "objective_unavailable" | "unsupported_schema"
                        ) || (reason == "unsupported_schema"
                            && response_generation != request.origin().spawn_generation)
                        {
                            return Err(());
                        }
                        out.stage = ObjectiveStage::Refused;
                        None
                    }
                    SubmissionStatus::Admitted {
                        run_id,
                        objective_digest,
                        hard_constraint_digest,
                        publication_digest,
                        chain_digest,
                        disposition,
                        idempotent: _,
                        response_generation,
                    } => {
                        response(response_generation)?;
                        if run_id != request.identity().run_id
                            || [
                                &objective_digest,
                                &hard_constraint_digest,
                                &publication_digest,
                                &chain_digest,
                            ]
                            .into_iter()
                            .any(|d| !digest(d))
                            || !matches!(
                                disposition.as_str(),
                                "compiled"
                                    | "explicit_abstain"
                                    | "canonical_ready"
                                    | "canonical_abstained"
                                    | "canonical_slow_path"
                            )
                        {
                            return Err(());
                        }
                        Some(KnownPublication::Admitted {
                            objective: objective_digest,
                            hard: hard_constraint_digest,
                            publication: publication_digest,
                            chain: chain_digest,
                            abstained: matches!(
                                disposition.as_str(),
                                "explicit_abstain" | "canonical_abstained"
                            ),
                        })
                    }
                    SubmissionStatus::Conflict {
                        run_id,
                        conflict_digest,
                        response_generation,
                    } => {
                        response(response_generation)?;
                        if run_id != request.identity().run_id || !digest(&conflict_digest) {
                            return Err(());
                        }
                        Some(KnownPublication::Conflict(conflict_digest))
                    }
                };
                if let Some(known) = known {
                    preserve_known(&mut out, known)?;
                }
            }
            ObjectiveSenderObservationKind::History => {
                let record: History =
                    serde_json::from_slice(observation.exact_original()).map_err(|_| ())?;
                if record.schema != 1
                    || record.original_sha256 != request.identity().original_sha256.as_str()
                    || record.query.agent_id != expected.agent_id
                    || record.query.spawn_generation == 0
                    || record.query.request_id == 0
                    || record.query.expected_peer_pid == 0
                    || record.query.expected_peer_pid > i32::MAX as u32
                    || serde_json::to_value(&record.query.objective).map_err(|_| ())?
                        != serde_json::to_value(&expected.objective).map_err(|_| ())?
                {
                    return Err(());
                }
                io_shape(record.bytes_written, record.request_frame_bytes)?;
                match record.status {
                    HistoryStatus::HistoricalPublication {
                        publication: value,
                        response_generation,
                    } => {
                        response_shape(
                            record.query.spawn_generation,
                            response_generation,
                            record.bytes_written,
                            record.request_frame_bytes,
                        )?;
                        let known = publication(request, &value)?;
                        if let Some(anchor) = record.requested_anchor
                            && (anchor.sequence == 0
                                || anchor.sequence > 8192
                                || !digest(&anchor.chain_digest)
                                || value.publication_sequence > anchor.sequence
                                || (value.publication_sequence == anchor.sequence
                                    && value.chain_digest != anchor.chain_digest))
                        {
                            return Err(());
                        }
                        if out.first.as_ref().is_some_and(|first| **first != *value) {
                            return Err(());
                        }
                        if out.first.is_none() {
                            out.first = Some(value);
                        }
                        preserve_known(&mut out, known)?;
                    }
                    HistoryStatus::Unknown { issue } => {
                        if record.bytes_written == 0 || issue.is_empty() || issue.len() > 96 {
                            return Err(());
                        }
                    }
                    HistoryStatus::QueryNotSent { issue } => {
                        if record.bytes_written != 0 || issue.is_empty() || issue.len() > 96 {
                            return Err(());
                        }
                    }
                }
            }
        }
    }
    if snapshot.locally_cancelled {
        if !snapshot.observations.is_empty() {
            return Err(());
        }
        out.stage = ObjectiveStage::NotSent;
    } else if let Some(known) = &out.known {
        out.stage = known.stage();
    }
    Ok(out)
}

fn preserve_known(out: &mut Projection, known: KnownPublication) -> Result<(), ()> {
    if out
        .known
        .as_ref()
        .is_some_and(|previous| *previous != known)
    {
        return Err(());
    }
    out.known = Some(known);
    Ok(())
}

fn io_shape(written: usize, frame: Option<usize>) -> Result<(), ()> {
    if written as u64 > crate::MAX_CONTROL_FRAME_BYTES
        || frame.is_some_and(|frame| {
            frame == 0 || frame as u64 > crate::MAX_CONTROL_FRAME_BYTES || written > frame
        })
    {
        Err(())
    } else {
        Ok(())
    }
}

fn response_shape(
    spawn: u64,
    generation: u64,
    written: usize,
    frame: Option<usize>,
) -> Result<(), ()> {
    if written == 0
        || frame.is_some_and(|frame| written != frame)
        || !matches!(generation.checked_sub(spawn), Some(0..=2))
    {
        Err(())
    } else {
        Ok(())
    }
}

fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        && value.bytes().any(|byte| byte != b'0')
}
