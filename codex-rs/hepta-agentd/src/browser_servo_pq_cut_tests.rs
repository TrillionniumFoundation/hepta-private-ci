use super::*;
use crate::pq_final_use::LockedDispatchLease;
use codex_hepta_contracts::VerifiedUseToken;

// Invoke the real claim and original locked dispatch entrypoints at explicit
// cut points. The shared lease cannot be synthesized from request JSON.
fn cross_boundary(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    invocation: &BrowserFinalUseInvocation,
    lease: LockedDispatchLease,
    output: Arc<Mutex<Vec<Value>>>,
) -> Result<(), BrowserServoError> {
    let mut state = PortState {
        transport: ScriptedBrowser::new(output, invocation.binding.request_sha256),
        next_request_id: 1,
        next_outgoing_sequence: 1,
        next_incoming_sequence: 1,
    };
    dispatch_final_use(authority, token, &invocation.binding, || {
        lease.check()?;
        send_frame(
            &mut state,
            "authority_enter",
            "browser.agentd.1",
            json!({"authorized":true}),
        )
    })?
}

#[test]
fn authenticated_feed_then_claim_revocation_and_head_drift_never_enter() -> anyhow::Result<()> {
    for revoke in [false, true] {
        let fixture = Fixture::new()?;
        let invocation = fixture.invocation(/*nonce*/ 43, NOW + 30_000)?;
        let authority = BrowserServoHost::open(&fixture.config_path)?.authority;
        let lease = authority.gate.authenticate(
            &authority.owner,
            &authority.feed_path,
            &invocation.signed_grant,
        )?;
        let mut successor = fixture.head.clone();
        successor.revision += 1;
        if revoke {
            successor
                .revoked_grant_ids
                .insert(invocation.signed_grant.grant.grant_id.clone());
        }
        fixture.publish(successor, NOW + 60_000)?;
        authority.gate.authenticate(
            &authority.owner,
            &authority.feed_path,
            &invocation.signed_grant,
        )?;
        let claim = claim_final_use(
            &authority.owner,
            &invocation.signed_grant,
            &invocation.binding,
        );
        if revoke {
            assert!(matches!(claim, Err(FinalUseError::Revoked)));
            assert_eq!(authority.owner.capacity()?.used_nonces, 0);
        } else {
            let token = claim?;
            assert!(matches!(
                lease.check_claim(&token),
                Err(FinalUseError::StaleRevocationHead)
            ));
            assert_eq!(authority.owner.capacity()?.used_nonces, 1);
        }
    }
    Ok(())
}

#[test]
fn claimed_browser_token_revoked_before_original_dispatch_never_enters() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let invocation = fixture.invocation(/*nonce*/ 44, NOW + 30_000)?;
    let authority = BrowserServoHost::open(&fixture.config_path)?.authority;
    let lease = authority.gate.authenticate(
        &authority.owner,
        &authority.feed_path,
        &invocation.signed_grant,
    )?;
    let token = claim_final_use(
        &authority.owner,
        &invocation.signed_grant,
        &invocation.binding,
    )?;
    let lease = lease.check_claim(&token)?;
    let mut revoked = fixture.head.clone();
    revoked.revision += 1;
    revoked
        .revoked_grant_ids
        .insert(invocation.signed_grant.grant.grant_id.clone());
    fixture.publish(revoked, NOW + 60_000)?;
    authority.gate.authenticate(
        &authority.owner,
        &authority.feed_path,
        &invocation.signed_grant,
    )?;
    let output = Arc::new(Mutex::new(Vec::new()));
    assert!(matches!(
        cross_boundary(
            &authority.owner,
            token,
            &invocation,
            lease,
            Arc::clone(&output)
        ),
        Err(BrowserServoError::Authority(FinalUseError::Revoked))
    ));
    assert_eq!(entries(&output), 0);
    assert_eq!(authority.owner.capacity()?.used_nonces, 1);
    Ok(())
}

#[test]
fn expiry_after_locked_entry_validation_is_rechecked_before_authority_enter() -> anyhow::Result<()>
{
    let fixture = Fixture::new()?;
    let invocation = fixture.invocation(/*nonce*/ 45, NOW + 30_000)?;
    let authority = BrowserServoHost::open(&fixture.config_path)?.authority;
    let lease = authority.gate.authenticate(
        &authority.owner,
        &authority.feed_path,
        &invocation.signed_grant,
    )?;
    let token = claim_final_use(
        &authority.owner,
        &invocation.signed_grant,
        &invocation.binding,
    )?;
    let lease = lease.check_claim(&token)?;
    *fixture.advance_after_clock.lock().expect("clock program") = Some(NOW + 30_000);
    let output = Arc::new(Mutex::new(Vec::new()));
    assert!(matches!(
        cross_boundary(
            &authority.owner,
            token,
            &invocation,
            lease,
            Arc::clone(&output)
        ),
        Err(BrowserServoError::Authority(FinalUseError::Expired))
    ));
    assert_eq!(entries(&output), 0);
    assert_eq!(authority.owner.capacity()?.used_nonces, 1);
    Ok(())
}
