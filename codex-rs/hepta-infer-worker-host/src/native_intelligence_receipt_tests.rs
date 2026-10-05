use super::*;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;

const OBSERVED_NOW_MS: u64 = 1000;

fn completed() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "model-a".to_string(),
        model_provider: "provider-a".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "observed prefix and recovered suffix".to_string(),
        observed_output_tokens: None,
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some("a".repeat(64)),
    }
}

fn handoff() -> NativeIntelligenceRunBinding {
    NativeIntelligenceRunBinding {
        run_id: "run-a".to_string(),
        expected_revision: 2,
        context_digest: "b".repeat(64),
        envelope_digest: "c".repeat(64),
    }
}

fn dispatched() -> AgentRunReceipt {
    AgentRunReceipt {
        run_id: "run-a".to_string(),
        revision: 3,
        phase: AgentRunPhase::Dispatched,
        context_digest: Some("b".repeat(64)),
        compilation_receipt_digest: Some("c".repeat(64)),
        authority_epoch: 1,
        generation: 7,
        fence_digest: "d".repeat(64),
        deadline_ms: 61_000,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: true,
    }
}

#[test]
fn owner_lifecycle_epoch_is_independent_and_cannot_advance_the_pinned_cursor() {
    let current = AgentRunReceipt {
        generation: 8,
        ..dispatched()
    };
    // The control connection can be spawn 7 while the observed owner run is 8.
    validate_intelligence_owner_generation(8, 8, &current).unwrap();
    for (pinned, observed, receipt_generation) in
        [(7, 8, 8), (8, 8, 7), (8, 9, 8), (8, 9, 9), (0, 0, 0)]
    {
        let mixed = AgentRunReceipt {
            generation: receipt_generation,
            ..current.clone()
        };
        assert!(validate_intelligence_owner_generation(pinned, observed, &mixed).is_err());
    }
}

#[test]
fn intelligence_completed_after_local_stop_never_publishes_success() {
    for (boundary_status, expected_phase) in [
        (NativeBoundaryStatus::Succeeded, AgentRunPhase::Succeeded),
        (NativeBoundaryStatus::Failed, AgentRunPhase::Failed),
        (NativeBoundaryStatus::Cancelled, AgentRunPhase::Cancelled),
        (NativeBoundaryStatus::Interrupted, AgentRunPhase::Cancelled),
        (NativeBoundaryStatus::TimedOut, AgentRunPhase::Failed),
        (NativeBoundaryStatus::Quarantined, AgentRunPhase::Failed),
    ] {
        let output = NativeRunOutput {
            boundary_status,
            ..completed()
        };
        assert_eq!(
            intelligence_terminal_phase(&output).unwrap(),
            expected_phase
        );
    }
    let denied = NativeRunOutput {
        stop_reason: Some("terminal publication requires reconciliation".to_string()),
        ..completed()
    };
    assert_eq!(
        intelligence_terminal_phase(&denied).unwrap(),
        AgentRunPhase::Failed
    );
    let unknown = NativeRunOutput {
        status: NativeRunStatus::Indeterminate,
        terminal_observed: false,
        ..completed()
    };
    assert!(intelligence_terminal_phase(&unknown).is_err());
}

#[test]
fn owner_cancellation_advances_only_the_exact_cursor_and_denies_execution() {
    let binding = handoff();
    let mut revision = 3;
    verify_intelligence_receipt(7, &binding, &mut revision, &dispatched(), OBSERVED_NOW_MS)
        .unwrap();
    let cancelling = AgentRunReceipt {
        revision: 4,
        phase: AgentRunPhase::Cancelling,
        cancel_reason: Some("operator cancelled at the owner".to_string()),
        ..dispatched()
    };
    assert_eq!(
        verify_intelligence_receipt(7, &binding, &mut revision, &cancelling, OBSERVED_NOW_MS),
        Err(LOCAL_CANCELLED.to_string())
    );
    assert_eq!(revision, 4);
    // Terminal observation must use the accepted cancellation revision, while
    // physical Completed remains separate from the local Cancelled boundary.
    let completed_after_cancel = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Cancelled,
        ..completed()
    };
    assert_eq!(
        intelligence_terminal_phase(&completed_after_cancel).unwrap(),
        AgentRunPhase::Cancelled
    );
}

#[test]
fn newer_or_mixed_owner_receipts_never_replace_the_dispatch_cursor() {
    for field in 0..6 {
        let mut receipt = dispatched();
        match field {
            0 => receipt.run_id = "other-run".to_string(),
            1 => receipt.generation += 1,
            2 => receipt.context_digest = Some("d".repeat(64)),
            3 => receipt.compilation_receipt_digest = Some("e".repeat(64)),
            4 => receipt.revision += 1,
            _ => receipt.phase = AgentRunPhase::Succeeded,
        }
        let mut revision = 3;
        assert!(
            verify_intelligence_receipt(7, &handoff(), &mut revision, &receipt, OBSERVED_NOW_MS)
                .is_err()
        );
        assert_eq!(revision, 3);
    }
    let mut stale = dispatched();
    stale.revision = 2;
    stale.phase = AgentRunPhase::Cancelling;
    stale.cancel_reason = Some("stale cancellation".to_string());
    let mut revision = 3;
    assert!(
        verify_intelligence_receipt(7, &handoff(), &mut revision, &stale, OBSERVED_NOW_MS).is_err()
    );
    assert_eq!(revision, 3);
}

