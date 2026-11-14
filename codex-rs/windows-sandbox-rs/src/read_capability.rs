use crate::path_normalization::canonical_path_key;
use crate::path_normalization::canonicalize_path;
use crate::setup::SandboxSetupRequest;
use crate::setup::SetupRootOverrides;
use crate::setup::build_payload_roots;
use anyhow::Result;
use std::path::Path;
use windows_sys::Win32::Security::Cryptography::BCRYPT_SHA256_ALGORITHM;
use windows_sys::Win32::Security::Cryptography::BCryptCloseAlgorithmProvider;
use windows_sys::Win32::Security::Cryptography::BCryptHash;
use windows_sys::Win32::Security::Cryptography::BCryptOpenAlgorithmProvider;

/// Identifies a read root independently of CODEX_HOME and writable-root caps.
///
/// Stable, domain-separated SHA-256 identities let setup reuse exact read grants
/// for platform roots. Only roots in the current request enter the child token.
/// The setup helper grants these SIDs READ/EXECUTE and never write or delete.
pub fn read_cap_sid_for_root(root: &Path) -> Result<String> {
    let canonical = canonicalize_path(root);
    anyhow::ensure!(
        canonical.to_str().is_some(),
        "read capability root must have a lossless Unicode path"
    );
    let key = canonical_path_key(&canonical);
    let mut input = b"codex/windows/read-capability/v1\0".to_vec();
    input.extend_from_slice(key.as_bytes());
    let input_len = input.len().try_into()?;
    let mut algorithm = std::ptr::null_mut();
    let status = unsafe {
        BCryptOpenAlgorithmProvider(
            &mut algorithm,
            BCRYPT_SHA256_ALGORITHM,
            std::ptr::null(),
            /*dwflags*/ 0,
        )
    };
    anyhow::ensure!(
        status >= 0,
        "open read-capability hash provider failed: {status:#x}"
    );
    let mut digest = [0u8; 32];
    let hash = unsafe {
        BCryptHash(
            algorithm,
            std::ptr::null(),
            /*cbsecret*/ 0,
            input.as_ptr(),
            input_len,
            digest.as_mut_ptr(),
            digest.len() as u32,
        )
    };
    let close = unsafe {
        BCryptCloseAlgorithmProvider(algorithm, /*dwflags*/ 0)
    };
    anyhow::ensure!(hash >= 0, "read-capability root hash failed: {hash:#x}");
    anyhow::ensure!(
        close >= 0,
        "close read-capability hash provider failed: {close:#x}"
    );
    let [a, b, c, d] = std::array::from_fn(|index| {
        let offset = index * 4;
        u32::from_le_bytes([
            digest[offset],
            digest[offset + 1],
            digest[offset + 2],
            digest[offset + 3],
        ])
    });
    Ok(format!("S-1-5-21-{a}-{b}-{c}-{d}"))
}

pub(crate) fn read_cap_sids_for_setup(
    request: &SandboxSetupRequest<'_>,
    overrides: &SetupRootOverrides,
) -> Result<Vec<String>> {
    if !request
        .permissions
        .uses_write_capabilities_for_cwd(request.command_cwd, request.env_map)
    {
        return Ok(Vec::new());
    }
    let (roots, _) = build_payload_roots(request, overrides);
    let mut sids = roots
        .iter()
        .map(|root| read_cap_sid_for_root(root))
        .collect::<Result<Vec<_>>>()?;
    sids.sort();
    sids.dedup();
    Ok(sids)
}

#[cfg(test)]
#[path = "read_capability_tests.rs"]
mod tests;
