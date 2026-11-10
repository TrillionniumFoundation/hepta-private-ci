# Frozen joint-candidate Syn edge qualification

## Qualification source-path continuation

The #5771 head added the reviewed helper and this README, but the preparation
code's exact proposal-file allowlist omitted both paths. Its source gate would
reject that head before download or candidate mutation. Add precisely those two
paths to the existing set; all pinned inputs and the rejection of any other
source change remain enforced. The workflow and lock-edge helper are unchanged.

The original five preparation tests pass with an extended real temporary Git
history that first includes both allowed additions plus an unrelated file,
proves rejection without an evidence/vendor directory, then removes only the
unrelated file and completes the original fixture preparation. With the old
allowlist restored, that positive continuation fails at the original source
gate. This is a preparation regression, not native dependency qualification.
Ruff 0.15.13 lint/format and AST preservation apply to the touched Python files;
the partial scratch checkout still lacks the justfile for full `just fmt`.
The queued #5771 attempt remains unchanged and must not be called passed.

This continues the disposable qualification in #5696 at
`2c5dbaf66729c1c9464166349343bfa9185e48c2`; it does not adopt the candidate.
Original run `42787638375`, job `129732774017`, failed its consumer and format
stages. Its preparation, resolution, Bazel, policy and cargo-deny stages passed.
The retained artifact `13760711675` has SHA256
`456766f917c21d795c83a91df14075ef48dedfe298efbcc9879d164538e2c206`.
The empty final format log does not establish that stage's root cause or success.
All original results and the complete artifact remain unchanged.

The consumer log reports incompatible Syn types: bindgen 0.73.2 resolved Syn
3.0.9 while prettyplease 0.2.37 uses Syn 2.0.119. The upstream
[bindgen v0.73.2 workspace manifest](https://github.com/rust-lang/rust-bindgen/blob/v0.73.2/Cargo.toml)
allows Syn `>=2, <4`. This continuation reuses the single lock edge already
present in #5755 source `5019fc36f636850902d940ad2152cde1c73cb085`, Cargo.lock
Git blob `025813e20504f31d12dae2092a0807a1a4066419`. No other #5755 source is
imported.

The bounded helper accepts only the original generated Cargo.lock SHA256
`c3d1fec8c1291a9689d91c6fda6b7f593e95d1416730b00decf43e9dd31166a0`.
It changes only bindgen 0.73.2's dependency from Syn 3.0.9 to Syn 2.0.119,
checks the parsed lock has no other changes, and requires the exact reviewed
output SHA256
`98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69`.
Package versions, checksums and other edges, including users of Syn 3, remain
unchanged. A different regenerated graph fails closed and needs separate review.

After this selection, the existing workflow must obtain fresh locked
all-features metadata and assert bindgen and prettyplease resolve the same
Syn 2.0.119 package while Syn 3.0.9 remains available for other macros. It then
retains the original mandatory Bazel regeneration/check, seven consumer
packages, no-suppression policy, cargo-deny action, formatting and preserved
vendor implementation checks. The original read-only permissions, exact-head
checkout, action pins, timeouts and always-retained failure artifact remain.
No production manifest, lockfile, security policy or test requirement changes.

Local replay uses the actual retained failed lock and the exact #5755 lock;
changed-input and repeated-application attempts must reject without mutation.
This validates the bounded selection, not native compilation or qualification.
The replay and rejection checks passed, as did shell/YAML/embedded Python syntax,
unchanged-gate comparison and Ruff 0.15.13 lint. Ruff formatting preserved the
complete AST including type comments. Local `just fmt` returned nonzero because
this partial scratch checkout has no justfile; full repository formatting is not
claimed. The graph-guard check rejected the original metadata and accepted a
one-edge structural fixture; that fixture is not a new native Cargo resolution.
Fresh native CI, both lockfiles, consumer results and final formatting are still
required. Dependency security closure, full VERIFY acceptance, registry image
admission and independent scientific benefit remain OPEN/HOLD; missing physical
costs and independent real labels remain null.

## Auth-status discovery diagnostic compatibility

The original #5789 candidate compiled but failed five auth-status cases because
rmcp 3.9.0's `AuthError::DiscoveryRequestFailed` displays only its URL while
retaining the transport/HTTP/redirect cause through `source()`. Upstream
[rmcp-v3.9.0 auth.rs](https://github.com/modelcontextprotocol/rust-sdk/blob/rmcp-v3.9.0/crates/rmcp/src/transport/auth.rs)
and the retained original failure log establish this changed error shape.

Convert the error to anyhow, capture its complete chain for the public diagnostic,
and attach that diagnostic as context to the same original error. This preserves
underlying typed downcasts and source-chain information rather than converting
it to a string-only replacement. The returned outcome is still an error. Request
construction, redirect/issuer checks, timeouts, headers and response processing
are unchanged. Retain every original assertion and the full seven-consumer run.
The other four direct-SDK OAuth tests, three streamable-HTTP cases, Matrix restart
failure and vendor-format conflict remain separate unresolved failures.

Only the exact auth-status source path is added to the disposable preparation
allowlist. Existing pins and refusal of unreviewed paths remain. Local rustfmt
syntax/format check and preparation Ruff checks pass; all five original
preparation tests pass. Full native consumer tests are NOT_RUN locally: this
scratch checkout lacks the Rust workspace/justfile; `just fmt` fails for that
reason. Fresh qualification is required and no five-test improvement is claimed
before those original tests actually run. No dependency, suppression, permission,
production admission, scientific or cost acceptance changes.

## Typed compatibility correction after the original failed run

The #5825 run 42872910595/job 130028537143 completed FAILURE on exact
95b9153068222b63ccc90b7e002b15b43a61406e. All 13 result file hashes were
verified in artifact 13794592813 (1134716 bytes, SHA256
582f1647ce75111762fa928cee83cd9c9568cdd6c5af0dac382f6abc1ffbcefd).
It still ran 810 tests with 797 passed, 13 failed and 9 skipped. The five target
auth-status tests did not improve; FORMAT also failed. Preserve that negative
result and the complete original artifact.

The earlier display-only diagnosis was incorrect: the existing five assertions
require downcast to AuthError::MetadataError and then inspect its reason. They
are not merely checking the public error string. Attach a typed MetadataError
context for source-bearing discovery failures while retaining the original error
underneath. Return HttpError and UrlError unchanged, and leave source-free errors
unchanged. NoAuthorizationSupport retains its original separate handling. In the
frozen RMCP 3.9 error enum, the remaining source-bearing case is
DiscoveryRequestFailed; this also avoids referencing a new variant unavailable
to the original SDK. Public metadata classification is restored without dropping
the new source chain or changing rejection/network policy.

All original assertions and all seven consumer packages remain. Do not claim
this correction fixes the other eight failures or the vendor format conflict.
Local pinned rustfmt syntax/format check and the five preparation tests passed;
full native tests are NOT_RUN locally and just fmt still fails without the
partial checkout's missing justfile. Fresh exact-source native CI is required.
