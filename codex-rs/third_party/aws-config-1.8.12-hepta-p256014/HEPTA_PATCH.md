# aws-config 1.8.12: Hepta P-256 compatibility patch

This is an explicitly patched Apache-2.0 copy of the official `aws-config`
1.8.12 source. It is not an AWS release. The crate keeps its original package
identity for `[patch.crates-io]`, resides in the separate
`aws-config-1.8.12-hepta-p256014` directory, and sets `publish = false`.

The original crate is from
`https://static.crates.io/crates/aws-config/aws-config-1.8.12.crate`, SHA-256
`96571e6996817bf3d58f6b569e4b9fd2e9d2fcf9f7424eed07b2ce9bb87535e5`.
Its recorded upstream VCS revision is
`f031610a8cbb4ac2dac3229bfaeaa88182787ab4`, path `sdk/aws-config` in
`awslabs/aws-sdk-rust`. The original LICENSE, copyright notices,
`Cargo.toml.orig`, published source, and all original test fixtures are retained.
The test-data, integration-test and fuzz directories omitted from the published
crate were retrieved from that exact VCS revision and verified against Git blob
identities. Their public dummy credentials and conformance keys are upstream
test data, never deployment credentials.

The original standalone `Cargo.lock` remains in the source archive as provenance
and is not installed here. This package is an explicit product workspace member
and uses the one hosted-generated workspace lock. No Cargo checksum is edited.

## Deliberate changes

The optional P-256 dependency moves from 0.13.2 to 0.14.0. The optional rand
dependency moves from 0.8.5 to 0.10.3, retaining `std` and `std_rng` and adding
`sys_rng`. All original aws-config feature definitions remain byte-equivalent
as TOML values, including `credentials-login`, `default`, and `sso`.

DPoP uses `ToSec1Point::to_sec1_point`, the renamed public-point API. The private
signing function accepts a fallible `TryCryptoRng`; production supplies the OS
`SysRng` and calls the real `try_sign_with_rng`. A signing/entropy failure returns
`LoginTokenError` with a generic diagnostic and no token. The success path still
emits ES256, raw 64-byte signatures, base64url without padding, and the original
JWK and DPoP claims. SEC1 key parsing, identity caches, provider order, refresh,
expiry, endpoint behavior and SSO remain the original upstream code.

The UUID JTI generation remains upstream `Uuid::new_v4`; this patch does not
claim that every entropy-failure path throughout the SDK is fallible. It also
does not prove constant-time execution for every compiler/CPU or erase all
possible stack copies.

Three new native tests use real P-256 signing and the independent ring ES256
verifier, reject message/signature/key substitutions, exercise RNG failure,
and check malformed-key diagnostics. The failure RNG never emits bytes and is
not a successful-crypto mock. The original four DPoP tests and all other provider
tests remain present. The added ring dev dependency permits independent
verification even when SSO is not selected for a dedicated login-only test.

The Bazel library explicitly retains the six production features and package
version, and includes the original Markdown compile-time data. The original AWS
provider suite runs via Cargo in the workspace; first-party AWS auth tests and
the full product qualification remain unchanged under Cargo and Bazel.

Repository formatting is generated only on the hosted runner, scoped to this
package. Any resulting formatting-only source changes must be reviewed alongside
the actual Cargo/Bazel locks before import. A resolver artifact is a proposal,
not a passing result for the final committed source.
