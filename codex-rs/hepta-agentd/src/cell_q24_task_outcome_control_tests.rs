//! Actual task, witnessed Ledger and private UDS; all role keys are explicit
//! engineering fixtures. These cases do not qualify a Root deployment or B.

use codex_hepta_agent_protocol::AGENTD_Q24_ORIGINAL_OUTCOME_CAPABILITY;
use codex_hepta_agent_protocol::MAX_Q24_OUTCOME_PREIMAGE_BYTES;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeReceiptV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeRequestV1;
use codex_uds::UnixStream;
use ed25519_dalek::Signer;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio_util::sync::CancellationToken;

use super::*;
use crate::AgentdClient;
use crate::AgentdControlServer;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AgentdState;
use crate::cell_q24_task_ledger::control::encode;

struct Control {
    client: AgentdClient,
    cancel: CancellationToken,
    worker: tokio::task::JoinHandle<Result<(), crate::AgentdError>>,
}

impl Control {
    async fn open(f: &mut Fixture) -> anyhow::Result<Self> {
        let mut config = f.session.take_configuration();
        if let Some(producer) = config.take_original_q24_outcome_control() {
            AgentdState::attach_original_q24_outcome_control(&f.session.runtime.state, producer)?;
        }
        drop(config);
        let cancel = CancellationToken::new();
        let server = AgentdControlServer::bind(
            f.session.runtime.identity.control_socket.clone(),
            Arc::clone(&f.session.runtime.state),
            cancel.clone(),
        )
        .await?;
        Ok(Self {
            client: AgentdClient::new(
                f.session.runtime.identity.control_socket.clone(),
                f.session.runtime.identity.agent_id.clone(),
                f.session.runtime.identity.spawn_generation,
            )?,
            cancel,
            worker: tokio::spawn(server.run()),
        })
    }

    async fn stop(self) -> anyhow::Result<()> {
        self.cancel.cancel();
        self.worker.await??;
        Ok(())
    }
}

async fn raw(
    f: &Fixture,
    spawn_generation: u64,
    request: Q24OriginalTerminalOutcomeRequestV1,
) -> anyhow::Result<AgentdResponse> {
    let stream = UnixStream::connect(&f.session.runtime.identity.control_socket).await?;
    let (reader, mut writer) = tokio::io::split(stream);
    let mut bytes = serde_json::to_vec(&AgentdRequest {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 42,
        spawn_generation,
        method: crate::AgentdMethod::Q24OriginalTerminalOutcome {
            request: Box::new(request),
        },
    })?;
    bytes.push(b'\n');
    writer.write_all(&bytes).await?;
    let mut bytes = Vec::new();
    BufReader::new(reader)
        .take(crate::MAX_CONTROL_FRAME_BYTES + 1)
        .read_until(b'\n', &mut bytes)
        .await?;
    assert!(bytes.len() as u64 <= crate::MAX_CONTROL_FRAME_BYTES);
    assert!(bytes.ends_with(b"\n"));
    Ok(serde_json::from_slice(&bytes)?)
}

