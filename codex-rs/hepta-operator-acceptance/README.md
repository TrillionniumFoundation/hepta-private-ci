# Operator acceptance: native SSHSIG verification

## Ownership and trust

`trust::TrustAnchor::verify_bytes` and `g5_trust::assess_signature` share
`sshsig::verify_ed25519`. This is a verifier for the existing externally pinned
single raw-Ed25519 profile, not a new authority issuer or a general SSH trust
store. Existing policy digests, principal selection, revocation, validity
windows, nonce consumption and durable receipt checks remain with their owners.

Both callers retain the privately loaded `allowed_signers` bytes. Verification
rederives the selected principal's key fingerprint from those bytes and rejects
any disagreement with the reported binding. Mutable receipt metadata therefore
cannot replace the pinned signing key or relabel its principal. An embedded
public key or a successfully self-signed packet cannot establish its own trust.

## Wire profile and resource bounds

The implementation follows OpenSSH's `PROTOCOL.sshsig` and
`sshsig_wrap_verify`, with the existing LF-delimited armor envelope and a
4 KiB packet limit. Persisted base64 input is bounded before decoding; decoded
armor is still checked against the packet limit. Every binary string length is
checked against the remaining input, including nested public-key and signature
records. Trailing binary data, unsupported algorithms and weak Ed25519 keys are
rejected. Verification uses `ed25519-dalek::VerifyingKey::verify_strict`.

The namespace must match the caller's nonempty namespace exactly. Message
hashing supports SHA-256 and SHA-512. The statement is hashed without copying it
into the signed packet; its input bound remains the calling owner's obligation.
The private profile accepts only raw Ed25519 keys, not certificates, RSA keys,
multiple signers or `allowed_signers` options.

For compatibility, the version check retains OpenSSH's acceptance of versions
zero and one and rejection of higher versions. OpenSSH currently ignores the
wire reserved field and verifies an empty reserved string. The native verifier
preserves that behavior: reserved bytes must never be interpreted as signed
policy, tags, authority or release permission.

The original armored signature digest and base64 representation are retained in
receipts; verification does not rewrite previously stored signature identity.
No subprocess, inherited descriptor or temporary verification file is required.

## Verification and platform limits

From the repository root:

```sh
just test -p codex-hepta-operator-acceptance --lib --locked
just clippy -p codex-hepta-operator-acceptance --lib --locked
```

`sshsig_tests.rs` contains independently generated OpenSSH SHA-256/SHA-512
fixtures, a second legitimate signer, truncation and length-bound probes,
namespace/hash substitution, weak-key and malformed-signature cases. These
in-memory tests do not need OpenSSH or a Unix host. Existing trust and G5 tests
also exercise live OpenSSH signing, private policy inputs and durable acceptance
boundaries. No signing private key is retained in the repository.

The verifier's portability does not establish Windows filesystem ownership,
whole-workspace platform qualification, deployment acceptance or release
permission. Successful G5 verification remains evidence without acceptance
or release authority.

References: [OpenSSH signature protocol](https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.sshsig),
[OpenSSH verification implementation](https://github.com/openssh/openssh-portable/blob/master/sshsig.c),
and [ed25519-dalek 2.2.0 strict verification](https://docs.rs/ed25519-dalek/2.2.0/ed25519_dalek/struct.VerifyingKey.html#method.verify_strict).
