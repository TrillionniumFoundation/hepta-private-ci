//! Actual ordinary A and original journals, with explicit fixture enrollment.
//! These component receipts do not establish the ordinary StageOwner aggregate,
//! an independent B evaluation, adoption, or a daemon/Root process restart.

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellQ24SourcePredecessorV1 as Predecessor;
use crate::OriginalCellQ24SourceReceiptOwnerV1 as SourceReceiptTestOwner;
use crate::OriginalCellQ24SourceSigningConfigV1 as Config;
use crate::cell_q24_dataset::test_support as signed;

#[path = "cell_q24_source_receipt_fence_tests.rs"]
mod fences;

type Completion = (LearningIterationReceiptV1, SignedLearningEvidenceV1);
type SourceReceiptFileTestOwner = SourceReceiptTestOwner<FileAnchorWitnessStore>;

#[derive(Clone, Copy)]
enum OpenOwner {
    Create,
    Recover,
}

fn file(root: &Path, name: &str, mode: OpenOwner) -> anyhow::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut options = OpenOptions::new();
    options
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW);
    if matches!(mode, OpenOwner::Create) {
        options.create_new(true);
    }
    let file = options.open(root.join(name))?;
    if matches!(mode, OpenOwner::Recover) {
        let metadata = file.metadata()?;
        anyhow::ensure!(
            metadata.is_file() && metadata.len() > 0,
            "missing original {name}"
        );
    }
    Ok(file)
}

fn snapshot(config: &Config) -> &LearningIterationSnapshotV1 {
    match &config.predecessor {
        Predecessor::Initial(snapshot) | Predecessor::Experience { snapshot, .. } => snapshot,
    }
}

fn witness(
    root: &Path,
    name: &str,
    config: &Config,
    mode: OpenOwner,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        file(root, &format!("{name}-witness"), mode)?,
        JournalScope {
            scope_digest: config.scope.binding(),
            objective_digest: snapshot(config).request.envelope.objective_digest,
        },
        Generation::new(1)?,
        /*max_records*/ 16,
    )?)
}

fn initial(native: &OriginalQ24DatasetIngressFixture) -> anyhow::Result<Config> {
    let template = super::super::trained::training_prefix(
        &native.publication,
        native.bundle.clone(),
        native.material.batch(),
        native.material.dataset().snapshot.dataset_digest,
        native.material.dataset().revocation_cut_digest,
        native.material.profile().principal_id.clone(),
    )?;
    // Reuse only the declared fixture request/owner identities, never its mocked
    // stage receipts. The new real receipt owner starts from an empty prefix.
    let signer = signed::signer(LearningEvidenceRoleV1::Observer, native.at);
    let verifier = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?
        .verifier()
        .clone();
    let mut owners = template.owners;
    owners.experience = signer.principal.principal_id.clone();
    owners.dataset = signer.principal.principal_id.clone();
    owners.evidence_trust_digest = verifier.trust_digest();
    let coordinator = LearningIterationCoordinatorV1::new(template.request, owners)?;
    let snapshot = coordinator.snapshot().clone();
    let scope = FrozenLearningScopeV2::freeze(
        &snapshot.request,
        &snapshot.owners,
        LearningUpdateScopeV2::Cell,
        signed::d("explicit-receipt-fixture-update-rule"),
    )?;
    Ok(Config {
        predecessor: Predecessor::Initial(snapshot),
        scope,
        signer,
        verifier,
        maximum_signature_lifetime_seconds: 300,
    })
}

fn dataset_config(initial: &Config, original: &Completion) -> anyhow::Result<Config> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot(initial).clone())?;
    coordinator.record(original.0.clone(), original.0.observed_unix_seconds)?;
    let mut config = initial.clone();
    config.predecessor = Predecessor::Experience {
        snapshot: coordinator.snapshot().clone(),
        attestation: original.1.clone(),
    };
    Ok(config)
}

fn owner(
    native: &OriginalQ24DatasetIngressFixture,
    root: &Path,
    name: &str,
    config: &Config,
    mode: OpenOwner,
) -> anyhow::Result<SourceReceiptFileTestOwner> {
    let file = file(root, name, mode)?;
    let witness = witness(root, name, config, mode)?;
    let key = SigningKey::from_bytes(&[2; 32]);
    Ok(match mode {
        OpenOwner::Create => SourceReceiptTestOwner::create(
            file,
            witness,
            config.clone(),
            key,
            Arc::clone(&native.material),
        )?,
        OpenOwner::Recover => SourceReceiptTestOwner::recover(
            file,
            witness,
            config.clone(),
            key,
            Arc::clone(&native.material),
        )?,
    })
}

