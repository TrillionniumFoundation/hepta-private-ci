# Remaining aws-config / P-256 dependency blocker

Status: concrete implementation candidate identified; not implemented or qualified.
`credentials-login` remains enabled. No product authorization path is removed.

## Published source now verified

The exact locked `aws-config 1.8.12` archive was downloaded from the official
registry and its SHA-256 matched the pinned index and Cargo.lock:
`96571e6996817bf3d58f6b569e4b9fd2e9d2fcf9f7424eed07b2ce9bb87535e5`.
Only archive parsing and source inspection occurred. The package's VCS receipt
identifies `awslabs/aws-sdk-rust` commit
`f031610a8cbb4ac2dac3229bfaeaa88182787ab4`, path `sdk/aws-config`.
`aws-config-1.8.12-static-review.json` retains source-file hashes and relevant API
lines without copying private-key material or claiming an exploit demonstration.

The locked release has optional `p256 = "0.13.2"`, optional
`rand = "0.8.5"` with `std`/`std_rng`, and the existing login feature activates
both. Its DPoP implementation converts a P-256 private key into a signing key,
seeds `rand::rngs::StdRng::from_entropy`, signs with `sign_with_rng`, and serializes
the raw ECDSA signature into the ES256 JWT. It parses persisted keys with
`SecretKey::from_sec1_pem`. These observations now apply to the checksummed
published crate, rather than only the current upstream branch.

## Why a lock-only update cannot close this finding

The current old subgraph requires `elliptic-curve ^0.13` and `crypto-bigint ^0.5`.
Adding a second fixed bigint copy leaves the vulnerable dependency installed.
The published `aws-config 1.13.0` index record still requires `p256 ^0.13.2`, so a
routine AWS version bump does not remove the old subgraph.

A real published candidate chain is:

`p256 0.14.0 → elliptic-curve 0.14.3 → crypto-bigint 0.7.10`.

The published P-256 0.14.0 requirement is `elliptic-curve ^0.14.1`, which permits
0.14.3; the latter's bigint requirement is `^0.7.8`, which permits 0.7.10. The
inspected index marks bigint 0.7.6 and 0.7.8 as yanked. The 0.7.9 release explains
the older 0.7.x yanks and additional timing/trait corrections. A candidate must
therefore resolve a currently usable fixed version, not force the advisory's
minimum into an incompatible old graph. The complete selected official records
are in `upstream-versions.json`.

## Minimum provider migration surface

| API or dependency | Existing release | Candidate change |
| --- | --- | --- |
| Curve dependency | `p256 ^0.13.2` | Change the provider's own requirement to `^0.14.0`; resolve and inspect the entire new curve subgraph. |
| Randomness interface | `rand 0.8.5` supplies rand_core 0.6 traits | ECDSA 0.17/signature 3 use rand_core 0.10; the old `StdRng` cannot be passed unchanged. |
| Narrow RNG adapter | No getrandom dependency in aws-config | Add optional `getrandom 0.4.3` with `sys_rng`, enabled only by the existing login feature. `getrandom::SysRng` implements the required fallible `TryCryptoRng`. Retain existing rand dependency/features for any other provider uses until all callers are reviewed. |
| Signing operation | `sign_with_rng` can panic on failure | Use `try_sign_with_rng` and map the error into the existing `LoginTokenError`; retain randomized ES256. |
| Public point export | `ToEncodedPoint` and `to_encoded_point(false)` | Prefer `ToSec1Point` and `to_sec1_point(false)`; the old names are deprecated compatibility stubs. Preserve uncompressed X/Y coordinates and base64url encoding. |
| Key decoding | SEC1 PEM via `SecretKey::from_sec1_pem` | The inspected new curve source retains this API; keep the `pem` feature and existing persisted-key format. Validate old token/key fixtures on the new implementation. |
| Signing-key conversion | `SigningKey::from(&SecretKey)` | ECDSA 0.17 retains this conversion. Preserve raw 64-byte ES256 signature serialization and independent verification. |

The narrow signing replacement, subject to hosted compilation and tests, is:

```rust
let signing_key = SigningKey::from(private_key);
let mut rng = getrandom::SysRng;
let signature: Signature = signing_key
    .try_sign_with_rng(&mut rng, message.as_bytes())
    .map_err(|error| LoginTokenError::other("DPoP signing failed", Some(error.into())))?;
```

This snippet is a source-reviewed proposal, not a reported successful build. It
does not install a provider fork or change authentication policy.

## Supply-chain and acceptance requirements

The preferred route is an upstream AWS release that actually adopts the new curve
chain. No such published release was found in this review. If work proceeds with
a maintained provider patch, pin a separately reviewed fork commit or a fully
checksummed local vendor source of the exact existing provider, change only the
necessary dependency/API surface, and retain its license and provenance. Do not
give a forked provider an upstream qualification label.

The root Cargo patch and Bazel source graph need to refer to that exact same
source. Generate both locks with real tools on the hosted path and confirm that
the old bigint/curve branch is absent, including transitive consumers. Preserve
default features, login, profile selection, credential refresh, expiry handling,
and existing non-login credential providers. A fresh full RustSec scan is required
because the candidate introduces a new transitive dependency generation.

Hosted qualification must cover DPoP signing plus independent ES256 verification,
existing SEC1 PEM/key-cache fixtures, malformed keys, wrong-curve rejection,
randomness/signing failures, and unchanged token claims and signature encoding.
It also needs the provider's login refresh/expiry tests and the project's actual
AWS authorization tests on the supported native targets. A successful library
signature test alone does not prove the account/login integration works.

Official implementation sources and their SHA-256 identities are recorded in
`api-source-identities.json`. They include
[AWS DPoP](https://github.com/smithy-lang/smithy-rs/blob/c97559a2cc78ef17e534b2e88c08046a8f473110/aws/rust-runtime/aws-config/src/login/dpop.rs),
[ECDSA 0.17](https://github.com/RustCrypto/signatures/blob/ecdsa/v0.17.0/ecdsa/src/signing.rs),
[SEC1 API](https://github.com/RustCrypto/traits/blob/8fffd5b1e6c5b9272b18efa967c55a8bd78d0d9b/elliptic-curve/src/sec1.rs), and
[getrandom 0.4.3 SysRng](https://github.com/rust-random/getrandom/blob/v0.4.3/src/sys_rng.rs).
