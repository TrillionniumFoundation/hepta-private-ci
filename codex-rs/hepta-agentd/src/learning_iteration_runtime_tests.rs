//! Source-composition tests using the existing native owner/signing fixtures.
//! The trainer is a deterministic test port, not trained-model evidence.

use std::fmt::Debug;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use pretty_assertions::assert_eq;

use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationProposalPayloadV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::PreparedLearningIterationProposalV1;
use crate::learning_iteration_channel_v1;

use super::*;

fn ok<T, E: Debug>(result: Result<T, E>) -> T {
    match result { Ok(value) => value, Err(error) => panic!("fixture: {error:?}") }
}

struct IterationPorts {
    signing: SigningFixture,
    verifier: LearningEvidenceVerifierV1,
    proposal: Option<ParameterPlasticityProductRequestV1>,
    evaluation: LearningEvaluationDispositionV1,
    checkpoint: Mutex<Option<LearningIterationSnapshotV1>>,
    executed: Mutex<Vec<LearningIterationStageV1>>,
    lose_ack_once: AtomicBool,
    corrupt_signature: AtomicBool,
}
impl IterationPorts {
    fn owners(&self) -> LearningIterationOwnersV1 {
        LearningIterationOwnersV1 {
            evidence_trust_digest: self.verifier.trust_digest(),
            experience: self.signing.principals[1].principal_id.clone(),
            dataset: self.signing.principals[1].principal_id.clone(),
            trainer: self.signing.principals[0].principal_id.clone(),
            evaluator: self.signing.principals[2].principal_id.clone(),
            proposal: id("owner:anchored-proposal"), selector: id("owner:external-selector"),
            next_use_observer: self.signing.principals[1].principal_id.clone(),
        }
    }
    fn new(proposal: Option<ParameterPlasticityProductRequestV1>, evaluation: LearningEvaluationDispositionV1) -> Self {
        let signing = SigningFixture::new();
        let verifier = signing.verifier(digest("plasticity-objective"));
        Self { signing, verifier, proposal, evaluation, checkpoint: Mutex::new(None),
            executed: Mutex::new(Vec::new()), lose_ack_once: AtomicBool::new(false), corrupt_signature: AtomicBool::new(false) }
    }
}

