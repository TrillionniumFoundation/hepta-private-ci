# Remove pin-utils through its actual parents

The three current Smithy versions use their exact official source archives, with
only the pin-utils dependency and actual pinning sites changed. Loom uses the
official 0.7.3 release. Existing Smithy schema compatibility and the AWS
credentials-login/P-256 patch are preserved.

The source import and actual backport are separate commits. Each crate retains
its original archive checksum, license, original-file bindings and minimal patch.
The final Cargo and Bazel locks are synchronized. All other dependency identities,
checksums and edges match the original baseline.

## Actual validation

The final native invocation of `just test --locked -p codex-aws-auth -p
codex-network-proxy` passed 225 tests, with zero skipped. Earlier scoped
invocations are retained separately; repeated invocations are not extra
independent test cases. Full-workspace `cargo metadata --locked --all-features`
and the official `just bazel-lock-update` succeeded.

The same cargo-deny 0.19.0 command used by CI reports no pin-utils advisory. Its
only remaining error is vodozemac 0.10.0 / RUSTSEC-2026-0451, and its real exit
code remains 1. No advisory, license or audit policy was weakened. Final input
hashes remained stable. This is not a full security-gate pass.

The earlier unsupported Smithy upgrade, rejected unrelated graph drift, original
test runs, first cargo-deny lock-normalization failure and successful final
stable-input validation remain in the raw evidence. The lock normalization was
package-block ordering only, not the initially suspected Windows-edge change.

Official formatting ran after the final tests. Its three Rust-file changes are
import layout only and are retained separately. Tests were not repeated after
formatting. Unmodified official source and licenses were not reformatted.

`MANIFEST.json` binds the actual source, native jobs, lock files and archive.
`native-evidence.tar.gz` retains the original commands, logs, failed attempts,
source/graph reviews, final validation and formatter records. The capsule's
member manifest binds every retained file. This publication starts no new tests,
training or production operation.
