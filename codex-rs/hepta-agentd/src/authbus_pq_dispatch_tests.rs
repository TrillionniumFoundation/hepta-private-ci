use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;

use super::*;

pub(super) enum FixtureSigner {
    Classic(Box<SigningKey>),
    Pq(Box<PqNativeSigningKey>),
}

impl FixtureSigner {
    pub(super) fn new(seed: u8, algorithm: AuthBusAlgorithm) -> Self {
        match algorithm {
            AuthBusAlgorithm::Ed25519V1 => {
                Self::Classic(Box::new(SigningKey::from_bytes(&[seed; 32])))
            }
            AuthBusAlgorithm::MlDsa65V2 => {
                let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
                Self::Pq(Box::new(
                    PqNativeSigningKey::from_owned_seed(
                        [seed; 32].into(),
                        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
                    )
                    .unwrap(),
                ))
            }
        }
    }

    pub(super) fn algorithm(&self) -> AuthBusAlgorithm {
        match self {
            Self::Classic(_) => AuthBusAlgorithm::Ed25519V1,
            Self::Pq(_) => AuthBusAlgorithm::MlDsa65V2,
        }
    }

    pub(super) fn verifying_key(&self) -> AuthBusVerifyingKey {
        match self {
            Self::Classic(key) => key.verifying_key().into(),
            Self::Pq(key) => AuthBusVerifyingKey::from_pq_spki(key.public_spki()).unwrap(),
        }
    }

    pub(super) fn sign(&self, owner: &AgentId, request: &mut AuthBusTextIngress) {
        match self {
            Self::Classic(key) => {
                request.signature_hex = key
                    .sign(&authbus_text_claims(owner, request).unwrap().signing_bytes())
                    .to_bytes()
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect();
            }
            Self::Pq(key) => crate::sign_authbus_text_pq(owner, request, key).unwrap(),
        }
    }
}

