//! Arithmetic mode supplied by actual compiler and artifact admission.
#[cfg(not(any(
    codex_hia_unified_diff_policy = "0",
    codex_hia_unified_diff_policy = "1"
)))]
compile_error!("hia-native unified diff requires an admitted same-policy compiler receipt");

#[cfg(codex_hia_unified_diff_policy = "0")]
pub(crate) const ARITHMETIC_POLICY: u64 = 0;
#[cfg(codex_hia_unified_diff_policy = "1")]
pub(crate) const ARITHMETIC_POLICY: u64 = 1;
