//! Signed data/codec components only. Fixture Root keys and profiles never
//! create the opaque actual-session recipient capsule or a Dataset authority.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::root_initial_learning_trust_data::LearningTrustRoleV1;
use crate::root_initial_learning_trust_data::LearningTrustSignerDataV1;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn fixture() -> TestResult<(
    HistoricalLearningTrustPayloadV1,
    HistoricalLearningTrustPinV1,
    LearningIterationSnapshotV1,
)> {
    let mut signed = crate::root_initial_learning_trust_data::tests::payload();
    let key = SigningKey::from_bytes(&[76; 32]).verifying_key().to_bytes();
    signed.distribution.signers.push(LearningTrustSignerDataV1 {
        principal_id: "freeze-evaluator".into(),
        credential_chain_digest: Digest32::of_bytes(b"freeze-evaluator").into_array(),
        signing_key_digest: Digest32::of_bytes(&key).into_array(),
        scope_digest: signed.root.scope_digest,
        authority_epoch: 1,
        authenticated_at_seconds: 10,
        expires_at_seconds: 100,
        controller_id: "freeze-controller".into(),
        verifying_key: key,
        roles: vec![LearningTrustRoleV1::Evaluator],
        revoked_at_seconds: None,
    });
    crate::root_initial_learning_trust_data::tests::sign(&mut signed)?;
    let (activated, _, _) = signed.activate_pinned_genesis(/*now_seconds*/ 50)?;
    let (_directory, _, coordinator) =
        crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
    let initial = coordinator.snapshot();
    let mut request = initial.request.clone();
    request.envelope.objective_digest = activated.verifier().objective_digest();
    let mut owners = initial.owners.clone();
    owners.evidence_trust_digest = activated.verifier().trust_digest();
    let initial = LearningIterationCoordinatorV1::new(request, owners)?
        .snapshot()
        .clone();
    let payload = HistoricalLearningTrustPayloadV1 {
        signed,
        freeze_evaluator: LearningTrustRoleSelectionV1 {
            principal_id: "freeze-evaluator".into(),
            controller_id: "freeze-controller".into(),
        },
    };
    let pin = HistoricalLearningTrustPinV1 {
        initial: initial.head_digest.to_string(),
        target: Digest32::of_bytes(b"component-target").to_string(),
        mapping: Digest32::of_bytes(b"component-mapping").to_string(),
        payload: Digest32::of_bytes(&serde_json::to_vec(&payload.signed)?).to_string(),
        root: activated.root_digest().to_string(),
        distribution: activated.distribution_digest().to_string(),
        trust: activated.verifier().trust_digest().to_string(),
        learning_scope: activated.verifier().scope_digest().to_string(),
        objective: activated.verifier().objective_digest().to_string(),
        freeze_evaluator: payload.freeze_evaluator_digest()?.to_string(),
    };
    Ok((payload, pin, initial))
}

#[test]
fn historical_recipient_trust_activates_current_signed_roles_and_refuses_old_or_forged_inputs()
-> TestResult {
    let (payload, pin, initial) = fixture()?;
    let (activated, evaluator) =
        payload.activate_for_recipient(&initial, /*now_seconds*/ 50)?;
    payload.require_activation_pin(&initial, &activated, &pin)?;
    assert_eq!(
        evaluator.principal.principal_id.as_str(),
        "freeze-evaluator"
    );
    let mut old = initial.clone();
    old.owners.evidence_trust_digest = Digest32::of_bytes(b"old-A-trust");
    assert!(
        payload
            .activate_for_recipient(&old, /*now_seconds*/ 50)
            .is_err()
    );
    assert!(
        payload
            .activate_for_recipient(&initial, /*now_seconds*/ 91)
            .is_err()
    );
    let mut forged = payload.clone();
    forged.signed.distribution.signature[0] ^= 1;
    assert!(
        forged
            .activate_for_recipient(&initial, /*now_seconds*/ 50)
            .is_err()
    );
    let mut wrong_role = payload;
    wrong_role.freeze_evaluator = wrong_role.signed.generator.clone();
    assert!(
        wrong_role
            .activate_for_recipient(&initial, /*now_seconds*/ 50)
            .is_err()
    );
    Ok(())
}

#[test]
fn historical_recipient_trust_reply_is_strict_and_keeps_the_original_wire_budget() -> TestResult {
    use crate::root_historical_task_read_protocol::HistoricalReadOperationV1;
    use crate::root_historical_task_read_protocol::HistoricalTaskReadRequestV1;
    use crate::root_historical_task_read_protocol::WIRE_BOUND;

    let (payload, pin, initial) = fixture()?;
    let response = HistoricalLearningTrustResponseV1 {
        schema: 1,
        purpose: TRUST_PURPOSE.into(),
        request_id: 1,
        profile: Digest32::of_bytes(b"actual-profile-data").to_string(),
        data_cut: Digest32::of_bytes(b"complete-observed-task-data").to_string(),
        pin: pin.clone(),
        payload,
    };
    let bytes = serde_json::to_vec(&response)?;
    assert!(bytes.len() <= WIRE_BOUND);
    let decoded = require_original_trust_reply(
        &bytes,
        /*request_id*/ 1,
        &response.profile,
        &pin,
        &initial,
    )?;
    assert_eq!(decoded.payload, response.payload);
    for field in ["purpose", "profile", "data_cut", "grant"] {
        let mut altered = serde_json::to_value(&response)?;
        altered[field] = serde_json::json!("untrusted-override");
        assert!(
            require_original_trust_reply(
                &serde_json::to_vec(&altered)?,
                /*request_id*/ 1,
                &response.profile,
                &pin,
                &initial
            )
            .is_err()
        );
    }
    assert!(HistoricalReadOperationV1::from_purpose(TRUST_PURPOSE).is_ok());
    assert!(
        HistoricalReadOperationV1::from_purpose("runtime.learning.historical-source-cell-read.v1")
            .is_err()
    );
    let mut request = serde_json::json!({"schema":1,"purpose":TRUST_PURPOSE,"request_id":1,"profile":response.profile});
    request["root_key"] = serde_json::json!(vec![0; 32]);
    assert!(serde_json::from_value::<HistoricalTaskReadRequestV1>(request).is_err());
    Ok(())
}
