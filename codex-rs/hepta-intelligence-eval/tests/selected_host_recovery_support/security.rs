use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::product::SelectedHostClockErrorV1;
use codex_hepta_intelligence_eval::product::SelectedHostClockV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

// Both single-outcome and multi-outcome test crates use this fixture. Do not
// depend on the name under which either crate registers its model module.
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture identity: {error:?}"))
}

pub struct FixtureClock {
    binding: Digest32,
    now: u64,
}

pub fn clock(now: u64) -> FixtureClock {
    FixtureClock {
        binding: digest("selected-host-test-clock"),
        now,
    }
}

impl SelectedHostClockV1 for FixtureClock {
    fn binding(&self) -> Digest32 {
        self.binding
    }

    fn sample_current_time(&mut self) -> Result<u64, SelectedHostClockErrorV1> {
        Ok(self.now)
    }
}

pub fn principal(name: &str, key: &SigningKey, scope: Digest32) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 9,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{}-evidence", principal.principal_id)),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: 9,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

pub fn verifier_and_evidence(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    generator_key: &SigningKey,
    evaluator_key: &SigningKey,
) -> (ActivatedLearningTrustV1, SignedEvaluationEvidenceV1) {
    let trust = LearningEvidenceTrustV1 {
        scope_digest: bundle.generator.scope_digest,
        objective_digest: bundle.objective_digest,
        authority_epoch: 9,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: bundle.generator.clone(),
                controller_id: bundle.generator.principal_id.clone(),
                verifying_key: generator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: bundle.evaluator.clone(),
                controller_id: bundle.evaluator.principal_id.clone(),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    };
    let root_key = SigningKey::from_bytes(&[89; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("selected-host-test-root"),
        scope_digest: bundle.generator.scope_digest,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 100,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("selected-host-test-distribution"),
            generation: 1,
            effective_at: 10,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 5,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key
        .sign(
            &signed
                .signing_bytes()
                .unwrap_or_else(|error| panic!("distribution payload: {error:?}")),
        )
        .to_bytes();
    let activated = activate_learning_trust(&root, signed, None, 50)
        .unwrap_or_else(|error| panic!("activated trust: {error:?}"));
    let verifier = activated.verifier();
    let payload = evaluation_signing_payload_v2(bundle, roles)
        .unwrap_or_else(|error| panic!("evaluation payload: {error:?}"));
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            verifier,
            &bundle.generator,
            generator_key,
            LearningEvidenceRoleV1::Generator,
            bundle.objective_digest,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            verifier,
            &bundle.evaluator,
            evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            bundle.objective_digest,
            &payload,
        ),
    };
    (activated, evidence)
}

#[derive(Clone)]
pub struct FaultingAnchorStore {
    state: Arc<Mutex<AnchorState>>,
}

struct AnchorState {
    retained: Option<ProductEvaluationAttemptAnchorV1>,
    fail_once_at_event_count: Option<u64>,
}

impl FaultingAnchorStore {
    pub fn new(fail_once_at_event_count: u64) -> Self {
        Self {
            state: Arc::new(Mutex::new(AnchorState {
                retained: None,
                fail_once_at_event_count: Some(fail_once_at_event_count),
            })),
        }
    }
}

impl ProductEvaluationAttemptAnchorStoreV1 for FaultingAnchorStore {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        let state = self
            .state
            .lock()
            .unwrap_or_else(|error| panic!("anchor state: {error:?}"));
        if state.retained.is_some_and(|value| value.binding != binding) {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        Ok(state.retained)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|error| panic!("anchor state: {error:?}"));
        if next.binding != binding || state.retained != expected {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        if state.fail_once_at_event_count == Some(next.event_count) {
            state.fail_once_at_event_count = None;
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        if expected.is_some_and(|value| {
            next.event_count < value.event_count || next.state_digest == value.state_digest
        }) {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        state.retained = Some(next);
        Ok(())
    }
}
