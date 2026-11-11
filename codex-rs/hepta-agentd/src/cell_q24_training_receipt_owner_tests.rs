//! Real native Q24 optimization, original signature files and independent
//! witnesses, with explicit credential/Dataset fixtures. These are not real
//! source custody, daemon/Root cold restart, adoption or independent B evidence.

use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::LearningOriginalOwnerErrorV1;
use crate::OriginalCellQ24TrainingReceiptErrorV1 as ReceiptError;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;

#[path = "cell_q24_training_stage_tests.rs"]
mod stage;

#[path = "cell_q24_training_snapshot_readback_tests.rs"]
mod snapshot_readback;

fn clock() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs())
}

fn signing_config(
    prefix: &LearningIterationSnapshotV1,
    data: &CellQ24TrainingBatchV1,
    rule: CellQ24SgdRuleV1,
) -> anyhow::Result<OriginalCellQ24TrainingSigningConfigV1> {
    let key = SigningKey::from_bytes(&[79; 32]);
    let now = clock()?;
    let signer = TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: prefix.owners.trainer.clone(),
            credential_chain_digest: d("explicit-training-credential-fixture"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: d("explicit-training-trust-fixture"),
            authority_epoch: 7,
            authenticated_at: now - 1,
            expires_at: now + 900,
        },
        controller_id: StableId::new("original-generator-fixture")?,
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![LearningEvidenceRoleV1::Generator],
        revoked_at: None,
    };
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: signer.principal.scope_digest,
        objective_digest: prefix.request.envelope.objective_digest,
        authority_epoch: 7,
        signers: vec![signer.clone()],
    })?;
    let mut owners = prefix.owners.clone();
    owners.evidence_trust_digest = verifier.trust_digest();
    let mut coordinator = LearningIterationCoordinatorV1::new(prefix.request.clone(), owners)?;
    for original in &prefix.receipts {
        let mut receipt = original.clone();
        receipt.predecessor = coordinator.snapshot().head_digest;
        coordinator.record(receipt, original.observed_unix_seconds)?;
    }
    let dataset = coordinator.snapshot().clone();
    let scope = FrozenLearningScopeV2::freeze(
        &dataset.request,
        &dataset.owners,
        LearningUpdateScopeV2::Cell,
        cell_q24_single_head_update_rule_v1(
            &dataset.request.selected_bundle,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            rule.digest(data)?,
        )?,
    )?;
    Ok(OriginalCellQ24TrainingSigningConfigV1 {
        dataset,
        scope,
        signer,
        verifier,
        maximum_signature_lifetime_seconds: 300,
    })
}

struct ReceiptFixture {
    root: tempfile::TempDir,
    baseline: Arc<LoadedCellQ24ModelV1>,
    data: CellQ24TrainingBatchV1,
    rule: CellQ24SgdRuleV1,
    config: OriginalCellQ24TrainingSigningConfigV1,
}

