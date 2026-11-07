//! Actual PQ owner/Unix trust composition with a scripted private channel.
//! No result from this fixture qualifies Servo execution or external custody.

use super::*;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use crate::BrowserServoHost;
use codex_hepta_contracts::FinalUseAuthenticationProfile;

#[path = "browser_servo_pq_test_support.rs"]
mod support;
use support::Fixture;
use support::NOW;
use support::ScriptedBrowser;

#[path = "browser_servo_pq_cut_tests.rs"]
mod cuts;
#[path = "browser_servo_pq_rollback_tests.rs"]
mod rollback;

struct Harness {
    port: BrowserServoPort<ScriptedBrowser>,
    owner: FinalUseAuthority,
    output: Arc<Mutex<Vec<Value>>>,
}

fn harness(fixture: &Fixture, invocation: &BrowserFinalUseInvocation) -> anyhow::Result<Harness> {
    let host = BrowserServoHost::open(&fixture.config_path)?;
    let owner = host.authority.owner.clone();
    let output = Arc::new(Mutex::new(Vec::new()));
    let transport = ScriptedBrowser::new(Arc::clone(&output), invocation.binding.request_sha256);
    Ok(Harness {
        port: BrowserServoPort::new_pq(host.authority, transport),
        owner,
        output,
    })
}

fn entries(output: &Arc<Mutex<Vec<Value>>>) -> usize {
    output
        .lock()
        .expect("outbound frames")
        .iter()
        .filter(|value| value["kind"] == "authority_enter")
        .count()
}

#[test]
fn ordinary_browser_pq_enters_once_replay_is_spent_and_unknown_remains_readable()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let invocation = fixture.invocation(/*nonce*/ 41, NOW + 30_000)?;
    let h = harness(&fixture, &invocation)?;
    assert_eq!(
        h.owner.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    let expected = json!({"status":"indeterminate","terminalObserved":false});
    assert_eq!(
        h.port.call(BrowserServoCall::effect(
            json!({"operationId":"operation.1"}),
            invocation.clone()
        )?)?,
        expected
    );
    assert_eq!(entries(&h.output), 1);
    assert_eq!(h.owner.capacity()?.used_nonces, 1);
    assert!(matches!(
        h.port.call(BrowserServoCall::effect(
            json!({"operationId":"operation.1"}),
            invocation.clone()
        )?),
        Err(BrowserServoError::Authority(FinalUseError::AlreadyClaimed))
    ));
    let mut revoked = fixture.head.clone();
    revoked.revision += 1;
    revoked
        .revoked_grant_ids
        .insert(invocation.signed_grant.grant.grant_id);
    h.owner.update_revocations(revoked)?;
    fixture.now.store(NOW + 90_000, Ordering::SeqCst);
    let before = fixture.trust_requests();
    assert_eq!(
        h.port.call(BrowserServoCall::read(
            BrowserServoMethod::ReconcilePersistedOperation,
            json!({"operationId":"operation.1"})
        )?)?,
        expected
    );
    assert_eq!(fixture.trust_requests(), before);
    assert_eq!(entries(&h.output), 1);
    Ok(())
}

#[test]
fn ordinary_browser_refuses_legacy_missing_profile_and_expanded_deadline_before_trust()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let original = fixture.config.clone();
    for case in 0..4 {
        fixture.config = original.clone();
        match case {
            0 => {
                fixture
                    .config
                    .as_object_mut()
                    .expect("config")
                    .remove("authentication_profile");
            }
            1 => fixture.config["authentication_profile"] = json!("classical_v1"),
            2 => fixture.config = json!({"signer_id":"legacy","verifying_key":vec![0;32]}),
            3 => fixture.config["final_use"]["external_clock"]["timeout_ms"] = json!(2001),
            _ => unreachable!(),
        }
        fixture.write_config()?;
        assert!(
            matches!(BrowserServoHost::open(&fixture.config_path), Err(BrowserServoError::Invalid(message))
            if message.contains("explicit ml_dsa65_v2") || message.contains("trust deadline"))
        );
        assert!(!fixture.local.join("authority").exists());
        assert_eq!(fixture.trust_requests(), 0);
    }
    Ok(())
}

#[test]
fn ordinary_browser_refuses_reused_role_keys_before_owner_creation() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.config["final_use"]["revocation_keys"] =
        fixture.config["final_use"]["issuer_keys"].clone();
    fixture.write_config()?;
    assert!(
        matches!(BrowserServoHost::open(&fixture.config_path), Err(BrowserServoError::Invalid(message))
        if message.contains("distinct public keys"))
    );
    assert!(!fixture.local.join("authority").exists());
    assert_eq!(fixture.trust_requests(), 0);
    Ok(())
}

#[test]
fn browser_pq_forged_revoked_expired_and_uncovered_grants_never_enter() -> anyhow::Result<()> {
    for case in 0..5 {
        let fixture = Fixture::new()?;
        let mut invocation = fixture.invocation(/*nonce*/ 42, NOW + 30_000)?;
        match case {
            0 => invocation.signed_grant.signature[0] ^= 1,
            1 => {
                let mut revoked = fixture.head.clone();
                revoked.revision += 1;
                revoked
                    .revoked_grant_ids
                    .insert(invocation.signed_grant.grant.grant_id.clone());
                fixture.publish(revoked, NOW + 60_000)?;
            }
            2 => {
                fixture.now.store(NOW + 30_000, Ordering::SeqCst);
            }
            3 => fixture.publish(fixture.head.clone(), NOW + 20_000)?,
            4 => fixture.publish(fixture.head.clone(), NOW)?,
            _ => unreachable!(),
        }
        let h = harness(&fixture, &invocation)?;
        assert!(
            h.port
                .call(BrowserServoCall::effect(
                    json!({"operationId":"blocked"}),
                    invocation
                )?)
                .is_err()
        );
        assert_eq!(entries(&h.output), 0, "case {case}");
        assert_eq!(h.owner.capacity()?.used_nonces, 0, "case {case}");
    }
    Ok(())
}
