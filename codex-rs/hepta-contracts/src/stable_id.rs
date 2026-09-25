use crate::Sha256Digest;

pub(crate) fn parse_prefixed_sha256_id(
    value: impl Into<String>,
    prefix: &str,
    label: &str,
) -> Result<String, String> {
    let value = value.into();
    let Some(digest) = value.strip_prefix(prefix) else {
        return Err(format!("{label} id must start with {prefix}"));
    };
    Sha256Digest::parse(digest.to_string())?;
    Ok(value)
}
