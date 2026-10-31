use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

struct CountingTransport(Arc<AtomicUsize>);

impl BrowserServoTransport for CountingTransport {
    fn write_frame(&mut self, _bytes: &[u8]) -> Result<(), BrowserServoError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(BrowserServoError::Unavailable(
            "unexpected transport write".into(),
        ))
    }

    fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(BrowserServoError::Unavailable(
            "unexpected transport read".into(),
        ))
    }
}

#[test]
fn unavailable_final_use_store_cannot_create_a_browser_port_or_change_state()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let existing = temp.path().join("existing");
    let missing = temp.path().join("missing");
    std::fs::create_dir(&existing)?;
    std::fs::write(existing.join("authority.json"), b"existing authority")?;
    std::fs::write(existing.join("authority.claims"), b"existing claims")?;
    let io_count = Arc::new(AtomicUsize::new(0));
    for root in [&missing, &existing] {
        let port = FinalUseAuthority::open_state_dir(
            root,
            "browser-test-issuer".into(),
            SigningKey::from_bytes(&[7; 32]).verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: Default::default(),
            },
        )
        .map(|authority| {
            BrowserServoPort::new(authority, CountingTransport(Arc::clone(&io_count)))
        });
        assert_eq!(port.err(), Some(FinalUseError::UnsafeStateDirectory));
        assert_eq!(io_count.load(Ordering::SeqCst), 0);
        assert!(!missing.exists());
        assert_eq!(
            std::fs::read(existing.join("authority.json"))?,
            b"existing authority"
        );
        assert_eq!(
            std::fs::read(existing.join("authority.claims"))?,
            b"existing claims"
        );
        assert_eq!(std::fs::read_dir(&existing)?.count(), 2);
    }
    Ok(())
}

#[test]
fn read_call_construction_does_not_admit_an_effect_without_authority()
-> Result<(), Box<dyn std::error::Error>> {
    let call = BrowserServoCall::read(
        BrowserServoMethod::ObservePage,
        json!({"profileId":"profile.1"}),
    )?;
    assert_eq!(call.method, BrowserServoMethod::ObservePage);
    assert!(call.final_use.is_none());
    assert!(matches!(
        BrowserServoCall::read(
            BrowserServoMethod::NavigateOrAct,
            json!({"operationId":"operation.1"})
        ),
        Err(BrowserServoError::Invalid(_))
    ));
    Ok(())
}
