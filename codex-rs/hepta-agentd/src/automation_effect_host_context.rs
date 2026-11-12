//! Original provider context, kept separate from the stable operation key.

use codex_hepta_contracts::Sha256Digest;

pub(super) fn digest(
    kind: &str,
    scope: &str,
    destination: &str,
    contract: &Sha256Digest,
    verifying_key: &[u8; 32],
) -> Sha256Digest {
    let mut bytes = b"hepta.agentd.effect-provider-context.v1\0".to_vec();
    for field in [
        kind.as_bytes(),
        scope.as_bytes(),
        destination.as_bytes(),
        contract.as_str().as_bytes(),
        verifying_key.as_slice(),
    ] {
        bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        bytes.extend_from_slice(field);
    }
    Sha256Digest::for_bytes(&bytes)
}