#[tokio::test]
async fn original_q24_outcome_control_commits_real_records_and_replays_exactly()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "control-original-outcome",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    assert!(
        control
            .client
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|capability| capability.id == AGENTD_Q24_ORIGINAL_OUTCOME_CAPABILITY)
    );
    assert!(matches!(
        f.producer.readback()?,
        Status::AwaitingOutcome { .. }
    ));
    let task_bytes = f.task_bytes()?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 600);
    let receipt = control
        .client
        .submit_original_q24_terminal_outcome(&outcome, &signed)
        .await?;
    let Status::Complete {
        decision,
        outcome: committed,
    } = f.producer.readback()?
    else {
        anyhow::bail!("real original Outcome not completed");
    };
    assert_eq!(
        receipt,
        Q24OriginalTerminalOutcomeReceiptV1 {
            decision_sequence: decision.sequence.get(),
            decision_chain_digest: decision.chain_digest.to_string(),
            outcome_sequence: committed.sequence.get(),
            outcome_chain_digest: committed.chain_digest.to_string(),
        }
    );
    let after = f.learning_bytes()?;
    assert_eq!(
        control
            .client
            .submit_original_q24_terminal_outcome(&outcome, &signed)
            .await?,
        receipt
    );
    assert_eq!(f.learning_bytes()?, after);
    let mut changed = outcome.clone();
    changed.value = Some(FixedQ32::from_raw(3_i64 << 32));
    let changed_signature = f.sign_outcome(&changed, /*lifetime*/ 600);
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&changed, &changed_signature)
            .await
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, after);
    f.require_task_unchanged(&task_bytes)?;
    control.stop().await?;
    f.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn original_q24_outcome_control_rejects_bad_evidence_without_file_changes()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "control-invalid-outcome",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    let before = f.learning_bytes()?;
    let task_bytes = f.task_bytes()?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 600);
    let original = encode(&outcome, &signed)?;
    let mut signature = signed.clone();
    signature.signature[0] ^= 1;
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&outcome, &signature)
            .await
            .is_err()
    );
    let mut support = outcome.clone();
    support.support_digest = Digest32::of_bytes(b"unrelated task");
    let support_signature = f.sign_outcome(&support, /*lifetime*/ 600);
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&support, &support_signature)
            .await
            .is_err()
    );
    let mut pending = outcome.clone();
    pending.watermark.terminality = OutcomeTerminalityV1::Pending;
    pending.watermark.finalized_at = None;
    let pending_signature = f.sign_outcome(&pending, /*lifetime*/ 600);
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&pending, &pending_signature)
            .await
            .is_err()
    );
    let mut expired = signed.clone();
    expired.issued_at = fixture::now() - 2;
    expired.expires_at = fixture::now() - 1;
    expired.signature = SigningKey::from_bytes(&[2; 32])
        .sign(&expired.signing_bytes())
        .to_bytes();
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&outcome, &expired)
            .await
            .is_err()
    );
    let mut trailing = original.clone();
    trailing.outcome_preimage_hex.push_str("00");
    let mut oversized = original.clone();
    oversized.outcome_preimage_hex = "00".repeat(MAX_Q24_OUTCOME_PREIMAGE_BYTES + 1);
    let mut wrong_trust = original.clone();
    wrong_trust.evidence.trust_digest = Digest32::of_bytes(b"caller chosen trust").to_string();
    for invalid in [trailing, oversized, wrong_trust] {
        let response = raw(&f, f.session.runtime.identity.spawn_generation, invalid).await?;
        assert!(matches!(response.payload, AgentdPayload::Error { .. }));
    }
    let response = raw(
        &f,
        f.session.runtime.identity.spawn_generation + 1,
        original,
    )
    .await?;
    assert!(matches!(response.payload, AgentdPayload::Error { .. }));
    assert_eq!(f.learning_bytes()?, before);
    f.require_task_unchanged(&task_bytes)?;
    control.stop().await?;
    f.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn original_q24_outcome_control_generator_cannot_claim_fixed_observer() -> anyhow::Result<()>
{
    let mut f = Fixture::new(
        "control-generator-observer",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    let before = f.learning_bytes()?;
    let mut outcome = f.outcome();
    outcome.observer = f.signers[0].principal.clone();
    let mut signed = f.sign_outcome(&outcome, /*lifetime*/ 600);
    signed.principal_id = f.signers[0].principal.principal_id.clone();
    signed.signature = SigningKey::from_bytes(&[1; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&outcome, &signed)
            .await
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, before);
    control.stop().await?;
    f.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn original_q24_outcome_control_requires_real_installed_owner() -> anyhow::Result<()> {
    let mut f = Fixture::new(
        "control-no-ledger-owner",
        /*lifetime*/ 600,
        /*automatic*/ false,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    assert!(
        !control
            .client
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|capability| capability.id == AGENTD_Q24_ORIGINAL_OUTCOME_CAPABILITY)
    );
    let before = f.learning_bytes()?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 600);
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&outcome, &signed)
            .await
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, before);
    control.stop().await?;
    f.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn original_q24_outcome_control_refuses_fenced_state_without_append() -> anyhow::Result<()> {
    let mut f = Fixture::new(
        "control-fenced-ledger-owner",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    let before = f.learning_bytes()?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 600);
    f.session.runtime.state.mark_fenced();
    assert!(
        control
            .client
            .submit_original_q24_terminal_outcome(&outcome, &signed)
            .await
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, before);
    control.stop().await?;
    f.session.stop().await?;
    Ok(())
}
