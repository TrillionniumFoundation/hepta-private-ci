//! Signed metadata for Root authentication and wire mechanism tests only.
//! No opaque S/C command receipt, role owner, publication or C execution is
//! constructed. The protected Root checkpoint must remain vacant throughout.

use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1 as Observation;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1 as Role;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::super::super::authentication;
use super::super::super::runtime::ResidentRuntimeObservationV3;
use super::super::super::transport::ResidentReadbackPinV3;
use super::super::super::wire;
use super::metadata::ResidentMetadata;
use super::metadata::digest;
use super::support::ResidentRootFixture;
use crate::LearningIterationRuntimeErrorV1 as Error;

enum Controllers {
    Independent,
    Shared { left: usize, right: usize },
}

struct Metadata {
    root: ResidentRootFixture,
    verifier: LearningEvidenceVerifierV1,
    cuts: Vec<LearningIterationSnapshotV1>,
    signatures: Vec<SignedLearningEvidenceV1>,
    at: u64,
}

impl Metadata {
    fn new(controllers: Controllers) -> anyhow::Result<Self> {
        let original = ResidentMetadata::new()?;
        let (metadata, signatures) = original.completed_metadata()?;
        let at = signatures[0].issued_at;
        let evidence_scope = original.verifier.scope_digest();
        let mut owners = original.initial.owners.clone();
        let roles = [
            (owners.experience.clone(), Role::Observer),
            (owners.dataset.clone(), Role::Observer),
            (owners.trainer.clone(), Role::Generator),
            (owners.evaluator.clone(), Role::Evaluator),
            (owners.selector.clone(), Role::Selector),
            (owners.next_use_observer.clone(), Role::Observer),
        ];
        let mut signers = Vec::new();
        for (index, (principal_id, role)) in roles.iter().enumerate() {
            let key = SigningKey::from_bytes(&[151 + index as u8; 32]);
            signers.push(TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: principal_id.clone(),
                    credential_chain_digest: digest(&format!("retention-auth-chain-{index}")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: evidence_scope,
                    authority_epoch: 1,
                    authenticated_at: at - 60,
                    expires_at: at + 900,
                },
                controller_id: StableId::new(format!("retention-auth-controller-{index}"))?,
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![*role],
                revoked_at: None,
            });
        }
        if let Controllers::Shared { left, right } = controllers {
            signers[right].controller_id = signers[left].controller_id.clone();
        }
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: evidence_scope,
            objective_digest: original.initial.request.envelope.objective_digest,
            authority_epoch: 1,
            signers,
        })?;
        owners.evidence_trust_digest = verifier.trust_digest();
        let mut coordinator =
            LearningIterationCoordinatorV1::new(original.initial.request.clone(), owners)?;
        let initial = coordinator.snapshot().clone();
        let rule = digest("resident-fixture-frozen-rule");
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            LearningUpdateScopeV2::Cell,
            rule,
        )?;
        let mut candidate = initial.request.selected_bundle.clone();
        candidate.artifact_id = StableId::new("retention-auth-candidate")?;
        candidate.generation = candidate.generation.next()?;
        candidate.components.cell_adapter = Some(digest("retention-auth-changed-cell"));
        candidate.rollback_predecessor = Some(initial.request.selected_bundle.digest()?);
        candidate.training_lineage = Some(CellTrainingLineageV1 {
            source_bundle: initial.request.selected_bundle.digest()?,
            dataset: digest("resident-fixture-dataset"),
            update_rule: rule,
            evaluation_profile: initial.request.evaluation_profile,
        });
        let candidate_digest = candidate.digest()?;
        let mut observations: Vec<_> = metadata
            .receipts
            .into_iter()
            .map(|receipt| receipt.observation)
            .collect();
        observations[2] = Observation::Training {
            candidate: Box::new(candidate),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 1,
        };
        observations.insert(
            3,
            Observation::Evaluation {
                candidate_bundle: candidate_digest,
                evaluation_profile: initial.request.evaluation_profile,
                disposition: LearningEvaluationDispositionV1::NoUpdate,
            },
        );
        let mut cuts = vec![initial.clone()];
        let mut signatures = Vec::new();
        for (index, observation) in observations.into_iter().enumerate() {
            let receipt = LearningIterationReceiptV1 {
                operation_id: initial.request.operation_id.clone(),
                predecessor: coordinator.snapshot().head_digest,
                actor_id: initial.owners.owner(observation.stage()).clone(),
                evidence_digest: digest(&format!("retention-auth-result-{index}")),
                observed_unix_seconds: at,
                observation,
            };
            signatures.push(sign(index, &receipt, roles[index].1, &verifier, at)?);
            coordinator.record(receipt, at)?;
            cuts.push(coordinator.snapshot().clone());
        }
        let root = ResidentRootFixture::new(initial, scope, &verifier)?;
        Ok(Self {
            root,
            verifier,
            cuts,
            signatures,
            at,
        })
    }

    fn verify(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        signatures: &[SignedLearningEvidenceV1],
    ) -> Result<(), Error> {
        authentication::verify_attestations(
            &self.root.profile,
            &self.verifier,
            snapshot,
            signatures,
            self.at,
        )
    }

    fn readback(
        &self,
        count: usize,
        signatures: Vec<SignedLearningEvidenceV1>,
    ) -> anyhow::Result<crate::RootResidentLearningObservationV3> {
        let reply = wire::encode_current(ResidentRuntimeObservationV3 {
            snapshot: Some(self.cuts[count].clone()),
            attestations: signatures,
            dispatch_pending: false,
            model: None,
        })?;
        let encoded = serde_json::to_vec(&reply)?;
        assert!(encoded.len() < wire::BOUND);
        Ok(wire::decode_current(
            serde_json::from_slice(&encoded)?,
            &self.root.profile,
            &self.verifier,
            self.at,
        )?)
    }

    fn require_vacant(&self) -> anyhow::Result<()> {
        let current = self
            .root
            .registration
            .as_ref()
            .expect("protected Root")
            .owner
            .checkpoint
            .read()?;
        assert!(current.snapshot.is_none());
        assert!(!current.dispatch_pending);
        Ok(())
    }
}