impl ReceiptFixture {
    fn new(target: i64) -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
        let selected = bundle(&baseline, /*prior*/ None)?;
        let data = batch(target)?;
        let rule = CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        };
        let (_, prefix) = plan(
            Arc::clone(&baseline),
            &selected,
            &data,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            rule,
            "none",
        )?;
        let config = signing_config(&prefix, &data, rule)?;
        Ok(Self {
            root,
            baseline,
            data,
            rule,
            config,
        })
    }

    fn create_training(&self) -> anyhow::Result<CellQ24TrainingOwnerV1<FileAnchorWitnessStore>> {
        Ok(CellQ24TrainingOwnerV1::create(
            opened(self.root.path(), "job")?,
            witness(self.root.path())?,
            original_plan(
                Arc::clone(&self.baseline),
                &self.config.dataset,
                &self.data,
                self.rule,
            )?,
            self.data.clone(),
            self.rule,
        )?)
    }

    fn recover_training(&self) -> anyhow::Result<CellQ24TrainingOwnerV1<FileAnchorWitnessStore>> {
        Ok(CellQ24TrainingOwnerV1::recover(
            opened(self.root.path(), "job")?,
            witness(self.root.path())?,
            original_plan(
                Arc::clone(&self.baseline),
                &self.config.dataset,
                &self.data,
                self.rule,
            )?,
            self.data.clone(),
            self.rule,
        )?)
    }

    fn receipt_witness(&self) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            opened(self.root.path(), "receipt-witness")?,
            JournalScope {
                scope_digest: self.config.scope.binding(),
                objective_digest: self.config.dataset.request.envelope.objective_digest,
            },
            Generation::new(1)?,
            /*max_records*/ 16,
        )?)
    }

    fn create_receipts(
        &self,
    ) -> anyhow::Result<OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>> {
        Ok(OriginalCellQ24TrainingReceiptOwnerV1::create(
            opened(self.root.path(), "receipts")?,
            self.receipt_witness()?,
            self.config.clone(),
            SigningKey::from_bytes(&[79; 32]),
        )?)
    }

    fn recover_receipts(
        &self,
    ) -> anyhow::Result<OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>> {
        Ok(OriginalCellQ24TrainingReceiptOwnerV1::recover(
            opened(self.root.path(), "receipts")?,
            self.receipt_witness()?,
            self.config.clone(),
            SigningKey::from_bytes(&[79; 32]),
        )?)
    }
}

#[test]
fn original_training_receipt_signs_actual_candidate_and_no_update_then_reopens_exactly()
-> anyhow::Result<()> {
    for target in [2 * Q, Q] {
        let f = ReceiptFixture::new(target)?;
        let mut training = f.create_training()?;
        let mut receipts = f.create_receipts()?;
        let empty = fs::read(f.root.path().join("receipts"))?;
        assert!(receipts.attest_original_completion(&mut training).is_err());
        assert_eq!(fs::read(f.root.path().join("receipts"))?, empty);
        let outcome = training.fit_or_readback(&AtomicBool::new(false))?;
        let original_training = fs::read(f.root.path().join("job"))?;
        let observation = training.read_learning_observation(&f.config.dataset)?;
        let first = receipts.attest_original_completion(&mut training)?;
        assert_eq!(first.0.observation, *observation.observation());
        assert_eq!(first.0.evidence_digest, observation.evidence_digest());
        assert_eq!(first.0.observed_unix_seconds, first.1.issued_at);
        assert_eq!(
            f.config
                .verifier
                .verify(
                    LearningEvidenceRoleV1::Generator,
                    &first.1,
                    &learning_iteration_receipt_signing_bytes_v1(&first.0)?,
                    clock()?
                )?
                .principal(),
            &f.config.signer.principal
        );
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(f.config.dataset.clone())?;
        coordinator.record(first.0.clone(), first.0.observed_unix_seconds)?;
        f.config.scope.validate_snapshot(coordinator.snapshot())?;
        assert_eq!(
            coordinator.next_stage(),
            Some(if target == Q {
                LearningIterationStageV1::Selection
            } else {
                LearningIterationStageV1::Evaluation
            })
        );
        let saved = fs::read(f.root.path().join("receipts"))?;
        std::thread::sleep(std::time::Duration::from_secs(1));
        assert!(clock()? > first.1.issued_at);
        assert_eq!(receipts.attest_original_completion(&mut training)?, first);
        drop(receipts);
        drop(training);
        let mut training = f.recover_training()?;
        let mut receipts = f.recover_receipts()?;
        assert_eq!(receipts.readback(&mut training)?, first);
        assert_eq!(receipts.attest_original_completion(&mut training)?, first);
        assert_eq!(
            result_identity(&training.readback()?)?,
            result_identity(&outcome)?
        );
        assert_eq!(fs::read(f.root.path().join("job"))?, original_training);
        assert_eq!(fs::read(f.root.path().join("receipts"))?, saved);
        drop(receipts);
        fs::write(f.root.path().join("receipts"), empty)?;
        assert!(f.recover_receipts().is_err());
    }
    Ok(())
}

