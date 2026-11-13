//! Fixture scheduling and archived DATA only. The product progress reader
//! proves the exact original successful trace; an admission or lost ACK does
//! not supply that fact, and this module never submits an Objective again.

use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use codex_hepta_agent_protocol::ObjectivePublicationOutcome;
use codex_hepta_agent_protocol::Q24OriginalInitialTaskCompletionV1;
use codex_hepta_agent_protocol::Q24OriginalInitialTaskProgressV1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_types::Digest32;
use serde::Serialize;

use super::inputs::ObjectiveInputs;
use super::launch::RunningOrdinaryA;
use crate::AgentdClient;
use crate::AuthBusObjectiveIngress;
use crate::ObjectiveRunAdmission;
use crate::ObjectiveStartOutcome;
use crate::client::ObjectiveStartReplyV1;

#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum OriginalObjectiveAcknowledgement {
    Acknowledged { receipt: ObjectiveRunAdmission },
    AcknowledgementLost { error: String },
}

#[derive(Serialize)]
pub(super) struct OriginalACompletionEvidence {
    acknowledgement: OriginalObjectiveAcknowledgement,
    pub(super) completed: Q24OriginalInitialTaskCompletionV1,
}

impl OriginalObjectiveAcknowledgement {
    fn from_reply(
        reply: ObjectiveStartReplyV1,
        run_id: &str,
        objective: Digest32,
    ) -> anyhow::Result<Self> {
        match reply {
            ObjectiveStartReplyV1::Completed(ObjectiveStartOutcome::Admitted { receipt }) => {
                anyhow::ensure!(
                    receipt.run_id == run_id
                        && receipt.objective_digest.parse::<Digest32>()? == objective
                        && receipt.disposition == "circuit_succeeded"
                        && !receipt.idempotent
                        && !receipt.publication_digest.parse::<Digest32>()?.is_zero()
                        && !receipt.chain_digest.parse::<Digest32>()?.is_zero(),
                    "actual original ordinary Circuit acknowledgement differs"
                );
                Ok(Self::Acknowledged { receipt })
            }
            ObjectiveStartReplyV1::Completed(ObjectiveStartOutcome::Conflict {
                run_id,
                conflict_digest,
            }) => anyhow::bail!(
                "ordinary original Objective conflict: run_id={run_id}, conflict_digest={conflict_digest}"
            ),
            ObjectiveStartReplyV1::AcknowledgementLost(error) => {
                let error = error.to_string();
                eprintln!("ORDINARY_Q24_OBJECTIVE_ACKNOWLEDGEMENT_LOST={error}");
                Ok(Self::AcknowledgementLost { error })
            }
        }
    }

    fn observation_context(&self) -> String {
        match self {
            Self::Acknowledged { .. } => "original Objective ACK received".into(),
            Self::AcknowledgementLost { error } => {
                format!("original Objective ACK lost: {error}")
            }
        }
    }
}

pub(super) async fn read_original_completion(
    running: &RunningOrdinaryA,
    client: &AgentdClient,
    reply: ObjectiveStartReplyV1,
) -> anyhow::Result<OriginalACompletionEvidence> {
    let original = &running.plan.objective;
    let acknowledgement = OriginalObjectiveAcknowledgement::from_reply(
        reply,
        &original.request.body.run_id,
        original.objective,
    )?;
    let observed = async {
        super::root::write_json(
            &running
                .plan
                .protected
                .path()
                .join("original-objective-acknowledgement.json"),
            &acknowledgement,
        )?;
        let data = read_until_completed(client, &original.request, running.end, || {
            running.require_live()
        })
        .await?;
        require_original_completion(&data, &running.plan.identity, original, &acknowledgement)?;
        running.require_live()?;
        Ok::<_, anyhow::Error>(data)
    }
    .await;
    let completed = observed.with_context(|| acknowledgement.observation_context())?;
    Ok(OriginalACompletionEvidence {
        acknowledgement,
        completed,
    })
}

async fn read_until_completed(
    client: &AgentdClient,
    request: &AuthBusObjectiveIngress,
    end: Instant,
    require_live: impl Fn() -> anyhow::Result<()>,
) -> anyhow::Result<Q24OriginalInitialTaskCompletionV1> {
    let deadline = tokio::time::Instant::from_std(end);
    loop {
        require_live()?;
        anyhow::ensure!(
            Instant::now() < end,
            "original Initial completion end elapsed"
        );
        // Each original client frame still has its own unchanged two-second
        // limit. The outer absolute end is never renewed by another read.
        let observed = tokio::time::timeout_at(
            deadline,
            client.original_q24_initial_task_progress(request.clone()),
        )
        .await;
        let after = require_live();
        let observed = observed
            .context("original Initial completion deadline elapsed")?
            .context("original Initial progress read failed")?;
        after?;
        anyhow::ensure!(
            Instant::now() < end,
            "original Initial completion end elapsed"
        );
        match observed {
            Q24OriginalInitialTaskProgressV1::Completed { data } => return Ok(*data),
            Q24OriginalInitialTaskProgressV1::InFlight {} => {
                tokio::time::sleep_until(
                    (tokio::time::Instant::now() + Duration::from_millis(50)).min(deadline),
                )
                .await;
            }
        }
    }
}