impl LearningIterationOwnerPortsV1 for IterationPorts {
    fn restore<'a>(&'a self, _request: &'a LearningIterationRequestV1) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move { Ok(ok(self.checkpoint.lock()).clone()) })
    }
    fn checkpoint<'a>(&'a self, expected: Digest32, snapshot: &'a LearningIterationSnapshotV1) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        Box::pin(async move {
            let mut current = ok(self.checkpoint.lock());
            if current.as_ref().map_or(Digest32::ZERO, |value| value.head_digest) != expected {
                return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
            }
            *current = Some(snapshot.clone());
            if snapshot.receipts.len() == 5 && self.lose_ack_once.swap(false, Ordering::SeqCst) {
                return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
            }
            Ok(snapshot.head_digest)
        })
    }
    fn execute_stage<'a>(&'a self, snapshot: &'a LearningIterationSnapshotV1, stage: LearningIterationStageV1) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            ok(self.executed.lock()).push(stage);
            let dataset = self.proposal.as_ref().map_or(digest("test-dataset"), |proposal| proposal.admission.dataset_digest);
            let update_rule = self.proposal.as_ref().map_or(digest("test-rule"), |proposal| proposal.admission.update_rule_digest);
            let mut candidate = snapshot.request.selected_bundle.clone();
            candidate.artifact_id = id("artifact:trained-test");
            candidate.generation = ok(candidate.generation.next());
            candidate.components.cell_adapter = Some(digest("trained-test-adapter"));
            let source_bundle = ok(snapshot.request.selected_bundle.digest());
            candidate.rollback_predecessor = Some(source_bundle);
            candidate.training_lineage = Some(CellTrainingLineageV1 {
                source_bundle, dataset, update_rule, evaluation_profile: digest("frozen-evaluation"),
            });
            let candidate_bundle = ok(candidate.digest());
            let observation = match stage {
                LearningIterationStageV1::Experience => LearningIterationObservationV1::Experience {
                    episode_digest: digest("completed-episode"), completed_task_receipt: snapshot.request.completed_task_receipt,
                },
                LearningIterationStageV1::Dataset => LearningIterationObservationV1::Dataset {
                    snapshot_digest: dataset, episode_digest: digest("completed-episode"),
                    withdrawal_frontier: digest("withdrawals"), rows: 1, bytes: 64,
                },
                LearningIterationStageV1::Training => LearningIterationObservationV1::Training {
                    candidate, steps: 1, milliseconds: 1, artifact_bytes: 64,
                },
                LearningIterationStageV1::Evaluation => LearningIterationObservationV1::Evaluation {
                    candidate_bundle, evaluation_profile: digest("frozen-evaluation"), disposition: self.evaluation,
                },
                LearningIterationStageV1::Proposal | LearningIterationStageV1::Selection | LearningIterationStageV1::NextUse =>
                    return Err(LearningIterationRuntimeErrorV1::OwnerUnavailable("unexpected downstream stage")),
            };
            Ok(LearningIterationReceiptV1 {
                operation_id: snapshot.request.operation_id.clone(), predecessor: snapshot.head_digest,
                actor_id: snapshot.owners.owner(stage).clone(), evidence_digest: digest(&format!("owner-evidence:{stage:?}")),
                observed_unix_seconds: 50, observation,
            })
        })
    }
    fn prepare_proposal<'a>(&'a self, snapshot: &'a LearningIterationSnapshotV1) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async move {
            let coordinator = ok(LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()));
            let Some(candidate) = coordinator.candidate() else { panic!("candidate missing"); };
            let Some(proposal) = self.proposal.clone() else { return Err(LearningIterationRuntimeErrorV1::OwnerUnavailable("proposal")); };
            Ok(PreparedLearningIterationProposalV1 {
                iteration_head: snapshot.head_digest, candidate_bundle: ok(candidate.digest()),
                evaluation_evidence: snapshot.receipts[3].evidence_digest,
                payload: LearningIterationProposalPayloadV1::Parameter(Box::new(proposal)),
            })
        })
    }
    fn receipt_attestation<'a>(&'a self, snapshot: &'a LearningIterationSnapshotV1, receipt: &'a LearningIterationReceiptV1, _now: u64) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            let (signer, role) = match receipt.observation.stage() {
                LearningIterationStageV1::Training => (0, LearningEvidenceRoleV1::Generator),
                LearningIterationStageV1::Evaluation => (2, LearningEvidenceRoleV1::Evaluator),
                _ => (1, LearningEvidenceRoleV1::Observer),
            };
            let mut signed = self.signing.sign(&self.verifier, snapshot.request.envelope.objective_digest,
                signer, role, &ok(learning_iteration_receipt_signing_bytes_v1(receipt)));
            if self.corrupt_signature.load(Ordering::SeqCst) { signed.signature[0] ^= 1; }
            Ok(signed)
        })
    }
}

fn iteration_request(daemon: &AgentdFixture) -> LearningIterationRequestV1 {
    LearningIterationRequestV1 {
        operation_id: id("proposal:agentd-lifetime"), principal_id: id("principal:task-owner"),
        agent_id: id(&daemon.identity.agent_id.to_string()), cell_id: id("cell:one"), source_run_id: id("run:source"),
        completed_task_receipt: digest("completed-task"), selected_artifact_digest: digest("selected-artifact:lifetime"),
        selected_bundle: CellCompatibilityBundleV1 {
            artifact_id: id("artifact:baseline"), generation: generation(1),
            components: CellBundleComponentsV1 {
                base: digest("selected-artifact:lifetime"), organ_adapter: None, cell_adapter: None,
                heads: digest("heads"), composition: digest("composition"), encoder: digest("encoder"),
                tokenizer: digest("tokenizer"), normalizer: digest("normalizer"), calibration: digest("calibration"),
                numeric_profile: digest("numeric"), output_schema: digest("output"), state_schema: digest("state"), state_semantics: digest("semantics"),
            }, training_lineage: None, rollback_predecessor: None,
        },
        envelope: IterationEnvelopeV1 {
            envelope_id: id("window:lifetime"), base_commit: digest("commit"), base_tree: digest("tree"),
            objective_digest: digest("plasticity-objective"), grammar_digest: digest("mutation-grammar:lifetime"),
            maximum_files: 1, maximum_diff_bytes: 128, maximum_candidates: 1, maximum_parallel_sandboxes: 1, expiry_unix_seconds: 90,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 16, maximum_dataset_bytes: 1024, maximum_training_steps: 2,
            maximum_training_milliseconds: 1000, maximum_artifact_bytes: 128,
        },
    }
}

