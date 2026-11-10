//! Synthetic mechanism checks. Test keys and cohorts are not deployed owners
//! or independent-learning efficacy evidence.
use super::*;
use pretty_assertions::assert_eq;

#[path = "product_execution_process_tests.rs"]
mod process_tests;

use crate::ProductEvaluationExecutionAttestationRequestV1;
use crate::ProductEvaluationExecutionAttestorV1;
use crate::ProductEvaluationExecutionClaimV1 as Claim;
use crate::ProductEvaluationExecutionErrorV1 as Error;
use crate::ProductEvaluationExecutionKeyV1 as Key;
use crate::ProductEvaluationExecutionRequestV1;
use crate::ProductEvaluationExecutionStateV1 as State;
use crate::ProductEvaluationExecutionStoreErrorV1 as StoreError;
use crate::ProductEvaluationExecutionStoreV1;

#[derive(Clone, Copy, Default)]
enum LostAck {
    #[default]
    None,
    Claim,
    Complete,
}

#[derive(Default)]
struct Executions {
    state: Option<(Key, State)>,
    lost: LostAck,
    takeover: Option<MemoryCas>,
}

impl ProductEvaluationExecutionStoreV1 for Executions {
    fn claim(&mut self, key: &Key) -> Result<Claim, StoreError> {
        if let Some((stored, state)) = &self.state {
            if let Some(store) = self.takeover.take() {
                FencedFinalHoldoutOwnerV1::recover(
                    store,
                    digest("holdout-binding"),
                    HoldoutWriterFenceV1 {
                        owner_id: id("evaluation-owner"),
                        generation: 2,
                        lease_digest: digest("during-readback"),
                    },
                )
                .expect("successor takes over during execution readback");
            }
            return if stored == key {
                Ok(Claim::Existing(state.clone()))
            } else {
                Err(StoreError::Conflict)
            };
        }
        self.state = Some((key.clone(), State::Pending));
        if matches!(self.lost, LostAck::Claim) {
            return Err(StoreError::Indeterminate);
        }
        Ok(Claim::Claimed)
    }
    fn complete(&mut self, key: &Key, payload: &[u8]) -> Result<(), StoreError> {
        let (stored, state) = self.state.as_mut().ok_or(StoreError::Missing)?;
        if stored != key || *state != State::Pending {
            return Err(StoreError::Conflict);
        }
        *state = State::Completed(payload.to_vec());
        if matches!(self.lost, LostAck::Complete) {
            return Err(StoreError::Indeterminate);
        }
        Ok(())
    }
    fn readback(&mut self, key: &Key) -> Result<State, StoreError> {
        let (stored, state) = self.state.as_ref().ok_or(StoreError::Missing)?;
        if stored != key {
            return Err(StoreError::Conflict);
        }
        Ok(state.clone())
    }
}

struct Attestor {
    principal: AuthenticatedPrincipalV1,
    key: SigningKey,
    trust: Digest32,
    objective: Digest32,
    calls: usize,
    unavailable: bool,
    original: Option<ProductTemporalEvaluationReceiptV1>,
}

