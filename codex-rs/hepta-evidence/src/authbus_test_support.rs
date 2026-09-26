use std::path::Path;
use std::sync::Arc;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(crate) struct TestAuthority {
    pub(crate) host: Arc<AuthBusAuthorityHost>,
    pub(crate) issuer_id: StableId,
    pub(crate) epoch: Generation,
    key: SigningKey,
}

impl TestAuthority {
    pub(crate) async fn open(
        root: &Path,
        issuer_id: &str,
        epoch: u64,
        seed: u8,
    ) -> Self {
        let suffix = issuer_id.replace([':', '/', '\\'], "-");
        let database = root
            .join(format!("authbus-authority-{suffix}"))
            .join("authority.sqlite");
        let checkpoint = root
            .join(format!("authbus-witness-{suffix}"))
            .join("checkpoint.json");
        let host = Arc::new(
            AuthBusAuthorityHost::open_or_bootstrap(
                &database,
                checkpoint,
                &format!("test:{issuer_id}"),
            )
            .await
            .expect("open test authority"),
        );
        let key = SigningKey::from_bytes(&[seed; 32]);
        let issuer_id = StableId::new(issuer_id).expect("issuer id");
        let epoch = Generation::new(epoch).expect("issuer epoch");
        host.enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: issuer_id.clone(),
                key_epoch: epoch,
                verifying_key: key.verifying_key(),
            },
        )
        .await
        .expect("enroll test issuer");
        Self {
            host,
            issuer_id,
            epoch,
            key,
        }
    }

    pub(crate) async fn handle(&self) -> IssuerRegistration {
        self.host
            .verify_message_issuer(&self.issuer_id, self.epoch)
            .await
            .expect("resolve test issuer")
    }

    pub(crate) fn message(
        &self,
        message_id: impl Into<String>,
        subject_id: StableId,
        scope_digest: Digest32,
        payload_digest: Digest32,
        sequence: u64,
        expires_at_ms: u64,
    ) -> SignedMessage {
        let claims = SignedMessageClaims {
            issuer_id: self.issuer_id.clone(),
            key_epoch: self.epoch,
            message_id: StableId::new(message_id.into()).expect("message id"),
            subject_id,
            scope_digest,
            payload_digest,
            sequence,
            expires_at_ms,
        };
        SignedMessage {
            signature: self.key.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        }
    }

    pub(crate) async fn revoke(&self) {
        let record = self
            .host
            .issuer_record(IssuerPurpose::Message, &self.issuer_id, self.epoch)
            .await
            .expect("issuer record");
        self.host
            .revoke_issuer(
                IssuerPurpose::Message,
                &self.issuer_id,
                self.epoch,
                record.revision(),
            )
            .await
            .expect("revoke test issuer");
    }
}