fn require_original_completion(
    data: &Q24OriginalInitialTaskCompletionV1,
    identity: &crate::AgentdIdentity,
    original: &ObjectiveInputs,
    acknowledgement: &OriginalObjectiveAcknowledgement,
) -> anyhow::Result<()> {
    let request = &original.request;
    let admission = &data.admission;
    let claims = crate::authbus_objective_claims(identity, request)?;
    let profile = decode_admission_profile_json_v1(&serde_json::to_vec(&original.profile)?)?;
    anyhow::ensure!(
        admission.run_id == request.body.run_id
            && admission.original_spawn_generation == request.body.spawn_generation
            && admission.issuer_id == request.issuer_id
            && admission.key_epoch == request.key_epoch
            && admission.message_id == request.message_id
            && admission.message_sequence == request.sequence
            && admission.expires_at_ms == request.expires_at_ms
            && admission.signed_body_digest == claims.payload_digest.to_string()
            && admission.profile_digest == profile.digest()?.to_string()
            && admission.publication_sequence > 0
            && !admission.publication_digest.parse::<Digest32>()?.is_zero()
            && !admission.chain_digest.parse::<Digest32>()?.is_zero(),
        "original Initial completion does not match the exact submitted request"
    );
    let ObjectivePublicationOutcome::Compiled {
        objective_digest,
        hard_constraint_digest,
    } = &admission.outcome
    else {
        anyhow::bail!("original Initial completion requires its original Compiled publication");
    };
    anyhow::ensure!(
        objective_digest.parse::<Digest32>()? == original.objective
            && !hard_constraint_digest.parse::<Digest32>()?.is_zero()
            && data.circuit_revision > 0
            && !data.circuit_history_digest.parse::<Digest32>()?.is_zero()
            && data.observation.run_id == request.body.run_id
            && data.observation.source_history_digest == data.circuit_history_digest
            && !data
                .observation
                .source_publication_digest
                .parse::<Digest32>()?
                .is_zero()
            && data.observation.decision_sequence > 0
            && !data
                .observation
                .decision_chain_digest
                .parse::<Digest32>()?
                .is_zero(),
        "original Initial successful Circuit trace and Source observation differ"
    );
    if let OriginalObjectiveAcknowledgement::Acknowledged { receipt } = acknowledgement {
        anyhow::ensure!(
            receipt.run_id == admission.run_id
                && receipt.objective_digest == *objective_digest
                && receipt.hard_constraint_digest == *hard_constraint_digest
                && receipt.publication_digest == admission.publication_digest
                && receipt.chain_digest == admission.chain_digest,
            "original Initial completion differs from the retained Objective ACK"
        );
    }
    Ok(())
}

#[test]
fn ordinary_initial_ack_loss_retains_error_data_without_an_admission() -> anyhow::Result<()> {
    let error = crate::AgentdError::Protocol("original read-response timeout".into());
    let original = error.to_string();
    let acknowledgement = OriginalObjectiveAcknowledgement::from_reply(
        ObjectiveStartReplyV1::AcknowledgementLost(error),
        "original-run",
        Digest32::of_bytes(b"original objective"),
    )?;
    pretty_assertions::assert_eq!(
        serde_json::to_value(&acknowledgement)?,
        serde_json::json!({"type":"acknowledgement_lost", "error":original})
    );
    let failure = Err::<(), _>(anyhow::anyhow!("original Source corrupt"))
        .with_context(|| acknowledgement.observation_context())
        .unwrap_err();
    let failure = format!("{failure:#}");
    assert!(failure.contains(&original));
    assert!(failure.contains("original Source corrupt"));
    Ok(())
}

#[test]
fn ordinary_initial_conflict_is_not_a_pending_or_lost_ack() {
    let conflict = Digest32::of_bytes(b"actual conflict").to_string();
    let failure = OriginalObjectiveAcknowledgement::from_reply(
        ObjectiveStartReplyV1::Completed(ObjectiveStartOutcome::Conflict {
            run_id: "original-conflicted-run".into(),
            conflict_digest: conflict.clone(),
        }),
        "original-conflicted-run",
        Digest32::of_bytes(b"original objective"),
    )
    .unwrap_err();
    assert!(failure.to_string().contains("original-conflicted-run"));
    assert!(failure.to_string().contains(&conflict));
}
