# codex-arg0

This crate bootstraps the single-executable helper aliases and async entry
point. [src/lib.rs](src/lib.rs) owns dispatch, the invocation-scoped helper
directory and lock, environment setup and runtime lifetime.

## Technical contract

`dispatch_hidden_helper_if_requested` (`src/lib.rs:66`) checks executable
basename and hidden first arguments before ordinary initialization. It routes
the existing apply-patch, Linux sandbox, Unix exec wrapper, exec-server and
filesystem helpers, plus the Windows sandbox helper on that platform. A normal
invocation returns without loading `.env`, making aliases or changing the
environment. Native sealed entry points can call this cut before bootstrap
checks; helper re-execution does not manufacture another daemon/authority role.
Helper behavior and OS enforcement remain owned by the dispatched crates.

`arg0_dispatch` performs ordinary initialization before any worker threads:

1. Load the configured Codex home's `.env`. Keys beginning with `CODEX_`, matched
   case-insensitively, are excluded. Missing/unreadable files and parse errors
   are skipped by the existing loader; `.env` is not an authority source.
2. Prepend the install context's optional package PATH directory, then prepare
   invocation aliases beneath the Codex home's `tmp/arg0` root. Unix uses
   symlinks to the current executable; Windows uses the apply-patch batch route.
   The Unix temporary root is mode 0700. Release builds reject a Codex home
   beneath the system temporary directory.
3. Keep a `TempDir` and locked `.lock` file in `Arg0PathEntryGuard`. Janitor
   cleanup skips directories without a lock or with a held lock. Alias setup
   failure emits a warning and can retain the package PATH without an alias
   guard; it is not reported as successful helper creation.

`arg0_dispatch_or_else` (`src/lib.rs:229`) retains that guard through the entire
async `main_fn`. It starts the `codex-main` thread and Tokio workers with a
16 MiB stack budget. `run_main_with_arg0_guard` releases the aliases only after
the main future completes. Thread/runtime creation errors propagate; a joined
panic is resumed rather than converted into success.

`Arg0DispatchPaths` carries stable self, Linux sandbox and Unix exec-wrapper
paths. Linux prefers the sandbox alias so basename dispatch survives a re-exec,
then falls back to the current executable when necessary. Consumers must keep
the guard alive and use these supplied paths; in a test harness,
`current_exe()` can name the harness rather than the real Codex CLI. This crate
does not provide a general executable resolver or prove that a product binary
was built. A required normal `codex-cli` producer remains a separate build input.

## Development and validation

Keep environment mutation before runtime/thread creation. Preserve the early
hidden-helper cut and guard ownership when changing a binary entry point.
PATH preparation is in `src/lib.rs:186`; runtime/guard retention is at `:260`;
alias construction and stale-directory locking are at `:348` and `:491`.
Platform-conditional branches require their own platform evidence.

From the repository root, the original package command is:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline \
  -p codex-arg0 --test-threads 2 --retries 0 --cargo-profile dev-small
```

The existing inline test module includes
`linux_sandbox_exe_path_prefers_codex_linux_sandbox_alias`,
`package_path_survives_arg0_alias_setup_failure`,
`run_main_with_arg0_guard_keeps_aliases_alive_until_main_returns` and the three
`janitor_*` cases. These exercise owned temporary paths and locks. They do not
replace tests of the actual helper executables, cross-platform enforcement,
normal CLI startup or the complete nineteen-owner release lane.

This manual was source-reviewed against code baseline
`7673ea62fc019f97ad17d205ee1f81f96e0f47a0`. This documentation change ran no
Rust command, helper or product and inherits no previous runtime qualification.
It grants no production authorization.
