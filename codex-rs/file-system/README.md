# codex-file-system

This crate defines the executor filesystem interface and upward-marker search.
It does not implement a local disk, a remote transport or OS sandbox enforcement.
The concrete filesystem remains owned by the selected execution environment.

## Technical contract

[src/lib.rs](src/lib.rs) exports `ExecutorFileSystem`, whose operations return
`Send` boxed futures with `std::io::Result`. Paths are `PathUri`s. Read/write,
metadata, creation/removal, copy and walk requests carry explicit options and an
optional `FileSystemSandboxContext`. Most follow-symlink options default to
`true`; a caller requiring another policy must select it. Passing `None` is not
evidence that an operation was authorized.

`FileSystemSandboxContext` transports a permission profile, cwd/workspace roots
and platform options. Native permission-path conversion validates the path on
the receiving host. `should_run_in_sandbox` remains true if that conversion
fails, rather than selecting an unsandboxed filesystem. Cwd-dependent relative
globs and project-root permissions retain cwd; `drop_cwd_if_unused` clears cwd
and workspace roots only when those dependencies are absent. Policy data alone
does not prove that a concrete executor enforced it.

`FileSystemReadStream` owns its `Send + 'static` byte stream. The per-chunk
contract is at most 1 MiB. The default `read_file_bounded_authorized` opens one
stream with the supplied sandbox context and accumulates only while its positive
`max_bytes` bound holds. Zero/overflowing bounds are `InvalidInput`; oversized
or overflowing content is `InvalidData`; underlying stream errors propagate.
No partial prefix is returned on failure. The stream-open cut owns authorization
and the immutable handle; concrete implementations must preserve those
semantics. `read_file_text` additionally rejects invalid UTF-8. Ordinary
`read_file` has no automatic whole-file limit from the 1 MiB chunk constant.

Walk types describe entries, recoverable errors and an explicit `truncated`
flag. The published maxima are depth 64, 10,000 directories including root,
50,000 examined entries and 4 MiB estimated response, with 64 bytes overhead
per entry/error. This crate declares the interface/limits; concrete local and
remote walkers must enforce them. A truncated or error-bearing walk is not
proof that every descendant was inspected.

[src/find_up.rs](src/find_up.rs) implements
`find_nearest_ancestor_with_markers` and its native-path counterpart. It searches
from `start` toward root in ancestor/marker input order while buffering at most
256 ordinary metadata probes. Buffered result ordering preserves the nearest
match even when later probes complete first. `NotFound` is a missing marker;
`FindUpErrorPolicy::Propagate` returns the ordered error, while `Ignore` treats
other metadata errors as missing. No marker yields `None`. The native variant
keeps native ancestors until each complete probe is converted to `PathUri`,
preserving opaque native paths rather than guessing a different host's path.

## Development and validation

Review `src/lib.rs:457` for the executor trait and `:485` for its default bounded reader;
`src/find_up.rs:27` / `:54` are the public upward searches. Preserve URI ownership,
single-handle authorization, caller bounds and sandbox error propagation when
changing the interface. Concrete implementations are in
[`../exec-server/src/local_file_system.rs`](../exec-server/src/local_file_system.rs)
and [`../exec-server/src/remote_file_system.rs`](../exec-server/src/remote_file_system.rs).

The original package selection, from the repository root, is:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline \
  -p codex-file-system --test-threads 2 --retries 0 --cargo-profile dev-small
```

The current [Cargo.toml](Cargo.toml) explicitly sets `lib.test = false` and
`doctest = false`; this crate has no independent Rust test target. Selecting it
is not a claim of a positive test count or runtime behavior. Existing consumer
coverage lives in exec-server's `local_file_system_authorized_read_tests.rs`,
`remote_file_system_path_uri_tests.rs`, `tests/file_system/shared.rs` and
`tests/file_system_unix.rs`. Examples include
`stable_handle_read_rejects_parent_symlink_replacement`,
`stable_handle_read_rejects_file_path_identity_aba` and bounded walk/symlink
cases. Changes to this contract need the appropriate original consumer lane,
such as the following separate development command, without filtering away
its original assertions or changing the fixed release-owner set:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline \
  -p codex-exec-server --test-threads 2 --retries 0 --cargo-profile dev-small
```

This manual was source-reviewed against code baseline
`7673ea62fc019f97ad17d205ee1f81f96e0f47a0`. No Rust or consumer test was run
for this documentation change. No earlier runtime qualification transfers;
the interface is not an Asterinas VFS driver or a production Notes/Device grant.
