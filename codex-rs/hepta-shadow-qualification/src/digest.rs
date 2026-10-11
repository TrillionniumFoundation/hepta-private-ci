use sha2::Digest;
use sha2::Sha256;

pub(crate) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn framed_digest<'a>(
    domain: &[u8],
    fields: impl IntoIterator<Item = &'a [u8]>,
) -> String {
    let mut preimage = Vec::new();
    preimage.extend_from_slice(&(domain.len() as u64).to_be_bytes());
    preimage.extend_from_slice(domain);
    for field in fields {
        preimage.extend_from_slice(&(field.len() as u64).to_be_bytes());
        preimage.extend_from_slice(field);
    }
    sha256(&preimage)
}
