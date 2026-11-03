# Current secure provider hosted qualification

Source commit: `3645a9c67ee7ff1dae193e372c932e9e3ed1f8b1`.
Workflow run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41674396703

Both jobs completed successfully. This directory preserves the actual artifacts,
including their download digests and input verification receipts. The source retains
4.1.0 zeroization and backports the official 4.0.3 OS randomness to all DH and IV paths.

The native job passed the original pinned D-Bus identity assertions and the complete
12-stage old/new credential recovery sequence on a private real Secret Service. It
observed 17 DH sessions and no Plain sessions; rejection caused one DH request and
no Plain retry. All 15 original `codex-secrets` tests passed with zero skips. The
candidate was statically linked to the pinned native D-Bus client. Before/after
source and binary hashes matched.

The Bazel job ran the original `just bazel-lock-update` and lock checker, the real
`//third_party/dbus:native_identity_test` (1 of 1 executed and passed), and built
`//codex-rs/keyring-store:keyring-store`. The adopted root `MODULE.bazel.lock` is the
exact 1,645,528-byte output, SHA256
`c5b9158e8adffc1642a0f476f383b4753d0822dc092775c20724a5198afe9648`.
Its path provider fact selects `rand` and both cryptographic backend feature sets
retain OS randomness. No advisory or license policy changed.

The follow-up changes only this generated lock, evidence, and the Bazel job's
checkout depth. Bazel generation needs the exact current tree, so a shallow
filtered checkout avoids downloading unrelated repository history; all original
checks and the timeout remain unchanged. Current-head revalidation and global
platform CI remain separate acceptance gates. Earlier local PID-namespace and
socket failures remain in history; this successful hosted result does not rewrite
those observations.
