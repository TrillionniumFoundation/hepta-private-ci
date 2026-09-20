//! Virtual-clock admission tests, not observed future-calendar results.
use super::digest;
use super::*;
use crate::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

struct Fixture {
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    verifier: LearningEvidenceVerifierV1,
    keys: [SigningKey; 3],
    principals: [AuthenticatedPrincipalV1; 3],
    timing: LongitudinalTimeEvidenceV1,
}
impl Fixture {
    fn new() -> Self {
        let mut bundle = bundle();
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("task-utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        bundle.frozen_plan = freeze_cross_fold_plan_v2(plan(), roles.clone()).expect("freeze");
        bundle.holdout_use = FinalHoldoutRegistry::new()
            .consume(&bundle.frozen_plan)
            .expect("holdout");
        bundle.future_window_ids = vec![id("w-1"), id("w-2")];
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
            SigningKey::from_bytes(&[33; 32]),
        ];
        let mut principals = [
            bundle.generator.clone(),
            bundle.evaluator.clone(),
            actor("observer", "observer-chain", "observer-key"),
        ];
        let mut signers = Vec::new();
        for (index, role) in [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Observer,
        ]
        .into_iter()
        .enumerate()
        {
            principals[index].scope_digest = digest("shared-scope");
            principals[index].signing_key_digest =
                Digest32::of_bytes(&keys[index].verifying_key().to_bytes());
            signers.push(TrustedLearningSignerV1 {
                principal: principals[index].clone(),
                controller_id: principals[index].principal_id.clone(),
                verifying_key: keys[index].verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            });
        }
        bundle.generator = principals[0].clone();
        bundle.evaluator = principals[1].clone();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("shared-scope"),
            objective_digest: bundle.objective_digest,
            authority_epoch: 4,
            signers,
        })
        .expect("trusted fixture keys");
        let timing = LongitudinalTimeEvidenceV1 {
            frozen_unix_micros: 10,
            windows: vec![
                ObservedFutureWindowV1 {
                    window_id: id("w-1"),
                    snapshot_id: id("snapshot-2"),
                    starts_unix_micros: 11,
                    ends_unix_micros: 25,
                    observation_count: 400,
                    observed_source_cut: digest("cut-1"),
                },
                ObservedFutureWindowV1 {
                    window_id: id("w-2"),
                    snapshot_id: id("snapshot-3"),
                    starts_unix_micros: 26,
                    ends_unix_micros: 40,
                    observation_count: 400,
                    observed_source_cut: digest("cut-2"),
                },
            ],
            observer: SignedLearningEvidenceV1 {
                evidence_id: id("observer"),
                principal_id: id("observer"),
                role: LearningEvidenceRoleV1::Observer,
                trust_digest: verifier.trust_digest(),
                scope_digest: digest("shared-scope"),
                objective_digest: bundle.objective_digest,
                authority_epoch: 4,
                issued_at: 45,
                expires_at: 90,
                payload_digest: Digest32::ZERO,
                signature: [0; 64],
            },
        };
        Self {
            bundle,
            roles,
            verifier,
            keys,
            principals,
            timing,
        }
    }
    fn sign(
        &self,
        index: usize,
        role: LearningEvidenceRoleV1,
        bytes: &[u8],
        issued_at: u64,
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: self.principals[index].principal_id.clone(),
            principal_id: self.principals[index].principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: digest("shared-scope"),
            objective_digest: self.bundle.objective_digest,
            authority_epoch: 4,
            issued_at,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(bytes),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
    fn attest(&mut self) -> SignedEvaluationEvidenceV1 {
        let observed = future_window_signing_payload_v1(&self.bundle, &self.timing, 10)
            .expect("observer bytes");
        self.timing.observer = self.sign(2, LearningEvidenceRoleV1::Observer, &observed, 45);
        let evaluated =
            longitudinal_evaluation_signing_payload_v3(&self.bundle, &self.roles, &self.timing, 10)
                .expect("evaluator bytes");
        SignedEvaluationEvidenceV1 {
            generator_plan: self.sign(
                0,
                LearningEvidenceRoleV1::Generator,
                self.bundle.frozen_plan.plan_digest.as_array(),
                10,
            ),
            evaluator_bundle: self.sign(1, LearningEvidenceRoleV1::Evaluator, &evaluated, 50),
        }
    }
    fn decide(
        &self,
        evidence: &SignedEvaluationEvidenceV1,
    ) -> Result<SignedEvaluationDecisionV1, SignedEvaluationError> {
        decide_with_signed_longitudinal_evidence_v3(
            self.bundle.clone(),
            self.roles.clone(),
            evidence,
            &self.timing,
            10,
            &self.verifier,
            50,
        )
    }
}

#[test]
fn signed_observed_windows_pass_only_with_full_statistical_bundle() {
    let mut fixture = Fixture::new();
    let evidence = fixture.attest();
    let result = fixture
        .decide(&evidence)
        .expect("valid virtual-clock evidence");
    assert_eq!(
        result.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!result.decision.authority.grants_any());
    fixture.bundle.retention_receipt_digests.clear();
    let evidence = fixture.attest();
    assert_eq!(
        fixture
            .decide(&evidence)
            .expect("insufficient")
            .decision
            .disposition,
        IndependentEvaluationDispositionV1::InsufficientEvidence
    );
}

#[test]
fn valid_signatures_do_not_hide_unobserved_overlapping_or_wrong_source_windows() {
    for mutation in 0..7 {
        let mut fixture = Fixture::new();
        match mutation {
            0 => fixture.timing.windows[1].ends_unix_micros = 80,
            1 => fixture.timing.windows[1].starts_unix_micros = 20,
            2 => fixture.timing.windows[0].starts_unix_micros = 5,
            3 => fixture.timing.windows[0].observation_count = 0,
            4 => fixture.timing.windows[0].snapshot_id = id("not-loaded"),
            5 => {
                fixture.timing.windows[1].observed_source_cut =
                    fixture.timing.windows[0].observed_source_cut
            }
            6 => fixture.timing.frozen_unix_micros = 9,
            _ => unreachable!(),
        }
        let evidence = fixture.attest();
        assert!(matches!(
            fixture.decide(&evidence),
            Err(SignedEvaluationError::Timing(_))
        ));
    }
}

#[test]
fn time_policy_observer_and_future_collection_cannot_be_substituted() {
    let mut fixture = Fixture::new();
    let mut evidence = fixture.attest();
    assert!(
        decide_with_signed_longitudinal_evidence_v3(
            fixture.bundle.clone(),
            fixture.roles.clone(),
            &evidence,
            &fixture.timing,
            9,
            &fixture.verifier,
            50
        )
        .is_err()
    );
    assert!(
        crate::longitudinal_time::validate_observed_windows(
            &fixture.bundle,
            &fixture.timing,
            10,
            10,
            39
        )
        .is_err()
    );
    evidence.evaluator_bundle.signature[0] ^= 1;
    assert!(fixture.decide(&evidence).is_err());
    let evidence = fixture.attest();
    fixture.timing.observer.signature[0] ^= 1;
    assert!(fixture.decide(&evidence).is_err());
}
