//! A retained evaluator cannot differ from the request's signed owner pin.

use super::*;
use codex_hepta_intelligence::CurrentOwnerStateV1;

#[allow(
    clippy::expect_used,
    reason = "The two signed manifests deliberately differ only in evaluator key identity."
)]
fn evaluator_b_for_snapshot_a() -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
    Vec<OwnerBindingV1>,
) {
    let (mut value, _) = signed_fixture();
    let b = value.owners.clone();
    let key_a = SigningKey::from_bytes(&[48; 32]);
    for owner in &mut value.owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest = Digest32::of_bytes(&key_a.verifying_key().to_bytes());
        }
    }
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(),
        authority_epoch: snapshot.authority_epoch(),
        body_generation: snapshot.body_generation(),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .expect("snapshot A");
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    let context = compile(value.inputs.context_request.clone()).expect("context A");
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).expect("legal set");
    let binding = AgentdEvaluationBindingV1 {
        run_id: value.request.run_id.clone(),
        objective_digest: value.request.snapshot.objective_digest(),
        snapshot_digest: value.request.snapshot.digest(),
        context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest,
        selected_candidate_id: id("action.read"),
    };
    let (trust, signed) = crate::intelligence_product::evaluation_tests::evidence_fixture(
        &binding,
        wall_clock_ms().expect("clock"),
    );
    value.inputs.signed_evaluation = Some(signed);
    (value, trust, b)
}

#[tokio::test]
#[allow(
    clippy::expect_used,
    reason = "A mismatched signed owner must reject before even occupied worker admission."
)]
async fn evaluator_session_rejects_a_different_snapshot_pin_before_worker_admission() {
    let (value, trust, b) = evaluator_b_for_snapshot_a();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority");
    write_authority_file(
        &path,
        &b,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust B");
    let _occupied = runner
        .worker_slots
        .clone()
        .acquire_many_owned(MAX_CANONICAL_OWNER_WORKERS as u32)
        .await
        .expect("reserve workers");
    let profile = routing_profile(
        &value.inputs.intuition_request,
        CanonicalRiskRuleV1::HighOnlySlowPath,
    );
    assert!(matches!(
        runner
            .prepare_for_composition_with_intuition(
                product_test_coordinator().composition(),
                value.request,
                value.inputs,
                AgentdIntuitionComputationV1::Product(Box::new(profile)),
            )
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::StaleOwner(owner)
        )) if owner == id("learning.eval")
    ));
}

struct RestoreManifest<'a, O> {
    oracle: O,
    path: &'a std::path::Path,
    owners: &'a [OwnerBindingV1],
    frontier: Digest32,
    restored: bool,
}

impl<O: CanonicalFreshnessOracleV1> CanonicalFreshnessOracleV1 for RestoreManifest<'_, O> {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        let result = self.oracle.current(owner_id);
        if !self.restored {
            write_authority_file(self.path, self.owners, self.frontier);
            self.restored = true;
        }
        result
    }
}

#[tokio::test]
#[allow(
    clippy::expect_used,
    reason = "Restoring signed manifest A must not hide a captured evaluator B session."
)]
async fn restoring_manifest_a_cannot_admit_evaluator_b_proof_bound_to_context_a() {
    let (value, trust, b) = evaluator_b_for_snapshot_a();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority");
    let frontier = value.request.snapshot.revocation_frontier_digest();
    write_authority_file(&path, &b, frontier);
    let source = FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier());
    let mut restoring = RestoreManifest {
        oracle: source.snapshot_oracle(),
        path: &path,
        owners: &value.owners,
        frontier,
        restored: false,
    };
    assert_eq!(
        crate::intelligence_product::authority::current_from_snapshot(
            &value.request.snapshot,
            &mut restoring,
            &id("learning.eval"),
        ),
        Err(CanonicalIntelligenceError::StaleOwner(id("learning.eval")))
    );
    assert!(restoring.restored);
    source
        .validate_snapshot(&value.request.snapshot)
        .expect("fresh manifest A really matches snapshot A");
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust B");
    let profile = routing_profile(
        &value.inputs.intuition_request,
        CanonicalRiskRuleV1::HighOnlySlowPath,
    );
    assert!(matches!(
        runner
            .prepare_for_composition_with_intuition(
                product_test_coordinator().composition(),
                value.request,
                value.inputs,
                AgentdIntuitionComputationV1::Product(Box::new(profile)),
            )
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::PortFailure {
                stage: CanonicalStageV1::EvaluationAdmitted,
                ..
            }
        ))
    ));
}