fn bytes(root: &Path) -> anyhow::Result<Vec<Vec<u8>>> {
    [
        "experience",
        "experience-witness",
        "dataset",
        "dataset-witness",
    ]
    .iter()
    .map(|name| Ok(fs::read(root.join(name))?))
    .collect()
}

#[tokio::test]
async fn actual_a_issues_original_observer_receipts_and_reopens_without_resigning()
-> anyhow::Result<()> {
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let initial = initial(&native)?;
    let source_before = native.source_bytes()?;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Create,
    )?;
    let first = experience.attest_experience(&ledger, &source, &native.identity)?;
    let config = dataset_config(&initial, &first)?;
    let mut dataset = owner(&native, root.path(), "dataset", &config, OpenOwner::Create)?;
    let second = dataset.attest_dataset(&mut experience, &ledger, &source, &native.identity)?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot(&config).clone())?;
    coordinator.record(second.0.clone(), second.0.observed_unix_seconds)?;
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::Training)
    );
    let LearningIterationObservationV1::Experience {
        episode_digest,
        completed_task_receipt,
    } = &first.0.observation
    else {
        anyhow::bail!("Experience")
    };
    assert_eq!(
        *completed_task_receipt,
        native
            .publication
            .history_digest()
            .as_str()
            .parse::<Digest32>()?
    );
    assert_eq!(
        second.0.observation,
        LearningIterationObservationV1::Dataset {
            snapshot_digest: native.material.dataset().snapshot.dataset_digest,
            episode_digest: *episode_digest,
            withdrawal_frontier: native.material.dataset().revocation_cut_digest,
            rows: native.material.batch().rows(),
            bytes: native.material.batch().encoded().len() as u64,
        }
    );
    for (receipt, signature) in [&first, &second] {
        assert_eq!(signature.role, LearningEvidenceRoleV1::Observer);
        assert_eq!(receipt.observed_unix_seconds, signature.issued_at);
        initial.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            signature,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            signature.issued_at,
        )?;
    }
    let retained = bytes(root.path())?;
    drop((experience, dataset));
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Recover,
    )?;
    let mut dataset = owner(&native, root.path(), "dataset", &config, OpenOwner::Recover)?;
    assert_eq!(
        experience.readback_experience(&ledger, &source, &native.identity)?,
        first
    );
    assert_eq!(
        dataset.readback_dataset(&mut experience, &ledger, &source, &native.identity)?,
        second
    );
    assert_eq!(
        dataset.attest_dataset(&mut experience, &ledger, &source, &native.identity)?,
        second
    );
    assert_eq!(bytes(root.path())?, retained);
    assert_eq!(native.source_bytes()?, source_before);
    Ok(())
}

