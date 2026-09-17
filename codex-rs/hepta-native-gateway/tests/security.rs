#![forbid(unsafe_code)]

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use pretty_assertions::assert_eq;

#[path = "../src/shell_runtime.rs"]
mod shell_runtime;
#[path = "../src/platform_adapter.rs"]
mod platform_adapter;
#[path = "../src/security.rs"]
mod security;

use security::DetachedSignatureVerifier;
use security::SignedGrantVerifier;
use shell_runtime::GrantVerifier;
use shell_runtime::PlatformAction;
use shell_runtime::PlatformRequest;
use shell_runtime::SessionKey;
use shell_runtime::VerifiedPlatformGrant;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const SIGNATURE: &str = "aabbccdd";

#[derive(Clone, Debug)]
struct FixtureSignatures {
    expected_message: Arc<Mutex<Option<Vec<u8>>>>,
    accept: bool,
}

impl FixtureSignatures {
    fn accepting() -> Self {
        Self {
            expected_message: Arc::new(Mutex::new(None)),
            accept: true,
        }
    }

    fn rejecting() -> Self {
        Self {
            expected_message: Arc::new(Mutex::new(None)),
            accept: false,
        }
    }

    fn observed_message(&self) -> Option<Vec<u8>> {
        self.expected_message
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }
}

impl DetachedSignatureVerifier for FixtureSignatures {
    fn verify(&self, message: &[u8], signature: &[u8]) -> Result<bool> {
        *self
            .expected_message
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = Some(message.to_vec());
        assert_eq!(signature, &[0xaa, 0xbb, 0xcc, 0xdd]);
        Ok(self.accept)
    }
}

fn session() -> SessionKey {
    SessionKey {
        session_id: "session.1".to_string(),
        generation: 3,
    }
}

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after unix epoch")
        .as_millis()
        .try_into()
        .expect("millisecond clock fits u64")
}

fn request_with_window(not_before: u64, expires: u64) -> PlatformRequest {
    PlatformRequest {
        operation_id: "operation.1".to_string(),
        action: PlatformAction::Notify,
        resource: "message".to_string(),
        displayed_revision: 11,
        payload_digest: D1.to_string(),
        grant: format!(
            "native-grant-v1|session.1|3|operation.1|notify|{D1}|{not_before}|{expires}|authority.native|{SIGNATURE}"
        ),
    }
}

#[test]
fn signed_grant_binds_exact_session_operation_action_payload_and_expiry() -> Result<()> {
    let now = now_millis();
    let signatures = FixtureSignatures::accepting();
    let observer = signatures.clone();
    let verifier = SignedGrantVerifier::new(signatures);
    let request = request_with_window(now.saturating_sub(1000), now + 60_000);

    assert_eq!(
        verifier.verify(&session(), &request)?,
        VerifiedPlatformGrant {
            session: session(),
            operation_id: "operation.1".to_string(),
            action: PlatformAction::Notify,
            payload_digest: D1.to_string(),
        }
    );
    let observed = String::from_utf8(observer.observed_message().expect("signed message"))?;
    assert_eq!(
        observed,
        format!(
            "native-grant-v1|session.1|3|operation.1|notify|{D1}|{}|{}|authority.native",
            now.saturating_sub(1000),
            now + 60_000
        )
    );
    Ok(())
}

#[test]
fn signature_rejection_fails_closed() {
    let now = now_millis();
    let verifier = SignedGrantVerifier::new(FixtureSignatures::rejecting());
    let error = verifier
        .verify(
            &session(),
            &request_with_window(now.saturating_sub(1000), now + 60_000),
        )
        .unwrap_err();
    assert!(error.to_string().contains("signature is invalid"));
}

#[test]
fn expired_or_excessively_long_grants_fail_before_signature_acceptance() {
    let now = now_millis();
    let verifier = SignedGrantVerifier::new(FixtureSignatures::accepting());
    let expired = request_with_window(now.saturating_sub(120_000), now.saturating_sub(60_000));
    assert!(
        verifier
            .verify(&session(), &expired)
            .unwrap_err()
            .to_string()
            .contains("not currently valid")
    );

    let too_long = request_with_window(now, now + Duration::from_secs(10 * 60).as_millis() as u64);
    assert!(
        verifier
            .verify(&session(), &too_long)
            .unwrap_err()
            .to_string()
            .contains("lifetime is invalid")
    );
}

#[test]
fn caller_cannot_retarget_a_signed_grant() {
    let now = now_millis();
    let verifier = SignedGrantVerifier::new(FixtureSignatures::accepting());
    let mut request = request_with_window(now.saturating_sub(1000), now + 60_000);
    request.operation_id = "operation.2".to_string();
    let error = verifier.verify(&session(), &request).unwrap_err();
    assert!(error.to_string().contains("does not bind"));
}