#[test]
fn original_training_receipt_refuses_wrong_key_trust_scope_and_changed_dataset_prefix()
-> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    for change in ["key", "controller", "role", "trust", "scope"] {
        let mut config = f.config.clone();
        let key = if change == "key" {
            SigningKey::from_bytes(&[80; 32])
        } else {
            SigningKey::from_bytes(&[79; 32])
        };
        match change {
            "controller" => config.signer.controller_id = StableId::new("substituted-controller")?,
            "role" => config.signer.roles = vec![LearningEvidenceRoleV1::Observer],
            "trust" => config.dataset.owners.evidence_trust_digest = d("substituted-trust"),
            "scope" => {
                let mut request = config.dataset.request.clone();
                request.source_run_id = StableId::new("substituted-scope-source")?;
                config.scope = FrozenLearningScopeV2::freeze(
                    &request,
                    &config.dataset.owners,
                    LearningUpdateScopeV2::Cell,
                    d("substituted-rule"),
                )?;
            }
            "key" => {}
            _ => anyhow::bail!("unknown binding mutation"),
        }
        assert!(
            OriginalCellQ24TrainingReceiptOwnerV1::create(
                opened(f.root.path(), "receipts")?,
                f.receipt_witness()?,
                config,
                key
            )
            .is_err()
        );
        assert_eq!(fs::metadata(f.root.path().join("receipts"))?.len(), 0);
    }
    let mut training = f.create_training()?;
    training.fit_or_readback(&AtomicBool::new(false))?;
    let mut rebound = f.config.dataset.clone();
    rebound.request.source_run_id = StableId::new("different-dataset-source")?;
    let changed = signing_config(&rebound, &f.data, f.rule)?;
    let mut receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
        opened(f.root.path(), "receipts")?,
        f.receipt_witness()?,
        changed,
        SigningKey::from_bytes(&[79; 32]),
    )?;
    let empty = fs::read(f.root.path().join("receipts"))?;
    assert!(matches!(
        receipts.attest_original_completion(&mut training),
        Err(ReceiptError::Training(OwnerError::Binding(_)))
    ));
    assert_eq!(fs::read(f.root.path().join("receipts"))?, empty);
    drop(receipts);
    assert!(f.recover_receipts().is_err());
    Ok(())
}

#[test]
fn original_training_receipt_pending_native_job_never_claims_or_signs() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    assert!(matches!(
        training.fit_or_readback(&AtomicBool::new(true)),
        Err(OwnerError::Training(CellQ24TrainingErrorV1::Cancelled))
    ));
    let pending = fs::read(f.root.path().join("job"))?;
    drop(training);
    let mut training = f.recover_training()?;
    let mut receipts = f.create_receipts()?;
    let empty = fs::read(f.root.path().join("receipts"))?;
    assert!(matches!(
        receipts.attest_original_completion(&mut training),
        Err(ReceiptError::Training(OwnerError::Pending))
    ));
    assert!(matches!(
        receipts.readback(&mut training),
        Err(ReceiptError::Training(OwnerError::Pending))
    ));
    assert_eq!(fs::read(f.root.path().join("receipts"))?, empty);
    assert_eq!(fs::read(f.root.path().join("job"))?, pending);
    Ok(())
}

#[test]
fn original_training_receipt_lost_ack_reopens_pending_or_exact_completed_signature()
-> anyhow::Result<()> {
    for sequence in [2, 3] {
        for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
            let f = ReceiptFixture::new(2 * Q)?;
            let mut training = f.create_training()?;
            training.fit_or_readback(&AtomicBool::new(false))?;
            let original_training = fs::read(f.root.path().join("job"))?;
            let mut receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
                opened(f.root.path(), "receipts")?,
                FaultWitness {
                    inner: f.receipt_witness()?,
                    sequence,
                    fault,
                },
                f.config.clone(),
                SigningKey::from_bytes(&[79; 32]),
            )?;
            assert!(matches!(
                receipts.attest_original_completion(&mut training),
                Err(ReceiptError::Owner(
                    LearningOriginalOwnerErrorV1::CommitUncertain
                ))
            ));
            drop(receipts);
            let mut receipts = f.recover_receipts()?;
            let saved = fs::read(f.root.path().join("receipts"))?;
            if sequence == 2 {
                assert!(matches!(
                    receipts.readback(&mut training),
                    Err(ReceiptError::Owner(LearningOriginalOwnerErrorV1::Pending))
                ));
                assert!(matches!(
                    receipts.attest_original_completion(&mut training),
                    Err(ReceiptError::Owner(LearningOriginalOwnerErrorV1::Pending))
                ));
            } else {
                let first = receipts.readback(&mut training)?;
                assert_eq!(receipts.attest_original_completion(&mut training)?, first);
                assert_eq!(receipts.readback(&mut training)?, first);
            }
            assert_eq!(fs::read(f.root.path().join("receipts"))?, saved);
            assert_eq!(fs::read(f.root.path().join("job"))?, original_training);
        }
    }
    Ok(())
}

