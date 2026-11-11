//! Original issuer persistence tests. These local fixtures do not authenticate
//! a production human; the actual Root UI lane supplies that provenance.
use super::super::tests::body;
use super::super::tests::identity;
use super::super::tests::issuer;
use super::*;
use codex_hepta_contracts::SystemAuthorityClock;

fn human(owner: &AgentdIdentity) -> io::Result<TextHumanBinding> {
    Ok(TextHumanBinding {
        principal_id: "test-human".into(),
        session_id: "test-original-login".into(),
        permission_revision: 1,
        expires_at_ms: SystemAuthorityClock
            .now_unix_ms()
            .map_err(io::Error::other)?
            + 5000,
        route: AgentdTextSessionConfig {
            agent_id: owner.agent_id.clone(),
            spawn_generation: owner.spawn_generation,
            control_socket: owner.control_socket.clone(),
            codex_home: owner.home_root.clone(),
            thread_id: body().thread_id,
            app_server_session_id: "test-original-session".into(),
        },
    })
}

#[test]
fn generic_signature_cannot_upgrade_into_human_provenance_or_consume_another_sequence()
-> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let owner = identity(temp.path());
    let issuer = issuer(&temp.path().join("issuer"), &owner);
    let human = human(&owner)?;
    let signed = issuer.text(
        &owner,
        "same-public-namespace:1",
        body(),
        TextIssuerOperation::Sign,
    )?;
    let before = issuer.store.load(STATE_OWNER).map_err(io::Error::other)?;
    assert!(
        issuer
            .verify_retained_human_text(&owner, &signed, &human, "same-public-namespace")
            .is_err()
    );
    assert!(
        issuer
            .text_until(
                &owner,
                "same-public-namespace:1",
                body(),
                TextIssuerOperation::Sign,
                None,
                Some(&human)
            )
            .is_err()
    );
    assert!(issuer.store.load(STATE_OWNER).map_err(io::Error::other)? == before);
    Ok(())
}

#[test]
fn exact_human_binding_survives_reopen_and_readback_never_changes_the_original_cas()
-> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let owner = identity(temp.path());
    let path = temp.path().join("issuer");
    let original = issuer(&path, &owner);
    let human = human(&owner)?;
    let signed = original.text_until(
        &owner,
        "human:1",
        body(),
        TextIssuerOperation::Sign,
        None,
        Some(&human),
    )?;
    assert!(signed.expires_at_ms <= human.expires_at_ms);
    drop(original);
    let original = DeploymentFinalUseIssuer::open(&path, Arc::new(SystemAuthorityClock))?;
    let before = original.store.load(STATE_OWNER).map_err(io::Error::other)?;
    original.verify_retained_human_text(&owner, &signed, &human, "human")?;
    let mut changed_session = human.clone();
    changed_session.session_id = "another-login".into();
    assert!(
        original
            .verify_retained_human_text(&owner, &signed, &changed_session, "human")
            .is_err()
    );
    let mut changed_permission = human.clone();
    changed_permission.permission_revision += 1;
    assert!(
        original
            .verify_retained_human_text(&owner, &signed, &changed_permission, "human")
            .is_err()
    );
    let mut changed_call = signed.clone();
    changed_call.body.text.push('!');
    assert!(
        original
            .verify_retained_human_text(&owner, &changed_call, &human, "human")
            .is_err()
    );
    assert!(
        original
            .verify_retained_human_text(&owner, &signed, &human, "another-namespace")
            .is_err()
    );
    assert!(original.store.load(STATE_OWNER).map_err(io::Error::other)? == before);
    Ok(())
}
