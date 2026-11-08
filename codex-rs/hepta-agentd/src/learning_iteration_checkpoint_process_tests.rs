//! Separate processes retain and reauthenticate an evaluated fixture checkpoint.
//! No producer runs in readers. Fixture keys, local pins and storage are not
//! production custody, independent scientific evaluation or power-loss evidence.
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicUsize;

use pretty_assertions::assert_eq;

use super::*;

#[path = "learning_iteration_checkpoint_test_wire.rs"]
mod wire;

struct ReadOnlyPorts {
    owners: LearningIterationOwnersV1,
    verifier: LearningEvidenceVerifierV1,
    path: PathBuf,
    pinned_head: Digest32,
    refuse_attestations: bool,
    expected_now: u64,
    forbidden_calls: AtomicUsize,
}

impl LearningIterationOwnerPortsV1 for ReadOnlyPorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            let snapshot = wire::DiskCheckpoint::read(&self.path)
                .and_then(|disk| disk.snapshot(request, self.owners.clone(), self.pinned_head))
                .map_err(|_| LearningIterationRuntimeErrorV1::OwnerUnavailable("checkpoint"))?;
            Ok(Some(snapshot))
        })
    }
    fn receipt_attestation<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            assert_eq!(now, self.expected_now);
            if self.refuse_attestations {
                return Err(LearningIterationRuntimeErrorV1::Evidence(
                    SignedEvidenceError::Revoked,
                ));
            }
            wire::DiskCheckpoint::read(&self.path)
                .and_then(|disk| disk.attestation(receipt))
                .map_err(|_| LearningIterationRuntimeErrorV1::OwnerUnavailable("attestation"))
        })
    }
    fn checkpoint<'a>(
        &'a self,
        _head: Digest32,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        self.forbidden_calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "read-only",
            ))
        })
    }
    fn execute_stage<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
        _stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        self.forbidden_calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "read-only",
            ))
        })
    }
    fn prepare_proposal<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.forbidden_calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "read-only",
            ))
        })
    }
}

#[tokio::test]
#[ignore = "explicit subprocess entry used by restored_no_update_authenticates_across_processes"]
async fn learning_checkpoint_process_child() -> anyhow::Result<()> {
    let root = PathBuf::from(
        std::env::var_os("HEPTA_LEARNING_CHECKPOINT_CASE")
            .ok_or_else(|| anyhow::anyhow!("missing explicit test case"))?,
    );
    let mode = std::env::var("HEPTA_LEARNING_CHECKPOINT_MODE")?;
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon.identity);
    let mut fixture = IterationPorts::new(
        /*proposal*/ None,
        LearningEvaluationDispositionV1::NoUpdate,
    );
    let report = if mode == "write" {
        let ports = Arc::new(fixture);
        let (_, owner) = learning_iteration_channel_v1(
            daemon.identity.agent_id.clone(),
            daemon.identity.spawn_generation,
            ports.owners(),
            ports.clone(),
            ports.verifier.clone(),
            /*capacity*/ 2,
        )?;
        let snapshot = owner.process(&daemon.state(), request, || Ok(50)).await?;
        let disk = wire::DiskCheckpoint::capture(&snapshot, &ports).await?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(root.join("checkpoint.json"))?;
        file.write_all(&serde_json::to_vec(&disk)?)?;
        file.sync_all()?;
        fs::File::open(&root)?.sync_all()?;
        serde_json::json!({"pid": std::process::id(), "head": disk.head,
            "in_progress_head": snapshot.receipts[3].predecessor.into_array(),
            "stages": ports.executed.lock().map_err(|_| anyhow::anyhow!("poisoned"))?.len()})
    } else {
        if mode == "revoked" {
            fixture.verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
                scope_digest: digest("plasticity-scope"),
                objective_digest: digest("plasticity-objective"),
                authority_epoch: 7,
                signers: fixture
                    .signing
                    .principals
                    .iter()
                    .zip(&fixture.signing.keys)
                    .enumerate()
                    .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                        principal: principal.clone(),
                        controller_id: id(&format!("plasticity-controller-{index}")),
                        verifying_key: key.verifying_key().to_bytes(),
                        roles: vec![match index {
                            0 => LearningEvidenceRoleV1::Generator,
                            1 => LearningEvidenceRoleV1::Observer,
                            _ => LearningEvidenceRoleV1::Evaluator,
                        }],
                        revoked_at: Some(50),
                    })
                    .collect(),
            })?;
        }
        let pin: [u8; 32] =
            serde_json::from_str(&std::env::var("HEPTA_LEARNING_CHECKPOINT_HEAD")?)?;
        let owners = fixture.owners();
        let verifier = fixture.verifier.clone();
        drop(fixture);
        let now = match mode.as_str() {
            "expired" | "signature-expired" | "owner-revoked-expired" | "in-progress-expired" => {
                100
            }
            "future" => 49,
            _ => 50,
        };
        let ports = Arc::new(ReadOnlyPorts {
            owners,
            verifier,
            path: root.join("checkpoint.json"),
            pinned_head: Digest32::from_array(pin),
            refuse_attestations: matches!(mode.as_str(), "owner-revoked" | "owner-revoked-expired"),
            expected_now: now,
            forbidden_calls: AtomicUsize::new(/*v*/ 0),
        });
        let before = fs::read(&ports.path).ok();
        let (_, owner) = learning_iteration_channel_v1(
            daemon.identity.agent_id.clone(),
            daemon.identity.spawn_generation,
            ports.owners.clone(),
            ports.clone(),
            ports.verifier.clone(),
            /*capacity*/ 2,
        )?;
        let result = owner.process(&daemon.state(), request, || Ok(now)).await;
        let error = result.as_ref().err().map(ToString::to_string);
        let accepted = matches!(mode.as_str(), "accept" | "expired");
        if accepted {
            let recovered = result?;
            assert_eq!(recovered.head_digest, ports.pinned_head);
            assert_eq!(
                LearningIterationCoordinatorV1::from_snapshot(recovered)?.disposition(),
                LearningIterationDispositionV1::NoUpdate
            );
        } else {
            assert!(result.is_err(), "restored evidence must be refused: {mode}");
            if mode == "signature" || mode == "signature-expired" {
                assert!(matches!(
                    result,
                    Err(LearningIterationRuntimeErrorV1::Evidence(
                        SignedEvidenceError::InvalidSignature
                    ))
                ));
            }
        }
        assert_eq!(ports.forbidden_calls.load(Ordering::SeqCst), 0);
        assert_eq!(fs::read(&ports.path).ok(), before);
        serde_json::json!({"pid": std::process::id(), "mode": mode,
            "forbidden_calls": 0, "checkpoint_unchanged": true, "accepted": accepted, "current_owner_time": now, "error": error})
    };
    fs::write(
        root.join(format!("result-{mode}.json")),
        serde_json::to_vec(&report)?,
    )?;
    Ok(())
}