#[test]
fn original_training_receipt_expired_signature_never_renews_or_retrains() -> anyhow::Result<()> {
    let mut f = ReceiptFixture::new(2 * Q)?;
    f.config.maximum_signature_lifetime_seconds = 1;
    let mut training = f.create_training()?;
    training.fit_or_readback(&AtomicBool::new(false))?;
    let mut receipts = f.create_receipts()?;
    let first = receipts.attest_original_completion(&mut training)?;
    let original_training = fs::read(f.root.path().join("job"))?;
    let original_receipts = fs::read(f.root.path().join("receipts"))?;
    std::thread::sleep(std::time::Duration::from_secs(2));
    assert!(clock()? > first.1.expires_at);
    assert!(matches!(
        receipts.readback(&mut training),
        Err(ReceiptError::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    assert!(matches!(
        receipts.attest_original_completion(&mut training),
        Err(ReceiptError::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    drop(receipts);
    let mut receipts = f.recover_receipts()?;
    assert!(matches!(
        receipts.readback(&mut training),
        Err(ReceiptError::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    assert!(matches!(
        receipts.attest_original_completion(&mut training),
        Err(ReceiptError::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    assert_eq!(fs::read(f.root.path().join("job"))?, original_training);
    assert_eq!(fs::read(f.root.path().join("receipts"))?, original_receipts);
    Ok(())
}

#[test]
fn original_training_receipt_lost_genesis_witness_ack_stays_blocked() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    assert!(matches!(
        OriginalCellQ24TrainingReceiptOwnerV1::create(
            opened(f.root.path(), "receipts")?,
            FaultWitness {
                inner: f.receipt_witness()?,
                sequence: 1,
                fault: LostAck::BeforeWrite,
            },
            f.config.clone(),
            SigningKey::from_bytes(&[79; 32]),
        ),
        Err(ReceiptError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    let original_receipts = fs::read(f.root.path().join("receipts"))?;
    let original_witness = fs::read(f.root.path().join("receipt-witness"))?;
    assert!(!original_receipts.is_empty());
    assert_eq!(f.receipt_witness()?.current()?, None);
    assert!(matches!(
        OriginalCellQ24TrainingReceiptOwnerV1::recover(
            opened(f.root.path(), "receipts")?,
            f.receipt_witness()?,
            f.config.clone(),
            SigningKey::from_bytes(&[79; 32]),
        ),
        Err(ReceiptError::Owner(LearningOriginalOwnerErrorV1::Binding(
            "original independent witness"
        )))
    ));
    assert!(matches!(
        OriginalCellQ24TrainingReceiptOwnerV1::create(
            opened(f.root.path(), "receipts")?,
            f.receipt_witness()?,
            f.config.clone(),
            SigningKey::from_bytes(&[79; 32]),
        ),
        Err(ReceiptError::Owner(LearningOriginalOwnerErrorV1::File(
            LockedFileProductEvaluationExecutionErrorV1::AlreadyInitialized
        )))
    ));
    assert_eq!(f.receipt_witness()?.current()?, None);
    assert_eq!(fs::read(f.root.path().join("receipts"))?, original_receipts);
    assert_eq!(
        fs::read(f.root.path().join("receipt-witness"))?,
        original_witness
    );
    Ok(())
}