impl ProductEvaluationExecutionAttestorV1 for Attestor {
    fn attest_execution(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, ProductProviderErrorV1> {
        self.calls += 1;
        if self.unavailable {
            return Err(ProductProviderErrorV1::Unavailable);
        }
        request
            .execution()
            .validate_integrity()
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        if request.key().plan_id != request.execution().product_plan.frozen_plan.plan_id {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.original = Some(request.execution().clone());
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: id("original-execution"),
            principal_id: self.principal.principal_id.clone(),
            role: LearningEvidenceRoleV1::Evaluator,
            trust_digest: self.trust,
            scope_digest: self.principal.scope_digest,
            objective_digest: self.objective,
            authority_epoch: 7,
            issued_at: 10,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(request.signing_payload()),
            signature: [0; 64],
        };
        signed.signature = self.key.sign(&signed.signing_bytes()).to_bytes();
        Ok(signed)
    }
}

struct Harness {
    fixture: Fixture,
    frozen: ProductFrozenEvaluationPlanV1,
    cas: MemoryCas,
    runner: ProductEvaluationRunnerV1<MemoryCas>,
    context: ProductQualificationContextV1,
    trust: LearningEvidenceTrustV1,
    verifier: LearningEvidenceVerifierV1,
    attestor: Attestor,
    executions: Executions,
    now: u64,
}

impl Harness {
    fn new() -> Self {
        let fixture = fixture();
        let frozen = freeze_product_evaluation_plan_v1(
            fixture.cross_fold.clone(),
            fixture.roles.clone(),
            fixture.sources.clone(),
            &fixture.candidate_plan,
            &fixture.baseline_plan,
        )
        .expect("frozen plan");
        let cas = MemoryCas::default();
        let owner = FencedFinalHoldoutOwnerV1::initialize(
            cas.clone(),
            digest("holdout-binding"),
            HoldoutWriterFenceV1 {
                owner_id: id("evaluation-owner"),
                generation: 1,
                lease_digest: digest("lease-1"),
            },
        )
        .expect("original holdout owner");
        let generator_key = SigningKey::from_bytes(&[41; 32]);
        let evaluator_key = SigningKey::from_bytes(&[42; 32]);
        let principal = |name: &str, key: &SigningKey| AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("product-eval-scope"),
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: 100,
        };
        let generator = principal("generator", &generator_key);
        let evaluator = principal("evaluator", &evaluator_key);
        let trust = LearningEvidenceTrustV1 {
            scope_digest: evaluator.scope_digest,
            objective_digest: frozen.frozen_plan.objective_digest,
            authority_epoch: 7,
            signers: vec![
                TrustedLearningSignerV1 {
                    principal: generator.clone(),
                    controller_id: id("generator-controller"),
                    verifying_key: generator_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: evaluator.clone(),
                    controller_id: id("evaluator-controller"),
                    verifying_key: evaluator_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Evaluator],
                    revoked_at: None,
                },
            ],
        };
        let verifier = LearningEvidenceVerifierV1::new(trust.clone()).expect("original trust");
        let attestor = Attestor {
            principal: evaluator.clone(),
            key: evaluator_key,
            trust: verifier.trust_digest(),
            objective: frozen.frozen_plan.objective_digest,
            calls: 0,
            unavailable: false,
            original: None,
        };
        Self {
            fixture,
            frozen,
            cas,
            runner: ProductEvaluationRunnerV1::new(owner),
            context: ProductQualificationContextV1 {
                generator,
                evaluator,
                retention_receipt_digests: Vec::new(),
                unlearning_receipt_digest: Digest32::ZERO,
            },
            trust,
            verifier,
            attestor,
            executions: Executions::default(),
            now: 50,
        }
    }

    fn run(&mut self) -> Result<ProductTemporalEvaluationReceiptV1, Error> {
        let clock = || Ok(self.now);
        self.runner.evaluate_or_readback_temporal_comparison(
            &ProductEvaluationExecutionRequestV1 {
                plan: &self.frozen,
                candidate_plan: &self.fixture.candidate_plan,
                baseline_plan: &self.fixture.baseline_plan,
                evaluator: &self.context.evaluator,
                verifier: &self.verifier,
                clock: &clock,
            },
            &mut self.fixture.provider,
            &mut self.executions,
            &mut self.attestor,
        )
    }

    fn reopen(&mut self) {
        self.runner = ProductEvaluationRunnerV1::new(
            FencedFinalHoldoutOwnerV1::recover(
                self.cas.clone(),
                digest("holdout-binding"),
                HoldoutWriterFenceV1 {
                    owner_id: id("evaluation-owner"),
                    generation: 2,
                    lease_digest: digest("lease-2"),
                },
            )
            .expect("original history takeover"),
        );
    }

    fn readback(&mut self) -> Result<ProductTemporalEvaluationReceiptV1, Error> {
        let clock = || Ok(self.now);
        self.runner.readback_temporal_comparison(
            &ProductEvaluationExecutionRequestV1 {
                plan: &self.frozen,
                candidate_plan: &self.fixture.candidate_plan,
                baseline_plan: &self.fixture.baseline_plan,
                evaluator: &self.context.evaluator,
                verifier: &self.verifier,
                clock: &clock,
            },
            &mut self.executions,
        )
    }
}

