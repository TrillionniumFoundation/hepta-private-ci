// Public fixtures signed and independently verified by OpenSSH.
// No private key is retained. Tests exercise the existing Windows refusal.

pub(crate) const STATEMENT: &str = "canonical operator acceptance statement";
pub(crate) const ALLOWED_SIGNERS: &str = "operator@example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJoaEZJZo/lyHvT3IowyV2QwaCTEKEX8KnfiO0u1uOTK\n";
pub(crate) const FINGERPRINT: &str = "SHA256:ELCZGg0wrN3Fs8nzBbiNGhbW/e56t7za9dNGAhNUhQg";
pub(crate) const VALID_SIGNATURE: &str = "-----BEGIN SSH SIGNATURE-----\nU1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgmhoRklmj+XIe9PcijDJXZDBoJM\nQoRfwqd+I7S7W45MoAAAAiaGVwdGEtdm5leHQtb3BlcmF0b3ItYWNjZXB0YW5jZS12MQAA\nAAAAAAAGc2hhNTEyAAAAUwAAAAtzc2gtZWQyNTUxOQAAAEBvkS4yI1bUTDGllLhoHVm9Kt\nZzJBXyuDBjs2vqszAQjipPE46PcqEK+wHXcvA5Dd9Hf6miQB7u5SL4wlr+RnQO\n-----END SSH SIGNATURE-----\n";
pub(crate) const WRONG_NAMESPACE_SIGNATURE: &str = "-----BEGIN SSH SIGNATURE-----\nU1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgmhoRklmj+XIe9PcijDJXZDBoJM\nQoRfwqd+I7S7W45MoAAAAcaGVwdGEtb3BlcmF0b3ItYWNjZXB0YW5jZS12MQAAAAAAAAAG\nc2hhNTEyAAAAUwAAAAtzc2gtZWQyNTUxOQAAAEBBgqUCGrO2DQXgJx55VFc2DCtpJYt2ZY\nm1CEPAxmQZQvroRa4oaFpNk6URiE9QUuVNxTnupLt2osAejMm6uwwG\n-----END SSH SIGNATURE-----\n";
