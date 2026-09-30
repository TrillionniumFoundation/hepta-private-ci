//! Fixed synthetic trust configuration for cold-recovery and consumer fixtures.
//! A recovering child loads this host configuration without constructing a
//! model, dataset, qualification bundle or cached decision.
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub const MINIMUM_WINDOW_MICROS: u64 = 10;

pub fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
pub fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn key(role: LearningEvidenceRoleV1) -> SigningKey {
    SigningKey::from_bytes(&[match role {
        LearningEvidenceRoleV1::Generator => 41,
        LearningEvidenceRoleV1::Evaluator => 53,
        LearningEvidenceRoleV1::Observer => 67,
        _ => panic!("unexpected fixture role"),
    }; 32])
}

fn principal(role: LearningEvidenceRoleV1) -> AuthenticatedPrincipalV1 {
    let name = match role {
        LearningEvidenceRoleV1::Generator => "cold-generator",
        LearningEvidenceRoleV1::Evaluator => "cold-evaluator",
        LearningEvidenceRoleV1::Observer => "cold-observer",
        _ => panic!("unexpected fixture role"),
    };
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key(role).verifying_key().to_bytes()),
        scope_digest: digest("cold-scope"),
        authority_epoch: 9,
        authenticated_at: 10,
        expires_at: 100,
    }
}

pub fn definition(revoked: bool) -> LearningEvidenceTrustV1 {
    LearningEvidenceTrustV1 {
        scope_digest: digest("cold-scope"),
        objective_digest: digest("objective"),
        authority_epoch: 9,
        signers: [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Observer,
        ]
        .into_iter()
        .map(|role| {
            let principal = principal(role);
            TrustedLearningSignerV1 {
                controller_id: principal.principal_id.clone(),
                principal,
                verifying_key: key(role).verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: if revoked && role == LearningEvidenceRoleV1::Evaluator {
                    Some(80)
                } else {
                    None
                },
            }
        })
        .collect(),
    }
}

pub fn verifier(revoked: bool) -> LearningEvidenceVerifierV1 {
    LearningEvidenceVerifierV1::new(definition(revoked)).expect("host trust fixture")
}

fn activate_definition(revoked: bool) -> ActivatedLearningTrustV1 {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("cold-root"),
        scope_digest: digest("cold-scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 300,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("cold-distribution"),
            generation: 1,
            effective_at: 10,
            trust: definition(revoked),
        },
        root_id: root.root_id.clone(),
        issued_at: 5,
        expires_at: 90,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().expect("distribution bytes"))
        .to_bytes();
    activate_learning_trust(&root, distribution, None, 85).expect("activate fixture trust")
}

pub fn activate() -> ActivatedLearningTrustV1 {
    activate_definition(false)
}

pub fn activate_revoked() -> ActivatedLearningTrustV1 {
    activate_definition(true)
}

pub fn context() -> ProductQualificationContextV1 {
    ProductQualificationContextV1 {
        generator: principal(LearningEvidenceRoleV1::Generator),
        evaluator: principal(LearningEvidenceRoleV1::Evaluator),
        retention_receipt_digests: vec![digest("synthetic-retention")],
        unlearning_receipt_digest: digest("synthetic-unlearning"),
    }
}

pub fn sign(
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    issued_at: u64,
) -> SignedLearningEvidenceV1 {
    let principal = principal(role);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{}-evidence", principal.principal_id)),
        principal_id: principal.principal_id,
        role,
        trust_digest: verifier(false).trust_digest(),
        scope_digest: digest("cold-scope"),
        objective_digest: digest("objective"),
        authority_epoch: 9,
        issued_at,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key(role).sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

pub fn timing(bundle: &IndependentEvaluationBundleV1) -> LongitudinalTimeEvidenceV1 {
    assert!(bundle.snapshot_ids.len() >= 3 && bundle.future_window_ids.len() >= 2);
    let mut timing = LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: 20,
        windows: bundle
            .future_window_ids
            .iter()
            .take(2)
            .enumerate()
            .map(|(index, window)| ObservedFutureWindowV1 {
                window_id: window.clone(),
                snapshot_id: bundle.snapshot_ids[index + 1].clone(),
                starts_unix_micros: 31 + index as u64 * 11,
                ends_unix_micros: 41 + index as u64 * 11,
                observation_count: 2048,
                observed_source_cut: digest(&format!("synthetic-cut-{index}")),
            })
            .collect(),
        observer: sign(LearningEvidenceRoleV1::Observer, b"placeholder", 70),
    };
    let payload = future_window_signing_payload_v1(bundle, &timing, MINIMUM_WINDOW_MICROS)
        .expect("observer payload");
    timing.observer = sign(LearningEvidenceRoleV1::Observer, &payload, 70);
    timing
}

pub fn evidence(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    timing: Option<&LongitudinalTimeEvidenceV1>,
) -> SignedEvaluationEvidenceV1 {
    let payload = match timing {
        Some(timing) => longitudinal_evaluation_signing_payload_v3(
            bundle,
            roles,
            timing,
            MINIMUM_WINDOW_MICROS,
        )
        .expect("V3 payload"),
        None => evaluation_signing_payload_v2(bundle, roles).expect("V2 payload"),
    };
    SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            LearningEvidenceRoleV1::Generator,
            bundle.frozen_plan.plan_digest.as_array(),
            20,
        ),
        evaluator_bundle: sign(LearningEvidenceRoleV1::Evaluator, &payload, 80),
    }
}
