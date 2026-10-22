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
use test-only ephemeral native Ed25519 signing, private policy inputs and durable
acceptance boundaries. The frozen OpenSSH vectors retain independent format
coverage rather than deriving every expected result from that fixture signer.
No signing private key is retained in the repository.

The verifier's portability does not establish Windows filesystem ownership,
whole-workspace platform qualification, deployment acceptance or release
permission. Successful G5 verification remains evidence without acceptance
or release authority.

References: [OpenSSH signature protocol](https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.sshsig),
[OpenSSH verification implementation](https://github.com/openssh/openssh-portable/blob/master/sshsig.c),
and [ed25519-dalek 2.2.0 strict verification](https://docs.rs/ed25519-dalek/2.2.0/ed25519_dalek/struct.VerifyingKey.html#method.verify_strict).

### Windows custody candidate (not native-qualified)

The Windows adapter now applies the reviewed private-state owner/DACL snapshot
on the exact descriptor used for bounded input reads and revalidates that
snapshot against both the retained descriptor and a current pathname handle.
Final reparse, single-link and file-identity checks remain mandatory. Inputs do
not acquire a new private-parent requirement: a protected private input inside
an ordinary nonprivate parent can satisfy this contract, as on Unix.

Ownership is the process token's `TokenUser`; active thread impersonation and
any uncertain token-query result reject. The existing private-state allow-ACE
policy trusts that SID, LocalSystem, Builtin Administrators and Creator Owner.
SYSTEM/Administrators are privileged platform TCB, analogous in role to Unix
root, not arbitrary untrusted identities. Admission never rewrites an existing
owner or DACL and never creates an input or missing input parent.

Create-only outputs use an existing private immediate parent and an explicit
current-user, protected creation descriptor. The parent and newly created file
remain open through bounded readback, file/path identity checks and genuine
directory flushing. Flush failure is failure; cleanup addresses only the newly
created handle. Parent identity is compared independently of timestamps changed
by child creation. No all-ancestor private-mode or input-handle-through-crypto
promise is made. Optional assessment output remains supported, not silently
restricted to `None`.

These source changes do not establish native qualification. Cargo/Bazel
metadata must be generated, the complete original tests and new native custody
matrix must execute, and independent review must approve the exact successor
before Windows product enablement is accepted. New owner-mutation cases use the
explicit `windows-custody-privileged-tests` feature and require a separately
provisioned owner-assignment-capable fixture; attack setup failure is not a
passing rejection. No test or product code enables privileges for admission.
The V1 exact `/Volumes/T5` roots, replay owners and Unix-only sidecar locking
remain unchanged; Windows V1 release/replay support is not claimed.