#[tokio::test]
async fn pq_text_producer_recovers_through_existing_dispatch_and_rejects_wire_and_config_downgrade()
{
    let fixture = Fixture::with_algorithm(AuthBusAlgorithm::MlDsa65V2).await;
    let mut request = fixture.request(1);
    request.body.text = "x".repeat(8192);
    fixture
        .key
        .sign(&fixture.state.identity().agent_id, &mut request);
    assert_eq!(request.signature_hex.len(), 3309 * 2);
    assert!(serde_json::to_vec(&request).unwrap().len() < crate::MAX_CONTROL_FRAME_BYTES as usize);
    let mut downgrade = request.clone();
    downgrade.auth_version = 1;
    assert!(submit(&fixture.state, downgrade).await.is_err());
    let mut short_signature = request.clone();
    short_signature.signature_hex = "00".repeat(64);
    assert!(submit(&fixture.state, short_signature).await.is_err());
    let id = submit(&fixture.state, request)
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let recovered = TextIngress::open(
        fixture.state.identity(),
        fixture.trust_file.clone(),
        fixture.checkpoint_file.clone(),
    )
    .await
    .unwrap();
    let delivery = fixture.claim(&recovered, id).await;
    assert_eq!(delivery.message.signature.len(), 3309);
    let queue = ReplyLostQueue::default();
    queue.lose_reply.store(false, Ordering::SeqCst);
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(
        recovered
            .evidence
            .authbus_delivery_status(id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Acked
    );
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);
    let mut classic: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&fixture.trust_file).unwrap()).unwrap();
    classic.as_object_mut().unwrap().remove("policy_revision");
    classic["schema_version"] = serde_json::json!(1);
    let classic_key = SigningKey::from_bytes(&[17; 32]);
    classic["public_key_hex"] = serde_json::json!(
        classic_key
            .verifying_key()
            .as_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    );
    std::fs::write(&fixture.trust_file, serde_json::to_vec(&classic).unwrap()).unwrap();
    assert_eq!(
        crate::authbus_trust::TextTrust::load(&fixture.trust_file, fixture.state.identity())
            .unwrap()
            .algorithm()
            .unwrap(),
        AuthBusAlgorithm::Ed25519V1,
    );
    assert!(
        TextIngress::open(
            fixture.state.identity(),
            fixture.trust_file.clone(),
            fixture.checkpoint_file.clone()
        )
        .await
        .is_err()
    );
    assert!(submit(&fixture.state, fixture.request(2)).await.is_err());
    let mut classic_request = fixture.request(2);
    classic_request.auth_version = 1;
    classic_request.signature_hex = classic_key
        .sign(
            &authbus_text_claims(&fixture.state.identity().agent_id, &classic_request)
                .unwrap()
                .signing_bytes(),
        )
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    assert!(submit(&fixture.state, classic_request).await.is_err());
    fixture.trust(false);
    let resumed_id = submit(&fixture.state, fixture.request(2))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let delivery = fixture.claim(&recovered, resumed_id).await;
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 2);
    fixture.trust(true);
    assert!(submit(&fixture.state, fixture.request(3)).await.is_err());
    fixture.trust(false);
    assert!(
        TextIngress::open(
            fixture.state.identity(),
            fixture.trust_file.clone(),
            fixture.checkpoint_file.clone()
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn pq_text_owner_resumes_after_revocation_rotation_and_rejected_config_rollback() {
    let mut fixture = Fixture::with_algorithm(AuthBusAlgorithm::MlDsa65V2).await;
    let old_trust = std::fs::read(&fixture.trust_file).unwrap();
    let first = fixture.request(/*sequence*/ 1);
    let stale = fixture.request(/*sequence*/ 2);
    let queue = ReplyLostQueue::default();
    queue.lose_reply.store(false, Ordering::SeqCst);

    let first_id = submit(&fixture.state, first)
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, first_id).await;
    deliver(&fixture.state, &host, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);

    fixture.trust(/*revoked*/ true);
    assert!(submit(&fixture.state, stale.clone()).await.is_err());
    fixture.trust(/*revoked*/ false);
    assert!(submit(&fixture.state, stale.clone()).await.is_err());
    assert!(
        TextIngress::open(
            fixture.state.identity(),
            fixture.trust_file.clone(),
            fixture.checkpoint_file.clone(),
        )
        .await
        .is_err()
    );
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);

    // A legitimately installed newer key generation restores service. Never
    // clear the revoked epoch, replay journal or independently retained fence.
    fixture.key = FixtureSigner::new(/*seed*/ 56, AuthBusAlgorithm::MlDsa65V2);
    fixture.key_epoch = 2;
    fixture.trust(/*revoked*/ false);
    let current_trust = std::fs::read(&fixture.trust_file).unwrap();
    assert!(submit(&fixture.state, stale.clone()).await.is_err());
    let mut next = fixture.request(/*sequence*/ 1);
    next.message_id = "message:epoch2:1".into();
    fixture
        .key
        .sign(&fixture.state.identity().agent_id, &mut next);
    let next_id = submit(&fixture.state, next.clone())
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let recovered = TextIngress::open(
        fixture.state.identity(),
        fixture.trust_file.clone(),
        fixture.checkpoint_file.clone(),
    )
    .await
    .unwrap();
    let delivery = fixture.claim(&recovered, next_id).await;
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_ne!(first_id, next_id);
    assert_eq!(queue.accepted.lock().unwrap().len(), 2);
    assert_eq!(
        recovered
            .evidence
            .authbus_delivery_status(next_id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Acked
    );
    assert_eq!(
        submit(&fixture.state, next).await.unwrap().delivery_id,
        next_id.to_string()
    );
    assert_eq!(queue.accepted.lock().unwrap().len(), 2);

    // A rejected owner-file rollback cannot erase the durable issuer floor.
    // Restoring the current owner file permits a new ordinary signed message.
    std::fs::write(&fixture.trust_file, old_trust).unwrap();
    assert!(submit(&fixture.state, stale).await.is_err());
    assert_eq!(queue.accepted.lock().unwrap().len(), 2);
    std::fs::write(&fixture.trust_file, current_trust).unwrap();
    let mut last = fixture.request(/*sequence*/ 2);
    last.message_id = "message:epoch2:2".into();
    fixture
        .key
        .sign(&fixture.state.identity().agent_id, &mut last);
    let last_id = submit(&fixture.state, last)
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let delivery = fixture.claim(&recovered, last_id).await;
    deliver(&fixture.state, &recovered, &queue, delivery)
        .await
        .unwrap();
    assert_eq!(queue.accepted.lock().unwrap().len(), 3);
}