#[tokio::test]
async fn coordinator_uses_native_proposal_owner_and_reconciles_lost_ack() {
    let daemon = AgentdFixture::new();
    let root = ok(tempfile::tempdir());
    let files = runtime_files(root.path());
    let mut ledger = ok(DurableLedger::create(new_file(&files.ledger), digest("iteration-ledger"), 32));
    ok(ledger.append_qualification(Digest32::ZERO, ledger_decision(digest("plasticity-objective"))));
    let sources = build_owner_sources(root.path(), &ledger, digest("plasticity-objective"), digest("selected-artifact:lifetime"));
    let signing = SigningFixture::new();
    let verifier = signing.verifier(sources.objective_digest);
    let proposal = signed_request(&sources, &ledger, &signing, &verifier);
    let (writer, anchor) = ok(bootstrap_agentd_plasticity_writer_v1(new_file(&files.parameter_registry), new_file(&files.parameter_anchor), digest("parameter-scope"), 32));
    let (topology, topology_anchor) = ok(bootstrap_agentd_topology_writer_v1(new_file(&files.topology_registry), new_file(&files.topology_anchor), digest("topology-scope"), 32));
    let bootstrap = ok(PlasticityRuntimeBootstrapV1::new(8, sources.artifacts.clone(), ledger,
        Box::new(resolver(&sources)), sources.owner_policy.clone(), verifier, writer, anchor, topology, topology_anchor));
    let state = daemon.state();
    let owner = ok(crate::plasticity_runtime::compose_plasticity_runtime_v1(&state, Some(bootstrap)));
    let cancellation = CancellationToken::new();
    let task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(Arc::clone(&state), owner, cancellation.clone());
    let ports = Arc::new(IterationPorts::new(Some(proposal.clone()), LearningEvaluationDispositionV1::Qualified));
    ports.lose_ack_once.store(true, Ordering::SeqCst);
    let (_, iteration) = ok(learning_iteration_channel_v1(daemon.identity.agent_id.clone(), 1,
        ports.owners(), ports.clone(), ports.verifier.clone(), 2));
    let request = iteration_request(&daemon);
    assert!(matches!(iteration.process(&state, request.clone(), || Ok(50)).await, Err(LearningIterationRuntimeErrorV1::CommitUncertain)));
    let finished = ok(iteration.process(&state, request, || Ok(50)).await);
    assert_eq!(ok(LearningIterationCoordinatorV1::from_snapshot(finished)).disposition(), LearningIterationDispositionV1::NoUpdate);
    assert_eq!(ok(ports.executed.lock()).clone(), vec![LearningIterationStageV1::Experience,
        LearningIterationStageV1::Dataset, LearningIterationStageV1::Training, LearningIterationStageV1::Evaluation]);
    let replay = ok(state.submit_parameter_plasticity_v1(proposal, 50).await);
    assert_eq!(replay.registry.sequence, 1);
    assert_eq!(replay.registry.disposition, AppendDisposition::Unchanged);
    cancellation.cancel();
    ok(ok(task.await));
}