#[tokio::test]
async fn dataset_requires_actual_experience_journal_even_with_the_valid_original_signature()
-> anyhow::Result<()> {
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let initial = initial(&native)?;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Create,
    )?;
    let first = experience.attest_experience(&ledger, &source, &native.identity)?;
    let config = dataset_config(&initial, &first)?;
    let mut dataset = owner(&native, root.path(), "dataset", &config, OpenOwner::Create)?;
    let mut missing = owner(&native, root.path(), "missing", &initial, OpenOwner::Create)?;
    let before = bytes(root.path())?;
    let empty = fs::read(root.path().join("missing"))?;
    assert!(
        dataset
            .attest_dataset(&mut missing, &ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        dataset
            .readback_dataset(&mut missing, &ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        dataset
            .attest_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        experience
            .attest_dataset(&mut missing, &ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(bytes(root.path())?, before);
    assert_eq!(fs::read(root.path().join("missing"))?, empty);
    dataset.attest_dataset(&mut experience, &ledger, &source, &native.identity)?;
    Ok(())
}

#[tokio::test]
async fn observer_capability_trigger_and_complete_predecessor_conflicts_are_rejected()
-> anyhow::Result<()> {
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let config = initial(&native)?;
    let mut wrong_role = config.clone();
    wrong_role.signer = signed::signer(LearningEvidenceRoleV1::Evaluator, native.at);
    assert!(
        SourceReceiptTestOwner::create(
            file(root.path(), "role", OpenOwner::Create)?,
            witness(root.path(), "role", &config, OpenOwner::Create)?,
            wrong_role,
            SigningKey::from_bytes(&[3; 32]),
            Arc::clone(&native.material)
        )
        .is_err()
    );
    assert_eq!(fs::metadata(root.path().join("role"))?.len(), 0);
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &config,
        OpenOwner::Create,
    )?;
    let first = experience.attest_experience(&ledger, &source, &native.identity)?;
    let mut changed = dataset_config(&config, &first)?;
    if let Predecessor::Experience { attestation, .. } = &mut changed.predecessor {
        attestation.signature[0] ^= 1;
    }
    let mut dataset = owner(&native, root.path(), "dataset", &changed, OpenOwner::Create)?;
    let before = bytes(root.path())?;
    assert!(
        dataset
            .attest_dataset(&mut experience, &ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(bytes(root.path())?, before);
    drop(dataset);
    let correct = dataset_config(&config, &first)?;
    assert!(
        owner(
            &native,
            root.path(),
            "dataset",
            &correct,
            OpenOwner::Recover
        )
        .is_err()
    );
    let mut altered = snapshot(&config).request.clone();
    altered.source_run_id = signed::id("another-real-looking-run");
    let coordinator =
        LearningIterationCoordinatorV1::new(altered, snapshot(&config).owners.clone())?;
    let mut other = config;
    other.scope = FrozenLearningScopeV2::freeze(
        &coordinator.snapshot().request,
        &coordinator.snapshot().owners,
        LearningUpdateScopeV2::Cell,
        signed::d("explicit-receipt-fixture-update-rule"),
    )?;
    other.predecessor = Predecessor::Initial(coordinator.snapshot().clone());
    let mut wrong_run = owner(&native, root.path(), "wrong-run", &other, OpenOwner::Create)?;
    let empty = fs::read(root.path().join("wrong-run"))?;
    assert!(
        wrong_run
            .attest_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(fs::read(root.path().join("wrong-run"))?, empty);
    Ok(())
}

#[tokio::test]
async fn current_source_withdrawal_rejects_both_completed_receipts_without_new_work()
-> anyhow::Result<()> {
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let initial = initial(&native)?;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Create,
    )?;
    let first = experience.attest_experience(&ledger, &source, &native.identity)?;
    let config = dataset_config(&initial, &first)?;
    let mut dataset = owner(&native, root.path(), "dataset", &config, OpenOwner::Create)?;
    dataset.attest_dataset(&mut experience, &ledger, &source, &native.identity)?;
    native
        .original
        .withdraw_source(&snapshot(&initial).request.source_run_id)?;
    let retained = bytes(root.path())?;
    let source_after = native.source_bytes()?;
    assert!(
        experience
            .readback_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        dataset
            .readback_dataset(&mut experience, &ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        dataset
            .attest_dataset(&mut experience, &ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(bytes(root.path())?, retained);
    assert_eq!(native.source_bytes()?, source_after);
    Ok(())
}

#[tokio::test]
async fn expired_original_signature_is_not_renewed_by_attestation_or_readback() -> anyhow::Result<()>
{
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let mut config = initial(&native)?;
    config.maximum_signature_lifetime_seconds = 1;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &config,
        OpenOwner::Create,
    )?;
    let original = experience.attest_experience(&ledger, &source, &native.identity)?;
    let retained = fs::read(root.path().join("experience"))?;
    let start = Instant::now();
    while SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() <= original.1.expires_at {
        anyhow::ensure!(
            start.elapsed() < Duration::from_secs(4),
            "real clock did not reach expiry"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        experience
            .readback_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        experience
            .attest_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(fs::read(root.path().join("experience"))?, retained);
    Ok(())
}

#[tokio::test]
async fn current_outcome_correction_rejects_the_original_receipt_without_rewriting_it()
-> anyhow::Result<()> {
    use codex_hepta_learning_ledger::*;
    use codex_hepta_types::FixedQ32;
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let initial = initial(&native)?;
    let mut ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Create,
    )?;
    let first = experience.attest_experience(&ledger, &source, &native.identity)?;
    let config = dataset_config(&initial, &first)?;
    let mut dataset = owner(&native, root.path(), "dataset", &config, OpenOwner::Create)?;
    dataset.attest_dataset(&mut experience, &ledger, &source, &native.identity)?;
    let original = ledger
        .snapshot()?
        .records()
        .iter()
        .find_map(|record| match &record.event {
            LedgerEvent::AuthenticatedOutcomeV2(value) => Some(value.clone()),
            _ => None,
        })
        .ok_or_else(|| anyhow::anyhow!("missing original terminal Outcome"))?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let correction = AuthenticatedOutcomeV1 {
        record_id: signed::id("source-receipt-correction"),
        outcome_id: signed::id("corrected-terminal"),
        episode_id: original.episode_id,
        observer: signed::signer(LearningEvidenceRoleV1::Observer, native.at).principal,
        observed_at: Some(now),
        value: Some(FixedQ32::from_raw(2_i64 << 32)),
        unit_profile_digest: original.unit_profile_digest,
        support_digest: original.support_digest,
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: now,
            expected_delay_profile_digest: original.expected_delay_profile_digest,
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: Some(original.outcome_id),
            finalized_at: Some(now),
        },
    };
    let evidence = signed::sign(
        &ledger,
        LearningEvidenceRoleV1::Observer,
        native.at,
        &outcome_signing_payload_v2(&correction),
    );
    let head = ledger.snapshot()?.head_digest;
    ledger.append_outcome(head, correction, &evidence, now)?;
    let retained = bytes(root.path())?;
    assert!(
        experience
            .readback_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        dataset
            .readback_dataset(&mut experience, &ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(bytes(root.path())?, retained);
    Ok(())
}

#[tokio::test]
async fn a_second_enrolled_observer_cannot_replace_a_but_can_observe_its_dataset()
-> anyhow::Result<()> {
    use crate::OriginalCellQ24SourceReceiptErrorV1;
    let at = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let second_key = SigningKey::from_bytes(&[8; 32]);
    let mut second = signed::signer(LearningEvidenceRoleV1::Observer, at);
    second.principal.principal_id = signed::id("second-enrolled-observer");
    second.controller_id = signed::id("second-observer-controller");
    second.principal.credential_chain_digest = signed::d("second-original-fixture-chain");
    second.verifying_key = second_key.verifying_key().to_bytes();
    second.principal.signing_key_digest = Digest32::of_bytes(&second.verifying_key);
    let native = OriginalQ24DatasetIngressFixture::with_additional_signers(
        1_i64 << 32,
        vec![second.clone()],
    )
    .await?;
    let root = tempfile::tempdir()?;
    let mut config = initial(&native)?;
    let cut = snapshot(&config);
    let mut owners = cut.owners.clone();
    owners.experience = second.principal.principal_id.clone();
    let coordinator = LearningIterationCoordinatorV1::new(cut.request.clone(), owners)?;
    config.scope = FrozenLearningScopeV2::freeze(
        &coordinator.snapshot().request,
        &coordinator.snapshot().owners,
        LearningUpdateScopeV2::Cell,
        signed::d("explicit-receipt-fixture-update-rule"),
    )?;
    config.predecessor = Predecessor::Initial(coordinator.snapshot().clone());
    config.signer = second.clone();
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
    )?;
    let mut replacement = SourceReceiptTestOwner::create(
        file(root.path(), "replacement", OpenOwner::Create)?,
        witness(root.path(), "replacement", &config, OpenOwner::Create)?,
        config,
        second_key.clone(),
        Arc::clone(&native.material),
    )?;
    let before = fs::read(root.path().join("replacement"))?;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    assert!(matches!(
        replacement.attest_experience(&ledger, &source, &native.identity),
        Err(OriginalCellQ24SourceReceiptErrorV1::Binding(
            "original terminal Outcome Observer identity"
        ))
    ));
    assert_eq!(fs::read(root.path().join("replacement"))?, before);
    drop(ledger);

    // A separate Dataset Observer is valid when the original Experience owner
    // remains the actual source of the exact completed predecessor.
    let mut initial = initial(&native)?;
    let cut = snapshot(&initial);
    let mut owners = cut.owners.clone();
    owners.dataset = second.principal.principal_id.clone();
    let coordinator = LearningIterationCoordinatorV1::new(cut.request.clone(), owners)?;
    initial.scope = FrozenLearningScopeV2::freeze(
        &coordinator.snapshot().request,
        &coordinator.snapshot().owners,
        LearningUpdateScopeV2::Cell,
        signed::d("explicit-receipt-fixture-update-rule"),
    )?;
    initial.predecessor = Predecessor::Initial(coordinator.snapshot().clone());
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let mut experience = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Create,
    )?;
    let original = experience.attest_experience(&ledger, &source, &native.identity)?;
    let mut config = dataset_config(&initial, &original)?;
    config.signer = second;
    let mut dataset = SourceReceiptTestOwner::create(
        file(root.path(), "dataset", OpenOwner::Create)?,
        witness(root.path(), "dataset", &config, OpenOwner::Create)?,
        config,
        second_key,
        Arc::clone(&native.material),
    )?;
    let completed = dataset.attest_dataset(&mut experience, &ledger, &source, &native.identity)?;
    assert_ne!(original.0.actor_id, completed.0.actor_id);
    assert_eq!(
        dataset.readback_dataset(&mut experience, &ledger, &source, &native.identity)?,
        completed
    );
    Ok(())
}
