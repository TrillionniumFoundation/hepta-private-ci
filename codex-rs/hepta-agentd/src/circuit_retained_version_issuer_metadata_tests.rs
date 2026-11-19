//! Explicit E/D/T metadata only. The outer fixture separately executes real A
//! and owns the original Artifact, Control, FinalUse and C factory capabilities.
use super::*;
use crate::CellQ24DatasetRuleV1;
use crate::CellQ24PrivateHeadV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;

pub(super) fn rebuild_metadata(
    fixture: &mut RetainedPublicationFixture,
) -> anyhow::Result<(
    OriginalCellQ24MaterialReceiptConfigV1,
    Vec<SignedLearningEvidenceV1>,
)> {
    let at = now()?;
    let mut owners = fixture.metadata.initial.owners.clone();
    let mut signers = Vec::new();
    for (index, (actor, role)) in [
        (owners.trainer.clone(), LearningEvidenceRoleV1::Generator),
        (owners.selector.clone(), LearningEvidenceRoleV1::Selector),
        (
            owners.next_use_observer.clone(),
            LearningEvidenceRoleV1::Observer,
        ),
        (owners.experience.clone(), LearningEvidenceRoleV1::Observer),
        (owners.dataset.clone(), LearningEvidenceRoleV1::Observer),
        (owners.evaluator.clone(), LearningEvidenceRoleV1::Evaluator),
    ]
    .into_iter()
    .enumerate()
    {
        let key = SigningKey::from_bytes(&[101 + index as u8; 32]);
        signers.push(TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: actor,
                credential_chain_digest: d(&format!("retained-issuer-fixture-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: d("explicit-observer-trust"),
                authority_epoch: 1,
                authenticated_at: at - 60,
                expires_at: at + 1200,
            },
            controller_id: StableId::new(format!("retained-issuer-fixture-controller-{index}"))?,
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![role],
            revoked_at: None,
        });
    }
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: d("explicit-observer-trust"),
        objective_digest: fixture.metadata.initial.request.envelope.objective_digest,
        authority_epoch: 1,
        signers: signers.clone(),
    })?;
    owners.evidence_trust_digest = verifier.trust_digest();
    let mut decision =
        LearningIterationCoordinatorV1::new(fixture.metadata.initial.request.clone(), owners)?;
    let initial = decision.snapshot().clone();
    let update_rule = match &fixture.metadata.training.observation {
        LearningIterationObservationV1::TrainingNoUpdateV2(value) => value.update_rule,
        _ => anyhow::bail!("strict explicit NoUpdate fixture"),
    };
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        update_rule,
    )?;
    let mut evidence = Vec::new();
    for (index, old) in fixture
        .metadata
        .decision
        .snapshot()
        .receipts
        .iter()
        .enumerate()
    {
        let observation = LearningIterationReceiptV1 {
            operation_id: initial.request.operation_id.clone(),
            predecessor: decision.snapshot().head_digest,
            actor_id: old.actor_id.clone(),
            evidence_digest: if index < 2 {
                d("retained-issuer-explicit-material-provenance")
            } else {
                old.evidence_digest
            },
            observed_unix_seconds: at,
            observation: old.observation.clone(),
        };
        decision.record(observation.clone(), at)?;
        if index < 2 {
            evidence.push(signed(
                &observation,
                &verifier,
                LearningEvidenceRoleV1::Observer,
                &SigningKey::from_bytes(&[104 + index as u8; 32]),
                &format!("retained-issuer-explicit-material-{index}"),
            )?);
        }
    }
    let training = decision.snapshot().receipts[2].clone();
    let training_signature = signed(
        &training,
        &verifier,
        LearningEvidenceRoleV1::Generator,
        &SigningKey::from_bytes(&[101; 32]),
        "retained-issuer-explicit-training",
    )?;
    fixture.metadata = Metadata {
        initial: initial.clone(),
        decision,
        scope: scope.clone(),
        verifier: verifier.clone(),
        observer: signers[2].clone(),
        training,
        training_signature,
    };
    let rule = CellQ24DatasetRuleV1 {
        head: CellQ24PrivateHeadV1::Prediction { index: 0 },
        unit_profile_digest: d("retained-issuer-explicit-unit"),
    };
    let freeze_plan = DatasetFreezePlanV2 {
        snapshot_id: StableId::new("retained-issuer-explicit-freeze")?,
        objective_digest: verifier.objective_digest(),
        inclusion_policy_digest: rule.inclusion_policy_digest(&initial)?,
    };
    let mut freeze_evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("retained-issuer-explicit-freeze-evidence")?,
        principal_id: initial.owners.evaluator.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        payload_digest: d("explicit-fixture-not-a-Dataset-owner-execution"),
        authority_epoch: 1,
        issued_at: at,
        expires_at: at + 600,
        signature: [0; 64],
    };
    freeze_evidence.signature = SigningKey::from_bytes(&[106; 32])
        .sign(&freeze_evidence.signing_bytes())
        .to_bytes();
    Ok((
        OriginalCellQ24MaterialReceiptConfigV1 {
            initial,
            scope,
            rule,
            freeze_plan,
            freeze_evidence,
            experience_signer: signers[3].clone(),
            dataset_signer: signers[4].clone(),
            verifier,
            maximum_signature_lifetime_seconds: 600,
        },
        evidence,
    ))
}
