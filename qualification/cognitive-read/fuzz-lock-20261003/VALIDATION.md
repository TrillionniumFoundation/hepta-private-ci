# Immutable fuzz dependency inputs

At exact cognitive source `2e0b23f9a1f763df527a691b5ac91e805f3d9439`,
run 37043546301 source artifact 11245491051 contains a successful fuzz compilation
but rejects its newly generated untracked `hepta-cognitive-read/fuzz/Cargo.lock`.
The ZIP SHA-256 `ca6a48106d10b58df7b770ee3e9d1c1d1f6854057ecbdf25da30983108605fd8`,
nested TAR hash and all 194 checksum entries were verified. Its separate strict
and compatibility Clippy gates still fail five paused AuthBus diagnostics.

This repair commits the standalone fuzz workspace's own Cargo.lock and adds
`--locked` to the existing required fuzz check. The main `codex-rs/Cargo.lock`
is unchanged. Qualification still rejects any untracked source input; no cleanup,
ignore rule, source exception or success override conceals generated dependencies.
The nested lock has 33 package rows. All package versions present in the earlier
successful fuzz compilation log match the frozen resolution.

The real gate argv was exercised against small, isolated dependency-free Cargo
fixtures. Before the repair, missing/stale locks were silently created or updated.
After the repair, both fail without changing the lock, and an already frozen
fixture checks successfully with identical input bytes. These are tool-behavior
regressions, not substitute cognitive Rust tests.

Executed validation:

- Actual standalone fuzz `cargo check --offline --locked --all-targets` passed
  against the new lock in a dedicated 55 MiB temporary target.
- All 108 cognitive Python regression tests passed, including the three real
  Cargo lock-enforcement cases; Ruff and diff checks passed.
- `just bazel-lock-update` completed using its own temporary Bazel output/cache;
  `MODULE.bazel.lock` and the protected main Cargo.lock remained byte-identical.
  The temporary Bazel server was shut down and only this task's disposable cache
  was removed. No shared cache was restored or modified.

The existing exact-head and synthetic-merge workflows must supply fresh candidate
receipts. Earlier 287 memory and 226 Agentd passes, including exact-cut recovery,
remain results of the earlier source. They are not promoted by this lock repair.
No full CI, independent acceptance, product activation, deployment or release is
claimed; paused files and unrelated provenance remain unchanged.

Source commit `164199fc256850fcbecca91eed751f72df126c14`, tree
`28ffa036a8b823af70fc1a8ce563219bf0e3e903`, contains the frozen input and gate
repair. The cognitive.read map now uses the already-supported v3 exact-blob mode
with a separate current observation; its original sourceBase at c1f17d21 remains
unchanged historical provenance with the same tree and ancestry checks. All
original source/evidence paths remain covered, with explicit new lock/regression
paths added. Previous observation and flags remain recoverable from the original
map at 2e0b23f9; production, acceptance, activation and release flags are unchanged.
No other module map or history is rewritten to obtain source qualification.
