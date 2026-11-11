//! Component recovery qualification with synthetic fixture credentials/outcomes.
//! These subprocesses reopen original files; they do not establish ordinary
//! StageOwner assembly, independent task benefit, or Root/daemon cold startup.

use std::fs;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

use super::super::test_support as fixture;
use super::*;
use crate::circuit_task::original_source_test_support as original;

#[path = "cell_q24_dataset_recovery_inputs_tests.rs"]
mod inputs;

#[path = "cell_q24_dataset_recovery_witness_tests.rs"]
mod witness_tests;

type DatasetRecoveryTestOwner = OriginalCellQ24DatasetRecoveryOwnerV1<FileAnchorWitnessStore>;
const WORKER: &str = "cell_q24_dataset::recovery::tests::cold_process_worker";

fn plan(material: &OriginalCellQ24DatasetV1) -> DatasetFreezePlanV2 {
    DatasetFreezePlanV2 {
        snapshot_id: material.dataset.snapshot.snapshot_id.clone(),
        objective_digest: material.dataset.snapshot.objective_digest,
        inclusion_policy_digest: material.dataset.inclusion_policy_digest,
    }
}

fn create_owner(
    root: &Path,
    name: &str,
    profile: &CellQ24DatasetProfileV1,
) -> anyhow::Result<DatasetRecoveryTestOwner> {
    Ok(DatasetRecoveryTestOwner::create(
        original::opened(root, name)?,
        original::witness(root, &format!("{name}-witness"))?,
        profile.clone(),
    )?)
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ColdExpected {
    producer_pid: u32,
    original_material: Vec<u8>,
    witness_scope: String,
    witness_objective: String,
    witness_generation: u64,
    witness_limit: usize,
}

fn existing(root: &Path, name: &str) -> anyhow::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(root.join(name))?;
    let metadata = file.metadata()?;
    anyhow::ensure!(
        metadata.is_file() && metadata.len() > 0,
        "original {name} is not a nonempty regular file"
    );
    Ok(file)
}

fn acknowledged_bytes(root: &Path) -> anyhow::Result<Vec<Vec<u8>>> {
    [
        "ledger",
        "ledger-witness",
        "source-journal",
        "source-witness",
        "cell-journal",
        "cell-witness",
        "material",
        "material-witness",
        "original-inputs.json",
        "expected.json",
    ]
    .iter()
    .map(|name| Ok(fs::read(root.join(name))?))
    .collect()
}

async fn produce(control: &Path, case: &str) -> anyhow::Result<()> {
    let mut original = fixture::Fixture::new(fixture::Q / 2).await?;
    original.terminal(1_i64 << 32)?;
    let material = original.freeze()?;
    let plan = plan(&material);
    let root = original.directory.path().canonicalize()?;
    let mut owner = create_owner(&root, "material", &original.profile)?;
    owner.retain(
        &plan,
        &material,
        &original.writer,
        &original.source.readback(),
        &original.identity,
    )?;
    inputs::save_inputs(&original, &root)?;
    let expected = ColdExpected {
        producer_pid: std::process::id(),
        original_material: codec::encode(&codec::SavedMaterial::from_original(&plan, &material)?)?,
        witness_scope: fixture::d("material-witness").to_string(),
        witness_objective: fixture::d("original ordinary source").to_string(),
        witness_generation: 7,
        witness_limit: 64,
    };
    fs::write(root.join("expected.json"), serde_json::to_vec(&expected)?)?;
    match case {
        "r0" => {}
        "r1" => {
            let mut later = original.decision.clone();
            later.episode_id = fixture::id("later-unrelated-same-objective");
            later.record_id = circuit_learning_run_id_v1(
                &original.writer,
                &original.identity.agent_id,
                &later.episode_id,
            )?;
            let signed = fixture::sign(
                &original.writer,
                LearningEvidenceRoleV1::Generator,
                original.at,
                &decision_signing_payload_v2(&later)?,
            );
            original.writer.append_decision(
                original.writer.snapshot()?.head_digest,
                later,
                &signed,
                original.at,
            )?;
            assert_ne!(
                original.writer.snapshot()?.head_digest,
                material.dataset.snapshot.ledger_head_digest
            );
        }
        "corrected" => original.correct(2_i64 << 32)?,
        "withdrawn" => {
            let run = circuit_learning_run_id_v1(
                &original.writer,
                &original.identity.agent_id,
                &fixture::id("train-A"),
            )?;
            original.source.withdraw_source(&run)?;
        }
        _ => anyhow::bail!("unknown cold case"),
    }
    fs::write(
        control.join("original-root"),
        root.as_os_str().as_encoded_bytes(),
    )?;
    // Keep the exact original directory; producer exit drops every owner and
    // Arc. Recovery starts only after the parent has observed this exit.
    let _original_directory = original.directory.keep();
    Ok(())
}

