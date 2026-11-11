//! Actual signed ObjectiveStart, native Q24, CURRENT/FinalUse and receipt files.
//! The preceding learning cut, role keys and FileCAS deployment are explicit
//! component fixtures, not an ordinary learning/adoption or independent C claim.

use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use pretty_assertions::assert_eq;

use super::*;
use crate::AgentdQ24CircuitTaskRuntimeV1;
use crate::OriginalCircuitFeatureIngressV1;
use crate::OriginalCircuitFeatureLearningSourcesV1;
use crate::OriginalGenerationLearningReceiptConfigV1;
use crate::OriginalGenerationLearningReceiptOwnerV1;
use crate::OriginalGenerationLearningRoleV1;
use crate::control::AgentdControlServer;

struct FeatureFixture {
    session: support::Session,
    ingress: OriginalCircuitFeatureIngressV1,
    _config: crate::AgentdConfig,
    version: VersionFixture,
    root: tempfile::TempDir,
    coordinator: LearningIterationCoordinatorV1,
    scope: FrozenLearningScopeV2,
    signers: [TrustedLearningSignerV1; 2],
    verifier: LearningEvidenceVerifierV1,
    cancellation: CancellationToken,
    server: tokio::task::JoinHandle<Result<(), crate::AgentdError>>,
}

#[derive(Clone, Copy)]
enum ControlFixture {
    Original,
    DelayedOriginal,
}

impl FeatureFixture {
    async fn new(deadline_offset: u64) -> anyhow::Result<Self> {
        Self::with_control(deadline_offset, ControlFixture::Original).await
    }