#[test]
fn signed_completion_lost_ack_reopens_without_release_or_resigning() {
    let mut test = Harness::new();
    test.executions.lost = LostAck::Complete;
    assert_eq!(test.run(), Err(Error::Store(StoreError::Indeterminate)));
    let mut original = test.attestor.original.clone().expect("original execution");
    original.execution_evaluator = Some(test.context.evaluator.clone());
    test.reopen();
    let before = test.runner.holdout_anchor();
    assert_eq!(
        test.readback().expect("authenticated original readback"),
        original
    );
    assert_eq!(test.readback().expect("idempotent readback"), original);
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
    assert_eq!(test.runner.holdout_anchor(), before);
    assert!(!original.authority.grants_any());
}

#[test]
fn read_only_missing_execution_never_creates_a_claim() {
    let mut test = Harness::new();
    let before = test.runner.holdout_anchor();
    assert_eq!(test.readback(), Err(Error::Store(StoreError::Missing)));
    assert_eq!(test.executions.state, None);
    assert_eq!(test.runner.holdout_anchor(), before);
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (0, 0)
    );
}

#[test]
fn read_only_pending_execution_never_reissues_work() {
    let mut test = Harness::new();
    test.executions.lost = LostAck::Claim;
    assert_eq!(test.run(), Err(Error::Store(StoreError::Indeterminate)));
    let before = (test.runner.holdout_anchor(), test.executions.state.clone());
    assert_eq!(test.readback(), Err(Error::Pending));
    assert_eq!((test.runner.holdout_anchor(), test.executions.state), before);
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (0, 0)
    );
}

#[test]
fn uncertain_claim_never_starts_holdout_work() {
    let mut test = Harness::new();
    let before = test.runner.holdout_anchor();
    test.executions.lost = LostAck::Claim;
    assert_eq!(test.run(), Err(Error::Store(StoreError::Indeterminate)));
    assert_eq!(test.run(), Err(Error::Pending));
    assert_eq!(test.runner.holdout_anchor(), before);
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (0, 0)
    );
}

#[test]
fn provider_and_attestor_failures_leave_pending_without_second_release() {
    for failure in ["provider", "attestor"] {
        let mut test = Harness::new();
        if failure == "provider" {
            test.fixture.provider.inputs = None;
        }
        if failure == "attestor" {
            test.attestor.unavailable = true;
        }
        assert!(matches!(
            test.run(),
            Err(Error::Evaluation(ProductEvaluationError::Provider(_)))
        ));
        test.reopen();
        assert_eq!(test.run(), Err(Error::Pending));
        assert_eq!(test.fixture.provider.release_count, 1);
    }
}

