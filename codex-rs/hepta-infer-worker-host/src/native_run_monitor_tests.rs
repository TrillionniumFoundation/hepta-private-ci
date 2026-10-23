use super::*;
use codex_hepta_contracts::AgentId;
use std::time::Duration;

fn handoff() -> (
    NativeWorkerConfig,
    NativeIntelligenceRunBinding,
    AgentRunReceipt,
) {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
    fence.extend_from_slice(agent_id.as_str().as_bytes());
    fence.extend_from_slice(&1_u64.to_be_bytes());
    fence.extend_from_slice(&2_u64.to_be_bytes());
    let expected = NativeIntelligenceRunBinding {
        run_id: "run:original-cancellation".into(),
        expected_revision: 2,
        context_digest: Digest32::of_bytes(b"original-context").to_string(),
        envelope_digest: Digest32::of_bytes(b"original-compiled-envelope").to_string(),
    };
    let receipt = AgentRunReceipt {
        run_id: expected.run_id.clone(),
        revision: expected.expected_revision,
        phase: AgentRunPhase::ContextAttached,
        context_digest: Some(expected.context_digest.clone()),
        compilation_receipt_digest: Some(expected.envelope_digest.clone()),
        authority_epoch: 7,
        generation: 2,
        fence_digest: Digest32::of_bytes(&fence).to_string(),
        deadline_ms: 40_000,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: false,
    };
    (
        NativeWorkerConfig {
            agentd_socket: "/fixture/agentd.sock".into(),
            agent_id,
            generation: 1,
            model: "fixture-model".into(),
            timeout: Duration::from_secs(20),
        },
        expected,
        receipt,
    )
}

fn dispatched() -> (RetainedIntelligenceRun, AgentRunReceipt) {
    let (config, expected, mut receipt) = handoff();
    let mut retained =
        RetainedIntelligenceRun::from_handoff(&config, &expected, receipt.clone()).unwrap();
    receipt.phase = AgentRunPhase::Dispatched;
    receipt.revision += 1;
    receipt.idempotent = false;
    retained.accept_dispatch(&receipt).unwrap();
    (retained, receipt)
}

#[test]
fn spawn_one_retains_run_two_and_dispatch_cannot_be_reused() {
    let (config, expected, mut receipt) = handoff();
    let mut retained =
        RetainedIntelligenceRun::from_handoff(&config, &expected, receipt.clone()).unwrap();
    receipt.generation = 1;
    assert!(retained.accept_dispatch(&receipt).is_err());
    receipt.generation = 2;
    receipt.phase = AgentRunPhase::Dispatched;
    receipt.revision += 1;
    receipt.idempotent = true;
    assert!(
        retained.accept_dispatch(&receipt).is_err(),
        "idempotent ACK is not a physical-send permit"
    );
    receipt.idempotent = false;
    retained.accept_dispatch(&receipt).unwrap();
    assert_eq!(
        retained.observe(Some(receipt.clone())),
        Ok(RunObservation::Dispatched)
    );
    assert!(retained.accept_dispatch(&receipt).is_err());
    assert_eq!(retained.revision(), receipt.revision);
}

#[test]
fn every_retained_identity_field_and_revision_is_checked_without_advancing() {
    let mutations: &[fn(&mut AgentRunReceipt)] = &[
        |r| r.run_id.push_str("-other"),
        |r| r.context_digest = Some(Digest32::of_bytes(b"other-context").to_string()),
        |r| r.compilation_receipt_digest = Some(Digest32::of_bytes(b"other-envelope").to_string()),
        |r| r.authority_epoch += 1,
        |r| r.generation += 1,
        |r| r.fence_digest = Digest32::of_bytes(b"other-fence").to_string(),
        |r| r.deadline_ms += 1,
        |r| r.revision -= 1,
        |r| r.terminal_observed = true,
    ];
    for mutate in mutations {
        let (mut retained, mut receipt) = dispatched();
        let before = retained.clone();
        mutate(&mut receipt);
        assert!(retained.observe(Some(receipt)).is_err());
        assert_eq!(retained, before);
    }
}

#[test]
fn missing_indeterminate_and_terminal_projection_never_become_a_terminal_witness() {
    let (mut retained, receipt) = dispatched();
    let before = retained.clone();
    assert!(retained.observe(None).is_err());
    for phase in [
        AgentRunPhase::Admitted,
        AgentRunPhase::ContextAttached,
        AgentRunPhase::Indeterminate,
        AgentRunPhase::Cancelled,
        AgentRunPhase::Succeeded,
        AgentRunPhase::Failed,
    ] {
        let mut changed = receipt.clone();
        changed.phase = phase;
        changed.revision += 1;
        changed.terminal_observed = matches!(
            phase,
            AgentRunPhase::Cancelled | AgentRunPhase::Succeeded | AgentRunPhase::Failed
        );
        assert!(retained.observe(Some(changed)).is_err());
        assert_eq!(retained, before);
    }
}

#[test]
fn external_cancelling_is_one_checked_revision_transition() {
    let (mut retained, mut receipt) = dispatched();
    let before = retained.clone();
    receipt.phase = AgentRunPhase::Cancelling;
    receipt.cancel_reason = Some("original operator cancellation".into());
    receipt.cancel_ack_deadline_ms = Some(23_000);
    assert!(
        retained.observe(Some(receipt.clone())).is_err(),
        "same revision is mixed"
    );
    assert_eq!(retained, before);
    receipt.revision += 1;
    assert_eq!(
        retained.observe(Some(receipt.clone())),
        Ok(RunObservation::Cancelling)
    );
    assert!(
        retained.observe(Some(receipt)).is_err(),
        "no second cancellation consumption"
    );
}

#[test]
fn rejected_cancel_receipts_cannot_guess_or_roll_back_the_run_revision() {
    let (retained, receipt) = dispatched();
    for (phase, disposition, increment) in [
        (
            AgentRunPhase::Indeterminate,
            AgentCancellationDisposition::CancellingAfterDispatch,
            1,
        ),
        (
            AgentRunPhase::Cancelling,
            AgentCancellationDisposition::CancellingAfterDispatch,
            0,
        ),
        (
            AgentRunPhase::Cancelling,
            AgentCancellationDisposition::CancellingAfterDispatch,
            2,
        ),
        (
            AgentRunPhase::Cancelled,
            AgentCancellationDisposition::CancelledBeforeDispatch,
            1,
        ),
    ] {
        let mut candidate = retained.clone();
        let mut changed = receipt.clone();
        changed.phase = phase;
        changed.revision += increment;
        changed.cancel_reason = Some("operator".into());
        changed.cancel_ack_deadline_ms = Some(23_000);
        changed.terminal_observed = phase == AgentRunPhase::Cancelled;
        assert!(
            candidate
                .accept_cancellation(&AgentRunCancellation {
                    disposition,
                    receipt: changed
                })
                .is_err()
        );
        assert_eq!(candidate, retained);
    }
}
