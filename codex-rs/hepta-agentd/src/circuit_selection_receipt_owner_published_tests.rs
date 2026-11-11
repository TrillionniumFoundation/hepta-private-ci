//! Actual ordinary A, same-model publication and sealed version readback.
//! Enrollment, TrainingNoUpdate and peer transports are explicit fixtures.
//! This qualifies Selection custody mechanics, not a production owner host or
//! an independently trained positive candidate.

use super::*;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use pretty_assertions::assert_eq;
use std::path::Path;

use crate::OriginalCircuitSelectionReceiptConfigV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::OriginalCircuitSelectionReceiptSourcesV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;

type SelectionOwner = OriginalCircuitSelectionReceiptOwnerV1<FileAnchorWitnessStore>;

struct SelectionFixture {
    original: ObserverFixture,
    root: tempfile::TempDir,
    config: OriginalCircuitSelectionReceiptConfigV1,
}

impl SelectionFixture {
    async fn ready() -> anyhow::Result<Self> {
        let original = ObserverFixture::ready().await?;
        let mut decision = original.config.selection.clone();
        let fixture_selection = decision.receipts.pop().context("fixture Selection")?;
        decision.head_digest = fixture_selection.predecessor;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(decision.clone())?;
        assert_eq!(
            coordinator.next_stage(),
            Some(LearningIterationStageV1::Selection)
        );
        let key = SigningKey::from_bytes(&[102; 32]);
        // This is the fixture's already enrolled Selector, with exactly the
        // same original principal lifetime. No production enrollment is done.
        let trusted = &original.config.signer.principal;
        let signer = TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: decision.owners.selector.clone(),
                credential_chain_digest: d("explicit-observer-credential-1"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: trusted.scope_digest,
                authority_epoch: trusted.authority_epoch,
                authenticated_at: trusted.authenticated_at,
                expires_at: trusted.expires_at,
            },
            controller_id: StableId::new("explicit-observer-controller-1")?,
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Selector],
            revoked_at: None,
        };
        let config = OriginalCircuitSelectionReceiptConfigV1 {
            decision,
            scope: original.config.scope.clone(),
            signer,
            verifier: original.config.verifier.clone(),
            training_evidence: original.training_signature.clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        Ok(Self {
            original,
            root: tempfile::tempdir()?,
            config,
        })
    }

    fn sources<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        trainer: &'a LearningIterationEvidenceClientV1,
    ) -> OriginalCircuitSelectionReceiptSourcesV1<'a, FileAnchorWitnessStore> {
        OriginalCircuitSelectionReceiptSourcesV1 {
            snapshot,
            cell: &self.original.session.cell,
            trainer,
        }
    }

    fn peer(
        &self,
        evidence: SignedLearningEvidenceV1,
        reads: usize,
    ) -> anyhow::Result<(LearningIterationEvidenceClientV1, PeerThread)> {
        fixture_original_receipt_client(
            self.original.initial.clone(),
            self.original.training.clone(),
            self.config.verifier.clone(),
            evidence,
            reads,
        )
    }

    fn create(&self) -> anyhow::Result<SelectionOwner> {
        Ok(OriginalCircuitSelectionReceiptOwnerV1::create(
            opened(self.root.path(), "journal", true)?,
            witness(self.root.path(), &self.config, true)?,
            self.config.clone(),
            SigningKey::from_bytes(&[102; 32]),
        )?)
    }

    fn recover(&self) -> anyhow::Result<SelectionOwner> {
        Ok(OriginalCircuitSelectionReceiptOwnerV1::recover(
            opened(self.root.path(), "journal", false)?,
            witness(self.root.path(), &self.config, false)?,
            self.config.clone(),
            SigningKey::from_bytes(&[102; 32]),
        )?)
    }

    fn bytes(&self) -> anyhow::Result<(Vec<u8>, Vec<u8>)> {
        Ok((
            fs::read(self.root.path().join("journal"))?,
            fs::read(self.root.path().join("witness"))?,
        ))
    }
}

fn opened(root: &Path, name: &str, create: bool) -> anyhow::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).mode(0o600);
    if create {
        options.create_new(true);
    }
    Ok(options.open(root.join(name))?)
}

fn witness(
    root: &Path,
    config: &OriginalCircuitSelectionReceiptConfigV1,
    create: bool,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(root, "witness", create)?,
        JournalScope {
            scope_digest: config.scope.binding(),
            objective_digest: config.decision.request.envelope.objective_digest,
        },
        Generation::new(1)?,
        16,
    )?)
}

fn finish(client: LearningIterationEvidenceClientV1, thread: PeerThread) -> anyhow::Result<()> {
    drop(client);
    thread
        .join()
        .map_err(|_| anyhow::anyhow!("original Trainer fixture panicked"))??;
    Ok(())
}

