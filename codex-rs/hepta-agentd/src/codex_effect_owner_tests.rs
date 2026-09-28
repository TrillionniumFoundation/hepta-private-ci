use super::*;
use std::io::Write;
use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.1".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 2,
    }
}
fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.1".to_string(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 7,
        generation: 3,
        fence_digest: "9".repeat(64),
        deadline_ms: 10_000,
    }
}
fn binding() -> CodexEffectBinding {
    CodexEffectBinding {
        run_id: "run.1".to_string(),
        generation: 3,
        expected_revision: 2,
        request_digest: "a".repeat(64),
        context_digest: "7".repeat(64),
        compilation_receipt_digest: "8".repeat(64),
    }
}
fn open(path: &Path) -> AgentRunCoordinator {
    let mut owner = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    owner.open_effect_frontier(path).unwrap();
    owner
}
fn admitted(path: &Path) -> AgentRunCoordinator {
    let mut owner = open(path);
    let value = snapshot();
    owner.start_run(100, value.clone()).unwrap();
    owner
        .attach_context(
            200,
            1,
            ContextAttachment {
                run_id: value.run_id,
                request_digest: value.request_digest,
                objective_digest: value.objective_digest,
                body_digest: value.body_digest,
                artifact_set_digest: value.artifact_set_digest,
                authority_epoch: value.authority_epoch,
                generation: value.generation,
                fence_digest: value.fence_digest,
                deadline_ms: value.deadline_ms,
                context_digest: "7".repeat(64),
                compilation_receipt_digest: "8".repeat(64),
            },
        )
        .unwrap();
    owner
}
fn temp() -> tempfile::TempDir {
    let value = tempfile::tempdir().unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(value.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    value
}

#[test]
fn abort_is_durable_negative_not_provider_terminal_and_ack_replays_exactly() {
    let temp = temp();
    let path = temp.path().join("effects");
    let mut owner = admitted(&path);
    let receipt = owner
        .decide_codex_effect(
            20_000,
            binding(),
            CodexEffectDecision::AbortedBeforeEffect,
            Some("cancelled".to_string()),
        )
        .unwrap();
    assert_eq!(
        receipt,
        CodexEffectReceipt {
            binding: binding(),
            decision: CodexEffectDecision::AbortedBeforeEffect,
            reason: Some("cancelled".to_string()),
            owner_revision: 3,
            idempotent: false
        }
    );
    let terminal = owner.run("run.1").unwrap();
    assert_eq!(terminal.phase, RunPhase::Cancelled);
    assert!(!terminal.terminal_observed);
    assert_eq!(owner.active_run_count(), 0);
    drop(owner);
    let mut owner = open(&path);
    let mut expected = receipt;
    expected.idempotent = true;
    assert_eq!(
        owner
            .decide_codex_effect(
                30_000,
                binding(),
                CodexEffectDecision::AbortedBeforeEffect,
                Some("cancelled".to_string())
            )
            .unwrap(),
        expected
    );
    assert!(
        owner.start_run(100, snapshot()).is_err(),
        "a retained operation identity cannot be reused"
    );
    assert!(
        owner
            .decide_codex_effect(300, binding(), CodexEffectDecision::Entered, None)
            .is_err()
    );
    assert!(
        owner
            .decide_codex_effect(
                300,
                binding(),
                CodexEffectDecision::AbortedBeforeEffect,
                Some("different".to_string())
            )
            .is_err()
    );
}

#[test]
fn owner_enter_survives_restart_and_never_issues_a_second_send_permit() {
    let temp = temp();
    let path = temp.path().join("effects");
    let mut owner = admitted(&path);
    let receipt = owner
        .decide_codex_effect(300, binding(), CodexEffectDecision::Entered, None)
        .unwrap();
    assert!(!receipt.idempotent);
    drop(owner);
    let mut owner = open(&path);
    let duplicate = owner
        .decide_codex_effect(400, binding(), CodexEffectDecision::Entered, None)
        .unwrap();
    assert!(duplicate.idempotent);
    assert_eq!(duplicate.binding, receipt.binding);
    assert!(
        owner
            .decide_codex_effect(
                400,
                binding(),
                CodexEffectDecision::AbortedBeforeEffect,
                Some("unsent".to_string())
            )
            .is_err()
    );
    assert!(owner.start_run(100, snapshot()).is_err());
}

#[test]
fn exact_generation_revision_payload_and_context_are_required() {
    let temp = temp();
    let path = temp.path().join("effects");
    let mut owner = admitted(&path);
    for variant in 0..5 {
        let mut wrong = binding();
        match variant {
            0 => wrong.generation += 1,
            1 => wrong.expected_revision += 1,
            2 => wrong.context_digest = "b".repeat(64),
            3 => wrong.compilation_receipt_digest = "c".repeat(64),
            4 => wrong.run_id = "other".to_string(),
            _ => unreachable!(),
        }
        assert!(
            owner
                .decide_codex_effect(300, wrong, CodexEffectDecision::Entered, None)
                .is_err()
        );
    }
    owner
        .decide_codex_effect(300, binding(), CodexEffectDecision::Entered, None)
        .unwrap();
    let mut drift = binding();
    drift.request_digest = "d".repeat(64);
    assert!(
        owner
            .decide_codex_effect(300, drift, CodexEffectDecision::Entered, None)
            .is_err()
    );
}

#[test]
fn expiry_blocks_enter_but_not_a_definitive_abort() {
    let temp = temp();
    let path = temp.path().join("effects");
    let mut owner = admitted(&path);
    assert!(
        owner
            .decide_codex_effect(10_000, binding(), CodexEffectDecision::Entered, None)
            .is_err()
    );
    owner
        .decide_codex_effect(
            10_001,
            binding(),
            CodexEffectDecision::AbortedBeforeEffect,
            Some("deadline".to_string()),
        )
        .unwrap();
}

#[test]
fn concurrent_abort_and_enter_have_exactly_one_durable_winner() {
    for _ in 0..16 {
        let temp = temp();
        let path = temp.path().join("effects");
        let owner = Arc::new(Mutex::new(admitted(&path)));
        let barrier = Arc::new(Barrier::new(3));
        let tasks = [
            CodexEffectDecision::Entered,
            CodexEffectDecision::AbortedBeforeEffect,
        ]
        .map(|decision| {
            let owner = Arc::clone(&owner);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                owner.lock().unwrap().decide_codex_effect(
                    300,
                    binding(),
                    decision,
                    (decision == CodexEffectDecision::AbortedBeforeEffect)
                        .then(|| "cancelled".to_string()),
                )
            })
        });
        barrier.wait();
        let winners: Vec<_> = tasks
            .into_iter()
            .map(|task| task.join().unwrap())
            .filter_map(Result::ok)
            .collect();
        assert_eq!(winners.len(), 1);
        drop(owner);
        let mut reopened = open(&path);
        let won = &winners[0];
        assert!(
            reopened
                .decide_codex_effect(400, won.binding.clone(), won.decision, won.reason.clone())
                .unwrap()
                .idempotent
        );
    }
}

