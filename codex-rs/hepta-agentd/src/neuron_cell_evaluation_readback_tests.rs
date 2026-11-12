//! Synthetic cohorts and role keys; original file journals and signed Product
//! execution recovery. These checks do not establish deployed owner custody.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_ledger::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;

struct Authority {
    evaluator: AuthenticatedPrincipalV1,
    verifier: LearningEvidenceVerifierV1,
    now: u64,
}

impl Authority {
    fn new() -> Self {
        let scope = digest("synthetic-cell-evaluation-scope");
        let signers: Vec<_> = [
            ("generator", 41, LearningEvidenceRoleV1::Generator),
            ("evaluator", 42, LearningEvidenceRoleV1::Evaluator),
        ]
        .into_iter()
        .map(|(name, seed, role)| {
            let key = SigningKey::from_bytes(&[seed; 32]);
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(name),
                    credential_chain_digest: digest(&format!("{name}-credential")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: scope,
                    authority_epoch: 7,
                    authenticated_at: 1,
                    expires_at: 100,
                },
                controller_id: id(name),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            }
        })
        .collect();
        let evaluator = signers[1].principal.clone();
        let verifier = checked(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers,
        }));
        Self {
            evaluator,
            verifier,
            now: 50,
        }
    }
}

struct Attestor {
    trust: Digest32,
    calls: usize,
}

impl ProductEvaluationExecutionAttestorV1 for Attestor {
    fn attest_execution(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, ProductProviderErrorV1> {
        self.calls += 1;
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id("cell-execution"),
            principal_id: id("evaluator"),
            role: LearningEvidenceRoleV1::Evaluator,
            trust_digest: self.trust,
            scope_digest: digest("synthetic-cell-evaluation-scope"),
            objective_digest: request
                .execution()
                .product_plan
                .frozen_plan
                .objective_digest,
            authority_epoch: 7,
            issued_at: 10,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(request.signing_payload()),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[42; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        Ok(evidence)
    }
}

struct Executions {
    inner: LockedFileProductEvaluationExecutionStoreV1,
    claims: usize,
}

impl Executions {
    fn new(fixture: &Fixture) -> Self {
        Self {
            inner: checked(LockedFileProductEvaluationExecutionStoreV1::create(
                file(&fixture.directory.path().join("executions")),
                digest("execution-owner"),
            )),
            claims: 0,
        }
    }
}

impl ProductEvaluationExecutionStoreV1 for Executions {
    fn claim(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionClaimV1, ProductEvaluationExecutionStoreErrorV1> {
        self.claims += 1;
        self.inner.claim(key)
    }
    fn complete(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
        payload: &[u8],
    ) -> Result<(), ProductEvaluationExecutionStoreErrorV1> {
        self.inner.complete(key, payload)
    }
    fn readback(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionStateV1, ProductEvaluationExecutionStoreErrorV1> {
        self.inner.readback(key)
    }
}

struct Harness {
    fixture: Fixture,
    plan: CellEvaluationPlanV1,
    product: ProductFrozenEvaluationPlanV1,
    authority: Authority,
    executions: Executions,
    attestor: Attestor,
}

impl Harness {
    fn new() -> Self {
        let fixture = Fixture::new(Costs::Complete);
        let plan = checked(freeze_cell_learning_evaluation_plan_v1(
            fixture.registration.clone(),
            fixture.journals(),
            &fixture.candidate_temporal,
            &fixture.baseline_temporal,
            digest("host-frozen-evaluation-profile"),
        ));
        let authority = Authority::new();
        let executions = Executions::new(&fixture);
        let attestor = Attestor {
            trust: authority.verifier.trust_digest(),
            calls: 0,
        };
        Self {
            fixture,
            product: plan.product_plan().clone(),
            plan,
            authority,
            executions,
            attestor,
        }
    }

    fn run(&mut self) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        let fixture = &mut self.fixture;
        fixture.runner.evaluate_or_readback(
            &self.plan,
            CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &fixture.fixed,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: &self.product,
                candidate_plan: &fixture.candidate_temporal,
                baseline_plan: &fixture.baseline_temporal,
                evaluator: &self.authority.evaluator,
                verifier: &self.authority.verifier,
                clock: &|| Ok(self.authority.now),
            },
            &mut fixture.provider,
            &mut self.executions,
            &mut self.attestor,
        )
    }

    fn calls(&self) -> (usize, u32, u32, usize) {
        (
            self.executions.claims,
            self.fixture.provider.calls,
            self.fixture.provider.releases,
            self.attestor.calls,
        )
    }

    fn readback(&mut self) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        let fixture = &mut self.fixture;
        fixture.runner.readback_completed(
            &self.plan,
            CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &fixture.fixed,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: &self.product,
                candidate_plan: &fixture.candidate_temporal,
                baseline_plan: &fixture.baseline_temporal,
                evaluator: &self.authority.evaluator,
                verifier: &self.authority.verifier,
                clock: &|| Ok(self.authority.now),
            },
            &mut self.executions,
        )
    }
}

