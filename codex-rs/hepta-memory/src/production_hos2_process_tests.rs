//! SIGKILL boundaries around the actual SQLite writer and FinalUse dispatcher.

use super::*;
use futures::StreamExt;
use pretty_assertions::assert_eq;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::time::Instant;

struct ChildOwner(Child);

impl ChildOwner {
    fn kill_and_reap(&mut self) -> TestResult<ExitStatus> {
        self.0.kill()?;
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if let Some(status) = self.0.try_wait()? {
                return Ok(status);
            }
            if Instant::now() >= deadline {
                return Err("killed fixture child did not exit within 5s".into());
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

impl Drop for ChildOwner {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let deadline = Instant::now() + Duration::from_secs(5);
        while matches!(self.0.try_wait(), Ok(None)) && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

#[tokio::test]
async fn hos2_kill_child() -> TestResult {
    let Some(root) = std::env::var_os("HEPTA_HOS2_REAUTH_TEST_ROOT") else {
        return Ok(());
    };
    let root = PathBuf::from(root);
    let phase = std::env::var("HEPTA_HOS2_REAUTH_TEST_PHASE")?;
    let stage = std::env::var("HEPTA_HOS2_REAUTH_TEST_STAGE")?;
    let fixture = Fixture::open(&root).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    fs::write(root.join("queued.json"), serde_json::to_vec(&queued)?)?;
    if phase == "after-effect" {
        let (binding, grant) = fixture.signed(&queued, /*nonce*/ 1).await?;
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &grant, &binding, queued)
            .await?;
    } else {
        let claim = match stage.as_str() {
            "claim" => fixture.reject_claim(&queued).await?,
            "entry" => {
                let claim = fixture
                    .writer
                    .claim_dispatch_lease(&queued, /*lease_duration_ms*/ 5_000)
                    .await?;
                let (binding, grant) = fixture.signed(&queued, /*nonce*/ 1).await?;
                fs::write(root.join("entered-grant.json"), serde_json::to_vec(&grant)?)?;
                fixture.clock.calls.store(0, Ordering::SeqCst);
                fixture.clock.expire_at_entry.store(true, Ordering::SeqCst);
                assert!(matches!(
                    fixture
                        .dispatcher
                        .dispatch(&fixture.writer, &grant, &binding, queued.clone())
                        .await,
                    Err(ProductionWriterError::FinalUse(_))
                ));
                fixture.clock.expire_at_entry.store(false, Ordering::SeqCst);
                assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
                claim
            }
            _ => return Err("invalid fixed rejection stage".into()),
        };
        fixture.wait_eligible(&claim).await?;
        let (binding, grant) = fixture.signed(&queued, /*nonce*/ 2).await?;
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &grant, &binding, queued)
            .await?;
    }
    Err(format!("child did not stop at required checkpoint {phase}").into())
}

#[tokio::test]
async fn killed_owner_recovers_proof_boundaries_without_resending_unknown_d() -> TestResult {
    let cases = [
        ("claim", "before-proof"),
        ("claim", "after-proof"),
        ("entry", "before-proof"),
        ("entry", "after-proof"),
        ("claim", "new-claimed"),
        ("entry", "new-claimed"),
        ("claim", "new-entered"),
        ("entry", "new-entered"),
        ("claim", "after-effect"),
    ];
    // Every case owns a separate tempdir, SQLite owner and FinalUse store.
    // Crash hooks are configured only in its child process. Overlap at most two
    // real lease waits; retain every SIGKILL boundary and the whole-test timeout.
    let mut pending = futures::stream::iter(cases)
        .map(|(stage, phase)| recover_killed_owner_at_boundary(stage, phase))
        .buffer_unordered(/*n*/ 2);
    while let Some(result) = pending.next().await {
        result?;
    }
    Ok(())
}

async fn recover_killed_owner_at_boundary(stage: &str, phase: &str) -> TestResult {
    let started = Instant::now();
    eprintln!("hos2 recovery {stage}/{phase}: starting");
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let log_path = root.join("child.log");
    let log = fs::File::create(&log_path)?;
    let stderr = log.try_clone()?;
    let mut child = ChildOwner(
        Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "production_writer::hos2_tests::process_tests::hos2_kill_child",
                "--nocapture",
                "--test-threads=1",
            ])
            .env("HEPTA_HOS2_REAUTH_TEST_ROOT", &root)
            .env("HEPTA_HOS2_REAUTH_TEST_PHASE", phase)
            .env("HEPTA_HOS2_REAUTH_TEST_STAGE", stage)
            .env("HEPTA_HOS2_REAUTH_TEST_READY", root.join("ready"))
            .stdin(Stdio::null())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(stderr))
            .spawn()?,
    );
    let deadline = Instant::now() + Duration::from_secs(45);
    loop {
        if fs::read_to_string(root.join("ready")).ok().as_deref() == Some(phase) {
            break;
        }
        if let Some(status) = child.0.try_wait()? {
            return Err(format!(
                "child exited at {phase} before its durable checkpoint: {status}; {}",
                fs::read_to_string(&log_path)?
            )
            .into());
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "child timed out at {phase}; {}",
                fs::read_to_string(&log_path)?
            )
            .into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    eprintln!(
        "hos2 recovery {stage}/{phase}: checkpoint after {:?}",
        started.elapsed()
    );
    assert!(
        !child.kill_and_reap()?.success(),
        "fixture must be killed, not cleanly closed"
    );
    let queued: ProductionQueuedReceipt =
        serde_json::from_slice(&fs::read(root.join("queued.json"))?)?;
    let reopened = Fixture::open(&root).await?;
    eprintln!(
        "hos2 recovery {stage}/{phase}: reopened after {:?}",
        started.elapsed()
    );
    assert_eq!(
        reopened.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    if stage == "entry" {
        let old: SignedFinalUseGrant =
            serde_json::from_slice(&fs::read(root.join("entered-grant.json"))?)?;
        assert!(
            matches!(
                reopened.authority.claim(&old, &old.grant.binding),
                Err(FinalUseError::AlreadyClaimed)
            ),
            "the durable FinalUse nonce must survive a killed entry rejection"
        );
    }
    let proofs: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_operation_pre_boundary_rejections")
            .fetch_one(&reopened.writer.store.pool)
            .await?;
    let head: String = sqlx::query_scalar("SELECT claim_state FROM cognitive_operation_dispatch_claims ORDER BY claim_sequence DESC LIMIT 1")
        .fetch_one(&reopened.writer.store.pool).await?;
    if proofs == 1 {
        let stored_stage: String = sqlx::query_scalar("SELECT json_extract(proof_json, '$.stage') FROM cognitive_operation_pre_boundary_rejections")
            .fetch_one(&reopened.writer.store.pool).await?;
        assert_eq!(stored_stage, stage);
    }
    match phase {
        "after-proof" => {
            assert_eq!((proofs, head.as_str()), (1, "settled"));
            let eligible: i64 = sqlx::query_scalar("SELECT next_eligible_at_unix_ms FROM cognitive_operation_dispatch_claims ORDER BY claim_sequence DESC LIMIT 1")
                .fetch_one(&reopened.writer.store.pool).await?;
            let delay = u64::try_from(eligible)?.saturating_sub(now_unix_ms()?);
            assert!(delay <= 6_000);
            eprintln!("hos2 recovery {stage}/{phase}: waiting {delay}ms for original eligibility");
            tokio::time::sleep(Duration::from_millis(delay + 1)).await;
            let pending = reopened
                .writer
                .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
                .await?;
            assert_eq!(pending.len(), 1);
            assert_eq!(
                (&pending[0].outbox_id, &pending[0].payload_json),
                (&queued.outbox_id, &queued.payload_json)
            );
            let (binding, fresh) = reopened.signed(&pending[0], /*nonce*/ 3).await?;
            assert_eq!(
                reopened
                    .dispatcher
                    .dispatch(&reopened.writer, &fresh, &binding, pending[0].clone())
                    .await?
                    .state,
                LocalOutcomeState::Committed
            );
            assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 1);
        }
        "after-effect" => {
            assert_eq!((proofs, head.as_str()), (0, "entered"));
            assert!(
                reopened
                    .writer
                    .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
                    .await?
                    .is_empty()
            );
            assert_eq!(
                reopened
                    .dispatcher
                    .reconcile(&reopened.writer, /*limit*/ 8)
                    .await?,
                1
            );
            assert_eq!(
                reopened.writer.status(OPERATION).await?,
                LocalOutcomeState::Committed
            );
            assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 0);
        }
        "before-proof" | "new-claimed" | "new-entered" => {
            let expected = match phase {
                "before-proof" => (0, "entered"),
                "new-claimed" => (1, "claimed"),
                _ => (1, "entered"),
            };
            assert_eq!((proofs, head.as_str()), expected);
            assert!(
                reopened
                    .writer
                    .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
                    .await?
                    .is_empty()
            );
            let (binding, fresh) = reopened.signed(&queued, /*nonce*/ 3).await?;
            assert!(
                reopened
                    .dispatcher
                    .dispatch(&reopened.writer, &fresh, &binding, queued)
                    .await
                    .is_err()
            );
            assert_eq!(
                reopened.writer.status(OPERATION).await?,
                LocalOutcomeState::Indeterminate
            );
            assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 0);
            assert!(!reopened.device.path.exists());
        }
        _ => return Err("unrecognized fixed crash boundary".into()),
    }
    eprintln!(
        "hos2 recovery {stage}/{phase}: completed after {:?}",
        started.elapsed()
    );
    Ok(())
}
