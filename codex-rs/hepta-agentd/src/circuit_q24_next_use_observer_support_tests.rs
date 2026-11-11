//! Real ordinary A/C and sealed CURRENT owners, with explicit test-only
//! NoUpdate metadata, credential keys and EvidenceClient transports.
//! This does not run an optimizer or qualify production signer custody, a
//! daemon/Root cold restart, or the full ordinary learning assembly.

use std::fs::File;
use std::os::unix::fs::OpenOptionsExt;

use anyhow::Context;
use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::super::*;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCircuitNextUseReceiptConfigV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitNextUseReceiptSourcesV1;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client;

type Owner = OriginalCircuitNextUseReceiptOwnerV1<FileAnchorWitnessStore>;
type PeerThread = std::thread::JoinHandle<anyhow::Result<()>>;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn now() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs())
}

fn receipt(
    coordinator: &LearningIterationCoordinatorV1,
    observation: LearningIterationObservationV1,
    at: u64,
    evidence: &str,
) -> LearningIterationReceiptV1 {
    let snapshot = coordinator.snapshot();
    LearningIterationReceiptV1 {
        operation_id: snapshot.request.operation_id.clone(),
        predecessor: snapshot.head_digest,
        actor_id: snapshot.owners.owner(observation.stage()).clone(),
        evidence_digest: d(evidence),
        observed_unix_seconds: at,
        observation,
    }
}

fn signed(
    receipt: &LearningIterationReceiptV1,
    verifier: &LearningEvidenceVerifierV1,
    role: LearningEvidenceRoleV1,
    key: &SigningKey,
    evidence_id: &str,
) -> anyhow::Result<SignedLearningEvidenceV1> {
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(evidence_id)?,
        principal_id: receipt.actor_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: d("explicit-observer-trust"),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 1,
        issued_at: receipt.observed_unix_seconds,
        expires_at: receipt.observed_unix_seconds + 600,
        payload_digest: Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(receipt)?),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    Ok(signed)
}

struct Metadata {
    initial: LearningIterationSnapshotV1,
    decision: LearningIterationCoordinatorV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    observer: TrustedLearningSignerV1,
    training: LearningIterationReceiptV1,
    training_signature: SignedLearningEvidenceV1,
}

impl Metadata {
    fn new(request: LearningIterationRequestV1) -> anyhow::Result<Self> {
        let at = now()?;
        let mut owners = LearningIterationOwnersV1 {
            evidence_trust_digest: d("replaced-by-explicit-test-trust"),
            experience: StableId::new("explicit-observer-experience")?,
            dataset: StableId::new("explicit-observer-dataset")?,
            trainer: StableId::new("explicit-observer-generator")?,
            evaluator: StableId::new("explicit-observer-evaluator")?,
            proposal: StableId::new("explicit-observer-proposal")?,
            selector: StableId::new("explicit-observer-selector")?,
            next_use_observer: StableId::new("explicit-observer-next-use")?,
        };
        let mut signers = Vec::new();
        for (index, (actor, role)) in [
            (owners.trainer.clone(), LearningEvidenceRoleV1::Generator),
            (owners.selector.clone(), LearningEvidenceRoleV1::Selector),
            (owners.next_use_observer.clone(), LearningEvidenceRoleV1::Observer),
        ]
        .into_iter()
        .enumerate()
        {
            let key = SigningKey::from_bytes(&[101 + index as u8; 32]);
            signers.push(TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: actor,
                    credential_chain_digest: d(&format!("explicit-observer-credential-{index}")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: d("explicit-observer-trust"),
                    authority_epoch: 1,
                    authenticated_at: at - 60,
                    expires_at: at + 1200,
                },
                controller_id: StableId::new(format!("explicit-observer-controller-{index}"))?,
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            });
        }
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: d("explicit-observer-trust"),
            objective_digest: request.envelope.objective_digest,
            authority_epoch: 1,
            signers: signers.clone(),
        })?;
        owners.evidence_trust_digest = verifier.trust_digest();
        let mut decision = LearningIterationCoordinatorV1::new(request, owners)?;
        let initial = decision.snapshot().clone();
        let rule = d("explicit-observer-no-update-rule-fixture");
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            LearningUpdateScopeV2::Cell,
            rule,
        )?;
        // These three role observations are fixture metadata. Only the source
        // completion below and the subsequent ordinary A/C execution are real.
        for (index, observation) in [
            LearningIterationObservationV1::Experience {
                episode_digest: d("explicit-observer-episode-fixture"),
                completed_task_receipt: initial.request.completed_task_receipt,
            },
            LearningIterationObservationV1::Dataset {
                snapshot_digest: d("explicit-observer-dataset-fixture"),
                episode_digest: d("explicit-observer-episode-fixture"),
                withdrawal_frontier: d("explicit-observer-withdrawal-fixture"),
                rows: 1,
                bytes: 64,
            },
            LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
                retained_bundle: initial.request.selected_bundle.digest()?,
                dataset: d("explicit-observer-dataset-fixture"),
                update_rule: rule,
                steps: 1,
                milliseconds: 1,
                reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
            }),
        ]
        .into_iter()
        .enumerate()
        {
            let observed = receipt(
                &decision,
                observation,
                at,
                &format!("explicit-observer-stage-fixture-{index}"),
            );
            decision.record(observed, at)?;
        }
        let training = decision.snapshot().receipts.last().context("training fixture")?.clone();
        let training_signature = signed(
            &training,
            &verifier,
            LearningEvidenceRoleV1::Generator,
            &SigningKey::from_bytes(&[101; 32]),
            "explicit-original-generator-receipt",
        )?;
        Ok(Self {
            initial,
            decision,
            scope,
            verifier,
            observer: signers[2].clone(),
            training,
            training_signature,
        })
    }
}