#[test]
fn completed_cell_execution_reopens_with_original_evaluator() {
    let mut test = Harness::new();
    let original = checked(test.run());
    let anchor = test.fixture.runner.product.holdout_anchor();
    let minimum = test.executions.inner.anchor();
    drop(test.fixture.runner);
    drop(test.executions);
    let store = checked(LockedFileFinalHoldoutCasStoreV1::recover(
        file(&test.fixture.directory.path().join("holdout")),
        digest("binding"),
        Some(anchor),
    ));
    let mut successor = fence();
    successor.generation += 1;
    successor.lease_digest = digest("successor-lease");
    let owner = checked(FencedFinalHoldoutOwnerV1::recover(
        store,
        digest("binding"),
        successor,
    ));
    test.fixture.runner = CellEvaluationRunnerV1::new(ProductEvaluationRunnerV1::new(owner));
    test.executions = Executions {
        inner: checked(LockedFileProductEvaluationExecutionStoreV1::recover(
            file(&test.fixture.directory.path().join("executions")),
            digest("execution-owner"),
            minimum,
        )),
        claims: 0,
    };
    let before = test.fixture.holdout_bytes();
    let restored = checked(test.readback());
    assert_eq!(restored, original);
    assert_eq!(
        restored.plan().record().learning_evaluation_profile,
        Some(digest("host-frozen-evaluation-profile").into_array())
    );
    assert_eq!(test.executions.inner.anchor(), minimum);
    // The original qualification helper must accept the preserved evaluator.
    let _qualification = signed(&test.fixture.runner, &restored);
    test.authority.now = 91;
    assert!(matches!(
        test.readback(),
        Err(CellEvaluationErrorV1::Execution(
            ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Signed(_))
        ))
    ));
    test.authority.now = 50;
    test.authority.evaluator.credential_chain_digest = digest("replacement-evaluator");
    assert!(matches!(
        test.readback(),
        Err(CellEvaluationErrorV1::Execution(
            ProductEvaluationExecutionErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Conflict
            )
        ))
    ));
    assert_eq!(test.calls(), (0, 1, 1, 1));
    assert_eq!(test.fixture.holdout_bytes(), before);
}

#[test]
fn missing_cell_execution_readback_never_claims_or_releases() {
    let mut test = Harness::new();
    let before = test.fixture.holdout_bytes();
    let minimum = test.executions.inner.anchor();
    let original = match test.readback() {
        Err(error) => error,
        Ok(_) => panic!("missing original execution unexpectedly completed"),
    };
    assert!(matches!(
        &original,
        CellEvaluationErrorV1::Execution(ProductEvaluationExecutionErrorV1::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        ))
    ));
    let receipt = crate::OriginalCellEvaluationReceiptErrorV1::Cell(original);
    assert!(matches!(
        crate::cell_q24_learning_owner_error::owner_error(receipt),
        crate::LearningIterationRuntimeErrorV1::OwnerUnavailable(_)
    ));
    assert_eq!(test.calls(), (0, 0, 0, 0));
    assert_eq!(test.executions.inner.anchor(), minimum);
    assert_eq!(test.fixture.holdout_bytes(), before);
}

#[test]
fn pending_cell_execution_readback_never_reissues_work() {
    let mut test = Harness::new();
    test.authority.now = 91;
    // The original work consumed its holdout but could not authenticate its
    // expired signature, so the original durable claim is still pending.
    assert!(matches!(
        test.run(),
        Err(CellEvaluationErrorV1::Execution(
            ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Signed(_))
        ))
    ));
    test.authority.now = 50;
    let before = test.fixture.holdout_bytes();
    let minimum = test.executions.inner.anchor();
    let calls = test.calls();
    let original = match test.readback() {
        Err(error) => error,
        Ok(_) => panic!("pending original execution unexpectedly completed"),
    };
    assert!(matches!(
        &original,
        CellEvaluationErrorV1::Execution(ProductEvaluationExecutionErrorV1::Pending)
    ));
    let receipt = crate::OriginalCellEvaluationReceiptErrorV1::Cell(original);
    assert!(matches!(
        crate::cell_q24_learning_owner_error::owner_error(receipt),
        crate::LearningIterationRuntimeErrorV1::CommitUncertain
    ));
    assert_eq!(test.calls(), calls);
    assert_eq!(test.executions.inner.anchor(), minimum);
    assert_eq!(test.fixture.holdout_bytes(), before);
}

