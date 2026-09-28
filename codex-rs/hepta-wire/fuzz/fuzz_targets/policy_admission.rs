#![no_main]

mod managed_fixture;

use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::SessionLifecycleState;
use libfuzzer_sys::fuzz_target;
use managed_fixture::Outcome;
use managed_fixture::envelope;
use managed_fixture::owner;
use managed_fixture::session;

fn exercise(data: &[u8]) -> Outcome {
    let valid = envelope(data, "producer.managed-fuzz")?;
    let denied = envelope(data, "producer.not-admitted")?;
    let session = session(1)?;
    assert_eq!(session.decode_frame(&valid.encode())?, valid);
    // The digest is recomputed correctly: rejection must be policy admission,
    // not merely corruption detection. No record or effect authority is minted.
    assert!(session.decode_frame(&denied.encode()).is_err());
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    assert!(sender.seal_envelope(&denied).is_err());
    assert_eq!(sender.state(), SessionLifecycleState::Poisoned);
    assert!(sender.seal_envelope(&valid).is_err());
    let mut receiver = owner(1, SessionEndpoint::Responder)?;
    match receiver.open_record(data) {
        Ok(_) => assert_eq!(receiver.state(), SessionLifecycleState::Active),
        Err(_) => assert_eq!(receiver.state(), SessionLifecycleState::Poisoned),
    }
    Ok(())
}

fuzz_target!(|data: &[u8]| {
    assert!(exercise(data).is_ok(), "policy fixture or invariant failed");
});
