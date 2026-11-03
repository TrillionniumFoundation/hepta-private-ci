# Follow-up evidence for keyring PR #4711

Tested production source: `29e41072ce0d097acfd59b5ecc1fdb525e45d75e`.
The branch containing this evidence may have a different source tree; the
source-input manifest identifies the exact tested inputs in that commit.

The original all-features, locked cargo-deny check used the same advisory DB
`6c5fedf8ff03c485ed674d8f941e0180f3f72d70` and unchanged deny.toml policy.
Advisory errors fell from 7 to 4; RUSTSEC-2026-0370/0371/0372 are removed.
The remaining errors are RUSTSEC-2024-0449 and RUSTSEC-2026-0318/0319/0387.
Bans, licenses and sources each have zero errors. The full 13,168,206-byte
output is retained losslessly as cargo-deny.log.gz, with both hashes recorded.

The required original `just fix -p codex-keyring-store --locked --offline`
returned zero but reported no matching test targets; it is retained as a no-op,
not evidence of checking the implementation. The explicit original recipe
`just clippy -p codex-keyring-store --lib --locked --offline` then actually
checked the pinned D-Bus provider and codex-keyring-store and passed. The
production source manifest remained unchanged. No tests were rerun after fix.

Real Secret Service replay, native identity, generated Bazel lock adoption and
original platform CI remain required; these policy and Clippy results do not
convert the Draft into production acceptance.