pub(super) struct Peers {
    pub(super) trainer: LearningIterationEvidenceClientV1,
    pub(super) selector: LearningIterationEvidenceClientV1,
    trainer_thread: PeerThread,
    selector_thread: PeerThread,
}

impl Peers {
    pub(super) fn finish(self) -> anyhow::Result<()> {
        drop(self.trainer);
        drop(self.selector);
        self.trainer_thread.join().map_err(|_| anyhow::anyhow!("trainer fixture panicked"))??;
        self.selector_thread.join().map_err(|_| anyhow::anyhow!("selector fixture panicked"))??;
        Ok(())
    }
}

pub(super) struct ObserverFixture {
    _model_root: tempfile::TempDir,
    observer_root: tempfile::TempDir,
    pub(super) version: VersionFixture,
    pub(super) session: support::Session,
    pub(super) definition: CellDefinitionV1,
    pub(super) previous: CircuitTaskSourcePublicationV1,
    pub(super) previous_decision: CellDecisionReceiptV1,
    pub(super) config: OriginalCircuitNextUseReceiptConfigV1,
    initial: LearningIterationSnapshotV1,
    training: LearningIterationReceiptV1,
    training_signature: SignedLearningEvidenceV1,
    selection: LearningIterationReceiptV1,
    selection_signature: SignedLearningEvidenceV1,
}

