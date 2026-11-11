//! Every final consumer boundary retains the same authenticated claim head.
use super::*;
use pretty_assertions::assert_eq;

#[derive(Clone, Copy, Debug)]
enum Entry {
    Token,
    Owner,
    Consumer,
    ConsumerWitness,
    Effect,
    AsyncEffect,
    Dispatch,
    DispatchWitness,
}

const ENTRIES: [Entry; 8] = [
    Entry::Token,
    Entry::Owner,
    Entry::Consumer,
    Entry::ConsumerWitness,
    Entry::Effect,
    Entry::AsyncEffect,
    Entry::Dispatch,
    Entry::DispatchWitness,
];

fn enter(
    entry: Entry,
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    binding: &FinalUseBinding,
    called: &mut bool,
) -> Result<(), FinalUseError> {
    match entry {
        Entry::Token => token.enter(binding).map(|_| *called = true),
        Entry::Owner => authority
            .enter_verified_use(token, binding)
            .map(|_| *called = true),
        Entry::Consumer => authority.with_verified_use(token, binding, || *called = true),
        Entry::ConsumerWitness => {
            deliver_final_use_with_witness(authority, token, binding, || *called = true).map(|_| ())
        }
        Entry::Effect => authority.with_verified_effect(token, binding, || *called = true),
        Entry::AsyncEffect => {
            let mut effect = Box::pin(authority.with_verified_use_async(token, binding, || {
                *called = true;
                std::future::ready(())
            }));
            match effect
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
            {
                Poll::Ready(result) => result,
                Poll::Pending => panic!("ready effect must finish during the first poll"),
            }
        }
        Entry::Dispatch => authority.with_dispatch_boundary(token, binding, || *called = true),
        Entry::DispatchWitness => {
            dispatch_final_use_with_witness(authority, token, binding, |_| *called = true)
                .map(|_| ())
        }
    }
}

#[test]
fn pq_final_use_all_entries_require_the_exact_claimed_head() -> PqTestResult {
    for entry in ENTRIES {
        let fixture = pq_fixture()?;
        let binding = &fixture.signed.grant.binding;
        let token = fixture.authority.claim(&fixture.signed, binding)?;
        let mut head = fixture.authority.revocation_head()?;
        head.revision += 1;
        fixture.authority.update_revocations(head)?;

        let mut called = false;
        assert_eq!(
            enter(entry, &fixture.authority, token, binding, &mut called),
            Err(FinalUseError::StaleRevocationHead),
            "{entry:?}"
        );
        assert!(!called, "{entry:?} must refuse before consumer entry");
        assert_eq!(
            fixture
                .authority
                .claim(&fixture.signed, binding)
                .unwrap_err(),
            FinalUseError::AlreadyClaimed,
            "{entry:?} must preserve the consumed nonce"
        );

        // A new signed claim at the current head can use the same boundary.
        // Refusing the old token must not retain an active-effect fence.
        let mut fresh = fixture.signed.clone();
        fresh.grant.grant_id = "fresh-pq-grant".into();
        fresh.grant.nonce = [4; 32];
        fresh.signature = fixture
            .key
            .sign_exact_message(&fresh.grant.signing_bytes()?)?
            .to_vec();
        let token = fixture.authority.claim(&fresh, binding)?;
        assert_eq!(
            enter(entry, &fixture.authority, token, binding, &mut called),
            Ok(()),
            "{entry:?}"
        );
        assert!(called, "{entry:?} must admit the fresh current-head claim");
        let mut next = fixture.authority.revocation_head()?;
        next.revision += 1;
        fixture.authority.update_revocations(next)?;
        assert_eq!(fixture.authority.capacity()?.used_nonces, 2);
    }
    Ok(())
}

#[test]
fn pq_final_use_all_entries_keep_explicit_revocation_precedence() -> PqTestResult {
    for entry in ENTRIES {
        let fixture = pq_fixture()?;
        let binding = &fixture.signed.grant.binding;
        let token = fixture.authority.claim(&fixture.signed, binding)?;
        let mut head = fixture.authority.revocation_head()?;
        head.revision += 1;
        head.revoked_grant_ids
            .insert(fixture.signed.grant.grant_id.clone());
        fixture.authority.update_revocations(head)?;

        let mut called = false;
        assert_eq!(
            enter(entry, &fixture.authority, token, binding, &mut called),
            Err(FinalUseError::Revoked),
            "{entry:?}"
        );
        assert!(!called, "{entry:?} must refuse before consumer entry");
        assert_eq!(fixture.authority.capacity()?.used_nonces, 1);
    }
    Ok(())
}