#[test]
fn duplicate_writer_legacy_entry_and_corrupt_tail_fail_closed() {
    let temp = temp();
    let path = temp.path().join("effects");
    let mut owner = admitted(&path);
    let mut duplicate = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    assert!(duplicate.open_effect_frontier(&path).is_err());
    owner.mark_dispatched(300, "run.1", 2).unwrap();
    drop(owner);
    let mut owner = open(&path);
    assert!(
        owner
            .decide_codex_effect(
                400,
                binding(),
                CodexEffectDecision::AbortedBeforeEffect,
                Some("unsent".to_string())
            )
            .is_err()
    );
    drop(owner);
    std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(b"{torn")
        .unwrap();
    let mut owner = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    assert!(owner.open_effect_frontier(&path).is_err());
}

// The parent kills this real native child after it signals a reached cut. No
// environment is mutated in the test process and no failpoint exists in release.
#[test]
fn codex_effect_native_crash_child() {
    let Ok(path) = std::env::var("HEPTA_CODEX_OWNER_CHILD_PATH") else {
        return;
    };
    let path = std::path::PathBuf::from(path);
    let mut owner = admitted(&path);
    let action = std::env::var("HEPTA_CODEX_OWNER_CHILD_ACTION").unwrap();
    let decision = if action == "enter" {
        CodexEffectDecision::Entered
    } else {
        CodexEffectDecision::AbortedBeforeEffect
    };
    owner
        .decide_codex_effect(
            300,
            binding(),
            decision,
            (decision == CodexEffectDecision::AbortedBeforeEffect).then(|| "cancelled".to_string()),
        )
        .unwrap();
    crate::codex_effect_journal::crash_cut("owner-after-publish");
}

#[test]
fn actual_process_kill_reopen_preserves_all_owner_decision_cuts() {
    use std::io::BufRead;
    use std::io::BufReader;
    use std::process::Command;
    use std::process::Stdio;
    use std::time::Duration;
    for action in ["enter", "abort"] {
        for cut in [
            "owner-before-write",
            "owner-after-write",
            "owner-after-fsync",
            "owner-after-publish",
        ] {
            let temp = temp();
            let path = temp.path().join("effects");
            let mut child = Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "lane_b_runtime::codex_effect::tests::codex_effect_native_crash_child",
                    "--nocapture",
                ])
                .env("HEPTA_CODEX_OWNER_CHILD_PATH", &path)
                .env("HEPTA_CODEX_OWNER_CHILD_ACTION", action)
                .env("HEPTA_CODEX_OWNER_CRASH_CUT", cut)
                .stdout(Stdio::piped())
                .stderr(Stdio::inherit())
                .spawn()
                .unwrap();
            let output = child.stdout.take().unwrap();
            let (tx, rx) = std::sync::mpsc::channel();
            let reader = std::thread::spawn(move || {
                for line in BufReader::new(output).lines() {
                    if line.unwrap().contains("HEPTA_CODEX_CUT_REACHED") {
                        let _ = tx.send(());
                        break;
                    }
                }
            });
            let reached = rx.recv_timeout(Duration::from_secs(15));
            let _ = child.kill();
            let status = child.wait().unwrap();
            reader.join().unwrap();
            assert!(
                reached.is_ok(),
                "native child did not reach {cut}: {status}"
            );
            let mut reopened = open(&path);
            if cut == "owner-before-write" {
                assert!(!reopened.effects.as_ref().unwrap().contains("run.1"));
            } else {
                let decision = if action == "enter" {
                    CodexEffectDecision::Entered
                } else {
                    CodexEffectDecision::AbortedBeforeEffect
                };
                let receipt = reopened
                    .decide_codex_effect(
                        400,
                        binding(),
                        decision,
                        (decision == CodexEffectDecision::AbortedBeforeEffect)
                            .then(|| "cancelled".to_string()),
                    )
                    .unwrap();
                assert!(
                    receipt.idempotent,
                    "reopening never returns a fresh send permit"
                );
            }
        }
    }
}
