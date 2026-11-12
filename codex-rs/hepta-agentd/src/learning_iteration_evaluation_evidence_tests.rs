//! Same-UID mechanism fixtures exercise original framed readback only. Public
//! owner admission retains its separate UID/pidfd checks and Root qualification.

use std::io::ErrorKind;

use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellEvaluationReceiptConfigV1;
use crate::OriginalCellEvaluationReceiptErrorV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationReceiptSourcesV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::neuron_cell_evaluation::tests::learning::LearningFixture;
use crate::prepare_cell_learning_evaluation_v1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;

#[path = "learning_iteration_evaluation_insufficient_tests.rs"]
mod insufficient;
#[path = "learning_iteration_evaluation_recovery_tests.rs"]
mod recovery;

fn request(
    fixture: &LearningFixture,
) -> CellLearningEvaluationReadbackRequestV1<'_, LockedFileFinalHoldoutCasStoreV1> {
    CellLearningEvaluationReadbackRequestV1 {
        runner: fixture.runner(),
        snapshot: &fixture.snapshot,
        evaluation: &fixture.receipt,
        qualification: &fixture.qualification,
        context: &fixture.context,
        evidence: &fixture.evidence,
        timing: ProductTimingEvidenceV1::Qualification,
        verifier: &fixture.verifier,
    }
}

fn original_owners(
    fixture: &LearningFixture,
    evaluated: LearningIterationReceiptV1,
) -> anyhow::Result<(Fixture, Fixture)> {
    let initial = LearningIterationCoordinatorV1::new(
        fixture.snapshot.request.clone(),
        fixture.snapshot.owners.clone(),
    )?
    .snapshot()
    .clone();
    let training = fixture
        .snapshot
        .receipts
        .last()
        .expect("original Training")
        .clone();
    Ok((
        Fixture {
            initial: initial.clone(),
            signature: fixture.stage_attestation(&training),
            receipt: training,
            verifier: fixture.verifier.clone(),
        },
        Fixture {
            initial,
            signature: fixture.stage_attestation(&evaluated),
            receipt: evaluated,
            verifier: fixture.verifier.clone(),
        },
    ))
}

fn serve(
    mut server: UnixStream,
    fixture: Fixture,
    snapshot_head: Digest32,
    requests: u64,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        let receipt_digest = Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(
            &fixture.receipt,
        )?);
        for request_id in 1..=requests {
            let request = read_request(&mut server)?;
            // Exact field equality also rules out a payload/signing command.
            assert_eq!(
                serde_json::to_value(&request)?,
                serde_json::json!({
                    "schema": 1,
                    "operation": wire::OPERATION,
                    "request_id": request_id,
                    "binding": fixture.initial.head_digest.to_string(),
                    "snapshot_head": snapshot_head.to_string(),
                    "operation_id": fixture.receipt.operation_id.to_string(),
                    "actor_id": fixture.receipt.actor_id.to_string(),
                    "predecessor": fixture.receipt.predecessor.to_string(),
                    "receipt_digest": receipt_digest.to_string(),
                })
            );
            reply(&mut server, &response(request, fixture.evidence()))?;
        }
        Ok(())
    })
}

#[tokio::test]
async fn current_signed_qualification_reads_original_stage_evidence_for_all_decisions()
-> anyhow::Result<()> {
    for disposition in [
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        IndependentEvaluationDispositionV1::Ineligible,
    ] {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let fixture = LearningFixture::new_at(disposition, now);
        let prepared = prepare_cell_learning_evaluation_v1(
            fixture.runner(),
            &fixture.snapshot,
            &fixture.receipt,
            &fixture.qualification,
            &fixture.request(now),
        )?;
        let (training, evaluation) = original_owners(&fixture, prepared.clone())?;
        let expected = evaluation.signature.clone();
        let (trainer, trainer_server) = training.client()?;
        let (evaluator, evaluator_server) = evaluation.client()?;
        let head = fixture.snapshot.head_digest;
        let trainer_peer = serve(trainer_server, training, head, /*requests*/ 2);
        let evaluator_peer = serve(evaluator_server, evaluation, head, /*requests*/ 2);
        for _ in 0..2 {
            let authenticated =
                read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await?;
            assert_eq!(authenticated.receipt(), &prepared);
            assert_eq!(authenticated.attestation(), &expected);
            assert_eq!(
                authenticated.receipt().observed_unix_seconds,
                fixture.evidence.evaluator_bundle.issued_at
            );
            let after = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
            assert!((now..=after).contains(&authenticated.verified_at_unix_seconds()));
        }
        trainer_peer.join().expect("original trainer readback")?;
        evaluator_peer
            .join()
            .expect("original evaluator readback")?;
    }
    Ok(())
}