#[tokio::test]
async fn invalid_signature_prevents_dataset_training_and_checkpoint_progress() {
    let daemon = AgentdFixture::new();
    let state = daemon.state();
    let ports = Arc::new(IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate));
    ports.corrupt_signature.store(true, Ordering::SeqCst);
    let (_, owner) = ok(learning_iteration_channel_v1(daemon.identity.agent_id.clone(), 1,
        ports.owners(), ports.clone(), ports.verifier.clone(), 2));
    assert!(matches!(owner.process(&state, iteration_request(&daemon), || Ok(50)).await,
        Err(LearningIterationRuntimeErrorV1::Evidence(SignedEvidenceError::InvalidSignature))));
    assert_eq!(ok(ports.executed.lock()).clone(), vec![LearningIterationStageV1::Experience]);
    assert_eq!(ok(ports.checkpoint.lock()).as_ref().map(|snapshot| snapshot.receipts.len()), Some(0));
}

#[tokio::test]
async fn terminal_rejection_replays_after_expiry_without_retraining() {
    let daemon = AgentdFixture::new();
    let state = daemon.state();
    let ports = Arc::new(IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate));
    let (_, owner) = ok(learning_iteration_channel_v1(daemon.identity.agent_id.clone(), 1,
        ports.owners(), ports.clone(), ports.verifier.clone(), 2));
    let request = iteration_request(&daemon);
    let first = ok(owner.process(&state, request.clone(), || Ok(50)).await);
    let replay = ok(owner.process(&state, request, || Ok(100)).await);
    assert_eq!(replay, first);
    assert_eq!(ok(ports.executed.lock()).len(), 4);
}

#[tokio::test]
async fn scope_and_generation_readiness_refuse_before_owner_work() {
    let daemon = AgentdFixture::new();
    let ports = Arc::new(IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate));
    let (_, owner) = ok(learning_iteration_channel_v1(daemon.identity.agent_id.clone(), 1,
        ports.owners(), ports.clone(), ports.verifier.clone(), 2));
    let state = daemon.state();
    let mut wrong = iteration_request(&daemon);
    wrong.agent_id = id("agent:other");
    assert!(matches!(owner.process(&state, wrong, || Ok(50)).await, Err(LearningIterationRuntimeErrorV1::WrongScope)));
    let other = AgentdFixture::new();
    let not_ready = ok(AgentdState::new(other.identity.clone(), other.registry.clone(), 16));
    assert!(matches!(owner.process(&not_ready, iteration_request(&daemon), || Ok(50)).await, Err(LearningIterationRuntimeErrorV1::Unavailable)));
    assert_eq!(ok(ports.executed.lock()).len(), 0);
    assert!(ok(ports.checkpoint.lock()).is_none());
}

#[tokio::test]
async fn separate_keys_under_one_controller_cannot_self_evaluate() {
    let daemon = AgentdFixture::new();
    let state = daemon.state();
    let mut ports = IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate);
    ports.verifier = ok(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("plasticity-scope"), objective_digest: digest("plasticity-objective"), authority_epoch: 7,
        signers: ports.signing.principals.iter().zip(&ports.signing.keys).enumerate().map(|(index, (principal, key))| TrustedLearningSignerV1 {
            principal: principal.clone(), controller_id: id("one-controller"), verifying_key: key.verifying_key().to_bytes(),
            roles: vec![match index { 0 => LearningEvidenceRoleV1::Generator, 1 => LearningEvidenceRoleV1::Observer, _ => LearningEvidenceRoleV1::Evaluator }],
            revoked_at: None,
        }).collect(),
    }));
    let ports = Arc::new(ports);
    let (_, owner) = ok(learning_iteration_channel_v1(daemon.identity.agent_id.clone(), 1,
        ports.owners(), ports.clone(), ports.verifier.clone(), 2));
    assert!(matches!(owner.process(&state, iteration_request(&daemon), || Ok(50)).await,
        Err(LearningIterationRuntimeErrorV1::Evidence(SignedEvidenceError::ControllerCollision))));
    assert_eq!(ok(ports.checkpoint.lock()).as_ref().map(|snapshot| snapshot.receipts.len()), Some(3));
}