#[tokio::test]
async fn q24_original_selector_attests_actual_publication_and_recovers_exact_signature()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let original = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    let expected = f.original.session.cell.read_learning_selection(&original)?;
    assert!(
        matches!(&expected, LearningIterationObservationV1::Selection {
        candidate_bundle, ..
    } if *candidate_bundle == f.config.decision.request.selected_bundle.digest()?)
    );
    let (trainer, peer) = f.peer(f.config.training_evidence.clone(), 5)?;
    let mut owner = f.create()?;
    let before = f.bytes()?;
    assert!(matches!(
        owner
            .readback(f.sources(&f.config.decision, &trainer))
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
            OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
        ))
    ));
    assert_eq!(f.bytes()?, before);

    let saved = owner
        .attest_original_selection(f.sources(&f.config.decision, &trainer))
        .await?;
    assert_eq!(saved.0.observation, expected);
    assert_eq!(saved.0.observed_unix_seconds, saved.1.issued_at);
    assert_eq!(saved.1.role, LearningEvidenceRoleV1::Selector);
    assert!(saved.1.expires_at > saved.1.issued_at);
    assert!(saved.1.expires_at - saved.1.issued_at <= 300);
    let bytes = f.bytes()?;
    // Repeated dispatch reads the same original signature, without a new claim.
    assert_eq!(
        owner
            .attest_original_selection(f.sources(&f.config.decision, &trainer))
            .await?,
        saved
    );
    assert_eq!(f.bytes()?, bytes);
    let mut selected = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    selected.record(saved.0.clone(), saved.0.observed_unix_seconds)?;
    assert_eq!(
        selected.next_stage(),
        Some(LearningIterationStageV1::NextUse)
    );
    assert_eq!(
        owner
            .readback(f.sources(selected.snapshot(), &trainer))
            .await?,
        saved
    );

    // C was published but has not run. The actual new Selector receipt is
    // accepted by the sealed next-use readback only after C really completes.
    assert!(
        f.original
            .session
            .cell
            .read_learning_next_use(
                &selected,
                f.original.session.source.as_ref(),
                &f.original.session.runtime.identity,
            )
            .is_err()
    );
    let publication = execute(&f.original.session, 1).await?;
    let actual = read_receipt(&f.original.session, &f.original.definition, &publication)?;
    assert_ne!(
        publication.input().scope.run_id,
        f.original.previous.input().scope.run_id
    );
    assert_ne!(
        publication.input().observation,
        f.original.previous.input().observation
    );
    assert_eq!(
        actual.bundle_digest,
        f.original.previous_decision.bundle_digest
    );
    assert!(matches!(
        f.original.session.cell.read_learning_next_use(
            &selected,
            f.original.session.source.as_ref(),
            &f.original.session.runtime.identity,
        )?,
        LearningIterationObservationV1::RetainedModelNextUse { .. }
    ));

    drop(owner);
    let mut recovered = f.recover()?;
    assert_eq!(f.bytes()?, bytes);
    assert_eq!(
        recovered
            .readback(f.sources(selected.snapshot(), &trainer))
            .await?,
        saved
    );
    assert_eq!(f.bytes()?, bytes);
    f.original.version.withdraw()?;
    assert!(matches!(
        recovered
            .readback(f.sources(selected.snapshot(), &trainer))
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Observation(_))
    ));
    assert_eq!(f.bytes()?, bytes);
    drop(recovered);
    finish(trainer, peer)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_original_selector_refuses_withdrawn_publication_before_claim() -> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    f.original.version.withdraw()?;
    let (trainer, peer) = f.peer(f.config.training_evidence.clone(), 0)?;
    let mut owner = f.create()?;
    let before = f.bytes()?;
    assert!(matches!(
        owner
            .attest_original_selection(f.sources(&f.config.decision, &trainer))
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Observation(_))
    ));
    assert_eq!(f.bytes()?, before);
    drop(owner);
    let mut recovered = f.recover()?;
    assert!(matches!(
        recovered
            .readback(f.sources(&f.config.decision, &trainer))
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Observation(_))
    ));
    assert_eq!(f.bytes()?, before);
    drop(recovered);
    finish(trainer, peer)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_original_selector_refuses_valid_training_renewal_live_and_cold() -> anyhow::Result<()>
{
    let mut f = SelectionFixture::ready().await?;
    let mut renewed = f.config.training_evidence.clone();
    renewed.expires_at += 1;
    renewed.signature = SigningKey::from_bytes(&[101; 32])
        .sign(&renewed.signing_bytes())
        .to_bytes();
    f.config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &renewed,
        &learning_iteration_receipt_signing_bytes_v1(&f.original.training)?,
        now()?,
    )?;
    let (changed, changed_peer) = f.peer(renewed.clone(), 1)?;
    let mut owner = f.create()?;
    let before = f.bytes()?;
    assert!(matches!(
        owner
            .attest_original_selection(f.sources(&f.config.decision, &changed))
            .await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
            OwnerError::Binding("changed original Training signature")
        ))
    ));
    assert_eq!(f.bytes()?, before);
    drop(owner);
    finish(changed, changed_peer)?;

    let mut changed_config = f.config.clone();
    changed_config.training_evidence = renewed;
    assert!(
        OriginalCircuitSelectionReceiptOwnerV1::recover(
            opened(f.root.path(), "journal", false)?,
            witness(f.root.path(), &changed_config, false)?,
            changed_config,
            SigningKey::from_bytes(&[102; 32]),
        )
        .is_err()
    );
    assert_eq!(f.bytes()?, before);
    let mut original = f.recover()?;
    let (trainer, peer) = f.peer(f.config.training_evidence.clone(), 2)?;
    original
        .attest_original_selection(f.sources(&f.config.decision, &trainer))
        .await?;
    drop(original);
    finish(trainer, peer)?;
    f.original.session.stop().await?;
    Ok(())
}