#[test]
fn changed_cell_journals_and_foreign_product_plan_never_claim_execution() {
    for mutation in 0..3 {
        let mut test = Harness::new();
        let before = test.fixture.holdout_bytes();
        let fixture = &mut test.fixture;
        match mutation {
            0 => checked(fixture.candidate.resume()),
            1 => {
                checked(fixture.candidate.resume());
                checked(fixture.candidate.drain());
            }
            2 => checked(fixture.candidate.record_cost(CellCostEntryV2 {
                event_id: [99; 32],
                identity: checked(fixture.candidate.task_cost()).identity(),
                stage: CellCostStageV2::Recovery,
                outcome: CellCostOutcomeV2::Succeeded,
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2 {
                    wall_micros: Some(1),
                    cpu_micros: Some(1),
                    ..CellCostMetricsV2::default()
                },
            })),
            _ => unreachable!(),
        }
        assert!(test.run().is_err());
        assert!(test.readback().is_err());
        assert_eq!(test.calls(), (0, 0, 0, 0));
        assert_eq!(test.fixture.holdout_bytes(), before);
    }
    let mut test = Harness::new();
    test.fixture.registration.product.estimand_digest = digest("other-estimand");
    test.product = checked(test.fixture.freeze()).product_plan().clone();
    let before = test.fixture.holdout_bytes();
    assert!(matches!(
        test.run(),
        Err(CellEvaluationErrorV1::Binding(
            "Cell execution product plan"
        ))
    ));
    assert!(test.readback().is_err());
    assert_eq!(test.calls(), (0, 0, 0, 0));
    assert_eq!(test.fixture.holdout_bytes(), before);
}

#[test]
fn changed_learning_profile_is_refused_before_claim_or_holdout_contact() {
    let mut test = Harness::new();
    let original = checked(test.run());
    let before = test.fixture.holdout_bytes();
    let calls = test.calls();
    let foreign = checked(freeze_cell_learning_evaluation_plan_v1(
        test.fixture.registration.clone(),
        test.fixture.journals(),
        &test.fixture.candidate_temporal,
        &test.fixture.baseline_temporal,
        digest("different-learning-profile"),
    ));
    // This request retains the original Product plan. Swapping only the Cell
    // profile must be refused before touching the completed execution owner.
    test.plan = foreign;
    assert!(matches!(
        test.run(),
        Err(CellEvaluationErrorV1::Binding(
            "Cell execution product plan"
        ))
    ));
    assert_eq!(test.calls(), calls);
    assert_eq!(test.fixture.holdout_bytes(), before);
    test.plan = original.plan().clone();
    assert_eq!(checked(test.run()), original);
    assert_eq!(test.calls(), (calls.0 + 1, calls.1, calls.2, calls.3));
    assert_eq!(test.fixture.holdout_bytes(), before);
}

#[derive(Clone)]
struct SharedHoldout(Arc<Mutex<LockedFileFinalHoldoutCasStoreV1>>);

impl FinalHoldoutCasStoreV1 for SharedHoldout {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        self.0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?
            .load(binding)
    }
    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        self.0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?
            .compare_and_swap(binding, expected, next)
    }
}

#[test]
fn stale_cell_owner_cannot_read_completed_signed_execution() {
    let mut test = Harness::new();
    checked(test.run());
    let anchor = test.fixture.runner.product.holdout_anchor();
    drop(test.fixture.runner);
    let store = SharedHoldout(Arc::new(Mutex::new(checked(
        LockedFileFinalHoldoutCasStoreV1::recover(
            file(&test.fixture.directory.path().join("holdout")),
            digest("binding"),
            Some(anchor),
        ),
    ))));
    let owner = checked(FencedFinalHoldoutOwnerV1::recover(
        store.clone(),
        digest("binding"),
        fence(),
    ));
    let mut runner = CellEvaluationRunnerV1::new(ProductEvaluationRunnerV1::new(owner));
    let mut successor = fence();
    successor.generation += 1;
    successor.lease_digest = digest("successor-lease");
    let _successor = checked(FencedFinalHoldoutOwnerV1::recover(
        store,
        digest("binding"),
        successor,
    ));
    let authority = &test.authority;
    let claims = test.executions.claims;
    assert!(matches!(
        runner.readback_completed(
            &test.plan,
            CellEvaluationJournalsV1 {
                candidate: &test.fixture.candidate,
                fixed_expert: &test.fixture.fixed
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: &test.product,
                candidate_plan: &test.fixture.candidate_temporal,
                baseline_plan: &test.fixture.baseline_temporal,
                evaluator: &authority.evaluator,
                verifier: &authority.verifier,
                clock: &|| Ok(authority.now),
            },
            &mut test.executions,
        ),
        Err(CellEvaluationErrorV1::Execution(
            ProductEvaluationExecutionErrorV1::Evaluation(ProductEvaluationError::Holdout(
                FencedHoldoutError::StaleFence
            ))
        ))
    ));
    assert_eq!(test.executions.claims, claims);
    assert_eq!(
        (
            test.fixture.provider.calls,
            test.fixture.provider.releases,
            test.attestor.calls
        ),
        (1, 1, 1)
    );
}
