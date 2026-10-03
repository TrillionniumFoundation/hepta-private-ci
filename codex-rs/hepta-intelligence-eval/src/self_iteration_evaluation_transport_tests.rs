//! Synthetic native process-boundary tests; no installed keys or holdout reads.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::IndependentEvaluationDispositionV1;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::inputs;
use crate::paired_supervised_test_support::runner;
use pretty_assertions::assert_eq;

fn fixture() -> (SigningFixture, Publication) {
    let plan = crate::freeze_paired_supervised_plan_v1(inputs(6)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let execution = runner()
        .evaluate_paired_with_clock(
            &registration,
            &mut signing.provider(&plan),
            &signing.trust,
            &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    let mut bundle =
        crate::paired_supervised_qualification::paired_bundle(&execution, &signing.context())
            .unwrap();
    // A failed measured experiment is still an authenticated, completed round.
    bundle.metrics[0].candidate = bundle.metrics[0].baseline.clone();
    let roles: Vec<_> = plan
        .metrics
        .iter()
        .map(|metric| MetricRoleContractV2 {
            metric_id: metric.contract.metric_id.clone(),
            role: metric.role,
        })
        .collect();
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: execution.registration.generator_evidence.clone(),
        evaluator_bundle: signing.sign(
            2,
            &crate::evaluation_signing_payload_v2(&bundle, &roles).unwrap(),
            25,
        ),
    };
    let frozen_consumer = digest("frozen-original-cycle");
    let admission = admit_signed_eligibility_v2(
        bundle.clone(),
        roles.clone(),
        &evidence,
        &signing.verifier,
        frozen_consumer,
        30,
    )
    .unwrap();
    let use_attestation = signing.sign(
        2,
        &self_iteration_evaluation_use_payload_v1(
            frozen_consumer,
            admission.decision.authentication_digest,
        ),
        26,
    );
    (
        signing,
        Publication {
            frozen_consumer,
            bundle,
            roles,
            evidence,
            use_attestation,
        },
    )
}

#[test]
fn original_signed_rejection_crosses_only_its_current_frozen_consumer() {
    let (signing, original) = fixture();
    let bytes = encode_self_iteration_evaluation_transport_v1(
        original.frozen_consumer,
        original.bundle.clone(),
        original.roles.clone(),
        original.evidence.clone(),
        original.use_attestation.clone(),
        &signing.trust,
        30,
    )
    .unwrap();
    let received = decode_self_iteration_evaluation_transport_v1(
        &bytes,
        original.frozen_consumer,
        &signing.trust,
        30,
    )
    .unwrap();
    assert_eq!(received.publication, original);
    assert_eq!(
        received.admission.decision.decision.disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert!(!received.admission.authority.grants_any());
    assert!(
        decode_self_iteration_evaluation_transport_v1(
            &bytes,
            digest("another-frozen-cycle"),
            &signing.trust,
            30,
        )
        .is_err()
    );
    assert!(
        decode_self_iteration_evaluation_transport_v1(
            &bytes,
            original.frozen_consumer,
            &signing.trust,
            901,
        )
        .is_err()
    );
}

#[test]
fn forged_metrics_roles_candidate_or_use_attestation_never_escape_the_decoder() {
    let (signing, original) = fixture();
    for change in 0..5 {
        let mut forged = original.clone();
        match change {
            0 => forged.bundle.metrics[0].support_digest = digest("invented-metric-support"),
            1 => forged.roles[0].role = crate::MetricRoleV2::AbsoluteConstraint,
            2 => {
                forged.bundle.candidate_id =
                    crate::paired_supervised_test_support::id("invented-candidate")
            }
            3 => forged.use_attestation = signing.sign(1, b"observer-is-not-evaluator", 26),
            4 => forged.use_attestation.signature[0] ^= 1,
            _ => unreachable!(),
        }
        let bytes = encode(&forged).unwrap();
        assert!(
            decode_self_iteration_evaluation_transport_v1(
                &bytes,
                original.frozen_consumer,
                &signing.trust,
                30,
            )
            .is_err(),
            "forgery {change}"
        );
    }
    let mut trailing = encode(&original).unwrap();
    trailing.push(0);
    assert!(
        decode_self_iteration_evaluation_transport_v1(
            &trailing,
            original.frozen_consumer,
            &signing.trust,
            30,
        )
        .is_err()
    );
}