#[tokio::test]
async fn product_signature_cannot_replace_the_original_iteration_attestation() -> anyhow::Result<()>
{
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let fixture = LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
    let prepared = prepare_cell_learning_evaluation_v1(
        fixture.runner(),
        &fixture.snapshot,
        &fixture.receipt,
        &fixture.qualification,
        &fixture.request(now),
    )?;
    let (training, mut evaluation) = original_owners(&fixture, prepared.clone())?;
    // This Product signature has just passed qualification revalidation, but
    // its payload belongs to a different domain from the iteration receipt.
    assert_ne!(
        evaluation.signature.payload_digest,
        fixture.evidence.evaluator_bundle.payload_digest
    );
    evaluation.signature = fixture.evidence.evaluator_bundle.clone();
    let (trainer, trainer_server) = training.client()?;
    let (evaluator, evaluator_server) = evaluation.client()?;
    let head = fixture.snapshot.head_digest;
    let trainer_peer = serve(trainer_server, training, head, /*requests*/ 1);
    let evaluator_peer = serve(evaluator_server, evaluation, head, /*requests*/ 1);
    assert!(matches!(
        read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await,
        Err(CellLearningEvaluationReadbackErrorV1::Evidence(
            Error::Evidence(SignedEvidenceError::PayloadMismatch)
        ))
    ));
    assert!(matches!(
        evaluator.readback(&fixture.snapshot, &prepared).await,
        Err(Error::OwnerUnavailable(_))
    ));
    trainer_peer.join().expect("original trainer readback")?;
    evaluator_peer
        .join()
        .expect("wrong-domain evaluator fixture")?;
    Ok(())
}

#[tokio::test]
async fn missing_original_trainer_refuses_no_update_before_contacting_evaluator()
-> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let fixture = LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
    let prepared = prepare_cell_learning_evaluation_v1(
        fixture.runner(),
        &fixture.snapshot,
        &fixture.receipt,
        &fixture.qualification,
        &fixture.request(now),
    )?;
    let (training, evaluation) = original_owners(&fixture, prepared)?;
    let (trainer, trainer_server) = training.client()?;
    let (evaluator, mut evaluator_server) = evaluation.client()?;
    drop(trainer_server);
    evaluator_server.set_nonblocking(true)?;
    assert!(matches!(
        read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await,
        Err(CellLearningEvaluationReadbackErrorV1::Evidence(
            Error::OwnerUnavailable(_)
        ))
    ));
    assert_eq!(
        evaluator_server
            .read(&mut [0])
            .expect_err("no evaluator request")
            .kind(),
        ErrorKind::WouldBlock
    );
    Ok(())
}

// The existing synthetic signed cohort now drives the native original receipt
// journal. This qualifies source binding and recovery, not deployed key custody.
fn receipt_config(
    fixture: &LearningFixture,
) -> anyhow::Result<OriginalCellEvaluationReceiptConfigV1> {
    Ok(OriginalCellEvaluationReceiptConfigV1 {
        training: fixture.snapshot.clone(),
        scope: FrozenLearningScopeV2::freeze(
            &fixture.snapshot.request,
            &fixture.snapshot.owners,
            LearningUpdateScopeV2::Cell,
            Digest32::of_bytes(b"rule"),
        )?,
        plan: fixture.receipt.plan().clone(),
        signing: OriginalCellEvaluationSigningConfigV1 {
            plan: fixture.receipt.plan().product_plan().clone(),
            execution_namespace: Digest32::of_bytes(b"binding"),
            signer: TrustedLearningSignerV1 {
                principal: fixture.context.evaluator.clone(),
                controller_id: fixture.context.evaluator.principal_id.clone(),
                verifying_key: SigningKey::from_bytes(&[42; 32]).verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
            verifier: fixture.verifier.clone(),
            maximum_signature_lifetime_seconds: 300,
        },
    })
}

fn receipt_file(path: &std::path::Path) -> anyhow::Result<std::fs::File> {
    Ok(std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)?)
}
fn receipt_witness(
    path: &std::path::Path,
    config: &OriginalCellEvaluationReceiptConfigV1,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        receipt_file(&path.join("witness"))?,
        JournalScope {
            scope_digest: config.signing.verifier.scope_digest(),
            objective_digest: config.signing.verifier.objective_digest(),
        },
        Generation::new(1)?,
        /*max_records*/ 64,
    )?)
}
fn trainer_fixture(
    fixture: &LearningFixture,
    training: &LearningIterationReceiptV1,
) -> anyhow::Result<Fixture> {
    Ok(Fixture {
        initial: LearningIterationCoordinatorV1::new(
            fixture.snapshot.request.clone(),
            fixture.snapshot.owners.clone(),
        )?
        .snapshot()
        .clone(),
        receipt: training.clone(),
        verifier: fixture.verifier.clone(),
        signature: fixture.stage_attestation(training),
    })
}

