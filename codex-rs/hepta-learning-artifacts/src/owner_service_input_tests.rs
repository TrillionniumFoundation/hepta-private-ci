use super::tests::*;
use super::*;
use crate::test_support::FixtureValue;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

#[test]
fn rejected_new_request_does_not_leave_a_recovery_fence() {
    for case in 0..3 {
        let directory = TestDir::new();
        let key = key();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope = withdrawals.scope_digest().fixture("scope");
        let mut service =
            LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                root: directory.0.clone(),
                trust: trust(&key, scope),
                writer_lease: lease(&key, scope),
                required_current_head: None,
                withdrawal_registry: withdrawals.clone(),
                storage_binding: digest("binding"),
                now: 20,
            })
            .fixture("owner");
        let mut request = publish_request(&key, &withdrawals, Digest32::ZERO, digest("preview"));
        let preview = ArtifactPublicationTransactionV1::begin(
            request.operation_id.clone(),
            request.admission.clone(),
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            20,
        )
        .fixture("preview");
        let mut staged = ArtifactRegistry::new();
        service
            .host
            .stage_compatibility_registration(&preview, &mut staged, 20)
            .fixture("stage");
        request.signed_current_head.witness.head_digest = staged.snapshot().head_digest;
        request.signed_current_head.signature = key
            .sign(&request.signed_current_head.signing_bytes())
            .to_bytes();
        let valid = request.clone();
        match case {
            0 => request.payload = b"invalid".to_vec(),
            1 => request.signed_current_head.signature[0] ^= 1,
            2 => {
                request.signed_current_head.witness.head_digest = digest("other-head");
                request.signed_current_head.signature = key
                    .sign(&request.signed_current_head.signing_bytes())
                    .to_bytes();
            }
            _ => unreachable!(),
        }
        assert!(service.publish(request).is_err());
        assert_eq!(
            service.recovery_required(),
            None,
            "case {case}: invalid input must not create durable intent"
        );
        assert!(
            service
                .host
                .recover_publication(&valid.operation_id)
                .fixture("inspect")
                .is_none()
        );
        service
            .publish(valid)
            .fixture("valid request still publishes");
    }
}
