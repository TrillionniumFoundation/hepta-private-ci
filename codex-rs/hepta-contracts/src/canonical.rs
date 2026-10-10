use sha2::Digest;
use sha2::Sha256;

use crate::Sha256Digest;

pub(crate) fn length_delimited_sha256<I, S>(parts: I) -> Sha256Digest
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut hasher = Sha256::new();
    for part in parts {
        let part = part.as_ref();
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    Sha256Digest::from_sha256_output(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::length_delimited_sha256;

    #[test]
    fn length_delimited_sha256_counts_utf8_bytes() {
        assert_eq!(
            length_delimited_sha256(["é"]).as_str(),
            "1d9b2f68e31ef2b6730c67d7729ca6a523e7f19d8987ca7c72eb93cb3bb9d979"
        );
    }
}