#[tokio::test]
async fn original_evaluation_receipt_signs_actual_qualification_and_recovers_original_bytes()
-> anyhow::Result<()> {
    for disposition in [
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        IndependentEvaluationDispositionV1::Ineligible,
    ] {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let mut fixture = LearningFixture::new_at(disposition, now);
        let config = receipt_config(&fixture)?;
        let path = tempfile::tempdir()?;
        let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
            receipt_file(&path.path().join("owner"))?,
            receipt_witness(path.path(), &config)?,
            config.clone(),
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let genesis = std::fs::read(path.path().join("owner"))?;
        let training = config.training.receipts.last().expect("Training");
        let original_trainer = trainer_fixture(&fixture, training)?;
        let (client, server) = original_trainer.client()?;
        let peer = serve(
            server,
            original_trainer,
            fixture.snapshot.head_digest,
            /*requests*/ 2,
        );
        let original = owner
            .attest_original_completion(fixture.receipt_owner_sources(&client))
            .await?;
        peer.join().expect("original Trainer")?;
        let prepared = prepare_cell_learning_evaluation_v1(
            fixture.runner(),
            &config.training,
            &fixture.receipt,
            &fixture.qualification,
            &fixture.request(now),
        )?;
        assert_eq!(original.0, prepared);
        assert_ne!(
            original.1.payload_digest,
            fixture.evidence.evaluator_bundle.payload_digest
        );
        config.signing.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &original.1,
            &learning_iteration_receipt_signing_bytes_v1(&original.0)?,
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
        )?;
        let completed = std::fs::read(path.path().join("owner"))?;
        drop(owner);
        let mut recovered = OriginalCellEvaluationReceiptOwnerV1::recover(
            receipt_file(&path.path().join("owner"))?,
            receipt_witness(path.path(), &config)?,
            config.clone(),
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(fixture.snapshot.clone())?;
        coordinator.record(original.0.clone(), original.0.observed_unix_seconds)?;
        fixture.snapshot = coordinator.snapshot().clone();
        let original_trainer = trainer_fixture(&fixture, training)?;
        let (client, server) = original_trainer.client()?;
        let peer = serve(
            server,
            original_trainer,
            fixture.snapshot.head_digest,
            /*requests*/ 1,
        );
        assert_eq!(
            recovered
                .readback(fixture.receipt_owner_sources(&client))
                .await?,
            original
        );
        peer.join().expect("recovered Trainer")?;
        assert_eq!(std::fs::read(path.path().join("owner"))?, completed);
        drop(recovered);
        std::fs::write(path.path().join("owner"), genesis)?;
        assert!(
            OriginalCellEvaluationReceiptOwnerV1::recover(
                receipt_file(&path.path().join("owner"))?,
                receipt_witness(path.path(), &config)?,
                config,
                SigningKey::from_bytes(&[42; 32])
            )
            .is_err()
        );
    }
    Ok(())
}