fn sign(
    index: usize,
    receipt: &LearningIterationReceiptV1,
    role: Role,
    verifier: &LearningEvidenceVerifierV1,
    at: u64,
) -> anyhow::Result<SignedLearningEvidenceV1> {
    let mut signature = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!("retention-auth-evidence-{index}"))?,
        principal_id: receipt.actor_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 1,
        issued_at: at,
        expires_at: at + 600,
        payload_digest: Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(receipt)?),
        signature: [0; 64],
    };
    signature.signature = SigningKey::from_bytes(&[151 + index as u8; 32])
        .sign(&signature.signing_bytes())
        .to_bytes();
    Ok(signature)
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_retention_auth_roundtrip_keeps_exact_six_stage_prefix() -> anyhow::Result<()> {
    let fixture = Metadata::new(Controllers::Independent)?;
    let mut previous = None;
    for count in 4..=6 {
        fixture.verify(&fixture.cuts[count], &fixture.signatures[..count])?;
        let observed = fixture.readback(count, fixture.signatures[..count].to_vec())?;
        assert_eq!(observed.snapshot(), Some(&fixture.cuts[count]));
        assert_eq!(observed.attestations(), &fixture.signatures[..count]);
        assert!(observed.original_model_record().is_none());
        wire::require_original_prefix(&previous, &observed)?;
        previous = Some(ResidentReadbackPinV3 {
            snapshot: fixture.cuts[count].clone(),
            attestations: fixture.signatures[..count].to_vec(),
            model: None,
        });
    }
    let rollback = fixture.readback(/*count*/ 4, fixture.signatures[..4].to_vec())?;
    assert!(matches!(
        wire::require_original_prefix(&previous, &rollback),
        Err(Error::CommitUncertain)
    ));
    fixture.require_vacant()
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_retention_auth_refuses_changed_order_bundle_role_and_window() -> anyhow::Result<()>
{
    let fixture = Metadata::new(Controllers::Independent)?;
    for index in 0..6 {
        let mut missing = fixture.signatures.clone();
        missing.remove(index);
        assert!(matches!(
            fixture.verify(&fixture.cuts[6], &missing),
            Err(Error::WrongScope)
        ));
    }
    let mut reordered = fixture.signatures.clone();
    reordered.swap(3, 4);
    assert!(matches!(
        fixture.verify(&fixture.cuts[6], &reordered),
        Err(Error::Evidence(_))
    ));
    let mut reordered = fixture.cuts[6].clone();
    reordered.receipts.swap(4, 5);
    assert!(matches!(
        fixture.verify(&reordered, &fixture.signatures),
        Err(Error::Validation(_))
    ));
    let mut wrong_role = fixture.signatures.clone();
    wrong_role[3] = sign(
        /*index*/ 3,
        &fixture.cuts[4].receipts[3],
        Role::Observer,
        &fixture.verifier,
        fixture.at,
    )?;
    assert!(matches!(
        fixture.verify(&fixture.cuts[6], &wrong_role),
        Err(Error::Evidence(SignedEvidenceError::RoleMismatch))
    ));
    let mut premature = LearningIterationCoordinatorV1::from_snapshot(fixture.cuts[4].clone())?;
    let mut selection = fixture.cuts[5].receipts[4].clone();
    selection.observed_unix_seconds += 1;
    let mut premature_signatures = fixture.signatures[..4].to_vec();
    premature_signatures.push(sign(
        /*index*/ 4,
        &selection,
        Role::Selector,
        &fixture.verifier,
        fixture.at,
    )?);
    premature.record(selection, fixture.at + 1)?;
    assert!(matches!(
        fixture.verify(premature.snapshot(), &premature_signatures),
        Err(Error::Evidence(SignedEvidenceError::ContextMismatch))
    ));
    let candidate = LearningIterationCoordinatorV1::from_snapshot(fixture.cuts[4].clone())?
        .candidate()
        .expect("signed candidate metadata")
        .digest()?;
    let mut qualified = LearningIterationCoordinatorV1::from_snapshot(fixture.cuts[3].clone())?;
    let mut evaluation = fixture.cuts[4].receipts[3].clone();
    let Observation::Evaluation { disposition, .. } = &mut evaluation.observation else {
        unreachable!("evaluation metadata");
    };
    *disposition = LearningEvaluationDispositionV1::Qualified;
    let mut qualified_signatures = fixture.signatures[..3].to_vec();
    qualified_signatures.push(sign(
        /*index*/ 3,
        &evaluation,
        Role::Evaluator,
        &fixture.verifier,
        fixture.at,
    )?);
    qualified.record(evaluation, fixture.at)?;
    fixture.verify(qualified.snapshot(), &qualified_signatures)?;
    // Neither a positive B nor a negative B may borrow the other branch's
    // successor. Each rejected snapshot has an otherwise valid four-cut.
    for (prefix, observation) in [
        (
            qualified.snapshot().clone(),
            fixture.cuts[5].receipts[4].observation.clone(),
        ),
        (
            fixture.cuts[4].clone(),
            Observation::Proposal {
                candidate_bundle: candidate,
                proposal_id: fixture.cuts[4].request.operation_id.clone(),
                composition_digest: digest("negative-B-is-not-original-Model"),
                disposition: LearningProposalDispositionV1::UpdateCandidates,
            },
        ),
    ] {
        let mut illegal = prefix;
        let mut receipt = fixture.cuts[5].receipts[4].clone();
        receipt.predecessor = illegal.head_digest;
        receipt.actor_id = illegal.owners.owner(observation.stage()).clone();
        receipt.observation = observation;
        illegal.receipts.push(receipt);
        assert!(matches!(
            fixture.verify(&illegal, &fixture.signatures[..5]),
            Err(Error::Validation(LearningIterationError::WrongStage))
        ));
    }
    for index in [4, 5] {
        let mut wrong_bundle = fixture.cuts[6].clone();
        match &mut wrong_bundle.receipts[index].observation {
            Observation::Selection {
                candidate_bundle, ..
            } => *candidate_bundle = candidate,
            Observation::RetainedModelNextUse {
                retained_bundle, ..
            } => *retained_bundle = candidate,
            _ => unreachable!("selected metadata stages"),
        }
        assert!(matches!(
            fixture.verify(&wrong_bundle, &fixture.signatures),
            Err(Error::Validation(_))
        ));
    }
    assert!(matches!(
        authentication::verify_attestations(
            &fixture.root.profile,
            &fixture.verifier,
            &fixture.cuts[6],
            &fixture.signatures,
            fixture.at + 601,
        ),
        Err(Error::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    // A newly valid signature window is not the old owner's readback pin.
    let mut renewed = fixture.signatures.clone();
    renewed[3].expires_at -= 1;
    renewed[3].signature = SigningKey::from_bytes(&[154; 32])
        .sign(&renewed[3].signing_bytes())
        .to_bytes();
    let renewed = fixture.readback(/*count*/ 6, renewed)?;
    let previous = Some(ResidentReadbackPinV3 {
        snapshot: fixture.cuts[5].clone(),
        attestations: fixture.signatures[..5].to_vec(),
        model: None,
    });
    assert!(matches!(
        wire::require_original_prefix(&previous, &renewed),
        Err(Error::CommitUncertain)
    ));
    fixture.require_vacant()
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_retention_auth_refuses_all_cocontrolled_role_pairs() -> anyhow::Result<()> {
    for (left, right) in [(2, 3), (2, 4), (3, 4), (2, 5), (3, 5), (4, 5)] {
        let fixture = Metadata::new(Controllers::Shared { left, right })?;
        for (receipt, signature) in fixture.cuts[6].receipts.iter().zip(&fixture.signatures) {
            fixture.verifier.verify(
                signature.role,
                signature,
                &learning_iteration_receipt_signing_bytes_v1(receipt)?,
                fixture.at,
            )?;
        }
        assert!(matches!(
            fixture.verify(&fixture.cuts[6], &fixture.signatures),
            Err(Error::Evidence(SignedEvidenceError::ControllerCollision))
        ));
        fixture.require_vacant()?;
    }
    Ok(())
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_retention_auth_keeps_training_no_update_at_five_stages() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let (training_no_update, signatures) = metadata.completed_metadata()?;
    let root = ResidentRootFixture::new(metadata.initial, metadata.scope, &metadata.verifier)?;
    authentication::verify_attestations(
        &root.profile,
        &metadata.verifier,
        &training_no_update,
        &signatures,
        signatures[0].issued_at,
    )?;
    let mut extra = signatures.clone();
    extra.push(signatures[4].clone());
    assert!(matches!(
        authentication::verify_attestations(
            &root.profile,
            &metadata.verifier,
            &training_no_update,
            &extra,
            signatures[0].issued_at,
        ),
        Err(Error::WrongScope)
    ));
    let reply = wire::encode_current(ResidentRuntimeObservationV3 {
        snapshot: Some(training_no_update),
        attestations: extra,
        dispatch_pending: false,
        model: None,
    })?;
    assert!(matches!(
        wire::decode_current(
            reply,
            &root.profile,
            &metadata.verifier,
            signatures[0].issued_at
        ),
        Err(Error::WrongScope)
    ));
    assert!(
        root.registration
            .as_ref()
            .expect("protected Root")
            .owner
            .checkpoint
            .read()?
            .snapshot
            .is_none()
    );
    Ok(())
}
