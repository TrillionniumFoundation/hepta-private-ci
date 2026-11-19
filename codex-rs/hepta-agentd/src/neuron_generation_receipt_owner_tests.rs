//! Real CURRENT, consumed FinalUse, actor and receipt journals with explicit
//! synthetic learning history, worker and credential fixtures. Ordinary task
//! learning, independent custody and deployment acceptance remain unclaimed.

use std::fs::OpenOptions;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalGenerationLearningReceiptConfigV1;
use crate::OriginalGenerationLearningReceiptOwnerV1;
use crate::OriginalGenerationLearningReceiptSourcesV1;
use crate::OriginalGenerationLearningRoleV1;

struct ReceiptRuntime {
    host: host::Fixture,
    publication: Fixture,
    coordinator: LearningIterationCoordinatorV1,
    runtime: AgentdGenerationUpdateRuntimeV1,
    root: tempfile::TempDir,
    scope: FrozenLearningScopeV2,
    signers: [TrustedLearningSignerV1; 2],
    verifier: LearningEvidenceVerifierV1,
}

fn now() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs())
}

impl ReceiptRuntime {
    async fn new(deadline_offset: u64) -> anyhow::Result<Self> {
        let mut host = host::Fixture::new().await;
        let baseline = learning_test_baseline()?;
        host.config.manifest.bundle_digest = baseline.digest()?.into_array();
        host.config.initial.manifest_digest = host.config.manifest.digest()?;
        let mut next = host.config.clone();
        next.initial.scope.run_id.push_str("-original-receipt-next");
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.task_digest = Digest32::of_bytes(b"original receipt next task fixture").into_array();
        let publication = Fixture::new_with_target(host.config.clone(), next)?;
        let prior = learning_test_decision(&publication, baseline, "none")?;
        let at = now()?;
        let signer =
            |index: usize, role, actor: StableId| -> anyhow::Result<TrustedLearningSignerV1> {
                let key = SigningKey::from_bytes(&[111 + index as u8; 32]);
                Ok(TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: actor,
                        credential_chain_digest: Digest32::of_bytes(
                            b"explicit-generation-credential-fixture",
                        ),
                        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                        scope_digest: Digest32::of_bytes(b"explicit-generation-trust-fixture"),
                        authority_epoch: 7,
                        authenticated_at: at - 1,
                        expires_at: at + 900,
                    },
                    controller_id: StableId::new(format!("generation-receipt-fixture-{index}"))?,
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![role],
                    revoked_at: None,
                })
            };
        let signers = [
            signer(
                /*index*/ 0,
                LearningEvidenceRoleV1::Selector,
                prior.snapshot().owners.selector.clone(),
            )?,
            signer(
                /*index*/ 1,
                LearningEvidenceRoleV1::Observer,
                prior.snapshot().owners.next_use_observer.clone(),
            )?,
        ];
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: signers[0].principal.scope_digest,
            objective_digest: prior.snapshot().request.envelope.objective_digest,
            authority_epoch: 7,
            signers: signers.to_vec(),
        })?;
        let mut request = prior.snapshot().request.clone();
        request.envelope.expiry_unix_seconds = at + deadline_offset;
        let mut owners = prior.snapshot().owners.clone();
        owners.evidence_trust_digest = verifier.trust_digest();
        let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
        for retained in &prior.snapshot().receipts {
            let mut retained = retained.clone();
            retained.predecessor = coordinator.snapshot().head_digest;
            retained.observed_unix_seconds = at - 1;
            coordinator.record(retained, at - 1)?;
        }
        let scope = FrozenLearningScopeV2::freeze(
            &coordinator.snapshot().request,
            &coordinator.snapshot().owners,
            LearningUpdateScopeV2::Cell,
            Digest32::of_bytes(b"update"),
        )?;
        scope.validate_snapshot(coordinator.snapshot())?;
        let prepared = prepare_agentd_generation_same_model_task_v1(
            publication.current.clone(),
            publication.authorities()?,
            publication.stopped_old()?,
            publication.selection()?,
            publication.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: learning_retained_task_operation_id_v1(&coordinator)?.to_string(),
            },
        )?;
        let grant = publication.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&grant)?;
        let runtime = ready.into_runtime(
            support::next_config(&mut host, /*spawn_generation*/ 2).await?,
            support::Control::default(),
            host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        Ok(Self {
            host,
            publication,
            coordinator,
            runtime,
            root: tempfile::tempdir()?,
            scope,
            signers,
            verifier,
        })
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
        let index = if role == OriginalGenerationLearningRoleV1::Selection {
            0
        } else {
            1
        };
        let initial = LearningIterationCoordinatorV1::new(
            self.coordinator.snapshot().request.clone(),
            self.coordinator.snapshot().owners.clone(),
        )?;
        Ok(OriginalGenerationLearningReceiptConfigV1 {
            initial: initial.snapshot().clone(),
            scope: self.scope.clone(),
            role,
            signer: self.signers[index].clone(),
            verifier: self.verifier.clone(),
            maximum_signature_lifetime_seconds: 300,
        })
    }

    fn source(
        &self,
        next_use: Option<codex_hepta_neuron::CellGenerationIntentV2>,
    ) -> OriginalGenerationLearningReceiptSourcesV1 {
        OriginalGenerationLearningReceiptSourcesV1 {
            runtime: self.runtime.handle.clone(),
            baseline: self.publication.old_config.manifest.clone(),
            next_use,
        }
    }
}