fn recover(control: &Path, case: &str) -> anyhow::Result<()> {
    let root = PathBuf::from(fs::read_to_string(control.join("original-root"))?);
    let expected: ColdExpected = serde_json::from_slice(&fs::read(root.join("expected.json"))?)?;
    assert_ne!(std::process::id(), expected.producer_pid);
    let saved = codec::decode(&expected.original_material)?;
    let before = acknowledged_bytes(&root)?;
    let original = inputs::reopen_inputs(&root)?;
    let witness = FileAnchorWitnessStore::open(
        existing(&root, "material-witness")?,
        JournalScope {
            scope_digest: expected.witness_scope.parse()?,
            objective_digest: expected.witness_objective.parse()?,
        },
        Generation::new(expected.witness_generation)?,
        expected.witness_limit,
    )?;
    let mut owner = DatasetRecoveryTestOwner::recover(
        existing(&root, "material")?,
        witness,
        saved.profile.clone(),
    )?;
    let restored = owner.restore(
        &saved.plan,
        &original.writer,
        &original.source.readback(),
        &original.identity,
    );
    match case {
        "r0" | "r1" => {
            let material = restored?;
            assert_eq!(material.profile(), &saved.profile);
            assert_eq!(material.evidence, saved.evidence);
            assert_eq!(material.freeze_payload, saved.freeze_payload);
            assert_eq!(codec::receipt_bytes(material.dataset())?, saved.receipt);
            assert_eq!(material.batch().encoded(), saved.batch);
            if case == "r1" {
                assert_ne!(
                    original.writer.snapshot()?.head_digest,
                    material.dataset().snapshot.ledger_head_digest
                );
                assert_eq!(material.batch().rows(), 1);
            }
        }
        "corrected" | "withdrawn" => assert!(
            restored.is_err(),
            "current source invalidation must reject, never NoUpdate"
        ),
        _ => anyhow::bail!("unknown cold case"),
    }
    assert_eq!(acknowledged_bytes(&root)?, before);
    fs::write(control.join("recovery-pid"), std::process::id().to_string())?;
    Ok(())
}

#[tokio::test]
#[ignore = "subprocess entry; exercised by the four cold-recovery tests"]
async fn cold_process_worker() -> anyhow::Result<()> {
    let control = PathBuf::from(std::env::var("HEPTA_Q24_DATASET_COLD_CONTROL")?);
    let case = std::env::var("HEPTA_Q24_DATASET_COLD_CASE")?;
    match std::env::var("HEPTA_Q24_DATASET_COLD_PHASE")?.as_str() {
        "produce" => produce(&control, &case).await,
        "recover" => recover(&control, &case),
        _ => anyhow::bail!("unknown cold phase"),
    }
}