    async fn with_control(deadline_offset: u64, control: ControlFixture) -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let (model, bundle, definition) = support::model(root.path())?;
        let a = support::admission("feature-learning-original-A").await?;
        let source_a = support::source(&a, [Q, Q / 4])?;
        let config_a = support::configuration(
            &model,
            &bundle,
            &definition,
            &source_a,
            /*generation*/ 1,
        )?;
        let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
        let published = support::publish_initial(&version, definition.clone(), source_a)?;
        let mut a = support::start(a, published, Arc::clone(&model), bundle.clone()).await?;
        let publication = execute(&a, /*request_id*/ 1).await?;
        let (cut, _) = trained::training_cut(&publication, bundle.clone())?;
        let at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs();
        let signer = |index: usize, role, actor: StableId| TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: actor,
                credential_chain_digest: cell::d("feature-role-fixture-chain"),
                signing_key_digest: codex_hepta_types::Digest32::of_bytes(
                    &SigningKey::from_bytes(&[111 + index as u8; 32])
                        .verifying_key()
                        .to_bytes(),
                ),
                scope_digest: cell::d("feature-role-fixture-scope"),
                authority_epoch: 7,
                authenticated_at: at - 1,
                expires_at: at + 900,
            },
            controller_id: cell::id(&format!("feature-role-fixture-{index}")),
            verifying_key: SigningKey::from_bytes(&[111 + index as u8; 32])
                .verifying_key()
                .to_bytes(),
            roles: vec![role],
            revoked_at: None,
        };
        let signers = [
            signer(
                /*index*/ 0,
                LearningEvidenceRoleV1::Selector,
                cut.owners.selector.clone(),
            ),
            signer(
                /*index*/ 1,
                LearningEvidenceRoleV1::Observer,
                cut.owners.next_use_observer.clone(),
            ),
        ];
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: signers[0].principal.scope_digest,
            objective_digest: cut.request.envelope.objective_digest,
            authority_epoch: 7,
            signers: signers.to_vec(),
        })?;
        let mut request = cut.request;
        request.envelope.expiry_unix_seconds = at + deadline_offset;
        let mut owners = cut.owners;
        owners.evidence_trust_digest = verifier.trust_digest();
        let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
        for mut receipt in cut.receipts {
            receipt.predecessor = coordinator.snapshot().head_digest;
            receipt.observed_unix_seconds = at - 1;
            coordinator.record(receipt, at - 1)?;
        }
        let LearningIterationObservationV1::Dataset {
            snapshot_digest, ..
        } = &coordinator.snapshot().receipts[1].observation
        else {
            anyhow::bail!("fixture Dataset cut");
        };
        let observation =
            LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
                retained_bundle: bundle.digest()?,
                dataset: *snapshot_digest,
                update_rule: cell::d("feature-fixture-no-update-rule"),
                steps: 1,
                milliseconds: 1,
                reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
            });
        let receipt = LearningIterationReceiptV1 {
            operation_id: coordinator.snapshot().request.operation_id.clone(),
            actor_id: coordinator.snapshot().owners.trainer.clone(),
            predecessor: coordinator.snapshot().head_digest,
            evidence_digest: cell::d("explicit-fixture-no-update-evidence"),
            observed_unix_seconds: at - 1,
            observation,
        };
        coordinator.record(receipt, at - 1)?;
        let scope = FrozenLearningScopeV2::freeze(
            &coordinator.snapshot().request,
            &coordinator.snapshot().owners,
            LearningUpdateScopeV2::Cell,
            cell::d("feature-fixture-no-update-rule"),
        )?;
        let previous =
            a.retirement
                .drain_completed_task(&a.cell, &a.source, &a.runtime.identity)?;
        a.stop().await?;
        drop(a);
        let c = support::admission("feature-learning-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        let config_c = support::configuration(
            &model,
            &bundle,
            &definition,
            &source_c,
            /*generation*/ 2,
        )?;
        let update = crate::prepare_agentd_generation_cold_same_model_task_v1(
            version.reopen_current()?,
            version.authorities()?,
            AgentdGenerationUpdatePredecessorFilesV1 {
                file: version.file("target-journal")?,
                witness: version.witness("target-witness", &config_a)?,
                config: config_a,
                max_records: RECORDS,
            },
            version.selection()?,
            version.named_target_create("feature-C-journal", "feature-C-witness", config_c)?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: crate::learning_retained_task_operation_id_v1(&coordinator)?
                    .to_string(),
            },
        )?;
        let signed = version.sign(update.final_use_binding())?;
        let published = update
            .publish(&signed)?
            .into_circuit_feature_task(definition, source_c, previous)?;
        let mut session = support::start(c, published, model, bundle).await?;
        let installed = AgentdQ24CircuitTaskRuntimeV1 {
            config: session.take_configuration(),
            source: Arc::clone(&session.source),
            cell: session.cell.clone(),
        };
        let ingress = installed.original_successor_ingress()?;
        let cancellation = CancellationToken::new();
        let server = AgentdControlServer::bind(
            session.runtime.identity.control_socket.clone(),
            Arc::clone(&session.runtime.state),
            cancellation.clone(),
        )
        .await?;
        let server = match control {
            ControlFixture::Original => tokio::spawn(server.run()),
            ControlFixture::DelayedOriginal => {
                tokio::spawn(server.run_delayed_original_circuit_for_test())
            }
        };
        Ok(Self {
            session,
            ingress,
            _config: installed.config,
            version,
            root,
            coordinator,
            scope,
            signers,
            verifier,
            cancellation,
            server,
        })
    }

    async fn observe_original_completion(
        &self,
    ) -> anyhow::Result<OriginalCircuitFeatureLearningSourcesV1> {
        timeout(Duration::from_secs(60), async {
            loop {
                if let Ok(source) = self.ingress.readback() {
                    return source;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .map_err(Into::into)
    }

    fn file(&self, name: &str) -> anyhow::Result<std::fs::File> {
        Ok(OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.root.path().join(name))?)
    }

    fn witness(&self, name: &str) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            self.file(&format!("{name}.witness"))?,
            JournalScope {
                scope_digest: self.scope.binding(),
                objective_digest: self
                    .coordinator
                    .snapshot()
                    .request
                    .envelope
                    .objective_digest,
            },
            Generation::new(/*value*/ 1)?,
            /*max_records*/ 32,
        )?)
    }

    fn config(
        &self,
        role: OriginalGenerationLearningRoleV1,
    ) -> anyhow::Result<OriginalGenerationLearningReceiptConfigV1> {
        let initial = LearningIterationCoordinatorV1::new(
            self.coordinator.snapshot().request.clone(),
            self.coordinator.snapshot().owners.clone(),
        )?;
        let index = if role == OriginalGenerationLearningRoleV1::Selection {
            0
        } else {
            1
        };
        Ok(OriginalGenerationLearningReceiptConfigV1 {
            initial: initial.snapshot().clone(),
            scope: self.scope.clone(),
            role,
            signer: self.signers[index].clone(),
            verifier: self.verifier.clone(),
            maximum_signature_lifetime_seconds: 300,
        })
    }

    async fn finish(mut self) -> anyhow::Result<()> {
        self.cancellation.cancel();
        self.server.await??;
        self.session.stop().await
    }
}