#[tokio::test]
async fn original_evaluation_receipt_rejects_changed_custody_namespace_and_unsigned_no_update()
-> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut fixture = LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
    let config = receipt_config(&fixture)?;
    for case in 0..5 {
        let path = tempfile::tempdir()?;
        let mut changed = config.clone();
        let mut key = SigningKey::from_bytes(&[42; 32]);
        match case {
            0 => key = SigningKey::from_bytes(&[43; 32]),
            1 => changed.signing.signer.controller_id = StableId::new("substituted-controller")?,
            2 => {
                changed.signing.signer.principal.credential_chain_digest =
                    Digest32::of_bytes(b"substituted-credential")
            }
            3 => {
                changed.signing.plan.frozen_plan.objective_digest =
                    Digest32::of_bytes(b"substituted-plan")
            }
            4 => changed.training.head_digest = Digest32::of_bytes(b"substituted-Training-cut"),
            _ => unreachable!(),
        }
        assert!(
            OriginalCellEvaluationReceiptOwnerV1::create(
                receipt_file(&path.path().join("owner"))?,
                receipt_witness(path.path(), &changed)?,
                changed,
                key
            )
            .is_err()
        );
        assert_eq!(std::fs::metadata(path.path().join("owner"))?.len(), 0);
    }
    for case in 0..3 {
        let path = tempfile::tempdir()?;
        let mut changed = config.clone();
        if case == 0 {
            changed.signing.execution_namespace = Digest32::of_bytes(b"another-owner-namespace");
        }
        let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
            receipt_file(&path.path().join("owner"))?,
            receipt_witness(path.path(), &changed)?,
            changed,
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let before = std::fs::read(path.path().join("owner"))?;
        let original_trainer =
            trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
        let (client, server) = original_trainer.client()?;
        drop(server);
        let evidence = fixture.evidence.clone();
        if case == 1 {
            fixture.evidence.evaluator_bundle.signature[0] ^= 1;
        }
        let result = owner
            .attest_original_completion(fixture.receipt_owner_sources(&client))
            .await;
        match case {
            0 => assert!(matches!(
                result,
                Err(OriginalCellEvaluationReceiptErrorV1::Cell(_))
            )),
            1 => assert!(matches!(
                result,
                Err(OriginalCellEvaluationReceiptErrorV1::Preparation(_))
            )),
            2 => assert!(matches!(
                result,
                Err(OriginalCellEvaluationReceiptErrorV1::Trainer(_))
            )),
            _ => unreachable!(),
        }
        fixture.evidence = evidence;
        assert_eq!(std::fs::read(path.path().join("owner"))?, before);
    }
    Ok(())
}