struct DatasetTestChild(std::process::Child);
impl Drop for DatasetTestChild {
    fn drop(&mut self) {
        // Also reap on an I/O error or failed assertion in the parent.
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct KeptDatasetDirectory(PathBuf);
impl Drop for KeptDatasetDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn child(control: &Path, case: &str, phase: &str) -> anyhow::Result<()> {
    let stdout = control.join(format!("{phase}.stdout"));
    let stderr = control.join(format!("{phase}.stderr"));
    let mut child = DatasetTestChild(
        Command::new(std::env::current_exe()?)
            .args(["--exact", WORKER, "--ignored", "--nocapture"])
            .env("HEPTA_Q24_DATASET_COLD_CONTROL", control)
            .env("HEPTA_Q24_DATASET_COLD_CASE", case)
            .env("HEPTA_Q24_DATASET_COLD_PHASE", phase)
            .stdin(Stdio::null())
            .stdout(File::create(&stdout)?)
            .stderr(File::create(&stderr)?)
            .spawn()?,
    );
    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        if let Some(status) = child.0.try_wait()? {
            anyhow::ensure!(
                status.success(),
                "{case}/{phase}: {status}\n{}\n{}",
                fs::read_to_string(&stdout)?,
                fs::read_to_string(&stderr)?
            );
            return Ok(());
        }
        if Instant::now() >= deadline {
            // Only this test-owned child is reaped, never a product/compiler.
            child.0.kill()?;
            child.0.wait()?;
            anyhow::bail!("{case}/{phase} child exceeded 60 seconds");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn cold_case(case: &str) -> anyhow::Result<()> {
    let control = tempfile::tempdir()?;
    child(control.path(), case, "produce")?;
    let kept = KeptDatasetDirectory(PathBuf::from(fs::read_to_string(
        control.path().join("original-root"),
    )?));
    let root = &kept.0;
    let expected: ColdExpected = serde_json::from_slice(&fs::read(root.join("expected.json"))?)?;
    let before = acknowledged_bytes(&root)?;
    child(control.path(), case, "recover")?;
    let recovered: u32 = fs::read_to_string(control.path().join("recovery-pid"))?.parse()?;
    assert_ne!(expected.producer_pid, recovered);
    assert_ne!(expected.producer_pid, std::process::id());
    assert_ne!(recovered, std::process::id());
    assert_eq!(acknowledged_bytes(&root)?, before);
    Ok(())
}

#[test]
fn new_process_restores_original_dataset_and_all_signature_bytes() -> anyhow::Result<()> {
    cold_case("r0")
}
#[test]
fn new_process_restores_old_signed_prefix_after_same_objective_append() -> anyhow::Result<()> {
    cold_case("r1")
}
#[test]
fn new_process_rejects_current_outcome_correction() -> anyhow::Result<()> {
    cold_case("corrected")
}
#[test]
fn new_process_rejects_current_source_withdrawal() -> anyhow::Result<()> {
    cold_case("withdrawn")
}

#[tokio::test]
async fn self_consistent_fake_receipt_and_changed_full_material_are_not_history()
-> anyhow::Result<()> {
    let mut original = fixture::Fixture::new(fixture::Q / 2).await?;
    original.terminal(1_i64 << 32)?;
    let material = original.freeze()?;
    let plan = plan(&material);
    let saved = codec::SavedMaterial::from_original(&plan, &material)?;
    let receipt = material.dataset();
    let forged = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: receipt.snapshot.snapshot_id.clone(),
            producer: receipt.producer.clone(),
            ledger_head_digest: fixture::d("head-never-written-by-the-original-ledger"),
            objective_digest: receipt.snapshot.objective_digest,
            eligible_frontier: receipt.snapshot.eligible_frontier,
            outcome_watermark: receipt.snapshot.outcome_watermark,
            correction_cut_digest: receipt.correction_cut_digest,
            revocation_cut_digest: receipt.revocation_cut_digest,
            inclusion_policy_digest: receipt.inclusion_policy_digest,
            source_record_digests: receipt.snapshot.source_record_digests.clone(),
            pending_outcomes: receipt.snapshot.pending_outcomes,
            censored_outcomes: receipt.snapshot.censored_outcomes,
        },
        now()?,
    )?;
    // Demonstrate the precise older seam: self-consistency plus current active
    // source checks alone do not authenticate this invented historical head.
    original
        .writer
        .revalidate_dataset_snapshot(&forged, now()?)?;
    let mut fake_history = saved.clone();
    fake_history.original_head = forged.snapshot.ledger_head_digest;
    fake_history.receipt = codec::receipt_bytes(&forged)?;
    let mutations: &[fn(&mut codec::SavedMaterial)] = &[
        |s| s.freeze_payload[0] ^= 1,
        |s| s.evidence.signature[0] ^= 1,
        |s| s.receipt[0] ^= 1,
        |s| s.batch[0] ^= 1,
        |s| s.profile.excluded_episodes = vec![fixture::id("changed-excluded-partition")],
        |s| s.plan.snapshot_id = fixture::id("other-original-plan"),
    ];
    let cases = std::iter::once(fake_history).chain(mutations.iter().map(|mutate| {
        let mut changed = saved.clone();
        mutate(&mut changed);
        changed
    }));
    for (index, changed) in cases.enumerate() {
        let mut owner = create_owner(
            original.directory.path(),
            &format!("changed-{index}"),
            material.profile(),
        )?;
        let key = owner.key(&plan)?;
        let bytes = codec::encode(&changed)?;
        owner.journal.commit_once(&key, || Ok(bytes))?;
        assert!(
            owner
                .restore(
                    &plan,
                    &original.writer,
                    &original.source.readback(),
                    &original.identity
                )
                .is_err(),
            "changed material {index} admitted"
        );
    }
    Ok(())
}

#[tokio::test]
async fn conflicting_complete_material_and_pending_claim_never_replace_original()
-> anyhow::Result<()> {
    let mut original = fixture::Fixture::new(fixture::Q / 2).await?;
    original.terminal(1_i64 << 32)?;
    let material = original.freeze()?;
    let plan = plan(&material);
    let root = original.directory.path().to_path_buf();
    let mut owner = create_owner(&root, "retained", material.profile())?;
    owner.retain(
        &plan,
        &material,
        &original.writer,
        &original.source.readback(),
        &original.identity,
    )?;
    let before = [
        fs::read(root.join("retained"))?,
        fs::read(root.join("retained-witness"))?,
    ];
    original.correct(2_i64 << 32)?;
    let newer = original.freeze()?;
    assert!(
        owner
            .retain(
                &plan,
                &newer,
                &original.writer,
                &original.source.readback(),
                &original.identity
            )
            .is_err()
    );
    assert_eq!(
        [
            fs::read(root.join("retained"))?,
            fs::read(root.join("retained-witness"))?
        ],
        before
    );
    let mut pending = create_owner(&root, "pending", newer.profile())?;
    let key = pending.key(&plan)?;
    assert!(
        pending
            .journal
            .commit_once(&key, || Err(LearningOriginalOwnerErrorV1::Binding(
                "fixture interrupted after claim"
            )))
            .is_err()
    );
    drop(pending);
    let mut pending = DatasetRecoveryTestOwner::recover(
        existing(&root, "pending")?,
        original::witness(&root, "pending-witness")?,
        newer.profile().clone(),
    )?;
    assert!(matches!(
        pending.restore(
            &plan,
            &original.writer,
            &original.source.readback(),
            &original.identity
        ),
        Err(RecoveryError::Owner(LearningOriginalOwnerErrorV1::Pending))
    ));
    Ok(())
}

#[tokio::test]
async fn bounded_complete_codec_rejects_overflow_truncation_and_noncanonical_bytes()
-> anyhow::Result<()> {
    let mut original = fixture::Fixture::new(fixture::Q / 2).await?;
    original.terminal(1_i64 << 32)?;
    let material = original.freeze()?;
    let mut saved = codec::SavedMaterial::from_original(&plan(&material), &material)?;
    let bytes = codec::encode(&saved)?;
    assert_eq!(codec::encode(&codec::decode(&bytes)?)?, bytes);
    for end in [0, 7, bytes.len() - 1] {
        assert!(codec::decode(&bytes[..end]).is_err());
    }
    let mut changed = bytes.clone();
    changed.push(0);
    assert!(codec::decode(&changed).is_err());
    changed = bytes;
    changed[0] ^= 1;
    assert!(codec::decode(&changed).is_err());
    saved.freeze_payload = vec![1; 65_536];
    assert!(codec::encode(&saved).is_err());
    assert!(codec::decode(&vec![0; 65_537]).is_err());
    Ok(())
}