#[test]
fn restored_no_update_authenticates_across_processes() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let test_name = format!(
        "{}::learning_checkpoint_process_child",
        module_path!()
            .split_once("::")
            .ok_or_else(|| anyhow::anyhow!("test module"))?
            .1
    );
    let run = |directory: &std::path::Path,
               mode: &str,
               head: [u8; 32]|
     -> anyhow::Result<serde_json::Value> {
        let output = Command::new(std::env::current_exe()?)
            .args(["--exact", &test_name, "--ignored", "--nocapture"])
            .env("HEPTA_LEARNING_CHECKPOINT_CASE", directory)
            .env("HEPTA_LEARNING_CHECKPOINT_MODE", mode)
            .env(
                "HEPTA_LEARNING_CHECKPOINT_HEAD",
                serde_json::to_string(&head)?,
            )
            .output()?;
        anyhow::ensure!(
            output.status.success(),
            "child failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        Ok(serde_json::from_slice(&fs::read(
            directory.join(format!("result-{mode}.json")),
        )?)?)
    };
    let written = run(root.path(), "write", [0; 32])?;
    assert_eq!(written["stages"], 4);
    let pin: [u8; 32] = serde_json::from_value(written["head"].clone())?;
    let partial_pin: [u8; 32] = serde_json::from_value(written["in_progress_head"].clone())?;
    let original = fs::read(root.path().join("checkpoint.json"))?;
    let mut reports = vec![written];
    for mode in [
        "accept",
        "signature",
        "signature-expired",
        "payload",
        "expired",
        "future",
        "revoked",
        "owner-revoked",
        "owner-revoked-expired",
        "in-progress-expired",
        "wrong-head",
        "missing",
    ] {
        let directory = root.path().join(mode);
        fs::create_dir(&directory)?;
        let mut bytes = original.clone();
        if mode == "signature" || mode == "signature-expired" {
            let mut disk: wire::DiskCheckpoint = serde_json::from_slice(&bytes)?;
            disk.attestations[3].1[0] ^= 1;
            bytes = serde_json::to_vec(&disk)?;
        }
        if mode == "payload" {
            let mut disk: wire::DiskCheckpoint = serde_json::from_slice(&bytes)?;
            disk.payloads[3][0] ^= 1;
            bytes = serde_json::to_vec(&disk)?;
        }
        if mode == "in-progress-expired" {
            let mut disk: wire::DiskCheckpoint = serde_json::from_slice(&bytes)?;
            disk.payloads.truncate(3);
            disk.attestations.truncate(3);
            disk.head = partial_pin;
            bytes = serde_json::to_vec(&disk)?;
        }
        if mode != "missing" {
            fs::write(directory.join("checkpoint.json"), bytes)?;
        }
        let head = match mode {
            "wrong-head" => [3; 32],
            "in-progress-expired" => partial_pin,
            _ => pin,
        };
        reports.push(run(&directory, mode, head)?);
    }
    let pids: std::collections::BTreeSet<u64> = reports
        .iter()
        .map(|report| {
            report["pid"]
                .as_u64()
                .ok_or_else(|| anyhow::anyhow!("missing pid"))
        })
        .collect::<anyhow::Result<_>>()?;
    assert_eq!(pids.len(), 13);
    assert!(!pids.contains(&u64::from(std::process::id())));
    assert_eq!(fs::read(root.path().join("checkpoint.json"))?, original);
    if let Some(path) = std::env::var_os("HEPTA_NO_UPDATE_EVIDENCE_DIR") {
        let directory = PathBuf::from(path).join("learning-cross-process");
        fs::create_dir_all(&directory)?;
        fs::write(directory.join("fixture-checkpoint.json"), original)?;
        fs::write(
            directory.join("process-results.json"),
            serde_json::to_vec_pretty(
                &serde_json::json!({"classification": "engineering_fixture_not_production_custody",
                "processes": reports, "fresh_child_processes": 13,
                "writer_fixture_stage_calls": 4, "scientific_training_replicates": 0,
                "reader_owner_mutations": 0,
                "production_learning_owner": false, "power_loss_verified": false}),
            )?,
        )?;
    }
    Ok(())
}
