use codex_hepta_authbus::AuthBusSignature;
use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;

use super::*;

pub(super) enum EvidenceSigner {
    Classic(Box<SigningKey>),
    Pq(Box<PqNativeSigningKey>),
}

impl EvidenceSigner {
    pub(super) fn new(seed: u8, algorithm: AuthBusAlgorithm) -> Self {
        match algorithm {
            AuthBusAlgorithm::Ed25519V1 => {
                Self::Classic(Box::new(SigningKey::from_bytes(&[seed; 32])))
            }
            AuthBusAlgorithm::MlDsa65V2 => {
                let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
                let pin = ml_dsa_65_key_id_from_spki(&spki).unwrap();
                Self::Pq(Box::new(
                    PqNativeSigningKey::from_owned_seed([seed; 32].into(), pin).unwrap(),
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

    pub(super) fn sign(&self, message: &[u8]) -> AuthBusSignature {
        match self {
            Self::Classic(key) => key.sign(message).to_bytes().into(),
            Self::Pq(key) => key.sign_exact_message(message).unwrap().into(),
        }
    }
}

#[tokio::test]
async fn pq_time_and_settlement_cross_the_existing_bao_product_path() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("pq-fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (db, checkpoint, authbus, mut evidence, admission) =
        authbus_host(&client, &request, now, AuthBusAlgorithm::MlDsa65V2)
            .await
            .unwrap();
    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();
    let receipt = client
        .consume_kv_v2_with_authbus(
            &authbus,
            &admission,
            &authority,
            &grant,
            &request,
            &mut evidence,
            |bytes| {
                assert_eq!(bytes, SECRET.as_bytes());
                Ok(())
            },
        )
        .await
        .unwrap();
    assert_eq!(receipt.secret_sha256, request.expected_secret_sha256);
    let quota = authbus.quota_snapshot(&admission.quota_key).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 0, 1));
    drop(authbus);
    let database = db.path().join("authbus-authority.sqlite");
    let checkpoint = checkpoint.path().join("authbus-authority-checkpoint.json");
    assert!(matches!(
        AuthBusAuthorityHost::open(&database, checkpoint.clone(), "bao-product-owner").await,
        Err(AuthBusAuthorityError::CryptoProfileMismatch)
    ));
    let recovered = AuthBusAuthorityHost::open_pq(&database, checkpoint, "bao-product-owner")
        .await
        .unwrap();
    assert_eq!(
        recovered
            .quota_snapshot(&admission.quota_key)
            .await
            .unwrap(),
        quota
    );
    task.await.unwrap().unwrap();
}