struct ReceiptLostAck {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    after_write: bool,
}
impl AnchorWitnessStore for ReceiptLostAck {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if self.after_write {
                self.inner.compare_and_swap(expected, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn original_evaluation_receipt_pending_never_resigns_and_complete_ack_replays()
-> anyhow::Result<()> {
    for sequence in [2, 3] {
        for after_write in [false, true] {
            let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
            let mut fixture =
                LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
            let config = receipt_config(&fixture)?;
            let path = tempfile::tempdir()?;
            let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
                receipt_file(&path.path().join("owner"))?,
                ReceiptLostAck {
                    inner: receipt_witness(path.path(), &config)?,
                    sequence,
                    after_write,
                },
                config.clone(),
                SigningKey::from_bytes(&[42; 32]),
            )?;
            let original_trainer =
                trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
            let (client, server) = original_trainer.client()?;
            let peer = serve(
                server,
                original_trainer,
                fixture.snapshot.head_digest,
                /*requests*/ 1,
            );
            assert!(matches!(
                owner
                    .attest_original_completion(fixture.receipt_owner_sources(&client))
                    .await,
                Err(OriginalCellEvaluationReceiptErrorV1::Owner(
                    crate::LearningOriginalOwnerErrorV1::CommitUncertain
                ))
            ));
            peer.join().expect("original Trainer before claim")?;
            drop(owner);
            let mut owner = OriginalCellEvaluationReceiptOwnerV1::recover(
                receipt_file(&path.path().join("owner"))?,
                receipt_witness(path.path(), &config)?,
                config.clone(),
                SigningKey::from_bytes(&[42; 32]),
            )?;
            let before = std::fs::read(path.path().join("owner"))?;
            if sequence == 2 {
                assert!(matches!(
                    owner.readback(fixture.receipt_owner_sources(&client)).await,
                    Err(OriginalCellEvaluationReceiptErrorV1::Owner(
                        crate::LearningOriginalOwnerErrorV1::Pending
                    ))
                ));
                let original_trainer =
                    trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
                let (client, server) = original_trainer.client()?;
                let peer = serve(
                    server,
                    original_trainer,
                    fixture.snapshot.head_digest,
                    /*requests*/ 1,
                );
                assert!(matches!(
                    owner
                        .attest_original_completion(fixture.receipt_owner_sources(&client))
                        .await,
                    Err(OriginalCellEvaluationReceiptErrorV1::Owner(
                        crate::LearningOriginalOwnerErrorV1::Pending
                    ))
                ));
                peer.join().expect("Pending recheck")?;
            } else {
                let original_trainer =
                    trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
                let (client, server) = original_trainer.client()?;
                let peer = serve(
                    server,
                    original_trainer,
                    fixture.snapshot.head_digest,
                    /*requests*/ 2,
                );
                let first = owner
                    .readback(fixture.receipt_owner_sources(&client))
                    .await?;
                assert_eq!(
                    owner
                        .readback(fixture.receipt_owner_sources(&client))
                        .await?,
                    first
                );
                peer.join().expect("completed original signatures")?;
            }
            assert_eq!(std::fs::read(path.path().join("owner"))?, before);
        }
    }
    Ok(())
}

struct DisappearingExecution<'a, E> {
    inner: &'a mut E,
    reads: usize,
    disappear_at: usize,
}
impl<E: codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1>
    codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1
    for DisappearingExecution<'_, E>
{
    fn claim(
        &mut self,
        _: &codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1,
    ) -> Result<
        codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1,
        codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1,
    > {
        panic!("receipt owner cannot claim an execution")
    }
    fn complete(
        &mut self,
        _: &codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1,
        _: &[u8],
    ) -> Result<(), codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1> {
        panic!("receipt owner cannot complete an execution")
    }
    fn readback(
        &mut self,
        key: &codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1,
    ) -> Result<
        codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1,
        codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1,
    > {
        self.reads += 1;
        if self.reads >= self.disappear_at {
            return Err(
                codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1::Missing,
            );
        }
        self.inner.readback(key)
    }
}

#[tokio::test]
async fn original_evaluation_receipt_rechecks_source_before_signing_and_after_commit()
-> anyhow::Result<()> {
    for disappear_at in [2, 3] {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let mut fixture =
            LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
        let config = receipt_config(&fixture)?;
        let path = tempfile::tempdir()?;
        let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
            receipt_file(&path.path().join("owner"))?,
            receipt_witness(path.path(), &config)?,
            config.clone(),
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let before = std::fs::read(path.path().join("owner"))?;
        let original_trainer =
            trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
        let (client, server) = original_trainer.client()?;
        let peer = serve(
            server,
            original_trainer,
            fixture.snapshot.head_digest,
            (disappear_at - 1) as u64,
        );
        let source = fixture.receipt_owner_sources(&client);
        let mut executions = DisappearingExecution {
            inner: source.executions,
            reads: 0,
            disappear_at,
        };
        let source = OriginalCellEvaluationReceiptSourcesV1 {
            executions: &mut executions,
            snapshot: source.snapshot,
            runner: source.runner,
            journals: source.journals,
            candidate_plan: source.candidate_plan,
            baseline_plan: source.baseline_plan,
            qualification: source.qualification,
            context: source.context,
            evidence: source.evidence,
            timing: source.timing,
            trainer: source.trainer,
        };
        assert!(matches!(
            owner.attest_original_completion(source).await,
            Err(OriginalCellEvaluationReceiptErrorV1::Cell(_))
        ));
        peer.join().expect("source freshness reads")?;
        let after = std::fs::read(path.path().join("owner"))?;
        if disappear_at == 2 {
            assert_eq!(after, before);
        } else {
            assert_ne!(after, before);
        }
    }
    Ok(())
}

#[tokio::test]
async fn original_evaluation_receipt_expired_signature_is_not_renewed() -> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut fixture = LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
    let mut config = receipt_config(&fixture)?;
    config.signing.maximum_signature_lifetime_seconds = 3;
    let path = tempfile::tempdir()?;
    let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
        receipt_file(&path.path().join("owner"))?,
        receipt_witness(path.path(), &config)?,
        config.clone(),
        SigningKey::from_bytes(&[42; 32]),
    )?;
    let original_trainer =
        trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
    let (client, server) = original_trainer.client()?;
    let peer = serve(
        server,
        original_trainer,
        fixture.snapshot.head_digest,
        /*requests*/ 2,
    );
    owner
        .attest_original_completion(fixture.receipt_owner_sources(&client))
        .await?;
    peer.join().expect("initial signing")?;
    let before = std::fs::read(path.path().join("owner"))?;
    tokio::time::sleep(Duration::from_secs(4)).await;
    let original_trainer =
        trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
    let (client, server) = original_trainer.client()?;
    let peer = serve(
        server,
        original_trainer,
        fixture.snapshot.head_digest,
        /*requests*/ 3,
    );
    assert!(matches!(
        owner.readback(fixture.receipt_owner_sources(&client)).await,
        Err(OriginalCellEvaluationReceiptErrorV1::Evidence(
            SignedEvidenceError::ValidityWindow
        ))
    ));
    assert!(matches!(
        owner
            .attest_original_completion(fixture.receipt_owner_sources(&client))
            .await,
        Err(OriginalCellEvaluationReceiptErrorV1::Evidence(
            SignedEvidenceError::ValidityWindow
        ))
    ));
    peer.join().expect("expired original signature readback")?;
    assert_eq!(std::fs::read(path.path().join("owner"))?, before);
    Ok(())
}
