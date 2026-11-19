# Hepta i18n-config integration provenance

The memory-cell branch at
`1657238edcc0793bc353c931f9ca445ef992315c` recorded an upstream-derived
candidate from MIT-licensed `kellpossible/cargo-i18n` commit
`10e345470d97c9cffb3bc611182f595ad93251bf` and Hepta PR #2976.
That exact candidate remains in Git history.

The integrated source retains the existing 0.4.8 compatibility backport from
`83e1c6fc47bfc7277100534cd0994a547028cb11`, including its public
`CannotPaseI18nToml` variant and three parser regression tests. Its manifest
uses maintained `toml 1.1.8` instead of archived `basic-toml`.
It is not an unchanged copy of the other branch's Rust, README or manifest.
The existing package provenance files and license remain alongside it.

Both branches' maintained-parser objective is retained without a public enum
rename, deletion of parser tests, or downgrade of workspace dependencies.
No Cargo.lock or Bazel lock has been copied from the historical branch.
The combined source still requires ordinary dependency resolution and its
own parser/build/Clippy/qualification checks; this note is not a test receipt.