#[test]
fn readback_requires_current_evaluator_trust_and_original_validity() {
    let mut test = Harness::new();
    test.run().expect("complete original");
    test.now = 91;
    assert!(matches!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Signed(_)))
    ));
    test.now = 50;
    test.trust.signers[1].revoked_at = Some(50);
    test.verifier =
        LearningEvidenceVerifierV1::new(test.trust.clone()).expect("current revoked trust");
    assert!(matches!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Signed(_)))
    ));
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn changed_plan_and_changed_evaluator_do_not_consume_or_reuse() {
    let mut test = Harness::new();
    test.fixture.candidate_plan.ope.maximum_weight = FixedQ32::ONE;
    assert_eq!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Binding(
            "temporal execution plan"
        )))
    );
    assert!(test.executions.state.is_none());
    assert_eq!(test.fixture.provider.release_count, 0);
    let mut test = Harness::new();
    test.run().expect("complete original");
    test.context.evaluator.credential_chain_digest = digest("substituted evaluator");
    assert_eq!(test.run(), Err(Error::Store(StoreError::Conflict)));
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn self_rehashed_execution_bytes_cannot_replace_original_signature() {
    let mut test = Harness::new();
    test.run().expect("complete original");
    let (key, State::Completed(bytes)) = test.executions.state.as_mut().expect("stored original")
    else {
        panic!("completed state")
    };
    let (mut signed, body) =
        execution_codec::decode_envelope(bytes).expect("original signed envelope");
    let mut changed = body.to_vec();
    changed[8] ^= 1;
    let mut payload = b"hepta.intelligence-eval.signed-execution.v1".to_vec();
    super::super::push_id(&mut payload, &key.plan_id);
    payload.extend_from_slice(key.binding_digest.as_array());
    payload.extend_from_slice(Digest32::of_bytes(&changed).as_array());
    signed.payload_digest = Digest32::of_bytes(&payload);
    *bytes = execution_codec::encode_envelope(&signed, &changed).expect("self-rehashed envelope");
    assert!(matches!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Signed(_)))
    ));
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn stale_holdout_owner_cannot_read_a_valid_execution() {
    let mut test = Harness::new();
    test.run().expect("complete original");
    let _successor = FencedFinalHoldoutOwnerV1::recover(
        test.cas.clone(),
        digest("holdout-binding"),
        HoldoutWriterFenceV1 {
            owner_id: id("evaluation-owner"),
            generation: 2,
            lease_digest: digest("successor"),
        },
    )
    .expect("take over original history");
    assert_eq!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Holdout(
            crate::FencedHoldoutError::StaleFence
        )))
    );
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn takeover_during_completed_readback_refuses_the_cached_execution() {
    let mut test = Harness::new();
    test.run().expect("complete original");
    test.executions.takeover = Some(test.cas.clone());
    assert_eq!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Holdout(
            crate::FencedHoldoutError::StaleFence
        )))
    );
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
}

#[test]
fn consumed_holdout_without_execution_is_not_released_again() {
    let mut test = Harness::new();
    test.runner
        .evaluate_temporal_comparison(
            &test.frozen,
            &test.fixture.candidate_plan,
            &test.fixture.baseline_plan,
            &mut test.fixture.provider,
        )
        .expect("original legacy execution");
    assert_eq!(test.run(), Err(Error::MissingExecution));
    assert_eq!(test.run(), Err(Error::Pending));
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 0)
    );
}

#[test]
fn restored_execution_qualifies_only_with_its_original_evaluator() {
    let mut test = Harness::new();
    let restored = test.run().expect("signed execution");
    let bundle = test
        .runner
        .qualification_bundle(&restored, &test.context)
        .expect("same original evaluator");
    let (context, evidence, verifier) = signed_context(&bundle, &test.fixture.roles);
    let mut sink = Sink::default();
    let receipt = test
        .runner
        .qualify_and_persist(
            &restored,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 50,
            &mut sink,
        )
        .expect("original dual signed qualification");
    assert!(!receipt.authority.grants_any());
    let mut substituted = context;
    substituted.evaluator = substituted.generator.clone();
    assert_eq!(
        test.runner.qualification_bundle(&restored, &substituted),
        Err(ProductEvaluationError::Binding("execution evaluator"))
    );
    assert_eq!(sink.persisted, vec![receipt.publication_digest]);
}

#[test]
fn bounded_codec_rejects_truncation_trailing_bytes_and_historical_binding_changes() {
    let mut test = Harness::new();
    let restored = test.run().expect("signed execution");
    let encoded = execution_codec::encode_execution(&restored).expect("original body");
    for size in [0, 7, 39, encoded.len() - 1] {
        assert!(
            execution_codec::decode_execution(&encoded[..size], &test.frozen, &restored.holdout)
                .is_err()
        );
    }
    let mut extra = encoded.clone();
    extra.push(0);
    assert!(execution_codec::decode_execution(&extra, &test.frozen, &restored.holdout).is_err());
    let mut wrong = restored.holdout;
    wrong.sequence += 1;
    assert!(execution_codec::decode_execution(&encoded, &test.frozen, &wrong).is_err());
}