#[test]
fn owner_deadline_denies_a_still_dispatched_receipt_before_monitor_tick() {
    let expired = AgentRunReceipt {
        deadline_ms: 999,
        ..dispatched()
    };
    let mut revision = 3;
    assert_eq!(
        verify_intelligence_receipt(7, &handoff(), &mut revision, &expired, OBSERVED_NOW_MS),
        Err(LOCAL_DEADLINE_ELAPSED.to_string())
    );
    assert_eq!(revision, 3);
}

#[test]
fn recovery_accepts_owner_commit_before_local_settlement_after_deadline() {
    // Agentd terminal publication can commit just before the worker crashes
    // without writing local settlement. Recovery observes that existing effect;
    // it is not asking for another live dispatch permit.
    let owner_committed = AgentRunReceipt {
        revision: 4,
        phase: AgentRunPhase::Succeeded,
        terminal_observed: true,
        deadline_ms: 999,
        ..dispatched()
    };
    assert_eq!(
        matches_intelligence_terminal_receipt(7, &handoff(), &owner_committed, &completed()),
        Ok(true)
    );
    verify_intelligence_recovery_receipt(7, &handoff(), &owner_committed, &completed(), || {
        panic!("an exact historical terminal must not read the live clock")
    })
    .unwrap();
    let mut revision = 3;
    assert!(
        verify_intelligence_receipt(
            7,
            &handoff(),
            &mut revision,
            &owner_committed,
            OBSERVED_NOW_MS
        )
        .is_err()
    );
    assert_eq!(revision, 3);
    let denied = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Quarantined,
        owner_authority: NativeOwnerAuthority::Lost {
            reason: "previous durable owner loss".to_string(),
        },
        ..completed()
    };
    assert!(
        verify_intelligence_recovery_receipt(7, &handoff(), &owner_committed, &denied, || Ok(
            OBSERVED_NOW_MS
        ))
        .is_err()
    );
    assert!(
        verify_intelligence_recovery_receipt(8, &handoff(), &owner_committed, &completed(), || Ok(
            OBSERVED_NOW_MS
        ))
        .is_err()
    );
}

#[test]
fn recovery_matches_owner_publication_of_denied_provider_terminals() {
    for boundary_status in [
        NativeBoundaryStatus::Failed,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::Interrupted,
    ] {
        let output = NativeRunOutput {
            boundary_status,
            stop_reason: Some("local boundary was denied before provider completion".to_string()),
            ..completed()
        };
        let owner_committed = AgentRunReceipt {
            revision: 4,
            phase: intelligence_terminal_phase(&output).unwrap(),
            terminal_observed: true,
            deadline_ms: 999,
            ..dispatched()
        };
        verify_intelligence_recovery_receipt(7, &handoff(), &owner_committed, &output, || {
            Ok(OBSERVED_NOW_MS)
        })
        .unwrap();
        let mismatched = AgentRunReceipt {
            phase: AgentRunPhase::Succeeded,
            ..owner_committed.clone()
        };
        assert!(
            verify_intelligence_recovery_receipt(7, &handoff(), &mismatched, &output, || Ok(
                OBSERVED_NOW_MS
            ))
            .is_err()
        );
        for invalid in [
            AgentRunReceipt {
                revision: 3,
                ..owner_committed.clone()
            },
            AgentRunReceipt {
                terminal_observed: false,
                ..owner_committed.clone()
            },
            AgentRunReceipt {
                context_digest: Some("d".repeat(64)),
                ..owner_committed.clone()
            },
            AgentRunReceipt {
                compilation_receipt_digest: Some("e".repeat(64)),
                ..owner_committed.clone()
            },
            AgentRunReceipt {
                run_id: "other-run".to_string(),
                ..owner_committed.clone()
            },
        ] {
            assert!(
                verify_intelligence_recovery_receipt(7, &handoff(), &invalid, &output, || Ok(
                    OBSERVED_NOW_MS
                ))
                .is_err()
            );
        }
        let nonterminal = NativeRunOutput {
            status: NativeRunStatus::Indeterminate,
            terminal_observed: false,
            ..output
        };
        assert!(
            verify_intelligence_recovery_receipt(
                7,
                &handoff(),
                &owner_committed,
                &nonterminal,
                || Ok(OBSERVED_NOW_MS)
            )
            .is_err()
        );
    }
    let output = NativeRunOutput {
        stop_reason: Some("completed with an unresolved publication note".to_string()),
        ..completed()
    };
    let owner_committed = AgentRunReceipt {
        revision: 4,
        phase: AgentRunPhase::Failed,
        terminal_observed: true,
        ..dispatched()
    };
    verify_intelligence_recovery_receipt(7, &handoff(), &owner_committed, &output, || {
        Ok(OBSERVED_NOW_MS)
    })
    .unwrap();
}