impl ObserverFixture {
    pub(super) async fn ready() -> anyhow::Result<Self> {
        let model_root = tempfile::tempdir()?;
        let (model, bundle, definition) = support::model(model_root.path())?;
        let a = support::admission("observer-original-A").await?;
        let source_a = support::source(&a, [Q, Q / 4])?;
        let config_a = support::configuration(&model, &bundle, &definition, &source_a, 1)?;
        let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
        let published_a = support::publish_initial(&version, definition.clone(), source_a.clone())?;
        let mut a = support::start(a, published_a, Arc::clone(&model), bundle.clone()).await?;
        a.runtime.state.attach_circuit_learning_source(source_a.scope.run_id.clone())?;
        let previous = execute(&a, 1).await?;
        let previous_decision = read_receipt(&a, &definition, &previous)?;
        let intent = a.runtime.state.circuit_task_store()?
            .circuit_learning_delivery(source_a.scope.run_id.as_str())
            .await
            .map_err(|error| anyhow::anyhow!("original A delivery: {error:?}"))?
            .context("ordinary A did not retain its original delivery intent")?
            .intent;
        assert_eq!(previous.history_digest(), &intent.completed_task_receipt);
        let request = LearningIterationRequestV1 {
            operation_id: StableId::new(intent.operation_id)?,
            principal_id: StableId::new(source_a.scope.principal_digest.to_string())?,
            agent_id: source_a.scope.agent_id.clone(),
            cell_id: source_a.scope.cell_id.clone(),
            source_run_id: source_a.scope.run_id.clone(),
            completed_task_receipt: intent.completed_task_receipt.as_str().parse()?,
            selected_artifact_digest: bundle.components.base,
            evaluation_profile: d("explicit-no-update-evaluation-profile"),
            selected_bundle: bundle.clone(),
            envelope: IterationEnvelopeV1 {
                envelope_id: StableId::new("explicit-observer-envelope")?,
                base_commit: d("explicit-observer-source-commit-fixture"),
                base_tree: d("explicit-observer-source-tree-fixture"),
                objective_digest: intent.objective_digest.as_str().parse()?,
                grammar_digest: d("explicit-observer-grammar-fixture"),
                maximum_files: 1,
                maximum_diff_bytes: 128,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: now()? + 900,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 1,
                maximum_dataset_bytes: 128,
                maximum_training_steps: 1,
                maximum_training_milliseconds: 1,
                maximum_artifact_bytes: 128,
            },
        };
        a.runtime.state.require_circuit_learning_source(&request).await?;
        let mut metadata = Metadata::new(request)?;
        let completion_a = a.retirement.drain_completed_task(
            &a.cell, a.source.as_ref(), &a.runtime.identity,
        )?;
        a.stop().await?;
        drop(a);

        let c = support::admission("observer-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        assert_ne!(source_a.scope.run_id, source_c.scope.run_id);
        assert_ne!(source_a.observation, source_c.observation);
        let config_c = support::configuration(&model, &bundle, &definition, &source_c, 2)?;
        let operation = crate::learning_retained_task_operation_id_v1(&metadata.decision)?;
        let prepared = crate::prepare_agentd_generation_cold_same_model_task_v1(
            version.reopen_current()?,
            version.authorities()?,
            AgentdGenerationUpdatePredecessorFilesV1 {
                file: version.file("target-journal")?,
                witness: version.witness("target-witness", &config_a)?,
                config: config_a,
                max_records: RECORDS,
            },
            version.selection()?,
            version.named_target_create("observer-C-journal", "observer-C-witness", config_c)?,
            AgentdGenerationUpdateRequestV1 { operation_id: operation.to_string() },
        )?;
        let final_use = version.sign(prepared.final_use_binding())?;
        let published_c = prepared.publish(&final_use)?.into_circuit_feature_task(
            definition.clone(), source_c, completion_a,
        )?;
        let session = support::start(c, published_c, model, bundle).await?;
        // The learning selection is read from the actual just-published owner.
        // Its separate Selector role signature remains explicit test custody.
        let observed = session.cell.read_learning_selection(&metadata.decision)?;
        let selection = receipt(&metadata.decision, observed, now()?, "explicit-selector-evidence");
        let selection_signature = signed(
            &selection, &metadata.verifier, LearningEvidenceRoleV1::Selector,
            &SigningKey::from_bytes(&[102; 32]), "explicit-original-selector-receipt",
        )?;
        metadata.decision.record(selection.clone(), selection.observed_unix_seconds)?;
        assert_eq!(metadata.decision.next_stage(), Some(LearningIterationStageV1::NextUse));
        let config = OriginalCircuitNextUseReceiptConfigV1 {
            selection: metadata.decision.snapshot().clone(),
            scope: metadata.scope,
            signer: metadata.observer,
            verifier: metadata.verifier,
            training_evidence: metadata.training_signature.clone(),
            selection_evidence: selection_signature.clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        Ok(Self {
            _model_root: model_root,
            observer_root: tempfile::tempdir()?,
            version,
            session,
            definition,
            previous,
            previous_decision,
            config,
            initial: metadata.initial,
            training: metadata.training,
            training_signature: metadata.training_signature,
            selection,
            selection_signature,
        })
    }

    pub(super) fn peers(&self, expected_reads: usize) -> anyhow::Result<Peers> {
        let (trainer, trainer_thread) = fixture_original_receipt_client(
            self.initial.clone(), self.training.clone(), self.config.verifier.clone(),
            self.training_signature.clone(), expected_reads,
        )?;
        let (selector, selector_thread) = fixture_original_receipt_client(
            self.initial.clone(), self.selection.clone(), self.config.verifier.clone(),
            self.selection_signature.clone(), expected_reads,
        )?;
        Ok(Peers { trainer, selector, trainer_thread, selector_thread })
    }

    pub(super) fn sources<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        peers: &'a Peers,
    ) -> OriginalCircuitNextUseReceiptSourcesV1<'a, FileAnchorWitnessStore, FileAnchorWitnessStore> {
        OriginalCircuitNextUseReceiptSourcesV1 {
            snapshot,
            cell: &self.session.cell,
            source: self.session.source.as_ref(),
            identity: &self.session.runtime.identity,
            trainer: &peers.trainer,
            selector: &peers.selector,
        }
    }

    fn file(&self, name: &str, create: bool) -> anyhow::Result<File> {
        let mut options = OpenOptions::new();
        options.read(true).write(true).mode(0o600);
        if create { options.create_new(true); }
        Ok(options.open(self.observer_root.path().join(name))?)
    }

    fn witness(&self, create: bool) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            self.file("observer.witness", create)?,
            JournalScope {
                scope_digest: self.config.scope.binding(),
                objective_digest: self.config.selection.request.envelope.objective_digest,
            },
            Generation::new(1)?,
            16,
        )?)
    }

    pub(super) fn create_owner(&self) -> anyhow::Result<Owner> {
        Ok(OriginalCircuitNextUseReceiptOwnerV1::create(
            self.file("observer.journal", true)?, self.witness(true)?,
            self.config.clone(), SigningKey::from_bytes(&[103; 32]),
        )?)
    }

    pub(super) fn recover_owner(&self) -> anyhow::Result<Owner> {
        Ok(OriginalCircuitNextUseReceiptOwnerV1::recover(
            self.file("observer.journal", false)?, self.witness(false)?,
            self.config.clone(), SigningKey::from_bytes(&[103; 32]),
        )?)
    }

    pub(super) fn bytes(&self) -> anyhow::Result<(Vec<u8>, Vec<u8>)> {
        Ok((
            fs::read(self.observer_root.path().join("observer.journal"))?,
            fs::read(self.observer_root.path().join("observer.witness"))?,
        ))
    }
}

#[path = "circuit_selection_receipt_owner_published_tests.rs"]
mod selection_owner;