#[tokio::test]
async fn feature_receipts_require_actual_ordinary_c_and_reopen_original_bytes() -> anyhow::Result<()>
{
    let mut f = FeatureFixture::new(/*deadline_offset*/ 300).await?;
    assert!(f.ingress.readback().is_err());
    let mut wrong = f.session.request.clone();
    wrong.body.run_id.push_str("-wrong");
    assert!(f.ingress.submit(wrong).await.is_err());
    assert!(f.ingress.readback().is_err());
    let source = f.ingress.submit(f.session.request.clone()).await?;
    let _next_dataset_task = source.original_dataset_task()?;
    let source_bytes = owner_bytes(&f.session)?;
    let mut selector = OriginalGenerationLearningReceiptOwnerV1::create_feature(
        f.file("selector")?,
        f.witness("selector")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        source.clone(),
    )?;
    assert!(selector.readback(f.coordinator.snapshot()).await.is_err());
    let selection = selector
        .attest_original_completion(f.coordinator.snapshot())
        .await?;
    f.coordinator
        .record(selection.0.clone(), selection.0.observed_unix_seconds)?;
    let mut observer = OriginalGenerationLearningReceiptOwnerV1::create_feature(
        f.file("observer")?,
        f.witness("observer")?,
        f.config(OriginalGenerationLearningRoleV1::NextUse)?,
        SigningKey::from_bytes(&[112; 32]),
        source.clone(),
    )?;
    let used = observer
        .attest_original_completion(f.coordinator.snapshot())
        .await?;
    assert!(matches!(
        used.0.observation,
        LearningIterationObservationV1::RetainedModelNextUse { .. }
    ));
    f.coordinator
        .record(used.0.clone(), used.0.observed_unix_seconds)?;
    assert_eq!(f.coordinator.next_stage(), None);
    let original = (
        fs::read(f.root.path().join("selector"))?,
        fs::read(f.root.path().join("observer"))?,
        f.version.bytes("final-use/authority.claims")?,
    );
    drop(selector);
    drop(observer);
    let mut selector = OriginalGenerationLearningReceiptOwnerV1::recover_feature(
        f.file("selector")?,
        f.witness("selector")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        source.clone(),
    )?;
    let mut observer = OriginalGenerationLearningReceiptOwnerV1::recover_feature(
        f.file("observer")?,
        f.witness("observer")?,
        f.config(OriginalGenerationLearningRoleV1::NextUse)?,
        SigningKey::from_bytes(&[112; 32]),
        source,
    )?;
    assert_eq!(
        selector.readback(f.coordinator.snapshot()).await?,
        selection
    );
    assert_eq!(observer.readback(f.coordinator.snapshot()).await?, used);
    assert_eq!(
        observer
            .attest_original_completion(f.coordinator.snapshot())
            .await?,
        used
    );
    assert_eq!(
        original,
        (
            fs::read(f.root.path().join("selector"))?,
            fs::read(f.root.path().join("observer"))?,
            f.version.bytes("final-use/authority.claims")?
        )
    );
    assert_eq!(owner_bytes(&f.session)?, source_bytes);
    f.finish().await
}