struct RefuseWitnessAppend {
    original: FileAnchorWitnessStore,
    calls: usize,
    fail_at: usize,
}

impl AnchorWitnessStore for RefuseWitnessAppend {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.original.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.calls += 1;
        if self.calls == self.fail_at {
            return Err(WitnessStoreError::Indeterminate);
        }
        self.original.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn q24_original_selector_preserves_pending_and_recovers_completed_lost_ack()
-> anyhow::Result<()> {
    for fail_at in [2, 3] {
        let mut f = SelectionFixture::ready().await?;
        let (trainer, peer) = f.peer(
            f.config.training_evidence.clone(),
            if fail_at == 2 { 1 } else { 3 },
        )?;
        let mut owner = OriginalCircuitSelectionReceiptOwnerV1::create(
            opened(f.root.path(), "journal", true)?,
            RefuseWitnessAppend {
                original: witness(f.root.path(), &f.config, true)?,
                calls: 0,
                fail_at,
            },
            f.config.clone(),
            SigningKey::from_bytes(&[102; 32]),
        )?;
        assert!(matches!(
            owner
                .attest_original_selection(f.sources(&f.config.decision, &trainer))
                .await,
            Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
                OwnerError::CommitUncertain
            ))
        ));
        let original_journal = f.bytes()?.0;
        drop(owner);
        let mut recovered = f.recover()?;
        assert_eq!(f.bytes()?.0, original_journal);
        let recovered_bytes = f.bytes()?;
        if fail_at == 2 {
            assert!(matches!(
                recovered
                    .attest_original_selection(f.sources(&f.config.decision, &trainer))
                    .await,
                Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
                    OwnerError::Pending
                ))
            ));
            assert!(matches!(
                recovered
                    .readback(f.sources(&f.config.decision, &trainer))
                    .await,
                Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
                    OwnerError::Pending
                ))
            ));
        } else {
            let saved = recovered
                .readback(f.sources(&f.config.decision, &trainer))
                .await?;
            assert_eq!(
                recovered
                    .attest_original_selection(f.sources(&f.config.decision, &trainer))
                    .await?,
                saved
            );
        }
        assert_eq!(f.bytes()?, recovered_bytes);
        drop(recovered);
        finish(trainer, peer)?;
        f.original.session.stop().await?;
    }
    Ok(())
}

#[tokio::test]
async fn q24_original_selector_rejects_substituted_custody_before_store_creation()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    for scenario in 0..9 {
        let root = tempfile::tempdir()?;
        let mut config = f.config.clone();
        match scenario {
            0 => {
                config.signer.verifying_key = SigningKey::from_bytes(&[101; 32])
                    .verifying_key()
                    .to_bytes()
            }
            1 => config.signer.roles = vec![LearningEvidenceRoleV1::Generator],
            2 => config.signer.controller_id = StableId::new("substituted-controller")?,
            3 => config.signer.revoked_at = Some(now()?),
            4 => config.maximum_signature_lifetime_seconds = 0,
            5 => config.maximum_signature_lifetime_seconds = 86_401,
            6 => config.decision.owners.selector = StableId::new("substituted-selector")?,
            7 => {
                config.training_evidence.expires_at = now()? - 1;
                config.training_evidence.issued_at = config.training_evidence.expires_at - 1;
                config.training_evidence.signature = SigningKey::from_bytes(&[101; 32])
                    .sign(&config.training_evidence.signing_bytes())
                    .to_bytes();
            }
            8 => {
                let training = config.decision.receipts.pop().context("training fixture")?;
                config.decision.head_digest = training.predecessor;
            }
            _ => unreachable!(),
        }
        let file = opened(root.path(), "journal", true)?;
        let original_witness = witness(root.path(), &f.config, true)?;
        let before_witness = fs::read(root.path().join("witness"))?;
        assert!(
            OriginalCircuitSelectionReceiptOwnerV1::create(
                file,
                original_witness,
                config,
                SigningKey::from_bytes(&[102; 32]),
            )
            .is_err(),
            "scenario {scenario}"
        );
        assert!(
            fs::read(root.path().join("journal"))?.is_empty(),
            "scenario {scenario}"
        );
        assert_eq!(fs::read(root.path().join("witness"))?, before_witness);
    }
    f.original.session.stop().await?;
    Ok(())
}
