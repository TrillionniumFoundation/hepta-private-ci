use super::FROZEN_PREFIX;
use super::MAX_FROZEN_BYTES;
use super::frozen_payload;
use codex_hepta_types::Digest32;

#[test]
fn frozen_purpose_rejects_legacy_decisions_partial_and_changed_sources() {
    let legacy = b"hepta.agentd.self-iteration-candidate.v1\0opaque";
    assert!(frozen_payload(legacy, Digest32::of_bytes(legacy)).is_err());
    assert!(frozen_payload(FROZEN_PREFIX, Digest32::of_bytes(FROZEN_PREFIX)).is_err());
    let mut full = FROZEN_PREFIX.to_vec();
    full.extend_from_slice(b"Root-validated-complete-source");
    let approved = Digest32::of_bytes(&full);
    assert!(frozen_payload(&full, approved).is_ok());
    full.push(1);
    assert!(frozen_payload(&full, approved).is_err());
    assert!(frozen_payload(&full, Digest32::ZERO).is_err());
    full.resize(usize::try_from(MAX_FROZEN_BYTES).unwrap() + 1, 0);
    assert!(frozen_payload(&full, Digest32::of_bytes(&full)).is_err());
}