#[tokio::test]
async fn feature_receipts_reject_source_withdrawal_and_receipt_rollback() -> anyhow::Result<()> {
    let f = FeatureFixture::new(/*deadline_offset*/ 300).await?;
    let source = f.ingress.submit(f.session.request.clone()).await?;
    let mut selector = OriginalGenerationLearningReceiptOwnerV1::create_feature(
        f.file("selector")?,
        f.witness("selector")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        source.clone(),
    )?;
    let genesis = fs::read(f.root.path().join("selector"))?;
    let signed = selector
        .attest_original_completion(f.coordinator.snapshot())
        .await?;
    assert_eq!(selector.readback(f.coordinator.snapshot()).await?, signed);
    drop(selector);
    fs::write(f.root.path().join("selector"), genesis)?;
    assert!(
        OriginalGenerationLearningReceiptOwnerV1::recover_feature(
            f.file("selector")?,
            f.witness("selector")?,
            f.config(OriginalGenerationLearningRoleV1::Selection)?,
            SigningKey::from_bytes(&[111; 32]),
            source.clone(),
        )
        .is_err()
    );
    let mut live = OriginalGenerationLearningReceiptOwnerV1::create_feature(
        f.file("live")?,
        f.witness("live")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        source.clone(),
    )?;
    live.attest_original_completion(f.coordinator.snapshot())
        .await?;
    let before = fs::read(f.root.path().join("live"))?;
    f.session
        .source
        .withdraw_for_dataset_test(&StableId::new(&f.session.request.body.run_id)?)?;
    assert!(f.ingress.readback().is_err());
    assert!(source.original_dataset_task().is_err());
    assert!(live.readback(f.coordinator.snapshot()).await.is_err());
    assert!(
        live.attest_original_completion(f.coordinator.snapshot())
            .await
            .is_err()
    );
    assert_eq!(fs::read(f.root.path().join("live"))?, before);
    f.finish().await
}

#[tokio::test]
async fn feature_receipts_reject_wrong_key_role_and_expired_new_claim() -> anyhow::Result<()> {
    let f = FeatureFixture::new(/*deadline_offset*/ 0).await?;
    let source: OriginalCircuitFeatureLearningSourcesV1 =
        f.ingress.submit(f.session.request.clone()).await?;
    assert!(
        OriginalGenerationLearningReceiptOwnerV1::create_feature(
            f.file("wrong")?,
            f.witness("wrong")?,
            f.config(OriginalGenerationLearningRoleV1::Selection)?,
            SigningKey::from_bytes(&[112; 32]),
            source.clone(),
        )
        .is_err()
    );
    assert_eq!(fs::read(f.root.path().join("wrong"))?, Vec::<u8>::new());
    let mut config = f.config(OriginalGenerationLearningRoleV1::NextUse)?;
    config.signer = f.signers[0].clone();
    assert!(
        OriginalGenerationLearningReceiptOwnerV1::create_feature(
            f.file("role")?,
            f.witness("role")?,
            config,
            SigningKey::from_bytes(&[111; 32]),
            source.clone(),
        )
        .is_err()
    );
    assert_eq!(fs::read(f.root.path().join("role"))?, Vec::<u8>::new());
    let mut expired = OriginalGenerationLearningReceiptOwnerV1::create_feature(
        f.file("expired")?,
        f.witness("expired")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        source,
    )?;
    let before = (
        fs::read(f.root.path().join("expired"))?,
        fs::read(f.root.path().join("expired.witness"))?,
    );
    assert!(
        expired
            .attest_original_completion(f.coordinator.snapshot())
            .await
            .is_err()
    );
    assert_eq!(
        before,
        (
            fs::read(f.root.path().join("expired"))?,
            fs::read(f.root.path().join("expired.witness"))?
        )
    );
    f.finish().await
}

#[path = "circuit_feature_control_completion_tests.rs"]
mod control_completion;
