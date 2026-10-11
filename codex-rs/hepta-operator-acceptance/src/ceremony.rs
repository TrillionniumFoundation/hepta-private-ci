use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use rand::TryRngCore;
use rand::rngs::OsRng;

use crate::AcceptanceError;
use crate::durable::ensure_disjoint_roots;
use crate::durable::secure_canonical_file_path;
use crate::durable::secure_root;

const EXACT_QUALIFICATION_ROOT: &str =
    "/Volumes/T5/hepta-vnext/artifacts/receipts/qualification-3110c5aba5-final-20260810T192902Z";
const EXACT_PRODUCT_AUDIT_ROOT: &str =
    "/Volumes/T5/hepta-vnext/artifacts/audits/2026-08-09-frozen-product-2f704-live-build";
const ACCEPTANCE_STORE_PARENT: &str = "/Volumes/T5/hepta-vnext/artifacts/acceptances";

pub(crate) struct ValidatedRoots {
    pub allowed_signers: PathBuf,
    pub product_audit: PathBuf,
    pub qualification: PathBuf,
    pub sidecar: PathBuf,
    pub trust_policy: PathBuf,
}

impl ValidatedRoots {
    pub(crate) fn load(
        qualification: &Path,
        product_audit: &Path,
        sidecar: &Path,
        allowed_signers: &Path,
        trust_policy: &Path,
    ) -> Result<Self, AcceptanceError> {
        let qualification = secure_root(qualification, "qualification receipt root")?;
        let product_audit = secure_root(product_audit, "frozen product audit root")?;
        let sidecar = secure_root(sidecar, "operator acceptance sidecar root")?;
        validate_v1_paths(&qualification, &product_audit, &sidecar)?;
        ensure_disjoint_roots(&sidecar, &qualification, &product_audit)?;
        let allowed_signers =
            secure_canonical_file_path(allowed_signers, "external allowed_signers")?;
        let trust_policy = secure_canonical_file_path(trust_policy, "external trust policy")?;
        for external in [&allowed_signers, &trust_policy] {
            if external.starts_with(&sidecar)
                || external.starts_with(&qualification)
                || external.starts_with(&product_audit)
            {
                return Err(invalid(
                    "external trust material must be outside packet, sidecar, and evidence roots",
                ));
            }
        }
        if allowed_signers == trust_policy {
            return Err(invalid(
                "allowed_signers and trust policy must be distinct files",
            ));
        }
        Ok(Self {
            allowed_signers,
            product_audit,
            qualification,
            sidecar,
            trust_policy,
        })
    }
}

fn validate_v1_paths(
    qualification: &Path,
    product_audit: &Path,
    sidecar: &Path,
) -> Result<(), AcceptanceError> {
    if qualification != Path::new(EXACT_QUALIFICATION_ROOT)
        || product_audit != Path::new(EXACT_PRODUCT_AUDIT_ROOT)
    {
        return Err(invalid(
            "V1 requires the exact canonical qualification and product-audit roots",
        ));
    }
    let acceptance_parent = Path::new(ACCEPTANCE_STORE_PARENT);
    if sidecar == acceptance_parent || !sidecar.starts_with(acceptance_parent) {
        return Err(invalid(
            "V1 sidecar must be a strict child of the canonical acceptance store",
        ));
    }
    Ok(())
}

pub(crate) fn reject_existing(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    if path_present(path)? {
        return Err(invalid(format!("sidecar already contains a {label}")));
    }
    Ok(())
}

pub(crate) fn path_present(path: &Path) -> Result<bool, AcceptanceError> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

pub(crate) fn trusted_time() -> Result<u64, AcceptanceError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| invalid("trusted host clock is before the Unix epoch"))?
        .as_secs();
    if seconds == 0 {
        return Err(invalid("trusted host clock returned zero"));
    }
    Ok(seconds)
}

pub(crate) fn random_hex<const N: usize>() -> Result<String, AcceptanceError> {
    let mut bytes = [0_u8; N];
    OsRng
        .try_fill_bytes(&mut bytes)
        .map_err(|error| invalid(format!("OS randomness unavailable: {error}")))?;
    Ok(hex(&bytes))
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(char::from(DIGITS[usize::from(byte >> 4)]));
        encoded.push(char::from(DIGITS[usize::from(byte & 0x0f)]));
    }
    encoded
}

pub(crate) fn nonce_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && value.bytes().any(|byte| byte != b'0')
}

pub(crate) fn path_string(path: &Path) -> Result<String, AcceptanceError> {
    path.to_str()
        .map(str::to_string)
        .ok_or_else(|| invalid("sidecar path is not UTF-8"))
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::ACCEPTANCE_STORE_PARENT;
    use super::EXACT_PRODUCT_AUDIT_ROOT;
    use super::EXACT_QUALIFICATION_ROOT;
    use super::validate_v1_paths;

    #[test]
    fn v1_paths_are_exact_and_sidecar_is_a_strict_child() {
        let qualification = Path::new(EXACT_QUALIFICATION_ROOT);
        let product = Path::new(EXACT_PRODUCT_AUDIT_ROOT);
        let valid_sidecar = Path::new(ACCEPTANCE_STORE_PARENT).join("operator-acceptance-test");
        validate_v1_paths(qualification, product, &valid_sidecar).expect("exact V1 paths");
        assert!(
            validate_v1_paths(Path::new("/copied/qualification"), product, &valid_sidecar).is_err()
        );
        assert!(
            validate_v1_paths(qualification, Path::new("/copied/product"), &valid_sidecar).is_err()
        );
        assert!(
            validate_v1_paths(qualification, product, Path::new(ACCEPTANCE_STORE_PARENT),).is_err()
        );
        assert!(validate_v1_paths(qualification, product, Path::new("/tmp/copied-store")).is_err());
    }
}