#[tokio::test]
async fn original_generation_receipts_require_committed_work_and_reopen_exact_bytes()
-> anyhow::Result<()> {
    let mut f = ReceiptRuntime::new(/*deadline_offset*/ 300).await?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    let mut selector = OriginalGenerationLearningReceiptOwnerV1::create(
        f.file("selector")?,
        f.witness("selector")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        f.source(/*next_use*/ None),
    )?;
    let empty = std::fs::read(f.root.path().join("selector"))?;
    assert!(selector.readback(f.coordinator.snapshot()).await.is_err());
    assert_eq!(std::fs::read(f.root.path().join("selector"))?, empty);
    let selection = selector
        .attest_original_completion(f.coordinator.snapshot())
        .await?;
    assert_eq!(
        selector
            .attest_original_completion(f.coordinator.snapshot())
            .await?,
        selection
    );
    f.coordinator
        .record(selection.0.clone(), selection.0.observed_unix_seconds)?;
    let request = support::request(
        &f.publication.target_config,
        f.runtime.handle.snapshot().await?,
    );
    let intent = request.intent()?;
    let mut observer = OriginalGenerationLearningReceiptOwnerV1::create(
        f.file("observer")?,
        f.witness("observer")?,
        f.config(OriginalGenerationLearningRoleV1::NextUse)?,
        SigningKey::from_bytes(&[112; 32]),
        f.source(Some(intent.clone())),
    )?;
    let uncommitted = std::fs::read(f.root.path().join("observer"))?;
    assert!(
        observer
            .attest_original_completion(f.coordinator.snapshot())
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(f.root.path().join("observer"))?, uncommitted);
    f.runtime.handle.step(request).await?;
    let observation = f.runtime.handle.observe_generation().await?;
    let chunk = observation
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("fixture pending output"))?;
    f.runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_bytes(&chunk.bytes).into_array(),
            CellTaskCostV2::new(observation.cost().identity())?,
        )
        .await?;
    assert!(f.runtime.handle.drain().await?);
    let used = observer
        .attest_original_completion(f.coordinator.snapshot())
        .await?;
    f.coordinator
        .record(used.0.clone(), used.0.observed_unix_seconds)?;
    assert_eq!(f.coordinator.next_stage(), None);
    let original = (
        std::fs::read(f.root.path().join("selector"))?,
        std::fs::read(f.root.path().join("observer"))?,
        f.publication.bytes("final-use/authority.claims")?,
    );
    drop(selector);
    drop(observer);
    let mut selector = OriginalGenerationLearningReceiptOwnerV1::recover(
        f.file("selector")?,
        f.witness("selector")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        f.source(/*next_use*/ None),
    )?;
    let mut observer = OriginalGenerationLearningReceiptOwnerV1::recover(
        f.file("observer")?,
        f.witness("observer")?,
        f.config(OriginalGenerationLearningRoleV1::NextUse)?,
        SigningKey::from_bytes(&[112; 32]),
        f.source(Some(intent)),
    )?;
    assert_eq!(
        selector.readback(f.coordinator.snapshot()).await?,
        selection
    );
    assert_eq!(observer.readback(f.coordinator.snapshot()).await?, used);
    assert_eq!(
        original,
        (
            std::fs::read(f.root.path().join("selector"))?,
            std::fs::read(f.root.path().join("observer"))?,
            f.publication.bytes("final-use/authority.claims")?
        )
    );
    f.publication.withdraw()?;
    assert!(selector.readback(f.coordinator.snapshot()).await.is_err());
    assert!(observer.readback(f.coordinator.snapshot()).await.is_err());
    assert_eq!(std::fs::read(f.root.path().join("observer"))?, original.1);
    tasks.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn original_generation_receipt_rejects_known_expiry_before_claim() -> anyhow::Result<()> {
    let mut f = ReceiptRuntime::new(/*deadline_offset*/ 0).await?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    let mut owner = OriginalGenerationLearningReceiptOwnerV1::create(
        f.file("expired")?,
        f.witness("expired")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        f.source(/*next_use*/ None),
    )?;
    let before = (
        std::fs::read(f.root.path().join("expired"))?,
        std::fs::read(f.root.path().join("expired.witness"))?,
    );
    assert!(
        owner
            .attest_original_completion(f.coordinator.snapshot())
            .await
            .is_err()
    );
    assert_eq!(
        before,
        (
            std::fs::read(f.root.path().join("expired"))?,
            std::fs::read(f.root.path().join("expired.witness"))?
        )
    );
    tasks.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn original_generation_receipt_rejects_rollback_and_foreign_intent() -> anyhow::Result<()> {
    let mut f = ReceiptRuntime::new(/*deadline_offset*/ 300).await?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    let mut owner = OriginalGenerationLearningReceiptOwnerV1::create(
        f.file("rollback")?,
        f.witness("rollback")?,
        f.config(OriginalGenerationLearningRoleV1::Selection)?,
        SigningKey::from_bytes(&[111; 32]),
        f.source(/*next_use*/ None),
    )?;
    let initial = std::fs::read(f.root.path().join("rollback"))?;
    let selection = owner
        .attest_original_completion(f.coordinator.snapshot())
        .await?;
    f.coordinator
        .record(selection.0.clone(), selection.0.observed_unix_seconds)?;
    drop(owner);
    std::fs::write(f.root.path().join("rollback"), initial)?;
    assert!(
        OriginalGenerationLearningReceiptOwnerV1::recover(
            f.file("rollback")?,
            f.witness("rollback")?,
            f.config(OriginalGenerationLearningRoleV1::Selection)?,
            SigningKey::from_bytes(&[111; 32]),
            f.source(/*next_use*/ None),
        )
        .is_err()
    );
    let request = support::request(
        &f.publication.target_config,
        f.runtime.handle.snapshot().await?,
    );
    let mut intent = request.intent()?;
    f.runtime.handle.step(request).await?;
    intent.operation_id.push_str("-uncommitted");
    let mut observer = OriginalGenerationLearningReceiptOwnerV1::create(
        f.file("foreign")?,
        f.witness("foreign")?,
        f.config(OriginalGenerationLearningRoleV1::NextUse)?,
        SigningKey::from_bytes(&[112; 32]),
        f.source(Some(intent)),
    )?;
    let before = std::fs::read(f.root.path().join("foreign"))?;
    assert!(
        observer
            .attest_original_completion(f.coordinator.snapshot())
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(f.root.path().join("foreign"))?, before);
    tasks.shutdown().await;
    Ok(())
}
