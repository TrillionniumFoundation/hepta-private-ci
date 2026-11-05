//! Issuer expiry must fence policy succession while the registered writer lives.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn desktop_policy_issuer_expiry_is_half_open_with_a_live_writer() {
    for now in [99_999, 100_000, 100_001] {
        let mut f = Fixture::new();
        let proof = f.issuer.retained_writer_authorization(&f.writer).unwrap();
        // Rotate while the original issuer is still live. The new writer
        // legitimately outlives that issuer, so it cannot mask this boundary.
        f.clock.0.store(99_000, Ordering::SeqCst);
        let mut next_writer = f.writer.clone();
        next_writer.spawn_generation = 5;
        next_writer.owner_epoch = 3;
        next_writer.local_lease_generation = 3;
        next_writer.authority_lease.lease_id = "desktop-writer-long".into();
        next_writer.authority_lease.issued_at_unix_ms = 99_000;
        next_writer.authority_lease.expires_at_unix_ms = 110_000;
        f.registry
            .put_lease(next_writer.authority_lease.clone(), 0)
            .unwrap();
        f.issuer
            .rotate_writer_authorization(&f.writer, &proof, &next_writer)
            .unwrap();
        f.writer = next_writer;
        f.clock.0.store(now, Ordering::SeqCst);
        f.writer
            .with_live(&f.registry.verifier(), |_| Ok(()))
            .unwrap();

        let before = serde_json::to_value(f.state()).unwrap();
        let frontier = f.registry.frontier().unwrap();
        let key = f.issuer.trust_key().unwrap().verifying_key;
        let result = f.replace(&f.old, &f.next);
        if now < 100_000 {
            result.unwrap();
            let expected = f
                .next
                .policy()
                .policies(f.writer.registered_agent_id.as_str())
                .unwrap();
            assert_eq!(&f.state().policies[..2], &expected);
        } else {
            assert_eq!(result.unwrap_err().kind(), io::ErrorKind::PermissionDenied);
            assert_eq!(serde_json::to_value(f.state()).unwrap(), before);
        }
        assert_eq!(f.registry.frontier().unwrap(), frontier);
        assert_eq!(f.issuer.trust_key().unwrap().verifying_key, key);
    }
}
