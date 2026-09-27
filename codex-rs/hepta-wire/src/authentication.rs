//! Incremental standard HMAC; authenticated tags use the crate's constant-time verifier.

use codex_hepta_types::Digest32;
use hmac::Hmac;
use hmac::Mac;
use sha2::Sha256;

use crate::AuthenticatedSessionError;

fn state(key: &[u8; 32], parts: &[&[u8]]) -> Result<Hmac<Sha256>, AuthenticatedSessionError> {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(key).map_err(|_| AuthenticatedSessionError::MacKeyLength)?;
    for part in parts {
        mac.update(part);
    }
    Ok(mac)
}

pub(crate) fn hmac_sha256(
    key: &[u8; 32],
    parts: &[&[u8]],
) -> Result<Digest32, AuthenticatedSessionError> {
    Ok(Digest32::from_array(
        state(key, parts)?.finalize().into_bytes().into(),
    ))
}

pub(crate) fn verify_mac(key: &[u8; 32], parts: &[&[u8]], tag: &[u8]) -> bool {
    state(key, parts).is_ok_and(|mac| mac.verify_slice(tag).is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rfc4231_vector_is_exact_and_modified_tags_reject() -> Result<(), Box<dyn std::error::Error>>
    {
        // A 20-byte key padded with zeroes has the same HMAC block key.
        let mut key = [0_u8; 32];
        key[..20].fill(0x0b);
        let digest = hmac_sha256(&key, &[b"Hi ", b"There"])?;
        assert_eq!(
            digest.to_string(),
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        );
        assert!(verify_mac(&key, &[b"Hi There"], digest.as_array()));
        let mut corrupted = digest.into_array();
        corrupted[31] ^= 1;
        assert!(!verify_mac(&key, &[b"Hi There"], &corrupted));
        assert!(!verify_mac(&key, &[b"Hi There"], &corrupted[..31]));
        Ok(())
    }
}
